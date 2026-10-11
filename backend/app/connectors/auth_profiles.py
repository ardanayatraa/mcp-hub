"""P0 connector authentication: API key or scoped bearer. OAuth is Phase 3."""

from app.errors import HubError


def auth_headers(auth_type: str, secret: str) -> dict[str, str]:
    if auth_type == "api_key":
        return {"X-API-Key": secret}
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    raise HubError("VALIDATION_FAILED", "Connector authentication type is not supported in Phase 1", 422)
