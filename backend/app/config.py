"""Environment configuration. Secrets come from the environment, never from code."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.errors import HubError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"
    database_url: str = "sqlite+pysqlite:///:memory:"
    secret_encryption_key: str = ""
    session_signing_key: str = ""
    admin_initial_email: str = "admin@localhost"
    admin_initial_password: str = ""
    mfa_required: bool = False
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
    log_level: str = "INFO"
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

    def assert_production_safe(self) -> None:
        if self.environment != "production":
            return
        problems: list[str] = []
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if not self.mfa_required:
            problems.append("MFA_REQUIRED must be true")
        if self.allow_insecure_http or self.allow_insecure_tls:
            problems.append("insecure HTTP/TLS is disabled in production")
        if self.egress_allow_loopback or self.egress_allow_private:
            problems.append("private and loopback egress are disabled in production")
        if not self.secret_encryption_key or not self.session_signing_key:
            problems.append("encryption and session keys are required")
        if not self.egress_allowed_hosts and not self.egress_allowed_cidrs:
            problems.append("approved egress hosts or CIDRs are required")
        if self.database_url.startswith("sqlite"):
            problems.append("PostgreSQL metadata storage is required")
        if problems:
            raise HubError("UNSAFE_CONFIGURATION", "; ".join(problems), 500)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_safe()
    return settings
