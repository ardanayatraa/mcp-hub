"""Limits for login, tool calls, chat and the model gateway.

Each kind of limit (the text before the first ':' in its key: login, mfa, tool, gateway-day...) has its
own table, so a flood of one kind (many end users of one app, say) never blocks another (admin sign-in).
Windows under an hour slide (one timestamp per call); daily-length windows count in a fixed window,
which keeps one small counter per user however many calls it allows.
"""

import hashlib
import secrets
import time
from collections import deque
from functools import lru_cache
from threading import Lock

from redis import Redis, RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.config import get_settings
from app.errors import HubError

LONG_WINDOW = 3600
_MAX_SHORT = 10_000  # sliding buckets per kind
_MAX_LONG = 200_000  # fixed-window counters per kind (about 100 bytes each)

# kind -> key -> (deque of call times, window) | [count, window start, window]
_tables: dict[str, dict[str, object]] = {}
_last_cleanup: dict[str, float] = {}
_lock = Lock()

# A single atomic operation, including the per-kind cardinality bound. Redis TIME
# avoids different worker clocks. Denied requests never extend the window.
_SCRIPT = """
local t = redis.call('TIME')
local now = tonumber(t[1])*1000 + tonumber(t[2])/1000
local duration, limit, cap = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local long = ARGV[4] == '1'
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('EXISTS', KEYS[1]) == 0 then
    if redis.call('ZCARD', KEYS[2]) >= cap then return 2 end
end
if long then
    local n = tonumber(redis.call('GET', KEYS[1]) or '0')
    if n >= limit then return 1 end
    redis.call('INCR', KEYS[1])
    if n == 0 then redis.call('PEXPIRE', KEYS[1], duration) end
    local ttl = redis.call('PTTL', KEYS[1])
    redis.call('ZADD', KEYS[2], now+ttl, KEYS[1])
else
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now-duration)
    if redis.call('ZCARD', KEYS[1]) >= limit then return 1 end
    redis.call('ZADD', KEYS[1], now, ARGV[5])
    redis.call('PEXPIRE', KEYS[1], duration)
    redis.call('ZADD', KEYS[2], now+duration, KEYS[1])
end
redis.call('PEXPIRE', KEYS[2], math.max(duration, redis.call('PTTL', KEYS[2])))
return 0
"""


@lru_cache(maxsize=4)
def _redis(url: str, password: str) -> Redis:
    # Exceptions are never returned to clients: Redis URLs can contain secrets.
    return Redis.from_url(url, password=password or None, socket_connect_timeout=1,
                          socket_timeout=1, retry_on_timeout=False, retry=Retry(NoBackoff(), 0), max_connections=64)


def check_backend() -> None:
    settings = get_settings()
    if settings.rate_limit_backend == "redis":
        try:
            if not _redis(settings.rate_limit_redis_url, settings.rate_limit_redis_password).ping():
                raise RedisError()
        except (RedisError, ValueError, TypeError):
            raise HubError("UNAVAILABLE", "Request limits are unavailable", 503) from None


def _shared_hit(key: str, limit: int, window_seconds: int) -> None:
    settings = get_settings()
    kind = hashlib.sha256(key.split(":", 1)[0].encode()).hexdigest()[:24]
    group = settings.rate_limit_namespace+":{"+kind+"}:"
    digest = hashlib.sha256(f"{key}|{window_seconds}".encode()).hexdigest()
    long = window_seconds >= LONG_WINDOW
    try:
        result = _redis(settings.rate_limit_redis_url, settings.rate_limit_redis_password).eval(
            _SCRIPT, 2, group+digest, group+"index", window_seconds*1000, limit,
            _MAX_LONG if long else _MAX_SHORT, int(long), secrets.token_hex(16))
    except (RedisError, ValueError, TypeError):
        # A backend outage must never silently reset all users' budgets.
        raise HubError("UNAVAILABLE", "Request limits are unavailable", 503) from None
    if result == 2:
        raise HubError("RATE_LIMITED", "Request budget is exhausted", 429)
    if result != 0:
        raise HubError("RATE_LIMITED", "Too many requests", 429)


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
    if limit < 1 or window_seconds < 1:
        raise ValueError("Rate limit and duration must be positive")
    if get_settings().rate_limit_backend == "redis":
        _shared_hit(key, limit, window_seconds)
        return
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
