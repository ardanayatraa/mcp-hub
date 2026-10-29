"""Reusable restrictions; profiles never grant the source application's permissions."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import HubError
from app.ids import as_utc, new_id
from app.persistence.models import (
    Application,
    Connector,
    McpAccessProfile,
    ModuleDefinition,
    ServiceIdentity,
    ToolDefinition,
)
from app.privacy.pii_inspector import tree_contains_pii
from app.tools.catalog import HUB_TOOL_NAMES


def binding(db: Session, app_id: str, profile_id: str | None) -> McpAccessProfile | None:
    if profile_id is None:
        return None
    profile = db.get(McpAccessProfile, profile_id)
    if profile is None or profile.app_id != app_id:
        raise HubError("PERMISSION_DENIED", "Access profile is unavailable for this application", 403)
    return profile


def validate(db: Session, application: Application, values: dict) -> dict:
    out = {}
    if "name" in values:
        name = values["name"].strip()
        if not name or not name.isprintable() or tree_contains_pii(name):
            raise HubError("VALIDATION_FAILED", "Profile name must be non-sensitive text", 422)
        out["name"] = name
    if "enabled" in values:
        out["enabled"] = values["enabled"]
    for field, known in (
        ("modules", set(db.scalars(select(ModuleDefinition.module_key).where(ModuleDefinition.app_id == application.id)))),
        ("tools", set(HUB_TOOL_NAMES) | set(db.scalars(select(ToolDefinition.mcp_name)
            .join(Connector, Connector.id == ToolDefinition.connector_id)
            .where(Connector.app_id == application.id, ToolDefinition.status != "archived")))),
    ):
        if field in values:
            selected = sorted(set(values[field]))
            if not set(selected) <= known:
                raise HubError("VALIDATION_FAILED", "Profile restrictions must use this application's modules and tools", 422)
            out[field] = selected
    return out


def view(db: Session, profile: McpAccessProfile) -> dict:
    return {"id": profile.id, "app_id": profile.app_id, "name": profile.name, "enabled": profile.enabled,
            "modules": list(profile.modules or []), "tools": list(profile.tools or []), "revision": profile.revision,
            "bound_keys": db.scalar(select(func.count()).select_from(ServiceIdentity).where(ServiceIdentity.profile_id == profile.id)),
            "created_at": as_utc(profile.created_at).isoformat()}


def create(db: Session, application: Application, values: dict) -> McpAccessProfile:
    if db.scalar(select(func.count()).select_from(McpAccessProfile).where(McpAccessProfile.app_id == application.id)) >= 20:
        raise HubError("CONFLICT", "This application already has 20 access profiles", 409)
    checked = validate(db, application, values)
    profile = McpAccessProfile(id=new_id(), app_id=application.id, **checked)
    db.add(profile)
    db.flush()
    return profile


def change(db: Session, application: Application, profile: McpAccessProfile, values: dict) -> McpAccessProfile:
    revision = values.pop("revision")
    if not values:
        raise HubError("VALIDATION_FAILED", "No profile changes were supplied", 422)
    checked = validate(db, application, values)
    changed = db.execute(update(McpAccessProfile).where(McpAccessProfile.id == profile.id,
        McpAccessProfile.revision == revision).values(**checked, revision=revision+1),
        execution_options={"synchronize_session": False}).rowcount
    if changed != 1:
        raise HubError("CONFLICT", "Profile changed; reload before saving", 409)
    db.refresh(profile)
    return profile
