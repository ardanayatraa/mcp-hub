"""The chat an app embeds in other websites, for the app's own signed-in users only.

A widget belongs to one app. A visitor signs in to the app inside the widget; the Hub posts the
sign-in form to the app's login endpoint, keeps the token it returns (encrypted) and gives the
widget a random session id. Every chat turn then calls the app with that user's token, so the app
itself decides what each user may read. Admins can preview the widget as a signed-in user from
the Chat Agent page; those previews are read-only, short-lived and audited as the admin.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.http_adapter import execute_request, join_url
from app.connectors.user_credential import signs_in_users
from app.errors import HubError
from app.ids import as_utc, new_id, new_trace_id, utcnow
from app.persistence.models import (
    AdminUser,
    Application,
    ChatSetting,
    Connector,
    EmbedLink,
    EmbedWidget,
    ServiceIdentity,
)
from app.security.audit import record_audit
from app.security.clients import READ_SCOPE, Caller
from app.security.crypto import decrypt_secret, encrypt_secret

SESSION_PREFIX = "es_"
PREVIEW_PREFIX = "sim."
PREVIEW_SECONDS = 1800
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
PUBLIC_ID_RE = re.compile(r"^w_[A-Za-z0-9_-]{8,36}$")
MAX_ORIGINS = 20
MAX_FIELD = 300


@dataclass
class EmbedCaller(Caller):
    """A read-only caller for one signed-in widget user, or for an admin previewing as them."""

    link_id: str = ""
    admin_id: str | None = None

    @property
    def actor_ref(self) -> str:
        return f"admin:{self.admin_id}" if self.admin_id else f"embed:{self.link_id}"


@dataclass
class SignedIn:
    link: EmbedLink
    token: str
    name: str | None
    admin_id: str | None = None


def _new_public_id() -> str:
    return "w_" + secrets.token_urlsafe(15).replace("-", "a").replace("_", "b")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _dig(document, path: str):
    node = document
    for part in filter(None, path.split(".")):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _origin(value, settings: Settings) -> str:
    if not isinstance(value, str):
        raise HubError("VALIDATION_FAILED", "Each allowed site must be an address such as https://www.example.com", 422)
    parts = urlsplit(value.strip().rstrip("/"))
    schemes = {"https", "http"} if settings.allow_insecure_http else {"https"}
    if parts.scheme not in schemes or not parts.hostname or parts.path or parts.query or parts.fragment \
            or parts.username or parts.password or "*" in value:
        raise HubError("VALIDATION_FAILED", "Each allowed site must be only a scheme and host, such as https://www.example.com",
                       422)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


# ---- widgets (admin) ------------------------------------------------------------------------------

def widget_for(db: Session, application: Application) -> EmbedWidget | None:
    return db.scalar(select(EmbedWidget).where(EmbedWidget.app_id == application.id))


def ensure_widget(db: Session, application: Application) -> EmbedWidget:
    widget = widget_for(db, application)
    if widget is None:
        widget = EmbedWidget(id=new_id(), app_id=application.id, public_id=_new_public_id(), enabled=False,
                             allowed_origins=[], title=application.name[:80])
        db.add(widget)
        db.flush()
    return widget


def _active_links(db: Session, widget: EmbedWidget):
    now = utcnow()
    return [link for link in db.scalars(select(EmbedLink).where(EmbedLink.widget_id == widget.id,
                                                                  EmbedLink.revoked_at.is_(None))
                                        .order_by(EmbedLink.created_at.desc()).limit(500))
            if as_utc(link.expires_at) > now]


def widget_view(db: Session, widget: EmbedWidget, application: Application, connector: Connector | None,
                public_url: str) -> dict:
    chat = db.get(ChatSetting, application.id)
    base = public_url.rstrip("/")
    script = f"{base}/api/embed/v1/embed.js"
    return {
        "public_id": widget.public_id, "enabled": widget.enabled, "allowed_origins": list(widget.allowed_origins or []),
        "title": widget.title, "accent": widget.accent, "position": widget.position, "session_days": widget.session_days,
        "page_url": f"{base}/api/embed/v1/w/{widget.public_id}",
        "snippet": f'<script src="{script}" data-widget="{widget.public_id}" async></script>',
        "ready": {"user_sign_in": signs_in_users(connector), "chat_enabled": bool(chat and chat.enabled),
                  "app_active": bool(connector and connector.status == "active")},
        "signed_in_users": len(_active_links(db, widget)),
        "updated_at": as_utc(widget.updated_at).isoformat(),
    }


def update_widget(db: Session, admin: AdminUser, widget: EmbedWidget, application: Application,
                  connector: Connector | None, payload, settings: Settings) -> None:
    if not isinstance(payload, dict):
        raise HubError("VALIDATION_FAILED", "Request body must be an object", 422)
    unknown = set(payload) - {"enabled", "allowed_origins", "title", "accent", "position", "session_days"}
    if unknown:
        raise HubError("VALIDATION_FAILED", f"Unknown setting: {sorted(unknown)[0]}", 422)
    if "allowed_origins" in payload:
        origins = payload["allowed_origins"]
        if not isinstance(origins, list) or len(origins) > MAX_ORIGINS:
            raise HubError("VALIDATION_FAILED", f"List at most {MAX_ORIGINS} sites", 422)
        widget.allowed_origins = list(dict.fromkeys(_origin(item, settings) for item in origins))
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or len(title.strip()) > 80:
            raise HubError("VALIDATION_FAILED", "Title must be text of at most 80 characters", 422)
        widget.title = title.strip()
    if "accent" in payload:
        if not isinstance(payload["accent"], str) or not ACCENT_RE.match(payload["accent"]):
            raise HubError("VALIDATION_FAILED", "Colour must look like #2563eb", 422)
        widget.accent = payload["accent"].lower()
    if "position" in payload:
        if payload["position"] not in ("left", "right"):
            raise HubError("VALIDATION_FAILED", "Position must be left or right", 422)
        widget.position = payload["position"]
    if "session_days" in payload:
        days = payload["session_days"]
        if type(days) is not int or not 1 <= days <= 90:
            raise HubError("VALIDATION_FAILED", "Sessions last 1 to 90 days", 422)
        widget.session_days = days
    if "enabled" in payload:
        if type(payload["enabled"]) is not bool:
            raise HubError("VALIDATION_FAILED", "enabled must be true or false", 422)
        if payload["enabled"] and not signs_in_users(connector):
            raise HubError("VALIDATION_FAILED", "The embedded chat is for signed-in users: add user_auth to this "
                           "app's endpoint list first", 422)
        widget.enabled = payload["enabled"]
    widget.updated_at = utcnow()
    record_audit(db, action="embed.settings", actor_ref=f"admin:{admin.id}", result="success",
                 app_key=application.key, environment=application.environment)


def rotate_widget(db: Session, admin: AdminUser, widget: EmbedWidget, application: Application) -> None:
    widget.public_id = _new_public_id()
    widget.updated_at = utcnow()
    record_audit(db, action="embed.rotate", actor_ref=f"admin:{admin.id}", result="success",
                 app_key=application.key, environment=application.environment)


def link_views(db: Session, widget: EmbedWidget, settings: Settings) -> list[dict]:
    rows = []
    for link in _active_links(db, widget):
        rows.append({"id": link.id, "name": _label(link, settings),
                     "created_at": as_utc(link.created_at).isoformat(),
                     "last_used_at": as_utc(link.last_used_at).isoformat() if link.last_used_at else None,
                     "expires_at": as_utc(link.expires_at).isoformat()})
    return rows


def revoke_links(db: Session, admin: AdminUser, widget: EmbedWidget, application: Application,
                 link_id: str | None) -> int:
    query = select(EmbedLink).where(EmbedLink.widget_id == widget.id, EmbedLink.revoked_at.is_(None))
    if link_id:
        query = query.where(EmbedLink.id == link_id)
    count = 0
    for link in db.scalars(query):
        link.revoked_at = utcnow()
        count += 1
    if link_id and not count:
        raise HubError("NOT_FOUND", "That sign-in was not found", 404)
    record_audit(db, action="embed.revoke", actor_ref=f"admin:{admin.id}", result="success",
                 app_key=application.key, environment=application.environment)
    return count


def preview_token(db: Session, admin: AdminUser, widget: EmbedWidget, application: Application, link_id: str,
                  settings: Settings) -> str:
    link = db.get(EmbedLink, link_id)
    if link is None or link.widget_id != widget.id or link.revoked_at or as_utc(link.expires_at) <= utcnow():
        raise HubError("NOT_FOUND", "That sign-in was not found or has ended", 404)
    record_audit(db, action="embed.preview_as_user", actor_ref=f"admin:{admin.id}", result="success",
                 app_key=application.key, environment=application.environment, trace_id=new_trace_id())
    claims = {"link": link.id, "admin": admin.id, "widget": widget.id,
              "exp": int(utcnow().timestamp()) + PREVIEW_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{PREVIEW_PREFIX}{raw}.{_preview_digest(settings, raw)}"


def _preview_digest(settings: Settings, raw: str) -> str:
    # A key of its own, so a preview token can never pass as any other signed Hub value.
    key = hmac.new(settings.session_signing_key.encode(), b"embed-preview", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(hmac.new(key, raw.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def _preview_claims(settings: Settings, token: str, widget: EmbedWidget) -> dict | None:
    raw, _, digest = token[len(PREVIEW_PREFIX):].partition(".")
    if not raw or not hmac.compare_digest(digest, _preview_digest(settings, raw)):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    now = int(utcnow().timestamp())
    if not isinstance(claims, dict) or claims.get("widget") != widget.id or type(claims.get("exp")) is not int             or not now < claims["exp"] <= now + PREVIEW_SECONDS:
        return None
    return claims


# ---- the public widget -----------------------------------------------------------------------------

def public_widget(db: Session, public_id: str) -> tuple[EmbedWidget, Application, Connector]:
    """The widget behind a snippet. Unknown, turned-off and archived ones all look the same."""

    missing = HubError("NOT_FOUND", "This chat is not available", 404)
    if not isinstance(public_id, str) or not PUBLIC_ID_RE.match(public_id):
        raise missing
    widget = db.scalar(select(EmbedWidget).where(EmbedWidget.public_id == public_id))
    if widget is None or not widget.enabled:
        raise missing
    application = db.get(Application, widget.app_id)
    connector = db.scalar(select(Connector).where(Connector.app_id == widget.app_id))
    if application is None or connector is None or connector.status == "archived" or not signs_in_users(connector):
        raise missing
    return widget, application, connector


def frame_ancestors(widget: EmbedWidget) -> str:
    return " ".join(["'self'", *widget.allowed_origins])


def _label(link: EmbedLink, settings: Settings) -> str | None:
    if not link.label_ciphertext:
        return None
    try:
        return decrypt_secret(settings.secret_encryption_key, link.label_ciphertext)
    except HubError:
        return None


def sign_in_form(connector: Connector) -> list[dict]:
    # No form when users arrive with the token their page already has.
    fields = connector.custom_spec["user_auth"].get("fields") or []
    secret = ("password", "pin", "secret", "passcode")
    return [{"name": name, "label": name.replace("_", " ").capitalize(),
             "type": "password" if any(word in name.lower() for word in secret)
             else "email" if "email" in name.lower() else "text"} for name in fields]


async def sign_in(db: Session, widget: EmbedWidget, application: Application, connector: Connector, form,
                  settings: Settings) -> dict:
    """Post the visitor's sign-in form to the app and keep the token it returns. The form is never stored."""

    auth = connector.custom_spec["user_auth"]
    if "login_path" not in auth:
        raise HubError("VALIDATION_FAILED", "This chat opens from a page where you are already signed in", 422)
    if not isinstance(form, dict):
        raise HubError("VALIDATION_FAILED", "Fill in the sign-in form", 422)
    body = {}
    for name in auth["fields"]:
        value = form.get(name)
        if not isinstance(value, str) or not value or len(value) > MAX_FIELD:
            raise HubError("VALIDATION_FAILED", "Fill in every field of the sign-in form", 422)
        body[name] = value
    status, raw, _ = await execute_request(
        method="POST", url=join_url(connector.base_url, auth["login_path"]), settings=settings,
        headers={"Accept": "application/json"}, json_body=body, timeout_ms=connector.timeout_ms,
        tls_verify=connector.tls_verify, retries=0)
    if status in {400, 401, 403, 404, 422}:
        raise HubError("SIGN_IN_FAILED", f"{application.name} did not accept these sign-in details", 401)
    if status == 429:
        raise HubError("RATE_LIMITED", "Too many sign-in attempts. Wait a moment and try again.", 429)
    if status >= 400:
        raise HubError("UPSTREAM_ERROR", f"{application.name} could not sign you in right now", 502)
    try:
        token = _dig(json.loads(raw.decode("utf-8")), auth["token_path"])
    except (UnicodeDecodeError, json.JSONDecodeError):
        token = None
    if not isinstance(token, str) or not 8 <= len(token) <= 4096:
        raise HubError("SCHEMA_MISMATCH", f"{application.name} signed you in but returned no token where expected", 502)
    name = await _display_name(connector, token, settings)
    return _open_session(db, widget, application, token, name, settings, "embed.sign_in")


async def sign_in_with_token(db: Session, widget: EmbedWidget, application: Application, connector: Connector, token,
                             settings: Settings) -> dict:
    """The page the widget sits on is already signed in to the app: it hands over the user's own token. When the
    app has a me_path the Hub asks it whose token this is before using it; either way the token can only ever read
    that user's data, because the app decides what it may read."""

    auth = connector.custom_spec["user_auth"]
    if not isinstance(token, str) or not 8 <= len(token) <= 4096 or not token.isprintable():
        raise HubError("VALIDATION_FAILED", "The sign-in token is not valid", 422)
    if "me_path" not in auth:
        # Nothing to ask the app: a wrong token simply fails when the chat reads, and the widget asks for a new one.
        return _open_session(db, widget, application, token, None, settings, "embed.sign_in_host")
    status, raw, _ = await execute_request(
        method="GET", url=join_url(connector.base_url, auth["me_path"]), settings=settings,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout_ms=connector.timeout_ms, tls_verify=connector.tls_verify, retries=0)
    if status in {401, 403, 404}:
        raise HubError("SIGN_IN_FAILED", f"{application.name} did not accept this sign-in", 401)
    if status == 429:
        raise HubError("RATE_LIMITED", "Too many sign-in attempts. Wait a moment and try again.", 429)
    if status >= 400:
        raise HubError("UPSTREAM_ERROR", f"{application.name} could not sign you in right now", 502)
    try:
        value = _dig(json.loads(raw.decode("utf-8")), auth["name_path"])
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    name = " ".join(value.split())[:120] or None if isinstance(value, str) else None
    return _open_session(db, widget, application, token, name, settings, "embed.sign_in_host")


def _open_session(db: Session, widget: EmbedWidget, application: Application, token: str, name: str | None,
                  settings: Settings, action: str) -> dict:
    session = SESSION_PREFIX + secrets.token_urlsafe(32)
    link = EmbedLink(id=new_id(), widget_id=widget.id, session_hash=_hash(session),
                     token_ciphertext=encrypt_secret(settings.secret_encryption_key, token),
                     label_ciphertext=encrypt_secret(settings.secret_encryption_key, name) if name else None,
                     expires_at=utcnow() + timedelta(days=widget.session_days))
    db.add(link)
    record_audit(db, action=action, actor_ref=f"embed:{link.id}", result="success",
                 app_key=application.key, environment=application.environment)
    return {"session": session, "name": name}


async def _display_name(connector: Connector, token: str, settings: Settings) -> str | None:
    auth = connector.custom_spec["user_auth"]
    if "me_path" not in auth:
        return None
    try:
        status, raw, _ = await execute_request(
            method="GET", url=join_url(connector.base_url, auth["me_path"]), settings=settings,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout_ms=connector.timeout_ms, tls_verify=connector.tls_verify, retries=0)
        value = _dig(json.loads(raw.decode("utf-8")), auth["name_path"]) if status < 400 else None
    except (HubError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return " ".join(value.split())[:120] or None if isinstance(value, str) else None


def resolve_session(db: Session, widget: EmbedWidget, token: str | None, settings: Settings) -> SignedIn | None:
    """The signed-in user behind a widget's session id, or an admin's preview of one."""

    if not isinstance(token, str) or len(token) > 2048:
        return None
    admin_id = None
    if token.startswith(PREVIEW_PREFIX):
        claims = _preview_claims(settings, token, widget)
        if claims is None:
            return None
        link = db.get(EmbedLink, str(claims.get("link") or ""))
        admin_id = str(claims.get("admin") or "") or None
        admin = db.get(AdminUser, admin_id) if admin_id else None
        if admin is None or not admin.is_active:
            return None
    elif token.startswith(SESSION_PREFIX):
        link = db.scalar(select(EmbedLink).where(EmbedLink.session_hash == _hash(token)))
    else:
        return None
    if link is None or link.widget_id != widget.id or link.revoked_at or as_utc(link.expires_at) <= utcnow():
        return None
    if admin_id is None and (link.last_used_at is None or utcnow() - as_utc(link.last_used_at) > timedelta(minutes=1)):
        link.last_used_at = utcnow()
    try:
        user_token = decrypt_secret(settings.secret_encryption_key, link.token_ciphertext)
    except HubError:
        return None
    return SignedIn(link, user_token, _label(link, settings), admin_id)


def sign_out(db: Session, widget: EmbedWidget, application: Application, token: str | None, settings: Settings) -> None:
    if isinstance(token, str) and token.startswith(SESSION_PREFIX):
        link = db.scalar(select(EmbedLink).where(EmbedLink.session_hash == _hash(token)))
        if link is not None and link.widget_id == widget.id and link.revoked_at is None:
            link.revoked_at = utcnow()
            record_audit(db, action="embed.sign_out", actor_ref=f"embed:{link.id}", result="success",
                         app_key=application.key, environment=application.environment)


def caller_for(application: Application, connector: Connector, session: SignedIn) -> EmbedCaller:
    # Read-only always: an embedded chat never changes data, whoever is signed in.
    identity = ServiceIdentity(id="embed", name="Embedded chat", token_hash="", app_id=application.id,
                               scopes=[READ_SCOPE], allowed_tools=None)
    return EmbedCaller(identity, application, connector, link_id=session.link.id, admin_id=session.admin_id)
