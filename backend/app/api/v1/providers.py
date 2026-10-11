"""Model providers for the Hub chat. Every admin can see them; only super admins change them."""

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.chat import registry
from app.config import get_settings
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.auth import require_csrf
from app.security.authorization import ADMIN_ROLES, READ_ROLES, require_role
from app.security.rate_limit import hit

router = APIRouter(prefix="/model-providers", tags=["providers"])


@router.get("")
def index(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, READ_ROLES)
    return ok(registry.listing(db, get_settings()))


@router.get("/presets")
def presets(user: AdminUser = Depends(require_csrf)):
    require_role(user.role, READ_ROLES)
    return ok(registry.PRESETS)


@router.get("/{provider_key}/models")
async def models(provider_key: str, refresh: bool = False, db: Session = Depends(get_db),
                 user: AdminUser = Depends(require_csrf)):
    """The models a chat can pick for one provider ("anthropic", "openai_compatible" or a provider key).

    Served from a few hours of cache; fetched live when missing, stale or refresh=true.
    """

    require_role(user.role, READ_ROLES)
    if refresh:
        hit(f"models:{user.id}", 20, 60)
    catalog = await registry.model_catalog(db, provider_key, get_settings(), refresh=refresh)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()  # the fetched list is still returned, just not cached
    return ok(catalog)


@router.post("")
def create(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    row = registry.create(db, user, payload, get_settings())
    db.commit()
    return ok(registry.view(row), 201)


@router.patch("/{provider_id}")
def update(provider_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    row = registry.update(db, user, registry.require(db, provider_id), payload, get_settings())
    db.commit()
    return ok(registry.view(row))


@router.post("/{provider_id}/test")
async def test(provider_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    row = await registry.test(db, user, registry.require(db, provider_id), get_settings())
    db.commit()
    return ok(registry.view(row))


@router.delete("/{provider_id}")
def delete(provider_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, ADMIN_ROLES)
    registry.delete(db, user, registry.require(db, provider_id))
    db.commit()
    return ok({"deleted": True})
