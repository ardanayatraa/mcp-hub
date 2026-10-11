"""Per-app off switches. An off tool is hidden from every tool list, refused when called,
and any skill that needs it hides too. A switch only ever removes a tool; it never grants one."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import HubError
from app.persistence.models import ToolSwitch


def off_names(db: Session, app_id: str) -> set[str]:
    return set(db.scalars(select(ToolSwitch.tool_name).where(ToolSwitch.app_id == app_id)))


def require_on(db: Session, app_id: str, name: str) -> None:
    found = db.scalar(select(ToolSwitch.id).where(ToolSwitch.app_id == app_id, ToolSwitch.tool_name == name))
    if found is not None:
        raise HubError("TOOL_DISABLED", "This tool is switched off for this app", 403)
