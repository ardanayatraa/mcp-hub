"""FastAPI admin API and mounted official MCP Streamable HTTP app."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.api import chat, gateway
from app.api.v1 import access, activity, auth, connectors, modules, providers, skills, system, tools
from app.config import get_settings
from app.errors import HubError
from app.mcp.server import build_mcp_server, transport_security
from app.persistence.session import assert_schema_current, init_engine, open_session
from app.security.audit import SafeJSONFormatter
from app.security.crypto import keyring

logger = logging.getLogger("hub")


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.max_bytes if scope.get("path", "").startswith("/mcp") else min(self.max_bytes, get_settings().max_payload_bytes)
        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length", b"")
        messages, size = [], 0
        oversized = declared.isdigit() and int(declared) > limit
        while not oversized:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > limit:
                oversized = True
                break
            messages.append(message)
            if not message.get("more_body", False):
                break
        if oversized:
            response = JSONResponse(
                {"success": False, "error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large"}},
                status_code=413,
            )
            return await response(scope, receive, send)
        async def replay():
            return messages.pop(0) if messages else await receive()
        return await self.app(scope, replay, send)


# FastAPI's API explorer, served in development only; its page loads scripts from a CDN.
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc"}
# Probes call these by the container's own address, which is not a public host name.
PROBE_PATHS = {"/health", "/ready"}


class HostCheckMiddleware:
    """Refuse requests whose Host is not in ALLOWED_HOSTS (DNS rebinding, poisoned links).

    /mcp keeps the MCP SDK's own check against the same list; the probes are exempt.
    """

    def __init__(self, app, hosts: list[str]) -> None:
        self.app = app
        self.exact = {host.lower() for host in hosts}
        self.any_port = {host.lower() for host in hosts if ":" not in host}

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if scope["type"] != "http" or path in PROBE_PATHS or path == "/mcp" or path.startswith("/mcp/"):
            return await self.app(scope, receive, send)
        host = dict(scope.get("headers", [])).get(b"host", b"").decode("latin-1").strip().lower()
        if host not in self.exact and host.rsplit(":", 1)[0] not in self.any_port:
            response = JSONResponse({"success": False, "error": {"code": "INVALID_HOST", "message": "Host is not allowed"}},
                                    status_code=400)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


class SecurityHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        # The backend answers JSON and event streams only; nothing it sends may run, load or be framed.
        if request.url.path not in DOCS_PATHS:
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if get_settings().cookie_secure:  # served over HTTPS
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def _purge_once(retention_days: int) -> dict:
    from app.services.backup import purge_expired

    db = open_session()
    try:
        removed = purge_expired(db, retention_days)
        db.commit()
        return removed
    finally:
        db.close()


async def _housekeeping(interval_hours: int) -> None:
    """Remove expired audit rows, sessions, MFA challenges and memories on a schedule (0 = never).

    Each process runs it; the deletes are idempotent, so several workers only repeat a no-op.
    """

    if interval_hours <= 0:
        return
    await asyncio.sleep(300)  # let the process settle; restarts do not purge in a burst
    while True:
        try:
            removed = await asyncio.to_thread(_purge_once, get_settings().audit_retention_days)
            logger.info("purge_expired", extra={"count": sum(removed.values())})
        except Exception as exc:  # noqa: BLE001 - a failed run waits for the next one
            logger.warning("purge_failed", extra={"error_type": type(exc).__name__})
        await asyncio.sleep(interval_hours * 3600)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(SafeJSONFormatter())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(SafeJSONFormatter())
    if settings.secret_encryption_key:
        keyring(settings.secret_encryption_key)  # a malformed current or previous key stops the start, not a request
    assert_schema_current(init_engine(settings.database_url))
    mcp = build_mcp_server(settings)
    mcp_app = mcp.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(settings),
        max_request_body_size=2 * 1024 * 1024,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # The mounted SDK app does not receive the parent lifespan, so this process
        # owns the one allowed session_manager.run() call. Tools are read per request.
        housekeeping = asyncio.create_task(_housekeeping(settings.purge_interval_hours))
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            housekeeping.cancel()
            with suppress(asyncio.CancelledError):
                await housekeeping

    # The API map is for developers: staging and production do not publish it.
    explorer = settings.environment == "dev"
    app = FastAPI(title="MCP Hub", version=__version__, lifespan=lifespan, docs_url="/docs" if explorer else None,
                  redoc_url="/redoc" if explorer else None, openapi_url="/openapi.json" if explorer else None)
    app.state.mcp = mcp
    app.add_middleware(HostCheckMiddleware, hosts=settings.host_list)
    app.add_middleware(SecurityHeaderMiddleware)
    app.add_middleware(BodyLimitMiddleware, max_bytes=max(settings.max_payload_bytes, 2 * 1024 * 1024))

    @app.exception_handler(HubError)
    async def _hub_error(_request: Request, exc: HubError):
        return JSONResponse(
            {"success": False, "error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, _exc: RequestValidationError):
        return JSONResponse(
            {"success": False, "error": {"code": "VALIDATION_FAILED", "message": "Request is invalid"}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception):
        if isinstance(exc, StarletteHTTPException):
            return JSONResponse(
                {"success": False, "error": {"code": "HTTP_ERROR", "message": "Request was rejected"}},
                status_code=exc.status_code,
            )
        logger.error("unhandled", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            {"success": False, "error": {"code": "INTERNAL", "message": "The request could not be completed"}},
            status_code=500,
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            db = open_session()
        except RuntimeError:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        try:
            db.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        finally:
            db.close()
        return {"status": "ready"}

    for module in (auth, connectors, modules, tools, skills, providers, access, activity, system):
        app.include_router(module.router, prefix="/api/admin/v1")
    # Called by apps' servers with a client key, like /mcp.
    app.include_router(chat.router)
    app.include_router(gateway.router)
    # Mount last so /api and /health stay reachable. The SDK app serves /mcp.
    app.mount("/", mcp_app)
    return app


app = create_app()
