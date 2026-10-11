"""Tool templates and the fingerprint that binds a tested configuration to its source contract."""

import hashlib
import json

TEMPLATES = {
    "read": {
        "label": "Read records",
        "operation": "read",
        "summary": "Expose one reviewed read route: list, look up or count records.",
    },
    "report": {
        "label": "Report",
        "operation": "read",
        "summary": "A saved summary of a data source: filters, groups, totals and a short text summary.",
    },
    "create": {
        "label": "Create record",
        "operation": "create",
        "summary": "Send a create request to the application. Needs write permission on the client key.",
    },
    "update": {
        "label": "Update record",
        "operation": "update",
        "summary": "Send an update request to the application. Needs write permission on the client key.",
    },
    "delete": {
        "label": "Delete record",
        "operation": "delete",
        "summary": "Send a delete request to the application. Needs write permission on the client key.",
    },
}
WRITE_TEMPLATES = {"create", "update", "delete"}
MAPPING_KEYS = ("method", "path_template", "timeout_ms", "max_payload_bytes", "safe_query",
                "requires_user_context", "tenant_field", "pagination", "audit_level", "error_mapping")


def operation_for(template: str) -> str:
    return TEMPLATES[template]["operation"]


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def content_fingerprint(tool, mapping, module, *, module_hash: str | None = None) -> str:
    """Changes to the tool, its route or the source contract require a new passing test.

    The read-tool formula is unchanged from earlier releases so tested tools stay current
    across upgrades; newer fields only join the digest when they are set.
    """

    payload = {
        "key": tool.tool_key, "version": tool.version,
        "source": module_hash if module_hash is not None else module.manifest_hash,
        "description": tool.description, "input": tool.input_schema, "output": tool.output_schema,
        "policy": tool.output_policy, "risk": tool.risk,
        "mapping": {key: getattr(mapping, key) for key in MAPPING_KEYS},
    }
    if tool.template and tool.template != "read":
        payload["template"] = tool.template
    if tool.report_spec:
        payload["report"] = tool.report_spec
    if tool.title:
        payload["title"] = tool.title
    return _digest(payload)
