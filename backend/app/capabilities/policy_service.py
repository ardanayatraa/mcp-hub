"""Data source access: enabled operations and field policy.

The developer manifest is the upper bound. An admin can enable operations the manifest
offers and tighten (or relax back to the developer default) each field's visibility.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.contracts import developer_baseline
from app.connectors.endpoint_policy import dataset_endpoint
from app.errors import HubError
from app.persistence.models import Connector, FieldPolicy, ModuleDefinition, ModuleSetting
from app.security.authorization import RANK, is_sensitive_path

ADMIN_CLASSIFICATIONS = {"allowed_for_ai", "allowed", "aggregate_only", "blocked", "secure_form_only"}


def policy_map(db: Session, module_id: str) -> dict[str, str]:
    rows = db.scalars(select(FieldPolicy).where(FieldPolicy.module_id == module_id))
    return {row.field_path: row.classification for row in rows}


def module_setting(db: Session, module: ModuleDefinition) -> ModuleSetting:
    setting = db.scalar(select(ModuleSetting).where(ModuleSetting.module_id == module.id))
    if setting is None:
        raise HubError("NOT_FOUND", "Data source policy was not found", 404)
    return setting


def enableable_operations(module: ModuleDefinition) -> list[str]:
    manifest = module.manifest_json or {}
    supported = set(module.supported_operations or [])
    return [op for op in manifest.get("enableable_operations", ["read"]) if op in supported]


def update_module_policy(db: Session, module: ModuleDefinition, setting: ModuleSetting, *, enabled: bool,
                         operations: list[str], field_updates: list[dict], report_endpoint=...) -> None:
    connector = db.scalar(select(Connector).where(Connector.app_id == module.app_id))
    if connector and connector.connector_type == "source_managed":
        raise HubError("POLICY_LOCKED", "Manage models, fields and operations in the connected application", 409)
    if not isinstance(operations, list) or not all(isinstance(op, str) for op in operations):
        raise HubError("VALIDATION_FAILED", "Operations must be a list of names", 422)
    operations = list(dict.fromkeys(operations))
    if not set(operations) <= set(module.supported_operations):
        raise HubError("VALIDATION_FAILED", "Operation is not in the developer manifest", 422)
    offered = enableable_operations(module)
    if not set(operations) <= set(offered):
        raise HubError("NOT_SUPPORTED", "The application does not publish a reviewed route for that operation", 422)
    if enabled and not operations:
        raise HubError("VALIDATION_FAILED", "Choose at least one operation to enable this data source", 422)
    setting.enabled = bool(enabled)
    setting.operations_enabled = operations if enabled else []
    setting.policy_version += 1
    existing = {row.field_path: row for row in db.scalars(select(FieldPolicy).where(FieldPolicy.module_id == module.id))}
    baseline = developer_baseline(module.manifest_json or {"readable_fields": module.readable_fields})
    for update in field_updates:
        if not isinstance(update, dict):
            raise HubError("VALIDATION_FAILED", "Field policy update is invalid", 422)
        path = update.get("field_path")
        proposed = update.get("classification")
        current = existing.get(path)
        if current is None or path not in module.readable_fields:
            raise HubError("VALIDATION_FAILED", "Field is not in the developer allowlist", 422)
        if proposed not in ADMIN_CLASSIFICATIONS:
            raise HubError("VALIDATION_FAILED", "Unknown field classification", 422)
        if proposed == current.classification:
            continue
        floor = baseline.get(path, {"classification": "blocked", "locked": True})
        if current.locked or floor["locked"] or is_sensitive_path(path):
            raise HubError("POLICY_LOCKED", "This field policy is locked by the developer or hub", 422)
        if RANK[proposed] > RANK[floor["classification"]]:
            raise HubError("POLICY_LOCKED", "Field policy cannot be weaker than the developer limit", 422)
        current.classification = proposed
        current.source = "developer" if proposed == floor["classification"] else "admin"
    if report_endpoint is not ...:
        if report_endpoint in (None, ""):
            setting.report_endpoint = None
        elif not isinstance(report_endpoint, str) or dataset_endpoint(module, report_endpoint) is None:
            raise HubError("VALIDATION_FAILED", "Report endpoint must be a reviewed list route of this data source", 422)
        else:
            setting.report_endpoint = report_endpoint


def module_for_operation(db: Session, app_id: str, module_key: str, operation: str = "read") -> ModuleDefinition:
    """Every call re-reads this, so disabling a data source takes effect immediately."""

    module = db.scalar(select(ModuleDefinition).where(ModuleDefinition.app_id == app_id,
                                                      ModuleDefinition.module_key == module_key))
    if module is None:
        raise HubError("NOT_FOUND", "Data source is not in the developer manifest", 404)
    setting = db.scalar(select(ModuleSetting).where(ModuleSetting.module_id == module.id))
    if setting is None or not setting.enabled or operation not in (setting.operations_enabled or []):
        if operation == "read":
            raise HubError("MODULE_DISABLED", "Data source is disabled or read access is not enabled", 403)
        raise HubError("MODULE_DISABLED", f"The {operation} operation is not enabled for this data source", 403)
    return module


def module_is_readable(db: Session, app_id: str, module_key: str) -> ModuleDefinition:
    return module_for_operation(db, app_id, module_key, "read")
