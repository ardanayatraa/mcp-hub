"""MCP client keys. A key belongs to one application, always reads, and may write if granted."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import HubError
from app.ids import as_utc, utcnow
from app.persistence.models import Application, Connector, McpAccessProfile, ServiceIdentity
from app.security.auth import lookup_service_token

READ_SCOPE = "mcp:tools"
WRITE_SCOPE = "tools:write"


@dataclass
class Caller:
    identity: ServiceIdentity
    application: Application
    connector: Connector | None
    profile: McpAccessProfile | None = None

    @property
    def actor_ref(self) -> str:
        return f"service:{self.identity.id}"

    @property
    def can_write(self) -> bool:
        return WRITE_SCOPE in (self.identity.scopes or [])

    def allows(self, tool_name: str) -> bool:
        allowed = self.identity.allowed_tools
        return (allowed is None or tool_name in allowed) and (self.profile is None or tool_name in (self.profile.tools or []))

    def allows_module(self, module_key: str) -> bool:
        return self.profile is None or module_key in (self.profile.modules or [])


def resolve_caller(db: Session, token: str | None, *, touch: bool = False) -> Caller | None:
    identity = lookup_service_token(db, token or "")
    if identity is None or READ_SCOPE not in (identity.scopes or []):
        return None
    application = db.get(Application, identity.app_id)
    if application is None or application.status != "active":
        return None
    profile = db.get(McpAccessProfile, identity.profile_id) if identity.profile_id else None
    if identity.profile_id and (profile is None or not profile.enabled or profile.app_id != application.id):
        return None
    if touch and (identity.last_used_at is None or utcnow() - as_utc(identity.last_used_at) > timedelta(minutes=1)):
        identity.last_used_at = utcnow()
    connector = db.scalar(select(Connector).where(Connector.app_id == application.id))
    return Caller(identity, application, connector, profile)


def require_caller(db: Session, token: str | None) -> Caller:
    caller = resolve_caller(db, token, touch=True)
    if caller is None:
        raise HubError("UNAUTHENTICATED", "Authentication is required", 401)
    return caller
