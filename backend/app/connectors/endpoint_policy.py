"""Source-published fixed routes are the upper bound for every tool mapping.

A connected application lists the exact routes the Hub may call in its manifest:
``read_endpoints`` for reads (GET, or POST marked ``safe_query``) and, optionally,
``write_endpoints`` for create/update/delete requests. Tools can only bind to these.
"""

from app.errors import HubError
from app.security.authorization import is_sensitive_path
from app.tools.schema_tools import (
    validate_arguments,
    validate_input_schema,
    validate_output_schema,
    validate_path_template,
)

WRITE_OPERATIONS = ("create", "update", "delete")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PAGE_PARAMETERS = {"limit", "cursor"}


def endpoint_key(method: str, path: str) -> str:
    return f"{method} {path}"


def _output_fields(output: dict) -> list[str]:
    if not isinstance(output, dict):
        return []
    items = output.get("items")
    properties = items.get("properties") if isinstance(items, dict) else None
    return list(properties) if isinstance(properties, dict) else []


def _tenant_field(route: dict, *, required: bool) -> str | None:
    tenant = route.get("tenant_field")
    if required and (not isinstance(tenant, str) or not tenant.isidentifier()):
        raise HubError("SCHEMA_MISMATCH", "Private endpoints must declare their tenant field", 422)
    return tenant if required else None


def normalize_endpoints(raw, readable_fields: list[str], max_page_size: int) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 100:
        raise HubError("SCHEMA_MISMATCH", "Read endpoint definitions are invalid", 422)
    seen = set()
    result = []
    for route in raw:
        if not isinstance(route, dict):
            raise HubError("SCHEMA_MISMATCH", "Read endpoint definition is invalid", 422)
        method = route.get("method", "GET")
        if method not in {"GET", "POST"} or (method == "POST" and route.get("safe_query") is not True):
            raise HubError("SCHEMA_MISMATCH", "Source must explicitly review every read-only query", 422)
        schema = validate_input_schema(route.get("input_schema", {}))
        path = validate_path_template(route.get("path_template"), schema)
        if (method, path) in seen:
            raise HubError("SCHEMA_MISMATCH", "Duplicate source read endpoint", 422)
        seen.add((method, path))
        requires_user = route.get("requires_user_context", True)
        if type(requires_user) is not bool:
            raise HubError("SCHEMA_MISMATCH", "Source authorization requirement is invalid", 422)
        tenant = _tenant_field(route, required=requires_user)
        if not requires_user and route.get("public_aggregate") is not True:
            raise HubError("SCHEMA_MISMATCH", "Unscoped routes must be source-approved public aggregates", 422)
        output = route.get("output_schema", {})
        fields = _output_fields(output)
        if not fields or not set(fields) <= set(readable_fields):
            raise HubError("SCHEMA_MISMATCH", "Endpoint output is outside the module field allowlist", 422)
        output = validate_output_schema(output, fields, max_page_size)
        result.append({"method": method, "path_template": path, "input_schema": schema,
                       "output_schema": output, "requires_user_context": requires_user,
                       "tenant_field": tenant, "safe_query": method == "POST", "public_aggregate": not requires_user})
    return result


def normalize_write_endpoints(raw, *, operations: list[str], readable_fields: list[str],
                              writable_fields: list[str], taken: set[tuple[str, str]]) -> list[dict]:
    """Validate optional create/update/delete routes. The source still decides every write."""

    if raw is None or raw == []:
        return []
    if not isinstance(raw, list) or len(raw) > 50:
        raise HubError("SCHEMA_MISMATCH", "Write endpoint definitions are invalid", 422)
    seen = set(taken)
    declared = set(readable_fields) | set(writable_fields)
    result = []
    for route in raw:
        if not isinstance(route, dict):
            raise HubError("SCHEMA_MISMATCH", "Write endpoint definition is invalid", 422)
        operation = route.get("operation")
        if operation not in WRITE_OPERATIONS or operation not in operations:
            raise HubError("SCHEMA_MISMATCH", "Write endpoint operation is not supported by the module", 422)
        method = route.get("method")
        if method not in WRITE_METHODS:
            raise HubError("SCHEMA_MISMATCH", "Write endpoint method is not allowed", 422)
        schema = validate_input_schema(route.get("input_schema", {}))
        path = validate_path_template(route.get("path_template"), schema)
        if (method, path) in seen:
            raise HubError("SCHEMA_MISMATCH", "Duplicate source endpoint", 422)
        seen.add((method, path))
        for name in schema.get("properties", {}):
            if name not in declared or is_sensitive_path(name):
                raise HubError("SCHEMA_MISMATCH", "Write inputs must be declared, non-sensitive module fields", 422)
        if route.get("requires_user_context", True) is not True:
            raise HubError("SCHEMA_MISMATCH", "Write endpoints must require verified user context", 422)
        tenant = _tenant_field(route, required=True)
        output = route.get("output_schema", {})
        fields = _output_fields(output)
        if not fields or any(is_sensitive_path(field) for field in fields):
            raise HubError("SCHEMA_MISMATCH", "Write receipts must declare non-sensitive fields", 422)
        output = validate_output_schema(output, fields, 50)
        result.append({"operation": operation, "method": method, "path_template": path,
                       "input_schema": schema, "output_schema": output, "requires_user_context": True,
                       "tenant_field": tenant, "safe_query": False, "public_aggregate": False})
    return result


def module_endpoints(module) -> list[dict]:
    """Every reviewed route of a stored module, tagged with its kind."""

    manifest = module.manifest_json or {}
    reads = [{**route, "kind": "read", "key": endpoint_key(route["method"], route["path_template"])}
             for route in manifest.get("read_endpoints", [])]
    writes = [{**route, "kind": "write", "key": endpoint_key(route["method"], route["path_template"])}
              for route in manifest.get("write_endpoints", [])]
    return reads + writes


def find_endpoint(module, method: str, path: str) -> dict | None:
    return next((route for route in module_endpoints(module)
                 if route["method"] == method and route["path_template"] == path), None)


def reviewed_endpoint(module, mapping, arguments: dict | None = None) -> dict:
    route = find_endpoint(module, mapping.method, mapping.path_template)
    if route is None:
        raise HubError("PERMISSION_DENIED", "Endpoint is not in the source-reviewed allowlist", 403)
    if (route["requires_user_context"] != mapping.requires_user_context or route["tenant_field"] != mapping.tenant_field
            or route["safe_query"] != mapping.safe_query):
        raise HubError("POLICY_LOCKED", "Mapping cannot weaken source authorization requirements", 422)
    if arguments is not None:
        validate_arguments(route["input_schema"], arguments)
    return route


def is_dataset_candidate(route: dict) -> bool:
    """A read route that returns many records and needs no lookup argument."""

    required = set(route["input_schema"].get("required") or [])
    return (route["kind"] == "read" and route["output_schema"].get("maxItems", 50) > 1
            and not required - PAGE_PARAMETERS)


def dataset_endpoint(module, preferred: str | None = None) -> dict | None:
    """The read route that feeds reports: the admin's choice, else the best list route."""

    routes = [route for route in module_endpoints(module) if is_dataset_candidate(route)]
    if preferred:
        return next((route for route in routes if route["key"] == preferred), None)

    def rank(route: dict):
        properties = route["input_schema"].get("properties", {})
        return ("limit" not in properties, "cursor" not in properties,
                -len(_output_fields(route["output_schema"])), route["method"] != "GET", route["key"])

    return min(routes, key=rank) if routes else None


def pagination_for(route: dict) -> dict[str, str]:
    properties = route["input_schema"].get("properties", {})
    result = {}
    if properties.get("limit", {}).get("type") == "integer":
        result["limit_parameter"] = "limit"
    if properties.get("cursor", {}).get("type") == "string":
        result["cursor_parameter"] = "cursor"
    return result
