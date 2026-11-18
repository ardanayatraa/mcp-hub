"""Turn an admin-written endpoint list into the same contract an application would publish.

The admin names the resources and read endpoints of any HTTP API; the Hub validates them and
builds a source-managed contract, so permissions, field policy, privacy checks, tool switches
and audit work exactly as they do for a published manifest. Only GET is supported for now.
"""

import re

from app.connectors.contracts import FIELD_RE, KEY_RE, validate_manifest
from app.errors import HubError
from app.tools.schema_tools import NAME_RE, TYPES, clean_description

NAME_PART = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RESULT_PATH_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_]{0,39}(?:\.[A-Za-z][A-Za-z0-9_]{0,39}){0,3})?$")
PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]{0,40})\}")
MAX_RESOURCES, MAX_ENDPOINTS, MAX_FIELDS, MAX_PARAMS = 20, 30, 40, 20


def _fail(message: str) -> HubError:
    return HubError("VALIDATION_FAILED", message, 422)


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise _fail(f"{label} must be an object")
    return value


def _field_schema(name: str, raw) -> dict:
    """A field is "string", "number?" (nullable) or {"type": "string", "maxLength": 1000}."""

    spec = {"type": raw} if isinstance(raw, str) else dict(_object(raw, f"Field '{name}'"))
    kind = spec.get("type")
    if not isinstance(kind, str):
        raise _fail(f"Field '{name}' needs a type")
    nullable = kind.endswith("?")
    kind = kind.rstrip("?")
    if kind not in TYPES:
        raise _fail(f"Field '{name}' type must be one of: {', '.join(sorted(TYPES))}")
    result: dict = {"type": [kind, "null"] if nullable else kind}
    if kind == "string" and "maxLength" in spec:
        length = spec["maxLength"]
        if type(length) is not int or not 1 <= length <= 2000:
            raise _fail(f"Field '{name}' maxLength must be between 1 and 2000")
        result["maxLength"] = length
    return result


def _fields(raw, resource: str) -> dict[str, dict]:
    raw = _object(raw, f"Fields of '{resource}'")
    if not 1 <= len(raw) <= MAX_FIELDS:
        raise _fail(f"Resource '{resource}' needs between 1 and {MAX_FIELDS} fields")
    for name in raw:
        if not isinstance(name, str) or not FIELD_RE.match(name) or not NAME_RE.fullmatch(name):
            raise _fail(f"Field name '{name}' is not a valid identifier")
    return {name: _field_schema(name, spec) for name, spec in raw.items()}


def _params(raw, path: str, endpoint: str) -> tuple[dict, list[str]]:
    raw = raw or {}
    if isinstance(raw, list):
        raw = {name: "string" for name in raw}
    raw = _object(raw, f"Params of '{endpoint}'")
    if len(raw) > MAX_PARAMS:
        raise _fail(f"Endpoint '{endpoint}' has too many params")
    properties = {}
    for name, kind in raw.items():
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or kind not in TYPES:
            raise _fail(f"Param '{name}' of '{endpoint}' needs a name and one of the types: {', '.join(sorted(TYPES))}")
        properties[name] = {"type": kind}
    required = []
    for name in PLACEHOLDER.findall(path):
        properties.setdefault(name, {"type": "string"})
        required.append(name)
    return properties, required


def _endpoint(resource: str, raw, fields: dict[str, dict], app_key: str, label: str) -> dict:
    body = _object(raw, "Endpoint")
    name = body.get("name")
    if not isinstance(name, str) or not NAME_PART.match(name):
        raise _fail(f"Endpoint names in '{resource}' must be lowercase words, digits or underscores")
    method = str(body.get("method") or "GET").upper()
    if method != "GET":
        raise _fail(f"Endpoint '{name}': only GET is supported for now")
    path = body.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise _fail(f"Endpoint '{name}' needs a path that starts with /")
    result_path = body.get("result_path", "")
    if not isinstance(result_path, str) or not RESULT_PATH_RE.match(result_path):
        raise _fail(f"Endpoint '{name}' result_path must be dotted names such as products or data.items")
    properties, required = _params(body.get("params"), path, name)
    explicit = body.get("required") or []
    if not isinstance(explicit, list) or not set(explicit) <= set(properties):
        raise _fail(f"Endpoint '{name}' required must list its own params")
    required = list(dict.fromkeys(required + list(explicit)))
    description = body.get("description") or f"Read {label} through the {name} endpoint."
    return {
        "method": "GET", "path_template": path, "result_path": result_path,
        "tool_key": f"{app_key}.{resource}.{name}",
        "description": clean_description(description),
        "input_schema": {"type": "object", "additionalProperties": False, "properties": properties, "required": required},
        "output_schema": {"type": "array", "maxItems": 50,
                          "items": {"type": "object", "additionalProperties": False, "properties": fields}},
        # An API with no per-user data: the whole response is the answer, so no tenant filter applies.
        "requires_user_context": False, "public_aggregate": True,
    }


def _label(body: dict, key: str) -> str:
    aliases = body.get("alias") or []
    if (not isinstance(aliases, list) or len(aliases) > 10
            or not all(isinstance(item, str) and 0 < len(item) <= 40 for item in aliases)):
        raise _fail(f"Aliases of '{key}' must be a short list of words")
    return str(body.get("name") or key)[:200] + (f" (also called: {', '.join(aliases)})" if aliases else "")


def build_manifest(spec: dict, app_key: str) -> tuple[dict, dict]:
    """Return the cleaned spec to store and the validated source-managed manifest it produces."""

    resources = _object(_object(spec, "Endpoint list").get("resources"), "resources")
    if not 1 <= len(resources) <= MAX_RESOURCES:
        raise _fail(f"Add between 1 and {MAX_RESOURCES} resources")
    clean: dict = {}
    modules = []
    for key, raw in resources.items():
        if not isinstance(key, str) or not KEY_RE.match(key) or not NAME_PART.match(key):
            raise _fail(f"Resource key '{key}' must be lowercase words, digits or underscores")
        body = _object(raw, f"Resource '{key}'")
        fields = _fields(body.get("fields"), key)
        endpoints = body.get("endpoints")
        if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= MAX_ENDPOINTS:
            raise _fail(f"Resource '{key}' needs between 1 and {MAX_ENDPOINTS} endpoints")
        label = _label(body, key)
        routes = [_endpoint(key, item, fields, app_key, label) for item in endpoints]
        names = [route["tool_key"] for route in routes]
        if len(names) != len(set(names)):
            raise _fail(f"Endpoint names in '{key}' must be unique")
        modules.append({
            "key": key, "name": label, "description": str(body.get("description") or "")[:500],
            "supported_operations": ["read"], "readable_fields": list(fields), "writable_fields": [],
            "max_page_size": 50, "read_endpoints": routes,
        })
        clean[key] = {"name": str(body.get("name") or key)[:200], "description": str(body.get("description") or "")[:500],
                      "alias": body.get("alias") or [], "fields": body["fields"], "endpoints": endpoints}
    manifest = validate_manifest(
        {"contract_version": "1.0", "application": app_key, "managed_by": "application",
         "manifest_version": "custom", "modules": modules},
        expected_app_key=app_key, source_managed=True)
    return {"resources": clean}, manifest
