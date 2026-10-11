"""FastAPI admin API and mounted official MCP Streamable HTTP app."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.api import chat
from app.api.v1 import access, activity, auth, connectors, modules, providers, skills, system, tools
from app.config import get_settings
from app.errors import HubError
from app.mcp.server import build_mcp_server, transport_security
from app.persistence.session import assert_schema_current, init_engine, open_session
from app.security.audit import SafeJSONFormatter

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


class SecurityHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(SafeJSONFormatter())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(SafeJSONFormatter())
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
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="MCP Hub", version=__version__, lifespan=lifespan)
    app.state.mcp = mcp
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
    # Mount last so /api and /health stay reachable. The SDK app serves /mcp.
    app.mount("/", mcp_app)
    return app


app = create_app()
