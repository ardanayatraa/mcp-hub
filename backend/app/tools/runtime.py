"""Execute tools against connected applications. Every call re-checks policy.

Three pipelines share one source client:

* read   - call one reviewed read route and return allowlisted records;
* report - page through a data source's list route, then filter, group and summarize;
* write  - send one reviewed create/update/delete request; the application decides.

Each pipeline takes a ``fetch`` function, so the admin test console runs the same code
on sample data that production runs on live data.
"""

import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from app.capabilities.policy_service import module_for_operation, module_setting, policy_map
from app.config import Settings, get_settings
from app.connectors.auth_profiles import auth_headers
from app.connectors.discovery import connector_secret
from app.connectors.endpoint_policy import dataset_endpoint, pagination_for, reviewed_endpoint
from app.connectors.http_adapter import execute_request, join_url
from app.errors import HubError
from app.ids import as_utc, new_request_id, utcnow
from app.persistence.models import (
    Application,
    Connector,
    ModuleDefinition,
    RestToolMapping,
    ToolDefinition,
)
from app.privacy.envelope import safe_meta
from app.privacy.output_guard import guard_output, guard_receipt
from app.security.budgets import concurrency_slot
from app.security.crypto import decrypt_secret, sign_payload, verify_signed_payload
from app.security.rate_limit import hit
from app.tools import report_engine
from app.tools.definitions import WRITE_TEMPLATES, content_fingerprint, operation_for
from app.tools.rest_mapper import render_path
from app.tools.schema_tools import project_output_schema, validate_arguments, validate_output

SAFE_UPSTREAM_CODES = {"PERMISSION_DENIED", "VALIDATION_FAILED", "NOT_FOUND", "RATE_LIMITED", "SCHEMA_MISMATCH"}
CIRCUIT_CODES = {"UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE", "UPSTREAM_ERROR"}
# Read by the model, which tells the user: say what is missing and where it works instead.
NO_SIGNED_IN_USER = ("Only a signed-in user of the app can read this data, and this request has none "
                     "(the Hub's Try it never has one). Ask from inside the app while signed in.")

Fetch = Callable[..., Awaitable[tuple[int, bytes]]]


@dataclass
class Route:
    """One fixed source call, from a stored mapping or a reviewed manifest route."""

    method: str
    path_template: str
    input_schema: dict
    output_schema: dict
    requires_user_context: bool
    tenant_field: str | None
    safe_query: bool = False
    timeout_ms: int = 5000
    max_payload_bytes: int = 1_048_576
    pagination: dict = field(default_factory=dict)
    error_mapping: dict = field(default_factory=dict)

    @classmethod
    def of(cls, route: dict, mapping: RestToolMapping | None = None, *, timeout_ms: int = 5000) -> "Route":
        return cls(
            method=route["method"], path_template=route["path_template"],
            input_schema=route["input_schema"], output_schema=route["output_schema"],
            requires_user_context=route["requires_user_context"], tenant_field=route["tenant_field"],
            safe_query=route["safe_query"],
            timeout_ms=mapping.timeout_ms if mapping else timeout_ms,
            max_payload_bytes=mapping.max_payload_bytes if mapping else 1_048_576,
            pagination=(mapping.pagination if mapping else pagination_for(route)) or {},
            error_mapping=(mapping.error_mapping if mapping else {}) or {},
        )


@dataclass
class Source:
    connector: Connector
    application: Application
    module: ModuleDefinition
    api_secret: str
    delegation_secret: str


def load_source(db: Session, connector: Connector, application: Application, module: ModuleDefinition,
                settings: Settings) -> Source:
    row = connector_secret(db, connector.id)
    return Source(connector, application, module,
                  decrypt_secret(settings.secret_encryption_key, row.secret_ciphertext),
                  decrypt_secret(settings.secret_encryption_key, row.delegation_ciphertext))


def delegation_from_header(token: str | None, secret: str, app_key: str) -> dict | None:
    """Verify the short-lived user assertion the application gateway signed."""

    if not token:
        return None
    payload = verify_signed_payload(secret, token, audience="mcp-hub")
    if payload.get("app_key") != app_key or not payload.get("tenant_id") or not payload.get("user_ref"):
        raise HubError("PERMISSION_DENIED", "Delegated user context does not match this application", 403)
    return payload


def assert_available(connector: Connector, *, allow_draft: bool = False) -> None:
    if connector.status in {"paused", "archived"} or (connector.status != "active" and not allow_draft):
        raise HubError("CONNECTOR_INACTIVE", "Connector is not active", 409)
    if connector.circuit_open_until is not None and as_utc(connector.circuit_open_until) > utcnow():
        raise HubError("UPSTREAM_UNAVAILABLE", "Connector circuit is open; the application failed repeatedly", 503)


def record_outcome(connector: Connector, settings: Settings, error: HubError | None) -> None:
    """Basic circuit breaker: repeated upstream failures pause calls for a short time."""

    if error is None:
        connector.failure_count = 0
        connector.circuit_open_until = None
    elif error.code in CIRCUIT_CODES:
        connector.failure_count += 1
        if connector.failure_count >= settings.circuit_failure_threshold:
            connector.circuit_open_until = utcnow() + timedelta(seconds=settings.circuit_open_seconds)


async def call_source(source: Source, route: Route, arguments: dict, delegation: dict | None, settings: Settings, *,
                      trace_id: str, write: bool = False, timeout_ms: int | None = None) -> tuple[int, bytes]:
    base_url = source.connector.base_url
    path, remaining = render_path(route.path_template, arguments)
    url = join_url(base_url, path)
    if urlsplit(url).netloc != urlsplit(base_url).netloc:
        raise HubError("SSRF_BLOCKED", "Resolved URL escaped the connector origin", 422)
    base_headers = {"Accept": "application/json", **auth_headers(source.connector.auth_type, source.api_secret),
                    "X-Request-ID": new_request_id()}
    if write:
        # Lets the application de-duplicate; the Hub itself never retries a write.
        base_headers["Idempotency-Key"] = trace_id

    def headers() -> dict[str, str]:
        if delegation is None:
            return base_headers
        # A fresh assertion per attempt: its jti lets the application refuse any replay.
        return {**base_headers, "X-Hub-Assertion": sign_payload(source.delegation_secret, {
            "app_key": source.application.key, "tenant_id": delegation["tenant_id"],
            "user_ref": delegation["user_ref"], "aud": base_url, "jti": secrets.token_urlsafe(18)}, ttl_seconds=60)}
    in_query = route.method in {"GET", "DELETE"}
    status, raw, _elapsed = await execute_request(
        method=route.method, url=url, settings=settings, headers=headers,
        params=remaining if in_query else None, json_body=None if in_query else remaining,
        timeout_ms=min(route.timeout_ms, timeout_ms) if timeout_ms else route.timeout_ms,
        max_bytes=min(route.max_payload_bytes, settings.max_payload_bytes),
        tls_verify=source.connector.tls_verify, retries=2 if route.method == "GET" else 0, write=write)
    return status, raw


def live_fetch(source: Source, route: Route, delegation: dict | None, settings: Settings, trace_id: str,
               *, write: bool = False) -> Fetch:
    async def fetch(arguments: dict, timeout_ms: int | None = None) -> tuple[int, bytes]:
        return await call_source(source, route, arguments, delegation, settings, trace_id=trace_id,
                                 write=write, timeout_ms=timeout_ms)
    return fetch


def sample_fetch(document: dict) -> Fetch:
    payload = json.dumps(document).encode("utf-8")

    async def fetch(arguments: dict, timeout_ms: int | None = None) -> tuple[int, bytes]:
        return 200, payload
    return fetch


def parse_rows(status: int, raw: bytes, route: Route, *, max_rows: int) -> tuple[list[dict], dict]:
    if status == 401:
        raise HubError("UPSTREAM_UNAUTHORIZED", "The connected application rejected the service credential", 401)
    if status == 403:
        raise HubError("PERMISSION_DENIED", "The connected application denied the request", 403)
    if status == 404:
        raise HubError("NOT_FOUND", "The connected application hid or could not find the resource", 404)
    if status == 429:
        raise HubError("RATE_LIMITED", "The connected application rate limited the request", 429)
    if status >= 400:
        code = route.error_mapping.get(str(status), "UPSTREAM_ERROR")
        raise HubError(code, "The connected application returned an error", 504 if code == "UPSTREAM_TIMEOUT" else 502)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubError("SCHEMA_MISMATCH", "Upstream response was not valid JSON", 502) from exc
    if isinstance(document, dict) and document.get("success") is False:
        error = document.get("error") if isinstance(document.get("error"), dict) else {}
        code = error.get("code") if error.get("code") in SAFE_UPSTREAM_CODES else "UPSTREAM_ERROR"
        raise HubError(code, "The connected application rejected the request", 422)
    if not isinstance(document, dict) or "data" not in document:
        raise HubError("SCHEMA_MISMATCH", "Upstream response must use the reviewed JSON envelope", 502)
    data = document.get("data")
    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    if document.get("success") is not True or not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise HubError("SCHEMA_MISMATCH", "Upstream response records are invalid", 502)
    if len(data) > max_rows:
        raise HubError("PAYLOAD_TOO_LARGE", "Upstream response exceeds the record limit", 413)
    return data, meta


def apply_tenant(rows: list[dict], meta: dict, tenant_field: str | None, tenant_id: str) -> tuple[list[dict], dict]:
    """Keep only rows the source labelled with the caller's tenant, then drop the label."""

    if not tenant_field or any(not isinstance(row.get(tenant_field), str) for row in rows):
        raise HubError("SCHEMA_MISMATCH", "Upstream tenant context is missing", 502)
    kept = [{key: value for key, value in row.items() if key != tenant_field}
            for row in rows if row[tenant_field] == tenant_id]
    if len(kept) != len(rows):
        meta = {key: value for key, value in meta.items() if key not in {"total_count", "next_cursor"}}
        meta["coverage"] = "partial"
    return kept, meta


def envelope(data, meta: dict, trace_id: str) -> dict:
    return {"success": True, "data": data, "meta": safe_meta(meta), "trace_id": trace_id}


async def read_pipeline(db: Session, *, module: ModuleDefinition, route: Route, allow_fields: list[str],
                        output_schema: dict, arguments: dict, fetch: Fetch, tenant_id: str | None,
                        settings: Settings, trace_id: str) -> dict:
    max_rows = min(module.max_page_size, settings.max_records)
    arguments = dict(arguments)
    limit_parameter = route.pagination.get("limit_parameter", "limit")
    if isinstance(arguments.get(limit_parameter), int):
        arguments[limit_parameter] = max(1, min(arguments[limit_parameter], max_rows))
    status, raw = await fetch(arguments)
    rows, meta = parse_rows(status, raw, route, max_rows=max_rows)
    if route.requires_user_context:
        rows, meta = apply_tenant(rows, meta, route.tenant_field, tenant_id)
    minimized = guard_output(rows, allow_fields, policy_map(db, module.id))
    validate_output(project_output_schema(route.output_schema, allow_fields), minimized)
    validate_output(output_schema, minimized)
    return envelope(minimized, meta, trace_id)


def _pushdown(filters: list[report_engine.Filter], route: Route) -> dict:
    """Send exact-match filters the source route accepts as enum or typed parameters."""

    properties = route.input_schema.get("properties", {})
    arguments = {}
    for item in filters:
        spec = properties.get(item.field)
        if item.op != "eq" or spec is None or item.field in route.pagination.values() or item.value is None:
            continue
        if spec.get("type") == "string" and "enum" not in spec:
            continue  # Free-text matching rules may differ at the source; filter locally.
        if not list(Draft202012Validator(spec).iter_errors(item.value)):
            arguments[item.field] = item.value
    return arguments


async def report_pipeline(db: Session, *, module: ModuleDefinition, route: Route, spec: report_engine.ReportSpec,
                          fetch: Fetch, tenant_id: str | None, settings: Settings, trace_id: str,
                          label: str) -> dict:
    fields = report_engine.source_fields(route.output_schema, policy_map(db, module.id))
    report_engine.validate_spec(spec, fields)
    base = _pushdown(spec.filters, route)
    limit_parameter = route.pagination.get("limit_parameter")
    cursor_parameter = route.pagination.get("cursor_parameter")
    page_size = min(module.max_page_size, settings.max_records,
                    route.input_schema.get("properties", {}).get(limit_parameter or "", {}).get("maximum", 50))
    deadline = time.monotonic() + settings.report_timeout_seconds
    rows: list[dict] = []
    first_meta = last_meta = None
    cursor, pages, truncated = None, 0, False
    while True:
        arguments = dict(base)
        if limit_parameter:
            arguments[limit_parameter] = page_size
        if cursor is not None:
            arguments[cursor_parameter] = cursor
        validate_arguments(route.input_schema, arguments)
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            if not pages:
                raise HubError("UPSTREAM_TIMEOUT", "The connected application timed out", 504)
            truncated = True
            break
        try:
            status, raw = await fetch(arguments, timeout_ms=remaining_ms)
        except HubError as exc:
            if pages and exc.code in {"UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE"}:
                truncated = True  # Keep what was read; the answer says it is partial.
                break
            raise
        page, meta = parse_rows(status, raw, route,
                                max_rows=page_size if limit_parameter else min(module.max_page_size, settings.max_records))
        if route.requires_user_context:
            page, meta = apply_tenant(page, meta, route.tenant_field, tenant_id)
        safe_meta(meta)
        pages += 1
        first_meta = first_meta or meta
        last_meta = meta
        rows.extend(page)
        next_cursor = meta.get("next_cursor") if meta.get("has_more") else None
        if len(rows) >= settings.report_max_records:
            truncated = bool(next_cursor) or len(rows) > settings.report_max_records
            break
        if not next_cursor or not cursor_parameter or next_cursor == cursor:
            break
        cursor = next_cursor
    rows = rows[:settings.report_max_records]
    coverage = "partial" if truncated or last_meta.get("coverage") == "partial" else "complete"
    meta = {**safe_meta(first_meta), "coverage": coverage}
    meta.pop("has_more", None)
    meta.pop("next_cursor", None)
    meta.pop("total_count", None)
    zone = ZoneInfo(meta["timezone"])
    safe_rows, hidden = report_engine.prepare_rows(rows, fields)
    result = report_engine.run_report(safe_rows, spec, fields, zone=zone)
    if hidden:
        result["notes"] = sorted({*result["notes"], f"{hidden} value(s) were hidden by the privacy filter."})
    summary = report_engine.summarize(result, label=label, scanned=len(rows), coverage=coverage,
                                      truncated=truncated, filtered=bool(spec.filters))
    meta.update({"source": module.module_key, "records_read": len(rows), "pages": pages, "truncated": truncated})
    data = {key: result[key] for key in ("mode", "columns", "rows", "totals", "groups")}
    return {"success": True, "data": data, "summary": summary, "chart": report_engine.chart_hint(result),
            "notes": result["notes"], "meta": meta, "trace_id": trace_id}


async def write_pipeline(*, route: Route, operation: str, allow_fields: list[str], output_schema: dict,
                         arguments: dict, fetch: Fetch, tenant_id: str, trace_id: str) -> dict:
    status, raw = await fetch(arguments)
    rows, meta = parse_rows(status, raw, route, max_rows=50)
    kept, _ = apply_tenant(rows, {}, route.tenant_field, tenant_id)
    if len(kept) != len(rows):
        raise HubError("SCHEMA_MISMATCH", "The application's receipt does not match the user context", 502)
    receipt = guard_receipt(kept, allow_fields)
    validate_output(output_schema, receipt)
    out_meta = {"operation": operation, "as_of": utcnow().isoformat(), "contains_personal_data": False}
    if type(meta.get("requires_confirmation")) is bool:
        out_meta["requires_confirmation"] = meta["requires_confirmation"]
    return {"success": True, "data": receipt, "meta": out_meta, "trace_id": trace_id}


def saved_report_spec(tool: ToolDefinition, arguments: dict) -> report_engine.ReportSpec:
    saved = report_engine.parse_spec(tool.report_spec or {}, report_engine.SavedReport)
    extra = arguments.get("filters") or []
    if extra and not saved.allow_filters:
        raise HubError("VALIDATION_FAILED", "This report does not accept extra filters", 422)
    data = saved.model_dump(exclude={"allow_filters"}, exclude_none=True)
    data["filters"] = data.get("filters", []) + list(extra)
    if "limit" in arguments:
        data["limit"] = arguments["limit"]
    return report_engine.parse_spec(data)


def source_label(application: Application, module: ModuleDefinition) -> str:
    return f"{application.name} · {module.name}"


async def execute_tool(db: Session, *, tool: ToolDefinition, arguments: dict, actor_ref: str,
                       delegation_header: str | None, trace_id: str, settings: Settings | None = None) -> dict:
    """Run a published tool for an MCP caller."""

    settings = settings or get_settings()
    connector = db.get(Connector, tool.connector_id)
    application = db.get(Application, connector.app_id) if connector else None
    mapping = db.get(RestToolMapping, tool.mapping_id)
    if connector is None or application is None or mapping is None:
        raise HubError("NOT_FOUND", "Tool binding is not available", 404)
    if tool.status != "published":
        raise HubError("TOOL_NOT_PUBLISHED", "Tool is not published", 403)
    assert_available(connector)
    hit(f"tool:{actor_ref}:{tool.mcp_name}", settings.tool_rate_limit, settings.tool_rate_window_seconds)
    operation = operation_for(tool.template)
    module = module_for_operation(db, application.id, tool.module_key, operation)
    if tool.content_hash != content_fingerprint(tool, mapping, module):
        raise HubError("CONFLICT", "The source contract changed; test and publish this tool again", 409)
    validate_arguments(tool.input_schema, arguments)
    route_definition = reviewed_endpoint(module, mapping, None if tool.template == "report" else arguments)
    route = Route.of(route_definition, mapping)
    if tool.template in WRITE_TEMPLATES and route_definition["kind"] != "write":
        raise HubError("PERMISSION_DENIED", "Write tools must use a reviewed write route", 403)
    if tool.template not in WRITE_TEMPLATES and route_definition["kind"] != "read":
        raise HubError("PERMISSION_DENIED", "Read tools must use a reviewed read route", 403)
    if mapping.method == "POST" and tool.template not in WRITE_TEMPLATES and not mapping.safe_query:
        raise HubError("VALIDATION_FAILED", "This mapping is not an approved read-only query", 422)
    source = load_source(db, connector, application, module, settings)
    delegation = delegation_from_header(delegation_header, source.delegation_secret, application.key)
    if route.requires_user_context and delegation is None:
        raise HubError("PERMISSION_DENIED", NO_SIGNED_IN_USER, 403)
    tenant_id = delegation["tenant_id"] if delegation else None
    fetch = live_fetch(source, route, delegation, settings, trace_id, write=tool.template in WRITE_TEMPLATES)
    error = None
    try:
        with concurrency_slot(f"tool:{tool.id}", settings.tool_concurrency):
            if tool.template == "report":
                return await report_pipeline(db, module=module, route=route, spec=saved_report_spec(tool, arguments),
                                             fetch=fetch, tenant_id=tenant_id, settings=settings, trace_id=trace_id,
                                             label=source_label(application, module))
            if tool.template in WRITE_TEMPLATES:
                return await write_pipeline(route=route, operation=operation,
                                            allow_fields=tool.output_policy.get("allow_fields", []),
                                            output_schema=tool.output_schema, arguments=arguments, fetch=fetch,
                                            tenant_id=tenant_id, trace_id=trace_id)
            return await read_pipeline(db, module=module, route=route,
                                       allow_fields=tool.output_policy.get("allow_fields", []),
                                       output_schema=tool.output_schema, arguments=arguments, fetch=fetch,
                                       tenant_id=tenant_id, settings=settings, trace_id=trace_id)
    except HubError as exc:
        error = exc
        raise
    finally:
        record_outcome(connector, settings, error)


def report_route(db: Session, module: ModuleDefinition, connector: Connector) -> Route:
    route = dataset_endpoint(module, module_setting(db, module).report_endpoint)
    if route is None:
        raise HubError("NOT_SUPPORTED", "This data source has no list route that reports can read", 422)
    return Route.of(route, timeout_ms=connector.timeout_ms)


def resolve_source_key(application: Application, value) -> str:
    """Accept 'orders', 'app_key.orders' or 'app_key:orders' (models write both)."""

    if not isinstance(value, str) or not 1 <= len(value) <= 130:
        raise HubError("VALIDATION_FAILED", "source must name a data source from list_data_sources", 422)
    for prefix in (application.key + ".", application.key + ":"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


async def run_report_for_caller(db: Session, *, application: Application, connector: Connector, arguments: dict,
                                actor_ref: str, delegation_header: str | None, trace_id: str,
                                settings: Settings | None = None) -> dict:
    """The built-in run_report tool: any enabled data source, any allowed spec."""

    settings = settings or get_settings()
    assert_available(connector)
    hit(f"tool:{actor_ref}:run_report", settings.tool_rate_limit, settings.tool_rate_window_seconds)
    module = module_for_operation(db, application.id, resolve_source_key(application, arguments.get("source")), "read")
    route = report_route(db, module, connector)
    spec = report_engine.parse_spec({key: value for key, value in arguments.items() if key != "source"})
    source = load_source(db, connector, application, module, settings)
    delegation = delegation_from_header(delegation_header, source.delegation_secret, application.key)
    if route.requires_user_context and delegation is None:
        raise HubError("PERMISSION_DENIED", NO_SIGNED_IN_USER, 403)
    error = None
    try:
        with concurrency_slot(f"builtin:{application.id}:run_report", settings.tool_concurrency):
            return await report_pipeline(db, module=module, route=route, spec=spec,
                                         fetch=live_fetch(source, route, delegation, settings, trace_id),
                                         tenant_id=delegation["tenant_id"] if delegation else None,
                                         settings=settings, trace_id=trace_id, label=source_label(application, module))
    except HubError as exc:
        error = exc
        raise
    finally:
        record_outcome(connector, settings, error)
