"""Shared test helpers: a mocked connected app and shortcuts through the admin workflow."""

import copy
import json
import socket
from base64 import urlsafe_b64decode
from contextlib import contextmanager

import httpx
from app.connectors.http_adapter import push_transport, reset_transport
from app.security.crypto import sign_payload
from reference.your_app.contract import MANIFEST as REFERENCE_MANIFEST

API_KEY = "dev-your-app-key"
DELEGATION_SECRET = "dev-delegation-secret"
CANARY = "canary.a@example.com"
MANIFEST = copy.deepcopy(REFERENCE_MANIFEST)
META = {"as_of": "2026-10-10T09:00:00+08:00", "timezone": "Asia/Makassar", "scope": "authorized_records", "coverage": "complete"}
PROJECT_ROWS = [
    {"ref": "prj_125", "name": "Website Villa", "status": "active", "created_at": "2026-10-01T09:00:00+08:00",
     "budget": 12500.0, "tenant_id": "tenant_a", "owner_email": CANARY},
    {"ref": "prj_200", "name": "Harbor Office", "status": "completed", "created_at": "2026-09-01T09:00:00+08:00",
     "budget": 48000.0, "tenant_id": "tenant_a", "owner_email": "canary.hidden@example.com"},
    {"ref": "prj_210", "name": "Beach Resort", "status": "active", "created_at": "2026-09-14T10:30:00+08:00",
     "budget": 91000.0, "tenant_id": "tenant_a", "owner_email": "owner.c@example.com"},
    {"ref": "prj_220", "name": "Coffee Bar", "status": "active", "created_at": "2026-10-03T13:00:00+08:00",
     "budget": 8600.0, "tenant_id": "tenant_a", "owner_email": "owner.e@example.com"},
    {"ref": "prj_900", "name": "Other Tenant", "status": "active", "created_at": "2026-10-02T09:00:00+08:00",
     "budget": 99999.0, "tenant_id": "tenant_b", "owner_email": "canary.b@example.com"},
]
CALLS: list[httpx.Request] = []


def dns(monkeypatch) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr("app.connectors.ssrf_guard.socket.getaddrinfo", fake_getaddrinfo)


def _assertion_tenant(request: httpx.Request) -> str | None:
    token = request.headers.get("X-Hub-Assertion", "")
    try:
        raw = token.split(".", 1)[0]
        return json.loads(urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))["tenant_id"]
    except (ValueError, KeyError, IndexError):
        return None


def project_page(request: httpx.Request, rows: list[dict]) -> httpx.Response:
    params = request.url.params
    if params.get("status"):
        rows = [row for row in rows if row["status"] == params["status"]]
    limit = int(params.get("limit", 50))
    offset = int(params["cursor"][5:]) if params.get("cursor") else 0
    page = rows[offset:offset + limit]
    more = offset + limit < len(rows)
    meta = {**META, "coverage": "partial" if more else "complete", "has_more": more,
            "next_cursor": f"page_{offset + limit}" if more else None}
    return httpx.Response(200, json={"success": True, "data": page, "meta": meta})


def handler(request: httpx.Request, *, leak_other_tenants: bool = False) -> httpx.Response:
    """A connected app that keeps its own tenant boundary unless told to leak."""

    CALLS.append(request)
    path = request.url.path
    if request.headers.get("Authorization") != f"Bearer {API_KEY}" or "X-API-Key" in request.headers:
        return httpx.Response(401, json={"success": False, "error": {"code": "UNAUTHENTICATED", "message": "no"}})
    if path.endswith("/health"):
        return httpx.Response(200, json={"status": "ok"})
    if path.endswith("/capabilities"):
        return httpx.Response(200, json=MANIFEST)
    if path.endswith("/projects") and request.method == "POST":
        body = json.loads(request.content or b"{}")
        return httpx.Response(200, json={"success": True, "meta": {"requires_confirmation": True}, "data": [
            {"proposal_ref": "prop_test1", "summary": f"Create project '{body.get('name')}'",
             "status": "pending_confirmation", "tenant_id": _assertion_tenant(request)}]})
    if path.endswith("/projects"):
        tenant = _assertion_tenant(request)
        rows = PROJECT_ROWS if leak_other_tenants else [row for row in PROJECT_ROWS if row["tenant_id"] == tenant]
        return project_page(request, rows)
    if path.endswith("/activity"):
        rows = [{"last_active_at": "2026-10-09T09:00:00+08:00", "status": "active", "tenant_id": "tenant_a"},
                {"last_active_at": None, "status": "active", "tenant_id": "tenant_a"},
                {"last_active_at": "2026-10-04T09:00:00+08:00", "status": "active", "tenant_id": "tenant_a"},
                {"last_active_at": "2026-09-28T09:00:00+08:00", "status": "suspended", "tenant_id": "tenant_a"}]
        return httpx.Response(200, json={"success": True, "data": rows, "meta": {**META, "scope": "authorized_users"}})
    return httpx.Response(404, json={"success": False, "error": {"code": "NOT_FOUND", "message": "missing"}})


def leaky_handler(request: httpx.Request) -> httpx.Response:
    return handler(request, leak_other_tenants=True)


@contextmanager
def source(app_handler=handler):
    CALLS.clear()
    token = push_transport(httpx.MockTransport(app_handler))
    try:
        yield CALLS
    finally:
        reset_transport(token)


def headers(admin: dict) -> dict:
    return {"X-CSRF-Token": admin["csrf"]}


def api(admin: dict, method: str, path: str, body=None, expect: int | None = None):
    response = admin["client"].request(method, "/api/admin/v1" + path, headers=headers(admin), json=body)
    if expect is not None:
        assert response.status_code == expect, response.text
    return response


def connect_app(admin: dict, *, app_key: str = "your_app", enable: dict | None = None, base_url: str = "http://projects.test") -> dict:
    """Create, test, sync and activate an app; enable the given data sources and operations."""

    created = api(admin, "POST", "/connectors", {
        "name": "Your App", "app_key": app_key, "environment": "dev", "base_url": base_url,
        "auth_type": "bearer", "secret": API_KEY, "delegation_secret": DELEGATION_SECRET}, expect=201).json()["data"]
    assert API_KEY not in json.dumps(created)
    assert api(admin, "POST", f"/connectors/{created['id']}/test", expect=200).json()["data"]["status"] == "ok"
    modules = api(admin, "POST", f"/connectors/{created['id']}/discover", expect=200).json()["data"]["modules"]
    ids = {module["module_key"]: module["id"] for module in modules}
    for key, operations in (enable if enable is not None else {"projects": ["read"]}).items():
        api(admin, "PATCH", f"/modules/{ids[key]}/settings", {"enabled": True, "operations": operations}, expect=200)
    api(admin, "POST", f"/connectors/{created['id']}/activate", expect=200)
    return {"connector_id": created["id"], "app_id": created["app_id"], "modules": ids}


def create_tool(admin: dict, connector_id: str, **overrides) -> dict:
    body = {"connector_id": connector_id, "module_key": "projects", "template": "read", "tool_key": "your_app.projects.list",
            "description": "List project status for the signed-in tenant.", "method": "GET", "path_template": "/api/v1/projects"}
    body.update(overrides)
    return api(admin, "POST", "/tools", body, expect=201).json()["data"]


def run_tool_test(admin: dict, tool_id: str, body: dict | None = None) -> dict:
    return api(admin, "POST", f"/tools/{tool_id}/test", body or {"mode": "sample"}, expect=200).json()["data"]


def publish(admin: dict, tool_id: str, body: dict | None = None) -> dict:
    tested = run_tool_test(admin, tool_id, body)
    assert tested["passed"], tested
    return api(admin, "POST", f"/tools/{tool_id}/publish", expect=200).json()["data"]


def issue_key(admin: dict, *, app_key: str = "your_app", **options) -> str:
    created = api(admin, "POST", "/service-identities", {"name": "gateway", "app_key": app_key, "environment": "dev", **options},
                  expect=201).json()["data"]
    return created["token"]


def delegation(tenant: str = "tenant_a", user: str = "user_1", app_key: str = "your_app", **extra) -> str:
    return sign_payload(DELEGATION_SECRET, {"app_key": app_key, "tenant_id": tenant, "user_ref": user, "aud": "mcp-hub", **extra})


def mcp(client, token: str | None, method: str, params: dict | None = None, user_delegation: str | None = None):
    request_headers = {"Origin": "http://testserver"}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if user_delegation:
        request_headers["X-Hub-Delegation"] = user_delegation
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers=request_headers, json=body)


def call(client, token: str, name: str, arguments: dict | None = None, user_delegation: str | None = None):
    return mcp(client, token, "tools/call", {"name": name, "arguments": arguments or {}}, user_delegation)


def listed(client, token: str) -> list[str]:
    response = mcp(client, token, "tools/list")
    assert response.status_code == 200, response.text
    return [tool["name"] for tool in response.json()["result"]["tools"]]


def result(response) -> dict:
    body = response.json()["result"]
    assert body.get("isError") is not True, body
    return body.get("structuredContent") or json.loads(body["content"][0]["text"])


def error_text(response) -> str:
    body = response.json()["result"]
    assert body.get("isError") is True, body
    return body["content"][0]["text"]
