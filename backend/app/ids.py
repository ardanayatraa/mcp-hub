"""Identifiers that are safe to put in logs."""

from datetime import datetime, timezone
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive timestamps. Values written by this app are UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_trace_id() -> str:
    return "tr_" + uuid4().hex


def new_request_id() -> str:
    return "req_" + uuid4().hex[:20]
