"""The signed-in user's own token for an app, for the calls made during one chat turn.

A custom API connection with ``user_auth`` reads data as each user: the embedded chat sets the
user's token here for its turn, and every source call in that turn sends it instead of the
connection's secret. Without one, such a connection refuses to call the app at all.
"""

from contextvars import ContextVar

from app.persistence.models import Connector

_token: ContextVar[str | None] = ContextVar("hub_user_token", default=None)


def signs_in_users(connector: Connector | None) -> bool:
    return bool(connector and connector.connector_type == "custom_api"
                and (connector.custom_spec or {}).get("user_auth"))


def push(token: str | None):
    return _token.set(token)


def reset(handle) -> None:
    _token.reset(handle)


def current() -> str | None:
    return _token.get()
