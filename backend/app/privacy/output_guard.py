"""Drop anything that was not allowlisted, then fail closed if PII remains."""

from app.errors import HubError
from app.privacy.pii_inspector import tree_contains_pii
from app.security.authorization import is_sensitive_path

AI_SAFE = {"allowed", "allowed_for_ai"}


def _classification(path: str, policies: dict[str, str]) -> str:
    if is_sensitive_path(path):
        return "blocked"
    return policies.get(path, "blocked")


def project_record(record: dict, allow_fields: list[str], policies: dict[str, str]) -> dict:
    projected: dict = {}
    for field in allow_fields:
        if field not in record:
            continue
        if _classification(field, policies) not in AI_SAFE:
            continue
        value = record[field]
        if isinstance(value, (dict, list)) or tree_contains_pii(value):
            raise HubError("PII_DETECTED", "Response blocked by privacy policy", 422)
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise HubError("SCHEMA_MISMATCH", "Response field has an unsupported type", 422)
        projected[field] = value
    return projected


def guard_output(payload, allow_fields: list[str], policies: dict[str, str]):
    """Return minimized rows, or raise if an allowlisted value still looks sensitive."""

    if isinstance(payload, list):
        if not all(isinstance(row, dict) for row in payload):
            raise HubError("VALIDATION_FAILED", "Tool output records must be objects", 422)
        return [project_record(row, allow_fields, policies) for row in payload]
    if isinstance(payload, dict):
        return project_record(payload, allow_fields, policies)
    raise HubError("VALIDATION_FAILED", "Tool output is not JSON", 422)


def guard_receipt(rows: list[dict], allow_fields: list[str]) -> list[dict]:
    """Write receipts are not module fields; keep declared, non-sensitive scalars only."""

    fields = [field for field in allow_fields if not is_sensitive_path(field)]
    return guard_output(rows, fields, {field: "allowed_for_ai" for field in fields})
