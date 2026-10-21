"""Tools read as names, not keys, in the dashboard and activity log; a tool page shows its own usage."""

from app.tools.catalog import key_title
from tests import helpers
from tests.helpers import api, call, connect_app, delegation, issue_key, result


def test_key_titles_read_naturally():
    assert key_title("shop.templates.count") == "Count templates"
    assert key_title("shop.blast_messages.list") == "List blast messages"
    assert key_title("shop.templates.get") == "Get one template"
    assert key_title("shop.billing_users.prepare_create") == "Create a billing user"
    assert key_title("shop.companies.summary") == "Companies summary"
    assert key_title("shop.activity.weekly") == "Activity: weekly"


def test_dashboard_activity_and_tool_page_name_the_tool(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        api(admin, "POST", "/tools/generate", {"connector_id": app["connector_id"]}, expect=201)
        token = issue_key(admin)
        for _ in range(3):
            result(call(admin["client"], token, "your_app__projects__list", {}, delegation()))
        call(admin["client"], token, "your_app__projects__list", {})  # no user context: denied
        result(call(admin["client"], token, "run_report", {"source": "projects"}, delegation()))

        dashboard = api(admin, "GET", "/dashboard?period=24h", expect=200).json()["data"]
        top = {item["tool_key"]: item for item in dashboard["top_tools"]}
        listing = top["your_app.projects.list"]
        assert listing["calls"] == 4 and listing["tool"]["title"] == "List projects"
        assert listing["tool"]["kind"] == "list" and listing["tool"]["app_name"] == "Your App" and listing["tool"]["tool_id"]
        assert top["run_report"]["tool"] == {"tool_id": None, "title": "Run report", "kind": "hub", "app_name": None,
                                             "module_name": None, "mcp_name": "run_report", "status": "published"}
        recent_calls = [event for event in dashboard["recent"] if event["action"] == "tool.execute"]
        assert recent_calls and all(event["tool"] for event in recent_calls)

        rows = api(admin, "GET", "/executions?kind=calls", expect=200).json()["data"]
        assert {row["tool"]["title"] for row in rows} == {"List projects", "Run report"}
        admin_rows = api(admin, "GET", "/executions?kind=admin", expect=200).json()["data"]
        assert all(row["tool"] is None for row in admin_rows)

        page = api(admin, "GET", f"/tools/{listing['tool']['tool_id']}", expect=200).json()["data"]
        assert page["display_title"] == "List projects"
        usage = page["usage"]
        assert usage["calls"] == 4 and usage["success"] == 3 and usage["denied"] == 1 and usage["success_rate"] == 0.75
        assert len(usage["series"]) == 7 and usage["series"][-1]["calls"] == 4 and usage["last_used_at"]


def test_generator_publishes_a_get_one_route(admin, monkeypatch):
    """A read route with a required path parameter that returns one row passes its sample test."""

    import copy

    from app.services.tools import sample_arguments

    assert sample_arguments({"type": "object", "required": ["ref", "status", "page"], "properties": {
        "ref": {"type": "string", "maxLength": 40}, "status": {"type": "string", "enum": ["open", "paid"]},
        "page": {"type": "integer", "minimum": 2}}}) == {"ref": "sample1", "status": "open", "page": 2}

    manifest = copy.deepcopy(helpers.MANIFEST)
    projects = manifest["modules"][0]
    listing = projects["read_endpoints"][0]
    one = copy.deepcopy(listing["output_schema"])
    one["maxItems"] = 1
    projects["read_endpoints"].append({
        "method": "GET", "path_template": "/api/v1/projects/{ref}", "requires_user_context": True, "tenant_field": "tenant_id",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["ref"],
                         "properties": {"ref": {"type": "string", "maxLength": 40}}},
        "output_schema": one})
    manifest["manifest_version"] = manifest.get("manifest_version", "1") + "-get"
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        made = api(admin, "POST", "/tools/generate", {"connector_id": app["connector_id"]}, expect=201).json()["data"]
        get = next(item for item in made["created"] if item["tool_key"] == "your_app.projects.get")
        assert get["status"] == "published" and get["title"] == "Get one project"


def test_capabilities_describe_what_the_hub_can_do(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin, enable={"projects": ["read", "create"]})
        api(admin, "POST", "/tools/generate", {"connector_id": app["connector_id"]}, expect=201)
        api(admin, "PUT", f"/connectors/{app['connector_id']}/tool-switches", {"tools": {"your_app__projects__summary": False}},
            expect=200)
        token = issue_key(admin)
        result(call(admin["client"], token, "your_app__projects__list", {}, delegation()))
        result(call(admin["client"], token, "run_report", {"source": "projects"}, delegation()))

        data = api(admin, "GET", "/tools/capabilities", expect=200).json()["data"]
        assert data["version"] and "tools/call" in data["protocol"]["methods"] and data["protocol"]["endpoint"].endswith("/mcp")
        assert data["summary"]["apps"] == 1 and data["summary"]["switched_off"] == 1 and data["summary"]["client_keys"] == 1
        assert data["report"]["metrics"] == ["count", "sum", "avg", "min", "max"] and "between" in data["report"]["filters"]
        row = data["apps"][0]
        assert row["name"] == "Your App" and row["kinds"]["list"] == 1 and row["kinds"]["report"] == 0  # summary is switched off
        assert row["memory"] is False and row["chat"] is False and row["switched_off"] == 1
        assert data["usage"] == {"your_app.projects.list": 1, "run_report": 1}

        client = admin["client"]
        api(admin, "POST", "/users", {"email": "scoped@localhost", "password": "ChangeMe-Now-12", "role": "app_admin"}, expect=201)
        client.cookies.clear()
        login = client.post("/api/admin/v1/auth/login", json={"email": "scoped@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
        scoped = client.get("/api/admin/v1/tools/capabilities", headers={"X-CSRF-Token": login["csrf_token"]}).json()["data"]
        assert scoped["apps"] == [] and scoped["usage"] == {}  # nothing from apps outside this admin's scope
