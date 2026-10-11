"""Isolated PRD audit probes. Uses in-memory SQLite and mocked upstreams only.

Run from the repository root:
    backend/.venv/Scripts/python.exe docs/PRD_AUDIT_REPRO.py
This does not change the application's existing database.
"""

import json
import logging
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

# Reuse the test environment, including its in-memory DB and dummy secrets.
import tests.conftest  # noqa: E402,F401
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import app.persistence.session as db_session  # noqa: E402
from app.connectors.http_adapter import push_transport, reset_transport  # noqa: E402
from app.ids import new_id  # noqa: E402
from app.main import create_app  # noqa: E402
from app.persistence.base import Base  # noqa: E402
from app.persistence.models import AdminUser, ToolDefinition  # noqa: E402
from app.persistence.session import open_session  # noqa: E402
from app.security.crypto import sign_payload  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from tests.integration.test_connector_and_tool import (  # noqa: E402
    _dns,
    _handler,
    test_admin_can_publish_a_read_only_tool_without_new_python,
)

CANARY = "audit.canary@example.com"
NID = 3201010101010001
results = {}


def record(name, **values):
    results[name] = values


application = create_app()
Base.metadata.create_all(db_session.engine)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpx2").setLevel(logging.ERROR)
logging.getLogger("mcp").setLevel(logging.CRITICAL)
logging.getLogger("hub").setLevel(logging.CRITICAL)
patch = pytest.MonkeyPatch()
_dns(patch)

with TestClient(application, raise_server_exceptions=False) as client:
    with open_session() as db:
        db.add(AdminUser(id=new_id(), email="admin@localhost",
                         password_hash=hash_password("ChangeMe-Now-12"), role="super_admin"))
        db.commit()
    login = client.post("/api/admin/v1/auth/login", json={
        "email": "admin@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
    headers = {"X-CSRF-Token": login["csrf_token"]}
    admin = {"client": client, "csrf": login["csrf_token"]}
    test_admin_can_publish_a_read_only_tool_without_new_python(admin, patch)
    tool = client.get("/api/admin/v1/tools").json()["data"][0]
    connector_id = tool["connector_id"]
    identity = client.post("/api/admin/v1/service-identities", headers=headers, json={
        "name": "audit", "app_key": "your_app", "environment": "dev"}).json()["data"]
    delegation = sign_payload("dev-delegation-secret", {
        "app_key": "your_app", "tenant_id": "tenant_a", "user_ref": "user_1", "aud": "mcp-hub"})
    mcp_headers = {"Authorization": "Bearer " + identity["token"],
                   "Origin": "http://testserver", "X-Hub-Delegation": delegation}

    def call(name, arguments=None, request_headers=None):
        response = client.post("/mcp", headers=request_headers or mcp_headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": name, "arguments": arguments or {}}})
        return response.json()

    def payload_of(response):
        result = response.get("result", {})
        if "structuredContent" in result:
            return result["structuredContent"]
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (KeyError, json.JSONDecodeError):
                    continue
        return {}

    def wrapped(document):
        def handle(request):
            if request.url.path.endswith("/projects"):
                return httpx.Response(200, json=document)
            return _handler(request)
        return httpx.MockTransport(handle)

    async def official_client_probe():
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=application),
                                      headers=mcp_headers) as http_client:
            async with streamable_http_client("http://testserver/mcp", http_client=http_client) as streams:
                async with ClientSession(*streams, read_timeout_seconds=8) as session:
                    await session.discover()
                    listed = await session.list_tools()
                    called = await session.call_tool(tool["mcp_name"], {"status": "active"})
                    return {"negotiated_protocol": session.protocol_version,
                            "published_tool_found": any(t.name == tool["mcp_name"] for t in listed.tools),
                            "call_error": called.is_error}

    async def bounded_official_probe():
        return await asyncio.wait_for(official_client_probe(), timeout=15)

    transport_token = push_transport(httpx.MockTransport(_handler))
    try:
        try:
            record("official_sdk_client", **client.portal.call(bounded_official_probe))
        except Exception as exc:
            record("official_sdk_client", error_type=type(exc).__name__, message=str(exc)[:300])
    finally:
        reset_transport(transport_token)

    normal_meta = {"as_of": "2026-10-10T09:00:00+08:00", "timezone": "UTC",
                   "scope": "authorized_records", "coverage": "complete"}
    normal_row = {"ref": "prj_125", "name": "Project", "status": "active",
                  "created_at": "2026-10-01", "tenant_id": "tenant_a"}

    transport_token = push_transport(wrapped({"success": True, "data": [normal_row],
                                               "meta": {**normal_meta, "scope": CANARY}}))
    try:
        response = call(tool["mcp_name"], {"status": "active"})
        record("rest_metadata_pii", leaked=CANARY in json.dumps(response),
               tool_error=response.get("result", {}).get("isError", False))
    finally:
        reset_transport(transport_token)

    transport_token = push_transport(wrapped({"success": True,
        "data": [{**normal_row, "status": NID}], "meta": normal_meta}))
    try:
        response = call(tool["mcp_name"], {"status": "active"})
        record("numeric_national_id", leaked=str(NID) in json.dumps(response),
               tool_error=response.get("result", {}).get("isError", False))
    finally:
        reset_transport(transport_token)

    transport_token = push_transport(wrapped({"success": True, "data": "invalid shape",
                                               "meta": normal_meta}))
    try:
        response = call(tool["mcp_name"], {"status": "active"})
        record("invalid_upstream_shape", result=payload_of(response))
    finally:
        reset_transport(transport_token)

    dataset_args = {"dataset": [{"value": 2}, {"value": 10}], "meta": normal_meta,
                    "operation": "sort", "parameters": {"allow_fields": ["value"],
                    "field": "value"}, "field_policy": {"value": "allowed_for_ai"}}
    response = call("process_dataset", dataset_args)
    record("numeric_sort", result=payload_of(response))
    response = call("process_dataset", {**dataset_args, "operation": "count",
                                       "meta": {**normal_meta, "scope": CANARY}})
    record("push_metadata_pii", leaked=CANARY in json.dumps(response),
           tool_error=response.get("result", {}).get("isError", False))

    success_count = 0
    for _ in range(65):
        response = call("process_dataset", {**dataset_args, "operation": "count"})
        success_count += payload_of(response).get("success") is True
    record("builtin_tool_rate_limit", successful_calls=success_count, configured_per_minute=60)

    # A token bound to another app sees the globally registered tools.
    created = client.post("/api/admin/v1/connectors", headers=headers, json={
        "name": "Other app", "app_key": "other_app", "environment": "dev",
        "connector_type": "http_contract", "base_url": "http://other.test",
        "auth_type": "api_key", "secret": "dummy-secret-123"})
    assert created.status_code == 201
    blank_delegation = client.post("/api/admin/v1/connectors", headers=headers, json={
        "name": "Wizard blank", "app_key": "wizard_blank", "environment": "dev",
        "connector_type": "http_contract", "base_url": "http://wizard.test",
        "auth_type": "api_key", "secret": "dummy-secret-123", "delegation_secret": ""})
    record("wizard_blank_delegation", http_status=blank_delegation.status_code,
           generated_secret_returned="delegation_secret" in blank_delegation.json().get("data", {}),
           falsely_reports_supplied=blank_delegation.json().get("data", {}).get("delegation_secret_set"))
    other_identity = client.post("/api/admin/v1/service-identities", headers=headers, json={
        "name": "other", "app_key": "other_app", "environment": "dev"}).json()["data"]
    other_headers = {"Authorization": "Bearer " + other_identity["token"], "Origin": "http://testserver"}
    listing = client.post("/mcp", headers=other_headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    denied = call(tool["mcp_name"], {}, other_headers)
    record("cross_app_discovery", listed_other_app_tool=tool["mcp_name"] in listing.text,
           direct_call_denied=denied.get("result", {}).get("isError", False))

    backup = client.post("/api/admin/v1/operations/export", headers=headers).json()["data"]
    restore = client.post("/api/admin/v1/operations/import", headers=headers, json=backup)
    record("backup_with_published_tool", http_status=restore.status_code,
           error=restore.json().get("error"),
           saved_tool_count=len(backup["tables"]["tool_definitions"]))
    from app.services.backup import import_metadata
    with open_session() as db:
        try:
            import_metadata(db, backup)
        except Exception as exc:
            record("backup_restore_cause", error_type=type(exc).__name__,
                   database_reason=str(getattr(exc, "orig", "")),
                   statement=getattr(exc, "statement", ""))
            db.rollback()

    # Create an app admin; the model contains no application assignment for this user.
    client.post("/api/admin/v1/users", headers=headers, json={
        "email": "unassigned-admin@localhost", "password": "ChangeMe-Now-12", "role": "app_admin"})
    super_cookies = dict(client.cookies)
    client.cookies.clear()
    app_login = client.post("/api/admin/v1/auth/login", json={
        "email": "unassigned-admin@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
    app_headers = {"X-CSRF-Token": app_login["csrf_token"]}
    forged_access = client.post("/api/admin/v1/service-identities", headers=app_headers, json={
        "name": "unassigned", "app_key": "your_app", "environment": "dev"})
    pause = client.post(f"/api/admin/v1/connectors/{connector_id}/pause", headers=app_headers)
    record("unassigned_app_admin", identity_for_other_app_status=forged_access.status_code,
           pause_other_app_status=pause.status_code)
    client.cookies.clear()
    client.cookies.update(super_cookies)
    client.post(f"/api/admin/v1/connectors/{connector_id}/resume", headers=headers)

    # Synthetic success is sufficient even for an endpoint never tested at source.
    draft = {"connector_id": connector_id, "tool_key": "your_app.projects.unverified",
             "module_key": "projects", "description": "Audit nonexistent route",
             "method": "GET", "path_template": "/api/v1/not-reviewed-or-tested",
             "input_schema": {"type": "object", "additionalProperties": False,
                              "properties": {"limit": {"type": "integer", "maximum": 50}},
                              "required": ["limit"]},
             "allow_fields": ["ref", "status"], "risk": "read_only",
             "requires_user_context": False}
    transport_token = push_transport(httpx.MockTransport(_handler))
    try:
        created = client.post("/api/admin/v1/tools", headers=headers, json=draft)
        assert created.status_code == 201, created.text
        tool_id = created.json()["data"]["id"]
        tested = client.post(f"/api/admin/v1/tools/{tool_id}/test", headers=headers,
                             json={"mode": "synthetic", "sample": {"data": []}})
        approved = client.post(f"/api/admin/v1/tools/{tool_id}/approve", headers=headers)
        published = client.post(f"/api/admin/v1/tools/{tool_id}/publish", headers=headers)
        record("publish_unverified_endpoint", synthetic_passed=tested.json()["data"]["passed"],
               approval_status=approved.status_code, publish_status=published.status_code,
               required_input_omitted=True, user_context_disabled=True)

        # An upstream can exceed the reviewed module's record count.
        transport_override = push_transport(wrapped({"success": True,
            "data": [{**normal_row, "ref": f"prj_{i}"} for i in range(60)], "meta": normal_meta}))
        try:
            response = call(tool["mcp_name"], {"status": "active"})
            content = payload_of(response)
            record("upstream_record_limit", returned_records=len(content.get("data", [])),
                   configured_module_max=50, metadata=content.get("meta"))
        finally:
            reset_transport(transport_override)

        # A valid JSON schema with optional-before-required fields fails during code generation.
        created = client.post("/api/admin/v1/tools", headers=headers, json={**draft,
            "tool_key": "your_app.projects.optional_required",
            "path_template": "/api/v1/projects",
            "input_schema": {"type": "object", "additionalProperties": False,
                "properties": {"optional_status": {"type": "string", "maxLength": 20},
                               "limit": {"type": "integer", "maximum": 50}},
                "required": ["limit"]}})
        assert created.status_code == 201
        broken_id = created.json()["data"]["id"]
        client.post(f"/api/admin/v1/tools/{broken_id}/test", headers=headers,
                    json={"mode": "synthetic", "sample": {"data": []}})
        client.post(f"/api/admin/v1/tools/{broken_id}/approve", headers=headers)
        publication = client.post(f"/api/admin/v1/tools/{broken_id}/publish", headers=headers)
        with open_session() as db:
            persisted_status = db.get(ToolDefinition, broken_id).status
        record("optional_before_required_schema", publish_status=publication.status_code,
               persisted_status=persisted_status,
               runtime_tool_name=created.json()["data"]["mcp_name"])
        from app.mcp.dynamic_tools import sync_published_tools
        try:
            with open_session() as db:
                sync_published_tools(application.state.mcp, db)
        except Exception as exc:
            record("restart_registry_sync", error_type=type(exc).__name__, message=str(exc))
    finally:
        reset_transport(transport_token)

patch.undo()

# Repeat restore against Alembic-created tables, not just Base.metadata test tables.
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.config import get_settings  # noqa: E402

with tempfile.TemporaryDirectory(prefix="prd-audit-") as audit_dir:
    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + (Path(audit_dir) / "metadata.db").as_posix()
    get_settings.cache_clear()
    command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")
    db_session.init_engine(os.environ["DATABASE_URL"])
    with open_session() as db:
        try:
            import_metadata(db, backup)
            db.commit()
            record("backup_restore_migrated_database", restored=True)
        except Exception as exc:
            record("backup_restore_migrated_database", restored=False,
                   error_type=type(exc).__name__, database_reason=str(getattr(exc, "orig", "")),
                   statement=getattr(exc, "statement", ""))
            db.rollback()
    db_session.engine.dispose()

# Exercise the actual reference source rather than the permissive integration mock.
from reference.your_app.app import app as source_app  # noqa: E402

with TestClient(source_app) as source:
    assertion = sign_payload("dev-delegation-secret", {"app_key": "your_app",
        "user_ref": "nonexistent-or-revoked-user", "tenant_id": "tenant_a", "aud": "http://testserver"})
    response = source.get("/api/v1/projects?limit=1", headers={
        "X-API-Key": "dev-your-app-key", "X-Hub-Assertion": assertion})
    body = response.json()
    record("reference_authorization_and_pagination", http_status=response.status_code,
           unknown_user_received_records=len(body.get("data", [])),
           actual_matching_records=2, metadata=body.get("meta"))

output = json.dumps(results, indent=2)
(ROOT / "docs" / "PRD_AUDIT_EVIDENCE.json").write_text(output + "\n", encoding="utf-8")
print(output)
