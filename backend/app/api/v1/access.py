"""Who can use the hub: client keys for AI clients and admin users for people."""

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.api.v1.configuration import (
    IdentityChanges,
    IdentityCreate,
    UserChanges,
    UserCreate,
    checked,
)
from app.errors import HubError
from app.ids import as_utc, new_id, utcnow
from app.persistence.models import (
    AdminApplicationScope,
    AdminUser,
    Application,
    Connector,
    ServiceIdentity,
    ToolDefinition,
)
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import (
    ADMIN_ROLES,
    READ_ROLES,
    WRITE_ROLES,
    allowed_app_ids,
    require_app_access,
    require_role,
)
from app.security.clients import READ_SCOPE, WRITE_SCOPE
from app.security.crypto import sha256_hex
from app.security.passwords import hash_password, password_is_acceptable
from app.tools.catalog import HUB_TOOL_NAMES

router = APIRouter(tags=["access"])


def _identity_view(row: ServiceIdentity, application: Application | None) -> dict:
    expires = as_utc(row.expires_at) if row.expires_at else None
    status = "revoked" if row.revoked_at else ("expired" if expires and expires <= utcnow() else "active")
    return {
        "id": row.id, "name": row.name, "app_id": row.app_id,
        "app_key": application.key if application else None, "app_name": application.name if application else None,
        "environment": application.environment if application else None,
        "scopes": row.scopes, "write": WRITE_SCOPE in (row.scopes or []), "allowed_tools": row.allowed_tools,
        "expires_at": expires.isoformat() if expires else None, "revoked": row.revoked_at is not None,
        "status": status, "last_used_at": as_utc(row.last_used_at).isoformat() if row.last_used_at else None,
        "created_at": as_utc(row.created_at).isoformat(),
    }


def _allowed_tools(db: Session, application: Application, names: list[str] | None) -> list[str] | None:
    if names is None:
        return None
    known = set(HUB_TOOL_NAMES) | set(db.scalars(
        select(ToolDefinition.mcp_name).join(Connector, Connector.id == ToolDefinition.connector_id)
        .where(Connector.app_id == application.id, ToolDefinition.status != "archived")))
    cleaned = sorted(set(names))
    if any(name not in known for name in cleaned):
        raise HubError("VALIDATION_FAILED", "Allowed tools must be built-in tools or tools of this app", 422)
    return cleaned


@router.get("/service-identities")
def identities(app_id: str | None = None, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, READ_ROLES)
    query = select(ServiceIdentity).order_by(ServiceIdentity.created_at.desc())
    allowed = allowed_app_ids(db, user)
    if allowed is not None:
        query = query.where(ServiceIdentity.app_id.in_(allowed))
    if app_id:
        query = query.where(ServiceIdentity.app_id == app_id)
    return ok([_identity_view(row, db.get(Application, row.app_id)) for row in db.scalars(query)])


@router.post("/service-identities")
def create_identity(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    data = checked(IdentityCreate, payload)
    application = db.scalar(select(Application).where(Application.key == data["app_key"],
                                                      Application.environment == data["environment"]))
    if application is None:
        raise HubError("NOT_FOUND", "Application was not found", 404)
    require_app_access(db, user, application.id)
    raw = "hub_" + secrets.token_urlsafe(32)
    identity = ServiceIdentity(
        id=new_id(), name=data["name"], token_hash=sha256_hex(raw), app_id=application.id,
        scopes=[READ_SCOPE] + ([WRITE_SCOPE] if data["write"] else []),
        allowed_tools=_allowed_tools(db, application, data["allowed_tools"]),
        expires_at=utcnow() + timedelta(days=data["ttl_days"]),
    )
    db.add(identity)
    record_audit(db, action="key.create", actor_ref=f"admin:{user.id}", result="success",
                 app_key=application.key, environment=application.environment)
    db.commit()
    # The token is shown once; only its hash is stored.
    return ok({**_identity_view(identity, application), "token": raw}, 201)


@router.patch("/service-identities/{identity_id}")
def update_identity(identity_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    identity = db.get(ServiceIdentity, identity_id)
    if identity is None:
        raise HubError("NOT_FOUND", "Client key was not found", 404)
    require_app_access(db, user, identity.app_id)
    if identity.revoked_at is not None:
        raise HubError("CONFLICT", "Revoked keys cannot be changed", 409)
    application = db.get(Application, identity.app_id)
    changes = checked(IdentityChanges, payload, partial=True)
    if "name" in changes:
        identity.name = changes["name"]
    if "write" in changes:
        identity.scopes = [READ_SCOPE] + ([WRITE_SCOPE] if changes["write"] else [])
    if "allowed_tools" in changes:
        identity.allowed_tools = _allowed_tools(db, application, changes["allowed_tools"])
    record_audit(db, action="key.update", actor_ref=f"admin:{user.id}", result="success",
                 app_key=application.key, environment=application.environment)
    db.commit()
    return ok(_identity_view(identity, application))


@router.post("/service-identities/{identity_id}/revoke")
def revoke_identity(identity_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    identity = db.get(ServiceIdentity, identity_id)
    if identity is None:
        raise HubError("NOT_FOUND", "Client key was not found", 404)
    require_app_access(db, user, identity.app_id)
    application = db.get(Application, identity.app_id)
    identity.revoked_at = identity.revoked_at or utcnow()
    record_audit(db, action="key.revoke", actor_ref=f"admin:{user.id}", result="success",
                 app_key=application.key if application else None, environment=application.environment if application else None)
    db.commit()
    return ok({"revoked": True})


def _user_view(db: Session, row: AdminUser) -> dict:
    return {"id": row.id, "email": row.email, "role": row.role, "mfa_enabled": row.mfa_enabled, "is_active": row.is_active,
            "app_ids": list(db.scalars(select(AdminApplicationScope.app_id).where(AdminApplicationScope.user_id == row.id))),
            "created_at": as_utc(row.created_at).isoformat()}


def _set_scopes(db: Session, target: AdminUser, app_ids: list[str]) -> None:
    for app_id in set(app_ids):
        if db.get(Application, app_id) is None:
            raise HubError("VALIDATION_FAILED", "Application assignment is invalid", 422)
    db.execute(delete(AdminApplicationScope).where(AdminApplicationScope.user_id == target.id))
    for app_id in set(app_ids):
        db.add(AdminApplicationScope(user_id=target.id, app_id=app_id))


@router.get("/users")
def users(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    return ok([_user_view(db, row) for row in db.scalars(select(AdminUser).order_by(AdminUser.created_at))])


@router.post("/users")
def create_user(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    data = checked(UserCreate, payload)
    email = data["email"].strip().lower()
    if "@" not in email or not password_is_acceptable(data["password"]):
        raise HubError("VALIDATION_FAILED", "Use a valid email and a password of 12+ characters with upper, lower and a digit", 422)
    if db.scalar(select(AdminUser).where(AdminUser.email == email)):
        raise HubError("CONFLICT", "An admin with that email already exists", 409)
    created = AdminUser(id=new_id(), email=email, password_hash=hash_password(data["password"]), role=data["role"])
    db.add(created)
    db.flush()
    _set_scopes(db, created, data["app_ids"])
    record_audit(db, action="admin.create", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok(_user_view(db, created), 201)


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    target = db.get(AdminUser, user_id)
    if target is None:
        raise HubError("NOT_FOUND", "Administrator was not found", 404)
    changes = checked(UserChanges, payload, partial=True)
    demoting = changes.get("role", target.role) != "super_admin" or changes.get("is_active", target.is_active) is False
    if target.role == "super_admin" and demoting:
        if target.id == user.id:
            raise HubError("CONFLICT", "You cannot remove your own super admin access", 409)
        others = db.scalar(select(AdminUser.id).where(AdminUser.role == "super_admin", AdminUser.is_active.is_(True),
                                                      AdminUser.id != target.id))
        if others is None:
            raise HubError("CONFLICT", "At least one active super admin is required", 409)
    if "role" in changes:
        target.role = changes["role"]
    if "is_active" in changes:
        target.is_active = changes["is_active"]
    if "app_ids" in changes:
        _set_scopes(db, target, changes["app_ids"])
    record_audit(db, action="admin.update", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok(_user_view(db, target))
