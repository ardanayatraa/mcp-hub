"""The default reporting tool and saved report tools, end to end over MCP."""

import json

import pytest
from app.config import get_settings
from tests import helpers
from tests.helpers import (
    CANARY,
    api,
    call,
    connect_app,
    create_tool,
    delegation,
    error_text,
    issue_key,
    result,
)


@pytest.fixture()
def reporting(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source() as calls:
        app = connect_app(admin, enable={"projects": ["read"], "activity": ["read"]})
        yield {"admin": admin, "client": admin["client"], "token": issue_key(admin), "app": app, "calls": calls}


def report(state, arguments, user_delegation="default"):
    return call(state["client"], state["token"], "run_report", arguments,
                delegation() if user_delegation == "default" else user_delegation)


def test_list_data_sources_shows_usable_fields_only(reporting):
    sources = {row["source"]: row for row in result(call(reporting["client"], reporting["token"], "list_data_sources"))["data"]}
    assert set(sources) == {"projects", "activity"}
    fields = {field["name"]: field for field in sources["projects"]["fields"]}
    assert set(fields) == {"ref", "name", "status", "created_at", "budget"}
    assert fields["budget"]["aggregate_only"] is True
    assert fields["status"]["values"] == ["active", "pending", "completed"]
    assert sources["projects"]["reportable"] is True


def test_run_report_groups_and_totals_across_pages(reporting, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_records", 2)  # two records per source page
    body = result(report(reporting, {"source": "projects", "group_by": ["status"],
                                     "metrics": [{"fn": "count"}, {"fn": "sum", "field": "budget"}]}))
    assert body["meta"]["pages"] == 2 and body["meta"]["records_read"] == 4 and body["meta"]["coverage"] == "complete"
    rows = {row["status"]: row for row in body["data"]["rows"]}
    assert rows["active"]["count"] == 3 and rows["active"]["sum_budget"] == 112100
    assert rows["completed"]["count"] == 1 and rows["completed"]["sum_budget"] is None  # fewer than 3 records
    assert body["data"]["totals"] == {"count": 4, "sum_budget": 160100}
    assert "hidden for groups with fewer than 3 records" in body["summary"]
    assert body["chart"] == {"type": "bar", "x": "status", "y": ["count", "sum_budget"]}
    assert CANARY not in json.dumps(body)


def test_run_report_filters_lists_and_pushes_exact_filters_to_the_source(reporting):
    body = result(report(reporting, {"source": "your_app.projects", "filters": [
        {"field": "status", "op": "eq", "value": "active"}, {"field": "created_at", "op": "gte", "value": "2026-10-01"}],
        "columns": ["ref", "created_at"], "sort": {"by": "created_at", "direction": "asc"}}))
    assert body["data"]["mode"] == "records"
    assert [row["ref"] for row in body["data"]["rows"]] == ["prj_125", "prj_220"]
    assert body["data"]["columns"] == ["ref", "created_at"]
    assert any(request.url.params.get("status") == "active" for request in reporting["calls"])


def test_time_bucket_trend_uses_the_source_timezone(reporting):
    body = result(report(reporting, {"source": "projects", "time_bucket": {"field": "created_at", "interval": "month"}}))
    assert [(row["period"], row["count"]) for row in body["data"]["rows"]] == [("2026-09", 2), ("2026-10", 2)]
    assert body["chart"]["type"] == "line"


def test_inactive_users_report(reporting):
    inactive = result(report(reporting, {"source": "activity", "filters": [
        {"field": "last_active_at", "op": "lte", "value": "2026-10-07"}], "metrics": [{"fn": "count"}]}))
    never = result(report(reporting, {"source": "activity", "filters": [{"field": "last_active_at", "op": "is_null"}],
                                      "metrics": [{"fn": "count"}]}))
    assert inactive["data"]["totals"]["count"] == 2 and never["data"]["totals"]["count"] == 1
    assert inactive["data"]["mode"] == "summary"


@pytest.mark.parametrize("arguments,code", [
    ({"source": "projects", "group_by": ["budget"]}, "POLICY_LOCKED"),
    ({"source": "projects", "metrics": [{"fn": "max", "field": "budget"}]}, "POLICY_LOCKED"),
    ({"source": "projects", "filters": [{"field": "owner_email", "op": "is_null"}]}, "POLICY_LOCKED"),
    ({"source": "projects", "filters": [{"field": "status", "op": "in", "value": "active"}]}, "VALIDATION_FAILED"),
    ({"source": "projects", "limit": 500}, "VALIDATION_FAILED"),
    ({"source": "missing"}, "NOT_FOUND"),
    ({"source": "projects", "tenant_id": "tenant_b"}, "PRIVILEGE_ESCALATION"),
])
def test_report_misuse_is_rejected_with_a_clear_code(reporting, arguments, code):
    assert error_text(report(reporting, arguments)).startswith(code)


def test_report_requires_verified_user_context(reporting):
    assert "PERMISSION_DENIED" in error_text(report(reporting, {"source": "projects"}, user_delegation=None))


def test_report_masks_personal_data_instead_of_failing(reporting, monkeypatch):
    rows = [dict(row) for row in helpers.PROJECT_ROWS]
    rows[0]["name"] = f"Ask {CANARY}"
    monkeypatch.setattr(helpers, "PROJECT_ROWS", rows)
    response = report(reporting, {"source": "projects", "columns": ["ref", "name"]})
    body = result(response)
    assert CANARY not in response.text
    assert body["data"]["rows"][0]["name"] is None
    assert "hidden by the privacy filter" in body["summary"]


def test_report_stops_at_the_record_cap_and_says_so(reporting, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_records", 2)
    monkeypatch.setattr(get_settings(), "report_max_records", 2)
    body = result(report(reporting, {"source": "projects", "metrics": [{"fn": "count"}]}))
    assert body["meta"]["coverage"] == "partial" and body["meta"]["truncated"] is True
    assert "partial data" in body["summary"]


def test_saved_report_tool_lifecycle(reporting):
    admin = reporting["admin"]
    tool = create_tool(admin, reporting["app"]["connector_id"], template="report", tool_key="projects.by_status",
                       title="Projects by status", description="Count projects per status.", method=None, path_template="",
                       report={"group_by": ["status"], "metrics": [{"fn": "count"}], "allow_filters": True})
    assert set(tool["input_schema"]["properties"]) == {"filters", "limit"}
    tested = helpers.run_tool_test(admin, tool["id"])
    assert tested["passed"] and tested["preview"]["data"]["mode"] == "groups"
    assert {"pii_masked", "numeric_pii_masked"} <= set(tested["checks"])
    api(admin, "POST", f"/tools/{tool['id']}/publish", expect=200)
    body = result(call(reporting["client"], reporting["token"], "your_app__projects__by_status",
                       {"filters": [{"field": "created_at", "op": "gte", "value": "2026-10-01"}]}, delegation()))
    assert {row["status"]: row["count"] for row in body["data"]["rows"]} == {"active": 2}
    rejected = create_tool(admin, reporting["app"]["connector_id"], template="report", tool_key="projects.fixed",
                           method=None, path_template="", report={"metrics": [{"fn": "count"}], "allow_filters": False})
    assert "filters" not in rejected["input_schema"]["properties"]
    bad = api(admin, "POST", "/tools", {"connector_id": reporting["app"]["connector_id"], "module_key": "projects",
                                        "template": "report", "tool_key": "projects.bad",
                                        "report": {"group_by": ["budget"]}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "POLICY_LOCKED"


def test_report_playground_previews_with_sample_data(reporting):
    preview = api(reporting["admin"], "POST", "/tools/builtins/run_report/test", {
        "connector_id": reporting["app"]["connector_id"], "mode": "sample",
        "arguments": {"source": "projects", "group_by": ["status"], "metrics": [{"fn": "count"}]}}, expect=200).json()["data"]
    assert preview["passed"] and preview["preview"]["meta"]["scope"] == "sample_records"
    assert sum(row["count"] for row in preview["preview"]["data"]["rows"]) == 12
    sources = api(reporting["admin"], "POST", "/tools/builtins/list_data_sources/test",
                  {"connector_id": reporting["app"]["connector_id"]}, expect=200).json()["data"]
    assert {row["source"] for row in sources["preview"]["data"]} == {"projects", "activity"}
