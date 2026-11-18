"""The monitoring board: every AI client, the checks a request meets, and where traffic went.

Built from the audit rows the activity log shows, so it is metadata only: no request bodies,
results or user identities.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.chat import registry
from app.config import Settings
from app.ids import as_utc, utcnow
from app.persistence.models import (
    Application,
    AuditEvent,
    ChatSetting,
    Connector,
    ConnectorHealthCheck,
    McpAccessProfile,
    ModuleDefinition,
    ModuleSetting,
    ServiceIdentity,
    ToolDefinition,
)
from app.security.clients import WRITE_SCOPE
from app.services import tool_cards
from app.services.dashboard import scoped_events
from app.tools import catalog, memory

WINDOWS = {"5m": 300, "1h": 3600, "24h": 86400}
# A client or app with traffic this recently is shown as live.
LIVE_SECONDS = 300
EVENT_LIMIT = 60
KINDS = {"tool.execute": "tool", "chat.turn": "chat", "model.chat": "model", "skill.use": "skill"}
# The checks in the order a request meets them, and the error codes each one answers with. The audit
# log keeps the code, not the sentence, so a refusal by the connected app counts under permissions.
GATES = {
    "key": ("UNAUTHENTICATED",),
    "privacy": ("PII_DETECTED", "VALIDATION_FAILED", "PRIVILEGE_ESCALATION", "INVALID_JSON"),
    "permissions": ("PERMISSION_DENIED", "TOOL_DISABLED", "MODULE_DISABLED", "TOOL_NOT_PUBLISHED", "UNKNOWN_TOOL",
                    "NOT_FOUND", "NOT_SUPPORTED", "POLICY_LOCKED", "CONFLICT", "CONNECTOR_INACTIVE", "CHAT_DISABLED",
                    "MODEL_NOT_ALLOWED", "MODEL_ACCESS_UNCONFIGURED", "TOKEN_BUDGET_UNCONFIGURED"),
    "limits": ("RATE_LIMITED", "DAILY_LIMIT", "BUDGET_EXCEEDED", "UNAVAILABLE"),
}
STOPS = {code: gate for gate, codes in GATES.items() for code in codes}
APP_FAILURES = {"SCHEMA_MISMATCH", "SSRF_BLOCKED", "CONNECTOR_DNS", "SECRET_UNAVAILABLE", "PAYLOAD_TOO_LARGE"}
# Tools the Hub answers without calling the connected app.
HUB_ANSWERED = {catalog.LIST_SOURCES, *memory.NAMES, "unrecognized"}
UNKNOWN, PREVIEW = "unknown", "preview"


def stopped_at(result: str, code: str | None) -> str | None:
    """None for a success; otherwise the gate that refused, or where the request failed after the gates."""

    if result == "success":
        return None
    code = code or ""
    if code in STOPS:
        return STOPS[code]
    if code in APP_FAILURES or code.startswith("UPSTREAM_"):
        return "app"
    if code.startswith("MODEL_") or code == "CHAT_NOT_CONFIGURED":
        return "model"
    return "hub"


def destination(action: str, tool_key: str | None) -> str:
    if action in ("chat.turn", "model.chat"):
        return "model"
    return "hub" if action == "skill.use" or tool_key in HUB_ANSWERED else "app"


def _iso(value: datetime | None) -> str | None:
    return as_utc(value).isoformat() if value else None


def _client_id(actor: str, app_id: str | None, key_ids: set[str]) -> str | None:
    """The board node a request starts from, or None for a caller the board does not show."""

    kind, _, ref = actor.partition(":")
    if kind == "service" and ref in key_ids and app_id is not None:
        return ref
    if actor == "service:unknown":
        return UNKNOWN
    return PREVIEW if kind == "admin" and app_id is not None else None


def _tally() -> dict:
    return {"requests": 0, "blocked": 0, "failed": 0, "last": None}


def _count(stats: dict, key: str, count: int, last: datetime, *, blocked: bool = False, failed: bool = False) -> None:
    row = stats.setdefault(key, _tally())
    row["requests"] += count
    row["blocked"] += count if blocked else 0
    row["failed"] += count if failed else 0
    row["last"] = last if row["last"] is None else max(row["last"], last)


def _numbers(stats: dict | None) -> dict:
    stats = stats or _tally()
    return {"requests": stats["requests"], "blocked": stats["blocked"], "failed": stats["failed"],
            "last_seen_at": _iso(stats["last"])}


def _key_off_reason(key: ServiceIdentity, profiles: dict, connector: Connector, application: Application,
                    now: datetime) -> str | None:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and as_utc(key.expires_at) <= now:
        return "expired"
    if key.profile_id and not getattr(profiles.get(key.profile_id), "enabled", False):
        return "profile_off"
    return "app_off" if connector.status != "active" or application.status != "active" else None


def snapshot(db: Session, settings: Settings, *, window: str, app_ids: set[str] | None) -> dict:
    now = utcnow()
    seconds = WINDOWS[window]
    start, live_from = now - timedelta(seconds=seconds), now - timedelta(seconds=LIVE_SECONDS)

    def live(stats: dict | None) -> bool:
        return bool(stats and stats["last"] and stats["last"] >= live_from)

    query = (select(Connector, Application).join(Application, Application.id == Connector.app_id)
             .where(Connector.status != "archived").order_by(Application.name, Application.environment))
    if app_ids is not None:
        query = query.where(Application.id.in_(app_ids))
    pairs = list(db.execute(query))
    by_app = {application.id: (connector, application) for connector, application in pairs}
    by_key = {(application.key, application.environment): application.id for _connector, application in pairs}
    visible, connector_ids = list(by_app), [connector.id for connector, _application in pairs]

    tools = dict(db.execute(select(ToolDefinition.connector_id, func.count())
                            .where(ToolDefinition.status == "published", ToolDefinition.connector_id.in_(connector_ids))
                            .group_by(ToolDefinition.connector_id)).all())
    sources = dict(db.execute(select(ModuleDefinition.app_id, func.count())
                              .join(ModuleSetting, ModuleSetting.module_id == ModuleDefinition.id)
                              .where(ModuleSetting.enabled.is_(True), ModuleDefinition.app_id.in_(visible))
                              .group_by(ModuleDefinition.app_id)).all())
    chats = {row.app_id: row for row in db.scalars(select(ChatSetting).where(ChatSetting.app_id.in_(visible)))}
    latest = (select(ConnectorHealthCheck.connector_id, func.max(ConnectorHealthCheck.created_at).label("at"))
              .where(ConnectorHealthCheck.connector_id.in_(connector_ids))
              .group_by(ConnectorHealthCheck.connector_id).subquery())
    health = {row.connector_id: row for row in db.scalars(
        select(ConnectorHealthCheck).join(latest, (ConnectorHealthCheck.connector_id == latest.c.connector_id)
                                          & (ConnectorHealthCheck.created_at == latest.c.at)))}
    keys = list(db.scalars(select(ServiceIdentity).where(ServiceIdentity.app_id.in_(visible))
                           .order_by(ServiceIdentity.created_at)))
    key_ids = {key.id for key in keys}
    profiles = {row.id: row for row in db.scalars(select(McpAccessProfile).where(McpAccessProfile.app_id.in_(visible)))}

    def provider_of(action: str, tool_key: str | None, app_id: str | None) -> str | None:
        if action == "model.chat":
            return (tool_key or "").split("/", 1)[0] or None
        chat = chats.get(app_id)
        return chat.provider if chat else None

    traffic = scoped_events(select(AuditEvent).where(AuditEvent.created_at >= start, AuditEvent.action.in_(KINDS)),
                            None, app_ids)
    columns = (AuditEvent.actor_ref, AuditEvent.app_key, AuditEvent.environment, AuditEvent.action,
               AuditEvent.tool_key, AuditEvent.result, AuditEvent.error_code)
    totals = {"requests": 0, "passed": 0, "blocked": 0, "failed": 0}
    gate_stats = {gate: {"stopped": 0, "codes": {}} for gate in GATES}
    client_stats: dict[str, dict] = {}
    app_stats: dict[str, dict] = {}
    model_stats: dict[str, dict] = {}
    answered = 0
    for actor, app_key, environment, action, tool_key, result, code, count, last in db.execute(
            traffic.with_only_columns(*columns, func.count(AuditEvent.id), func.max(AuditEvent.created_at))
            .group_by(*columns)):
        app_id = by_key.get((app_key, environment))
        client = _client_id(actor, app_id, key_ids)
        if client is None:
            continue
        stop, last = stopped_at(result, code), as_utc(last)
        totals["requests"] += count
        if stop in GATES:
            totals["blocked"] += count
            gate_stats[stop]["stopped"] += count
            gate_stats[stop]["codes"][code] = gate_stats[stop]["codes"].get(code, 0) + count
            _count(client_stats, client, count, last, blocked=True)
            continue
        totals["passed" if stop is None else "failed"] += count
        _count(client_stats, client, count, last, failed=stop is not None)
        target = stop if stop in ("app", "model") else destination(action, tool_key)
        provider = provider_of(action, tool_key, app_id) if target == "model" else None
        if target == "app" and app_id is not None:
            _count(app_stats, app_id, count, last, failed=stop is not None)
        elif provider:
            _count(model_stats, provider, count, last, failed=stop is not None)
        elif stop is None:
            answered += count

    clients = []
    for key in keys:
        connector, application = by_app[key.app_id]
        stats = client_stats.get(key.id)
        reason = _key_off_reason(key, profiles, connector, application, now)
        if key.revoked_at is not None and stats is None:
            continue  # Keys revoked long ago stay out of the picture.
        profile = profiles.get(key.profile_id) if key.profile_id else None
        clients.append({
            "id": key.id, "kind": "key", "name": key.name, "app": connector.id, "app_name": application.name,
            "state": "off" if reason else ("live" if live(stats) else "on"), "reason": reason,
            "can_write": WRITE_SCOPE in (key.scopes or []), "profile": profile.name if profile else None,
            "last_used_at": _iso(key.last_used_at), **_numbers(stats)})
    for pseudo, name in ((PREVIEW, "Admin preview"), (UNKNOWN, "Unknown key")):
        stats = client_stats.get(pseudo)
        if stats is None:
            continue
        # A caller without a valid key is never "on": it is shown so its refused requests have a start.
        state = "off" if pseudo == UNKNOWN else ("live" if live(stats) else "on")
        clients.append({"id": pseudo, "kind": pseudo, "name": name, "app": None, "app_name": None, "state": state,
                        "reason": "not_recognized" if pseudo == UNKNOWN else None, "can_write": False, "profile": None,
                        "last_used_at": None, **_numbers(stats)})

    apps = []
    for connector, application in pairs:
        stats, check = app_stats.get(application.id), health.get(connector.id)
        circuit = connector.circuit_open_until is not None and as_utc(connector.circuit_open_until) > now
        if connector.status != "active" or application.status != "active":
            state = "off"
            reason = {"paused": "paused", "draft": "setup"}.get(connector.status, "inactive")
        elif circuit or connector.failure_count > 0 or (check is not None and check.status == "fail"):
            state, reason = "warn", "circuit_open" if circuit else "failing"
        else:
            state, reason = "live" if live(stats) else "on", None
        chat = chats.get(application.id)
        numbers = _numbers(stats)
        apps.append({
            "id": connector.id, "name": application.name, "app_key": application.key,
            "environment": application.environment, "state": state, "reason": reason, "status": connector.status,
            "health": {"status": check.status, "latency_ms": check.latency_ms, "checked_at": _iso(check.created_at)}
            if check is not None else None,
            "tools": tools.get(connector.id, 0), "sources": sources.get(application.id, 0),
            "chat": bool(chat and chat.enabled), "requests": numbers["requests"], "failed": numbers["failed"],
            "last_seen_at": numbers["last_seen_at"]})

    listing = registry.listing(db, settings)
    known = {item["key"]: item for item in listing["builtin"] + listing["providers"]}
    used = {chat.provider for chat in chats.values() if chat.enabled}
    models = []
    for key in [*known, *(key for key in model_stats if key not in known)]:
        item, stats = known.get(key), model_stats.get(key)
        ready = bool(item and item["ready"])
        if not (ready or stats or key in used):
            continue
        reason = None if ready else ("removed" if item is None else "turned_off" if item.get("enabled") is False else "no_key")
        numbers = _numbers(stats)
        models.append({"key": key, "name": item["name"] if item else key,
                       "state": "off" if not ready else ("live" if live(stats) else "on"), "reason": reason,
                       "requests": numbers["requests"], "failed": numbers["failed"],
                       "last_seen_at": numbers["last_seen_at"]})

    rows = list(db.scalars(traffic.order_by(AuditEvent.created_at.desc()).limit(EVENT_LIMIT)))
    cards = tool_cards.cards(db, (row.tool_key for row in rows if row.action == "tool.execute"))
    events = []
    for row in rows:
        app_id = by_key.get((row.app_key, row.environment))
        client = _client_id(row.actor_ref, app_id, key_ids)
        if client is None:
            continue
        stop = stopped_at(row.result, row.error_code)
        target = stop if stop in ("app", "model") else destination(row.action, row.tool_key)
        kind = KINDS[row.action]
        label = {"tool": (cards.get(row.tool_key) or {}).get("title") or row.tool_key or "Tool call",
                 "chat": "Chat answer", "model": row.tool_key or "Model call", "skill": row.tool_key or "Skill"}[kind]
        events.append({
            "id": row.id, "at": _iso(row.created_at), "kind": kind, "label": label, "client": client,
            "app": by_app[app_id][0].id if app_id is not None else None,
            "model": provider_of(row.action, row.tool_key, app_id) if target == "model" else None,
            "destination": target, "stopped_at": stop, "result": row.result, "error_code": row.error_code,
            "duration_ms": row.duration_ms, "trace_id": row.trace_id})

    return {
        "as_of": now.isoformat(), "window": window, "window_seconds": seconds, "live_seconds": LIVE_SECONDS,
        "totals": {**totals, "per_minute": round(totals["requests"] / (seconds / 60), 2)},
        "gates": [{"key": gate, "stopped": gate_stats[gate]["stopped"],
                   "codes": [{"code": code, "count": count} for code, count in
                             sorted(gate_stats[gate]["codes"].items(), key=lambda item: (-item[1], item[0]))]}
                  for gate in GATES],
        "clients": clients, "apps": apps, "models": models, "hub": {"answered": answered}, "events": events,
    }
