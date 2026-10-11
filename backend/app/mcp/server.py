"""MCP runtime mounted beside the admin API. Wire handling stays in the official SDK.

Tools are read from the database on every request and scoped to the calling client key,
so publishing, disabling or revoking takes effect on the next request with nothing to
re-register. Discovery is not authorization: every call is re-checked from scratch.
"""

import json
import logging

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, GetPromptResult, Prompt, TextContent, Tool
from pydantic import AnyHttpUrl

from app.config import Settings, get_settings
from app.connectors.discovery import sync_source_permissions
from app.errors import HubError
from app.ids import as_utc, new_trace_id
from app.persistence.session import open_session
from app.privacy.pii_inspector import tree_contains_pii
from app.security.audit import record_audit
from app.security.clients import READ_SCOPE, require_caller, resolve_caller
from app.services import skills
from app.tools import catalog, dispatch
from mcp.server import MCPServer

logger = logging.getLogger("hub.mcp")


def _result(payload: dict) -> CallToolResult:
    text = json.dumps(payload, ensure_ascii=False)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=payload)


def _error(code: str, message: str, trace: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"{code}: {message} (trace {trace})")], is_error=True)


class HubMCPServer(MCPServer):
    async def list_tools(self) -> list[Tool]:
        token = get_access_token()
        if token is None:
            return []
        try:
            db = open_session()
        except RuntimeError:
            return []
        try:
            caller = resolve_caller(db, token.token)
            if caller is None:
                return []
            try:
                await sync_source_permissions(db, caller.connector, caller.application, get_settings())
                visible = catalog.visible_tools(db, caller)
                db.commit()
                return visible
            except HubError:
                db.rollback()
                # A failed policy fetch must not expose yesterday's permissions.
                return []
        finally:
            db.close()

    async def call_tool(self, name, arguments, context=None) -> CallToolResult:
        try:
            db = open_session()
        except RuntimeError:
            return _error("UNAVAILABLE", "The hub database is not ready", new_trace_id())
        token = get_access_token()
        headers = getattr(context, "headers", None) if context is not None else None
        try:
            outcome = await dispatch.execute(
                db, name, arguments, delegation=headers.get("x-hub-delegation") if headers else None,
                caller_for=lambda session: require_caller(session, token.token if token else None))
        finally:
            db.close()
        if outcome.error is not None:
            return _error(outcome.error.code, outcome.error.message, outcome.trace_id)
        return _result(outcome.payload)

    async def list_prompts(self) -> list[Prompt]:
        """Skills of the caller's app whose tools this key may call."""

        token = get_access_token()
        if token is None:
            return []
        try:
            db = open_session()
        except RuntimeError:
            return []
        try:
            caller = resolve_caller(db, token.token)
            return skills.visible_prompts(db, caller) if caller else []
        finally:
            db.close()

    async def get_prompt(self, name, arguments=None, context=None) -> GetPromptResult:
        token = get_access_token()
        trace = new_trace_id()
        safe_name = dispatch.safe_name(name)
        try:
            db = open_session()
        except RuntimeError as exc:
            raise MCPError(code=INVALID_PARAMS, message="The hub database is not ready") from exc
        try:
            caller = require_caller(db, token.token if token else None)
            try:
                if tree_contains_pii(arguments or {}):
                    raise HubError("PII_DETECTED", "Input blocked by privacy policy", 422)
                result = skills.get_prompt(db, caller, safe_name, arguments)
            except HubError as exc:
                record_audit(db, action="skill.use", actor_ref=caller.actor_ref, app_key=caller.application.key,
                             environment=caller.application.environment, tool_key=safe_name, trace_id=trace,
                             result="denied" if exc.status_code in {401, 403, 404} else "error", error_code=exc.code)
                db.commit()
                raise MCPError(code=INVALID_PARAMS, message=f"{exc.code}: {exc.message} (trace {trace})") from exc
            record_audit(db, action="skill.use", actor_ref=caller.actor_ref, app_key=caller.application.key,
                         environment=caller.application.environment, tool_key=safe_name, trace_id=trace, result="success")
            db.commit()
            return result
        except HubError as exc:
            raise MCPError(code=INVALID_PARAMS, message=f"{exc.code}: {exc.message}") from exc
        finally:
            db.close()


class HubTokenVerifier(TokenVerifier):
    def __init__(self, resource: str) -> None:
        self._resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            db = open_session()
        except RuntimeError:
            return None
        try:
            caller = resolve_caller(db, token)
            if caller is None:
                return None
            identity = caller.identity
            expires = int(as_utc(identity.expires_at).timestamp()) if identity.expires_at else None
            return AccessToken(token=token, client_id=identity.id, scopes=list(identity.scopes),
                               expires_at=expires, resource=self._resource)
        finally:
            db.close()


def _hosts(settings: Settings) -> list[str]:
    hosts: list[str] = []
    for host in settings.host_list:
        hosts.append(host)
        if ":" not in host:
            hosts.append(f"{host}:*")
    return hosts


def build_mcp_server(settings: Settings) -> MCPServer:
    return HubMCPServer(
        "MCP Hub",
        instructions=catalog.SERVER_INSTRUCTIONS,
        token_verifier=HubTokenVerifier(settings.mcp_public_url),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.mcp_issuer_url),
            resource_server_url=AnyHttpUrl(settings.mcp_public_url),
            required_scopes=[READ_SCOPE],
            validate_token_resource=True,
        ),
    )


def transport_security(settings: Settings) -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_hosts(settings),
        allowed_origins=settings.origin_list,
    )
