import copy
import json

import pytest
from app.connectors.contracts import validate_manifest
from app.errors import HubError
from app.tools.runtime import Route, write_pipeline

PROPERTIES = {
    "proposal_ref": {"type": "string", "maxLength": 80},
    "status": {"type": "string"},
    "operation": {"type": "string"},
    "requires_confirmation": {"type": "boolean"},
    "expires_at": {"type": "string", "maxLength": 32},
}
OUTPUT = {"type": "array", "maxItems": 1, "items": {
    "type": "object", "additionalProperties": False, "properties": PROPERTIES, "required": list(PROPERTIES),
}}
ENDPOINT = {
    "tool_key": "your_app.orders.create", "workflow": "proposal", "operation": "create", "method": "POST",
    "path_template": "/api/ai/v1/orders/commands/create", "requires_user_context": True, "tenant_field": "tenant_id",
    "input_schema": {"type": "object", "additionalProperties": False,
                     "properties": {"title": {"type": "string", "maxLength": 100}}, "required": ["title"]},
    "output_schema": OUTPUT,
}
MANIFEST = {"contract_version": "1.0", "application": "your_app", "managed_by": "application", "modules": [{
    "key": "orders", "supported_operations": ["read", "create"], "readable_fields": ["title"],
    "writable_fields": ["title"], "read_endpoints": [], "write_endpoints": [ENDPOINT],
}]}


def test_proposal_workflow_survives_contract_normalization():
    manifest = validate_manifest(copy.deepcopy(MANIFEST), expected_app_key="your_app", source_managed=True)
    endpoint = manifest["modules"][0]["write_endpoints"][0]
    assert endpoint["workflow"] == "proposal"
    assert Route.of(endpoint).workflow == "proposal"


@pytest.mark.parametrize("change", [
    {"workflow": "unknown"}, {"method": "DELETE"}, {"output_schema": {
        "type": "array", "maxItems": 1, "items": {"type": "object", "additionalProperties": False,
                                               "properties": {"status": {"type": "string"}}, "required": ["status"]},
    }},
])
def test_incomplete_or_unknown_proposal_contract_fails_closed(change):
    document = copy.deepcopy(MANIFEST)
    document["modules"][0]["write_endpoints"][0].update(change)
    with pytest.raises(HubError):
        validate_manifest(document, expected_app_key="your_app", source_managed=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "committed", "cancelled", "expired"])
async def test_proposal_result_has_explicit_state_and_confirmation_requirement(state):
    receipt = {"proposal_ref": "prop_" + "a" * 48, "status": state, "operation": "create",
               "requires_confirmation": state == "pending", "expires_at": "2026-10-29T09:00:00Z", "tenant_id": "tenant_a"}

    async def fetch(_arguments):
        return 200, json.dumps({"success": True, "data": [receipt], "meta": {
            "requires_confirmation": not (state == "pending"),  # untrusted metadata cannot override the receipt
        }}).encode()

    route = Route.of({**ENDPOINT, "safe_query": False})
    result = await write_pipeline(route=route, operation="create", allow_fields=list(PROPERTIES),
                                  output_schema=OUTPUT, arguments={"title": "New order"}, fetch=fetch,
                                  tenant_id="tenant_a", trace_id="tr_test")
    assert result["meta"]["workflow"] == "proposal"
    assert result["meta"]["status"] == state
    assert result["meta"]["requires_confirmation"] is (state == "pending")
    assert result["data"][0]["status"] == state
    # MCP clients validate structuredContent against the advertised outputSchema.
    from app.tools.catalog import records_output
    from jsonschema import validate
    validate(result, records_output(OUTPUT, write=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"requires_confirmation": False}, {"operation": "delete"}, {"proposal_ref": "bad"},
    {"status": "done"}, {"tenant_id": "tenant_b"},
])
async def test_inconsistent_or_cross_tenant_proposal_receipt_is_rejected(change):
    receipt = {"proposal_ref": "prop_" + "a" * 48, "status": "pending", "operation": "create",
               "requires_confirmation": True, "expires_at": "2026-10-29T09:00:00Z", "tenant_id": "tenant_a", **change}

    async def fetch(_arguments):
        return 200, json.dumps({"success": True, "data": [receipt]}).encode()

    route = Route.of({**ENDPOINT, "safe_query": False})
    with pytest.raises(HubError):
        await write_pipeline(route=route, operation="create", allow_fields=list(PROPERTIES),
                             output_schema=OUTPUT, arguments={"title": "New order"}, fetch=fetch,
                             tenant_id="tenant_a", trace_id="tr_test")
