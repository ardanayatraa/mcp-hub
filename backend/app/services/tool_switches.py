"""Admin view and bulk update of an app's tool switches."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import HubError
from app.ids import utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    Connector,
    ModuleDefinition,
    ServiceIdentity,
    ToolDefinition,
    ToolSwitch,
)
from app.security.audit import record_audit
from app.security.clients import READ_SCOPE, WRITE_SCOPE, Caller
from app.tools import catalog, memory, switches
from app.tools.definitions import WRITE_TEMPLATES

MAX_CHANGES = 500
_STATUS_NOTE = {"draft": "Draft: publish it on its page first", "disabled": "Disabled on its page"}


def _rows(db: Session, connector: Connector, application: Application) -> list[dict]:
    """Every tool the app's AI could ever be offered, and whether a full key would see it now."""

    preview = ServiceIdentity(id="preview", name="preview", token_hash="", app_id=application.id,
                              scopes=[READ_SCOPE, WRITE_SCOPE], allowed_tools=None)
    live = {tool.name for tool in catalog.visible_tools(db, Caller(preview, application, connector), ignore_switches=True)}
    memory_on = memory.is_enabled(db, application.id)
    rows = [{"name": tool.name, "title": tool.title, "kind": "hub", "group": "Hub tools",
             "template": "report" if name == catalog.RUN_REPORT else "read", "status": "published", "write": False,
             "live": name in live, "note": None if name in live else "Activate the app first"}
            for name, tool in catalog.BUILTINS.items()]
    rows += [{"name": tool.name, "title": tool.title, "kind": "memory", "group": "Memory",
              "template": "read" if name == memory.RECALL else "update", "status": "published",
              "write": name != memory.RECALL, "live": name in live,
              "note": None if name in live else ("Memory is off for this app" if not memory_on else "Activate the app first")}
             for name, tool in memory.TOOLS.items()]
    modules = dict(db.execute(select(ModuleDefinition.module_key, ModuleDefinition.name)
                              .where(ModuleDefinition.app_id == application.id)).all())
    for tool in db.scalars(select(ToolDefinition).where(ToolDefinition.connector_id == connector.id,
                                                        ToolDefinition.status != "archived")
                           .order_by(ToolDefinition.module_key, ToolDefinition.tool_key)):
        visible = tool.mcp_name in live
        note = None if visible else _STATUS_NOTE.get(tool.status, "Its data source or operation is not allowed yet")
        rows.append({"name": tool.mcp_name, "title": catalog.tool_title(tool), "kind": "app",
                     "group": modules.get(tool.module_key, tool.module_key), "template": tool.template,
                     "status": tool.status, "write": tool.template in WRITE_TEMPLATES, "live": visible, "note": note,
                     "tool_id": tool.id})
    return rows


def admin_view(db: Session, connector: Connector, application: Application) -> dict:
    off = switches.off_names(db, application.id)
    rows = [{**row, "enabled": row["name"] not in off} for row in _rows(db, connector, application)]
    return {"tools": rows, "total": len(rows), "off": sum(1 for row in rows if not row["enabled"]),
            "reaching_ai": sum(1 for row in rows if row["enabled"] and row["live"])}


def update(db: Session, admin: AdminUser, connector: Connector, application: Application, payload) -> dict:
    changes = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(changes, dict) or not changes or len(changes) > MAX_CHANGES:
        raise HubError("VALIDATION_FAILED", f"Send tools as an object of 1 to {MAX_CHANGES} name: true/false pairs", 422)
    known = {row["name"] for row in _rows(db, connector, application)}
    for name, on in changes.items():
        if name not in known:
            raise HubError("VALIDATION_FAILED", f"Unknown tool: {str(name)[:80]}", 422)
        if type(on) is not bool:
            raise HubError("VALIDATION_FAILED", f"{name} must be true or false", 422)
    off = switches.off_names(db, application.id)
    for name, on in changes.items():
        if on and name in off:
            db.execute(delete(ToolSwitch).where(ToolSwitch.app_id == application.id, ToolSwitch.tool_name == name))
        elif not on and name not in off:
            db.add(ToolSwitch(app_id=application.id, tool_name=name, updated_by=admin.id, updated_at=utcnow()))
        else:
            continue
        record_audit(db, action="tool.switch_on" if on else "tool.switch_off", actor_ref=f"admin:{admin.id}",
                     result="success", app_key=application.key, environment=application.environment, tool_key=name)
    db.flush()
    return admin_view(db, connector, application)
