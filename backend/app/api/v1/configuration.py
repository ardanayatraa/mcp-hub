"""Strict configuration types shared by HTTP endpoints and service callers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import HubError

Environment = Literal["dev", "test", "staging", "production"]
Template = Literal["read", "report", "create", "update", "delete"]


class ConnectorConfiguration(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    name: str = Field(default="", max_length=200)
    app_key: str = Field(min_length=1, max_length=64)
    environment: Environment = "dev"
    connector_type: Literal["http_contract", "data_push", "source_managed"] = "http_contract"
    base_url: str = Field(min_length=1, max_length=2048)
    auth_type: Literal["bearer"] = "bearer"
    secret: str = Field(min_length=8, max_length=500)
    delegation_secret: str = Field(default="", max_length=500)
    manifest_path: str = Field(default="/api/ai/v1/capabilities", max_length=500)
    health_path: str = Field(default="/api/ai/v1/health", max_length=500)
    timeout_ms: int = Field(default=5000, ge=100, le=30000)
    tls_verify: bool = True


class ConnectorChanges(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    connector_type: Literal["http_contract", "source_managed"] = "http_contract"
    name: str = Field(default="", min_length=1, max_length=200)
    base_url: str = Field(default="", min_length=1, max_length=2048)
    manifest_path: str = Field(default="/api/ai/v1/capabilities", max_length=500)
    health_path: str = Field(default="/api/ai/v1/health", max_length=500)
    timeout_ms: int = Field(default=5000, ge=100, le=30000)
    tls_verify: bool = True


class ToolChanges(BaseModel):
    """Editable tool settings. Source authorization fields are accepted only if they agree with the contract."""

    model_config = ConfigDict(strict=True, extra="ignore")
    title: str | None = Field(default=None, max_length=120)
    description: str = Field(default="", max_length=1000)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    path_template: str = Field(default="", max_length=500)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    allow_fields: list[str] = Field(default_factory=list, max_length=100)
    report: dict | None = None
    timeout_ms: int = Field(default=5000, ge=100, le=30000)
    max_payload_bytes: int = Field(default=1048576, ge=1024, le=1048576)
    pagination: dict[str, str] = Field(default_factory=dict)
    error_mapping: dict[str, str] = Field(default_factory=dict)
    audit_level: Literal["minimal", "standard", "detailed"] = "standard"
    requires_user_context: bool | None = None
    tenant_field: str | None = Field(default=None, max_length=100)
    safe_query: bool | None = None
    risk: Literal["read_only", "write"] | None = None


class ToolConfiguration(ToolChanges):
    connector_id: str = Field(min_length=1, max_length=36)
    module_key: str = Field(min_length=1, max_length=64)
    template: Template = "read"
    tool_key: str = Field(min_length=1, max_length=120)
    version: str = "1.0.0"


class IdentityCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(default="gateway", min_length=1, max_length=120)
    app_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    environment: Environment = "dev"
    ttl_days: int = Field(default=90, ge=1, le=365)
    write: bool = False
    allowed_tools: list[str] | None = Field(default=None, max_length=200)


class IdentityChanges(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(default="gateway", min_length=1, max_length=120)
    write: bool = False
    allowed_tools: list[str] | None = Field(default=None, max_length=200)


class UserCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    email: str | None = Field(default=None, min_length=3, max_length=320)
    role: Literal["hub_admin", "app_admin", "auditor"]
    password: str | None = Field(default=None, min_length=12, max_length=200)
    app_ids: list[str] = Field(default_factory=list, max_length=500)


class UserChanges(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    role: Literal["hub_admin", "app_admin", "auditor"] = "auditor"
    is_active: bool = True
    app_ids: list[str] = Field(default_factory=list, max_length=500)
    # Clears the admin's authenticator and opens a new enrollment window.
    reset_mfa: bool = False


class ModuleChanges(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    enabled: bool = False
    operations: list[str] = Field(default_factory=list, max_length=4)
    fields: list[dict] = Field(default_factory=list, max_length=100)
    report_endpoint: str | None = Field(default=None, max_length=320)


def checked(model, payload, *, partial=False):
    try:
        return model.model_validate(payload).model_dump(exclude_unset=partial)
    except ValidationError as exc:
        # Pydantic's detailed errors can contain submitted secrets; name the fields only.
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"] and error["type"] != "extra_forbidden"})
        unexpected = any(error["type"] == "extra_forbidden" for error in exc.errors())
        detail = ", ".join(fields[:5]) if fields else ("an unexpected field" if unexpected else "the request")
        raise HubError("VALIDATION_FAILED", f"Invalid value for {detail}", 422) from exc
