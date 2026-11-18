"""Admin settings of the embedded chat, and the Chat Agent preview."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.embed import public_base
from app.api.v1.common import ok
from app.config import get_settings
from app.connectors.registry import get_connector_bundle
from app.errors import HubError
from app.persistence.models import AdminUser, Application, Connector, EmbedWidget
from app.persistence.session import get_db
from app.security.auth import require_csrf
from app.security.authorization import (
    WRITE_ROLES,
    allowed_app_ids,
    require_app_access,
    require_role,
)
from app.services import embed

router = APIRouter(tags=["embed"])


def _bundle(db: Session, user: AdminUser, connector_id: str, *, write: bool = False):
    if write:
        require_role(user.role, WRITE_ROLES)
    connector, application = get_connector_bundle(db, connector_id)
    require_app_access(db, user, application.id)
    return connector, application


def _view(db: Session, widget: EmbedWidget, application: Application, connector: Connector) -> dict:
    return embed.widget_view(db, widget, application, connector, public_base())


@router.get("/connectors/{connector_id}/embed")
def show(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = _bundle(db, user, connector_id)
    widget = embed.ensure_widget(db, application)
    body = _view(db, widget, application, connector)
    db.commit()
    return ok(body)


@router.put("/connectors/{connector_id}/embed")
def update(connector_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = _bundle(db, user, connector_id, write=True)
    if connector.status == "archived":
        raise HubError("CONFLICT", "Archived apps cannot be embedded", 409)
    widget = embed.ensure_widget(db, application)
    embed.update_widget(db, user, widget, application, connector, payload, get_settings())
    db.commit()
    return ok(_view(db, widget, application, connector))


@router.post("/connectors/{connector_id}/embed/rotate")
def rotate(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = _bundle(db, user, connector_id, write=True)
    widget = embed.ensure_widget(db, application)
    embed.rotate_widget(db, user, widget, application)
    db.commit()
    return ok(_view(db, widget, application, connector))


@router.get("/connectors/{connector_id}/embed/users")
def users(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    # Names of the app's users: only admins who may change this app see them.
    _connector, application = _bundle(db, user, connector_id, write=True)
    widget = embed.ensure_widget(db, application)
    body = embed.link_views(db, widget, get_settings())
    db.commit()
    return ok(body)


@router.delete("/connectors/{connector_id}/embed/users")
def revoke_all(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _connector, application = _bundle(db, user, connector_id, write=True)
    widget = embed.ensure_widget(db, application)
    count = embed.revoke_links(db, user, widget, application, None)
    db.commit()
    return ok({"revoked": count})


@router.delete("/connectors/{connector_id}/embed/users/{link_id}")
def revoke(connector_id: str, link_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _connector, application = _bundle(db, user, connector_id, write=True)
    widget = embed.ensure_widget(db, application)
    count = embed.revoke_links(db, user, widget, application, link_id)
    db.commit()
    return ok({"revoked": count})


@router.post("/connectors/{connector_id}/embed/preview")
def preview(connector_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    """A short read-only token to open the widget as one signed-in user. Audited as this admin."""

    _connector, application = _bundle(db, user, connector_id, write=True)
    widget = embed.widget_for(db, application)
    if widget is None or not widget.enabled:
        raise HubError("CONFLICT", "Turn the embedded chat on first", 409)
    link_id = payload.get("link_id") if isinstance(payload, dict) else None
    if not isinstance(link_id, str):
        raise HubError("VALIDATION_FAILED", "Choose a signed-in user", 422)
    token = embed.preview_token(db, user, widget, application, link_id, get_settings())
    db.commit()
    return ok({"token": token, "expires_in": embed.PREVIEW_SECONDS})


@router.get("/embed/widgets")
def widgets(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    """Every app this admin can see that has an embedded chat set up, for the Chat Agent page."""

    allowed = allowed_app_ids(db, user)
    rows = []
    query = (select(EmbedWidget, Application, Connector).join(Application, Application.id == EmbedWidget.app_id)
             .join(Connector, Connector.app_id == Application.id).order_by(Application.name))
    for widget, application, connector in db.execute(query):
        if allowed is not None and application.id not in allowed:
            continue
        view = _view(db, widget, application, connector)
        rows.append({"connector_id": connector.id, "app_name": application.name, "app_key": application.key,
                     "environment": application.environment, **view})
    return ok(rows)
