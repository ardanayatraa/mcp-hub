"""The embedded chat other websites show: the loader script, the widget page and its API.

The page runs inside an iframe on the sites an admin allows (CSP frame-ancestors), so a visitor's
sign-in form and session stay out of reach of the host page's scripts. The widget talks to this
API from the Hub's own origin with a bearer session; no cookies are used.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.api.chat import read_body, stream_turn
from app.api.v1.common import client_host, ok
from app.chat import engine
from app.chat import settings as chat_settings
from app.config import get_settings
from app.errors import HubError
from app.persistence.session import open_session
from app.security.rate_limit import hit
from app.services import embed

router = APIRouter(prefix="/api/embed/v1", tags=["embed"])
ASSETS = Path(__file__).with_name("embed_assets")


@lru_cache(maxsize=4)
def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def public_base() -> str:
    url = get_settings().mcp_public_url.rstrip("/")
    return url[: -len("/mcp")] if url.endswith("/mcp") else url


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


@router.get("/embed.js")
def loader():
    return Response(_asset("embed.js"), media_type="application/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=300"})


@router.get("/w/{public_id}")
def page(public_id: str):
    db = open_session()
    try:
        widget, _application, _connector = embed.public_widget(db, public_id)
        ancestors = embed.frame_ancestors(widget)
    except HubError:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Chat</title><p>This chat is not available.</p>",
                            status_code=404, headers={"Content-Security-Policy": "default-src 'none'; frame-ancestors *"})
    finally:
        db.close()
    nonce = secrets.token_urlsafe(18)
    html = (_asset("widget.html").replace("{{NONCE}}", nonce).replace("{{WIDGET}}", public_id)
            .replace("{{CSS}}", _asset("widget.css")).replace("{{JS}}", _asset("widget.js")))
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
           f"img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors {ancestors}")
    return HTMLResponse(html, headers={"Content-Security-Policy": csp})


@router.get("/w/{public_id}/config")
def config(public_id: str, request: Request):
    settings = get_settings()
    db = open_session()
    try:
        widget, application, connector = embed.public_widget(db, public_id)
        signed = embed.resolve_session(db, widget, _bearer(request), settings)
        chat = chat_settings.setting(db, application.id)
        body = {
            "app": application.name, "title": widget.title or application.name, "accent": widget.accent,
            "position": widget.position, "available": bool(chat.enabled and connector.status == "active"),
            "welcome_message": chat.welcome_message, "suggestions": list(chat.suggestions or []),
            "sign_in": embed.sign_in_form(connector),
            "user": {"name": signed.name, "preview": signed.admin_id is not None} if signed else None,
        }
        allowed = list(widget.allowed_origins or [])
        db.commit()
    finally:
        db.close()
    response = ok(body)
    origin = request.headers.get("origin")
    # The loader on an allowed site reads the colour and side for its button; nothing private is here.
    if origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


@router.post("/w/{public_id}/sign-in")
async def sign_in(public_id: str, request: Request):
    body = await read_body(request)
    settings = get_settings()
    db = open_session()
    try:
        widget, application, connector = embed.public_widget(db, public_id)
        hit(f"embed-sign-in:{widget.id}:{client_host(request)}", 10, 600)
        result = await embed.sign_in(db, widget, application, connector,
                                     body.get("fields") if isinstance(body, dict) else None, settings)
        db.commit()
    finally:
        db.close()
    return ok(result)


@router.post("/w/{public_id}/sign-in-token")
async def sign_in_token(public_id: str, request: Request):
    """The host page is already signed in to the app and hands its user's app token to the widget."""

    body = await read_body(request)
    settings = get_settings()
    db = open_session()
    try:
        widget, application, connector = embed.public_widget(db, public_id)
        hit(f"embed-sign-in:{widget.id}:{client_host(request)}", 30, 600)
        result = await embed.sign_in_with_token(db, widget, application, connector,
                                                body.get("token") if isinstance(body, dict) else None, settings)
        db.commit()
    finally:
        db.close()
    return ok(result)


@router.post("/w/{public_id}/sign-out")
def sign_out(public_id: str, request: Request):
    db = open_session()
    try:
        widget, application, _connector = embed.public_widget(db, public_id)
        embed.sign_out(db, widget, application, _bearer(request), get_settings())
        db.commit()
    finally:
        db.close()
    return ok({"signed_out": True})


@router.post("/w/{public_id}/turn")
async def turn(public_id: str, request: Request):
    body = await read_body(request)
    settings = get_settings()
    db = open_session()
    try:
        widget, application, connector = embed.public_widget(db, public_id)
        signed = embed.resolve_session(db, widget, _bearer(request), settings)
        if signed is None:
            raise HubError("SIGN_IN_REQUIRED", f"Sign in to {application.name} to chat", 401)
        caller = embed.caller_for(application, connector, signed)
        request_body = {key: body.get(key) for key in ("message", "history", "locale") if key in body} \
            if isinstance(body, dict) else body
        prepared = await engine.Turn(db, caller, engine.parse_request(request_body), None, settings,
                                     user_token=signed.token, subject=f"embed:{signed.link.id}").prepare()
    except BaseException:
        db.close()
        raise
    return stream_turn(db, prepared)
