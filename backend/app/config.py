"""Environment configuration. Secrets come from the environment, never from code."""

from functools import lru_cache
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.errors import HubError

# Values printed in .env.example and the docs; a deployment that keeps one is not secret.
EXAMPLE_VALUES = {"replace-with-long-random-string", "replace-with-fernet-key", "ChangeMe-Now-12", "change-me"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"
    database_url: str = "sqlite+pysqlite:///:memory:"
    secret_encryption_key: str = ""
    # During a key rotation: the old keys, comma-separated. They decrypt only; run
    # `python -m app.rotate_keys` to re-encrypt everything with SECRET_ENCRYPTION_KEY, then remove them.
    secret_encryption_key_previous: str = ""
    session_signing_key: str = ""
    admin_initial_email: str = "admin@localhost"
    admin_initial_password: str = ""
    # Optional until invitations are enabled; activation email delivery fails closed without it.
    admin_console_url: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls_mode: str = "starttls"
    mfa_required: bool = False
    # Hours a new (or reset) admin has to set up MFA while it is required; later a super admin resets it.
    mfa_enroll_hours: int = Field(default=72, ge=1, le=720)
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allowed_hosts: str = "localhost,127.0.0.1,localhost:8000,127.0.0.1:8000"
    mcp_public_url: str = "http://127.0.0.1:8000/mcp"
    mcp_issuer_url: str = "http://127.0.0.1:8000"
    egress_allow_private: bool = False
    egress_allow_loopback: bool = False
    egress_allowed_ports: str = "80,443"
    egress_allowed_hosts: str = ""
    egress_allowed_cidrs: str = ""
    allow_insecure_http: bool = False
    allow_insecure_tls: bool = False
    # Records per source page and per read-tool response.
    max_records: int = Field(default=50, ge=1, le=50)
    max_payload_bytes: int = Field(default=1_048_576, ge=1024, le=1048576)
    # The reporting tool pages through a source up to this many records or seconds,
    # then answers with partial coverage instead of failing.
    report_max_records: int = Field(default=1000, ge=50, le=5000)
    report_timeout_seconds: int = Field(default=20, ge=1, le=120)
    audit_retention_days: int = Field(default=90, ge=1, le=3650)
    # Hours between automatic purges of expired audit rows, sessions and memories; 0 turns it off.
    purge_interval_hours: int = Field(default=6, ge=0, le=168)
    log_level: str = "INFO"
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_redis_url: str = Field(default="", repr=False)
    rate_limit_redis_password: str = Field(default="", repr=False)
    rate_limit_namespace: str = Field(default="mcp-hub", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    circuit_failure_threshold: int = 5
    circuit_open_seconds: int = 30
    tool_rate_limit: int = Field(default=60, ge=1, le=10000)
    tool_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    login_rate_limit: int = Field(default=10, ge=1, le=100)
    mfa_rate_limit: int = Field(default=10, ge=1, le=100)
    tool_concurrency: int = Field(default=8, ge=1, le=128)
    connector_concurrency: int = Field(default=8, ge=1, le=128)
    session_hours: int = Field(default=8, ge=1, le=24)
    cookie_name: str = "hub_session"
    # Hub chat. The model keys live here only; apps and browsers never see them.
    anthropic_api_key: str = ""
    chat_openai_base_url: str = ""
    chat_openai_api_key: str = ""
    chat_max_tokens: int = Field(default=16000, ge=1024, le=64000)
    chat_timeout_seconds: int = Field(default=120, ge=10, le=600)
    chat_rate_limit: int = Field(default=20, ge=1, le=1000)
    # The console assistant reads this repository (README, docs, code); empty means the one this code runs from.
    assistant_repo_path: str = ""
    # Model gateway calls per app per minute, across all its users (end_user_id comes from the app).
    gateway_app_rate_limit: int = Field(default=300, ge=1, le=100000)
    # Where admin-added model providers may live. Empty hosts means any public host; private and
    # loopback addresses still follow EGRESS_ALLOW_PRIVATE / EGRESS_ALLOW_LOOPBACK.
    model_egress_allowed_hosts: str = ""
    model_egress_allowed_ports: str = "443,80,11434,1234"

    @field_validator("environment")
    @classmethod
    def _env(cls, value: str) -> str:
        allowed = {"dev", "test", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {sorted(allowed)}")
        return value

    def csv(self, raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def origin_list(self) -> list[str]:
        return self.csv(self.allowed_origins)

    @property
    def host_list(self) -> list[str]:
        return self.csv(self.allowed_hosts)

    @property
    def port_list(self) -> set[int]:
        return {int(item) for item in self.csv(self.egress_allowed_ports)}

    @property
    def smtp_configured(self) -> bool:
        base = self.admin_console_url or self.mcp_issuer_url
        return (all((self.smtp_host, self.smtp_username, self.smtp_password, self.smtp_from))
                and self.smtp_tls_mode in {"starttls", "ssl"}
                and (self.environment != "production" or base.startswith("https://")))

    def assert_production_safe(self) -> None:
        if self.environment != "production":
            return
        problems: list[str] = []
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        # MFA_REQUIRED is the operator's choice: recommended, but password-only admins may run in production.
        if self.allow_insecure_http or self.allow_insecure_tls:
            problems.append("insecure HTTP/TLS is disabled in production")
        if self.egress_allow_loopback or self.egress_allow_private:
            problems.append("private and loopback egress are disabled in production")
        if not self.secret_encryption_key or not self.session_signing_key:
            problems.append("encryption and session keys are required")
        elif len(self.session_signing_key) < 32 or self.session_signing_key in EXAMPLE_VALUES:
            problems.append("SESSION_SIGNING_KEY must be a random value of 32+ characters")
        if self.admin_initial_password in EXAMPLE_VALUES:
            problems.append("ADMIN_INITIAL_PASSWORD is the published example; choose your own")
        if not self.mcp_public_url.startswith("https://") or not self.mcp_issuer_url.startswith("https://"):
            problems.append("MCP_PUBLIC_URL and MCP_ISSUER_URL must be https addresses")
        if any(not origin.startswith("https://") for origin in self.origin_list):
            problems.append("ALLOWED_ORIGINS must be https origins")
        public = urlsplit(self.mcp_public_url)
        hosts = {host.lower() for host in self.host_list}
        if public.hostname and public.netloc.lower() not in hosts and public.hostname.lower() not in hosts:
            problems.append("ALLOWED_HOSTS must include the MCP_PUBLIC_URL host")
        if not self.egress_allowed_hosts and not self.egress_allowed_cidrs:
            problems.append("approved egress hosts or CIDRs are required")
        if self.database_url.startswith("sqlite"):
            problems.append("PostgreSQL metadata storage is required")
        redis = urlsplit(self.rate_limit_redis_url)
        if self.rate_limit_backend != "redis" or redis.scheme not in {"redis", "rediss"} or not redis.hostname:
            problems.append("a shared Redis rate limiter is required")
        elif len(unquote(redis.password) if redis.password else self.rate_limit_redis_password) < 32:
            problems.append("Redis authentication requires a random password of 32+ characters")
        if problems:
            raise HubError("UNSAFE_CONFIGURATION", "; ".join(problems), 500)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_safe()
    return settings
