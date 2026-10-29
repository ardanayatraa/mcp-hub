from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.errors import HubError
from app.persistence.models import AdminUser, Application, McpAccessProfile
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import READ_ROLES, WRITE_ROLES, require_app_access, require_role
from app.services import profiles

router = APIRouter(prefix="/mcp-profiles", tags=["MCP access profiles"])


class Restrictions(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(default="Access profile", min_length=1, max_length=120)
    enabled: bool = False
    modules: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list, max_length=100)
    tools: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=200)


class CreateProfile(Restrictions):
    app_id: str = Field(min_length=36, max_length=36)


class ChangeProfile(Restrictions):
    revision: int = Field(ge=1, le=2147483646)


def application(db, user, app_id):
    require_app_access(db, user, app_id)
    app = db.get(Application, app_id)
    if app is None:
        raise HubError("NOT_FOUND", "Application was not found", 404)
    return app


@router.get("")
def index(app_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, READ_ROLES)
    application(db, user, app_id)
    rows = db.scalars(select(McpAccessProfile).where(McpAccessProfile.app_id == app_id).order_by(McpAccessProfile.created_at))
    return ok([profiles.view(db, row) for row in rows])


@router.post("")
def create(body: CreateProfile, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    app = application(db, user, body.app_id)
    row = profiles.create(db, app, body.model_dump(exclude={"app_id"}))
    record_audit(db, action="profile.create", actor_ref=f"admin:{user.id}", app_key=app.key,
                 environment=app.environment, result="success")
    result = profiles.view(db, row)
    db.commit()
    return ok(result, 201)


@router.patch("/{profile_id}")
def change(profile_id: str, body: ChangeProfile, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    row = db.get(McpAccessProfile, profile_id)
    if row is None:
        raise HubError("NOT_FOUND", "Profile was not found", 404)
    app = application(db, user, row.app_id)
    row = profiles.change(db, app, row, body.model_dump(exclude_unset=True))
    record_audit(db, action="profile.update", actor_ref=f"admin:{user.id}", app_key=app.key,
                 environment=app.environment, result="success")
    result = profiles.view(db, row)
    db.commit()
    return ok(result)
