"""In-process limits for login and tool calls. Phase 2 can move the counters to Redis."""

import time
from collections import deque
from threading import Lock

from app.errors import HubError

_buckets: dict[str, tuple[deque, int]] = {}
_lock = Lock()
_last_cleanup = 0.0
_MAX_BUCKETS = 10000


def hit(key: str, limit: int, window_seconds: int) -> None:
    global _last_cleanup
    now = time.monotonic()
    with _lock:
        if now - _last_cleanup >= 60 or len(_buckets) >= _MAX_BUCKETS:
            expired = [name for name, (events, window) in _buckets.items() if not events or now - events[-1] > window]
            for name in expired:
                _buckets.pop(name, None)
            _last_cleanup = now
        if key not in _buckets:
            if len(_buckets) >= _MAX_BUCKETS:
                raise HubError("RATE_LIMITED", "Request budget is exhausted", 429)
            _buckets[key] = (deque(), window_seconds)
        bucket, _ = _buckets[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HubError("RATE_LIMITED", "Too many requests", 429)
        bucket.append(now)


def reset_limits() -> None:
    with _lock:
        _buckets.clear()
