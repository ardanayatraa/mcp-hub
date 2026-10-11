"""Skills: reusable instructions AI clients receive as MCP prompts."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.auth import require_csrf
from app.security.authorization import WRITE_ROLES, require_role
from app.services import skills as service

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
def index(connector_id: str | None = None, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    return ok(service.list_skills(db, user, connector_id))


@router.get("/templates")
def templates(user: AdminUser = Depends(require_csrf)):
    del user
    return ok(service.TEMPLATES)


@router.post("/preview")
def preview(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    return ok(service.preview(db, user, payload))


@router.post("")
def create(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = service.create_skill(db, user, payload)
    db.commit()
    return ok(body, 201)


@router.patch("/{skill_id}")
def update(skill_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    skill, application = service.require_skill(db, user, skill_id)
    body = service.update_skill(db, user, skill, application, payload)
    db.commit()
    return ok(body)


@router.delete("/{skill_id}")
def remove(skill_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    skill, application = service.require_skill(db, user, skill_id)
    service.delete_skill(db, user, skill, application)
    db.commit()
    return ok({"deleted": True})
