"""Non-blocking per-process budgets for the single-worker P0 deployment."""

from contextlib import contextmanager
from threading import Lock

from app.errors import HubError

_counts = {}
_lock = Lock()


@contextmanager
def concurrency_slot(key: str, limit: int):
    with _lock:
        if _counts.get(key, 0) >= limit:
            raise HubError("RATE_LIMITED", "Concurrent request budget is exhausted", 429)
        _counts[key] = _counts.get(key, 0) + 1
    try:
        yield
    finally:
        with _lock:
            remaining = _counts[key] - 1
            if remaining:
                _counts[key] = remaining
            else:
                _counts.pop(key, None)
