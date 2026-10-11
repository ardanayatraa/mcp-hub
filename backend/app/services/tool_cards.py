"""Readable names for tool keys in the activity log and dashboards, and a tool's own usage."""

import math
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.ids import as_utc, utcnow
from app.persistence.models import (
    Application,
    AuditEvent,
    Connector,
    ModuleDefinition,
    ToolDefinition,
)
from app.tools import catalog, memory
from app.tools.definitions import WRITE_TEMPLATES

HUB_TITLES = {catalog.LIST_SOURCES: "List data sources", catalog.RUN_REPORT: "Run report",
              memory.RECALL: "Recall memory", memory.SAVE: "Save memory", memory.FORGET: "Forget memory"}


def kind(template: str, tool_key: str) -> str:
    """What the tool does, for its icon: list, count, get, report, create, update, delete or read."""

    if template == "report":
        return "report"
    if template in WRITE_TEMPLATES:
        return template
    action = tool_key.rsplit(".", 1)[-1]
    return action if action in {"list", "count", "get"} else "read"


def cards(db: Session, keys: Iterable[str | None]) -> dict[str, dict]:
    """Tool key (or MCP name) -> {tool_id, title, kind, app_name, module_name, mcp_name, status}."""

    wanted = {key for key in keys if key}
    found: dict[str, dict] = {}
    for key in wanted & set(HUB_TITLES):
        found[key] = {"tool_id": None, "title": HUB_TITLES[key], "kind": "memory" if key in memory.NAMES else "hub",
                      "app_name": None, "module_name": None, "mcp_name": key, "status": "published"}
    rest = wanted - set(found)
    if not rest:
        return found
    rows = db.execute(
        select(ToolDefinition, Application.name, ModuleDefinition.name)
        .join(Connector, Connector.id == ToolDefinition.connector_id)
        .join(Application, Application.id == Connector.app_id)
        .outerjoin(ModuleDefinition, (ModuleDefinition.app_id == Application.id)
                   & (ModuleDefinition.module_key == ToolDefinition.module_key))
        .where(or_(ToolDefinition.tool_key.in_(rest), ToolDefinition.mcp_name.in_(rest)))
        .order_by(ToolDefinition.created_at))
    for tool, app_name, module_name in rows:
        card = {"tool_id": tool.id, "title": catalog.tool_title(tool), "kind": kind(tool.template, tool.tool_key),
                "app_name": app_name, "module_name": module_name or tool.module_key, "mcp_name": tool.mcp_name,
                "status": tool.status}
        # The newest definition of a key wins; archived ones only when nothing newer exists.
        for key in (tool.tool_key, tool.mcp_name):
            if key in rest and (key not in found or tool.status != "archived"):
                found[key] = card
    return found


def usage(db: Session, tool: ToolDefinition, days: int = 7) -> dict:
    """Calls of one tool over the last days: totals, success rate, latency and a daily series."""

    now = utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    calls = select(AuditEvent).where(AuditEvent.action == "tool.execute", AuditEvent.created_at >= start,
                                     AuditEvent.tool_key.in_({tool.tool_key, tool.mcp_name}))
    total, success, denied = db.execute(calls.with_only_columns(
        func.count(AuditEvent.id),
        func.coalesce(func.sum(case((AuditEvent.result == "success", 1), else_=0)), 0),
        func.coalesce(func.sum(case((AuditEvent.result == "denied", 1), else_=0)), 0))).one()
    duration = func.coalesce(AuditEvent.duration_ms, 0)
    p95 = db.scalar(calls.with_only_columns(duration).order_by(duration)
                    .offset(max(0, math.ceil(total * 0.95) - 1)).limit(1)) if total else None
    average = db.scalar(calls.with_only_columns(func.avg(duration))) if total else None
    last = db.scalar(select(func.max(AuditEvent.created_at)).where(
        AuditEvent.action == "tool.execute", AuditEvent.tool_key.in_({tool.tool_key, tool.mcp_name})))
    per_day = {(start + timedelta(days=offset)).date().isoformat(): {"calls": 0, "failed": 0} for offset in range(days)}
    for created, result in db.execute(calls.with_only_columns(AuditEvent.created_at, AuditEvent.result)):
        bucket = per_day.get(as_utc(created).date().isoformat())
        if bucket is not None:
            bucket["calls"] += 1
            bucket["failed"] += 0 if result == "success" else 1
    return {"days": days, "calls": total, "success": success, "denied": denied, "failed": total - success,
            "success_rate": (success / total) if total else None, "p95_ms": p95,
            "avg_ms": round(average) if average is not None else None,
            "last_used_at": as_utc(last).isoformat() if last else None,
            "series": [{"day": day, **counts} for day, counts in per_day.items()]}
