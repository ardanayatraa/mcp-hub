"""Profiles restrict every MCP entry point without widening existing permissions."""

import copy

from app.persistence.models import AdminUser, McpAccessProfile, ServiceIdentity
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import (
    api,
    call,
    connect_app,
    create_tool,
    delegation,
    error_text,
    issue_key,
    listed,
    mcp,
    publish,
    result,
)
from tests.integration.test_access import write_tool


def profile(admin, app, **values):
    return api(admin, "POST", "/mcp-profiles", {"app_id": app["app_id"], "name": "Reporting", **values},
               expect=201).json()["data"]


def test_profiles_default_closed_and_do_not_change_unbound_keys(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        row = profile(admin, app)
        token = issue_key(admin, profile_id=row["id"])
        assert row["enabled"] is False and row["modules"] == row["tools"] == [] and row["revision"] == 1
        assert mcp(admin["client"], token, "tools/list").status_code == 401
        assert listed(admin["client"], issue_key(admin)) == ["list_data_sources", "run_report"]
        api(admin, "PATCH", f"/mcp-profiles/{row['id']}", {"revision": 1, "enabled": True}, expect=200)
        assert listed(admin["client"], token) == []
        assert "not allowed" in error_text(call(admin["client"], token, "list_data_sources"))


def test_profile_module_restriction_covers_discovery_reports_and_direct_calls(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source() as requests:
        app = connect_app(admin, enable={"projects": ["read"], "activity": ["read"]})
        tool = publish(admin, create_tool(admin, app["connector_id"])["id"])
        row = profile(admin, app, enabled=True, modules=["activity"],
                      tools=["list_data_sources", "run_report", tool["mcp_name"]])
        token = issue_key(admin, profile_id=row["id"])
        assert listed(admin["client"], token) == ["list_data_sources", "run_report"]
        sources = result(call(admin["client"], token, "list_data_sources"))["data"]
        assert [source["source"] for source in sources] == ["activity"]
        before = len(requests)
        for name, arguments in [(tool["mcp_name"], {}), ("run_report", {"source": "projects"}),
                                ("run_report", {"source": "your_app:projects"})]:
            assert "PERMISSION_DENIED" in error_text(call(admin["client"], token, name, arguments, delegation()))
        assert len(requests) == before  # Hidden business records were never requested.
        assert result(call(admin["client"], token, "run_report", {"source": "activity"}, delegation()))["success"]


def test_key_allowlist_intersects_profiles_and_neither_grants_write_scope(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source() as requests:
        app = connect_app(admin, enable={"projects": ["read", "create"]})
        write = write_tool(admin, app["connector_id"])
        row = profile(admin, app, enabled=True, modules=["projects"],
                      tools=["list_data_sources", "run_report", write["mcp_name"]])
        narrow = issue_key(admin, profile_id=row["id"], allowed_tools=["list_data_sources"])
        assert listed(admin["client"], narrow) == ["list_data_sources"]
        assert "not allowed" in error_text(call(admin["client"], narrow, "run_report", {"source": "projects"}, delegation()))
        reader = issue_key(admin, profile_id=row["id"])
        assert write["mcp_name"] not in listed(admin["client"], reader)
        before = len(requests)
        assert "write permission" in error_text(call(admin["client"], reader, write["mcp_name"], {"name": "Draft"}, delegation()))
        assert len(requests) == before
        writer = issue_key(admin, profile_id=row["id"], write=True)
        assert write["mcp_name"] in listed(admin["client"], writer)
        api(admin, "PATCH", f"/modules/{app['modules']['projects']}/settings",
            {"enabled": False, "operations": []}, expect=200)
        assert write["mcp_name"] not in listed(admin["client"], writer)


def test_profile_revision_disable_and_key_binding_are_effective_on_next_request(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        row = profile(admin, app, enabled=True, modules=["projects"], tools=["run_report"])
        token = issue_key(admin, profile_id=row["id"])
        key = api(admin, "GET", "/service-identities").json()["data"][0]
        assert key["profile_name"] == row["name"]
        api(admin, "PATCH", f"/service-identities/{key['id']}", {"name": "Reader"}, expect=200)
        assert listed(admin["client"], token) == ["run_report"]  # Omission preserves the binding.
        changed = api(admin, "PATCH", f"/mcp-profiles/{row['id']}", {"revision": 1, "enabled": False}, expect=200).json()["data"]
        assert changed["revision"] == 2 and changed["bound_keys"] == 1
        api(admin, "PATCH", f"/mcp-profiles/{row['id']}", {"revision": 1, "enabled": True}, expect=409)
        assert mcp(admin["client"], token, "tools/list").status_code == 401
        assert api(admin, "GET", "/service-identities").json()["data"][0]["status"] == "blocked"
        api(admin, "GET", f"/tools/agent-view?connector_id={app['connector_id']}&key_id={key['id']}", expect=409)
        api(admin, "PATCH", f"/service-identities/{key['id']}", {"profile_id": None}, expect=200)
        assert listed(admin["client"], token) == ["list_data_sources", "run_report"]


def test_profiles_enforce_csrf_roles_app_scope_and_own_metadata(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        row = profile(admin, app)
        body = {"app_id": app["app_id"]}
        assert admin["client"].post("/api/admin/v1/mcp-profiles", json=body).status_code == 403
        for values in [{"modules": ["unknown"]}, {"tools": ["other_app__orders__list"]},
                       {"name": "canary@example.com"}, {"enabled": "true"}, {"tools": ["a" * 81]}, {"write": True}]:
            api(admin, "POST", "/mcp-profiles", {**body, **values}, expect=422)
        api(admin, "PATCH", f"/mcp-profiles/{row['id']}", {"name": "Missing revision"}, expect=422)
        with open_session() as db:
            db.scalar(select(AdminUser)).role = "auditor"
            db.commit()
        api(admin, "GET", f"/mcp-profiles?app_id={app['app_id']}", expect=403)
        api(admin, "PATCH", f"/mcp-profiles/{row['id']}", {"revision": 1, "enabled": True}, expect=403)


def test_foreign_profile_binding_fails_closed_and_cannot_be_assigned(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        row = profile(admin, app, enabled=True, modules=["projects"], tools=["run_report"])
        foreign = api(admin, "POST", "/connectors", {"name": "Shop", "app_key": "shop", "environment": "dev",
            "base_url": "https://shop.example.com", "auth_type": "bearer", "secret": helpers.API_KEY}, expect=201).json()["data"]
        api(admin, "POST", "/service-identities", {"app_key": "shop", "environment": "dev", "profile_id": row["id"]}, expect=403)
        token = issue_key(admin, app_key="shop")
        key = next(item for item in api(admin, "GET", "/service-identities").json()["data"] if item["app_id"] == foreign["app_id"])
        api(admin, "PATCH", f"/service-identities/{key['id']}", {"profile_id": row["id"]}, expect=403)
        # Even inconsistent data introduced outside the API cannot widen access.
        with open_session() as db:
            db.get(ServiceIdentity, key["id"]).profile_id = row["id"]
            db.commit()
        assert mcp(admin["client"], token, "tools/list").status_code == 401
        with open_session() as db:
            db.get(McpAccessProfile, row["id"]).enabled = False
            db.commit()
        assert mcp(admin["client"], token, "tools/list").status_code == 401


def test_agent_preview_and_skills_follow_profile_tool_restrictions(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        api(admin, "POST", "/skills", {"connector_id": app["connector_id"], "key": "weekly_report", "title": "Weekly report",
            "description": "Weekly report", "instructions": "Use run_report and show the totals.", "tools": ["run_report"]}, expect=201)
        row = profile(admin, app, enabled=True, modules=["projects"], tools=["list_data_sources"])
        token = issue_key(admin, profile_id=row["id"])
        key = api(admin, "GET", "/service-identities").json()["data"][0]
        preview = api(admin, "GET", f"/tools/agent-view?connector_id={app['connector_id']}&key_id={key['id']}", expect=200).json()["data"]
        assert [tool["name"] for tool in preview["tools"]] == listed(admin["client"], token) == ["list_data_sources"]
        assert preview["prompts"] == mcp(admin["client"], token, "prompts/list").json()["result"]["prompts"] == []
        assert preview["key"]["profile_id"] == row["id"]


def test_backup_preserves_profile_bindings_and_rejects_broken_references(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        row = profile(admin, app, enabled=True, modules=["projects"], tools=["run_report"])
        token = issue_key(admin, profile_id=row["id"])
        backup = api(admin, "POST", "/operations/export", expect=200).json()["data"]
        assert backup["tables"]["mcp_access_profiles"][0]["id"] == row["id"]
        assert backup["tables"]["service_identities"][0]["profile_id"] == row["id"]
        api(admin, "POST", "/operations/import", backup, expect=200)
        assert listed(admin["client"], token) == ["run_report"]
        broken = copy.deepcopy(backup)
        broken["tables"]["mcp_access_profiles"] = []
        api(admin, "POST", "/operations/import", broken, expect=422)
        assert listed(admin["client"], token) == ["run_report"]
