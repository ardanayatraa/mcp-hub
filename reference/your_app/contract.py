"""Developer-reviewed capabilities; the Hub discovers these as metadata.

Two data sources: ``projects`` (list, plus an optional create request that the app
turns into a proposal for the user to confirm) and ``activity`` (last-active timestamps
for the "inactive users" report). ``budget`` is aggregate-only: reports may total or
average it, but never show an individual value.
"""

PROJECT_FIELDS = {
    "ref": {"type": "string", "maxLength": 64},
    "name": {"type": "string", "maxLength": 120},
    "status": {"type": "string", "enum": ["active", "pending", "completed"]},
    "created_at": {"type": "string", "maxLength": 64},
    "budget": {"type": "number"},
}
PROJECT_INPUT = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["active", "pending", "completed"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "cursor": {"type": "string", "maxLength": 64},
    },
}
PROJECT_OUTPUT = {
    "type": "array", "maxItems": 50,
    "items": {"type": "object", "additionalProperties": False,
              "properties": PROJECT_FIELDS, "required": list(PROJECT_FIELDS)},
}
PROJECT_CREATE_INPUT = {
    "type": "object", "additionalProperties": False, "required": ["name"],
    "properties": {
        "name": {"type": "string", "minLength": 3, "maxLength": 120},
        "status": {"type": "string", "enum": ["active", "pending"]},
    },
}
PROPOSAL_OUTPUT = {
    "type": "array", "maxItems": 1,
    "items": {"type": "object", "additionalProperties": False, "required": ["proposal_ref", "summary", "status"],
              "properties": {"proposal_ref": {"type": "string", "maxLength": 64},
                             "summary": {"type": "string", "maxLength": 300},
                             "status": {"type": "string", "maxLength": 40}}},
}
ACTIVITY_OUTPUT = {
    "type": "array", "maxItems": 50,
    "items": {"type": "object", "additionalProperties": False, "required": ["last_active_at", "status"],
              "properties": {"last_active_at": {"type": ["string", "null"], "maxLength": 64},
                             "status": {"type": "string", "enum": ["active", "suspended"]}}},
}
MANIFEST = {
    "contract_version": "1.0", "application": "your_app", "manifest_version": "2026-10-10.3",
    "modules": [
        {
            "key": "projects", "name": "Projects", "description": "Projects the signed-in user may see",
            "schema_version": "1.0", "supported_operations": ["read", "create", "update"],
            "readable_fields": list(PROJECT_FIELDS), "writable_fields": ["name", "status"],
            "filters": {"status": {"type": "string", "enum": ["active", "pending", "completed"]}},
            "max_page_size": 50, "risk": {"read": "low", "create": "medium"},
            "field_policies": {"owner_email": "blocked", "owner_phone": "blocked", "budget": "aggregate_only"},
            "read_endpoints": [{"method": "GET", "path_template": "/api/v1/projects",
                                "requires_user_context": True, "tenant_field": "tenant_id",
                                "input_schema": PROJECT_INPUT, "output_schema": PROJECT_OUTPUT}],
            "write_endpoints": [{"operation": "create", "method": "POST", "path_template": "/api/v1/projects",
                                 "requires_user_context": True, "tenant_field": "tenant_id",
                                 "input_schema": PROJECT_CREATE_INPUT, "output_schema": PROPOSAL_OUTPUT}],
        },
        {
            "key": "activity", "name": "User activity", "description": "Last activity time of users in the tenant",
            "schema_version": "1.0", "supported_operations": ["read"],
            "readable_fields": ["last_active_at", "status"], "max_page_size": 50,
            "read_endpoints": [{"method": "GET", "path_template": "/api/v1/activity",
                                "requires_user_context": True, "tenant_field": "tenant_id",
                                "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
                                "output_schema": ACTIVITY_OUTPUT}],
        },
    ],
}
