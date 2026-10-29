"""Scoped connector pairing. Runtime client keys never authorize this control API."""

import hmac
import json
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import HubError
from app.ids import as_utc, new_id, utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    ConnectorEnrollment,
    ConnectorSecret,
    ServiceIdentity,
)
from app.security.audit import record_audit
from app.security.authorization import WRITE_ROLES, require_app_access, require_role
from app.security.clients import READ_SCOPE
from app.security.crypto import decrypt_secret, encrypt_secret, sha256_hex
from app.services import connectors


def metadata(row: ConnectorEnrollment) -> dict:
    expired = (as_utc(row.management_expires_at) <= utcnow()
               or (row.status != "active" and as_utc(row.expires_at) <= utcnow()))
    status = "expired" if expired and row.status not in {"revoked", "expired"} else row.status
    return {"id": row.id, "connector_id": row.connector_id, "status": status,
            "source_url": row.source_url, "expires_at": as_utc(row.expires_at).isoformat(),
            "management_expires_at": as_utc(row.management_expires_at).isoformat(),
            "created_at": as_utc(row.created_at).isoformat(), "replacement_id": row.replacement_id}


def _lock(db: Session, row: ConnectorEnrollment) -> Connector:
    # All lifecycle mutations lock the parent before the pairing/identity. This
    # also serializes them against source activation and operator pause/archive.
    connector = db.scalar(select(Connector).where(Connector.id == row.connector_id).with_for_update()
                          .execution_options(populate_existing=True))
    if connector is None:
        raise HubError("PERMISSION_DENIED", "Connection is unavailable", 403)
    current = db.scalar(select(ConnectorEnrollment).where(ConnectorEnrollment.id == row.id).with_for_update()
                        .execution_options(populate_existing=True))
    if current is None:
        raise HubError("CONFLICT", "Pairing is unavailable", 409)
    return connector


def create(db: Session, admin: AdminUser, data: dict, settings: Settings) -> dict:
    require_role(admin.role, WRITE_ROLES)
    source_token, delegation, client_key = (secrets.token_urlsafe(32), secrets.token_urlsafe(32),
                                             "hub_" + secrets.token_urlsafe(32))
    view = connectors.create_connector(db, admin, {
        **data, "connector_type": "source_managed", "auth_type": "bearer",
        "secret": source_token, "delegation_secret": delegation,
    }, settings)
    db.flush()
    connector = db.get(Connector, view["id"])
    return _issue(db, admin, connector, source_token, delegation, client_key, settings)


def _issue(db: Session, admin: AdminUser, connector: Connector, source_token: str,
           delegation: str, client_key: str, settings: Settings, enrollment_id: str | None = None,
           prior_identity: ServiceIdentity | None = None) -> dict:
    application = db.get(Application, connector.app_id)
    secret = db.scalar(select(ConnectorSecret).where(ConnectorSecret.connector_id == connector.id,
                                                     ConnectorSecret.revoked_at.is_(None)))
    deadline = utcnow() + timedelta(days=90)
    identity = ServiceIdentity(id=new_id(), app_id=application.id, name="Laravel connector",
                               token_hash=sha256_hex(client_key), scopes=[READ_SCOPE],
                               allowed_tools=(list(prior_identity.allowed_tools) if prior_identity is not None
                                              and prior_identity.allowed_tools is not None else None),
                               profile_id=prior_identity.profile_id if prior_identity is not None else None,
                               expires_at=utcnow())
    db.add(identity)
    db.flush()
    enrollment_id = enrollment_id or new_id()
    code = "enr_" + enrollment_id + "_" + secrets.token_urlsafe(24)
    row = ConnectorEnrollment(
        id=enrollment_id, connector_id=connector.id, identity_id=identity.id, secret_id=secret.id, created_by=admin.id,
        code_hash=sha256_hex(code), source_url=connector.base_url,
        expires_at=utcnow() + timedelta(minutes=10), management_expires_at=deadline,
        bundle_ciphertext=encrypt_secret(settings.secret_encryption_key, json.dumps({
            "app_key": application.key, "environment": application.environment,
            "url": settings.mcp_public_url, "source_url": connector.base_url,
            "app_token": source_token, "delegation_secret": delegation, "client_key": client_key,
            "connector_id": connector.id, "enabled": True,
        })), status="pending",
    )
    db.add(row)
    db.flush()
    record_audit(db, action="enrollment.create", actor_ref=f"admin:{admin.id}", app_key=application.key,
                 environment=application.environment, result="success")
    return {**metadata(row), "code": code}


def _bundle(db: Session, row: ConnectorEnrollment):
    connector = db.get(Connector, row.connector_id)
    application = db.get(Application, connector.app_id) if connector else None
    creator = db.get(AdminUser, row.created_by)
    if not connector or not application or not creator or not creator.is_active:
        raise HubError("PERMISSION_DENIED", "Enrollment is unavailable", 403)
    require_role(creator.role, WRITE_ROLES)
    require_app_access(db, creator, application.id)
    secret = db.get(ConnectorSecret, row.secret_id)
    identity = db.get(ServiceIdentity, row.identity_id)
    if not secret or secret.revoked_at is not None or not identity or identity.revoked_at is not None:
        raise HubError("PERMISSION_DENIED", "Enrollment credentials were revoked or replaced", 403)
    if application.status != "active" or connector.status == "archived" or connector.base_url != row.source_url:
        raise HubError("PERMISSION_DENIED", "Enrollment binding is no longer valid", 403)
    return connector, application, creator


def revoke(db: Session, row: ConnectorEnrollment, *, status: str = "revoked") -> None:
    connector = _lock(db, row)
    row.status = status
    row.bundle_ciphertext = None
    identity = db.get(ServiceIdentity, row.identity_id)
    if identity:
        identity.revoked_at = utcnow()
    changed = db.execute(update(ConnectorSecret).where(ConnectorSecret.id == row.secret_id,
                        ConnectorSecret.revoked_at.is_(None)).values(revoked_at=utcnow())).rowcount
    if connector and changed:
        connector.status = "paused"


def _expiry(db: Session, row: ConnectorEnrollment) -> None:
    expired = (as_utc(row.management_expires_at) <= utcnow()
               or (row.status != "active" and as_utc(row.expires_at) <= utcnow()))
    if expired and row.status not in {"revoked", "expired"}:
        _lock(db, row)
        # A concurrent administrator may have renewed it while this request
        # waited. Recheck the refreshed row before expiring any credentials.
        expired = (as_utc(row.management_expires_at) <= utcnow()
                   or (row.status != "active" and as_utc(row.expires_at) <= utcnow()))
        if expired and row.status not in {"revoked", "expired"}:
            revoke(db, row, status="expired")
            db.commit()
    if row.status in {"expired", "revoked"}:
        raise HubError("ENROLLMENT_EXPIRED", "Enrollment expired or was revoked", 410)


def claim(db: Session, data: dict, settings: Settings) -> dict:
    row = db.scalar(select(ConnectorEnrollment).where(ConnectorEnrollment.code_hash == sha256_hex(data["code"])))
    if row is None:
        raise HubError("UNAUTHENTICATED", "Enrollment is unavailable", 401)
    _expiry(db, row)
    _bundle(db, row)
    # Single compare-and-swap across workers; only one installation receives the bundle.
    changed = db.execute(update(ConnectorEnrollment).where(
        ConnectorEnrollment.id == row.id, ConnectorEnrollment.status == "pending",
        ConnectorEnrollment.expires_at > utcnow(),
    ).values(status="claimed", installation_id=data["installation_id"], attempt_id=data["attempt_id"],
             proof_hash=sha256_hex(data["proof"])), execution_options={"synchronize_session": False}).rowcount
    if changed != 1 or not row.bundle_ciphertext:
        raise HubError("CONFLICT", "Enrollment was already claimed; resume using the saved installation proof", 409)
    bundle = json.loads(decrypt_secret(settings.secret_encryption_key, row.bundle_ciphertext))
    row.status = "claimed"
    row.installation_id, row.attempt_id = data["installation_id"], data["attempt_id"]
    row.proof_hash = sha256_hex(data["proof"])
    row.bundle_ciphertext = None
    _connector, application, _creator = _bundle(db, row)
    record_audit(db, action="enrollment.claim", actor_ref="installation:" + sha256_hex(data["installation_id"])[:24],
                 app_key=application.key, environment=application.environment, result="success")
    db.flush()
    return {**metadata(row), "connection": bundle}


def authenticated(db: Session, enrollment_id: str, data: dict):
    row = db.get(ConnectorEnrollment, enrollment_id)
    if (row is None or not row.proof_hash
            or not hmac.compare_digest(row.proof_hash, sha256_hex(data["proof"]))
            or row.installation_id != data["installation_id"] or row.attempt_id != data["attempt_id"]):
        raise HubError("UNAUTHENTICATED", "Enrollment proof is not valid", 401)
    _expiry(db, row)
    connector, application, creator = _bundle(db, row)
    return row, connector, application, creator


async def complete(db: Session, enrollment_id: str, data: dict, settings: Settings) -> dict:
    row, connector, application, creator = authenticated(db, enrollment_id, data)
    if row.status == "active":
        return metadata(row)
    if row.status not in {"claimed", "failed"}:
        raise HubError("CONFLICT", "Enrollment verification is in progress", 409)
    changed = db.execute(update(ConnectorEnrollment).where(
        ConnectorEnrollment.id == row.id, ConnectorEnrollment.status.in_(["claimed", "failed"]),
    ).values(status="verifying"), execution_options={"synchronize_session": False}).rowcount
    if changed != 1:
        raise HubError("CONFLICT", "Enrollment verification is in progress", 409)
    row.status = "verifying"
    db.commit()
    try:
        health = await connectors.test_connector(db, creator, connector, application, settings)
        if health["status"] != "ok":
            raise HubError("UPSTREAM_UNAVAILABLE", "The source connection check failed", 422)
        await connectors.discover(db, creator, connector, application, settings)
        # Revalidate the binding and current authority after the network requests.
        db.flush()
        db.expire_all()
        row = db.get(ConnectorEnrollment, enrollment_id)
        if row.status != "verifying":
            raise HubError("CONFLICT", "Enrollment was changed during verification", 409)
        _expiry(db, row)
        connector, application, creator = _bundle(db, row)
        # Serialize completion against revocation and an operator pausing the source.
        connector = db.scalar(select(Connector).where(Connector.id == connector.id).with_for_update()
                              .execution_options(populate_existing=True))
        if connector.status != "draft":
            raise HubError("CONFLICT", "The source state changed during verification", 409)
        changed = db.execute(update(ConnectorEnrollment).where(
            ConnectorEnrollment.id == row.id, ConnectorEnrollment.status == "verifying",
            ConnectorEnrollment.expires_at > utcnow(),
        ).values(status="active"), execution_options={"synchronize_session": False}).rowcount
        if changed != 1:
            raise HubError("CONFLICT", "Enrollment was changed during verification", 409)
        connectors.activate(db, creator, connector, application)
        db.get(ServiceIdentity, row.identity_id).expires_at = row.management_expires_at
        row.status = "active"
        record_audit(db, action="enrollment.complete", actor_ref="installation:" + sha256_hex(data["installation_id"])[:24],
                     app_key=application.key, environment=application.environment, result="success")
        db.flush()
    except Exception:
        db.rollback()
        current = db.get(ConnectorEnrollment, enrollment_id)
        if current and current.status == "verifying":
            current.status = "failed"
            db.commit()
        raise
    return metadata(row)


async def sync(db: Session, enrollment_id: str, data: dict, settings: Settings) -> dict:
    row, connector, application, creator = authenticated(db, enrollment_id, data)
    if row.status != "active" or connector.status != "active":
        raise HubError("CONNECTOR_INACTIVE", "The paired connector is not active", 409)
    health = await connectors.test_connector(db, creator, connector, application, settings)
    if health["status"] != "ok":
        raise HubError("UPSTREAM_UNAVAILABLE", "The source connection check failed", 422)
    await connectors.discover(db, creator, connector, application, settings)
    return metadata(row)


def replace(db: Session, admin: AdminUser, row: ConnectorEnrollment, settings: Settings) -> dict:
    connector = _lock(db, row)
    application = db.get(Application, connector.app_id)
    require_app_access(db, admin, application.id)
    require_role(admin.role, WRITE_ROLES)
    if application.status != "active" or connector.status == "archived":
        raise HubError("PERMISSION_DENIED", "Connection is unavailable", 403)
    prior_identity = db.scalar(select(ServiceIdentity).where(ServiceIdentity.id == row.identity_id).with_for_update()
                               .execution_options(populate_existing=True))
    if prior_identity is None:
        raise HubError("CONFLICT", "Connection identity is unavailable", 409)
    # An old enrollment can never rotate a newer installation.
    enrollment_id = new_id()
    changed = db.execute(update(ConnectorEnrollment).where(
        ConnectorEnrollment.id == row.id, ConnectorEnrollment.replacement_id.is_(None),
    ).values(replacement_id=enrollment_id), execution_options={"synchronize_session": False}).rowcount
    if changed != 1:
        raise HubError("CONFLICT", "Use the current enrollment to replace the connection", 409)
    row.replacement_id = enrollment_id
    revoke(db, row)
    source_token, delegation = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    client_key = "hub_" + secrets.token_urlsafe(32)
    db.add(ConnectorSecret(id=new_id(), connector_id=connector.id,
                          secret_ciphertext=encrypt_secret(settings.secret_encryption_key, source_token),
                          delegation_ciphertext=encrypt_secret(settings.secret_encryption_key, delegation)))
    connector.status = "draft"
    db.flush()
    return _issue(db, admin, connector, source_token, delegation, client_key, settings, enrollment_id, prior_identity)


def renew(db: Session, admin: AdminUser, row: ConnectorEnrollment) -> dict:
    connector = _lock(db, row)
    require_role(admin.role, WRITE_ROLES)
    require_app_access(db, admin, connector.app_id)
    _expiry(db, row)
    _connector, application, _creator = _bundle(db, row)
    require_role(admin.role, WRITE_ROLES)
    require_app_access(db, admin, application.id)
    if row.status != "active":
        raise HubError("CONFLICT", "Only active connections can be renewed", 409)
    row.management_expires_at = utcnow() + timedelta(days=90)
    db.get(ServiceIdentity, row.identity_id).expires_at = row.management_expires_at
    record_audit(db, action="enrollment.renew", actor_ref=f"admin:{admin.id}", app_key=application.key,
                 environment=application.environment, result="success")
    return metadata(row)
