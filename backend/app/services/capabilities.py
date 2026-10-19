"""What this MCP Hub can do right now: protocol, limits, report features and a per-app matrix."""

import importlib.metadata
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings
from app.ids import utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    AuditEvent,
    ChatSetting,
    Connector,
    MemorySetting,
    ModuleDefinition,
    ModuleSetting,
    ServiceIdentity,
    Skill,
    ToolDefinition,
    ToolSwitch,
)
from app.security.authorization import allowed_app_ids
from app.security.clients import WRITE_SCOPE
from app.services.tool_cards import kind
from app.tools import catalog, memory, report_engine

KINDS = ("list", "count", "get", "read", "report", "create", "update", "delete")


def _in_scope(query, column, allowed: set[str] | None):
    return query if allowed is None else query.where(column.in_(allowed))


def capabilities(db: Session, admin: AdminUser, settings: Settings) -> dict:
    allowed = allowed_app_ids(db, admin)
    apps = list(db.execute(_in_scope(select(Connector, Application).join(Application, Application.id == Connector.app_id)
                                     .where(Connector.status != "archived").order_by(Application.name), Application.id, allowed)))
    app_ids = [application.id for _connector, application in apps]
    connector_ids = [connector.id for connector, _application in apps]
    tools = list(db.scalars(select(ToolDefinition).where(ToolDefinition.connector_id.in_(connector_ids),
                                                         ToolDefinition.status != "archived")))
    off = set(db.execute(select(ToolSwitch.app_id, ToolSwitch.tool_name).where(ToolSwitch.app_id.in_(app_ids))).all())
    sources = dict(db.execute(select(ModuleDefinition.app_id, func.count()).join(ModuleSetting, ModuleSetting.module_id == ModuleDefinition.id)
                              .where(ModuleDefinition.app_id.in_(app_ids), ModuleSetting.enabled.is_(True))
                              .group_by(ModuleDefinition.app_id)).all())
    skills = dict(db.execute(select(Skill.app_id, func.count()).where(Skill.app_id.in_(app_ids), Skill.enabled.is_(True))
                             .group_by(Skill.app_id)).all())
    memory_on = set(db.scalars(select(MemorySetting.app_id).where(MemorySetting.app_id.in_(app_ids), MemorySetting.enabled.is_(True))))
    chats = {row.app_id: row for row in db.scalars(select(ChatSetting).where(ChatSetting.app_id.in_(app_ids)))}
    keys = list(db.scalars(select(ServiceIdentity).where(ServiceIdentity.app_id.in_(app_ids), ServiceIdentity.revoked_at.is_(None))))

    matrix = []
    by_kind: Counter = Counter()
    for connector, application in apps:
        mine = [tool for tool in tools if tool.connector_id == connector.id]
        live = [tool for tool in mine if tool.status == "published" and (application.id, tool.mcp_name) not in off]
        counts = Counter(kind(tool.template, tool.tool_key) for tool in live)
        by_kind.update(counts)
        chat = chats.get(application.id)
        matrix.append({
            "connector_id": connector.id, "name": application.name, "app_key": application.key, "status": connector.status,
            "mode": connector.connector_type, "sources_on": sources.get(application.id, 0),
            "tools_total": len(mine), "tools_live": len(live), "switched_off": sum(1 for app_id, _ in off if app_id == application.id),
            "kinds": {name: counts.get(name, 0) for name in KINDS},
            "skills": skills.get(application.id, 0), "memory": application.id in memory_on,
            "chat": bool(chat and chat.enabled), "chat_model": f"{chat.provider} · {chat.model}" if chat and chat.enabled else None,
        })

    since = utcnow() - timedelta(days=7)
    keys_in_use = {*(tool.tool_key for tool in tools), *catalog.HUB_TOOL_NAMES}
    calls = select(AuditEvent.tool_key, func.count()).where(
        AuditEvent.action == "tool.execute", AuditEvent.created_at >= since, AuditEvent.tool_key.in_(keys_in_use))
    if allowed is not None:  # scoped admins count only their own apps' calls
        calls = calls.where(AuditEvent.app_key.in_([application.key for _connector, application in apps]))
    usage = dict(db.execute(calls.group_by(AuditEvent.tool_key)).all())

    try:
        sdk = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        sdk = "unknown"
    return {
        "version": __version__,
        "protocol": {
            "endpoint": settings.mcp_public_url, "transport": "Streamable HTTP, stateless JSON responses",
            "methods": ["initialize", "tools/list", "tools/call", "prompts/list", "prompts/get"],
            "auth": "Authorization: Bearer <client key>", "user_context": "X-Hub-Delegation, signed by the app, valid up to 150 seconds",
            "app_auth": "Authorization: Bearer <app token>, plus X-Hub-Assertion for the signed-in user",
            "chat": "/chat/v1/config and /chat/v1/turn (Server-Sent Events)", "sdk": f"Official MCP Python SDK {sdk}",
        },
        "summary": {
            "apps": len(apps), "apps_active": sum(1 for connector, _ in apps if connector.status == "active"),
            "data_sources_on": sum(sources.values()),
            "tools_total": len(tools) + len(catalog.BUILTINS) + len(memory.TOOLS),
            "tools_live": sum(row["tools_live"] for row in matrix) + len(catalog.BUILTINS),
            "by_kind": {name: by_kind.get(name, 0) for name in KINDS},
            "skills": sum(skills.values()), "memory_apps": len(memory_on), "chat_apps": sum(1 for row in matrix if row["chat"]),
            "switched_off": len(off), "client_keys": len(keys),
            "write_keys": sum(1 for key in keys if WRITE_SCOPE in (key.scopes or [])),
        },
        "report": {
            "filters": list(report_engine.FILTER_OPS), "metrics": list(report_engine.METRIC_FUNCTIONS),
            "intervals": list(report_engine.INTERVALS), "max_group_by": 2, "max_metrics": 6, "max_filters": 10,
            "max_rows": report_engine.MAX_LIMIT, "max_records_read": settings.report_max_records,
            "timeout_seconds": settings.report_timeout_seconds,
        },
        "limits": {
            "tool_calls": f"{settings.tool_rate_limit} per {settings.tool_rate_window_seconds} s per client key and tool",
            "page_size": settings.max_records, "chat_messages": f"{settings.chat_rate_limit} per minute per user",
            "payload_bytes": settings.max_payload_bytes,
        },
        "apps": matrix,
        "usage": usage,
    }
