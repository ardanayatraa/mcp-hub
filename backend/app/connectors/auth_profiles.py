"""Connector authentication: the Hub sends the app's secret as a bearer token. OAuth is Phase 3."""

from app.errors import HubError


def auth_headers(auth_type: str, secret: str) -> dict[str, str]:
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    raise HubError("VALIDATION_FAILED", "Connector authentication type is not supported", 422)
