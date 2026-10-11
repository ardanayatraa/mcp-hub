"""Validate a developer-published capability manifest. It is an allowlist, not an ORM dump."""

import hashlib
import json
import re

from app.connectors.endpoint_policy import normalize_endpoints, normalize_write_endpoints
from app.errors import HubError
from app.security.authorization import is_sensitive_path
from app.tools.schema_tools import clean_description, require_tool_key

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
FIELD_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,62}$")
OPERATIONS = {"read", "create", "update", "delete"}
CLASSIFICATIONS = {"blocked", "secure_form_only", "aggregate_only", "allowed_for_ai", "allowed"}


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise HubError("SCHEMA_MISMATCH", f"{label} must be an object", 422)
    return value


def validate_manifest(document: dict, *, expected_app_key: str, source_managed: bool = False) -> dict:
    body = _object(document, "Manifest")
    if body.get("contract_version") != "1.0":
        raise HubError("SCHEMA_MISMATCH", "Unsupported connector contract version", 422)
    if body.get("application") != expected_app_key:
        raise HubError("SCHEMA_MISMATCH", "Manifest application key does not match the connector", 422)
    if source_managed and body.get("managed_by") != "application":
        raise HubError("SCHEMA_MISMATCH", "The source must publish its saved application permissions", 422)
    modules = body.get("modules")
    if not isinstance(modules, list) or not (0 if source_managed else 1) <= len(modules) <= 100:
        raise HubError("SCHEMA_MISMATCH", "Manifest does not publish any modules", 422)
    normalized = []
    seen = set()
    for raw in modules:
        module = _object(raw, "Module")
        key = module.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise HubError("SCHEMA_MISMATCH", "Module key is not a stable identifier", 422)
        if key in seen:
            raise HubError("SCHEMA_MISMATCH", "Module keys must be unique", 422)
        seen.add(key)
        operations = module.get("supported_operations") or []
        if not isinstance(operations, list) or not all(isinstance(item, str) for item in operations) or not set(operations) <= OPERATIONS:
            raise HubError("SCHEMA_MISMATCH", "Module operations are not in the contract", 422)
        readable = module.get("readable_fields") or []
        writable = module.get("writable_fields") or []
        for collection, label in ((readable, "readable"), (writable, "writable")):
            if not isinstance(collection, list) or not all(isinstance(item, str) and FIELD_RE.match(item) for item in collection):
                raise HubError("SCHEMA_MISMATCH", f"Module {label} fields are invalid", 422)
            if len(collection) > 100 or len(collection) != len(set(collection)):
                raise HubError("SCHEMA_MISMATCH", "Module fields must be unique and bounded", 422)
        page = module.get("max_page_size", 50)
        if type(page) is not int or page < 1 or page > 50:
            raise HubError("SCHEMA_MISMATCH", "max_page_size must be between 1 and 50", 422)
        developer_policies = module.get("field_policies") or {}
        if not isinstance(developer_policies, dict):
            raise HubError("SCHEMA_MISMATCH", "field_policies must be an object", 422)
        reads = normalize_endpoints(module.get("read_endpoints", []), readable, page)
        writes = normalize_write_endpoints(
            module.get("write_endpoints"), operations=operations, readable_fields=readable,
            writable_fields=writable, taken={(route["method"], route["path_template"]) for route in reads})
        if source_managed:
            for raw_routes, routes in ((module.get("read_endpoints", []), reads),
                                       (module.get("write_endpoints") or [], writes)):
                for raw_route, route in zip(raw_routes, routes, strict=True):
                    tool_key = require_tool_key(raw_route.get("tool_key") or "")
                    if not tool_key.startswith(f"{expected_app_key}.{key}."):
                        raise HubError("SCHEMA_MISMATCH", "Source tool keys must belong to their application and module", 422)
                    route["tool_key"] = tool_key
                    route["description"] = clean_description(raw_route.get("description") or f"Use the reviewed {key} route.")
        entry = {
            "key": key,
            "name": str(module.get("name") or key)[:200],
            "description": str(module.get("description") or "")[:500],
            "schema_version": str(module.get("schema_version") or "1.0")[:32],
            "supported_operations": list(operations),
            "readable_fields": list(readable),
            "writable_fields": list(writable),
            "filters": module.get("filters") if isinstance(module.get("filters"), dict) else {},
            "max_page_size": page,
            "risk": module.get("risk") if isinstance(module.get("risk"), dict) else {},
            "field_policies": {str(k): str(v) for k, v in developer_policies.items()},
            # Read is enableable when published; a write only when the source declares its route.
            "enableable_operations": [op for op in ("read", "create", "update", "delete")
                                      if op in operations and (op == "read" or any(w["operation"] == op for w in writes))],
            "read_endpoints": reads,
        }
        if writes:
            # Added only when present so existing manifests keep their hash.
            entry["write_endpoints"] = writes
        normalized.append(entry)
    if source_managed:
        keys = [route["tool_key"] for module in normalized
                for route in module["read_endpoints"] + module.get("write_endpoints", [])]
        if len(keys) != len(set(keys)):
            raise HubError("SCHEMA_MISMATCH", "Source tool keys must be unique", 422)
    canonical = json.dumps({"application": expected_app_key, "modules": normalized}, sort_keys=True)
    result = {
        "contract_version": "1.0",
        "application": expected_app_key,
        "manifest_version": str(body.get("manifest_version") or "unversioned")[:64],
        "modules": normalized,
        "manifest_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
    if source_managed:
        result["managed_by"] = "application"
    return result


def initial_field_policies(module: dict) -> list[dict]:
    """The developer baseline: sensitive names and declared blocks are locked."""

    policies = []
    developer = module.get("field_policies") or {}
    for field in module["readable_fields"]:
        if is_sensitive_path(field):
            classification, locked = "blocked", True
        else:
            classification = developer.get(field, "allowed_for_ai")
            if classification not in CLASSIFICATIONS:
                classification = "blocked"
            locked = classification in {"blocked", "secure_form_only"}
        policies.append({"field_path": field, "classification": classification, "source": "developer", "locked": locked})
    return policies


def developer_baseline(module: dict) -> dict[str, dict]:
    return {policy["field_path"]: policy for policy in initial_field_policies(module)}
