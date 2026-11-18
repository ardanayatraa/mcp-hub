"""Connector authentication: the Hub sends the app's secret as a bearer token. OAuth is Phase 3."""

from app.errors import HubError


def auth_headers(auth_type: str, secret: str, header_name: str | None = None) -> dict[str, str]:
    if auth_type == "none":
        return {}
    if auth_type == "header":
        # A custom API key header, such as X-API-Key; the name is stored with the endpoint list, the key encrypted.
        if not header_name:
            raise HubError("VALIDATION_FAILED", "The API key header needs a name", 422)
        return {header_name: secret}
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    raise HubError("VALIDATION_FAILED", "Connector authentication type is not supported", 422)
