"""Hub settings the UI shows, plus super-admin backup, restore and retention."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import __version__
from app.api.v1.common import ok
from app.config import get_settings
from app.ids import utcnow
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import ADMIN_ROLES, require_role, require_root
from app.services import runtime_settings
from app.services.backup import (
    export_metadata,
    import_metadata,
    key_fingerprint,
    open_backup,
    purge_expired,
    seal,
)

router = APIRouter(tags=["system"])


@router.get("/system")
def system(user: AdminUser = Depends(require_csrf)):
    """Non-secret settings: where clients connect and which limits apply."""

    del user
    settings = get_settings()
    return ok({
        "version": __version__,
        "environment": settings.environment,
        "mcp_url": settings.mcp_public_url,
        # Which key opens this Hub's backups: a one-way label, never the key.
        "backup_key_fingerprint": key_fingerprint(settings.secret_encryption_key),
        "limits": {"records_per_call": settings.max_records, "report_max_records": settings.report_max_records,
                   "report_timeout_seconds": settings.report_timeout_seconds,
                   "tool_rate_limit": settings.tool_rate_limit, "tool_rate_window_seconds": settings.tool_rate_window_seconds,
                   "audit_retention_days": settings.audit_retention_days},
        "security": {"mfa_required": settings.mfa_required, "secure_cookies": settings.cookie_secure,
                     "email_delivery_ready": settings.smtp_configured,
                     "egress_allowlist": bool(settings.egress_allowed_hosts or settings.egress_allowed_cidrs),
                     "insecure_http_allowed": settings.allow_insecure_http,
                     "private_egress_allowed": settings.egress_allow_private or settings.egress_allow_loopback},
    })


@router.post("/operations/export")
def export_route(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    sealed = seal(export_metadata(db), get_settings().secret_encryption_key, version=__version__, created_at=utcnow())
    record_audit(db, action="backup.export", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok(sealed)


@router.post("/operations/import")
def import_route(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    # Restoring app metadata also replaces per-user app scopes.
    require_root(user)
    counts = import_metadata(db, open_backup(payload, get_settings().secret_encryption_key))
    record_audit(db, action="backup.import", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    runtime_settings.refresh(get_settings(), db, force=True)  # restored settings take effect at once
    return ok(counts)


@router.post("/operations/purge")
def purge(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    removed = purge_expired(db, get_settings().audit_retention_days)
    record_audit(db, action="backup.purge", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok({"removed": removed})
