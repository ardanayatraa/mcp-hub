"""Connect an app, build a tool from a template, publish it and call it over MCP."""

import copy
import json

from app.persistence.models import ToolDefinition, ToolTestRun
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import (
    CANARY,
    api,
    call,
    connect_app,
    create_tool,
    delegation,
    issue_key,
    listed,
    publish,
    result,
)


def test_admin_connects_app_and_publishes_a_tool_without_code(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source(helpers.leaky_handler):
        app = connect_app(admin)
        tool = create_tool(admin, app["connector_id"],
                           input_schema={"type": "object", "additionalProperties": False,
                                         "properties": {"status": {"type": "string", "enum": ["active", "completed"]}}},
                           allow_fields=["ref", "name", "status", "created_at"])
        assert tool["status"] == "draft" and tool["mcp_name"] == "your_app__projects__list"
        assert api(admin, "POST", f"/tools/{tool['id']}/publish").status_code == 409  # a test must pass first

        tested = api(admin, "POST", f"/tools/{tool['id']}/test", {"mode": "sample", "tenant_id": "tenant_a", "sample": {"data": [
            {"ref": "prj_125", "name": "Website Villa", "status": "active", "created_at": "2026-10-01",
             "tenant_id": "tenant_a", "owner_email": CANARY},
            {"ref": "prj_900", "name": "Other", "status": "active", "created_at": "2026-10-02",
             "tenant_id": "tenant_b", "owner_email": "canary.b@example.com"}]}}, expect=200).json()["data"]
        preview = json.dumps(tested)
        assert tested["passed"] and CANARY not in preview and "prj_900" not in preview and "prj_125" in preview
        assert all(tested["checks"].values()) and set(tested["checks"]) >= {"unknown_input_rejected", "pii_rejected"}
        published = api(admin, "POST", f"/tools/{tool['id']}/publish", expect=200).json()["data"]
        assert published["status"] == "published" and published["stale"] is False

        token = issue_key(admin)
        assert helpers.mcp(admin["client"], None, "tools/list").status_code in {401, 403}
        names = listed(admin["client"], token)
        assert {"list_data_sources", "run_report", "your_app__projects__list"} <= set(names)
        description = next(t for t in helpers.mcp(admin["client"], token, "tools/list").json()["result"]["tools"]
                           if t["name"] == "your_app__projects__list")["description"]
        assert description.startswith("List project status for the signed-in tenant.")

        response = call(admin["client"], token, "your_app__projects__list", {"status": "active"}, delegation())
        body = result(response)
        assert CANARY not in response.text and "prj_900" not in response.text and "budget" not in response.text
        assert {row["ref"] for row in body["data"]} == {"prj_125", "prj_210", "prj_220"}
        assert body["meta"]["coverage"] == "partial"  # the source returned another tenant's row; the Hub dropped it

        logs = api(admin, "GET", "/executions", expect=200)
        assert CANARY not in logs.text
        assert any(row["tool_key"] == "your_app.projects.list" and row["result"] == "success" for row in logs.json()["data"])


def test_template_defaults_come_from_the_source_contract(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        tool = create_tool(admin, app["connector_id"], tool_key="projects.overview", description="", method=None, path_template="")
    assert tool["tool_key"] == "your_app.projects.overview"
    assert tool["description"] == "Read Projects records from Your App."
    assert set(tool["input_schema"]["properties"]) == {"status", "limit", "cursor"}
    assert tool["allow_fields"] == ["ref", "name", "status", "created_at"]  # budget is aggregate-only
    assert tool["pagination"] == {"limit_parameter": "limit", "cursor_parameter": "cursor"}


def test_editing_a_live_tool_takes_it_offline_until_it_passes_again(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        tool = publish(admin, create_tool(admin, app["connector_id"])["id"])
        token = issue_key(admin)
        changed = api(admin, "PATCH", f"/tools/{tool['id']}", {"timeout_ms": 2000}, expect=200).json()["data"]
        assert changed["status"] == "draft" and changed["version"] == "1.0.1"
        assert "your_app__projects__list" not in listed(admin["client"], token)
        assert api(admin, "POST", f"/tools/{tool['id']}/publish").status_code == 409
        republished = publish(admin, tool["id"])
        assert republished["status"] == "published" and republished["version"] == "1.0.1"
        assert result(call(admin["client"], token, "your_app__projects__list", {}, delegation()))["success"] is True
        unchanged = api(admin, "PATCH", f"/tools/{tool['id']}", {"timeout_ms": 2000}, expect=200).json()["data"]
        assert unchanged["status"] == "published"


def test_tools_can_be_disabled_then_deleted_but_not_while_live(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        tool = publish(admin, create_tool(admin, app["connector_id"])["id"])
        assert api(admin, "DELETE", f"/tools/{tool['id']}").status_code == 409
        api(admin, "POST", f"/tools/{tool['id']}/disable", expect=200)
        api(admin, "DELETE", f"/tools/{tool['id']}", expect=200)
    with open_session() as db:
        assert db.get(ToolDefinition, tool["id"]) is None
        assert list(db.scalars(select(ToolTestRun).where(ToolTestRun.tool_id == tool["id"]))) == []


def test_contract_change_disables_only_the_changed_data_source(admin, monkeypatch):
    helpers.dns(monkeypatch)
    original = copy.deepcopy(helpers.MANIFEST)
    try:
        with helpers.source():
            app = connect_app(admin, enable={"projects": ["read"], "activity": ["read"]})
            tool = publish(admin, create_tool(admin, app["connector_id"])["id"])
            helpers.MANIFEST["modules"][1]["description"] = "Changed activity contract"
            changes = {row["module_key"]: row["change"] for row in
                       api(admin, "POST", f"/connectors/{app['connector_id']}/discover", expect=200).json()["data"]["modules"]}
            assert changes == {"projects": "unchanged", "activity": "changed"}
            sources = {row["module_key"]: row for row in api(admin, "GET", "/modules", expect=200).json()["data"]}
            assert sources["projects"]["enabled"] is True and sources["activity"]["enabled"] is False
            assert api(admin, "GET", f"/tools/{tool['id']}", expect=200).json()["data"]["stale"] is False
    finally:
        helpers.MANIFEST.clear()
        helpers.MANIFEST.update(original)


def test_ssrf_connector_url_is_rejected(admin):
    response = api(admin, "POST", "/connectors", {"name": "Bad", "app_key": "bad_app", "base_url": "http://169.254.169.254",
                                                  "auth_type": "bearer", "secret": "dev-your-app-key"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SSRF_BLOCKED"
    assert "169.254.169.254" not in response.json()["error"]["message"]


def test_apps_are_called_with_a_bearer_token_only(admin, monkeypatch):
    helpers.dns(monkeypatch)
    refused = api(admin, "POST", "/connectors", {"name": "Old style", "app_key": "old_style", "base_url": "http://projects.test",
                                                 "auth_type": "api_key", "secret": helpers.API_KEY})
    assert refused.status_code == 422
    with helpers.source():
        created = api(admin, "POST", "/connectors", {"name": "Bearer", "app_key": "bearer_app", "base_url": "http://projects.test",
                                                     "secret": helpers.API_KEY}, expect=201).json()["data"]
        assert created["auth_type"] == "bearer"
        assert api(admin, "POST", f"/connectors/{created['id']}/test", expect=200).json()["data"]["status"] == "ok"
    sent = helpers.CALLS[-1].headers
    assert sent["Authorization"] == f"Bearer {helpers.API_KEY}" and "X-API-Key" not in sent


def test_connection_test_explains_failures(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        created = api(admin, "POST", "/connectors", {"name": "Wrong key", "app_key": "wrong_key", "base_url": "http://projects.test",
                                                     "auth_type": "bearer", "secret": "not-the-right-key"}, expect=201).json()["data"]
        tested = api(admin, "POST", f"/connectors/{created['id']}/test", expect=200).json()["data"]
    assert tested["status"] == "fail" and tested["error_category"] == "authorization" and "bearer token" in tested["hint"]
    assert api(admin, "POST", f"/connectors/{created['id']}/activate").status_code == 422
    api(admin, "DELETE", f"/connectors/{created['id']}", expect=200)
    assert all(row["id"] != created["id"] for row in api(admin, "GET", "/connectors").json()["data"])
