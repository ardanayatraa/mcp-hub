"""The in-process limiter: kinds are isolated, short windows slide, daily windows count."""

import pytest
from app.errors import HubError
from app.security import rate_limit
from app.security.rate_limit import hit, reset_limits


@pytest.fixture(autouse=True)
def fresh():
    reset_limits()
    yield
    reset_limits()


def test_a_flood_of_one_kind_never_blocks_another(monkeypatch):
    monkeypatch.setattr(rate_limit, "_MAX_LONG", 50)
    for user in range(50):
        hit(f"gateway-day:app:{user}", 200, 86400)
    with pytest.raises(HubError, match="exhausted"):
        hit("gateway-day:app:new-user", 200, 86400)
    hit("login:203.0.113.9", 10, 60)  # admin sign-in still has room
    with pytest.raises(HubError, match="exhausted"):  # the full kind stays full until entries expire
        hit("gateway-day:other-app:1", 200, 86400)


def test_daily_windows_count_calls_and_reset_after_the_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock[0])
    for _ in range(3):
        hit("chat-day:app:7", 3, 86400)
    with pytest.raises(HubError, match="Too many"):
        hit("chat-day:app:7", 3, 86400)
    clock[0] += 86400
    hit("chat-day:app:7", 3, 86400)  # a new day


def test_short_windows_slide(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock[0])
    hit("login:x", 2, 60)
    clock[0] = 30
    hit("login:x", 2, 60)
    with pytest.raises(HubError):
        hit("login:x", 2, 60)
    clock[0] = 61  # the first call left the window
    hit("login:x", 2, 60)


def test_expired_entries_are_swept(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock[0])
    for user in range(100):
        hit(f"gateway:app:{user}", 5, 60)
    clock[0] = 200
    hit("gateway:app:late", 5, 60)
    assert len(rate_limit._tables["gateway"]) == 1
