"""Connected applications (shown as Apps in the admin UI)."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.chat import read_body, stream_turn
from app.api.v1.common import ok
from app.chat import engine as chat_engine
from app.chat import settings as chat_settings
from app.config import get_settings
from app.connectors.discovery import sync_admin_sources
from app.connectors.registry import get_connector_bundle
from app.errors import HubError
from app.persistence.models import AdminUser, ServiceIdentity
from app.persistence.session import get_db, open_session
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import ADMIN_ROLES, WRITE_ROLES, require_app_access, require_role
from app.security.clients import READ_SCOPE, Caller
from app.services import connectors as service
from app.services import tool_switches
from app.tools import memory

router = APIRouter(prefix="/connectors", tags=["apps"])


def current_catalog(view: dict, failures: dict) -> dict:
    if view["id"] in failures:
        view.update(sources_total=0, sources_enabled=0, tools_total=0, tools_published=0,
                    source_sync_error=failures[view["id"]])
    return view


def scoped_bundle(db: Session, user: AdminUser, connector_id: str):
    connector, application = get_connector_bundle(db, connector_id)
    require_app_access(db, user, application.id)
    return connector, application


def writable_bundle(db: Session, user: AdminUser, connector_id: str):
    require_role(user.role, WRITE_ROLES)
    return scoped_bundle(db, user, connector_id)


@router.get("")
async def index(environment: str | None = None, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    failures = await sync_admin_sources(db, user, get_settings(), environment=environment, connection_metadata=True)
    return ok([current_catalog(view, failures) for view in service.list_connector_views(db, user, environment)])


@router.post("")
def create(payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    body = service.create_connector(db, user, payload, get_settings())
    db.commit()
    return ok(body, 201)


@router.get("/{connector_id}")
async def detail(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = scoped_bundle(db, user, connector_id)
    failures = await sync_admin_sources(db, user, get_settings(), connector_id=connector_id, connection_metadata=True)
    return ok({**current_catalog(service.connector_view(db, connector, application), failures),
               "health_history": service.health_history(db, connector.id),
               "contracts": service.contract_history(db, connector.id)})


@router.patch("/{connector_id}")
def update(connector_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = service.edit_connector(db, user, connector, application, payload, get_settings())
    db.commit()
    return ok(body)


@router.delete("/{connector_id}")
def remove(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    service.delete_connector(db, user, connector, application)
    db.commit()
    return ok({"deleted": True})


@router.post("/{connector_id}/test")
async def test(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = await service.test_connector(db, user, connector, application, get_settings())
    db.commit()
    return ok(body)


@router.post("/{connector_id}/discover")
async def discover(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = await service.discover(db, user, connector, application, get_settings())
    db.commit()
    return ok(body)


@router.post("/{connector_id}/activate")
def activate(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = service.activate(db, user, connector, application)
    db.commit()
    return ok(body)


@router.post("/{connector_id}/pause")
def pause(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = service.pause(db, user, connector, application)
    db.commit()
    return ok(body)


@router.post("/{connector_id}/rotate")
def rotate(connector_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = service.rotate_secret(db, user, connector, application, payload, get_settings())
    db.commit()
    return ok(body)


@router.get("/{connector_id}/memory")
def memory_settings(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _connector, application = scoped_bundle(db, user, connector_id)
    return ok(memory.admin_view(db, application))


@router.patch("/{connector_id}/memory")
def update_memory(connector_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    if connector.status == "archived" and isinstance(payload, dict) and payload.get("enabled") is True:
        raise HubError("CONFLICT", "Archived apps cannot turn memory on", 409)
    memory.update_settings(db, application, payload)
    record_audit(db, action="memory.settings", actor_ref=f"admin:{user.id}", result="success",
                 app_key=application.key, environment=application.environment)
    db.commit()
    return ok(memory.admin_view(db, application))


@router.delete("/{connector_id}/memory")
def purge_memory(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _connector, application = writable_bundle(db, user, connector_id)
    removed = memory.purge_app(db, application)
    record_audit(db, action="memory.purge", actor_ref=f"admin:{user.id}", result="success",
                 app_key=application.key, environment=application.environment)
    db.commit()
    return ok({"removed": removed})


@router.get("/{connector_id}/tool-switches")
def tool_switch_view(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = scoped_bundle(db, user, connector_id)
    return ok(tool_switches.admin_view(db, connector, application))


@router.put("/{connector_id}/tool-switches")
def update_tool_switches(connector_id: str, payload: dict, db: Session = Depends(get_db),
                         user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = tool_switches.update(db, user, connector, application, payload)
    db.commit()
    return ok(body)


@router.get("/{connector_id}/chat")
def chat_view(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    _connector, application = scoped_bundle(db, user, connector_id)
    return ok(chat_settings.admin_view(db, application, get_settings()))


@router.get("/{connector_id}/chat/gateway-models")
async def gateway_models(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    """Every model the Hub can reach now, for choosing the ones this app may call through the gateway."""

    from app.chat import gateway

    scoped_bundle(db, user, connector_id)
    rows = await gateway.every_model(db, get_settings())
    db.commit()
    return ok({"models": rows})


@router.patch("/{connector_id}/chat")
def update_chat(connector_id: str, payload: dict, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    if connector.status == "archived" and isinstance(payload, dict) and payload.get("enabled") is True:
        raise HubError("CONFLICT", "Archived apps cannot turn chat on", 409)
    if isinstance(payload, dict) and set(payload) & chat_settings.COST_FIELDS:
        require_role(user.role, ADMIN_ROLES)  # the cost guard is not for the app's own admins to lift
    chat_settings.update_settings(db, application, payload)
    record_audit(db, action="chat.settings", actor_ref=f"admin:{user.id}", result="success",
                 app_key=application.key, environment=application.environment)
    db.commit()
    return ok(chat_settings.admin_view(db, application, get_settings()))


@dataclass
class AdminPreviewCaller(Caller):
    """A transient read-only key used by an admin trying the chat; audited as that admin."""

    admin_id: str = ""

    @property
    def actor_ref(self) -> str:
        return f"admin:{self.admin_id}"


@router.post("/{connector_id}/chat/try")
async def try_chat(connector_id: str, request: Request, user: AdminUser = Depends(require_csrf)):
    """Stream a read-only answer, without a signed-in app user, so admins can check the setup.

    The admin may pick another provider and model for the turn, and sees what each tool returned.
    """

    body = await read_body(request)
    db = open_session()
    try:
        connector, application = scoped_bundle(db, user, connector_id)
        identity = ServiceIdentity(id="preview", name="Admin preview", token_hash="", app_id=application.id,
                                   scopes=[READ_SCOPE], allowed_tools=None)
        caller = AdminPreviewCaller(identity, application, connector, admin_id=user.id)
        turn = await chat_engine.Turn(db, caller, chat_engine.parse_request(body), None,
                                      model=chat_settings.chosen_model(db, body), show_results=True).prepare()
    except BaseException:
        db.close()
        raise
    return stream_turn(db, turn)


@router.post("/{connector_id}/archive")
def archive(connector_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    connector, application = writable_bundle(db, user, connector_id)
    body = service.archive_connector(db, user, connector, application)
    db.commit()
    return ok(body)
