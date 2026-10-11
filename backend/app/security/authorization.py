"""Hub policy checks. These add restrictions; they do not replace source authorization."""

import re

from sqlalchemy import select

from app.errors import HubError
from app.persistence.models import AdminApplicationScope, Connector, ToolDefinition

READ_ROLES = {"super_admin", "app_admin", "auditor"}
WRITE_ROLES = {"super_admin", "app_admin"}
ADMIN_ROLES = {"super_admin"}

RANK = {
    "blocked": 0,
    "secure_form_only": 0,
    "aggregate_only": 1,
    "allowed_for_ai": 2,
    "allowed": 2,
}

SENSITIVE_SEGMENTS = {
    "email",
    "e_mail",
    "phone",
    "phone_number",
    "mobile",
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "authorization",
    "national_id",
    "nik",
    "ssn",
    "full_name",
    "first_name",
    "last_name",
    "address",
    "dob",
    "date_of_birth",
    "user_id",
    "tenant_id",
    # One-time and secret codes are credentials, never data for a model.
    "otp",
    "one_time_password",
    "pin",
    "cvv",
    "cvc",
    "verification_code",
    "auth_code",
    "security_code",
    # Identifiers that point at one person or account.
    "msisdn",
    "card_number",
    "credit_card",
    "iban",
    "account_number",
    "passport",
    "npwp",
    "ktp",
}

FORBIDDEN_ARGUMENT_KEYS = {
    "user_id",
    "tenant_id",
    "role",
    "approved",
    "password",
    "token",
    "secret",
    "authorization",
    "base_url",
    "method",
    "path",
    "url",
}


def require_role(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise HubError("PERMISSION_DENIED", "Operation is not permitted", 403)


def allowed_app_ids(db, user) -> set[str] | None:
    if user.role == "super_admin":
        return None
    require_role(user.role, READ_ROLES)
    return set(db.scalars(select(AdminApplicationScope.app_id).where(AdminApplicationScope.user_id == user.id)))


def require_app_access(db, user, app_id: str) -> None:
    allowed = allowed_app_ids(db, user)
    if allowed is not None and app_id not in allowed:
        raise HubError("PERMISSION_DENIED", "Application is outside this administrator scope", 403)


def require_connector_access(db, user, connector_id: str):
    connector = db.get(Connector, connector_id)
    if connector is None:
        raise HubError("NOT_FOUND", "Connector was not found", 404)
    require_app_access(db, user, connector.app_id)
    return connector


def require_tool_access(db, user, tool_id: str):
    tool = db.get(ToolDefinition, tool_id)
    if tool is None:
        raise HubError("NOT_FOUND", "Tool was not found", 404)
    require_connector_access(db, user, tool.connector_id)
    return tool


def is_sensitive_path(field_path: str) -> bool:
    """True when any word, or run of two or three words, names personal or secret data.

    owner_email, contactPhone and customer_first_name match; emailed_at does not.
    """

    for part in str(field_path).split("."):
        words = [word for word in re.split(r"[_\-]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", part).lower()) if word]
        candidates = {part.lower(), *words}
        for size in (2, 3):
            candidates.update("_".join(words[index:index + size]) for index in range(len(words) - size + 1))
        if candidates & SENSITIVE_SEGMENTS:
            return True
    return False


def assert_not_weaker(current: str, proposed: str) -> None:
    if proposed not in RANK or current not in RANK:
        raise HubError("VALIDATION_FAILED", "Unknown field classification", 422)
    if RANK[proposed] > RANK[current]:
        raise HubError(
            "POLICY_LOCKED",
            "Field policy cannot be weaker than the developer or hub limit",
            422,
        )


def reject_forbidden_keys(value, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_ARGUMENT_KEYS:
                raise HubError(
                    "PRIVILEGE_ESCALATION",
                    "Argument contains a field the model is not allowed to set",
                    422,
                )
            reject_forbidden_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            reject_forbidden_keys(item, path)
