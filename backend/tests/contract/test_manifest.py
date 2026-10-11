import copy

import pytest
from app.connectors.contracts import validate_manifest
from app.errors import HubError
from reference.your_app.contract import MANIFEST

BASE = {
    "contract_version": "1.0",
    "application": "your_app",
    "manifest_version": "2026-10-10.1",
    "modules": [
        {
            "key": "projects",
            "name": "Projects",
            "schema_version": "1.0",
            "supported_operations": ["read", "create"],
            "readable_fields": ["ref", "name", "status"],
            "writable_fields": ["name"],
            "max_page_size": 50,
        }
    ],
}


def test_manifest_accepts_the_reference_shape():
    document = validate_manifest(BASE, expected_app_key="your_app")
    module = document["modules"][0]
    assert module["enableable_operations"] == ["read"]  # create has no reviewed route
    assert "write_endpoints" not in module  # older manifests keep their exact hash


def test_reference_manifest_offers_reviewed_create():
    document = validate_manifest(MANIFEST, expected_app_key="your_app")
    projects = document["modules"][0]
    assert projects["enableable_operations"] == ["read", "create"]
    assert projects["write_endpoints"][0]["requires_user_context"] is True
    assert document["modules"][1]["read_endpoints"][0]["path_template"] == "/api/v1/activity"


def test_manifest_hash_is_stable_and_changes_with_the_contract():
    first = validate_manifest(MANIFEST, expected_app_key="your_app")["manifest_hash"]
    assert validate_manifest(copy.deepcopy(MANIFEST), expected_app_key="your_app")["manifest_hash"] == first
    changed = copy.deepcopy(MANIFEST)
    changed["modules"][1]["description"] = "Changed"
    assert validate_manifest(changed, expected_app_key="your_app")["manifest_hash"] != first


def write_manifest(**route_changes):
    document = copy.deepcopy(MANIFEST)
    document["modules"][0]["write_endpoints"][0].update(route_changes)
    return document


@pytest.mark.parametrize("changes", [
    {"operation": "delete"},  # not in supported_operations
    {"method": "GET"},
    {"requires_user_context": False},
    {"tenant_field": None},
    {"input_schema": {"type": "object", "additionalProperties": False, "properties": {"owner_email": {"type": "string"}}}},
    {"input_schema": {"type": "object", "additionalProperties": False, "properties": {"unknown_field": {"type": "string"}}}},
    {"method": "GET", "path_template": "/api/v1/projects"},
])
def test_unsafe_write_routes_are_rejected(changes):
    with pytest.raises(HubError):
        validate_manifest(write_manifest(**changes), expected_app_key="your_app")


def test_manifest_rejects_unknown_operations_and_app_mismatch():
    with pytest.raises(HubError):
        validate_manifest({**BASE, "application": "other"}, expected_app_key="your_app")
    bad = copy.deepcopy(BASE)
    bad["modules"][0]["supported_operations"] = ["drop_database"]
    with pytest.raises(HubError):
        validate_manifest(bad, expected_app_key="your_app")
