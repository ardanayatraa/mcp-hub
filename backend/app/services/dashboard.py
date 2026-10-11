"""Overview numbers. The queries read metadata only, never tool payloads."""

import math
from datetime import datetime, timedelta

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.orm import Session

from app.ids import as_utc, utcnow
from app.persistence.models import (
    Application,
    AuditEvent,
    Connector,
    ConnectorHealthCheck,
    ModuleDefinition,
    ModuleSetting,
    ServiceIdentity,
    ToolDefinition,
)
from app.services import tool_cards

TOOL_ACTIONS = {"tool.execute", "tool.switch_on", "tool.switch_off"}


def event_view(event: AuditEvent, cards: dict | None = None) -> dict:
    return {
        "trace_id": event.trace_id, "action": event.action, "actor_ref": event.actor_ref, "app_key": event.app_key,
        "module_key": event.module_key, "tool_key": event.tool_key, "environment": event.environment,
        "result": event.result, "error_code": event.error_code, "duration_ms": event.duration_ms,
        "retry_count": event.retry_count, "created_at": as_utc(event.created_at).isoformat(),
        # A readable name and a link for events about a tool.
        "tool": (cards or {}).get(event.tool_key) if event.action in TOOL_ACTIONS else None,
    }


def events_view(db: Session, events) -> list[dict]:
    rows = list(events)
    named = tool_cards.cards(db, (event.tool_key for event in rows if event.action in TOOL_ACTIONS))
    return [event_view(event, named) for event in rows]


def scoped_events(query, environment: str | None, app_ids: set[str] | None):
    if environment:
        query = query.where(AuditEvent.environment == environment)
    if app_ids is not None:
        scopes = select(Application.key, Application.environment).where(Application.id.in_(app_ids))
        query = query.where(tuple_(AuditEvent.app_key, AuditEvent.environment).in_(scopes))
    return query


SERIES_STEPS = (timedelta(hours=1), timedelta(hours=3), timedelta(hours=6), timedelta(hours=12), timedelta(days=1),
                timedelta(days=7))
SERIES_MAX_POINTS = 48


def call_series(db: Session, calls, start: datetime, end: datetime) -> list[dict]:
    """Calls and unsuccessful calls per time bucket, aggregated in one query over the window."""

    span = max(end - start, timedelta(hours=1))
    step = next((item for item in SERIES_STEPS if span / item <= SERIES_MAX_POINTS), SERIES_STEPS[-1])
    # Rounded so a window a few microseconds over 24 hours still gives 24 buckets.
    edges = [start + step * index for index in range(max(1, math.ceil(round(span / step, 3))) + 1)]
    columns = []
    for low, high in zip(edges, edges[1:]):
        # The last bucket is open-ended: the outer query already stops at the window's end.
        inside = (AuditEvent.created_at >= low) & (AuditEvent.created_at < high) if high != edges[-1] \
            else AuditEvent.created_at >= low
        columns.append(func.coalesce(func.sum(case((inside, 1), else_=0)), 0))
        columns.append(func.coalesce(func.sum(case((inside & (AuditEvent.result != "success"), 1), else_=0)), 0))
    values = db.execute(calls.with_only_columns(*columns)).one()
    return [{"start": as_utc(low).isoformat(), "calls": values[index * 2], "failed": values[index * 2 + 1]}
            for index, low in enumerate(edges[:-1])]


def summary(db: Session, *, environment: str | None, start: datetime | None, end: datetime | None,
            app_ids: set[str] | None = None) -> dict:
    start = start or (utcnow() - timedelta(days=1))
    end = end or utcnow()
    connector_query = select(Connector, Application).join(Application, Application.id == Connector.app_id)
    if environment:
        connector_query = connector_query.where(Application.environment == environment)
    if app_ids is not None:
        connector_query = connector_query.where(Application.id.in_(app_ids))
    connectors = list(db.execute(connector_query))
    failing = 0
    for connector, _app in connectors:
        health = db.scalar(select(ConnectorHealthCheck.status).where(ConnectorHealthCheck.connector_id == connector.id)
                           .order_by(ConnectorHealthCheck.created_at.desc()).limit(1))
        failing += int(connector.status != "archived" and (connector.failure_count > 0 or health == "fail"))
    selected_apps = [app.id for _connector, app in connectors]
    selected_connectors = [connector.id for connector, _app in connectors]
    enabled_sources = db.scalar(select(func.count()).select_from(ModuleSetting)
                                .join(ModuleDefinition, ModuleDefinition.id == ModuleSetting.module_id)
                                .where(ModuleSetting.enabled.is_(True), ModuleDefinition.app_id.in_(selected_apps))) or 0
    tool_counts = dict(db.execute(select(ToolDefinition.status, func.count())
                                  .where(ToolDefinition.connector_id.in_(selected_connectors))
                                  .group_by(ToolDefinition.status)).all())
    keys_active = db.scalar(select(func.count()).select_from(ServiceIdentity).where(
        ServiceIdentity.app_id.in_(selected_apps), ServiceIdentity.revoked_at.is_(None),
        (ServiceIdentity.expires_at.is_(None)) | (ServiceIdentity.expires_at > utcnow()))) or 0
    calls = scoped_events(select(AuditEvent).where(AuditEvent.created_at >= start, AuditEvent.created_at <= end,
                                                   AuditEvent.action == "tool.execute"), environment, app_ids)
    total, success, denied, retries = db.execute(calls.with_only_columns(
        func.count(AuditEvent.id),
        func.coalesce(func.sum(case((AuditEvent.result == "success", 1), else_=0)), 0),
        func.coalesce(func.sum(case((AuditEvent.result == "denied", 1), else_=0)), 0),
        func.coalesce(func.sum(AuditEvent.retry_count), 0),
    )).one()
    duration = func.coalesce(AuditEvent.duration_ms, 0)
    p95 = db.scalar(calls.with_only_columns(duration).order_by(duration)
                    .offset(max(0, math.ceil(total * 0.95) - 1)).limit(1)) if total else 0
    top = db.execute(calls.with_only_columns(AuditEvent.tool_key, func.count(AuditEvent.id))
                     .group_by(AuditEvent.tool_key).order_by(func.count(AuditEvent.id).desc()).limit(5)).all()
    # Sign-ins stay in the activity log; the overview shows calls and configuration changes.
    recent = db.scalars(scoped_events(select(AuditEvent).where(AuditEvent.action.not_like("auth.%")), environment, app_ids)
                        .order_by(AuditEvent.created_at.desc()).limit(8))
    named = tool_cards.cards(db, (key for key, _count in top))
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "environment": environment,
        "apps_total": sum(1 for connector, _app in connectors if connector.status != "archived"),
        "connectors_active": sum(1 for connector, _app in connectors if connector.status == "active"),
        "connectors_failing": failing,
        "modules_enabled": enabled_sources,
        "tools_published": tool_counts.get("published", 0),
        "tools_draft": tool_counts.get("draft", 0),
        "keys_active": keys_active,
        "executions": total,
        "success": success,
        "denied": denied,
        "failure": total - success,
        "success_rate": (success / total) if total else None,
        "latency_p95_ms": p95,
        "retries": retries,
        "top_tools": [{"tool_key": key or "unknown", "calls": count, "tool": named.get(key)} for key, count in top],
        "series": call_series(db, calls, start, end),
        "recent": events_view(db, recent),
        "checklist": {
            "app_connected": any(connector.status == "active" for connector, _app in connectors),
            "source_enabled": enabled_sources > 0,
            "tool_published": tool_counts.get("published", 0) > 0,
            "key_created": keys_active > 0,
        },
    }
