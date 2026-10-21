"""In-process limits for login, tool calls, chat and the model gateway. Phase 2 can move the counters to Redis.

Each kind of limit (the text before the first ':' in its key: login, mfa, tool, gateway-day...) has its
own table, so a flood of one kind (many end users of one app, say) never blocks another (admin sign-in).
Windows under an hour slide (one timestamp per call); daily-length windows count in a fixed window,
which keeps one small counter per user however many calls it allows.
"""

import time
from collections import deque
from threading import Lock

from app.errors import HubError

LONG_WINDOW = 3600
_MAX_SHORT = 10_000  # sliding buckets per kind
_MAX_LONG = 200_000  # fixed-window counters per kind (about 100 bytes each)

# kind -> key -> (deque of call times, window) | [count, window start, window]
_tables: dict[str, dict[str, object]] = {}
_last_cleanup: dict[str, float] = {}
_lock = Lock()


def _expired(entry, now: float) -> bool:
    if isinstance(entry, list):
        return now - entry[1] >= entry[2]
    events, window = entry
    return not events or now - events[-1] > window


def _sweep(kind: str, table: dict, now: float) -> None:
    for name in [name for name, entry in table.items() if _expired(entry, now)]:
        del table[name]
    _last_cleanup[kind] = now


def hit(key: str, limit: int, window_seconds: int) -> None:
    kind = key.split(":", 1)[0]
    long = window_seconds >= LONG_WINDOW
    cap = _MAX_LONG if long else _MAX_SHORT
    now = time.monotonic()
    with _lock:
        table = _tables.setdefault(kind, {})
        if now - _last_cleanup.get(kind, 0.0) >= 60 or len(table) >= cap:
            _sweep(kind, table, now)
        entry = table.get(key)
        if entry is not None and isinstance(entry, list) != long:  # the window setting changed
            entry = table.pop(key) and None
        if entry is None:
            if len(table) >= cap:
                raise HubError("RATE_LIMITED", "Request budget is exhausted", 429)
            entry = [0, now, window_seconds] if long else (deque(), window_seconds)
            table[key] = entry
        if long:
            if now - entry[1] >= window_seconds:
                entry[0], entry[1] = 0, now
            if entry[0] >= limit:
                raise HubError("RATE_LIMITED", "Too many requests", 429)
            entry[0] += 1
            return
        bucket = entry[0]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HubError("RATE_LIMITED", "Too many requests", 429)
        bucket.append(now)


def reset_limits() -> None:
    with _lock:
        _tables.clear()
        _last_cleanup.clear()
