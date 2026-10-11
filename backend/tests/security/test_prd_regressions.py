"""Release blockers from the PRD review, exercised through real boundaries."""

import asyncio
import copy
import json

import httpx
import pytest
from app.connectors.http_adapter import push_transport, reset_transport
from app.errors import HubError
from app.persistence.models import ConnectorSecret
from app.persistence.session import open_session
from app.security.crypto import sign_payload
from app.tools.schema_tools import validate_input_schema
from fastapi.testclient import TestClient
from reference.your_app.app import app as source_app
from sqlalchemy import select
from tests import helpers
from tests.helpers import api, connect_app, create_tool, delegation, issue_key, publish

META = {"as_of": "2026-10-10T09:00:00+08:00", "timezone": "UTC", "scope": "authorized_records", "coverage": "complete"}
ROW = {"ref": "prj_125", "name": "Project", "status": "active", "created_at": "2026-10-01T00:00:00+00:00", "tenant_id": "tenant_a"}
CANARY = "regression.canary@example.com"


@pytest.fixture()
def published(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source(helpers.leaky_handler):
        app = connect_app(admin)
        tool = publish(admin, create_tool(admin, app["connector_id"],
                                          input_schema={"type": "object", "additionalProperties": False, "properties": {
                                              "status": {"type": "string", "enum": ["active", "completed"]}}})["id"])
        token = issue_key(admin)
        request_headers = {"Authorization": "Bearer " + token, "Origin": "http://testserver", "X-Hub-Delegation": delegation()}
        yield {"admin": admin, "client": admin["client"], "tool": tool, "headers": request_headers, "token": token, "app": app}


def call(state, name=None, arguments=None, headers=None):
    return state["client"].post("/mcp", headers=headers or state["headers"], json={"jsonrpc": "2.0", "id": 1,
        "method": "tools/call", "params": {"name": name or state["tool"]["mcp_name"], "arguments": arguments or {}}})


def result(response):
    body = response.json()["result"]
    if "structuredContent" in body:
        return body["structuredContent"]
    return json.loads(body["content"][0]["text"])


def mock_document(document):
    def handle(request):
        return httpx.Response(200, json=document) if request.url.path.endswith("/projects") else helpers.handler(request)
    return push_transport(httpx.MockTransport(handle))


@pytest.mark.parametrize("field", ["scope", "as_of", "timezone"])
def test_rest_metadata_pii_never_reaches_tool_or_logs(published, field):
    token = mock_document({"success": True, "data": [ROW], "meta": {**META, field: CANARY}})
    try:
        response = call(published, arguments={"status": "active"})
        assert response.json()["result"]["isError"] is True
        assert "PII_DETECTED" in response.text
        assert CANARY not in response.text
        assert CANARY not in published["client"].get("/api/admin/v1/executions").text
    finally:
        reset_transport(token)


@pytest.mark.parametrize("value", [3201010101010001, 3201010101010001.0, "+62 812 3456 7890", {"notes": CANARY},
                                   "password=should-never-leak", "hub_" + "a" * 40, "canary@localhost"])
def test_numeric_formatted_and_nested_pii_fail_closed(published, value):
    token = mock_document({"success": True, "data": [{**ROW, "status": value}], "meta": META})
    try:
        response = call(published, arguments={"status": "active"})
        assert response.json()["result"]["isError"] is True
        assert "PII_DETECTED" in response.text
        assert CANARY not in response.text and "3201010101010001" not in response.text
    finally:
        reset_transport(token)


@pytest.mark.parametrize("data", ["bad shape", None, ["not a record"], [{**ROW, "status": 123}]])
def test_wrong_output_shape_or_type_is_never_empty_success(published, data):
    token = mock_document({"success": True, "data": data, "meta": META})
    try:
        response = call(published, arguments={"status": "active"})
        assert response.json()["result"]["isError"] is True
        assert "SCHEMA_MISMATCH" in response.text
    finally:
        reset_transport(token)


def test_input_validation_errors_do_not_echo_sensitive_values(published):
    response = call(published, arguments={"status": CANARY})
    assert response.json()["result"]["isError"] is True
    assert CANARY not in response.text
    response = call(published, arguments={"status": "archived-and-secret"})
    assert "must be one of: active, completed" in response.text and "archived-and-secret" not in response.text


def test_upstream_record_limit_enforced(published):
    token = mock_document({"success": True, "data": [ROW] * 51, "meta": META})
    try:
        assert "PAYLOAD_TOO_LARGE" in call(published, arguments={"status": "active"}).text
    finally:
        reset_transport(token)


def test_tenant_rows_from_a_misbehaving_source_are_dropped(published):
    with helpers.source(helpers.leaky_handler):
        body = result(call(published, arguments={"status": "active"}))
    assert "prj_900" not in json.dumps(body) and body["meta"]["coverage"] == "partial"
    assert "total_count" not in body["meta"]


def test_unassigned_admin_cannot_view_mutate_or_issue_other_app_tokens(published):
    client, admin = published["client"], published["admin"]
    connector_id = published["tool"]["connector_id"]
    app_id = published["app"]["app_id"]
    created = api(admin, "POST", "/users", {"email": "scoped@localhost", "password": "ChangeMe-Now-12", "role": "app_admin"}, expect=201)
    user_id = created.json()["data"]["id"]
    super_cookies = dict(client.cookies)
    client.cookies.clear()
    login = client.post("/api/admin/v1/auth/login", json={"email": "scoped@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
    app_cookies, headers = dict(client.cookies), {"X-CSRF-Token": login["csrf_token"]}
    assert client.get("/api/admin/v1/connectors").json()["data"] == []
    assert client.get("/api/admin/v1/tools").json()["data"] == []
    assert client.get("/api/admin/v1/modules").json()["data"] == []
    assert client.post(f"/api/admin/v1/connectors/{connector_id}/pause", headers=headers).status_code == 403
    assert client.post("/api/admin/v1/service-identities", headers=headers, json={"name": "bad", "app_key": "your_app"}).status_code == 403
    assert client.get("/api/admin/v1/users").status_code == 403
    client.cookies.clear()
    client.cookies.update(super_cookies)
    assert api(admin, "PATCH", f"/users/{user_id}", {"app_ids": [app_id]}).status_code == 200
    client.cookies.clear()
    client.cookies.update(app_cookies)
    assert len(client.get("/api/admin/v1/connectors").json()["data"]) == 1
    assert client.post(f"/api/admin/v1/connectors/{connector_id}/pause", headers=headers).status_code == 200


def test_cross_app_discovery_and_direct_call_are_both_denied(published):
    admin = published["admin"]
    created = api(admin, "POST", "/connectors", {"name": "Other", "app_key": "other_app", "base_url": "http://other.test",
                                                 "auth_type": "api_key", "secret": "dummy-secret-123"})
    assert created.status_code == 201
    token = issue_key(admin, app_key="other_app")
    request_headers = {"Authorization": "Bearer " + token, "Origin": "http://testserver"}
    listed = published["client"].post("/mcp", headers=request_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert published["tool"]["mcp_name"] not in listed.text
    assert listed.json()["result"]["tools"] == []  # the other app is still a draft: nothing is callable
    assert "PERMISSION_DENIED" in call(published, headers=request_headers).text


def test_scoped_auditor_reads_identity_metadata_without_write_authority(published):
    client, admin = published["client"], published["admin"]
    assert api(admin, "POST", "/users", {"email": "auditor@localhost", "password": "ChangeMe-Now-12", "role": "auditor",
                                         "app_ids": [published["app"]["app_id"]]}).status_code == 201
    client.cookies.clear()
    login = client.post("/api/admin/v1/auth/login", json={"email": "auditor@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
    rows = client.get("/api/admin/v1/service-identities").json()["data"]
    assert len(rows) == 1
    assert all("token" not in row and "token_hash" not in row for row in rows)
    headers = {"X-CSRF-Token": login["csrf_token"]}
    assert client.post("/api/admin/v1/service-identities", headers=headers, json={"app_key": "your_app"}).status_code == 403
    assert client.post(f"/api/admin/v1/service-identities/{rows[0]['id']}/revoke", headers=headers).status_code == 403
    assert client.post(f"/api/admin/v1/tools/{published['tool']['id']}/test", headers=headers, json={}).status_code == 403


@pytest.mark.parametrize("ttl", [True, "90", [], 0, 366])
def test_service_identity_ttl_is_strictly_validated(published, ttl):
    response = api(published["admin"], "POST", "/service-identities", {"app_key": "your_app", "ttl_days": ttl})
    assert response.status_code == 422
    assert response.json()["error"] == {"code": "VALIDATION_FAILED", "message": "Invalid value for ttl_days"}


def test_unreviewed_route_and_weaker_delegation_rejected(published):
    admin, connector_id = published["admin"], published["tool"]["connector_id"]
    base = {"connector_id": connector_id, "module_key": "projects", "tool_key": "your_app.projects.new"}
    assert api(admin, "POST", "/tools", {**base, "path_template": "/api/v1/not-reviewed"}).status_code == 403
    response = api(admin, "POST", "/tools", {**base, "path_template": "/api/v1/projects", "requires_user_context": False, "tenant_field": None})
    assert response.status_code == 422 and response.json()["error"]["code"] == "POLICY_LOCKED"
    response = api(admin, "POST", "/tools", {**base, "path_template": "/api/v1/projects", "allow_fields": ["ref", "budget"]})
    assert response.status_code == 422 and response.json()["error"]["code"] == "POLICY_LOCKED"


def test_identity_routing_and_approval_arguments_cannot_be_declared():
    schema = {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "maxLength": 20}}}
    assert validate_input_schema(schema)["properties"]["status"]["maxLength"] == 20
    for reserved in ("user_id", "tenant_id", "role", "approved", "url"):
        with pytest.raises(HubError):
            validate_input_schema({**schema, "properties": {reserved: {"type": "string"}}})


def test_sample_test_validates_required_input(published):
    admin = published["admin"]
    created = create_tool(admin, published["tool"]["connector_id"], tool_key="your_app.projects.required",
                          input_schema={"type": "object", "additionalProperties": False, "required": ["limit"],
                                        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}})
    tested = api(admin, "POST", f"/tools/{created['id']}/test", {"mode": "sample", "sample": {"data": [], "meta": META}}).json()["data"]
    assert tested["passed"] is False and "missing required argument 'limit'" in tested["error_message"]
    assert api(admin, "POST", f"/tools/{created['id']}/publish").status_code == 409


def test_complete_backup_restore_preserves_secrets_tests_and_runtime(published):
    admin = published["admin"]
    with open_session() as db:
        encrypted = db.scalar(select(ConnectorSecret)).secret_ciphertext
    backup = api(admin, "POST", "/operations/export", expect=200).json()["data"]
    assert backup["tables"]["tool_test_runs"]
    assert "dev-your-app-key" not in json.dumps(backup)
    restored = api(admin, "POST", "/operations/import", backup)
    assert restored.status_code == 200, restored.text
    with open_session() as db:
        assert db.scalar(select(ConnectorSecret)).secret_ciphertext == encrypted
    assert result(call(published, arguments={"status": "active"}))["success"] is True
    bad = copy.deepcopy(backup)
    bad["tables"]["field_policies"][0]["module_id"] = "missing-parent"
    assert api(admin, "POST", "/operations/import", bad).status_code == 422
    assert result(call(published, arguments={"status": "active"}))["success"] is True
    legacy = copy.deepcopy(backup)
    legacy["tables"]["mcp_server_profiles"] = [{"id": "x", "key": "default"}]
    assert api(admin, "POST", "/operations/import", legacy).status_code == 200


@pytest.mark.parametrize("user,tenant", [("unknown", "tenant_a"), ("revoked_user", "tenant_a"), ("user_1", "tenant_b")])
def test_reference_source_reauthorizes_known_active_user(user, tenant):
    assertion = sign_payload("dev-delegation-secret", {"app_key": "your_app", "user_ref": user, "tenant_id": tenant, "aud": "http://testserver"})
    with TestClient(source_app) as client:
        assert client.get("/api/v1/projects", headers={"X-API-Key": "dev-your-app-key", "X-Hub-Assertion": assertion}).status_code == 403


def test_reference_source_record_permissions_and_pagination():
    def headers(user):
        return {"X-API-Key": "dev-your-app-key", "X-Hub-Assertion": sign_payload("dev-delegation-secret", {
            "app_key": "your_app", "user_ref": user, "tenant_id": "tenant_a", "aud": "http://testserver"})}
    with TestClient(source_app) as client:
        body = client.get("/api/v1/projects?limit=1", headers=headers("user_1")).json()
        assert body["meta"]["coverage"] == "partial" and body["meta"]["has_more"] is True
        assert body["meta"]["total_count"] == 8
        page = client.get("/api/v1/projects?limit=1&cursor=" + body["meta"]["next_cursor"], headers=headers("user_1")).json()
        assert page["data"][0]["ref"] == "prj_200"
        body = client.get("/api/v1/projects", headers=headers("user_2")).json()
        assert [row["ref"] for row in body["data"]] == ["prj_200"]
        assert client.get("/api/v1/projects?limit=0", headers=headers("user_1")).status_code == 422
        assert CANARY not in json.dumps(body) and "owner_email" not in json.dumps(body)
        proposal = client.post("/api/v1/projects", headers=headers("user_1"), json={"name": "New clinic"}).json()
        assert proposal["data"][0]["status"] == "pending_confirmation"
        assert client.post("/api/v1/projects", headers=headers("user_2"), json={"name": "New clinic"}).status_code == 403


def test_source_denies_long_lived_signed_assertion():
    assertion = sign_payload("dev-delegation-secret", {"app_key": "your_app", "user_ref": "user_1", "tenant_id": "tenant_a",
                                                       "aud": "http://testserver"}, ttl_seconds=86400)
    with TestClient(source_app) as client:
        assert client.get("/api/v1/projects", headers={"X-API-Key": "dev-your-app-key", "X-Hub-Assertion": assertion}).status_code == 403


def test_official_sdk_client_discovers_and_executes_protocol_target(published):
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    from mcp import ClientSession

    async def exercise():
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=published["client"].app), headers=published["headers"]) as http_client:
            async with streamable_http_client("http://testserver/mcp", http_client=http_client) as streams:
                async with ClientSession(*streams, read_timeout_seconds=8) as session:
                    await session.discover()
                    assert session.protocol_version == "2026-07-28"
                    tools = await session.list_tools()
                    definition = next(t for t in tools.tools if t.name == published["tool"]["mcp_name"])
                    assert definition.input_schema == published["tool"]["input_schema"]
                    assert definition.output_schema["properties"]["data"] == published["tool"]["output_schema"]
                    assert definition.input_schema["additionalProperties"] is False
                    assert (await session.call_tool(published["tool"]["mcp_name"], {"status": "active"})).is_error is False
                    report = await session.call_tool("run_report", {"source": "projects", "group_by": ["status"]})
                    assert report.is_error is False and report.structured_content["data"]["mode"] == "groups"
                    sources = await session.call_tool("list_data_sources", {})
                    assert sources.is_error is False

    async def bounded():
        await asyncio.wait_for(exercise(), 15)

    with helpers.source(helpers.leaky_handler):
        published["client"].portal.call(bounded)
