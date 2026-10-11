"""Reconcile capability manifests. Manual sources stay off until reviewed; trusted sources own grants."""

import asyncio
import hashlib
import json
from weakref import WeakValueDictionary

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.auth_profiles import auth_headers
from app.connectors.contracts import initial_field_policies, validate_manifest
from app.connectors.http_adapter import execute_request, join_url
from app.errors import HubError
from app.ids import new_id, utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    ConnectorSecret,
    ContractSnapshot,
    FieldPolicy,
    ModuleDefinition,
    ModuleSetting,
)
from app.security.authorization import RANK, allowed_app_ids
from app.security.crypto import decrypt_secret

_sync_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def module_fingerprint(module: dict) -> str:
    return hashlib.sha256(json.dumps(module, sort_keys=True).encode("utf-8")).hexdigest()


async def fetch_manifest(connector: Connector, application: Application, secret: str, settings: Settings) -> dict:
    status, body, _elapsed = await execute_request(
        method="GET",
        url=join_url(connector.base_url, connector.manifest_path),
        settings=settings,
        headers={**auth_headers(connector.auth_type, secret), "Accept": "application/json"},
        timeout_ms=connector.timeout_ms,
        tls_verify=connector.tls_verify,
        retries=1,
    )
    if status == 401:
        raise HubError("UPSTREAM_UNAUTHORIZED", "Connector credentials were rejected", 401)
    if status == 403:
        raise HubError("PERMISSION_DENIED", "Connector credentials are not allowed to read the manifest", 403)
    if status >= 400:
        raise HubError("SCHEMA_MISMATCH", "Capability manifest request failed", 422)
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HubError("SCHEMA_MISMATCH", "Capability manifest was not valid JSON", 422) from exc
    return validate_manifest(document, expected_app_key=application.key,
                             source_managed=connector.connector_type == "source_managed")


async def discover_capabilities(db: Session, connector: Connector, application: Application, *,
                                settings: Settings, encryption_key: str) -> list[tuple[ModuleDefinition, str]]:
    """Reconcile one connector atomically; malformed contracts never partly publish."""

    lock = _sync_locks.setdefault(connector.id, asyncio.Lock())
    async with lock:
        with db.begin_nested():
            db.execute(select(Connector).where(Connector.id == connector.id).with_for_update())
            return await _discover_capabilities(db, connector, application, settings=settings,
                                                encryption_key=encryption_key)


async def sync_source_permissions(db: Session, connector: Connector | None, application: Application,
                                  settings: Settings) -> None:
    # Client keys cannot choose a source, change connector mode or grant permissions.
    if connector and connector.connector_type == "source_managed" and connector.status == "active":
        await discover_capabilities(db, connector, application, settings=settings,
                                    encryption_key=settings.secret_encryption_key)


async def sync_admin_sources(db: Session, admin: AdminUser, settings: Settings, *, connector_id: str | None = None,
                             environment: str | None = None, app_key: str | None = None,
                             connection_metadata: bool = False) -> dict[str, dict]:
    """Refresh only this admin's trusted sources before showing their current catalog."""
    query = (select(Connector, Application).join(Application, Application.id == Connector.app_id)
             .where(Connector.connector_type == "source_managed", Connector.status == "active"))
    allowed = allowed_app_ids(db, admin)
    if allowed is not None:
        query = query.where(Application.id.in_(allowed))
    if connector_id:
        query = query.where(Connector.id == connector_id)
    if environment:
        query = query.where(Application.environment == environment)
    if app_key:
        query = query.where(Application.key == app_key)
    failures = {}
    for connector, application in db.execute(query):
        try:
            await sync_source_permissions(db, connector, application, settings)
        except HubError as error:
            if not connection_metadata:
                raise
            # Keep connection settings reachable for repair, never claim old grants are current.
            failures[connector.id] = {"code": error.code, "message": error.message}
    db.commit()
    return failures


async def _discover_capabilities(db: Session, connector: Connector, application: Application, *,
                                 settings: Settings, encryption_key: str) -> list[tuple[ModuleDefinition, str]]:

    secret = decrypt_secret(encryption_key, connector_secret(db, connector.id).secret_ciphertext)
    manifest = await fetch_manifest(connector, application, secret, settings)
    snapshot = db.scalar(select(ContractSnapshot.id).where(ContractSnapshot.connector_id == connector.id,
                                                           ContractSnapshot.manifest_hash == manifest["manifest_hash"]))
    if snapshot is None:
        db.add(ContractSnapshot(connector_id=connector.id, manifest_hash=manifest["manifest_hash"],
                                manifest_version=manifest["manifest_version"], manifest_json=manifest))
    current = {module["key"]: module for module in manifest["modules"]}
    results: list[tuple[ModuleDefinition, str]] = []
    for existing in db.scalars(select(ModuleDefinition).where(ModuleDefinition.app_id == application.id)):
        if existing.module_key not in current:
            _disable(db, existing)
            results.append((existing, "removed"))
    for key, module in current.items():
        existing = db.scalar(select(ModuleDefinition).where(ModuleDefinition.app_id == application.id,
                                                            ModuleDefinition.module_key == key))
        fingerprint = module_fingerprint(module)
        if existing is None:
            existing = ModuleDefinition(id=new_id(), app_id=application.id, module_key=key,
                                        manifest_hash=fingerprint, manifest_json=module, **_columns(module))
            db.add(existing)
            db.flush()
            db.add(ModuleSetting(id=new_id(), module_id=existing.id, enabled=False, operations_enabled=[]))
            for policy in initial_field_policies(module):
                db.add(FieldPolicy(id=new_id(), module_id=existing.id, **policy))
            results.append((existing, "new"))
            continue
        changed = existing.manifest_json != module
        previous_hash = existing.manifest_hash
        existing.manifest_json = module
        existing.manifest_hash = fingerprint
        for column, value in _columns(module).items():
            setattr(existing, column, value)
        _merge_developer_policies(db, existing.id, module,
                                  source_managed=connector.connector_type == "source_managed")
        if changed:
            # A changed contract needs review: off until an admin re-enables it, and its
            # tools need a fresh test because their fingerprints include the module hash.
            _disable(db, existing)
        elif previous_hash != fingerprint:
            # Same contract, new hash format: keep tested tools current.
            from app.services.tools import refresh_fingerprints
            refresh_fingerprints(db, existing, previous_hash)
        results.append((existing, "changed" if changed else "unchanged"))
    if connector.connector_type == "source_managed":
        from app.services.tools import sync_source_tools

        db.flush()
        sync_source_tools(db, connector, application, results)
    return results


def _columns(module: dict) -> dict:
    return {
        "name": module["name"],
        "description": module["description"],
        "schema_version": module["schema_version"],
        "supported_operations": module["supported_operations"],
        "readable_fields": module["readable_fields"],
        "writable_fields": module["writable_fields"],
        "filters": module["filters"],
        "max_page_size": module["max_page_size"],
        "risk": module["risk"],
        "last_synced_at": utcnow(),
    }


def _disable(db: Session, module: ModuleDefinition) -> None:
    setting = db.scalar(select(ModuleSetting).where(ModuleSetting.module_id == module.id))
    if setting and (setting.enabled or setting.operations_enabled):
        setting.enabled = False
        setting.operations_enabled = []
        setting.policy_version += 1


def connector_secret(db: Session, connector_id: str) -> ConnectorSecret:
    row = db.scalar(
        select(ConnectorSecret)
        .where(ConnectorSecret.connector_id == connector_id, ConnectorSecret.revoked_at.is_(None))
        .order_by(ConnectorSecret.rotated_at.desc())
    )
    if row is None:
        raise HubError("SECRET_UNAVAILABLE", "Connector credential is not available", 409)
    return row


def _merge_developer_policies(db: Session, module_id: str, module: dict, *, source_managed: bool = False) -> None:
    existing = {row.field_path: row for row in db.scalars(select(FieldPolicy).where(FieldPolicy.module_id == module_id))}
    for policy in initial_field_policies(module):
        current = existing.get(policy["field_path"])
        if current is None:
            db.add(FieldPolicy(id=new_id(), module_id=module_id, **policy))
            continue
        # A rediscovery may tighten a developer limit, never loosen an admin restriction.
        if source_managed:
            # One policy owner; sensitive fields still use the Hub's locked baseline.
            current.classification = policy["classification"]
            current.locked = policy["locked"]
            current.source = "developer"
        elif RANK[policy["classification"]] < RANK.get(current.classification, 0) or policy["locked"]:
            current.classification = policy["classification"]
            current.locked = policy["locked"] or current.locked
            current.source = "developer"
