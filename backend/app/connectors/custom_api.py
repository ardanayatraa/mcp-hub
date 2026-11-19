"""Turn an admin-written endpoint list into the same contract an application would publish.

The admin names the resources and read endpoints of any HTTP API; the Hub validates them and
builds a source-managed contract, so permissions, field policy, privacy checks, tool switches
and audit work exactly as they do for a published manifest. Only GET is supported for now.
"""

import re

from app.connectors.contracts import FIELD_RE, KEY_RE, validate_manifest
from app.errors import HubError
from app.tools.schema_tools import NAME_RE, PATH_RE, TYPES, clean_description

NAME_PART = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RESULT_PATH_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_]{0,39}(?:\.[A-Za-z][A-Za-z0-9_]{0,39}){0,3})?$")
PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]{0,40})\}")
MAX_RESOURCES, MAX_ENDPOINTS, MAX_FIELDS, MAX_PARAMS = 20, 30, 40, 20
HEADER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,40}$")
# Headers the Hub or the transport owns, or that would carry another identity.
RESERVED_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "host", "content-length",
                    "content-type", "connection", "transfer-encoding", "upgrade", "te", "trailer", "accept",
                    "idempotency-key", "x-request-id", "x-hub-assertion", "x-hub-delegation", "x-forwarded-for",
                    "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded"}


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


def header_name(raw, label: str = "Header") -> str:
    if not isinstance(raw, str) or not HEADER_NAME.match(raw) or raw.lower() in RESERVED_HEADERS:
        raise _fail(f"{label} must be a plain header name that is not one the Hub controls")
    return raw


def static_headers(raw, endpoint: str) -> dict[str, str]:
    """Fixed, non-secret headers sent with one endpoint (for example Accept-Language). Keys belong in the connection."""

    if raw in (None, {}, []):
        return {}
    if isinstance(raw, list):
        raw = {item.get("name"): item.get("value") for item in raw if isinstance(item, dict)}
    raw = _object(raw, f"Headers of '{endpoint}'")
    if len(raw) > 10:
        raise _fail(f"Endpoint '{endpoint}' has too many headers")
    result = {}
    for name, value in raw.items():
        header_name(name, f"Header '{name}' of '{endpoint}'")
        if not isinstance(value, str) or not value or len(value) > 200 or not value.isprintable():
            raise _fail(f"Header '{name}' of '{endpoint}' needs a short text value")
        result[name] = value
    return result


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
    headers = static_headers(body.get("headers"), name)
    return {
        "method": "GET", "path_template": path, "result_path": result_path,
        **({"headers": headers} if headers else {}),
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


def _path(value, label: str) -> str:
    if not isinstance(value, str) or not PATH_RE.match(value) or ".." in value or "{" in value:
        raise _fail(f"{label} must be a fixed path that starts with /")
    return value


def user_auth(raw) -> dict | None:
    """How a user signs in to the app: the Hub posts the login form and keeps the token it returns.

    {"login_path": "/api/login", "fields": ["email", "password"], "token_path": "token",
     "me_path": "/api/me", "name_path": "name"}. The token is then sent as a bearer token on every
    call made for that user, so the app itself decides what each user may read.

    Without a login_path the Hub shows no form: the page the chat sits on hands over the token its user already
    has (``data-token``), and me_path, if given, only supplies the name. {} means exactly that.
    """

    if raw is None:
        return None
    body = _object(raw, "user_auth")
    if body.get("login_path") is None:
        result = {"host_token": True}
        if body.get("me_path") is not None:
            result["me_path"] = _path(body["me_path"], "user_auth me_path")
            name_path = body.get("name_path") or "name"
            if not isinstance(name_path, str) or not name_path or not RESULT_PATH_RE.match(name_path):
                raise _fail("user_auth name_path must be dotted names such as name or data.name")
            result["name_path"] = name_path
        return result
    fields = body.get("fields") or ["email", "password"]
    if (not isinstance(fields, list) or not 1 <= len(fields) <= 4 or len(set(fields)) != len(fields)
            or not all(isinstance(name, str) and NAME_RE.fullmatch(name) for name in fields)):
        raise _fail("user_auth fields must be 1 to 4 field names, such as email and password")
    token_path = body.get("token_path") or "token"
    if not isinstance(token_path, str) or not token_path or not RESULT_PATH_RE.match(token_path):
        raise _fail("user_auth token_path must be dotted names such as token or data.access_token")
    result = {"login_path": _path(body.get("login_path"), "user_auth login_path"), "fields": fields,
              "token_path": token_path}
    if body.get("me_path") is not None:
        result["me_path"] = _path(body["me_path"], "user_auth me_path")
        name_path = body.get("name_path") or "name"
        if not isinstance(name_path, str) or not name_path or not RESULT_PATH_RE.match(name_path):
            raise _fail("user_auth name_path must be dotted names such as name or data.name")
        result["name_path"] = name_path
    return result


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _records(document, prefix: str = "", depth: int = 0):
    """Where the records of a JSON response sit: (result_path, records), or None."""

    if isinstance(document, list):
        return (prefix, document) if document and all(isinstance(item, dict) for item in document) else None
    if not isinstance(document, dict):
        return None
    for key, value in document.items():
        if RESULT_PATH_RE.match(_join(prefix, key)) and isinstance(value, list) and value \
                and all(isinstance(item, dict) for item in value):
            return _join(prefix, key), value
    if depth < 3:
        for key, value in document.items():
            if isinstance(value, dict) and RESULT_PATH_RE.match(_join(prefix, key)):
                found = _records(value, _join(prefix, key), depth + 1)
                if found:
                    return found
    return (prefix, [document]) if any(not isinstance(value, (dict, list)) for value in document.values()) else None


def _scalar_type(value) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _shown(value):
    from app.privacy.pii_inspector import tree_contains_pii

    if isinstance(value, (dict, list)):
        return "{…}" if isinstance(value, dict) else "[…]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return "••••" if tree_contains_pii(text) else (text if len(text) <= 40 else text[:40] + "…")


def analyze(document) -> dict:
    """What an admin needs to write the endpoint: the result path, the scalar fields with types, and a masked sample."""

    from app.security.authorization import is_sensitive_path

    found = _records(document)
    if found is None:
        return {"result_path": None, "fields": {}, "sample": [], "count": 0}
    path, records = found
    kinds: dict[str, set] = {}
    nullable: set = set()
    for record in records[:30]:
        for name, value in list(record.items())[:80]:
            if value is None:
                nullable.add(name)
                kinds.setdefault(name, set())
                continue
            kind = _scalar_type(value)
            if kind:
                kinds.setdefault(name, set()).add(kind)
    fields = {}
    for name, found_kinds in kinds.items():
        if not found_kinds or not FIELD_RE.match(name) or not NAME_RE.fullmatch(name):
            continue
        kind = "number" if found_kinds <= {"integer", "number"} and "number" in found_kinds else sorted(found_kinds)[0]
        fields[name] = kind + ("?" if name in nullable else "")
        if len(fields) >= MAX_FIELDS:
            break
    return {"result_path": path, "fields": fields, "count": len(records),
            "sensitive": [name for name in fields if is_sensitive_path(name)],
            "sample": [{key: _shown(value) for key, value in list(record.items())[:20]} for record in records[:2]]}


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
    stored: dict = {"resources": clean}
    signin = user_auth(spec.get("user_auth"))
    if signin:
        stored["user_auth"] = signin
    if spec.get("auth_header"):
        stored["auth_header"] = header_name(spec["auth_header"], "The API key header")
    return stored, manifest
