"""Validate admin-authored tool schemas. No remote refs and no nested free-form objects."""

import copy
import hashlib
import json
import math
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError, best_match

from app.errors import HubError
from app.privacy.pii_inspector import tree_contains_pii
from app.security.authorization import FORBIDDEN_ARGUMENT_KEYS

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")
TOOL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){1,4}$")
_PATH_SEGMENT = r"(?:[A-Za-z0-9._~-]+|\{[A-Za-z][A-Za-z0-9_]{0,40}\})"
PATH_RE = re.compile(rf"^/{_PATH_SEGMENT}(?:/{_PATH_SEGMENT})*$")
TYPES = {"string", "integer", "number", "boolean"}
_BOUNDS = ("minimum", "maximum", "minLength", "maxLength", "maxItems", "minItems")


def _check_metadata(schema):
    for key in ("title", "description"):
        if key in schema and (not isinstance(schema[key], str) or len(schema[key]) > 300):
            raise HubError("VALIDATION_FAILED", "Schema metadata must be bounded text", 422)
    if tree_contains_pii({key: schema[key] for key in ("title", "description", "enum") if key in schema}):
        raise HubError("PII_DETECTED", "Schema metadata is blocked by privacy policy", 422)


def require_tool_key(value: str) -> str:
    if not isinstance(value, str) or not TOOL_KEY_RE.match(value):
        raise HubError("VALIDATION_FAILED", "Tool name must be dotted lowercase words, for example app.orders.list", 422)
    return value


def mcp_name_for(tool_key: str, environment: str = "dev") -> str:
    name = require_tool_key(tool_key).replace(".", "__")
    if environment != "dev":
        suffix = "__" + environment
        if len(name + suffix) > 64:
            name = name[:40] + "__" + hashlib.sha256(name.encode()).hexdigest()[:8]
        name += suffix
    if len(name) > 64:
        raise HubError("VALIDATION_FAILED", "Tool name is too long for an MCP name", 422)
    return name


def validate_input_schema(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise HubError("VALIDATION_FAILED", "Input schema must be an object", 422)
    if schema.get("additionalProperties") is not False:
        raise HubError("VALIDATION_FAILED", "Input schema must set additionalProperties to false", 422)
    if set(schema) - {"type", "additionalProperties", "properties", "required", "title", "description"}:
        raise HubError("VALIDATION_FAILED", "Input schema uses unsupported keywords", 422)
    _check_metadata(schema)
    if "$ref" in json.dumps(schema) or "contentMediaType" in json.dumps(schema):
        raise HubError("VALIDATION_FAILED", "Input schema cannot use references or embedded media", 422)
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict) or len(properties) > 30:
        raise HubError("VALIDATION_FAILED", "Input schema properties are invalid", 422)
    required = schema.get("required") or []
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required) or not set(required) <= set(properties):
        raise HubError("VALIDATION_FAILED", "Input schema required list is invalid", 422)
    for name, spec in properties.items():
        # Identity, routing and approval arguments can never come from a model.
        if not NAME_RE.fullmatch(name) or name.lower() in FORBIDDEN_ARGUMENT_KEYS or not isinstance(spec, dict):
            raise HubError("VALIDATION_FAILED", "Input schema property is invalid", 422)
        if set(spec) - {"type", "enum", "minimum", "maximum", "minLength", "maxLength", "title", "description"}:
            raise HubError("VALIDATION_FAILED", "Input property uses unsupported keywords", 422)
        _check_metadata(spec)
        types = spec.get("type")
        types = types if isinstance(types, list) else [types]
        if (not types or not all(isinstance(item, str) for item in types)
                or len(types) != len(set(types)) or not set(types) <= (TYPES | {"null"})
                or len(set(types) & TYPES) != 1):
            raise HubError("VALIDATION_FAILED", "Input property must declare its scalar type", 422)
        kind = next(item for item in types if item != "null")
        if "enum" in spec:
            enum = spec["enum"]
            if not isinstance(enum, list) or not 1 <= len(enum) <= 30:
                raise HubError("VALIDATION_FAILED", "Enum is invalid", 422)
            if not all((isinstance(item, str) and len(item) <= 64 and item.isprintable())
                       or item is None or type(item) in {bool, int}
                       or (type(item) is float and math.isfinite(item)) for item in enum):
                raise HubError("VALIDATION_FAILED", "Enum values must be bounded scalars", 422)
            if not all(Draft202012Validator({"type": types}).is_valid(item) for item in enum):
                raise HubError("VALIDATION_FAILED", "Enum values must match the declared type", 422)
        if kind == "string" and "enum" not in spec:
            spec.setdefault("maxLength", 200)
        if kind in {"number", "integer"}:
            spec.setdefault("minimum", -1_000_000_000)
            spec.setdefault("maximum", 1_000_000_000)
        for bound in ("minimum", "maximum", "minLength", "maxLength"):
            if bound in spec:
                value = spec[bound]
                numeric = bound in {"minimum", "maximum"}
                try:
                    finite = math.isfinite(value)
                except (OverflowError, TypeError, ValueError):
                    finite = False
                if type(value) not in ({int, float} if numeric else {int}) or not finite:
                    raise HubError("VALIDATION_FAILED", "Schema bounds must be finite numbers with integer lengths", 422)
        cap = 1024 if name in {"ref", "record_ref", "proposal_ref"} else 512
        if spec.get("maxLength", 0) > cap:
            raise HubError("VALIDATION_FAILED", "String inputs exceed the supported length limit", 422)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise HubError("VALIDATION_FAILED", "Input schema is not valid JSON Schema", 422) from exc
    return schema


def validate_output_schema(schema: dict, allow_fields: list[str], max_records: int = 50) -> dict:
    schema = copy.deepcopy(schema)
    if not isinstance(schema, dict) or schema.get("type") != "array" or "$ref" in json.dumps(schema):
        raise HubError("VALIDATION_FAILED", "Output schema must be an array without references", 422)
    if set(schema) - {"type", "maxItems", "items", "title", "description"}:
        raise HubError("VALIDATION_FAILED", "Output schema uses unsupported keywords", 422)
    _check_metadata(schema)
    item = schema.get("items")
    if not isinstance(item, dict) or item.get("type") != "object" or item.get("additionalProperties") is not False:
        raise HubError("VALIDATION_FAILED", "Output records must have a closed object schema", 422)
    if set(item) - {"type", "additionalProperties", "properties", "required", "title", "description"}:
        raise HubError("VALIDATION_FAILED", "Output record schema uses unsupported keywords", 422)
    _check_metadata(item)
    fields = item.get("properties")
    if not isinstance(fields, dict) or set(fields) != set(allow_fields):
        raise HubError("VALIDATION_FAILED", "Output schema fields must match the output allowlist", 422)
    for name, spec in fields.items():
        if not NAME_RE.fullmatch(name) or not isinstance(spec, dict):
            raise HubError("VALIDATION_FAILED", "Output schema field is invalid", 422)
        types = spec.get("type")
        types = types if isinstance(types, list) else [types]
        if not types or not all(isinstance(item, str) for item in types) or not set(types) <= (TYPES | {"null"}):
            raise HubError("VALIDATION_FAILED", "Output fields must use explicit scalar types", 422)
        if set(spec) - {"type", "enum", "minimum", "maximum", "minLength", "maxLength", "title", "description"}:
            raise HubError("VALIDATION_FAILED", "Output property uses unsupported keywords", 422)
        _check_metadata(spec)
        if "string" in types:
            spec.setdefault("maxLength", 200)
            if not isinstance(spec["maxLength"], int) or not 1 <= spec["maxLength"] <= 2000:
                raise HubError("VALIDATION_FAILED", "Output string length is invalid", 422)
    if type(schema.get("maxItems", max_records)) is not int or not 1 <= schema.get("maxItems", max_records) <= max_records:
        raise HubError("VALIDATION_FAILED", "Output record limit exceeds source policy", 422)
    schema.setdefault("maxItems", max_records)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise HubError("VALIDATION_FAILED", "Output schema is invalid", 422) from exc
    return schema


def validate_output(schema: dict, data) -> None:
    try:
        Draft202012Validator(schema).validate(data)
    except (ValidationError, SchemaError) as exc:
        raise HubError("SCHEMA_MISMATCH", "Response does not match the reviewed output schema", 422) from exc


def project_output_schema(schema: dict, fields: list[str]) -> dict:
    result = copy.deepcopy(schema)
    item = result["items"]
    item["properties"] = {k: v for k, v in item["properties"].items() if k in fields}
    item["required"] = [k for k in item.get("required", []) if k in fields]
    return result


def describe_problem(error: ValidationError) -> str:
    """Name the argument and the broken rule, never the submitted value."""

    location = ".".join(str(part) for part in error.absolute_path)
    rule = error.validator
    where = f"'{location}'" if location else "arguments"
    if rule == "additionalProperties":
        return f"{where} contains an argument this tool does not accept"
    if rule == "required":
        match = re.match(r"^'([A-Za-z][A-Za-z0-9_]{0,63})' is a required property$", error.message)
        return f"missing required argument '{match.group(1)}'" if match else "a required argument is missing"
    if rule in _BOUNDS:
        return f"{where} must respect {rule} {error.validator_value}"
    if rule == "enum" and isinstance(error.validator_value, list):
        return f"{where} must be one of: {', '.join(str(item) for item in error.validator_value[:20])}"
    if rule == "type":
        return f"{where} must be of type {error.validator_value}"
    return f"{where} is invalid ({rule})"


def validate_arguments(schema: dict, arguments: dict) -> dict:
    if not isinstance(arguments, dict):
        raise HubError("VALIDATION_FAILED", "Tool arguments must be an object", 422)
    error = best_match(Draft202012Validator(schema).iter_errors(arguments))
    if error is not None:
        raise HubError("VALIDATION_FAILED", f"Input does not match the tool schema: {describe_problem(error)}", 422)
    return arguments


def validate_path_template(template: str, schema: dict) -> str:
    if not isinstance(template, str) or not PATH_RE.match(template) or ".." in template:
        raise HubError("VALIDATION_FAILED", "Path template is not an allowlisted relative path", 422)
    names = re.findall(r"\{([A-Za-z][A-Za-z0-9_]{0,40})\}", template)
    properties = schema.get("properties") or {}
    for name in names:
        if name not in properties:
            raise HubError("VALIDATION_FAILED", "Path placeholder is not an input property", 422)
    return template


def clean_description(text: str) -> str:
    """Admin-authored text the model will read. Obvious injection phrasing is refused."""

    if not isinstance(text, str):
        raise HubError("VALIDATION_FAILED", "Description is required", 422)
    cleaned = " ".join("".join(ch for ch in text if ch.isprintable()).split())
    lowered = cleaned.lower()
    banned = ("ignore previous", "ignore all previous", "system prompt", "disregard", "<|", "```")
    if any(token in lowered for token in banned) or len(cleaned) < 3:
        raise HubError("VALIDATION_FAILED", "Tool description was rejected; describe what the tool returns", 422)
    if tree_contains_pii(cleaned):
        raise HubError("PII_DETECTED", "Tool description is blocked by privacy policy", 422)
    return cleaned[:300]
