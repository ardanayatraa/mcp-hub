"""Verify the isolated UAT fixture created through the browser on localhost:18000.

Dummy credentials and fixed test ports only. Does not use backend/hub.db.
Usage: backend/.venv/Scripts/python.exe docs/PRD_LIVE_VERIFY.py --restart-pid <UAT pid>
"""

# ruff: noqa: E402 -- Repository path must be available before application imports.

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx
import httpx2
from app.security.crypto import sign_payload
from mcp.client.streamable_http import streamable_http_client

from mcp import ClientSession

parser = argparse.ArgumentParser()
parser.add_argument("--restart-pid", type=int, required=True)
args = parser.parse_args()
base = "http://127.0.0.1:18000"
origin = "http://127.0.0.1:15173"
evidence = {"verified_at": datetime.now(timezone.utc).isoformat(), "fixture": "isolated SQLite UAT with dummy Your App data", "checks": {}}


def delegation(user="user_1", tenant="tenant_a"):
    return sign_payload("dev-delegation-secret", {"app_key": "your_app", "tenant_id": tenant, "user_ref": user, "aud": "mcp-hub"})


with httpx.Client(base_url=base, timeout=15, headers={"Origin": origin}) as admin:
    def request(method, path, **kwargs):
        response = admin.request(method, "/api/admin/v1" + path, **kwargs)
        assert response.is_success, (path, response.status_code, response.text)
        return response.json()["data"]
    login = request("POST", "/auth/login", json={"email": "admin@localhost", "password": "ChangeMe-Now-12"})
    admin.headers["X-CSRF-Token"] = login["csrf_token"]
    tool = next(row for row in request("GET", "/tools") if row["status"] == "published")
    module = request("GET", "/modules")[0]
    identity = request("POST", "/service-identities", json={"name": "isolated-live-verification", "app_key": "your_app", "environment": "dev"})
    headers = {"Authorization": "Bearer " + identity["token"], "Origin": origin, "X-Hub-Delegation": delegation()}
    backup = request("POST", "/operations/export")
    (ROOT / ".verification" / "uat-backup.json").write_text(json.dumps(backup), encoding="utf-8")

    async def exercise(name):
        async with httpx2.AsyncClient(headers=headers, timeout=10) as transport:
            async with streamable_http_client(base + "/mcp", http_client=transport) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as session:
                    await session.discover()
                    assert session.protocol_version == "2026-07-28"
                    assert tool["mcp_name"] in [row.name for row in (await session.list_tools()).tools]
                    response = await session.call_tool(tool["mcp_name"], {"status": "active", "limit": 1})
                    assert not response.is_error
                    body = response.structured_content
                    assert body["success"] is True
                    assert [row["ref"] for row in body["data"]] == ["prj_125"]
                    assert "owner_email" not in json.dumps(body) and "tenant_id" not in json.dumps(body)
                    evidence["checks"][name] = {"passed": True, "protocol": session.protocol_version, "records": len(body["data"])}
    asyncio.run(exercise("real_http_sdk_call"))

    def call(extra=None):
        response = admin.post("/mcp", headers={**headers, **(extra or {})}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["mcp_name"], "arguments": {"status": "active"}}})
        assert response.is_success
        return response.json()["result"]
    for label, assertion in [("revoked_source_user_denied", delegation("revoked_user")), ("cross_tenant_source_user_denied", delegation(tenant="tenant_b"))]:
        denied = call({"X-Hub-Delegation": assertion})
        assert denied["isError"] is True
        evidence["checks"][label] = {"passed": True}
    request("PATCH", f"/modules/{module['id']}/settings", json={"enabled": False, "operations": [], "fields": []})
    assert call()["isError"] is True
    evidence["checks"]["cached_disabled_tool_denied"] = {"passed": True}
    request("POST", "/operations/import", json=backup)
    asyncio.run(exercise("real_http_after_atomic_restore"))

    # Restart only the PID returned by the isolated UAT launch, never a process scan.
    os.kill(args.restart_pid, signal.SIGTERM)
    task_env = {**os.environ, "ENVIRONMENT": "dev", "DATABASE_URL": "sqlite+pysqlite:///" + (ROOT / ".verification" / "hub-uat.db").as_posix(),
        "SECRET_ENCRYPTION_KEY": "WyzcJBTgZUDuBhqKXe8GWpoJSvp2nR5J9ag3X5fMf5g=", "SESSION_SIGNING_KEY": "isolated-uat-session-signing-key",
        "MFA_REQUIRED": "false", "COOKIE_SECURE": "false", "ALLOW_INSECURE_HTTP": "true", "EGRESS_ALLOW_LOOPBACK": "true", "EGRESS_ALLOWED_PORTS": "80,443,18881",
        "ALLOWED_HOSTS": "localhost,127.0.0.1,127.0.0.1:15173,localhost:15173,127.0.0.1:18000", "ALLOWED_ORIGINS": origin,
        "MCP_PUBLIC_URL": base + "/mcp", "MCP_ISSUER_URL": base}
    logs = ROOT / ".verification"
    with (logs / "backend-restart.out.log").open("wb") as stdout, (logs / "backend-restart.err.log").open("wb") as stderr:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18000", "--no-access-log"], cwd=ROOT / "backend", env=task_env, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    (logs / "restart-pid.txt").write_text(str(process.pid))
    for attempt in range(50):
        try:
            if admin.get("/ready").is_success:
                break
        except httpx.TransportError:
            pass
        if process.poll() is not None:
            raise RuntimeError("Isolated backend failed to restart")
        time.sleep(0.1)
    else:
        raise RuntimeError("Isolated backend did not become ready")
    assert request("GET", "/tools")[0]["status"] == "published"
    assert request("GET", "/auth/me")["csrf_token"] == login["csrf_token"]
    headers["X-Hub-Delegation"] = delegation()
    asyncio.run(exercise("real_http_after_process_restart"))
    request("POST", f"/service-identities/{identity['id']}/revoke")
    evidence["checks"]["session_and_credential_persistence"] = {"passed": True}

(ROOT / "docs" / "PRD_LIVE_EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
print(json.dumps(evidence, indent=2))
