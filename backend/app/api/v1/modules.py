"""Data sources published in each app's contract, with their access and field policy."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.api.v1.configuration import ModuleChanges, checked
from app.capabilities.policy_service import (
    enableable_operations,
    module_setting,
    update_module_policy,
)
from app.config import get_settings
from app.connectors.contracts import developer_baseline
from app.connectors.discovery import sync_admin_sources
from app.connectors.endpoint_policy import dataset_endpoint, is_dataset_candidate, module_endpoints
from app.errors import HubError
from app.ids import as_utc
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    FieldPolicy,
    ModuleDefinition,
    ModuleSetting,
    ToolDefinition,
)
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import (
    WRITE_ROLES,
    allowed_app_ids,
    require_app_access,
    require_role,
)

router = APIRouter(prefix="/modules", tags=["data sources"])


def _endpoint_view(route: dict) -> dict:
    output = route["output_schema"]
    return {
        "key": route["key"], "kind": route["kind"], "operation": route.get("operation", "read"),
        "method": route["method"], "path_template": route["path_template"],
        "requires_user_context": route["requires_user_context"], "public_aggregate": route["public_aggregate"],
        "safe_query": route["safe_query"], "tenant_field": route["tenant_field"],
        "input_schema": route["input_schema"], "output_schema": output, "max_items": output.get("maxItems"),
        "dataset": is_dataset_candidate(route),
    }


def module_view(db: Session, module: ModuleDefinition, setting: ModuleSetting, application: Application) -> dict:
    policies = list(db.scalars(select(FieldPolicy).where(FieldPolicy.module_id == module.id)))
    baseline = developer_baseline(module.manifest_json or {"readable_fields": module.readable_fields})
    endpoints = module_endpoints(module)
    types = {}
    for route in endpoints:
        for name, spec in route["output_schema"]["items"]["properties"].items():
            kind = spec.get("type")
            types.setdefault(name, next((item for item in (kind if isinstance(kind, list) else [kind]) if item != "null"), "string"))
    auto = dataset_endpoint(module)
    chosen = dataset_endpoint(module, setting.report_endpoint) if setting.report_endpoint else auto
    connector = db.scalar(select(Connector).where(Connector.app_id == application.id))
    connector_id = connector.id if connector else None
    source_managed = connector and connector.connector_type == "source_managed"
    if source_managed:
        policies = [policy for policy in policies if policy.field_path in baseline]
    tools = db.scalar(select(func.count()).select_from(ToolDefinition).where(
        ToolDefinition.connector_id == connector_id, ToolDefinition.module_key == module.module_key,
        ToolDefinition.status == "published" if source_managed else ToolDefinition.status != "archived")) if connector_id else 0
    return {
        "id": module.id, "app_id": application.id, "app_key": application.key, "app_name": application.name,
        "environment": application.environment, "connector_id": connector_id,
        "module_key": module.module_key, "name": module.name, "description": module.description,
        "schema_version": module.schema_version, "supported_operations": module.supported_operations,
        "enableable_operations": enableable_operations(module), "readable_fields": module.readable_fields,
        "read_endpoints": (module.manifest_json or {}).get("read_endpoints", []),
        "endpoints": [_endpoint_view(route) for route in endpoints],
        "enabled": setting.enabled, "operations_enabled": setting.operations_enabled,
        "policy_version": setting.policy_version,
        "report_endpoint": setting.report_endpoint, "report_endpoint_effective": chosen["key"] if chosen else None,
        "report_endpoint_auto": auto["key"] if auto else None,
        "last_synced_at": as_utc(module.last_synced_at).isoformat(),
        "tools": tools or 0,
        "fields": [{"field_path": policy.field_path, "classification": policy.classification,
                    "baseline": baseline.get(policy.field_path, {}).get("classification", "blocked"),
                    "source": policy.source,
                    "locked": policy.locked or baseline.get(policy.field_path, {}).get("locked", True),
                    "type": types.get(policy.field_path)} for policy in policies],
    }


@router.get("")
async def index(app_key: str | None = None, environment: str | None = None, connector_id: str | None = None,
          db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    await sync_admin_sources(db, user, get_settings(), connector_id=connector_id,
                             environment=environment, app_key=app_key)
    allowed = allowed_app_ids(db, user)
    query = (select(ModuleDefinition, ModuleSetting, Application)
             .join(ModuleSetting, ModuleSetting.module_id == ModuleDefinition.id)
             .join(Application, Application.id == ModuleDefinition.app_id)
             .join(Connector, Connector.app_id == Application.id)
             .where(or_(Connector.connector_type != "source_managed", ModuleSetting.enabled.is_(True)))
             .order_by(Application.name, ModuleDefinition.name))
    if app_key:
        query = query.where(Application.key == app_key)
    if environment:
        query = query.where(Application.environment == environment)
    if connector_id:
        query = query.where(Application.id == select(Connector.app_id).where(Connector.id == connector_id).scalar_subquery())
    if allowed is not None:
        query = query.where(Application.id.in_(allowed))
    return ok([module_view(db, module, setting, application) for module, setting, application in db.execute(query)])


@router.patch("/{module_id}/settings")
def update_settings(module_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    module = db.get(ModuleDefinition, module_id)
    if module is None:
        raise HubError("NOT_FOUND", "Data source was not found", 404)
    require_app_access(db, user, module.app_id)
    application = db.get(Application, module.app_id)
    setting = module_setting(db, module)
    changes = checked(ModuleChanges, payload, partial=True)
    enabled = changes.get("enabled", setting.enabled)
    operations = changes.get("operations")
    if operations is None:
        operations = (setting.operations_enabled or ["read"]) if enabled else []
    update_module_policy(
        db, module, setting, enabled=enabled, operations=operations,
        field_updates=changes.get("fields", []),
        report_endpoint=changes["report_endpoint"] if "report_endpoint" in changes else ...,
    )
    record_audit(db, action="module.update", actor_ref=f"admin:{user.id}", result="success", app_key=application.key,
                 module_key=module.module_key, environment=application.environment)
    db.commit()
    return ok(module_view(db, module, setting, application))
