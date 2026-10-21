"""Admin session dependencies and MCP service-token lookup."""

import hashlib
import hmac
import secrets
from datetime import timedelta

import pyotp
from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import HubError
from app.ids import as_utc, new_id, utcnow
from app.persistence.models import AdminSession, AdminUser, MfaChallenge, ServiceIdentity
from app.persistence.session import get_db
from app.security.crypto import decrypt_secret, sha256_hex
from app.security.passwords import _DUMMY_HASH, verify_password

SESSION_COOKIE = "hub_session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_signing_key, salt="hub-mfa")


def issue_mfa_token(db: Session, user_id: str, purpose: str, *, code: str | None = None,
                    recipient_email: str | None = None) -> str:
    minutes = 10 if purpose in {"email_otp", "activation_code"} else 5
    challenge = MfaChallenge(id=new_id(), user_id=user_id, purpose=purpose,
                             recipient_email=recipient_email, expires_at=utcnow() + timedelta(minutes=minutes))
    if code is not None:
        challenge.code_hash = email_code_hash(challenge.id, code)
    db.add(challenge)
    return _serializer().dumps({"uid": user_id, "purpose": purpose, "nonce": challenge.id})


def email_code_hash(challenge_id: str, code: str) -> str:
    payload = f"{challenge_id}:{code}".encode()
    return hmac.new(get_settings().session_signing_key.encode(), payload, hashlib.sha256).hexdigest()


def read_mfa_token(db: Session, token: str) -> MfaChallenge:
    try:
        payload = _serializer().loads(token, max_age=600)
    except (BadSignature, SignatureExpired) as exc:
        raise HubError("UNAUTHENTICATED", "MFA challenge expired", 401) from exc
    challenge = db.get(MfaChallenge, payload.get("nonce"))
    if challenge is None or challenge.used_at is not None or as_utc(challenge.expires_at) <= utcnow() or challenge.user_id != payload.get("uid") or challenge.purpose != payload.get("purpose"):
        raise HubError("UNAUTHENTICATED", "MFA challenge expired", 401)
    return challenge


def start_session(db: Session, user: AdminUser) -> tuple[str, str]:
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.add(
        AdminSession(
            id=new_id(),
            user_id=user.id,
            token_hash=sha256_hex(raw),
            csrf_token=csrf,
            expires_at=utcnow() + timedelta(hours=settings.session_hours),
        )
    )
    return raw, csrf


def write_session_cookie(response: Response, raw: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(get_settings().cookie_name, path="/")


def _session_from_request(request: Request, db: Session) -> tuple[AdminSession, AdminUser]:
    raw = request.cookies.get(get_settings().cookie_name)
    if not raw:
        raise HubError("UNAUTHENTICATED", "Authentication is required", 401)
    row = db.scalar(select(AdminSession).where(AdminSession.token_hash == sha256_hex(raw)))
    if row is None or as_utc(row.expires_at) < utcnow():
        raise HubError("UNAUTHENTICATED", "Authentication is required", 401)
    user = db.get(AdminUser, row.user_id)
    if user is None or not user.is_active or user.activation_token_hash is not None:
        raise HubError("UNAUTHENTICATED", "Authentication is required", 401)
    return row, user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    _session, user = _session_from_request(request, db)
    return user


def require_csrf(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    session, user = _session_from_request(request, db)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        header = request.headers.get("x-csrf-token", "")
        if not header or not secrets.compare_digest(header, session.csrf_token):
            raise HubError("PERMISSION_DENIED", "CSRF token is missing or invalid", 403)
    return user


def authenticate_password(db: Session, email: str, password: str) -> AdminUser | None:
    user = db.scalar(select(AdminUser).where(AdminUser.email == email.strip().lower()))
    if user is None or not user.is_active:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    return user


def enrollment_deadline(user: AdminUser):
    """When a never-enrolled admin's MFA setup window closes; None until it has started."""

    return as_utc(user.mfa_enroll_until) if user.mfa_enroll_until else None


def enrollment_open(user: AdminUser, hours: int) -> bool:
    """Whether a never-enrolled admin may still set up MFA with a password alone.

    Admins from before the window existed get theirs at the first sign-in that requires MFA, so
    turning MFA_REQUIRED on later does not lock every one of them out.
    """

    if user.mfa_enroll_until is None:
        user.mfa_enroll_until = utcnow() + timedelta(hours=hours)
        return True
    return utcnow() <= as_utc(user.mfa_enroll_until)


def reset_mfa(db: Session, user: AdminUser, hours: int) -> None:
    """Clear the admin's authenticator, sign them out everywhere and open a new enrollment window."""

    from sqlalchemy import delete

    user.mfa_enabled = False
    user.totp_secret_encrypted = None
    user.last_totp_counter = None
    user.mfa_enroll_until = utcnow() + timedelta(hours=hours)
    db.execute(delete(AdminSession).where(AdminSession.user_id == user.id))


def verify_totp(user: AdminUser, code: str) -> int | None:
    if not user.totp_secret_encrypted:
        return None
    secret = decrypt_secret(get_settings().secret_encryption_key, user.totp_secret_encrypted)
    import time
    totp = pyotp.TOTP(secret)
    current = int(time.time()) // totp.interval
    for counter in (current, current - 1, current + 1):
        if (user.last_totp_counter is None or counter > user.last_totp_counter) and secrets.compare_digest(totp.at(counter * totp.interval), code.strip()):
            return counter
    return None


def lookup_service_token(db: Session, token: str) -> ServiceIdentity | None:
    if not token:
        return None
    row = db.scalar(select(ServiceIdentity).where(ServiceIdentity.token_hash == sha256_hex(token)))
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is not None and as_utc(row.expires_at) < utcnow():
        return None
    return row
