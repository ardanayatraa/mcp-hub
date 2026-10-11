import pytest
from app.errors import HubError
from app.privacy.envelope import safe_meta
from app.privacy.output_guard import guard_output, guard_receipt
from app.privacy.pii_inspector import contains_pii
from app.tools.schema_tools import validate_arguments, validate_input_schema

CANARY = "canary.a@example.com"
PHONE = "+6281234567890"
NID = "3201010101010001"
META = {"as_of": "2026-10-10T00:00:00+00:00", "timezone": "Asia/Singapore", "scope": "authorized_records", "coverage": "complete"}


def test_detectors_match_canaries():
    assert contains_pii(CANARY)
    assert contains_pii(PHONE)
    assert contains_pii(NID)
    assert contains_pii("123-45-6789")
    assert not contains_pii("prj_125")


def test_guard_drops_blocked_fields_and_rejects_embedded_pii():
    with pytest.raises(HubError) as raised:
        guard_output(
            [{"ref": "prj_125", "notes": "mail me at canary.a@example.com", "owner_email": CANARY}],
            ["ref", "notes"],
            {"ref": "allowed_for_ai", "notes": "allowed_for_ai", "owner_email": "blocked"},
        )
    assert raised.value.code == "PII_DETECTED"
    clean = guard_output(
        [{"ref": "prj_125", "status": "active", "owner_email": CANARY, "notes": "hello canary.a@example.com"}],
        ["ref", "status"],
        {"ref": "allowed_for_ai", "status": "allowed_for_ai", "owner_email": "blocked"},
    )
    assert clean == [{"ref": "prj_125", "status": "active"}]
    assert CANARY not in str(clean)


def test_unlisted_and_sensitive_fields_are_default_deny():
    rows = [{"ref": "a", "email": CANARY, "budget": 10}]
    assert guard_output(rows, ["ref", "email", "budget"], {"ref": "allowed", "email": "allowed", "budget": "aggregate_only"}) == [{"ref": "a"}]


def test_receipts_keep_declared_fields_and_reject_pii():
    assert guard_receipt([{"proposal_ref": "p1", "summary": "ok", "user_id": "7"}], ["proposal_ref", "summary", "user_id"]) == [
        {"proposal_ref": "p1", "summary": "ok"}]
    with pytest.raises(HubError):
        guard_receipt([{"summary": f"Mail {CANARY}"}], ["summary"])


@pytest.mark.parametrize("count", [3201010101010001, True, -1, 1.2])
def test_metadata_count_cannot_carry_numeric_pii_or_invalid_types(count):
    with pytest.raises(HubError) as error:
        safe_meta({**META, "total_count": count})
    assert error.value.code == "SCHEMA_MISMATCH"


def test_metadata_requires_aware_time_and_honest_coverage():
    with pytest.raises(HubError):
        safe_meta({**META, "as_of": "2026-10-10T00:00:00"})
    with pytest.raises(HubError):
        safe_meta({**META, "has_more": True})
    assert safe_meta({**META, "coverage": "partial", "has_more": True})["has_more"] is True


def test_nullable_model_attributes_keep_closed_scalar_schema_and_bounds():
    schema = validate_input_schema({"type": "object", "additionalProperties": False, "properties": {
        "note": {"type": ["string", "null"], "maxLength": 40},
        "rating": {"type": ["number", "null"]}}})
    assert schema["properties"]["rating"]["maximum"] == 1_000_000_000
    assert validate_arguments(schema, {"note": None, "rating": None}) == {"note": None, "rating": None}
    for arguments in [{"note": {}}, {"rating": True}, {"note": "x" * 41}, {"user_id": "other"}]:
        with pytest.raises(HubError):
            validate_arguments(schema, arguments)
    for types in [["string", "object", "null"], ["string", "integer"], ["null"], ["string", "string"]]:
        with pytest.raises(HubError):
            validate_input_schema({"type": "object", "additionalProperties": False,
                                   "properties": {"value": {"type": types}}})
