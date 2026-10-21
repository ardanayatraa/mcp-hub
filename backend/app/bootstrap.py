"""Create the initial administrator. The password is read from the environment."""

import sys
from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.ids import new_id, utcnow
from app.persistence.models import AdminUser
from app.persistence.session import init_engine, open_session
from app.security.passwords import hash_password, password_is_acceptable


def seed_admin() -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    db = open_session()
    try:
        email = settings.admin_initial_email.strip().lower()
        existing = db.scalar(select(AdminUser).where(AdminUser.email == email))
        if existing is not None:
            print("admin already exists")
            return
        password = settings.admin_initial_password
        if not password_is_acceptable(password):
            raise SystemExit("ADMIN_INITIAL_PASSWORD must be at least 12 characters and include upper, lower, and a digit")
        first_root = db.scalar(select(AdminUser.id).where(AdminUser.is_root.is_(True))) is None
        db.add(
            AdminUser(
                id=new_id(),
                email=email,
                password_hash=hash_password(password),
                role="super_admin" if first_root else "hub_admin",
                is_root=first_root,
                mfa_enabled=False,
                mfa_enroll_until=utcnow() + timedelta(hours=settings.mfa_enroll_hours),
            )
        )
        db.commit()
        print("admin created")
    finally:
        db.close()


def reset_admin_mfa(email: str) -> None:
    """Recovery from the server shell: clear an admin's MFA and open a new enrollment window."""

    from app.security.audit import record_audit
    from app.security.auth import reset_mfa

    settings = get_settings()
    init_engine(settings.database_url)
    db = open_session()
    try:
        user = db.scalar(select(AdminUser).where(AdminUser.email == email.strip().lower()))
        if user is None:
            raise SystemExit("no admin with that email")
        reset_mfa(db, user, settings.mfa_enroll_hours)
        record_audit(db, action="admin.mfa_reset", actor_ref="system:cli", result="success")
        db.commit()
        print(f"two-factor sign-in reset; enroll within {settings.mfa_enroll_hours} hours")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--reset-mfa":
        reset_admin_mfa(sys.argv[2])
    elif len(sys.argv) == 1:
        seed_admin()
    else:
        raise SystemExit("usage: python -m app.bootstrap [--reset-mfa EMAIL]")
