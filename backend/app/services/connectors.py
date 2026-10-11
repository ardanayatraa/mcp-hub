"""Connected applications. Secrets are encrypted before they touch the database.

Lifecycle: draft -> active <-> paused, archived is permanent. Activation needs a
passing health check and a discovered contract.
"""

import json
import secrets
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.configuration import ConnectorChanges, ConnectorConfiguration, checked
from app.config import Settings
from app.connectors.auth_profiles import auth_headers
from app.connectors.contracts import KEY_RE
from app.connectors.discovery import connector_secret, discover_capabilities
from app.connectors.http_adapter import execute_request, join_url
from app.connectors.registry import list_connectors
from app.connectors.ssrf_guard import validate_destination
from app.errors import HubError
from app.ids import as_utc, new_id, new_trace_id, utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    ConnectorHealthCheck,
    ConnectorSecret,
    ContractSnapshot,
    ModuleDefinition,
    ModuleSetting,
    ServiceIdentity,
    ToolDefinition,
)
from app.security.audit import record_audit
from app.security.authorization import (
    ADMIN_ROLES,
    allowed_app_ids,
    require_app_access,
    require_role,
)
from app.security.crypto import decrypt_secret, encrypt_secret

HINTS = {
    "authorization": "The application rejected the credential. Check the API key or bearer token.",
    "dns": "The host name could not be resolved. Check the base URL.",
    "timeout": "The application did not answer in time. Check that it is running or raise the timeout.",
    "network": "The application could not be reached or the address is blocked by the egress policy.",
    "schema": "The health endpoint answered, but not with {\"status\": \"ok\"}.",
}


def _active_secret_rotated_at(db: Session, connector: Connector):
    return db.scalar(select(ConnectorSecret.rotated_at).where(ConnectorSecret.connector_id == connector.id,
                                                              ConnectorSecret.revoked_at.is_(None))
                     .order_by(ConnectorSecret.rotated_at.desc()).limit(1))


def connector_view(db: Session, connector: Connector, application: Application) -> dict:
    latest = db.scalar(select(ConnectorHealthCheck).where(ConnectorHealthCheck.connector_id == connector.id)
                       .order_by(ConnectorHealthCheck.created_at.desc()).limit(1))
    secret_rotated_at = _active_secret_rotated_at(db, connector)
    modules = db.execute(select(ModuleSetting.enabled).join(ModuleDefinition, ModuleDefinition.id == ModuleSetting.module_id)
                         .where(ModuleDefinition.app_id == application.id)).scalars().all()
    tool_counts = dict(db.execute(select(ToolDefinition.status, func.count()).where(ToolDefinition.connector_id == connector.id)
                                  .group_by(ToolDefinition.status)).all())
    if connector.connector_type == "source_managed":
        modules = [enabled for enabled in modules if enabled]
        tool_counts = {"published": tool_counts.get("published", 0)}
    contract = db.scalar(select(ContractSnapshot).where(ContractSnapshot.connector_id == connector.id)
                         .order_by(ContractSnapshot.created_at.desc()).limit(1))
    return {
        "id": connector.id,
        "app_id": application.id,
        "app_key": application.key,
        "name": application.name,
        "environment": application.environment,
        "connector_type": connector.connector_type,
        "base_url": connector.base_url,
        "manifest_path": connector.manifest_path,
        "health_path": connector.health_path,
        "auth_type": connector.auth_type,
        "status": connector.status,
        "tls_verify": connector.tls_verify,
        "timeout_ms": connector.timeout_ms,
        "secret_configured": secret_rotated_at is not None,
        "secret_updated_at": as_utc(secret_rotated_at).isoformat() if secret_rotated_at else None,
        "failure_count": connector.failure_count,
        "circuit_open": bool(connector.circuit_open_until and as_utc(connector.circuit_open_until) > utcnow()),
        "health": {"status": latest.status, "latency_ms": latest.latency_ms, "error_category": latest.error_category,
                   "checked_at": as_utc(latest.created_at).isoformat()} if latest else None,
        "contract": {"version": contract.manifest_version, "synced_at": as_utc(contract.created_at).isoformat()} if contract else None,
        "sources_total": len(modules),
        "sources_enabled": sum(1 for enabled in modules if enabled),
        "tools_published": tool_counts.get("published", 0),
        "tools_total": sum(count for status, count in tool_counts.items() if status != "archived"),
        "created_at": as_utc(connector.created_at).isoformat(),
    }


def list_connector_views(db: Session, admin: AdminUser, environment: str | None = None) -> list[dict]:
    allowed = allowed_app_ids(db, admin)
    return [connector_view(db, connector, application) for connector, application in list_connectors(db, environment)
            if allowed is None or application.id in allowed]


def _audit(db: Session, admin: AdminUser, action: str, application: Application, **extra) -> None:
    record_audit(db, action=action, actor_ref=f"admin:{admin.id}", result=extra.pop("result", "success"),
                 app_key=application.key, environment=application.environment, **extra)


def create_connector(db: Session, admin: AdminUser, payload: dict, settings: Settings) -> dict:
    data = checked(ConnectorConfiguration, payload)
    app_key = data["app_key"]
    if not KEY_RE.match(app_key):
        raise HubError("VALIDATION_FAILED", "App key must be lowercase letters, digits and underscores", 422)
    base_url = data["base_url"].rstrip("/")
    validate_destination(base_url + "/", settings)
    join_url(base_url, data["manifest_path"])
    join_url(base_url, data["health_path"])
    if not data["tls_verify"] and not settings.allow_insecure_tls:
        raise HubError("UNSAFE_CONFIGURATION", "TLS verification cannot be disabled", 422)
    application = db.scalar(select(Application).where(Application.key == app_key, Application.environment == data["environment"]))
    if application is None:
        require_role(admin.role, ADMIN_ROLES)
        application = Application(id=new_id(), key=app_key, name=(data["name"] or app_key)[:200],
                                  environment=data["environment"], status="active")
        db.add(application)
        db.flush()
    require_app_access(db, admin, application.id)
    if db.scalar(select(Connector).where(Connector.app_id == application.id)):
        raise HubError("CONFLICT", "This app and environment is already connected", 409)
    connector = Connector(id=new_id(), app_id=application.id, connector_type=data["connector_type"], base_url=base_url,
                          manifest_path=data["manifest_path"], health_path=data["health_path"],
                          auth_type=data["auth_type"], status="draft", tls_verify=data["tls_verify"],
                          timeout_ms=data["timeout_ms"])
    db.add(connector)
    db.flush()
    generated = not data["delegation_secret"]
    delegation = data["delegation_secret"] or secrets.token_urlsafe(32)
    if len(delegation) < 8:
        raise HubError("VALIDATION_FAILED", "Delegation secret must be at least 8 characters", 422)
    db.add(ConnectorSecret(id=new_id(), connector_id=connector.id,
                           secret_ciphertext=encrypt_secret(settings.secret_encryption_key, data["secret"]),
                           delegation_ciphertext=encrypt_secret(settings.secret_encryption_key, delegation)))
    _audit(db, admin, "connector.create", application, trace_id=new_trace_id())
    body = connector_view(db, connector, application)
    if generated:
        # Shown once so it can be configured in the application; stored encrypted only.
        body["delegation_secret"] = delegation
    else:
        body["delegation_secret_set"] = True
    return body


async def test_connector(db: Session, admin: AdminUser, connector: Connector, application: Application, settings: Settings) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot be tested", 409)
    secret = decrypt_secret(settings.secret_encryption_key, connector_secret(db, connector.id).secret_ciphertext)
    started = time.perf_counter()
    category, status_label, latency = None, "ok", None
    try:
        status, body, latency = await execute_request(
            method="GET", url=join_url(connector.base_url, connector.health_path), settings=settings,
            headers={**auth_headers(connector.auth_type, secret), "Accept": "application/json"},
            timeout_ms=connector.timeout_ms, tls_verify=connector.tls_verify, retries=0)
        if status in {401, 403}:
            status_label, category = "fail", "authorization"
        elif status >= 400:
            status_label, category = "fail", "network"
        else:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            if not isinstance(parsed, dict) or (parsed.get("status") not in {"ok", "healthy"} and parsed.get("success") is not True):
                status_label, category = "fail", "schema"
    except HubError as exc:
        status_label = "fail"
        category = {"CONNECTOR_DNS": "dns", "UPSTREAM_TIMEOUT": "timeout", "UPSTREAM_UNAUTHORIZED": "authorization",
                    "SCHEMA_MISMATCH": "schema"}.get(exc.code, "network")
        latency = int((time.perf_counter() - started) * 1000)
    db.add(ConnectorHealthCheck(id=new_id(), connector_id=connector.id, status=status_label, latency_ms=latency,
                                error_category=category))
    _audit(db, admin, "connector.test", application, result="success" if status_label == "ok" else "error",
           error_code=category, duration_ms=latency)
    return {"status": status_label, "latency_ms": latency, "error_category": category, "hint": HINTS.get(category)}


async def discover(db: Session, admin: AdminUser, connector: Connector, application: Application, settings: Settings) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot be synchronized", 409)
    results = await discover_capabilities(db, connector, application, settings=settings,
                                          encryption_key=settings.secret_encryption_key)
    _audit(db, admin, "connector.discover", application)
    ids = [module.id for module, _change in results]
    enabled = {row.module_id: row.enabled for row in db.scalars(select(ModuleSetting).where(ModuleSetting.module_id.in_(ids)))}
    return {"modules": [{"id": module.id, "module_key": module.module_key, "name": module.name,
                         "description": module.description, "schema_version": module.schema_version,
                         "supported_operations": module.supported_operations,
                         "readable_fields": module.readable_fields, "change": change,
                         "enabled": bool(enabled.get(module.id))} for module, change in results]}


def activate(db: Session, admin: AdminUser, connector: Connector, application: Application) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot be activated", 409)
    connector_secret(db, connector.id)
    latest = db.scalar(select(ConnectorHealthCheck).where(ConnectorHealthCheck.connector_id == connector.id)
                       .order_by(ConnectorHealthCheck.created_at.desc()))
    discovered = db.scalar(select(ModuleDefinition.id).where(ModuleDefinition.app_id == application.id))
    if connector.connector_type == "source_managed":
        snapshot = db.scalar(select(ContractSnapshot).where(ContractSnapshot.connector_id == connector.id)
                             .order_by(ContractSnapshot.created_at.desc()).limit(1))
        discovered = snapshot.id if snapshot and snapshot.manifest_json.get("managed_by") == "application" else None
    if latest is None or latest.status != "ok" or discovered is None:
        raise HubError("VALIDATION_FAILED", "Activation needs a passing connection test and a synced contract", 422)
    connector.status = "active"
    connector.updated_at = utcnow()
    _audit(db, admin, "connector.activate", application)
    return connector_view(db, connector, application)


def pause(db: Session, admin: AdminUser, connector: Connector, application: Application) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot be paused", 409)
    connector.status = "paused"
    connector.updated_at = utcnow()
    _audit(db, admin, "connector.pause", application)
    return connector_view(db, connector, application)


def rotate_secret(db: Session, admin: AdminUser, connector: Connector, application: Application, payload: dict,
                  settings: Settings) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot rotate credentials", 409)
    new_secret = payload.get("secret") or None
    if new_secret is not None and (not isinstance(new_secret, str) or not 8 <= len(new_secret) <= 500):
        raise HubError("VALIDATION_FAILED", "The new secret must be 8 to 500 characters", 422)
    delegation = payload.get("delegation_secret")
    if delegation is not None and (not isinstance(delegation, str) or not 8 <= len(delegation) <= 500):
        raise HubError("VALIDATION_FAILED", "The new delegation secret must be 8 to 500 characters", 422)
    if new_secret is None and not delegation:
        raise HubError("VALIDATION_FAILED", "Provide a new secret, a new delegation secret, or both", 422)
    current = db.scalar(select(ConnectorSecret).where(ConnectorSecret.connector_id == connector.id)
                        .order_by(ConnectorSecret.rotated_at.desc()))
    if current is None:
        raise HubError("SECRET_UNAVAILABLE", "Credential history is unavailable", 409)
    for row in db.scalars(select(ConnectorSecret).where(ConnectorSecret.connector_id == connector.id,
                                                        ConnectorSecret.revoked_at.is_(None))):
        row.revoked_at = utcnow()
    # Either half may be replaced on its own; the other is carried over still encrypted.
    db.add(ConnectorSecret(id=new_id(), connector_id=connector.id,
                           secret_ciphertext=encrypt_secret(settings.secret_encryption_key, new_secret)
                           if new_secret else current.secret_ciphertext,
                           delegation_ciphertext=encrypt_secret(settings.secret_encryption_key, delegation)
                           if delegation else current.delegation_ciphertext))
    _audit(db, admin, "connector.rotate", application)
    return {"rotated": True}


def edit_connector(db: Session, admin: AdminUser, connector: Connector, application: Application, payload: dict,
                   settings: Settings) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot be changed", 409)
    changes = checked(ConnectorChanges, payload, partial=True)
    base = changes.get("base_url", connector.base_url).rstrip("/")
    validate_destination(base + "/", settings)
    for key in ("manifest_path", "health_path"):
        join_url(base, changes.get(key, getattr(connector, key)))
    if changes.get("tls_verify") is False and not settings.allow_insecure_tls:
        raise HubError("UNSAFE_CONFIGURATION", "TLS verification cannot be disabled", 422)
    if "base_url" in changes:
        changes["base_url"] = base
    source_changed = any(key in changes and changes[key] != getattr(connector, key)
                         for key in ("base_url", "manifest_path", "connector_type"))
    for key, value in changes.items():
        if key == "name":
            application.name = value
        else:
            setattr(connector, key, value)
    if source_changed:
        # A different source must be re-tested and its data sources reviewed again.
        connector.status = "draft"
        for setting in db.scalars(select(ModuleSetting).join(ModuleDefinition, ModuleDefinition.id == ModuleSetting.module_id)
                                  .where(ModuleDefinition.app_id == application.id)):
            setting.enabled = False
            setting.operations_enabled = []
            setting.policy_version += 1
    connector.updated_at = utcnow()
    _audit(db, admin, "connector.update", application)
    return connector_view(db, connector, application)


def archive_connector(db: Session, admin: AdminUser, connector: Connector, application: Application) -> dict:
    if connector.status == "archived":
        raise HubError("CONFLICT", "This app is already archived", 409)
    connector.status = "archived"
    connector.updated_at = utcnow()
    for row in db.scalars(select(ConnectorSecret).where(ConnectorSecret.connector_id == connector.id,
                                                        ConnectorSecret.revoked_at.is_(None))):
        row.revoked_at = utcnow()
    for tool in db.scalars(select(ToolDefinition).where(ToolDefinition.connector_id == connector.id)):
        tool.status = "archived"
    for identity in db.scalars(select(ServiceIdentity).where(ServiceIdentity.app_id == application.id,
                                                             ServiceIdentity.revoked_at.is_(None))):
        identity.revoked_at = utcnow()
    _audit(db, admin, "connector.archive", application)
    return connector_view(db, connector, application)


def delete_connector(db: Session, admin: AdminUser, connector: Connector, application: Application) -> None:
    """Remove a draft or archived app with its configuration. Audit history is kept."""

    if connector.status not in {"draft", "archived"}:
        raise HubError("CONFLICT", "Archive the app before deleting it", 409)
    _audit(db, admin, "connector.delete", application)
    db.delete(application)


def health_history(db: Session, connector_id: str) -> list[dict]:
    rows = db.scalars(select(ConnectorHealthCheck).where(ConnectorHealthCheck.connector_id == connector_id)
                      .order_by(ConnectorHealthCheck.created_at.desc()).limit(20))
    return [{"status": row.status, "latency_ms": row.latency_ms, "error_category": row.error_category,
             "hint": HINTS.get(row.error_category), "created_at": as_utc(row.created_at).isoformat()} for row in rows]


def contract_history(db: Session, connector_id: str) -> list[dict]:
    rows = db.scalars(select(ContractSnapshot).where(ContractSnapshot.connector_id == connector_id)
                      .order_by(ContractSnapshot.created_at.desc()).limit(20))
    return [{"version": row.manifest_version, "hash": row.manifest_hash, "created_at": as_utc(row.created_at).isoformat(),
             "modules": [module["key"] for module in row.manifest_json.get("modules", [])]} for row in rows]
