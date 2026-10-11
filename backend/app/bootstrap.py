"""Create the initial administrator. The password is read from the environment."""

from sqlalchemy import select

from app.config import get_settings
from app.ids import new_id
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
        db.add(
            AdminUser(
                id=new_id(),
                email=email,
                password_hash=hash_password(password),
                role="super_admin",
                mfa_enabled=False,
            )
        )
        db.commit()
        print("admin created")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
