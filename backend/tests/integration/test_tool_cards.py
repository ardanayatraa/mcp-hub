"""Tools read as names, not keys, in the dashboard and activity log; a tool page shows its own usage."""

from app.tools.catalog import key_title
from tests import helpers
from tests.helpers import api, call, connect_app, delegation, issue_key, result


def test_key_titles_read_naturally():
    assert key_title("hireach.templates.count") == "Count templates"
    assert key_title("hireach.blast_messages.list") == "List blast messages"
    assert key_title("hireach.templates.get") == "Get one template"
    assert key_title("hireach.billing_users.prepare_create") == "Create a billing user"
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
