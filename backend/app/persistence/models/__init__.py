"""SQLAlchemy models for hub configuration and audit metadata."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.ids import new_id, utcnow
from app.persistence.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (Index("ix_admin_users_activation_token_hash", "activation_token_hash", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="super_admin")
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auth_method: Mapped[str] = mapped_column(String(16), nullable=False, default="totp")
    activation_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_totp_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # While MFA is required, an account that never enrolled may enroll until then (created or reset
    # + MFA_ENROLL_HOURS); afterwards a super admin must reset it. Empty: created_at + the window.
    mfa_enroll_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("key", "environment", name="uq_application_key_env"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="dev")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    tenant_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AdminApplicationScope(Base):
    __tablename__ = "admin_application_scopes"
    __table_args__ = (UniqueConstraint("user_id", "app_id", name="uq_admin_application_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Connector(Base):
    __tablename__ = "connectors"
    __table_args__ = (Index("ix_connector_status", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), unique=True)
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False, default="http_contract")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    manifest_path: Mapped[str] = mapped_column(String(200), nullable=False, default="/api/ai/v1/capabilities")
    health_path: Mapped[str] = mapped_column(String(200), nullable=False, default="/api/ai/v1/health")
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # draft -> active <-> paused; archived is permanent.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class ConnectorSecret(Base):
    __tablename__ = "connector_secrets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    delegation_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorHealthCheck(Base):
    __tablename__ = "connector_health_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class ContractSnapshot(Base):
    __tablename__ = "contract_snapshots"
    __table_args__ = (UniqueConstraint("connector_id", "manifest_hash", name="uq_contract_snapshot"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ModuleDefinition(Base):
    """A data source the connected application published in its manifest."""

    __tablename__ = "module_definitions"
    __table_args__ = (UniqueConstraint("app_id", "module_key", name="uq_module_app_key"), Index("ix_module_app_key", "app_id", "module_key"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    supported_operations: Mapped[list] = mapped_column(JSON, nullable=False)
    readable_fields: Mapped[list] = mapped_column(JSON, nullable=False)
    writable_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    max_page_size: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    risk: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ModuleSetting(Base):
    __tablename__ = "module_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    module_id: Mapped[str] = mapped_column(ForeignKey("module_definitions.id", ondelete="CASCADE"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    operations_enabled: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # "METHOD /path" of the read endpoint that feeds reports; null means automatic.
    report_endpoint: Mapped[str | None] = mapped_column(String(320), nullable=True)


class FieldPolicy(Base):
    __tablename__ = "field_policies"
    __table_args__ = (UniqueConstraint("module_id", "field_path", name="uq_field_policy"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    module_id: Mapped[str] = mapped_column(ForeignKey("module_definitions.id", ondelete="CASCADE"), nullable=False)
    field_path: Mapped[str] = mapped_column(String(200), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="developer")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RestToolMapping(Base):
    """The fixed source route a tool calls. Callers never supply a host, path or method."""

    __tablename__ = "rest_tool_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path_template: Mapped[str] = mapped_column(String(300), nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    max_payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=1_048_576)
    query_params: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pagination: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_mapping: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    safe_query: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_user_context: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tenant_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_level: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")


class ToolDefinition(Base):
    """An admin-configured MCP tool. Lifecycle: draft -> published <-> disabled; archived is final."""

    __tablename__ = "tool_definitions"
    __table_args__ = (
        UniqueConstraint("connector_id", "tool_key", "version", name="uq_tool_connector_key_version"),
        Index("uq_published_mcp_name", "mcp_name", unique=True,
              sqlite_where=text("status = 'published'"), postgresql_where=text("status = 'published'")),
        Index("ix_tool_connector_status", "connector_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tool_key: Mapped[str] = mapped_column(String(120), nullable=False)
    mcp_name: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    mapping_id: Mapped[str] = mapped_column(ForeignKey("rest_tool_mappings.id", ondelete="CASCADE"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # read | report | create | update | delete
    template: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    report_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk: Mapped[str] = mapped_column(String(32), nullable=False, default="read_only")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolTestRun(Base):
    __tablename__ = "tool_test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    case_results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ServiceIdentity(Base):
    """A client key: one application, read access, optional write scope and tool allowlist."""

    __tablename__ = "service_identities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    # Null means every tool the key's permissions allow.
    allowed_tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_trace", "trace_id"),
        Index("ix_audit_owner_created", "actor_ref", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    app_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    module_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class Skill(Base):
    """A reusable instruction for AI clients, served as an MCP prompt to one app's client keys.

    Text only: admins write instructions and name the tools to use; nothing is executed.
    """

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("app_id", "key", name="uq_skill_app_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"name", "description", "required"}]; values replace {{name}} in the instructions.
    arguments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # MCP tool names the skill relies on. A client key that cannot call them does not see the skill.
    tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MemorySetting(Base):
    """Opt-in per app: whether AI clients may keep notes about the signed-in user in the Hub."""

    __tablename__ = "memory_settings"

    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    max_notes: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class UserMemory(Base):
    """One remembered note or profile preference of one end user. Content is encrypted.

    The user is stored as a keyed hash of the verified delegation (app, tenant, user), so
    rows cannot be linked to a person without the Hub's key. Admins only see counts.
    """

    __tablename__ = "user_memories"
    __table_args__ = (Index("ix_memory_subject", "app_id", "subject", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    # profile: one value per key, such as language or currency. note: free text.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ToolSwitch(Base):
    """An admin's off switch for one tool of one app. No row means on.

    It only ever removes a tool for every client key of the app; it cannot grant one.
    """

    __tablename__ = "tool_switches"
    __table_args__ = (UniqueConstraint("app_id", "tool_name", name="uq_tool_switch_app_tool"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ChatSetting(Base):
    """The Hub-hosted AI chat for one app: off until an admin turns it on.

    The Hub never stores conversations; these are the assistant's settings only.
    """

    __tablename__ = "chat_settings"

    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "anthropic", "openai_compatible" (the gateway in the environment) or a ModelProvider key.
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="anthropic")
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="claude-opus-5-5")
    effort: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    welcome_message: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    suggestions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    # Model gateway: the models the app may call ("provider/model" or "provider/*"; empty = every
    # ready model) and its token budget per calendar month (0 = no budget).
    gateway_models: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    monthly_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class GatewayUsage(Base):
    """Model gateway calls and tokens per app, model and month. Counts only, never messages."""

    __tablename__ = "gateway_usage"
    __table_args__ = (UniqueConstraint("app_id", "period", "model", name="uq_gateway_usage_app_period_model"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    app_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM, UTC
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ModelProvider(Base):
    """An OpenAI-compatible model provider a super admin added for the Hub chat.

    The API key is encrypted with the Hub key and never returned; extra headers are not secret.
    """

    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # bearer (Authorization: Bearer), header (a named header such as api-key) or none (local servers).
    auth_style: Mapped[str] = mapped_column(String(16), nullable=False, default="bearer")
    auth_header: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False, default="")
    api_key_hint: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    headers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # max_tokens, max_completion_tokens (newer OpenAI models) or none.
    token_param: Mapped[str] = mapped_column(String(32), nullable=False, default="max_tokens")
    # full sends tool schemas as they are; basic strips keywords strict providers reject.
    tool_schema: Mapped[str] = mapped_column(String(16), nullable=False, default="full")
    streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    models: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="untested")
    status_message: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
