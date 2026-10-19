"""MCP tools: templates, built-ins, and the create -> test -> publish workflow."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.config import get_settings
from app.connectors.discovery import sync_admin_sources
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.auth import require_csrf
from app.security.authorization import WRITE_ROLES, require_role, require_tool_access
from app.services import capabilities as capabilities_service
from app.services import tool_cards
from app.services import tools as service
from app.tools.definitions import TEMPLATES

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def index(include_archived: bool = False, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    await sync_admin_sources(db, user, get_settings())
    return ok(service.list_tools(db, user, include_archived=include_archived))


@router.get("/templates")
def templates(user: AdminUser = Depends(require_csrf)):
    del user
    return ok([{"key": key, **value} for key, value in TEMPLATES.items()])


@router.get("/capabilities")
def capabilities(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    """What this MCP can do now: protocol, limits, report features, a per-app matrix and 7-day calls per tool."""

    return ok(capabilities_service.capabilities(db, user, get_settings()))


@router.get("/builtins")
def builtins(user: AdminUser = Depends(require_csrf)):
    del user
    return ok(service.builtin_catalog())


@router.post("/builtins/{name}/test")
async def test_builtin(name: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = await service.test_builtin(db, user, name, payload, get_settings())
    db.commit()
    return ok(body)


@router.post("")
def create(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = service.create_tool(db, user, payload)
    db.commit()
    return ok(body, 201)


@router.post("/generate")
async def generate(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = await service.generate_tools(db, user, payload, get_settings())
    db.commit()
    return ok(body, 201)


@router.get("/agent-view")
async def agent_view(connector_id: str, key_id: str | None = None, write: bool = False,
                     db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    failures = await sync_admin_sources(db, user, get_settings(), connector_id=connector_id)
    body = service.agent_view(db, user, connector_id, key_id=key_id, write=write)
    db.commit()
    return ok({**body, "sync_error": failures.get(connector_id)})


@router.get("/{tool_id}")
def detail(tool_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    tool = require_tool_access(db, user, tool_id)
    return ok({**service.tool_view(db, tool), "usage": tool_cards.usage(db, tool)})


@router.patch("/{tool_id}")
def update(tool_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = service.update_tool(db, user, require_tool_access(db, user, tool_id), payload)
    db.commit()
    return ok(body)


@router.delete("/{tool_id}")
def remove(tool_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    service.delete_tool(db, user, require_tool_access(db, user, tool_id))
    db.commit()
    return ok({"deleted": True})


@router.post("/{tool_id}/test")
async def test(tool_id: str, payload: dict | None = None, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = await service.test_tool(db, user, require_tool_access(db, user, tool_id), payload or {}, get_settings())
    db.commit()
    return ok(body)


@router.post("/{tool_id}/publish")
def publish(tool_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = service.publish_tool(db, user, require_tool_access(db, user, tool_id), get_settings())
    db.commit()
    return ok(body)


@router.post("/{tool_id}/disable")
def disable(tool_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = service.disable_tool(db, user, require_tool_access(db, user, tool_id))
    db.commit()
    return ok(body)
