"""Runtime settings in the admin UI: hub admins read them, the root administrator changes them."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.config import get_settings
from app.errors import HubError
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import ADMIN_ROLES, require_role, require_root
from app.security.mailer import send_email
from app.security.rate_limit import hit
from app.services import runtime_settings

router = APIRouter(prefix="/hub-settings", tags=["settings"])


@router.get("")
def show(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    settings = get_settings()
    runtime_settings.refresh(settings, db, force=True)
    return ok(runtime_settings.view(db, settings))


@router.patch("")
def change(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_root(user)
    settings = get_settings()
    runtime_settings.update(db, user, payload, settings)
    db.commit()
    return ok(runtime_settings.view(db, settings))


@router.post("/test-email")
def test_email(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    """Send a short message to the signed-in root administrator with the current email settings."""

    require_root(user)
    if not user.email:
        raise HubError("VALIDATION_FAILED", "Your account has no email address", 422)
    hit(f"email-test:{user.id}", 3, 300)
    send_email(user.email, "MCP Hub test email", "This is a test from MCP Hub. Email delivery works.\n")
    record_audit(db, action="settings.email_test", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok({"sent_to": user.email})
