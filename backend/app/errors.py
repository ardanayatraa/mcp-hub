"""Stable, non-sensitive application errors."""


class HubError(Exception):
    """Fail-closed error whose message is safe to return to admins and models."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.trace_id: str | None = None
