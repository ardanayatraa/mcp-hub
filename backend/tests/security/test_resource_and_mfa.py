"""Budgets, transport pinning, chunked requests, and single-use MFA."""


# ruff: noqa: F811 - pytest fixtures are imported for cross-module reuse.
import asyncio
import copy
import time

import httpx
import pyotp
import pytest
from app.config import Settings, get_settings
from app.connectors.http_adapter import (
    execute_request,
    last_retry_count,
    push_transport,
    reset_transport,
)
from app.connectors.pinned_transport import PinnedBackend
from app.errors import HubError
from app.main import BodyLimitMiddleware
from app.persistence.models import AdminUser, ContractSnapshot, MfaChallenge
from app.persistence.session import open_session
from app.security.crypto import encrypt_secret, sign_payload
from sqlalchemy import select
from tests import helpers
from tests.conftest import auth_headers
from tests.helpers import MANIFEST
from tests.helpers import dns as _dns
from tests.helpers import leaky_handler as _handler
from tests.security.test_prd_regressions import call, published  # noqa: F401


@pytest.mark.asyncio
async def test_socket_uses_validated_ip_and_preserves_origin(monkeypatch):
    captured = []
    async def connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        captured.append((host, port))
        return "stream"
    monkeypatch.setattr("httpcore._backends.auto.AutoBackend.connect_tcp", connect)
    backend = PinnedBackend("reviewed.test", 443, ["93.184.216.34"])
    assert await backend.connect_tcp("reviewed.test", 443) == "stream"
    assert captured == [("93.184.216.34", 443)]
    with pytest.raises(HubError, match="escaped"):
        await backend.connect_tcp("169.254.169.254", 443)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_chunked_request_limit_counts_actual_bytes():
    consumed, sent, entered = [], [], []
    async def downstream(scope, receive, send):
        entered.append(True)
    chunks = iter([{"type": "http.request", "body": b"a" * 8, "more_body": True}, {"type": "http.request", "body": b"b" * 8, "more_body": True}, {"type": "http.request", "body": b"c", "more_body": False}])
    async def receive():
        message = next(chunks)
        consumed.append(message)
        return message
    async def send(message):
        sent.append(message)
    await BodyLimitMiddleware(downstream, 10)({"type": "http", "path": "/api/test", "headers": [(b"content-length", b"1")]}, receive, send)
    assert sent[0]["status"] == 413
    assert len(consumed) == 2
    assert entered == []


class Chunks(httpx.AsyncByteStream):
    def __init__(self):
        self.reads = 0
    async def __aiter__(self):
        for _ in range(100):
            self.reads += 1
            yield b"x" * 16384


@pytest.mark.asyncio
async def test_response_stops_streaming_when_limit_exceeded(monkeypatch):
    _dns(monkeypatch)
    stream = Chunks()
    token = push_transport(httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)))
    try:
        with pytest.raises(HubError) as error:
            await execute_request(method="GET", url="http://reviewed.test/data", settings=get_settings(), headers={}, max_bytes=20000)
        assert error.value.code == "PAYLOAD_TOO_LARGE"
        assert stream.reads == 2
    finally:
        reset_transport(token)


@pytest.mark.asyncio
async def test_overall_deadline_cancels_slow_upstream(monkeypatch):
    _dns(monkeypatch)
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})
    token = push_transport(httpx.MockTransport(slow))
    started = time.perf_counter()
    try:
        with pytest.raises(HubError) as error:
            await execute_request(method="GET", url="http://reviewed.test/data", settings=get_settings(), headers={}, timeout_ms=100, retries=0)
        assert error.value.code == "UPSTREAM_TIMEOUT"
        assert time.perf_counter() - started < 0.8
    finally:
        reset_transport(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,expected", [("GET", 3), ("POST", 1)])
async def test_only_safe_get_requests_retry(monkeypatch, method, expected):
    _dns(monkeypatch)
    calls = []
    def unavailable(request):
        calls.append(request)
        return httpx.Response(503, json={"error": "private upstream text"})
    token = push_transport(httpx.MockTransport(unavailable))
    try:
        status, _, _ = await execute_request(method=method, url="http://reviewed.test/data", settings=get_settings(), headers={}, retries=2)
        assert status == 503 and len(calls) == expected
        assert last_retry_count() == expected - 1
    finally:
        reset_transport(token)


@pytest.mark.asyncio
async def test_burst_of_50_calls_has_bounded_concurrency(monkeypatch):
    _dns(monkeypatch)
    settings = get_settings().model_copy(update={"connector_concurrency": 4})
    release, all_entered = asyncio.Event(), asyncio.Event()
    active, peak = 0, 0
    async def slow(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 4:
            all_entered.set()
        await release.wait()
        active -= 1
        return httpx.Response(200, json={"success": True})
    async def run():
        try:
            await execute_request(method="GET", url="http://burst.test/data", settings=settings, headers={})
            return "success"
        except HubError as exc:
            return exc.code
    token = push_transport(httpx.MockTransport(slow))
    try:
        tasks = [asyncio.create_task(run()) for _ in range(50)]
        await asyncio.wait_for(all_entered.wait(), 3)
        release.set()
        outcomes = await asyncio.gather(*tasks)
        assert peak == 4
        assert outcomes.count("success") == 4
        assert outcomes.count("RATE_LIMITED") == 46
    finally:
        release.set()
        reset_transport(token)


def enable_mfa():
    secret = pyotp.random_base32()
    with open_session() as db:
        user = db.scalar(select(AdminUser).where(AdminUser.email == "admin@localhost"))
        user.mfa_enabled = True
        user.totp_secret_encrypted = encrypt_secret(get_settings().secret_encryption_key, secret)
        db.commit()
    return secret


def challenge(client):
    response = client.post("/api/admin/v1/auth/login", json={"email": "admin@localhost", "password": "ChangeMe-Now-12"})
    assert response.status_code == 200
    assert response.json()["data"]["mfa_required"] is True
    return response.json()["data"]["mfa_token"]


def test_mfa_challenge_and_totp_cannot_be_replayed(client):
    secret = enable_mfa()
    token, code = challenge(client), pyotp.TOTP(secret).now()
    first = client.post("/api/admin/v1/auth/mfa", json={"mfa_token": token, "code": code})
    assert first.status_code == 200, first.text
    replay = client.post("/api/admin/v1/auth/mfa", json={"mfa_token": token, "code": code})
    assert replay.status_code == 401
    fresh_token = challenge(client)
    assert client.post("/api/admin/v1/auth/mfa", json={"mfa_token": fresh_token, "code": code}).status_code == 401
    with open_session() as db:
        assert len(list(db.scalars(select(MfaChallenge).where(MfaChallenge.used_at.is_not(None))))) == 1


def test_mfa_attempts_are_rate_limited(client):
    enable_mfa()
    token = challenge(client)
    for _ in range(get_settings().mfa_rate_limit):
        assert client.post("/api/admin/v1/auth/mfa", json={"mfa_token": token, "code": "bad"}).status_code == 401
    assert client.post("/api/admin/v1/auth/mfa", json={"mfa_token": token, "code": "bad"}).status_code == 429


def test_egress_allowlist_is_required_and_applied(monkeypatch):
    _dns(monkeypatch)
    from app.connectors.ssrf_guard import validate_destination
    settings = get_settings().model_copy(update={"egress_allowed_hosts": "approved.test"})
    assert validate_destination("http://approved.test/", settings)[0] == "approved.test"
    with pytest.raises(HubError):
        validate_destination("http://unapproved.test/", settings)
    with pytest.raises(HubError):
        Settings(environment="production", cookie_secure=True, mfa_required=True, database_url="postgresql+psycopg://test", secret_encryption_key="set", session_signing_key="set").assert_production_safe()


def test_contract_change_requires_module_review_and_keeps_history(published):
    client, tool, admin = published["client"], published["tool"], published["admin"]
    changed = copy.deepcopy(MANIFEST)
    changed["manifest_version"] = "2026-10-10.4"
    changed["modules"][0]["name"] = "Reviewed project version 4"
    token = push_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=changed) if request.url.path.endswith("/capabilities") else _handler(request)))
    try:
        assert client.post(f"/api/admin/v1/connectors/{tool['connector_id']}/discover", headers=auth_headers(admin)).status_code == 200
        projects = next(row for row in client.get("/api/admin/v1/modules").json()["data"] if row["module_key"] == "projects")
        assert projects["enabled"] is False
        assert "MODULE_DISABLED" in call(published).text
        with open_session() as db:
            assert len(list(db.scalars(select(ContractSnapshot)))) == 2
        client.patch(f"/api/admin/v1/modules/{projects['id']}/settings", headers=auth_headers(admin), json={"enabled": True, "operations": ["read"]})
        assert "CONFLICT" in call(published).text  # reviewed again, but the tool must be re-tested
        assert client.get(f"/api/admin/v1/tools/{tool['id']}").json()["data"]["stale"] is True
        helpers.publish(admin, tool["id"])
        assert call(published, arguments={"status": "active"}).json()["result"].get("isError") is not True
    finally:
        reset_transport(token)


def test_lifecycle_pause_rotation_and_archive(published):
    client, tool, admin = published["client"], published["tool"], published["admin"]
    root = f"/api/admin/v1/connectors/{tool['connector_id']}"
    headers = auth_headers(admin)
    assert client.post(root + "/pause", headers=headers).status_code == 200
    assert "CONNECTOR_INACTIVE" in call(published, arguments={"status": "active"}).text
    assert client.post(root + "/rotate", headers=headers, json={"secret": "wrong-key-123"}).status_code == 200
    assert client.post(root + "/test", headers=headers).json()["data"]["error_category"] == "authorization"
    assert client.post(root + "/activate", headers=headers).status_code == 422
    assert client.post(root + "/rotate", headers=headers, json={"secret": "dev-your-app-key"}).status_code == 200
    assert client.post(root + "/test", headers=headers).json()["data"]["status"] == "ok"
    assert client.post(root + "/activate", headers=headers).status_code == 200
    assert call(published, arguments={"status": "active"}).json()["result"].get("isError") is not True
    assert client.delete(root, headers=headers).status_code == 409
    assert client.post(root + "/archive", headers=headers).status_code == 200
    assert client.get(root).json()["data"]["secret_configured"] is False
    assert client.post(root + "/activate", headers=headers).status_code == 409
    listed = client.post("/mcp", headers=published["headers"], json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed.status_code == 401  # archiving also revokes the app's client keys
    assert client.delete(root, headers=headers).status_code == 200


def test_api_key_and_delegation_secret_can_be_replaced_separately(published):
    client, tool, admin = published["client"], published["tool"], published["admin"]
    root = f"/api/admin/v1/connectors/{tool['connector_id']}"
    headers = auth_headers(admin)
    before = client.get(root).json()["data"]["secret_updated_at"]
    assert before is not None
    assert client.post(root + "/rotate", headers=headers, json={}).status_code == 422
    assert client.post(root + "/rotate", headers=headers, json={"secret": "short"}).status_code == 422
    assert client.post(root + "/rotate", headers=headers, json={"delegation_secret": "replaced-delegation"}).status_code == 200
    assert client.post(root + "/test", headers=headers).json()["data"]["status"] == "ok"  # the API key was kept
    detail = client.get(root).json()["data"]
    assert detail["secret_configured"] is True and detail["secret_updated_at"] >= before
    assert "replaced-delegation" not in str(detail)
    assert call(published, arguments={"status": "active"}).json()["result"].get("isError") is True
    signed = sign_payload("replaced-delegation", {"app_key": "your_app", "tenant_id": "tenant_a", "user_ref": "user_1",
                                                  "aud": "mcp-hub"})
    renewed = {**published["headers"], "X-Hub-Delegation": signed}
    assert call(published, arguments={"status": "active"}, headers=renewed).json()["result"].get("isError") is not True


@pytest.mark.parametrize("value", ["bad", [], None, True])
def test_invalid_configuration_type_returns_422(published, value):
    response = published["client"].post("/api/admin/v1/tools", headers=auth_headers(published["admin"]), json={**published["tool"], "tool_key": "your_app.projects.other", "max_payload_bytes": value})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Invalid value for max_payload_bytes"


def test_unknown_tool_name_never_leaks_into_audit(published):
    canary = "name.canary@example.com"
    response = call(published, name=canary)
    assert response.json()["result"]["isError"] is True
    assert canary not in response.text
    assert canary not in published["client"].get("/api/admin/v1/executions").text


def test_blank_delegation_secret_is_returned_once(admin, monkeypatch):
    _dns(monkeypatch)
    response = admin["client"].post("/api/admin/v1/connectors", headers=auth_headers(admin), json={"app_key": "your_app", "auth_type": "bearer", "secret": "dev-your-app-key", "delegation_secret": "", "base_url": "http://reviewed.test"})
    assert response.status_code == 201
    data = response.json()["data"]
    assert len(data["delegation_secret"]) >= 32
    assert data["delegation_secret"] not in admin["client"].get(f"/api/admin/v1/connectors/{data['id']}").text


def test_pii_in_enum_metadata_cannot_be_published():
    from app.tools.schema_tools import validate_input_schema
    with pytest.raises(HubError) as error:
        validate_input_schema({"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["enum.canary@example.com"]}}})
    assert error.value.code == "PII_DETECTED"


def test_retries_and_health_failures_are_real_metrics(published):
    attempts = []
    def unavailable_once(request):
        if request.url.path.endswith("/projects"):
            attempts.append(True)
            if len(attempts) == 1:
                return httpx.Response(503, json={"success": False})
        if request.url.path.endswith("/health"):
            return httpx.Response(401, json={"success": False})
        return _handler(request)
    token = push_transport(httpx.MockTransport(unavailable_once))
    try:
        response = call(published)
        assert response.json()["result"].get("isError") is not True
        client, admin = published["client"], published["admin"]
        client.post(f"/api/admin/v1/connectors/{published['tool']['connector_id']}/test", headers=auth_headers(admin))
        dashboard = client.get("/api/admin/v1/dashboard?environment=dev").json()["data"]
        assert dashboard["retries"] == 1
        assert dashboard["connectors_failing"] == 1
        assert dashboard["executions"] >= 1 and dashboard["success"] >= 1
        assert len(dashboard["series"]) == 24  # hourly over the default 24 hours
        assert sum(point["calls"] for point in dashboard["series"]) == dashboard["executions"]
        assert sum(point["failed"] for point in dashboard["series"]) == dashboard["failure"]
        assert client.get("/api/admin/v1/dashboard?period=7d").json()["data"]["checklist"]["tool_published"] is True
        assert client.get("/api/admin/v1/dashboard?period=1y").status_code == 422
        assert client.get("/api/admin/v1/dashboard?from_time=invalid").status_code == 422
    finally:
        reset_transport(token)


def test_activity_source_checks_module_and_row_permission():
    from app.security.crypto import sign_payload
    from fastapi.testclient import TestClient
    from reference.your_app.app import app
    def headers(user):
        return {"Authorization": "Bearer dev-your-app-key", "X-Hub-Assertion": sign_payload("dev-delegation-secret", {"app_key": "your_app", "tenant_id": "tenant_a", "user_ref": user, "aud": "http://testserver"})}
    with TestClient(app) as source:
        assert source.get("/api/v1/activity", headers=headers("user_2")).status_code == 403
        allowed = source.get("/api/v1/activity", headers=headers("user_1"))
        assert allowed.status_code == 200
        assert len(allowed.json()["data"]) == 4
        assert all(set(row) == {"last_active_at", "status", "tenant_id"} for row in allowed.json()["data"])


def test_delegation_must_be_short_lived():
    from app.security.crypto import sign_payload, verify_signed_payload
    long_token = sign_payload("dummy", {"aud": "mcp-hub"}, ttl_seconds=86400)
    with pytest.raises(HubError):
        verify_signed_payload("dummy", long_token, audience="mcp-hub")
