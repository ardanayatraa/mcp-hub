"""Administrator passwords: change your own, or set a new one from a one-use reset link.

The root administrator creates a reset link for another administrator (Access → Team); the server
shell creates one for anybody, including root (`python -m app.bootstrap --reset-password EMAIL`).
Only a hash of the link's token is stored. A reset or a change signs the account out everywhere else.
Two-step sign-in is not changed.
"""

import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import HubError
from app.ids import as_utc, utcnow
from app.persistence.models import AdminSession, AdminUser, MfaChallenge
from app.security.audit import record_audit
from app.security.crypto import sha256_hex
from app.security.mailer import activation_url
from app.security.passwords import hash_password, password_is_acceptable, verify_password

PURPOSE = "password_reset"
LINK_HOURS = 24
POLICY = "Use a password of 12+ characters with upper, lower and a digit"


def reset_url(token: str) -> str:
    # The same base and fragment as activation links: the token never reaches server logs.
    return activation_url(token).replace("/activate#", "/reset-password#", 1)


def issue(db: Session, user: AdminUser, *, actor_ref: str) -> tuple[str, str]:
    """A new reset link for `user`; earlier unused links stop working. Returns (url, expires_at)."""

    if not user.is_active or user.activation_token_hash is not None:
        raise HubError("CONFLICT", "Only an active, activated administrator can reset a password", 409)
    db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id, MfaChallenge.purpose == PURPOSE))
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=LINK_HOURS)
    db.add(MfaChallenge(user_id=user.id, purpose=PURPOSE, code_hash=sha256_hex(token), expires_at=expires))
    record_audit(db, action="admin.password_reset", actor_ref=actor_ref, result="success")
    return reset_url(token), as_utc(expires).isoformat()


def _sign_out_elsewhere(db: Session, user: AdminUser, keep: str | None = None) -> None:
    query = delete(AdminSession).where(AdminSession.user_id == user.id)
    if keep is not None:
        query = query.where(AdminSession.id != keep)
    db.execute(query)


def complete(db: Session, token: str, password: str) -> AdminUser:
    challenge = db.scalar(select(MfaChallenge).where(MfaChallenge.purpose == PURPOSE,
                                                     MfaChallenge.code_hash == sha256_hex(token)))
    if challenge is None or challenge.used_at is not None or as_utc(challenge.expires_at) <= utcnow():
        raise HubError("INVALID_RESET_LINK", "This reset link has expired or was already used. Ask root for a new one.", 400)
    user = db.get(AdminUser, challenge.user_id)
    if user is None or not user.is_active or user.activation_token_hash is not None:
        raise HubError("INVALID_RESET_LINK", "This reset link has expired or was already used. Ask root for a new one.", 400)
    if not password_is_acceptable(password):
        raise HubError("VALIDATION_FAILED", POLICY, 422)
    user.password_hash = hash_password(password)
    if user.auth_method == "email_otp":
        user.auth_method = "password"
    challenge.used_at = utcnow()
    _sign_out_elsewhere(db, user)
    record_audit(db, action="auth.password_reset", actor_ref=f"admin:{user.id}", result="success")
    return user


def change(db: Session, user: AdminUser, session_id: str, current: str, new: str) -> None:
    if not verify_password(user.password_hash, current):
        record_audit(db, action="auth.password_change", actor_ref=f"admin:{user.id}", result="denied",
                     error_code="UNAUTHENTICATED")
        raise HubError("UNAUTHENTICATED", "The current password is not correct", 401)
    if not password_is_acceptable(new):
        raise HubError("VALIDATION_FAILED", POLICY, 422)
    if verify_password(user.password_hash, new):
        raise HubError("VALIDATION_FAILED", "Choose a password different from the current one", 422)
    user.password_hash = hash_password(new)
    db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id, MfaChallenge.purpose == PURPOSE))
    _sign_out_elsewhere(db, user, keep=session_id)
    record_audit(db, action="auth.password_change", actor_ref=f"admin:{user.id}", result="success")
