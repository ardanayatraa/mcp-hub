import pytest
from app.chat.exports import export_receipts


def test_export_event_contains_only_a_source_reference_and_never_a_supplied_link():
    row = {"export_ref": "exp_" + "a" * 48, "status": "ready", "format": "xlsx",
           "download_url": "javascript:alert(1)", "arbitrary": "private-canary"}
    assert export_receipts({"data": [row]}) == [{key: row[key] for key in ("export_ref", "status", "format")}]


@pytest.mark.parametrize("payload", [None, [], {"data": "bad"}, {"data": [None]},
                                     {"data": [{"export_ref": "../../secret", "status": "ready", "format": "pdf"}]},
                                     {"data": [{"export_ref": "exp_" + "a" * 48, "status": [], "format": "pdf"}]},
                                     {"data": [{"export_ref": "exp_" + "a" * 48, "status": "ready", "format": {}}]},
                                     {"data": [{"export_ref": "exp_" + "a" * 48, "status": "ready", "format": "html"}]}])
def test_invalid_export_receipts_are_not_rendered(payload):
    assert export_receipts(payload) == []
