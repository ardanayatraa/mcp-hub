"""Who can use the hub: client keys for AI clients and admin users for people."""

import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.api.v1.configuration import (
    IdentityChanges,
    IdentityCreate,
    InviteLinkOptions,
    UserChanges,
    UserCreate,
    checked,
)
from app.config import get_settings
from app.errors import HubError
from app.ids import as_utc, new_id, utcnow
from app.persistence.models import (
    AdminApplicationScope,
    AdminUser,
    Application,
    Connector,
    MfaChallenge,
    ServiceIdentity,
    ToolDefinition,
)
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import enrollment_deadline, require_csrf, reset_mfa
from app.security.authorization import (
    READ_ROLES,
    WRITE_ROLES,
    allowed_app_ids,
    require_app_access,
    require_role,
    require_root,
)
from app.security.clients import READ_SCOPE, WRITE_SCOPE
from app.security.crypto import sha256_hex
from app.security.mailer import activation_url, require_mailer
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
        expires_at=utcnow() + timedelta(days=data["ttl_days"]) if data["ttl_days"] is not None else None,
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
    return {"id": row.id, "email": None if row.activation_token_hash else row.email,
            "role": row.role, "is_root": row.is_root,
            "auth_method": row.auth_method, "pending_activation": row.activation_token_hash is not None,
            "activation_expires_at": as_utc(row.activation_expires_at).isoformat() if row.activation_expires_at else None,
            "mfa_enabled": row.mfa_enabled, "is_active": row.is_active,
            "mfa_enroll_until": None if row.mfa_enabled or enrollment_deadline(row) is None else enrollment_deadline(row).isoformat(),
            "app_ids": list(db.scalars(select(AdminApplicationScope.app_id).where(AdminApplicationScope.user_id == row.id))),
            "created_at": as_utc(row.created_at).isoformat()}


def _set_scopes(db: Session, target: AdminUser, app_ids: list[str]) -> None:
    for app_id in set(app_ids):
        if db.get(Application, app_id) is None:
            raise HubError("VALIDATION_FAILED", "Application assignment is invalid", 422)
    db.execute(delete(AdminApplicationScope).where(AdminApplicationScope.user_id == target.id))
    for app_id in set(app_ids):
        db.add(AdminApplicationScope(user_id=target.id, app_id=app_id))


def _require_team_creator(user: AdminUser) -> None:
    if not ((user.is_root and user.role == "super_admin") or (not user.is_root and user.role == "hub_admin")):
        raise HubError("PERMISSION_DENIED", "Operation is not permitted", 403)


def _invite_deadline(expiry: str):
    days = {"1_day": 1, "1_week": 7, "1_month": 30}
    return utcnow() + timedelta(days=days[expiry]) if expiry != "never" else None


@router.get("/users")
def users(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _require_team_creator(user)
    query = select(AdminUser).order_by(AdminUser.created_at)
    if not user.is_root:
        query = query.where(AdminUser.is_root.is_(False))
    return ok([_user_view(db, row) for row in db.scalars(query)])


@router.post("/users")
def create_user(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _require_team_creator(user)
    data = checked(UserCreate, payload)
    if not user.is_root and data["password"] is not None:
        raise HubError("PERMISSION_DENIED", "Invite new members with an activation link", 403)
    invited = data["password"] is None
    if invited:
        if data["email"] is not None:
            raise HubError("VALIDATION_FAILED", "The member enters their email during activation", 422)
        require_mailer()
        email = None
    else:
        if data["email"] is None:
            raise HubError("VALIDATION_FAILED", "Email is required with a password", 422)
        email = data["email"].strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9][A-Za-z0-9.\-]*", email):
            raise HubError("VALIDATION_FAILED", "Use a valid email address", 422)
    if data["password"] is not None and not password_is_acceptable(data["password"]):
        raise HubError("VALIDATION_FAILED", "Use a password of 12+ characters with upper, lower and a digit", 422)
    if data["password"] is not None and get_settings().environment == "production":
        raise HubError("VALIDATION_FAILED", "Invite new administrators with an activation link", 422)
    if email is not None and db.scalar(select(AdminUser).where(AdminUser.email == email)):
        raise HubError("CONFLICT", "An admin with that email already exists", 409)
    activation_token = secrets.token_urlsafe(32) if invited else None
    created = AdminUser(id=new_id(), email=email,
                        password_hash=hash_password(data["password"] or secrets.token_urlsafe(48)), role=data["role"],
                        auth_method="email_otp" if invited else "totp",
                        activation_token_hash=sha256_hex(activation_token) if activation_token else None,
                        activation_expires_at=_invite_deadline(data["invite_expiry"]) if invited else None,
                        activation_issued_at=utcnow() if invited else None,
                        mfa_enroll_until=utcnow() + timedelta(hours=get_settings().mfa_enroll_hours) if not invited else None)
    db.add(created)
    db.flush()
    _set_scopes(db, created, data["app_ids"])
    record_audit(db, action="admin.create", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok({**_user_view(db, created),
               **({"activation_url": activation_url(activation_token)} if activation_token else {})}, 201)


@router.post("/users/{user_id}/resend-invite")
def resend_invite(user_id: str, payload: dict | None = None, db: Session = Depends(get_db),
                  user: AdminUser = Depends(require_csrf)):
    require_root(user)
    data = checked(InviteLinkOptions, payload or {})
    target = db.get(AdminUser, user_id)
    if target is None:
        raise HubError("NOT_FOUND", "Administrator was not found", 404)
    if target.auth_method != "email_otp" or target.activation_token_hash is None or not target.is_active:
        raise HubError("CONFLICT", "This account has no pending invitation", 409)
    if target.activation_issued_at and as_utc(target.activation_issued_at) > utcnow() - timedelta(minutes=1):
        raise HubError("RATE_LIMITED", "Please wait before resending this invitation", 429)
    require_mailer()
    token = secrets.token_urlsafe(32)
    target.activation_token_hash = sha256_hex(token)
    target.activation_expires_at = _invite_deadline(data["invite_expiry"])
    target.activation_issued_at = utcnow()
    db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == target.id,
               MfaChallenge.purpose.in_(["activation_code", "activation_ready"])))
    record_audit(db, action="admin.invite_resend", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok({"activation_url": activation_url(token),
               "activation_expires_at": as_utc(target.activation_expires_at).isoformat()
               if target.activation_expires_at else None})


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_root(user)
    target = db.get(AdminUser, user_id)
    if target is None:
        raise HubError("NOT_FOUND", "Administrator was not found", 404)
    changes = checked(UserChanges, payload, partial=True)
    if target.is_root and ("role" in changes or changes.get("is_active") is False or "app_ids" in changes):
        raise HubError("CONFLICT", "Root access cannot be changed through the team page", 409)
    if "role" in changes:
        target.role = changes["role"]
    if "is_active" in changes:
        target.is_active = changes["is_active"]
    if "app_ids" in changes:
        _set_scopes(db, target, changes["app_ids"])
    if changes.get("reset_mfa"):
        if target.id == user.id:
            raise HubError("CONFLICT", "Your own two-factor sign-in cannot be reset here", 409)
        if target.auth_method in {"email_otp", "password"}:
            raise HubError("CONFLICT", "This account does not use an authenticator app", 409)
        reset_mfa(db, target, get_settings().mfa_enroll_hours)
        record_audit(db, action="admin.mfa_reset", actor_ref=f"admin:{user.id}", result="success")
    record_audit(db, action="admin.update", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok(_user_view(db, target))
