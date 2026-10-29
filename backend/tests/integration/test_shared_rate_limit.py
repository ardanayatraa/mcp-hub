"""Real Redis, disposable server/namespace; never flush an operator's database."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from app.config import get_settings
from app.errors import HubError
from app.security import rate_limit
from redis import Redis, RedisError


@pytest.fixture()
def shared(monkeypatch, tmp_path):
    url = os.environ.get("HUB_TEST_REDIS_URL")
    process = None
    if not url:
        executable = shutil.which("redis-server")
        windows = Path("C:/laragon/bin/redis/redis-x64-5.0.14.1/redis-server.exe")
        if executable is None and windows.is_file():
            executable = str(windows)
        if executable is None:
            pytest.skip("Install redis-server or set HUB_TEST_REDIS_URL to test shared limits")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"redis://127.0.0.1:{port}/0"
        process = subprocess.Popen(
            [executable, "--bind", "127.0.0.1", "--port", str(port), "--save", "", "--appendonly", "no",
             "--maxmemory-policy", "noeviction"], cwd=tmp_path, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    client = Redis.from_url(url, socket_connect_timeout=.5, socket_timeout=.5)
    deadline = time.monotonic()+5
    while True:
        try:
            client.ping()
            break
        except RedisError:
            if time.monotonic() > deadline:
                if process:
                    process.terminate()
                    process.wait(timeout=5)
                pytest.fail("Disposable Redis did not start")
            time.sleep(.05)
    namespace = "test-"+uuid.uuid4().hex
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("RATE_LIMIT_REDIS_URL", url)
    monkeypatch.setenv("RATE_LIMIT_REDIS_PASSWORD", "")
    monkeypatch.setenv("RATE_LIMIT_NAMESPACE", namespace)
    get_settings.cache_clear()
    try:
        yield client
    finally:
        for key in client.scan_iter(namespace+":*"):
            client.delete(key)
        client.close()
        rate_limit._redis.cache_clear()
        get_settings.cache_clear()
        if process:
            process.terminate()
            process.wait(timeout=5)


def test_independent_processes_share_one_atomic_budget(shared):
    script = """
import json
from app.errors import HubError
from app.security.rate_limit import hit
accepted = denied = 0
for i in range(40):
    try:
        hit('login:same-user', 50, 60)
        accepted += 1
    except HubError as e:
        assert e.code == 'RATE_LIMITED', e.code
        denied += 1
print(json.dumps([accepted, denied]))
"""
    options = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    workers = [subprocess.Popen([sys.executable, "-c", script], **options) for _ in range(2)]
    results = []
    for worker in workers:
        output, error = worker.communicate(timeout=15)
        assert worker.returncode == 0, error
        results.append(json.loads(output))
    assert sum(result[0] for result in results) == 50
    assert sum(result[1] for result in results) == 30
    # Identifiers never become readable cache keys.
    assert all(b"same-user" not in key for key in shared.scan_iter("test-*:*") )


def test_sliding_window_expires_and_fixed_window_does_not_extend(shared):
    rate_limit.hit("login:one", 1, 1)
    with pytest.raises(HubError) as error:
        rate_limit.hit("login:one", 1, 1)
    assert error.value.status_code == 429
    time.sleep(1.05)
    rate_limit.hit("login:one", 1, 1)
    rate_limit.hit("gateway-day:one", 2, 86400)
    keys = [key for key in shared.scan_iter("test-*:*") if shared.type(key) == b"string"]
    assert len(keys) == 1
    before = shared.pttl(keys[0])
    rate_limit.hit("gateway-day:one", 2, 86400)
    with pytest.raises(HubError):
        rate_limit.hit("gateway-day:one", 2, 86400)
    assert 86_398_000 < shared.pttl(keys[0]) <= before


def test_kind_capacity_is_bounded_and_isolated(shared, monkeypatch):
    monkeypatch.setattr(rate_limit, "_MAX_SHORT", 2)
    rate_limit.hit("login:a", 1, 60)
    rate_limit.hit("login:b", 1, 60)
    with pytest.raises(HubError, match="exhausted"):
        rate_limit.hit("login:c", 1, 60)
    rate_limit.hit("pairing:a", 1, 60)


def test_backend_failure_is_closed_and_readiness_fails(client, monkeypatch):
    settings = get_settings().model_copy(update={"rate_limit_backend": "redis"})
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    def unavailable(*args, **kwargs):
        raise RedisError("redis://private-password@cache")
    monkeypatch.setattr(rate_limit, "_redis", unavailable)
    with pytest.raises(HubError) as error:
        rate_limit.hit("login:user", 10, 60)
    assert error.value.status_code == 503
    assert "password" not in str(error.value)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200
