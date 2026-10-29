"""Create, test, publish and manage MCP tools from templates. Admins never write code.

Lifecycle: draft -> (passing test) -> published <-> disabled. Editing a live tool takes
it offline until it is tested and published again. A source contract change marks
tools as needing a new test; publishing after that test re-binds them.
Explicitly source-managed connectors instead generate validated mappings from the
application's saved grants and cannot be edited through the manual workflow.
"""

import re
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1.configuration import ToolChanges, ToolConfiguration, checked
from app.capabilities.policy_service import module_setting, policy_map
from app.config import Settings
from app.connectors.discovery import discover_capabilities
from app.connectors.endpoint_policy import (
    PAGE_PARAMETERS,
    dataset_endpoint,
    find_endpoint,
    is_dataset_candidate,
    module_endpoints,
    pagination_for,
    reviewed_endpoint,
)
from app.connectors.registry import get_connector_bundle
from app.connectors.ssrf_guard import validate_destination
from app.errors import HubError
from app.ids import as_utc, new_id, new_trace_id, utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    ModuleDefinition,
    RestToolMapping,
    ServiceIdentity,
    ToolDefinition,
    ToolTestRun,
)
from app.privacy.output_guard import AI_SAFE, guard_output, guard_receipt
from app.privacy.pii_inspector import tree_contains_pii
from app.security.audit import record_audit
from app.security.authorization import allowed_app_ids, is_sensitive_path, require_app_access
from app.security.clients import READ_SCOPE, WRITE_SCOPE, Caller
from app.tools import catalog, memory, report_engine
from app.tools.definitions import TEMPLATES, WRITE_TEMPLATES, content_fingerprint, operation_for
from app.tools.runtime import (
    Route,
    assert_available,
    delegation_from_header,
    live_fetch,
    load_source,
    read_pipeline,
    record_outcome,
    report_pipeline,
    report_route,
    resolve_source_key,
    sample_fetch,
    saved_report_spec,
    source_label,
    write_pipeline,
)
from app.tools.schema_tools import (
    clean_description,
    mcp_name_for,
    project_output_schema,
    require_tool_key,
    validate_arguments,
    validate_input_schema,
    validate_output,
    validate_output_schema,
    validate_path_template,
)

ERROR_CATEGORIES = {"400": {"VALIDATION_FAILED"}, "408": {"UPSTREAM_TIMEOUT"}, "422": {"VALIDATION_FAILED", "SCHEMA_MISMATCH"},
                    "500": {"UPSTREAM_ERROR"}, "502": {"UPSTREAM_ERROR", "UPSTREAM_UNAVAILABLE"},
                    "503": {"UPSTREAM_UNAVAILABLE"}, "504": {"UPSTREAM_TIMEOUT"}}
DATE_HINT = re.compile(r"(?:_at|_on|date|time|day|timestamp)$")
CANARY_EMAIL = "test.canary@example.com"
CANARY_NUMBER = 3201010101010001


@dataclass
class Built:
    tool_key: str
    title: str | None
    description: str
    route: dict
    input_schema: dict
    output_schema: dict
    allow_fields: list[str]
    report_spec: dict | None
    risk: str
    mapping: dict


def _module(db: Session, application: Application, module_key: str) -> ModuleDefinition:
    module = db.scalar(select(ModuleDefinition).where(ModuleDefinition.app_id == application.id,
                                                      ModuleDefinition.module_key == module_key))
    if module is None:
        raise HubError("VALIDATION_FAILED", "Data source is not in the discovered contract", 422)
    return module


def _visible_fields(db: Session, module: ModuleDefinition) -> set[str]:
    return {name for name, classification in policy_map(db, module.id).items()
            if classification in AI_SAFE and not is_sensitive_path(name)}


def _tool_key(application: Application, raw: str) -> str:
    raw = (raw or "").strip()
    return require_tool_key(raw if raw.startswith(application.key + ".") else f"{application.key}.{raw}")


def _title(raw: str | None) -> str | None:
    text = " ".join((raw or "").split())[:120]
    if not text:
        return None
    if tree_contains_pii(text) or any(token in text.lower() for token in ("ignore previous", "system prompt", "<|")):
        raise HubError("VALIDATION_FAILED", "Tool title was rejected", 422)
    return text


def _default_description(template: str, module: ModuleDefinition, application: Application) -> str:
    if template == "report":
        return f"Summarize {module.name} records from {application.name}."
    if template in WRITE_TEMPLATES:
        return f"{template.capitalize()} a {module.name} record in {application.name}."
    return f"Read {module.name} records from {application.name}."


def _resolve_route(module: ModuleDefinition, template: str, method: str | None, path: str, preferred: str | None) -> dict:
    if template == "report":
        if path:
            route = find_endpoint(module, method or "GET", path)
            if route is None or not is_dataset_candidate(route):
                raise HubError("VALIDATION_FAILED", "Reports need a reviewed list route of this data source", 422)
            return route
        route = dataset_endpoint(module, preferred)
        if route is None:
            raise HubError("VALIDATION_FAILED", "This data source has no list route that reports can read", 422)
        return route
    wanted = "write" if template in WRITE_TEMPLATES else "read"
    candidates = [route for route in module_endpoints(module) if route["kind"] == wanted
                  and (wanted == "read" or route["operation"] == template)]
    if path:
        matches = [route for route in module_endpoints(module) if route["path_template"] == path
                   and (method is None or route["method"] == method)]
        if not matches:
            raise HubError("PERMISSION_DENIED", "Endpoint is not in the source-reviewed allowlist", 403)
        route = matches[0]
    elif len(candidates) == 1:
        route = candidates[0]
    else:
        raise HubError("VALIDATION_FAILED", "Choose one of the data source's reviewed endpoints", 422)
    if route not in candidates:
        expected = f"a {template} route" if wanted == "write" else "a read route"
        raise HubError("VALIDATION_FAILED", f"This template needs {expected} of the data source", 422)
    return route


def _check_pagination(pagination: dict, schema: dict) -> dict:
    if not isinstance(pagination, dict) or not set(pagination) <= {"limit_parameter", "cursor_parameter"}:
        raise HubError("VALIDATION_FAILED", "Pagination mapping is invalid", 422)
    properties = schema.get("properties", {})
    for option, name in pagination.items():
        expected = "integer" if option == "limit_parameter" else "string"
        if not isinstance(name, str) or properties.get(name, {}).get("type") != expected:
            raise HubError("VALIDATION_FAILED", "Pagination parameters must be declared inputs of the right type", 422)
    return pagination


def _check_error_mapping(mapping: dict) -> dict:
    if not isinstance(mapping, dict) or any(code not in ERROR_CATEGORIES or value not in ERROR_CATEGORIES[code]
                                            for code, value in mapping.items()):
        raise HubError("VALIDATION_FAILED", "Upstream error mapping is outside the approved error categories", 422)
    return mapping


def _build(db: Session, application: Application, module: ModuleDefinition, data: dict) -> Built:
    """Validate a tool configuration against the current source contract and field policy."""

    template = data.get("template") or "read"
    if template not in TEMPLATES:
        raise HubError("VALIDATION_FAILED", "Unknown tool template", 422)
    setting = module_setting(db, module)
    route = _resolve_route(module, template, data.get("method"), data.get("path_template") or "", setting.report_endpoint)
    for key in ("requires_user_context", "tenant_field", "safe_query"):
        if data.get(key) is not None and data[key] != route[key]:
            raise HubError("POLICY_LOCKED", "Mapping cannot weaken source authorization requirements", 422)
    risk = "write" if template in WRITE_TEMPLATES else "read_only"
    if data.get("risk") not in (None, risk):
        raise HubError("VALIDATION_FAILED", f"Risk for this template must be {risk}", 422)
    report_spec = None
    if template == "report":
        saved = report_engine.parse_spec(data.get("report") or {}, report_engine.SavedReport)
        fields = report_engine.source_fields(route["output_schema"], policy_map(db, module.id))
        report_engine.validate_spec(saved, fields)
        report_spec = saved.model_dump(exclude_none=True)
        input_schema = catalog.report_tool_input(saved.allow_filters)
        allow_fields, output_schema = [], {}
        pagination = pagination_for(route)
    else:
        input_schema = validate_input_schema(data.get("input_schema") or route["input_schema"])
        source_input = route["input_schema"]
        if not set(input_schema.get("properties", {})) <= set(source_input.get("properties", {})):
            raise HubError("POLICY_LOCKED", "Input parameters are outside the reviewed source route", 422)
        for name in source_input.get("required", []):
            if name not in input_schema.get("required", []):
                raise HubError("VALIDATION_FAILED", f"Parameter '{name}' is required by the source route", 422)
        validate_path_template(route["path_template"], input_schema)
        route_fields = list(route["output_schema"]["items"]["properties"])
        if template in WRITE_TEMPLATES:
            allow_fields = list(data.get("allow_fields") or route_fields)
            if not set(allow_fields) <= set(route_fields) or any(is_sensitive_path(name) for name in allow_fields):
                raise HubError("POLICY_LOCKED", "Receipt fields must come from the source route", 422)
            max_items = 50
            pagination = {}
        else:
            visible = _visible_fields(db, module)
            allow_fields = list(data.get("allow_fields") or [name for name in route_fields if name in visible])
            if not allow_fields:
                raise HubError("VALIDATION_FAILED", "At least one output field must be visible to AI", 422)
            for name in allow_fields:
                if name not in route_fields or name not in visible:
                    raise HubError("POLICY_LOCKED", f"Field '{name}' is not a visible output of this route", 422)
            max_items = module.max_page_size
            pagination = data.get("pagination")
            if pagination:
                _check_pagination(pagination, input_schema)
            else:
                pagination = {option: name for option, name in pagination_for(route).items()
                              if name in input_schema.get("properties", {})}
        output_schema = validate_output_schema(
            data.get("output_schema") or project_output_schema(route["output_schema"], allow_fields), allow_fields, max_items)
    timeout_ms = int(data.get("timeout_ms") or 5000)
    max_payload = int(data.get("max_payload_bytes") or 1_048_576)
    if not 100 <= timeout_ms <= 30000 or not 1024 <= max_payload <= 1_048_576:
        raise HubError("VALIDATION_FAILED", "Timeout or response size limit is out of range", 422)
    return Built(
        tool_key=_tool_key(application, data.get("tool_key") or ""),
        title=_title(data.get("title")),
        description=clean_description(data.get("description") or _default_description(template, module, application)),
        route=route, input_schema=input_schema, output_schema=output_schema, allow_fields=allow_fields,
        report_spec=report_spec, risk=risk,
        mapping={"method": route["method"], "path_template": route["path_template"], "timeout_ms": timeout_ms,
                 "max_payload_bytes": max_payload, "safe_query": route["safe_query"],
                 "requires_user_context": route["requires_user_context"], "tenant_field": route["tenant_field"],
                 "pagination": pagination, "error_mapping": _check_error_mapping(data.get("error_mapping") or {}),
                 "audit_level": data.get("audit_level") or "standard"},
    )


def _apply(tool: ToolDefinition, mapping: RestToolMapping, built: Built) -> None:
    tool.title = built.title
    tool.description = built.description
    tool.input_schema = built.input_schema
    tool.output_schema = built.output_schema
    tool.output_policy = {"allow_fields": built.allow_fields}
    tool.report_spec = built.report_spec
    tool.risk = built.risk
    for key, value in built.mapping.items():
        setattr(mapping, key, value)


def _current_payload(tool: ToolDefinition, mapping: RestToolMapping) -> dict:
    payload = {"template": tool.template, "tool_key": tool.tool_key, "title": tool.title or "",
               "description": tool.description, "method": mapping.method, "path_template": mapping.path_template,
               "timeout_ms": mapping.timeout_ms, "max_payload_bytes": mapping.max_payload_bytes,
               "pagination": mapping.pagination, "error_mapping": mapping.error_mapping,
               "audit_level": mapping.audit_level}
    if tool.template == "report":
        payload["report"] = tool.report_spec
    else:
        payload.update({"input_schema": tool.input_schema, "output_schema": tool.output_schema,
                        "allow_fields": tool.output_policy.get("allow_fields", [])})
    return payload


def _scoped(db: Session, admin: AdminUser, tool: ToolDefinition) -> tuple[Connector, Application, RestToolMapping, ModuleDefinition]:
    connector, application = get_connector_bundle(db, tool.connector_id)
    require_app_access(db, admin, application.id)
    mapping = db.get(RestToolMapping, tool.mapping_id)
    if mapping is None:
        raise HubError("NOT_FOUND", "Tool route was not found", 404)
    return connector, application, mapping, _module(db, application, tool.module_key)


def _audit(db: Session, admin: AdminUser, action: str, application: Application, tool: ToolDefinition, **extra) -> None:
    record_audit(db, action=action, actor_ref=f"admin:{admin.id}", result=extra.pop("result", "success"),
                 app_key=application.key, module_key=tool.module_key, tool_key=tool.tool_key,
                 environment=application.environment, **extra)


def _passing_test(db: Session, tool: ToolDefinition, fingerprint: str) -> ToolTestRun | None:
    rows = db.scalars(select(ToolTestRun).where(ToolTestRun.tool_id == tool.id, ToolTestRun.passed.is_(True),
                                               ToolTestRun.content_hash == fingerprint)
                      .order_by(ToolTestRun.created_at.desc()))
    return next((row for row in rows if all((row.case_results or {}).values())), None)


def require_manual_tools(connector: Connector) -> None:
    if connector.connector_type == "source_managed":
        raise HubError("POLICY_LOCKED", "Manage models, fields and operations in the connected application", 409)


def sync_source_tools(db: Session, connector: Connector, application: Application,
                      modules: list[tuple[ModuleDefinition, str]]) -> None:
    """Generate reviewed routes from saved source grants, with no second permission setup.

    Only explicitly trusted source-managed connectors use this path. Schemas go through
    the same mapping/privacy validator as manual tools. Sync never calls business routes.
    """
    existing = list(db.scalars(select(ToolDefinition).where(ToolDefinition.connector_id == connector.id,
                                                            ToolDefinition.status != "archived")
                               .order_by(ToolDefinition.created_at.desc())))
    wanted = set()
    changed = False
    for module, change in modules:
        if change == "removed":
            continue
        setting = module_setting(db, module)
        operations = module.manifest_json["enableable_operations"]
        if setting.enabled != bool(operations) or setting.operations_enabled != operations:
            setting.enabled = bool(operations)
            setting.operations_enabled = operations
            setting.policy_version += 1
            changed = True
        setting.report_endpoint = None
        for route in module_endpoints(module):
            template = route["operation"] if route["kind"] == "write" else "read"
            if operation_for(template) not in operations:
                continue
            built = _build(db, application, module, {"template": template, "tool_key": route["tool_key"],
                           "description": route["description"], "method": route["method"],
                           "path_template": route["path_template"], "timeout_ms": connector.timeout_ms})
            tool = next((row for row in existing if row.tool_key == built.tool_key), None)
            tool_changed = False
            if tool is None:
                mapping = RestToolMapping(id=new_id(), connector_id=connector.id, **built.mapping)
                tool = ToolDefinition(id=new_id(), tool_key=built.tool_key,
                                      mcp_name=mcp_name_for(built.tool_key, application.environment),
                                      version="1.0.0", connector_id=connector.id, mapping_id=mapping.id,
                                      module_key=module.module_key, template=template, owner_id=connector.id,
                                      status="draft", content_hash="")
                _apply(tool, mapping, built)
                db.add_all([mapping, tool])
                db.flush()
                tool_changed = True
            else:
                mapping = db.get(RestToolMapping, tool.mapping_id)
                if mapping is None:
                    raise HubError("SCHEMA_MISMATCH", "Source tool mapping was not found", 422)
                tool.template = template
                _apply(tool, mapping, built)
                if tool.content_hash != content_fingerprint(tool, mapping, module):
                    tool.version = _next_version(db, tool)
                    tool_changed = True
            wanted.add(tool.id)
            if tool.status != "published":
                tool_changed = True
            for old in existing:
                if old.id != tool.id and old.mcp_name == tool.mcp_name and old.status == "published":
                    old.status = "disabled"
            db.flush()
            tool.status = "published"
            tool.approved_by = None
            tool.policy_version = setting.policy_version
            tool.content_hash = content_fingerprint(tool, mapping, module)
            if tool_changed:
                tool.updated_at = utcnow()
                changed = True
    for tool in existing:
        if tool.id not in wanted and tool.status != "disabled":
            tool.status = "disabled"
            tool.updated_at = utcnow()
            changed = True
    if changed:
        record_audit(db, action="connector.source_sync", actor_ref=f"source:{connector.id}", result="success",
                     app_key=application.key, environment=application.environment, trace_id=new_trace_id())


def tool_view(db: Session, tool: ToolDefinition) -> dict:
    connector = db.get(Connector, tool.connector_id)
    application = db.get(Application, connector.app_id) if connector else None
    mapping = db.get(RestToolMapping, tool.mapping_id)
    module = db.scalar(select(ModuleDefinition).where(ModuleDefinition.app_id == application.id,
                                                      ModuleDefinition.module_key == tool.module_key)) if application else None
    fingerprint = content_fingerprint(tool, mapping, module) if mapping and module else None
    last = db.scalar(select(ToolTestRun).where(ToolTestRun.tool_id == tool.id).order_by(ToolTestRun.created_at.desc()).limit(1))
    return {
        "id": tool.id, "tool_key": tool.tool_key, "mcp_name": tool.mcp_name, "title": tool.title,
        "display_title": catalog.tool_title(tool), "description": tool.description, "template": tool.template,
        "operation": operation_for(tool.template), "version": tool.version, "status": tool.status,
        "connector_id": tool.connector_id, "app_id": application.id if application else None,
        "app_key": application.key if application else None, "app_name": application.name if application else None,
        "environment": application.environment if application else None,
        "source_managed": connector.connector_type == "source_managed" if connector else False,
        "module_key": tool.module_key, "module_name": module.name if module else tool.module_key,
        "method": mapping.method if mapping else None, "path_template": mapping.path_template if mapping else None,
        "input_schema": tool.input_schema, "output_schema": tool.output_schema, "output_policy": tool.output_policy,
        "allow_fields": tool.output_policy.get("allow_fields", []), "report": tool.report_spec,
        "timeout_ms": mapping.timeout_ms if mapping else None,
        "max_payload_bytes": mapping.max_payload_bytes if mapping else None,
        "pagination": mapping.pagination if mapping else {}, "error_mapping": mapping.error_mapping if mapping else {},
        "audit_level": mapping.audit_level if mapping else None,
        "requires_user_context": mapping.requires_user_context if mapping else None,
        "tenant_field": mapping.tenant_field if mapping else None, "safe_query": mapping.safe_query if mapping else None,
        "risk": tool.risk, "approved_by": tool.approved_by, "content_hash": tool.content_hash,
        "stale": tool.status == "published" and fingerprint is not None and tool.content_hash != fingerprint,
        "tested": fingerprint is not None and _passing_test(db, tool, fingerprint) is not None,
        "last_test": {"passed": last.passed, "mode": last.mode, "error_code": last.error_code,
                      "created_at": as_utc(last.created_at).isoformat(), "current": last.content_hash == fingerprint}
        if last else None,
        "mcp_tool": catalog.mcp_tool(tool, application.name).model_dump(by_alias=True, exclude_none=True) if application else None,
        "created_at": as_utc(tool.created_at).isoformat(),
        "updated_at": as_utc(tool.updated_at).isoformat() if tool.updated_at else None,
    }


def list_tools(db: Session, admin: AdminUser, *, include_archived: bool = False) -> list[dict]:
    query = (select(ToolDefinition).join(Connector, Connector.id == ToolDefinition.connector_id)
             .order_by(ToolDefinition.created_at.desc()))
    allowed = allowed_app_ids(db, admin)
    if allowed is not None:
        query = query.where(Connector.app_id.in_(allowed))
    if not include_archived:
        query = query.where(ToolDefinition.status != "archived")
    # Retired source grants remain in audit/history, never in the current catalog.
    query = query.where(or_(Connector.connector_type != "source_managed", ToolDefinition.status == "published"))
    return [tool_view(db, tool) for tool in db.scalars(query)]


def create_tool(db: Session, admin: AdminUser, payload: dict) -> dict:
    data = checked(ToolConfiguration, payload)
    connector, application = get_connector_bundle(db, data["connector_id"])
    require_app_access(db, admin, application.id)
    require_manual_tools(connector)
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot get new tools", 409)
    module = _module(db, application, data["module_key"])
    built = _build(db, application, module, data)
    if db.scalar(select(ToolDefinition.id).where(ToolDefinition.connector_id == connector.id,
                                                 ToolDefinition.tool_key == built.tool_key)):
        raise HubError("CONFLICT", "A tool with this name already exists", 409)
    now = utcnow()
    mapping = RestToolMapping(id=new_id(), connector_id=connector.id, **built.mapping)
    tool = ToolDefinition(
        id=new_id(), tool_key=built.tool_key, mcp_name=mcp_name_for(built.tool_key, application.environment),
        version="1.0.0", connector_id=connector.id, mapping_id=mapping.id, module_key=module.module_key,
        template=data["template"], title=built.title, description=built.description,
        input_schema=built.input_schema, output_schema=built.output_schema,
        output_policy={"allow_fields": built.allow_fields}, report_spec=built.report_spec, risk=built.risk,
        status="draft", content_hash="", policy_version=module_setting(db, module).policy_version,
        owner_id=admin.id, created_at=now, updated_at=now,
    )
    db.add(mapping)
    db.add(tool)
    db.flush()
    tool.content_hash = content_fingerprint(tool, mapping, module)
    _audit(db, admin, "tool.create", application, tool, trace_id=new_trace_id())
    return tool_view(db, tool)


def _next_version(db: Session, tool: ToolDefinition) -> str:
    versions = []
    for value in db.scalars(select(ToolDefinition.version).where(ToolDefinition.connector_id == tool.connector_id,
                                                                 ToolDefinition.tool_key == tool.tool_key)):
        if re.fullmatch(r"\d+\.\d+\.\d+", value):
            versions.append(tuple(int(part) for part in value.split(".")))
    major, minor, patch = max(versions, default=(1, 0, 0))
    return f"{major}.{minor}.{patch + 1}"


def update_tool(db: Session, admin: AdminUser, tool: ToolDefinition, payload: dict) -> dict:
    changes = checked(ToolChanges, payload, partial=True)
    if tool.status == "archived":
        raise HubError("CONFLICT", "Archived tools cannot be changed", 409)
    _connector, application, mapping, module = _scoped(db, admin, tool)
    require_manual_tools(_connector)
    current = _current_payload(tool, mapping)
    merged = {**current, **changes}
    if any(key in changes and changes[key] != current.get(key) for key in ("method", "path_template")):
        for key in ("input_schema", "output_schema", "allow_fields", "pagination"):
            if key not in changes:
                merged.pop(key, None)
    if "allow_fields" in changes and "output_schema" not in changes:
        merged.pop("output_schema", None)
    if "input_schema" in changes and "pagination" not in changes:
        merged.pop("pagination", None)
    before = content_fingerprint(tool, mapping, module)
    _apply(tool, mapping, _build(db, application, module, merged))
    if content_fingerprint(tool, mapping, module) == before:
        return tool_view(db, tool)
    if tool.status in {"published", "disabled"}:
        # A live tool goes offline until the changed configuration passes a test.
        tool.status = "draft"
        tool.version = _next_version(db, tool)
    tool.content_hash = content_fingerprint(tool, mapping, module)
    tool.updated_at = utcnow()
    _audit(db, admin, "tool.update", application, tool)
    return tool_view(db, tool)


def delete_tool(db: Session, admin: AdminUser, tool: ToolDefinition) -> None:
    if tool.status == "published":
        raise HubError("CONFLICT", "Disable the tool before deleting it", 409)
    connector, application = get_connector_bundle(db, tool.connector_id)
    require_app_access(db, admin, application.id)
    require_manual_tools(connector)
    mapping = db.get(RestToolMapping, tool.mapping_id)
    _audit(db, admin, "tool.delete", application, tool)
    db.delete(tool)
    db.flush()
    if mapping is not None:
        db.delete(mapping)


def sample_rows(output_schema: dict, *, count: int, tenant_field: str | None, tenant_id: str) -> list[dict]:
    """Plausible synthetic records shaped like the source output. No real data is involved."""

    properties = ((output_schema or {}).get("items") or {}).get("properties") or {}
    now = utcnow().replace(microsecond=0)
    rows = []
    for index in range(count):
        row = {}
        for name, spec in properties.items():
            types = spec.get("type")
            kind = next((item for item in (types if isinstance(types, list) else [types]) if item != "null"), "string")
            if spec.get("enum"):
                value = spec["enum"][index % len(spec["enum"])]
            elif kind == "integer":
                value = min(max((index + 1) * 3, spec.get("minimum", 0)), spec.get("maximum", 10**9))
            elif kind == "number":
                value = min(max(round(12.5 * (index + 1), 2), spec.get("minimum", 0)), spec.get("maximum", 10**9))
            elif kind == "boolean":
                value = index % 2 == 0
            elif DATE_HINT.search(name.lower()):
                moment = now - timedelta(days=index * 3)
                value = moment.isoformat() if spec.get("maxLength", 64) >= 25 else moment.date().isoformat()
            else:
                value = f"Sample {name.replace('_', ' ')} {index + 1}"[:spec.get("maxLength", 200)]
            row[name] = value
        if tenant_field:
            row[tenant_field] = tenant_id
        rows.append(row)
    return rows


def _sample_document(sample, route: Route, tenant_id: str, count: int) -> dict:
    meta = {"as_of": utcnow().isoformat(), "timezone": "UTC", "scope": "sample_records", "coverage": "complete"}
    if sample is None:
        return {"success": True, "meta": meta, "data": sample_rows(route.output_schema, count=count,
                                                                   tenant_field=route.tenant_field, tenant_id=tenant_id)}
    if not isinstance(sample, dict) or not isinstance(sample.get("data"), list) or not all(isinstance(row, dict) for row in sample["data"]):
        raise HubError("VALIDATION_FAILED", "Sample data must be an object with a 'data' list of records", 422)
    rows = [dict(row) for row in sample["data"]]
    if route.tenant_field:
        for row in rows:
            row.setdefault(route.tenant_field, tenant_id)
    return {"success": True, "meta": sample.get("meta") if isinstance(sample.get("meta"), dict) else meta, "data": rows}


def _rejects(check) -> bool:
    try:
        check()
    except HubError:
        return True
    return False


def safety_checks(db: Session, tool: ToolDefinition, module: ModuleDefinition, route: Route, arguments: dict) -> dict:
    """Prove the guards hold for this configuration: unknown inputs, bad output and personal data."""

    checks = {"unknown_input_rejected": _rejects(lambda: validate_arguments(tool.input_schema, {**arguments, "__probe__": 1}))}
    policies = policy_map(db, module.id)
    allow = tool.output_policy.get("allow_fields", [])
    if tool.template == "report":
        fields = report_engine.source_fields(route.output_schema, policies)
        visible = next((name for name, field in fields.items() if field.usage == "visible"), None)
        if visible:
            checks["pii_masked"] = report_engine.prepare_rows([{visible: CANARY_EMAIL}], fields)[1] == 1
            checks["numeric_pii_masked"] = report_engine.prepare_rows([{visible: CANARY_NUMBER}], fields)[1] == 1
    elif tool.template in WRITE_TEMPLATES:
        checks["invalid_output_rejected"] = _rejects(lambda: validate_output(tool.output_schema, "invalid"))
        if allow:
            checks["pii_rejected"] = _rejects(lambda: guard_receipt([{allow[0]: CANARY_EMAIL}], allow))
    else:
        checks["invalid_output_rejected"] = _rejects(lambda: validate_output(tool.output_schema, "invalid"))
        checks["pii_rejected"] = _rejects(lambda: guard_output([{allow[0]: CANARY_EMAIL}], [allow[0]], policies))
        checks["numeric_pii_rejected"] = _rejects(lambda: guard_output([{allow[0]: CANARY_NUMBER}], [allow[0]], policies))
    return checks


def _request_preview(route: Route, arguments: dict) -> dict:
    from app.tools.rest_mapper import render_path

    path, remaining = render_path(route.path_template, arguments)
    return {"method": route.method, "path": path, "fields": sorted(remaining), "sent": False}


async def _run_pipeline(db: Session, tool: ToolDefinition, module: ModuleDefinition, route: Route, arguments: dict,
                        fetch, tenant_id: str | None, settings: Settings, trace_id: str, label: str) -> dict:
    allow = tool.output_policy.get("allow_fields", [])
    if tool.template == "report":
        return await report_pipeline(db, module=module, route=route, spec=saved_report_spec(tool, arguments), fetch=fetch,
                                     tenant_id=tenant_id, settings=settings, trace_id=trace_id, label=label)
    if tool.template in WRITE_TEMPLATES:
        return await write_pipeline(route=route, operation=tool.template, allow_fields=allow,
                                    output_schema=tool.output_schema, arguments=arguments, fetch=fetch,
                                    tenant_id=tenant_id, trace_id=trace_id)
    return await read_pipeline(db, module=module, route=route, allow_fields=allow, output_schema=tool.output_schema,
                               arguments=arguments, fetch=fetch, tenant_id=tenant_id, settings=settings, trace_id=trace_id)


def _live_allowed(application: Application, route: Route) -> None:
    if application.environment == "production" and route.requires_user_context:
        raise HubError("PERMISSION_DENIED", "Live tests of user-scoped data need a non-production app", 403)


async def test_tool(db: Session, admin: AdminUser, tool: ToolDefinition, payload: dict, settings: Settings) -> dict:
    body = payload if isinstance(payload, dict) else {}
    mode = {"synthetic": "sample"}.get(body.get("mode"), body.get("mode") or "sample")
    if mode not in {"sample", "live"}:
        raise HubError("VALIDATION_FAILED", "Test mode must be sample or live", 422)
    connector, application, mapping, module = _scoped(db, admin, tool)
    # The connect wizard's checklist asks a sample test to fill the required inputs itself.
    fill = mode == "sample" and body.get("fill_required") is True and "arguments" not in body
    arguments = sample_arguments(tool.input_schema) if fill else body.get("arguments") or {}
    tenant_id = body.get("tenant_id") or "sample_tenant"
    if not isinstance(arguments, dict) or not isinstance(tenant_id, str) or len(tenant_id) > 120:
        raise HubError("VALIDATION_FAILED", "Test arguments must be an object", 422)
    fingerprint = content_fingerprint(tool, mapping, module)
    started, trace = time.perf_counter(), new_trace_id()
    passed, error, preview, checks, request = False, None, None, {}, None
    try:
        if tool.status == "archived":
            raise HubError("CONFLICT", "Archived tools cannot be tested", 409)
        route_definition = reviewed_endpoint(module, mapping)
        _build(db, application, module, _current_payload(tool, mapping))
        route = Route.of(route_definition, mapping)
        validate_arguments(tool.input_schema, arguments)
        if tool.template != "report":
            validate_arguments(route.input_schema, arguments)
        if tool.template in WRITE_TEMPLATES:
            request = _request_preview(route, arguments)
        label = source_label(application, module)
        if mode == "sample":
            count = 12 if tool.template == "report" else (1 if tool.template in WRITE_TEMPLATES else 3)
            # A route such as GET /orders/{ref} returns one row; never sample more than it may return.
            count = max(1, min(count, int(route.output_schema.get("maxItems") or count)))
            fetch = sample_fetch(_sample_document(body.get("sample"), route, tenant_id, count))
            preview = await _run_pipeline(db, tool, module, route, arguments, fetch, tenant_id, settings, trace, label)
        else:
            if tool.template in WRITE_TEMPLATES:
                raise HubError("VALIDATION_FAILED", "Write tools are tested with sample data only; nothing is sent", 422)
            _live_allowed(application, route)
            assert_available(connector, allow_draft=True)
            source = load_source(db, connector, application, module, settings)
            delegation = delegation_from_header(body.get("delegation"), source.delegation_secret, application.key)
            if route.requires_user_context and delegation is None:
                raise HubError("PERMISSION_DENIED", "A live test of user-scoped data needs a delegation token signed by the app", 403)
            outcome = None
            try:
                preview = await _run_pipeline(db, tool, module, route, arguments,
                                              live_fetch(source, route, delegation, settings, trace),
                                              delegation["tenant_id"] if delegation else None, settings, trace, label)
            except HubError as exc:
                outcome = exc
                raise
            finally:
                record_outcome(connector, settings, outcome)
        checks = safety_checks(db, tool, module, route, arguments)
        passed = all(checks.values())
        if not passed:
            error = HubError("SAFETY_CHECK_FAILED", "A privacy or schema guard did not hold for this configuration", 422)
    except HubError as exc:
        error = exc
    duration = int((time.perf_counter() - started) * 1000)
    db.add(ToolTestRun(id=new_id(), tool_id=tool.id, mode=mode, passed=passed, content_hash=fingerprint,
                       case_results=checks, trace_id=trace, duration_ms=duration, error_code=error.code if error else None))
    _audit(db, admin, "tool.test", application, tool, result="success" if passed else "error",
           error_code=error.code if error else None, duration_ms=duration, trace_id=trace)
    return {"passed": passed, "mode": mode, "trace_id": trace, "duration_ms": duration,
            "error_code": error.code if error else None, "error_message": error.message if error else None,
            "preview": preview, "checks": checks, "request": request, "cases": checks}


def publish_tool(db: Session, admin: AdminUser, tool: ToolDefinition, settings: Settings) -> dict:
    connector, application, mapping, module = _scoped(db, admin, tool)
    require_manual_tools(connector)
    if tool.status == "archived":
        raise HubError("CONFLICT", "Archived tools cannot be published", 409)
    if connector.status != "active":
        raise HubError("CONFLICT", "Activate the app before publishing its tools", 409)
    validate_destination(connector.base_url + "/", settings)
    setting = module_setting(db, module)
    operation = operation_for(tool.template)
    if not setting.enabled or operation not in (setting.operations_enabled or []):
        raise HubError("MODULE_DISABLED", f"Allow {operation} on the {module.name} data source first", 403)
    reviewed_endpoint(module, mapping)
    _build(db, application, module, _current_payload(tool, mapping))
    fingerprint = content_fingerprint(tool, mapping, module)
    if _passing_test(db, tool, fingerprint) is None:
        raise HubError("CONFLICT", "Run a passing test of the current configuration before publishing", 409)
    for old in db.scalars(select(ToolDefinition).where(ToolDefinition.mcp_name == tool.mcp_name,
                                                       ToolDefinition.status == "published", ToolDefinition.id != tool.id)):
        old.status = "archived"
    db.flush()
    tool.content_hash = fingerprint
    tool.status = "published"
    tool.approved_by = admin.id
    tool.policy_version = setting.policy_version
    tool.updated_at = utcnow()
    _audit(db, admin, "tool.publish", application, tool)
    return tool_view(db, tool)


def disable_tool(db: Session, admin: AdminUser, tool: ToolDefinition) -> dict:
    _connector, application, _mapping, _module_row = _scoped(db, admin, tool)
    require_manual_tools(_connector)
    if tool.status != "published":
        raise HubError("CONFLICT", "Only a published tool can be disabled", 409)
    tool.status = "disabled"
    tool.updated_at = utcnow()
    _audit(db, admin, "tool.disable", application, tool)
    return tool_view(db, tool)


def refresh_fingerprints(db: Session, module: ModuleDefinition, previous_hash: str) -> None:
    """Re-label tools tested against an unchanged contract whose hash format changed."""

    tools = db.scalars(select(ToolDefinition).join(Connector, Connector.id == ToolDefinition.connector_id)
                       .where(Connector.app_id == module.app_id, ToolDefinition.module_key == module.module_key,
                              ToolDefinition.status != "archived"))
    for tool in tools:
        mapping = db.get(RestToolMapping, tool.mapping_id)
        if mapping is None:
            continue
        old = content_fingerprint(tool, mapping, module, module_hash=previous_hash)
        new = content_fingerprint(tool, mapping, module)
        for run in db.scalars(select(ToolTestRun).where(ToolTestRun.tool_id == tool.id, ToolTestRun.content_hash == old)):
            run.content_hash = new
        if tool.content_hash == old:
            tool.content_hash = new


def builtin_catalog() -> list[dict]:
    """Hub tools: the two always-on tools, then the memory tools apps can turn on."""

    always = [{**tool.model_dump(by_alias=True, exclude_none=True), "requires": None} for tool in catalog.BUILTINS.values()]
    return always + [{**tool.model_dump(by_alias=True, exclude_none=True), "requires": "memory"}
                     for tool in memory.TOOLS.values()]


async def test_builtin(db: Session, admin: AdminUser, name: str, payload: dict, settings: Settings) -> dict:
    """Preview what an AI client would get from a built-in tool for one app."""

    if name not in catalog.BUILTINS:
        raise HubError("NOT_FOUND", "Built-in tool was not found", 404)
    body = payload if isinstance(payload, dict) else {}
    connector, application = get_connector_bundle(db, str(body.get("connector_id") or ""))
    require_app_access(db, admin, application.id)
    started, trace = time.perf_counter(), new_trace_id()
    mode = body.get("mode") or "sample"
    error, preview = None, None
    try:
        if name == catalog.LIST_SOURCES:
            preview = {"success": True, "data": catalog.data_sources(db, application.id),
                       "meta": {"scope": "enabled_sources", "coverage": "complete", "contains_personal_data": False},
                       "trace_id": trace}
        else:
            arguments = body.get("arguments") or {}
            validate_arguments(catalog.REPORT_INPUT, arguments)
            module = _module(db, application, resolve_source_key(application, arguments.get("source")))
            route = report_route(db, module, connector)
            spec = report_engine.parse_spec({key: value for key, value in arguments.items() if key != "source"})
            tenant_id = body.get("tenant_id") or "sample_tenant"
            label = source_label(application, module)
            if mode == "sample":
                fetch = sample_fetch(_sample_document(body.get("sample"), route, str(tenant_id), 12))
                preview = await report_pipeline(db, module=module, route=route, spec=spec, fetch=fetch,
                                                tenant_id=str(tenant_id), settings=settings, trace_id=trace, label=label)
            elif mode == "live":
                _live_allowed(application, route)
                assert_available(connector, allow_draft=True)
                source = load_source(db, connector, application, module, settings)
                delegation = delegation_from_header(body.get("delegation"), source.delegation_secret, application.key)
                if route.requires_user_context and delegation is None:
                    raise HubError("PERMISSION_DENIED", "A live report on user-scoped data needs a delegation token signed by the app", 403)
                preview = await report_pipeline(db, module=module, route=route, spec=spec,
                                                fetch=live_fetch(source, route, delegation, settings, trace),
                                                tenant_id=delegation["tenant_id"] if delegation else None,
                                                settings=settings, trace_id=trace, label=label)
            else:
                raise HubError("VALIDATION_FAILED", "Test mode must be sample or live", 422)
    except HubError as exc:
        error = exc
    duration = int((time.perf_counter() - started) * 1000)
    record_audit(db, action="tool.test", actor_ref=f"admin:{admin.id}", result="success" if error is None else "error",
                 app_key=application.key, environment=application.environment, tool_key=name,
                 error_code=error.code if error else None, duration_ms=duration, trace_id=trace)
    return {"passed": error is None, "mode": mode, "trace_id": trace, "duration_ms": duration,
            "error_code": error.code if error else None, "error_message": error.message if error else None,
            "preview": preview}


# Generator: the full recommended tool set of an app, from the routes it published.

def _action_for(module: ModuleDefinition, template: str, route: dict) -> str:
    if template == "report":
        return "summary"
    if template in WRITE_TEMPLATES:
        return template
    segments = [part for part in route["path_template"].split("/") if part]
    if segments and segments[-1].startswith("{"):
        return "get"
    last = re.sub(r"[^a-z0-9_]", "_", (segments[-1] if segments else "list").lower()).strip("_")
    if not last or last == module.module_key:
        return "list"
    return last if last[0].isalpha() else f"r_{last}"


def _generated_description(module: ModuleDefinition, application: Application, template: str, action: str,
                           route: dict) -> str:
    if template == "report":
        return f"Summarize {module.name} from {application.name}: totals and breakdowns."
    if template in WRITE_TEMPLATES:
        return f"{template.capitalize()} a {module.name} record in {application.name}."
    properties = route["input_schema"].get("properties", {})
    required = [name for name in route["input_schema"].get("required", []) if name not in PAGE_PARAMETERS]
    if action == "get" or required:
        return f"Look up one {module.name} record in {application.name} by {', '.join(required) or 'its reference'}."
    filters = [name for name in properties if name not in PAGE_PARAMETERS]
    text = f"List {module.name} records from {application.name}."
    return text + (f" Filters: {', '.join(filters[:6])}." if filters else "")


def _starter_report(db: Session, module: ModuleDefinition, route: dict) -> dict:
    """Count by the first category field (or by month), plus the total of the first numeric field."""

    fields = report_engine.source_fields(route["output_schema"], policy_map(db, module.id))
    category = next((field.name for field in fields.values() if field.usage == "visible" and field.values), None)
    moment = next((field.name for field in fields.values()
                   if field.usage == "visible" and DATE_HINT.search(field.name.lower())), None)
    number = next((field.name for field in fields.values() if field.kind in {"integer", "number"}), None)
    spec: dict = {"metrics": [{"fn": "count"}] + ([{"fn": "sum", "field": number}] if number else [])}
    if category:
        spec.update(group_by=[category], sort={"by": "count", "direction": "desc"})
    elif moment:
        spec["time_bucket"] = {"field": moment, "interval": "month"}
    return spec


def _generated_note(template: str, publish: bool, readable: bool) -> str | None:
    if template in WRITE_TEMPLATES:
        return "Draft: review the request, test it and publish it yourself"
    if not publish:
        return "Draft: test and publish when ready"
    if not readable:
        return "Draft: allow reading this data source to publish it"
    return None


def _generated_item(tool: ToolDefinition, module_name: str, note: str | None) -> dict:
    return {"id": tool.id, "tool_key": tool.tool_key, "mcp_name": tool.mcp_name, "template": tool.template,
            "title": catalog.tool_title(tool), "module_name": module_name, "status": tool.status, "note": note}


def sample_arguments(schema: dict) -> dict:
    """Values for the required inputs, so a sample test can run a route such as GET /orders/{ref}."""

    values = {}
    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        spec = properties.get(name) or {}
        kinds = spec.get("type") if isinstance(spec.get("type"), list) else [spec.get("type")]
        kind = next((item for item in kinds if item != "null"), "string")
        if spec.get("enum"):
            values[name] = spec["enum"][0]
        elif kind in ("integer", "number"):
            values[name] = max(spec.get("minimum", 1), 1) if kind == "integer" else float(max(spec.get("minimum", 1), 1))
        elif kind == "boolean":
            values[name] = True
        else:
            values[name] = "sample1"[: max(1, min(spec.get("maxLength", 7), 7))].ljust(spec.get("minLength", 0), "x")
    return values


async def _test_and_publish(db: Session, admin: AdminUser, tool: ToolDefinition, connector: Connector, readable: bool,
                            publish: bool, settings: Settings) -> str | None:
    """Publish a read or report tool when its sample test passes. Returns why it stayed a draft, if it did."""

    note = _generated_note(tool.template, publish, readable)
    if note is not None:
        return note
    result = await test_tool(db, admin, tool, {"mode": "sample", "arguments": sample_arguments(tool.input_schema)}, settings)
    db.flush()  # The session does not autoflush; publishing looks the test run up.
    if not result["passed"]:
        return f"Draft: the sample test did not pass ({result['error_message'] or result['error_code']})"
    if connector.status != "active":
        return "Tested. Activate the app to publish it"
    try:
        publish_tool(db, admin, tool, settings)
    except HubError as exc:
        return f"Tested, not published: {exc.message}"
    return None


async def _refresh_source_tools(db: Session, admin: AdminUser, connector: Connector, application: Application,
                                settings: Settings) -> dict:
    """Source-managed apps: their tools follow the app's grants, so generating means re-reading them now."""

    if connector.status != "active":
        raise HubError("CONFLICT", f"Activate {application.name} first: its tools follow the app's own permissions", 409)
    before = {tool.id: tool.status for tool in db.scalars(select(ToolDefinition).where(ToolDefinition.connector_id == connector.id))}
    await discover_capabilities(db, connector, application, settings=settings, encryption_key=settings.secret_encryption_key)
    db.flush()
    names = dict(db.execute(select(ModuleDefinition.module_key, ModuleDefinition.name)
                            .where(ModuleDefinition.app_id == application.id)).all())
    created, repaired, skipped, unchanged = [], [], [], 0
    for tool in db.scalars(select(ToolDefinition).where(ToolDefinition.connector_id == connector.id,
                                                        ToolDefinition.status != "archived")
                           .order_by(ToolDefinition.tool_key)):
        was = before.get(tool.id)
        name = names.get(tool.module_key, tool.module_key)
        if tool.status == "published" and was is None:
            created.append(_generated_item(tool, name, None))
        elif tool.status == "published" and was != "published":
            repaired.append(_generated_item(tool, name, "Allowed again in the app"))
        elif tool.status == "published":
            unchanged += 1
        elif was == "published":
            skipped.append({"tool_key": tool.tool_key, "reason": f"No longer allowed in {application.name}"})
    record_audit(db, action="tool.generate", actor_ref=f"admin:{admin.id}", result="success", app_key=application.key,
                 environment=application.environment, trace_id=new_trace_id())
    return {"mode": "source_managed", "created": created, "repaired": repaired, "skipped": skipped,
            "unchanged": unchanged, "published": len(created) + len(repaired)}


async def generate_tools(db: Session, admin: AdminUser, payload: dict, settings: Settings) -> dict:
    """Bring an app's tools up to date with the routes it published.

    New routes get a tool. Read and report tools are tested with synthetic data and published
    when they pass and the data source allows reading; a re-run also finishes drafts it left
    behind and re-tests live tools that need it after a contract change. Write tools stay
    drafts for an admin to review. Source-managed apps instead refresh from the app's grants.
    """

    body = payload if isinstance(payload, dict) else {}
    connector, application = get_connector_bundle(db, str(body.get("connector_id") or ""))
    require_app_access(db, admin, application.id)
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot get new tools", 409)
    if connector.connector_type == "source_managed":
        return await _refresh_source_tools(db, admin, connector, application, settings)
    publish = body.get("publish", True) is not False
    existing: dict[tuple[str, str, str], tuple[ToolDefinition, RestToolMapping]] = {}
    for tool, mapping in db.execute(select(ToolDefinition, RestToolMapping)
                                    .join(RestToolMapping, RestToolMapping.id == ToolDefinition.mapping_id)
                                    .where(ToolDefinition.connector_id == connector.id, ToolDefinition.status != "archived")
                                    .order_by(ToolDefinition.created_at)):
        # A live tool represents its route over any older draft of the same route.
        signature = (tool.template, mapping.method, mapping.path_template)
        if signature not in existing or tool.status == "published":
            existing[signature] = (tool, mapping)
    taken = set(db.scalars(select(ToolDefinition.tool_key).where(ToolDefinition.connector_id == connector.id)))
    created, repaired, skipped, unchanged = [], [], [], 0
    modules = list(db.scalars(select(ModuleDefinition).where(ModuleDefinition.app_id == application.id)
                              .order_by(ModuleDefinition.module_key)))
    if not modules:
        skipped.append({"tool_key": application.key,
                        "reason": "No data sources yet: test the connection and sync the contract first"})
    for module in modules:
        setting = module_setting(db, module)
        if not setting.enabled:
            skipped.append({"tool_key": f"{application.key}.{module.module_key}",
                            "reason": f"{module.name} is not allowed yet"})
            continue
        readable = "read" in (setting.operations_enabled or [])
        plans = [("read" if route["kind"] == "read" else route["operation"], route) for route in module_endpoints(module)]
        dataset = dataset_endpoint(module, setting.report_endpoint)
        if dataset is not None:
            plans.append(("report", dataset))
        for template, route in plans:
            action = _action_for(module, template, route)
            base_key = f"{application.key}.{module.module_key}.{action}"
            found = existing.get((template, route["method"], route["path_template"]))
            if found is not None:
                tool, mapping = found
                stale = tool.status == "published" and tool.content_hash != content_fingerprint(tool, mapping, module)
                if tool.status == "published" and not stale:
                    unchanged += 1
                elif tool.status == "disabled":
                    skipped.append({"tool_key": tool.tool_key, "reason": "Disabled by an admin; enable it on its page"})
                elif template in WRITE_TEMPLATES:
                    skipped.append({"tool_key": tool.tool_key, "reason": "Write tool waiting for review on its page"})
                else:
                    note = await _test_and_publish(db, admin, tool, connector, readable, publish, settings)
                    if note is None:
                        repaired.append(_generated_item(tool, module.name, "Re-tested and published" if stale else "Finished and published"))
                    else:
                        skipped.append({"tool_key": tool.tool_key, "reason": note})
                continue
            tool_key, suffix = base_key, 2
            while tool_key in taken:
                tool_key, suffix = f"{base_key}_{suffix}", suffix + 1
            data = {"connector_id": connector.id, "module_key": module.module_key, "template": template,
                    "tool_key": tool_key, "title": catalog.key_title(tool_key),
                    "description": _generated_description(module, application, template, action, route),
                    "method": route["method"], "path_template": route["path_template"]}
            if template == "report":
                data["report"] = _starter_report(db, module, route)
            try:
                view = create_tool(db, admin, data)
            except HubError as exc:
                if template != "report":
                    skipped.append({"tool_key": tool_key, "reason": exc.message})
                    continue
                try:  # The suggested breakdown may not suit this source; a plain count always does.
                    view = create_tool(db, admin, {**data, "report": {}})
                except HubError as retry:
                    skipped.append({"tool_key": tool_key, "reason": retry.message})
                    continue
            taken.add(tool_key)
            tool = db.get(ToolDefinition, view["id"])
            existing[(template, route["method"], route["path_template"])] = (tool, db.get(RestToolMapping, tool.mapping_id))
            note = await _test_and_publish(db, admin, tool, connector, readable, publish, settings)
            created.append(_generated_item(tool, module.name, note))
    record_audit(db, action="tool.generate", actor_ref=f"admin:{admin.id}", result="success", app_key=application.key,
                 environment=application.environment, trace_id=new_trace_id())
    return {"mode": "generated", "created": created, "repaired": repaired, "skipped": skipped, "unchanged": unchanged,
            "published": sum(1 for item in created + repaired if item["status"] == "published")}


def agent_view(db: Session, admin: AdminUser, connector_id: str, *, key_id: str | None = None,
               write: bool = False) -> dict:
    """Exactly what an AI client receives from tools/list and prompts/list for one app."""

    from app.services import skills
    from app.services.profiles import binding

    connector, application = get_connector_bundle(db, connector_id)
    require_app_access(db, admin, application.id)
    if key_id:
        identity = db.get(ServiceIdentity, key_id)
        if identity is None or identity.app_id != application.id:
            raise HubError("NOT_FOUND", "Client key was not found for this app", 404)
        if identity.revoked_at is not None or (identity.expires_at and as_utc(identity.expires_at) <= utcnow()):
            raise HubError("CONFLICT", "This client key is revoked or expired and sees nothing", 409)
        profile = binding(db, application.id, identity.profile_id)
        if profile is not None and not profile.enabled:
            raise HubError("CONFLICT", "This client key's access profile is disabled", 409)
        key = {"id": identity.id, "name": identity.name, "write": WRITE_SCOPE in (identity.scopes or []),
               "allowed_tools": identity.allowed_tools, "profile_id": identity.profile_id,
               "profile_name": profile.name if profile else None}
    else:
        # A transient key, never added to the session: shows what a new key of this kind would see.
        identity = ServiceIdentity(id="preview", name="preview", token_hash="", app_id=application.id,
                                   scopes=[READ_SCOPE] + ([WRITE_SCOPE] if write else []), allowed_tools=None)
        profile = None
        key = {"id": None, "name": "Read & write key" if write else "Read-only key", "write": write,
               "allowed_tools": None}
    caller = Caller(identity, application, connector, profile)
    tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in catalog.visible_tools(db, caller)]
    prompts = [prompt.model_dump(by_alias=True, exclude_none=True) for prompt in skills.visible_prompts(db, caller)]
    return {"app": {"connector_id": connector.id, "app_key": application.key, "name": application.name,
                    "environment": application.environment, "status": connector.status},
            "key": key, "instructions": catalog.SERVER_INSTRUCTIONS,
            "memory_enabled": memory.is_enabled(db, application.id), "tools": tools, "prompts": prompts}
