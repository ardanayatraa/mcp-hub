import pyotp
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.v1.common import client_host, ok, user_view
from app.config import get_settings
from app.errors import HubError
from app.ids import utcnow
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import (
    _session_from_request,
    authenticate_password,
    clear_session,
    enrollment_open,
    get_current_user,
    issue_mfa_token,
    read_mfa_token,
    require_csrf,
    start_session,
    verify_totp,
    write_session_cookie,
)
from app.security.crypto import encrypt_secret
from app.security.rate_limit import hit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or len(cleaned) > 320:
            raise ValueError("invalid email")
        return cleaned


class MfaBody(BaseModel):
    mfa_token: str
    code: str


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    hit(f"login:{client_host(request)}", settings.login_rate_limit, 60)
    user = authenticate_password(db, body.email, body.password)
    if user is None:
        record_audit(db, action="auth.login", actor_ref="anonymous", result="denied", error_code="UNAUTHENTICATED")
        db.commit()
        raise HubError("UNAUTHENTICATED", "Invalid credentials", 401)
    if user.mfa_enabled:
        token = issue_mfa_token(db, user.id, "mfa")
        record_audit(db, action="auth.mfa_challenge", actor_ref=f"admin:{user.id}", result="success")
        db.commit()
        return ok({"mfa_required": True, "mfa_token": token})
    if settings.mfa_required:
        # Trust on first use only within the window, so an old password alone cannot claim the account.
        if not enrollment_open(user, settings.mfa_enroll_hours):
            record_audit(db, action="auth.login", actor_ref=f"admin:{user.id}", result="denied",
                         error_code="MFA_ENROLLMENT_EXPIRED")
            db.commit()
            raise HubError("MFA_ENROLLMENT_EXPIRED", "Two-factor sign-in was not set up in time. "
                           "Ask a super admin to reset it for you.", 403)
        secret = pyotp.random_base32()
        user.totp_secret_encrypted = encrypt_secret(settings.secret_encryption_key, secret)
        user.mfa_enabled = False
        token = issue_mfa_token(db, user.id, "enroll")
        db.commit()
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="MCP Hub")
        return ok(
            {
                "enrollment_required": True,
                "mfa_token": token,
                "otpauth_uri": uri,
            }
        )
    raw, csrf = start_session(db, user)
    record_audit(db, action="auth.login", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    payload = ok({"user": user_view(user), "csrf_token": csrf})
    write_session_cookie(payload, raw)
    return payload


@router.post("/mfa")
def confirm_mfa(body: MfaBody, request: Request, db: Session = Depends(get_db)):
    from sqlalchemy import or_, update

    from app.persistence.models import MfaChallenge
    settings = get_settings()
    hit(f"mfa:{client_host(request)}", settings.mfa_rate_limit, 60)
    challenge = read_mfa_token(db, body.mfa_token)
    hit(f"mfa-challenge:{challenge.id}", settings.mfa_rate_limit, 300)
    purpose = challenge.purpose
    user = db.get(AdminUser, challenge.user_id)
    counter = verify_totp(user, body.code) if user is not None and user.is_active and not (purpose == "enroll" and user.mfa_enabled) else None
    if counter is None:
        record_audit(db, action="auth.mfa", actor_ref="anonymous", result="denied", error_code="UNAUTHENTICATED")
        db.commit()
        raise HubError("UNAUTHENTICATED", "Invalid credentials", 401)
    consumed = db.execute(update(MfaChallenge).where(MfaChallenge.id == challenge.id, MfaChallenge.used_at.is_(None), MfaChallenge.expires_at > utcnow()).values(used_at=utcnow()).execution_options(synchronize_session=False))
    updated = db.execute(update(AdminUser).where(AdminUser.id == user.id, AdminUser.is_active.is_(True),
        or_(AdminUser.last_totp_counter.is_(None), AdminUser.last_totp_counter < counter)).values(last_totp_counter=counter))
    if consumed.rowcount != 1 or updated.rowcount != 1:
        db.rollback()
        raise HubError("UNAUTHENTICATED", "MFA challenge was already used", 401)
    if purpose == "enroll":
        user.mfa_enabled = True
    raw, csrf = start_session(db, user)
    record_audit(db, action="auth.login", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    payload = ok({"user": user_view(user), "csrf_token": csrf})
    write_session_cookie(payload, raw)
    return payload


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    from sqlalchemy import select

    from app.persistence.models import AdminSession
    from app.security.crypto import sha256_hex

    raw = request.cookies.get(get_settings().cookie_name)
    if raw:
        row = db.scalar(select(AdminSession).where(AdminSession.token_hash == sha256_hex(raw)))
        if row is not None:
            db.delete(row)
    record_audit(db, action="auth.logout", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    payload = ok({"signed_out": True})
    clear_session(payload)
    return payload


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(get_current_user)):
    session, _ = _session_from_request(request, db)
    return ok({**user_view(user), "csrf_token": session.csrf_token})
