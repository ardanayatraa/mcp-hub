"""Client key permissions and optional write tools."""

import copy
import json
from pathlib import Path

import httpx
import pytest
from app.persistence.models import AdminUser
from app.persistence.session import open_session
from app.services import tools as tool_service
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
    publish,
    result,
)


def managed_manifest(document=None):
    manifest = copy.deepcopy(document or helpers.MANIFEST)
    manifest["managed_by"] = "application"
    for module in manifest["modules"]:
        for index, route in enumerate(module.get("read_endpoints", [])):
            route.setdefault("tool_key", f"{manifest['application']}.{module['key']}." + ("list" if index == 0 else f"read_{index}"))
        for route in module.get("write_endpoints", []):
            route.setdefault("tool_key", f"{manifest['application']}.{module['key']}.prepare_{route['operation']}")
    return manifest


def connect_managed(admin, app_key="your_app"):
    app = api(admin, "POST", "/connectors", {
        "name": "Source managed", "app_key": app_key, "environment": "dev", "connector_type": "source_managed",
        "base_url": "http://projects.test", "auth_type": "api_key", "secret": helpers.API_KEY,
        "delegation_secret": helpers.DELEGATION_SECRET}, expect=201).json()["data"]
    api(admin, "POST", f"/connectors/{app['id']}/test", expect=200)
    api(admin, "POST", f"/connectors/{app['id']}/discover", expect=200)
    api(admin, "POST", f"/connectors/{app['id']}/activate", expect=200)
    return app


def test_source_managed_tools_need_no_manual_enable_test_or_publish(admin, monkeypatch):
    helpers.dns(monkeypatch)
    monkeypatch.setattr(helpers, "MANIFEST", managed_manifest())
    with helpers.source() as requests:
        app = connect_managed(admin)
        reader, writer = issue_key(admin), issue_key(admin, write=True)
        read_name, write_name = "your_app__projects__list", "your_app__projects__prepare_create"
        assert read_name in listed(admin["client"], reader)
        assert write_name not in listed(admin["client"], reader)
        assert write_name in listed(admin["client"], writer)
        # Discovery never sends a write or reads records as an invented user.
        assert not [request for request in requests if request.url.path in {"/api/v1/projects", "/api/v1/activity"}]
        rows = result(call(admin["client"], reader, read_name, {}, delegation()))["data"]
        assert len(rows) == 4 and not any("budget" in row or "owner_email" in row for row in rows)
        assert "PERMISSION_DENIED" in error_text(call(admin["client"], reader, read_name))
        assert "write permission" in error_text(call(admin["client"], reader, write_name, {"name": "Clinic"}, delegation()))
        proposal = result(call(admin["client"], writer, write_name, {"name": "Clinic"}, delegation()))
        assert proposal["meta"]["requires_confirmation"] is True
        assert proposal["data"][0]["proposal_ref"] == "prop_test1"
        narrow = issue_key(admin, allowed_tools=["run_report"])
        assert listed(admin["client"], narrow) == ["run_report"]
        assert api(admin, "POST", "/tools", {"connector_id": app["id"], "module_key": "projects",
                   "tool_key": "projects.custom"}).status_code == 409
        modules = api(admin, "GET", "/modules").json()["data"]
        assert api(admin, "PATCH", f"/modules/{modules[0]['id']}/settings", {"enabled": False}).status_code == 409
        tools = api(admin, "GET", "/tools").json()["data"]
        for tool in tools:
            assert tool["source_managed"] and not tool["stale"] and tool["status"] == "published"
            assert api(admin, "PATCH", f"/tools/{tool['id']}", {"description": "Override source"}).status_code == 409
            assert api(admin, "POST", f"/tools/{tool['id']}/disable").status_code == 409


def test_source_changes_reconcile_on_next_list_and_call_without_manual_sync(admin, monkeypatch):
    helpers.dns(monkeypatch)
    manifest = managed_manifest()
    activity = manifest["modules"].pop()
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    with helpers.source() as requests:
        connect_managed(admin)
        token = issue_key(admin, write=True)
        assert "your_app__activity__list" not in listed(admin["client"], token)
        before = api(admin, "GET", "/tools").json()["data"]
        listed(admin["client"], token)
        after = api(admin, "GET", "/tools").json()["data"]
        assert [(tool["id"], tool["version"]) for tool in before] == [(tool["id"], tool["version"]) for tool in after]
        manifest["modules"].append(activity)
        assert result(call(admin["client"], token, "your_app__activity__list", {}, delegation()))["success"]
        assert "your_app__activity__list" in listed(admin["client"], token)
        manifest["modules"][0]["supported_operations"] = ["read"]
        manifest["modules"][0]["write_endpoints"] = []
        denied = call(admin["client"], token, "your_app__projects__prepare_create", {"name": "Clinic"}, delegation())
        assert "PERMISSION_DENIED" in error_text(denied)
        assert not [request for request in requests if request.method == "POST" and request.url.path == "/api/v1/projects"]
        manifest["modules"].clear()
        assert listed(admin["client"], token) == ["list_data_sources", "run_report"]
        assert result(call(admin["client"], token, "list_data_sources"))["data"] == []
        assert "PERMISSION_DENIED" in error_text(call(admin["client"], token, "your_app__projects__list", {}, delegation()))
        manifest["modules"].append(activity)
        assert "your_app__activity__list" in listed(admin["client"], token)


def test_source_managed_empty_initial_contract_can_connect(admin, monkeypatch):
    helpers.dns(monkeypatch)
    manifest = managed_manifest()
    manifest["modules"] = []
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    with helpers.source():
        app = connect_managed(admin)
        assert app["connector_type"] == "source_managed"
        assert listed(admin["client"], issue_key(admin)) == ["list_data_sources", "run_report"]


@pytest.mark.parametrize("failure", ["unavailable", "unmanaged", "wrong_app", "wrong_tool", "malformed", "late_build_failure"])
def test_invalid_source_policy_fails_closed_and_does_not_partly_publish(admin, monkeypatch, failure):
    helpers.dns(monkeypatch)
    manifest = managed_manifest()
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    broken = False

    def handler(request):
        if broken and failure == "unavailable" and request.url.path.endswith("/capabilities"):
            return httpx.Response(503, json={"error": "unavailable"})
        return helpers.handler(request)

    with helpers.source(handler) as requests:
        connected = connect_managed(admin)
        token = issue_key(admin)
        before = api(admin, "GET", "/tools").json()["data"]
        broken = True
        if failure == "unmanaged":
            manifest.pop("managed_by")
        elif failure == "wrong_app":
            manifest["application"] = "other_app"
        elif failure == "wrong_tool":
            manifest["modules"][-1]["read_endpoints"][0]["tool_key"] = "other_app.activity.list"
        elif failure == "malformed":
            manifest["modules"][-1]["read_endpoints"][0]["input_schema"] = {}
        elif failure == "late_build_failure":
            manifest["modules"][0]["read_endpoints"][0]["description"] = "Updated first tool before the last tool fails."
            manifest["modules"][-1]["read_endpoints"][0]["tool_key"] = "your_app.activity." + "x" * 41 + ".extra"
        assert listed(admin["client"], token) == []
        assert call(admin["client"], token, "your_app__projects__list", {}, delegation()).json()["result"]["isError"]
        assert not [request for request in requests if request.url.path == "/api/v1/projects"]
        assert api(admin, "GET", "/tools").status_code == 422
        connection = api(admin, "GET", f"/connectors/{connected['id']}", expect=200).json()["data"]
        assert connection["source_sync_error"] and connection["sources_total"] == connection["tools_total"] == 0
        assert api(admin, "GET", "/connectors", expect=200).json()["data"][0]["source_sync_error"]
        with open_session() as db:
            after = tool_service.list_tools(db, db.scalar(select(AdminUser)))
        assert [(tool["id"], tool["version"], tool["status"]) for tool in before] == [
            (tool["id"], tool["version"], tool["status"]) for tool in after]


@pytest.mark.parametrize("refresh", ["/tools", "/modules", "/connectors", "/connectors/{id}"])
def test_admin_catalog_matches_only_current_source_models_without_a_chat_request(admin, monkeypatch, refresh):
    helpers.dns(monkeypatch)
    manifest = managed_manifest()
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    with helpers.source() as requests:
        app = connect_managed(admin)
        original = api(admin, "GET", "/tools", expect=200).json()["data"]
        activity_tool = next(tool for tool in original if tool["module_key"] == "activity")
        activity = manifest["modules"].pop()
        api(admin, "GET", refresh.format(id=app["id"]), expect=200)
        modules = api(admin, "GET", "/modules", expect=200).json()["data"]
        tools = api(admin, "GET", "/tools", expect=200).json()["data"]
        assert [module["module_key"] for module in modules] == ["projects"]
        assert all(tool["module_key"] == "projects" and tool["status"] == "published" for tool in tools)
        counts = api(admin, "GET", f"/connectors/{app['id']}", expect=200).json()["data"]
        assert counts["sources_enabled"] == counts["sources_total"] == 1
        assert counts["tools_published"] == counts["tools_total"] == len(tools)
        assert modules[0]["tools"] == len(tools)
        # History remains available by its ID, but never masquerades as a current grant.
        retired = api(admin, "GET", f"/tools/{activity_tool['id']}", expect=200).json()["data"]
        assert retired["status"] == "disabled"
        manifest["modules"].append(activity)
        restored = api(admin, "GET", "/tools", expect=200).json()["data"]
        assert next(tool for tool in restored if tool["module_key"] == "activity")["id"] == activity_tool["id"]
        manifest["modules"].clear()
        assert api(admin, "GET", "/modules", expect=200).json()["data"] == []
        assert api(admin, "GET", "/tools", expect=200).json()["data"] == []
        assert not [request for request in requests if request.url.path in {"/api/v1/projects", "/api/v1/activity"}]


def test_source_marker_does_not_enable_automatic_permissions_on_manual_connector(admin, monkeypatch):
    helpers.dns(monkeypatch)
    monkeypatch.setattr(helpers, "MANIFEST", managed_manifest())
    with helpers.source():
        app = connect_app(admin, enable={})
        assert listed(admin["client"], issue_key(admin)) == ["list_data_sources", "run_report"]
        assert api(admin, "GET", "/tools").json()["data"] == []
        assert app["modules"]


def test_admin_refresh_never_contacts_a_source_outside_application_scope(admin, monkeypatch):
    helpers.dns(monkeypatch)
    monkeypatch.setattr(helpers, "MANIFEST", managed_manifest())
    with helpers.source() as requests:
        app = connect_managed(admin)
        with open_session() as db:
            db.scalar(select(AdminUser)).role = "auditor"
            db.commit()
        count = len(requests)
        for path in ["/connectors", "/modules", "/tools"]:
            assert api(admin, "GET", path, expect=200).json()["data"] == []
        assert api(admin, "GET", f"/connectors/{app['id']}").status_code == 403
        assert len(requests) == count


def write_tool(admin, connector_id):
    tool = create_tool(admin, connector_id, template="create", tool_key="projects.create",
                       description="Propose a new project for the signed-in user.", method="POST",
                       path_template="/api/v1/projects")
    return publish(admin, tool["id"], {"mode": "sample", "arguments": {"name": "New project"}})


def test_key_allowlist_limits_discovery_and_calls(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        tool = publish(admin, create_tool(admin, app["connector_id"])["id"])
        narrow = issue_key(admin, allowed_tools=["run_report"])
        assert listed(admin["client"], narrow) == ["run_report"]
        assert "not allowed" in error_text(call(admin["client"], narrow, tool["mcp_name"], {}, delegation()))
        assert result(call(admin["client"], narrow, "run_report", {"source": "projects"}, delegation()))["success"]
        bad = api(admin, "POST", "/service-identities", {"app_key": "your_app", "allowed_tools": ["other_app__x"]})
        assert bad.status_code == 422


def test_write_tools_need_an_enabled_operation_and_a_write_key(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source() as calls:
        app = connect_app(admin)
        blocked = create_tool(admin, app["connector_id"], template="create", tool_key="projects.create", method="POST",
                              path_template="/api/v1/projects")
        helpers.run_tool_test(admin, blocked["id"], {"mode": "sample", "arguments": {"name": "New project"}})
        denied = api(admin, "POST", f"/tools/{blocked['id']}/publish")
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "MODULE_DISABLED"
        api(admin, "DELETE", f"/tools/{blocked['id']}", expect=200)

        api(admin, "PATCH", f"/modules/{app['modules']['projects']}/settings", {"enabled": True, "operations": ["read", "create"]},
            expect=200)
        tool = write_tool(admin, app["connector_id"])
        assert tool["risk"] == "write" and tool["mcp_tool"]["annotations"]["readOnlyHint"] is False
        reader, writer = issue_key(admin), issue_key(admin, write=True)
        assert tool["mcp_name"] not in listed(admin["client"], reader)
        assert "write permission" in error_text(call(admin["client"], reader, tool["mcp_name"], {"name": "Clinic"}, delegation()))
        assert tool["mcp_name"] in listed(admin["client"], writer)
        assert "PERMISSION_DENIED" in error_text(call(admin["client"], writer, tool["mcp_name"], {"name": "Clinic"}))
        receipt = result(call(admin["client"], writer, tool["mcp_name"], {"name": "Clinic"}, delegation()))
        assert receipt["data"] == [{"proposal_ref": "prop_test1", "summary": "Create project 'Clinic'", "status": "pending_confirmation"}]
        assert receipt["meta"]["requires_confirmation"] is True and receipt["meta"]["operation"] == "create"
        posted = [request for request in calls if request.method == "POST" and request.url.path.endswith("/projects")]
        assert len(posted) == 1 and posted[0].headers.get("Idempotency-Key", "").startswith("tr_")
        assert "PII_DETECTED" in error_text(call(admin["client"], writer, tool["mcp_name"], {"name": "Call +6281234567890"}, delegation()))


def test_write_tools_are_never_sent_from_the_test_console(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source() as calls:
        app = connect_app(admin, enable={"projects": ["read", "create"]})
        tool = create_tool(admin, app["connector_id"], template="create", tool_key="projects.create", method="POST",
                           path_template="/api/v1/projects")
        live = helpers.run_tool_test(admin, tool["id"], {"mode": "live", "arguments": {"name": "New project"}})
        assert live["passed"] is False and live["error_code"] == "VALIDATION_FAILED"
        sample = helpers.run_tool_test(admin, tool["id"], {"mode": "sample", "arguments": {"name": "New project"}})
        assert sample["passed"] and sample["request"] == {"method": "POST", "path": "/api/v1/projects", "fields": ["name"], "sent": False}
        assert not [request for request in calls if request.method == "POST" and request.url.path.endswith("/projects")]


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("source_managed", [False, True])
def test_generated_laravel_contract_works_with_crud_templates_and_actor_permissions(admin, monkeypatch, operation, source_managed):
    # Generated by Laravel using dummy registration/config and isolated SQLite.
    path = Path(__file__).resolve().parents[3] / "docs/evidence/LARAVEL_CRUD_CONTRACT.json"
    manifest = json.loads(path.read_text())
    if source_managed:
        manifest = managed_manifest(manifest)
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    helpers.dns(monkeypatch)
    proposal = {"proposal_ref": "change_" + "a" * 32, "summary": f"Review {operation} Templates",
                "requires_confirmation": True}

    def source_handler(request):
        if "/prepare_" not in request.url.path:
            return helpers.handler(request)
        helpers.CALLS.append(request)
        assert request.method == "POST"
        assert request.url.path == f"/api/ai/v1/templates/prepare_{operation}"
        assert request.headers["X-API-Key"] == helpers.API_KEY
        assert request.headers["Idempotency-Key"].startswith("tr_")
        return httpx.Response(200, json={"success": True,
            "data": [{**proposal, "tenant_id": helpers._assertion_tenant(request)}],
            "meta": {"requires_confirmation": True, "contains_personal_data": False}})

    with helpers.source(source_handler) as calls:
        arguments = {"name": "Reviewed template"} if operation != "delete" else {}
        if operation != "create":
            arguments["ref"] = "tpl_1"
        if source_managed:
            connect_managed(admin, app_key="laravel_app")
            tool = next(tool for tool in api(admin, "GET", "/tools").json()["data"] if tool["template"] == operation)
        else:
            app = connect_app(admin, app_key="laravel_app", enable={"templates": ["read", operation]})
            tool = create_tool(admin, app["connector_id"], module_key="templates", template=operation,
                               tool_key=f"laravel_app.templates.prepare_{operation}", method="POST",
                               path_template=f"/api/ai/v1/templates/prepare_{operation}",
                               description=f"Prepare {operation}; the user confirms in the source application.")
            tool = publish(admin, tool["id"], {"mode": "sample", "arguments": arguments,
                        "tenant_id": "laravel_app_account_1", "sample": {"data": [{**proposal, "tenant_id": "laravel_app_account_1"}]}})
        assert not [request for request in calls if "/prepare_" in request.url.path]
        reader = issue_key(admin, app_key="laravel_app")
        writer = issue_key(admin, app_key="laravel_app", write=True)
        actor = delegation(tenant="laravel_app_account_1", user="laravel_app_user_1", app_key="laravel_app")
        assert tool["mcp_name"] not in listed(admin["client"], reader)
        assert tool["mcp_name"] in listed(admin["client"], writer)
        assert "PERMISSION_DENIED" in error_text(call(admin["client"], reader, tool["mcp_name"], arguments, actor))
        assert "PERMISSION_DENIED" in error_text(call(admin["client"], writer, tool["mcp_name"], arguments))
        receipt = result(call(admin["client"], writer, tool["mcp_name"], arguments, actor))
        assert receipt["data"] == [proposal]
        assert receipt["meta"]["operation"] == operation
        assert receipt["meta"]["requires_confirmation"] is True
        posted = [request for request in calls if "/prepare_" in request.url.path]
        assert len(posted) == 1 and json.loads(posted[0].content) == arguments
        if source_managed:
            manifest["modules"][0]["supported_operations"] = ["read"]
            manifest["modules"][0]["write_endpoints"] = []
            assert "PERMISSION_DENIED" in error_text(call(admin["client"], writer, tool["mcp_name"], arguments, actor))
        else:
            api(admin, "PATCH", f"/modules/{app['modules']['templates']}/settings", {"enabled": True, "operations": ["read"]}, expect=200)
            assert "MODULE_DISABLED" in error_text(call(admin["client"], writer, tool["mcp_name"], arguments, actor))


def test_key_permissions_can_change_and_revocation_is_immediate(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin, enable={"projects": ["read", "create"]})
        tool = write_tool(admin, app["connector_id"])
        token = issue_key(admin)
        key = next(row for row in api(admin, "GET", "/service-identities").json()["data"] if row["status"] == "active")
        api(admin, "PATCH", f"/service-identities/{key['id']}", {"write": True}, expect=200)
        assert tool["mcp_name"] in listed(admin["client"], token)
        assert result(call(admin["client"], token, "list_data_sources"))["success"]
        api(admin, "PATCH", f"/modules/{app['modules']['projects']}/settings", {"enabled": False}, expect=200)
        assert "MODULE_DISABLED" in error_text(call(admin["client"], token, "run_report", {"source": "projects"}, delegation()))
        api(admin, "POST", f"/service-identities/{key['id']}/revoke", expect=200)
        assert helpers.mcp(admin["client"], token, "tools/list").status_code == 401
        used = next(row for row in api(admin, "GET", "/service-identities").json()["data"] if row["id"] == key["id"])
        assert used["status"] == "revoked" and used["last_used_at"] is not None


def test_last_super_admin_cannot_be_removed(admin):
    me = api(admin, "GET", "/auth/me", expect=200).json()["data"]
    assert api(admin, "PATCH", f"/users/{me['id']}", {"role": "auditor"}).status_code == 409
    other = api(admin, "POST", "/users", {"email": "second@localhost", "role": "super_admin", "password": "ChangeMe-Now-12"},
                expect=201).json()["data"]
    api(admin, "PATCH", f"/users/{other['id']}", {"is_active": False}, expect=200)
    assert api(admin, "PATCH", f"/users/{me['id']}", {"is_active": False}).status_code == 409
    weak = api(admin, "POST", "/users", {"email": "weak@localhost", "role": "auditor", "password": "short"})
    assert weak.status_code == 422
