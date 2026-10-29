"""Untrusted API descriptions become reviewed drafts, never executable grants."""

import copy
import hashlib
import json
import math
import re
from urllib.parse import unquote, urljoin, urlsplit

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session
from yaml.events import AliasEvent
from yaml.nodes import ScalarNode

from app.capabilities.policy_service import policy_map
from app.config import Settings
from app.connectors.endpoint_policy import module_endpoints
from app.connectors.http_adapter import execute_request
from app.connectors.registry import get_connector_bundle
from app.errors import HubError
from app.persistence.models import AdminUser, ModuleDefinition
from app.privacy.output_guard import AI_SAFE
from app.privacy.pii_inspector import tree_contains_pii
from app.security.authorization import (
    WRITE_ROLES,
    is_sensitive_path,
    require_app_access,
    require_role,
)
from app.services import tools
from app.tools.schema_tools import NAME_RE, mcp_name_for, project_output_schema

MAX_BYTES = 524288
METHODS = {"get", "post", "put", "patch", "delete"}


def invalid(message="OpenAPI document is outside the supported import contract"):
    return HubError("VALIDATION_FAILED", message, 422)


class LimitedLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self.nodes_seen = self.depth = 0

    def compose_node(self, parent, index):
        self.nodes_seen += 1
        self.depth += 1
        if self.nodes_seen > 15000 or self.depth > 24 or self.check_event(AliasEvent):
            raise invalid("YAML aliases or excessive nesting are not supported")
        try:
            node = super().compose_node(parent, index)
            if node.tag not in {"tag:yaml.org,2002:" + kind for kind in ("map", "seq", "str", "int", "float", "bool", "null")}:
                raise invalid("Custom YAML tags are not supported")
            return node
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                raise invalid()
            key = self.construct_scalar(key_node)
            if key == "<<" or key in result:
                raise invalid("Duplicate keys and YAML merge keys are not supported")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise invalid("Duplicate document keys are not supported")
        result[key] = value
    return result


def parse(text: str, format: str) -> dict:
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        raise invalid("API descriptions must use UTF-8") from None
    if len(encoded) > MAX_BYTES:
        raise HubError("PAYLOAD_TOO_LARGE", "OpenAPI documents are limited to 512 KiB", 413)
    try:
        document = (json.loads(text, object_pairs_hook=unique_pairs) if format == "json"
                    else yaml.load(text, Loader=LimitedLoader))
    except (ValueError, TypeError, RecursionError, yaml.YAMLError):
        raise invalid("OpenAPI document could not be parsed") from None
    if not isinstance(document, dict) or not re.fullmatch(r"3\.[012]\.\d{1,3}", str(document.get("openapi", ""))):
        raise invalid("Use a supported OpenAPI 3.0, 3.1 or 3.2 document")
    count = 0

    def inspect(value, depth=0):
        nonlocal count
        count += 1
        if count > 15000 or depth > 24:
            raise invalid("OpenAPI document exceeds its structural limits")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 200 or key.lower().startswith("x-"):
                    raise invalid("Custom extensions and oversized keys are not supported")
                try:
                    key.encode("utf-8")
                except UnicodeError:
                    raise invalid("Document keys must use valid Unicode") from None
                if key == "$ref" and (not isinstance(item, str) or not item.startswith("#/components/")):
                    raise invalid("Only local component references are supported")
                if key in {"$dynamicRef", "$id", "$anchor", "$dynamicAnchor"}:
                    raise invalid("Dynamic reference scopes are not supported")
                inspect(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                inspect(item, depth + 1)
        elif value is not None and type(value) not in {str, int, float, bool}:
            raise invalid("Document values must be JSON-compatible")
        elif isinstance(value, float) and not math.isfinite(value):
            raise invalid("Non-finite document values are not supported")
        elif isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise invalid("Document strings must use valid Unicode") from None

    inspect(document)
    info = document.get("info")
    if not isinstance(info, dict) or any(not isinstance(info.get(field), str) or not 1 <= len(info[field]) <= 200 for field in ("title", "version")):
        raise invalid("OpenAPI info must include a bounded title and version")
    if not isinstance(document.get("paths"), dict) or len(document["paths"]) > 100:
        raise invalid("OpenAPI paths must be an object with at most 100 entries")
    return document


class Resolver:
    def __init__(self, document):
        self.document = document
        self.expanded = 0

    def resolve(self, value, seen=(), depth=0):
        self.expanded += 1
        if self.expanded > 50000 or depth > 24:
            raise invalid("Expanded document exceeds its limits")
        if isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                if ref in seen or len(seen) >= 12 or set(value) - {"$ref", "summary", "description"}:
                    raise invalid("Recursive or extended references are not supported")
                target = self.document
                try:
                    for segment in ref[2:].split("/"):
                        target = target[segment.replace("~1", "/").replace("~0", "~")]
                except (KeyError, TypeError):
                    raise invalid("Local component reference was not found") from None
                return self.resolve(target, (*seen, ref), depth + 1)
            return {key: self.resolve(item, seen, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item, seen, depth + 1) for item in value]
        return value


async def document_for(body: dict, settings: Settings) -> dict:
    text, url = body.get("document"), body.get("source_url")
    if (text is None) == (url is None):
        raise invalid("Provide one document or one HTTPS document URL")
    if url is not None:
        try:
            parts = urlsplit(url)
            parts.port
        except ValueError:
            raise invalid("The document URL is invalid") from None
        if parts.scheme != "https":
            raise invalid("Remote document URLs require HTTPS")
        status, raw, _elapsed = await execute_request(method="GET", url=url, settings=settings,
            headers={"Accept": "application/json, application/yaml, text/yaml"}, retries=0,
            timeout_ms=5000, max_bytes=MAX_BYTES, tls_verify=True)
        if not 200 <= status < 300:
            raise HubError("UPSTREAM_UNAVAILABLE", "The API description could not be downloaded", 502)
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            raise invalid("API descriptions must use UTF-8") from None
    return parse(text, body.get("format", "json"))


def origin(url):
    return url.scheme.lower(), (url.hostname or "").lower(), url.port or (443 if url.scheme == "https" else 80)


def routed_path(base: str, path: str, servers) -> str:
    if not isinstance(path, str) or len(path) > 500 or not path.startswith("/") or tree_contains_pii(path):
        raise invalid("Operation path is not a supported source route")
    if not servers:
        return path
    if not isinstance(servers, list) or len(servers) > 10:
        raise invalid("Server hints must be a bounded list")
    target = urlsplit(base)
    for server in servers:
        if not isinstance(server, dict) or not isinstance(server.get("url"), str) or server.get("variables"):
            continue
        try:
            hint = urlsplit(urljoin(base.rstrip("/") + "/", server["url"]))
            matches = origin(hint) == origin(target)
        except ValueError:
            continue
        if hint.username or hint.password or hint.query or hint.fragment or not matches:
            continue
        prefix, base_path = hint.path.rstrip("/"), target.path.rstrip("/")
        if prefix != base_path and not prefix.startswith(base_path + "/"):
            continue
        if "\\" in prefix or any(part in {".", ".."} for part in unquote(prefix).split("/")):
            continue
        return prefix[len(base_path):] + path
    raise invalid("Document servers do not match this connector's configured base URL")


def scalar_fields(schema) -> dict:
    if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise invalid("Only explicit scalar record fields are supported")
    fields = schema["properties"]
    if len(fields) > 100 or any(not NAME_RE.fullmatch(name) for name in fields):
        raise invalid("Record field names are outside the supported contract")
    return fields


def scalar(schema):
    if not isinstance(schema, dict) or any(key in schema for key in ("oneOf", "anyOf", "allOf", "contentEncoding", "contentMediaType")):
        return False
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    return bool(types) and all(isinstance(value, str) for value in types) and set(types) <= {"string", "number", "integer", "boolean", "null"} and bool(set(types) - {"null"}) and schema.get("format") not in {"binary", "byte"}


def operation_input(item: dict, operation: dict) -> set[str]:
    fields = {}
    for parameters in (item.get("parameters", []), operation.get("parameters", [])):
        names = set()
        if not isinstance(parameters, list) or len(parameters) > 30:
            raise invalid("Operation parameters must be a bounded list")
        for parameter in parameters:
            if not isinstance(parameter, dict) or parameter.get("in") not in {"path", "query"}:
                raise invalid("Only reviewed path/query inputs are supported; use source authentication for headers")
            name = parameter.get("name")
            if not isinstance(name, str) or not NAME_RE.fullmatch(name) or not scalar(parameter.get("schema")):
                raise invalid("Operation parameters must be scalar fields")
            if name in names or (name in fields and fields[name].get("in") != parameter.get("in")):
                raise invalid("Operation parameters must have distinct names and locations")
            names.add(name)
            fields[name] = parameter
    if "requestBody" in operation:
        body = operation["requestBody"]
        try:
            schema = body["content"]["application/json"]["schema"]
        except (KeyError, TypeError):
            raise invalid("Request bodies must declare JSON record fields") from None
        for name, spec in scalar_fields(schema).items():
            if name in fields or not scalar(spec):
                raise invalid("Request fields must be distinct scalars")
            fields[name] = spec
    if len(fields) > 30:
        raise invalid("Operations are limited to 30 inputs")
    return set(fields)


def output_fields(operation: dict) -> set[str]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        raise invalid("Operation responses must be explicit")
    response = next((responses[status] for status in ("200", "201", "202", "204") if status in responses), None)
    try:
        schema = response["content"]["application/json"]["schema"]
        if schema.get("type") == "object" and "data" in schema.get("properties", {}):
            schema = schema["properties"]["data"]
        if schema.get("type") == "array":
            schema = schema["items"]
        fields = scalar_fields(schema)
    except (KeyError, TypeError, AttributeError):
        raise invalid("A JSON record response is required") from None
    return {name for name, spec in fields.items() if scalar(spec)}


def authorize(db: Session, admin: AdminUser, connector_id: str):
    if not admin.is_active:
        raise HubError("PERMISSION_DENIED", "Administrator access was revoked", 403)
    require_role(admin.role, WRITE_ROLES)
    connector, application = get_connector_bundle(db, connector_id)
    require_app_access(db, admin, application.id)
    tools.require_manual_tools(connector)
    if connector.connector_type != "http_contract":
        raise HubError("POLICY_LOCKED", "Import requires a manually reviewed HTTP connection", 409)
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived connections cannot import tools", 409)
    return connector, application


def preview(db: Session, admin: AdminUser, connector_id: str, document: dict) -> dict:
    connector, application = authorize(db, admin, connector_id)
    modules = list(db.scalars(select(ModuleDefinition).where(ModuleDefinition.app_id == application.id).limit(200)))
    routes = {}
    for module in modules:
        for route in module_endpoints(module):
            routes.setdefault((route["method"], route["path_template"]), []).append((module, route))
    digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    resolved, candidates = Resolver(document).resolve(document), []
    for path, item in resolved["paths"].items():
        if not isinstance(item, dict):
            raise invalid("Path entries must be objects")
        for method, operation in item.items():
            if method not in METHODS | {"head", "options", "trace", "query"}:
                continue
            if len(candidates) >= 60:
                raise invalid("A document is limited to 60 operation candidates")
            identifier = hashlib.sha256((method + " " + path).encode()).hexdigest()[:24]
            candidate = {"id": identifier, "method": method.upper(), "path": path[:500], "eligible": False,
                         "reason": None, "module_key": None, "template": None, "payload": None}
            try:
                if method not in METHODS or not isinstance(operation, dict):
                    raise invalid("This HTTP operation is not supported")
                resolved_path = routed_path(connector.base_url, path, operation.get("servers", item.get("servers", resolved.get("servers"))))
                matches = routes.get((method.upper(), resolved_path), [])
                if len(matches) != 1:
                    raise invalid("Operation must match one reviewed source route")
                module, route = matches[0]
                inputs = operation_input(item, operation)
                reviewed = route["input_schema"]
                if not inputs <= set(reviewed.get("properties", {})) or not set(reviewed.get("required", [])) <= inputs:
                    raise invalid("Inputs must retain the reviewed source parameters and required fields")
                output = output_fields(operation)
                approved = set(route["output_schema"]["items"]["properties"])
                template = route["operation"] if route["kind"] == "write" else "read"
                visible = approved if template != "read" else {name for name, policy in policy_map(db, module.id).items()
                                                               if policy in AI_SAFE and not is_sensitive_path(name)}
                allowed = sorted(output & approved & visible)
                if not allowed or (template != "read" and not set(route["output_schema"]["items"].get("required", [])) <= set(allowed)):
                    raise invalid("No safe record output or required write receipt is documented")
                schema = copy.deepcopy(reviewed)
                schema["properties"] = {name: value for name, value in schema.get("properties", {}).items() if name in inputs}
                key = f"{application.key}.{module.module_key}.openapi_{identifier[:12]}"
                mcp_name_for(key, application.environment)
                title = operation.get("summary") or operation.get("operationId") or f"{method.upper()} {module.name}"
                title = tools._title(title) if isinstance(title, str) else None
                payload = {"connector_id": connector.id, "module_key": module.module_key, "tool_key": key,
                           "template": template, "method": method.upper(), "path_template": resolved_path,
                           "title": title, "input_schema": schema, "allow_fields": allowed,
                           "output_schema": project_output_schema(route["output_schema"], allowed)}
                tools._build(db, application, module, payload)
                security = operation.get("security", resolved.get("security", []))
                auth = sorted({name for requirement in security if isinstance(requirement, dict)
                               for name in requirement if isinstance(name, str) and NAME_RE.fullmatch(name)}) if isinstance(security, list) else []
                candidate.update(eligible=True, path=resolved_path, module_key=module.module_key, template=template, payload=payload,
                    input_fields=sorted(inputs), output_fields=allowed, excluded_output_fields=len(output - set(allowed)),
                    auth_requirements=auth, requires_user_context=route["requires_user_context"])
            except HubError as error:
                candidate["reason"] = error.message
            candidates.append(candidate)
    return {"fingerprint": digest, "candidates": candidates}


def import_drafts(db: Session, admin: AdminUser, connector_id: str, document: dict, fingerprint: str, selected: list[str]) -> dict:
    connector, _application = authorize(db, admin, connector_id)
    db.refresh(connector, with_for_update=True)
    checked = preview(db, admin, connector_id, document)
    if checked["fingerprint"] != fingerprint:
        raise HubError("CONFLICT", "The document changed; preview it again", 409)
    candidates = {candidate["id"]: candidate for candidate in checked["candidates"]}
    if len(selected) != len(set(selected)) or any(not candidates.get(key, {}).get("eligible") for key in selected):
        raise invalid("Select distinct eligible operations from the current preview")
    created = [tools.create_tool(db, admin, candidates[key]["payload"]) for key in selected]
    return {"created": [{"id": tool["id"], "tool_key": tool["tool_key"], "status": tool["status"]} for tool in created],
            "fingerprint": checked["fingerprint"]}
