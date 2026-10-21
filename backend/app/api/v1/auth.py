import hmac
import secrets
from datetime import timedelta

import pyotp
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.v1.common import client_host, ok, user_view
from app.config import get_settings
from app.errors import HubError
from app.ids import as_utc, utcnow
from app.persistence.models import AdminUser, MfaChallenge
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import (
    _session_from_request,
    authenticate_password,
    clear_session,
    email_code_hash,
    enrollment_open,
    get_current_user,
    issue_mfa_token,
    read_mfa_token,
    require_csrf,
    start_session,
    verify_totp,
    write_session_cookie,
)
from app.security.crypto import encrypt_secret, sha256_hex
from app.security.mailer import require_mailer, send_login_code
from app.security.passwords import hash_password, password_is_acceptable
from app.security.rate_limit import hit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or len(cleaned) > 320:
            raise ValueError("invalid email")
        return cleaned


class MfaBody(BaseModel):
    mfa_token: str = Field(max_length=1000)
    code: str = Field(max_length=20)


class ActivationBody(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=12, max_length=200)


@router.post("/activate")
def activate(body: ActivationBody, request: Request, db: Session = Depends(get_db)):
    hit(f"activate:{client_host(request)}", 10, 60)
    if not password_is_acceptable(body.password):
        raise HubError("VALIDATION_FAILED", "Use a password of 12+ characters with upper, lower and a digit", 422)
    result = db.execute(update(AdminUser).where(
        AdminUser.activation_token_hash == sha256_hex(body.token),
        AdminUser.activation_expires_at > utcnow(),
        AdminUser.auth_method == "email_otp",
        AdminUser.is_active.is_(True),
    ).values(password_hash=hash_password(body.password), activation_token_hash=None,
             activation_expires_at=None).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HubError("INVALID_INVITATION", "Invitation expired or already used. Ask root to resend it.", 400)
    record_audit(db, action="admin.activate", actor_ref="system:invite", result="success")
    db.commit()
    return ok({"activated": True})


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    hit(f"login:{client_host(request)}", settings.login_rate_limit, 60)
    user = authenticate_password(db, body.email, body.password)
    if user is None:
        record_audit(db, action="auth.login", actor_ref="anonymous", result="denied", error_code="UNAUTHENTICATED")
        db.commit()
        raise HubError("UNAUTHENTICATED", "Invalid credentials", 401)
    if user.auth_method == "email_otp":
        require_mailer()
        recent = list(db.scalars(select(MfaChallenge).where(
            MfaChallenge.user_id == user.id, MfaChallenge.purpose == "email_otp",
            MfaChallenge.expires_at > utcnow()).order_by(MfaChallenge.expires_at.desc())))
        if len(recent) >= 5 or (recent and as_utc(recent[0].expires_at) > utcnow() + timedelta(minutes=9)):
            raise HubError("RATE_LIMITED", "Please wait before requesting another email code", 429)
        db.execute(update(MfaChallenge).where(MfaChallenge.user_id == user.id,
                   MfaChallenge.purpose == "email_otp", MfaChallenge.used_at.is_(None))
                   .values(used_at=utcnow()).execution_options(synchronize_session=False))
        code = f"{secrets.randbelow(1_000_000):06d}"
        token = issue_mfa_token(db, user.id, "email_otp", code=code)
        send_login_code(user.email, code)
        record_audit(db, action="auth.mfa_challenge", actor_ref=f"admin:{user.id}", result="success")
        db.commit()
        return ok({"mfa_required": True, "mfa_channel": "email", "mfa_token": token})
    if user.mfa_enabled:
        token = issue_mfa_token(db, user.id, "mfa")
        record_audit(db, action="auth.mfa_challenge", actor_ref=f"admin:{user.id}", result="success")
        db.commit()
        return ok({"mfa_required": True, "mfa_token": token})
    if settings.mfa_required or (user.is_root and settings.environment == "production"):
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

    settings = get_settings()
    hit(f"mfa:{client_host(request)}", settings.mfa_rate_limit, 60)
    challenge = read_mfa_token(db, body.mfa_token)
    hit(f"mfa-challenge:{challenge.id}", settings.mfa_rate_limit, 300)
    purpose = challenge.purpose
    user = db.get(AdminUser, challenge.user_id)
    if purpose == "email_otp":
        valid_user = user is not None and user.is_active and user.auth_method == "email_otp" and user.activation_token_hash is None
        expected = email_code_hash(challenge.id, body.code.strip())
        if not valid_user or challenge.code_hash is None or not hmac.compare_digest(challenge.code_hash, expected):
            db.execute(update(MfaChallenge).where(MfaChallenge.id == challenge.id,
                       MfaChallenge.used_at.is_(None), MfaChallenge.attempts < 5)
                       .values(attempts=MfaChallenge.attempts + 1))
            record_audit(db, action="auth.mfa", actor_ref="anonymous", result="denied", error_code="UNAUTHENTICATED")
            db.commit()
            raise HubError("UNAUTHENTICATED", "Invalid credentials", 401)
        consumed = db.execute(update(MfaChallenge).where(MfaChallenge.id == challenge.id,
                              MfaChallenge.used_at.is_(None), MfaChallenge.expires_at > utcnow(),
                              MfaChallenge.attempts < 5).values(used_at=utcnow())
                              .execution_options(synchronize_session=False))
        if consumed.rowcount != 1:
            db.rollback()
            raise HubError("UNAUTHENTICATED", "Email code was already used", 401)
        raw, csrf = start_session(db, user)
        record_audit(db, action="auth.login", actor_ref=f"admin:{user.id}", result="success")
        db.commit()
        payload = ok({"user": user_view(user), "csrf_token": csrf})
        write_session_cookie(payload, raw)
        return payload
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
