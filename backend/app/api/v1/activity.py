"""Overview numbers and the audit log. Metadata only; payloads are never stored."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.errors import HubError
from app.ids import utcnow
from app.persistence.models import AdminUser, AuditEvent
from app.persistence.session import get_db
from app.security.auth import require_csrf
from app.security.authorization import allowed_app_ids
from app.services.dashboard import events_view, scoped_events, summary

router = APIRouter(tags=["activity"])
PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("naive time")
        return parsed
    except ValueError as exc:
        raise HubError("VALIDATION_FAILED", "Time filter must use an ISO timestamp with timezone", 422) from exc


def _window(period: str | None, from_time: str | None, to_time: str | None) -> tuple[datetime | None, datetime | None]:
    if period:
        if period not in PERIODS:
            raise HubError("VALIDATION_FAILED", "Period must be 24h, 7d or 30d", 422)
        return utcnow() - PERIODS[period], None
    return _parse(from_time), _parse(to_time)


@router.get("/executions")
def executions(trace_id: str | None = None, environment: str | None = None, tool_key: str | None = None,
               app_key: str | None = None, result: str | None = None, kind: str | None = None,
               period: str | None = None, from_time: str | None = None, to_time: str | None = None,
               before: str | None = None, limit: int = 100,
               db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    start, end = _window(period, from_time, to_time)
    query = scoped_events(select(AuditEvent), environment, allowed_app_ids(db, user))
    if trace_id:
        query = query.where(AuditEvent.trace_id == trace_id)
    if tool_key:
        query = query.where(or_(AuditEvent.tool_key == tool_key, AuditEvent.tool_key.like(f"%{tool_key[:80]}%")))
    if app_key:
        query = query.where(AuditEvent.app_key == app_key)
    if result:
        query = query.where(AuditEvent.result == result)
    if kind == "calls":
        query = query.where(AuditEvent.action == "tool.execute")
    elif kind == "admin":
        query = query.where(AuditEvent.action != "tool.execute")
    if start:
        query = query.where(AuditEvent.created_at >= start)
    if end:
        query = query.where(AuditEvent.created_at <= end)
    cursor = _parse(before)
    if cursor:
        query = query.where(AuditEvent.created_at < cursor)
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc()).limit(max(1, min(limit, 200))))
    return ok(events_view(db, rows))


@router.get("/dashboard")
def dashboard(environment: str | None = None, period: str | None = None, from_time: str | None = None,
              to_time: str | None = None, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    start, end = _window(period, from_time, to_time)
    return ok(summary(db, environment=environment, start=start, end=end, app_ids=allowed_app_ids(db, user)))
