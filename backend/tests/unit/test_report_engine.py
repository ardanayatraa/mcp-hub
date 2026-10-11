from zoneinfo import ZoneInfo

import pytest
from app.errors import HubError
from app.tools.report_engine import (
    ReportSpec,
    SavedReport,
    chart_hint,
    parse_spec,
    prepare_rows,
    run_report,
    source_fields,
    summarize,
)

ZONE = ZoneInfo("Asia/Singapore")
SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "ref": {"type": "string"}, "status": {"type": "string", "enum": ["open", "closed"]},
    "created_at": {"type": "string"}, "amount": {"type": "number"}, "salary": {"type": "number"},
    "owner_email": {"type": "string"}, "secret_note": {"type": "string"}}}}
POLICIES = {"ref": "allowed_for_ai", "status": "allowed_for_ai", "created_at": "allowed", "amount": "allowed_for_ai",
            "salary": "aggregate_only", "owner_email": "allowed_for_ai", "secret_note": "blocked"}
FIELDS = source_fields(SCHEMA, POLICIES)
ROWS = [
    {"ref": "a", "status": "open", "created_at": "2026-10-01T20:00:00+00:00", "amount": 10, "salary": 100},
    {"ref": "b", "status": "Open", "created_at": "2026-10-02T08:00:00+08:00", "amount": "2.50", "salary": 300},
    {"ref": "c", "status": "closed", "created_at": "2026-09-30", "amount": None, "salary": 200},
    {"ref": "d", "status": None, "created_at": None, "amount": 7, "salary": 400},
]


def run(**spec):
    return run_report(ROWS, parse_spec(spec), FIELDS, zone=ZONE)


def test_field_catalog_follows_policy_and_hides_sensitive_names():
    assert set(FIELDS) == {"ref", "status", "created_at", "amount", "salary"}
    assert FIELDS["salary"].usage == "aggregate" and FIELDS["status"].values == ("open", "closed")


def test_filters_are_typed_case_insensitive_and_date_aware():
    assert [row["ref"] for row in run(filters=[{"field": "status", "op": "eq", "value": "OPEN"}])["rows"]] == ["a", "b"]
    assert [row["ref"] for row in run(filters=[{"field": "amount", "op": "gte", "value": 2.5}])["rows"]] == ["a", "b", "d"]
    between = run(filters=[{"field": "created_at", "op": "between", "value": ["2026-09-30", "2026-10-02"]}])
    assert [row["ref"] for row in between["rows"]] == ["a", "b", "c"]  # the end date includes the whole day
    assert [row["ref"] for row in run(filters=[{"field": "status", "op": "is_null"}])["rows"]] == ["d"]
    assert [row["ref"] for row in run(filters=[{"field": "ref", "op": "in", "value": ["c", "d"]}])["rows"]] == ["c", "d"]
    assert run(filters=[{"field": "ref", "op": "contains", "value": "A"}])["matched"] == 1


def test_time_buckets_use_the_dataset_timezone():
    rows = run(time_bucket={"field": "created_at", "interval": "day"})["rows"]
    assert [(row["period"], row["count"]) for row in rows] == [("2026-09-30", 1), ("2026-10-02", 2), (None, 1)]
    weeks = run(time_bucket={"field": "created_at", "interval": "week"})["rows"]
    assert weeks[0]["period"] == "2026-W40"


def test_metrics_handle_numeric_text_nulls_and_small_group_privacy():
    result = run(group_by=["status"], metrics=[{"fn": "count"}, {"fn": "sum", "field": "amount"}, {"fn": "avg", "field": "salary"}])
    totals = result["totals"]
    assert totals["count"] == 4 and totals["sum_amount"] == 19.5 and totals["avg_salary"] == 250
    assert all(row["avg_salary"] is None for row in result["rows"])  # every group has fewer than 3 records
    assert any("fewer than 3" in note for note in result["notes"])
    assert run(metrics=[{"fn": "max", "field": "created_at"}])["totals"]["max_created_at"] == "2026-10-02T08:00:00+08:00"


def test_sorting_keeps_nulls_last_and_respects_limit():
    rows = run(sort={"by": "amount", "direction": "desc"}, columns=["ref", "amount"], limit=3)["rows"]
    assert rows == [{"ref": "a", "amount": 10}, {"ref": "d", "amount": 7}, {"ref": "b", "amount": "2.50"}]


@pytest.mark.parametrize("spec,code", [
    ({"group_by": ["salary"]}, "POLICY_LOCKED"),
    ({"metrics": [{"fn": "min", "field": "salary"}]}, "POLICY_LOCKED"),
    ({"filters": [{"field": "salary", "op": "gt", "value": 1}]}, "POLICY_LOCKED"),
    ({"filters": [{"field": "secret_note", "op": "is_null"}]}, "POLICY_LOCKED"),
    ({"metrics": [{"fn": "sum", "field": "status"}]}, "VALIDATION_FAILED"),
    ({"filters": [{"field": "amount", "op": "between", "value": [1]}]}, "VALIDATION_FAILED"),
    ({"group_by": ["status"], "sort": {"by": "ref"}}, "VALIDATION_FAILED"),
    ({"group_by": ["status", "status"]}, "VALIDATION_FAILED"),
])
def test_invalid_reports_fail_with_specific_codes(spec, code):
    with pytest.raises(HubError) as error:
        run(**spec)
    assert error.value.code == code


def test_spec_parsing_reports_locations_without_values():
    with pytest.raises(HubError) as error:
        parse_spec({"filters": [{"field": "status", "op": "like", "value": "secret-value"}], "evil@example.com": 1})
    assert "secret-value" not in error.value.message and "evil@example.com" not in error.value.message
    assert "filters.0.op" in error.value.message
    assert parse_spec({"metrics": [{"fn": "count"}], "allow_filters": False}, SavedReport).allow_filters is False
    with pytest.raises(HubError):
        parse_spec({"allow_filters": False}, ReportSpec)


def test_unsafe_values_are_masked_and_counted():
    rows, hidden = prepare_rows([{"ref": "x", "status": "mail canary@example.com", "salary": 5, "amount": {"nested": 1}}], FIELDS)
    assert hidden == 2 and rows[0]["status"] is None and rows[0]["amount"] is None and rows[0]["salary"] == 5


def test_summary_and_chart_are_derived_from_results():
    result = run(group_by=["status"])
    text = summarize(result, label="Demo · Orders", scanned=4, coverage="partial", truncated=True, filtered=False)
    assert text.startswith("Demo · Orders: 4 record(s) (partial data: the scan stopped early).")
    assert "open: 1 (25%)" in text
    assert chart_hint(result) == {"type": "bar", "x": "status", "y": ["count"]}
    assert chart_hint(run()) is None
