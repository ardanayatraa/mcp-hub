"""OpenAI-compatible model providers super admins add for the Hub chat.

Any service that speaks the Chat Completions API works: hosted (OpenAI, OpenRouter, Groq,
DeepSeek, Mistral, Gemini, Together, ...), a company gateway, or a local server (Ollama,
LM Studio, vLLM). Keys are encrypted at rest and never returned; calls go through the same
destination checks as connectors, pinned to the addresses that passed them.
"""

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

import anthropic
import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.pinned_transport import pinned_transport
from app.connectors.ssrf_guard import validate_destination
from app.errors import HubError
from app.ids import as_utc, utcnow
from app.persistence.models import AdminUser, Application, ChatSetting, ModelProvider
from app.security.audit import record_audit
from app.security.crypto import decrypt_secret, encrypt_secret

ANTHROPIC = "anthropic"
ENV_GATEWAY = "openai_compatible"
RESERVED = {ANTHROPIC, ENV_GATEWAY, "claude", "hub", "none"}
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,119}$")
HEADER_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
FORBIDDEN_HEADERS = {"host", "content-length", "content-type", "transfer-encoding", "connection", "cookie",
                     "authorization", "accept", "accept-encoding", "te", "upgrade", "proxy-authorization"}
AUTH_STYLES = ("bearer", "header", "none")
TOKEN_PARAMS = ("max_tokens", "max_completion_tokens", "none")
TOOL_SCHEMAS = ("full", "basic")
MAX_MODELS = 500
FIELDS = {"key", "name", "base_url", "auth_style", "auth_header", "api_key", "clear_api_key", "headers", "token_param",
          "tool_schema", "streaming", "default_model", "enabled"}

PRESETS = [
    {"key": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "token_param": "max_completion_tokens",
     "hint": "API key from platform.openai.com."},
    {"key": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "headers": {"X-Title": "MCP Hub"}, "hint": "One key for hundreds of models. Model names look like vendor/model."},
    {"key": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1", "hint": "Very fast open models."},
    {"key": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "hint": "API key from platform.deepseek.com."},
    {"key": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai/v1", "hint": "API key from console.mistral.ai."},
    {"key": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "tool_schema": "basic", "hint": "Gemini's OpenAI-compatible endpoint, with an AI Studio key."},
    {"key": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1", "hint": "Open models, pay per token."},
    {"key": "fireworks", "name": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1",
     "hint": "Model names look like accounts/fireworks/models/..."},
    {"key": "xai", "name": "xAI", "base_url": "https://api.x.ai/v1", "hint": "Grok models."},
    {"key": "cerebras", "name": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "hint": "Very fast inference."},
    {"key": "azure", "name": "Azure OpenAI", "base_url": "https://YOUR-RESOURCE.openai.azure.com/openai/v1",
     "auth_style": "header", "auth_header": "api-key", "token_param": "max_completion_tokens",
     "hint": "Replace YOUR-RESOURCE. The model is your deployment name."},
    {"key": "ollama", "name": "Ollama (local)", "base_url": "http://127.0.0.1:11434/v1", "auth_style": "none",
     "hint": "Models running on your own machine or server. Needs a model that supports tools."},
    {"key": "lmstudio", "name": "LM Studio (local)", "base_url": "http://127.0.0.1:1234/v1", "auth_style": "none",
     "hint": "LM Studio's local server."},
    {"key": "custom", "name": "Other OpenAI-compatible", "base_url": "",
     "hint": "Any gateway that serves /chat/completions, for example Telixcell, vLLM or LiteLLM."},
]


@dataclass
class Endpoint:
    """Everything a conversation needs to call one OpenAI-compatible provider."""

    label: str
    base_url: str
    headers: dict[str, str] = field(default_factory=dict)
    token_param: str = "max_tokens"
    tool_schema: str = "full"
    streaming: bool = True


def model_settings(settings: Settings) -> Settings:
    """The connector egress rules with the model provider host and port lists."""

    return settings.model_copy(update={"egress_allowed_hosts": settings.model_egress_allowed_hosts,
                                       "egress_allowed_cidrs": "",
                                       "egress_allowed_ports": settings.model_egress_allowed_ports})


def _worded(exc: HubError) -> HubError:
    return HubError(exc.code, exc.message.replace("Connector", "Provider").replace("connector", "provider"), exc.status_code)


def resolve(url: str, settings: Settings) -> tuple[str, int, list[str]]:
    """Host, port and the addresses that passed the egress rules (resolved now, against rebinding)."""

    try:
        return validate_destination(url, model_settings(settings))
    except HubError as exc:
        raise _worded(exc) from exc


def http_client(endpoint: Endpoint, settings: Settings, destination: tuple[str, int, list[str]]) -> httpx.AsyncClient:
    host, port, addresses = destination
    return httpx.AsyncClient(base_url=endpoint.base_url, headers=endpoint.headers, timeout=settings.chat_timeout_seconds,
                             transport=pinned_transport(host, port, addresses, verify=True), follow_redirects=False)


async def open_client(endpoint: Endpoint, settings: Settings) -> httpx.AsyncClient:
    destination = await asyncio.to_thread(resolve, endpoint.base_url + "/chat/completions", settings)
    return http_client(endpoint, settings, destination)


def _auth_headers(row: ModelProvider, settings: Settings) -> dict[str, str]:
    headers = dict(row.headers or {})
    if row.auth_style != "none" and row.api_key_ciphertext:
        secret = decrypt_secret(settings.secret_encryption_key, row.api_key_ciphertext)
        if row.auth_style == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        else:
            headers[row.auth_header] = secret
    return headers


def endpoint_for(db: Session, provider: str, settings: Settings) -> Endpoint | None:
    """The endpoint behind a chat provider key, or None for Claude. Fails when it is not usable."""

    if provider == ANTHROPIC:
        if not settings.anthropic_api_key:
            raise HubError("CHAT_NOT_CONFIGURED", "The Hub has no Anthropic API key yet. Ask an admin to add it.", 503)
        return None
    if provider == ENV_GATEWAY:
        if not settings.chat_openai_base_url:
            raise HubError("CHAT_NOT_CONFIGURED", "The OpenAI-compatible gateway is not configured on the Hub", 503)
        headers = {"Authorization": f"Bearer {settings.chat_openai_api_key}"} if settings.chat_openai_api_key else {}
        return Endpoint("Gateway (environment)", settings.chat_openai_base_url.rstrip("/"), headers)
    row = db.scalar(select(ModelProvider).where(ModelProvider.key == provider))
    if row is None or not row.enabled:
        raise HubError("CHAT_NOT_CONFIGURED", "This chat's model provider is missing or turned off. Ask an admin.", 503)
    if row.auth_style != "none" and not row.api_key_ciphertext:
        raise HubError("CHAT_NOT_CONFIGURED", f"{row.name} has no API key yet. Ask an admin to add it.", 503)
    return Endpoint(row.name, row.base_url, _auth_headers(row, settings), row.token_param, row.tool_schema, row.streaming)


def ready(db: Session, provider: str, settings: Settings) -> bool:
    try:
        endpoint_for(db, provider, settings)
    except HubError:
        return False
    return True


def exists(db: Session, provider: str) -> bool:
    return provider in (ANTHROPIC, ENV_GATEWAY) or db.scalar(select(ModelProvider.id).where(ModelProvider.key == provider)) is not None


# Administration ---------------------------------------------------------------------------


def _usage(db: Session) -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for key, name in db.execute(select(ChatSetting.provider, Application.name)
                                .join(Application, Application.id == ChatSetting.app_id)):
        used.setdefault(key, []).append(name)
    return used


def view(row: ModelProvider, used_by: list[str] | None = None) -> dict:
    return {"id": row.id, "key": row.key, "name": row.name, "base_url": row.base_url, "auth_style": row.auth_style,
            "auth_header": row.auth_header, "api_key_set": bool(row.api_key_ciphertext), "api_key_hint": row.api_key_hint,
            "headers": dict(row.headers or {}), "token_param": row.token_param, "tool_schema": row.tool_schema,
            "streaming": row.streaming, "default_model": row.default_model, "models": list(row.models or []),
            "enabled": row.enabled, "status": row.status, "status_message": row.status_message,
            "checked_at": as_utc(row.checked_at).isoformat() if row.checked_at else None,
            "used_by": sorted(used_by or []),
            "ready": row.enabled and (row.auth_style == "none" or bool(row.api_key_ciphertext))}


def listing(db: Session, settings: Settings) -> dict:
    used = _usage(db)
    rows = db.scalars(select(ModelProvider).order_by(ModelProvider.name))
    builtin = [{"key": ANTHROPIC, "name": "Claude (Anthropic)", "ready": bool(settings.anthropic_api_key),
                "configured_by": "ANTHROPIC_API_KEY", "used_by": sorted(used.get(ANTHROPIC, []))}]
    if settings.chat_openai_base_url or used.get(ENV_GATEWAY):
        builtin.append({"key": ENV_GATEWAY, "name": "Gateway (environment)", "ready": bool(settings.chat_openai_base_url),
                        "configured_by": "CHAT_OPENAI_BASE_URL", "used_by": sorted(used.get(ENV_GATEWAY, []))})
    return {"builtin": builtin, "providers": [view(row, used.get(row.key)) for row in rows]}


def _text(value, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HubError("VALIDATION_FAILED", f"{label} must be text of 1 to {maximum} characters", 422)
    return value.strip()


def _base_url(value, settings: Settings) -> str:
    url = _text(value, "Base URL", 500).rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise HubError("VALIDATION_FAILED", "Base URL must look like https://api.example.com/v1, without ? or #", 422)
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    try:
        resolve(url + "/chat/completions", settings)
    except HubError as exc:
        # An address that does not resolve yet may still be saved; everything else is refused now.
        if exc.code != "CONNECTOR_DNS":
            raise
    return url


def _headers(value, auth_header: str) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 10:
        raise HubError("VALIDATION_FAILED", "Extra headers must be up to 10 name: value pairs", 422)
    cleaned = {}
    for name, header_value in value.items():
        lowered = str(name).lower()
        if not HEADER_RE.fullmatch(str(name)) or lowered in FORBIDDEN_HEADERS or lowered == auth_header.lower():
            raise HubError("VALIDATION_FAILED", f"Header {str(name)[:64]} is not allowed", 422)
        if not isinstance(header_value, str) or len(header_value) > 300 or any(char in header_value for char in "\r\n"):
            raise HubError("VALIDATION_FAILED", f"Header {name} needs a single-line value of at most 300 characters", 422)
        cleaned[str(name)] = header_value
    return cleaned


def _apply(row: ModelProvider, payload: dict, settings: Settings) -> None:
    if "name" in payload:
        row.name = _text(payload["name"], "Name", 80)
    if "base_url" in payload:
        row.base_url = _base_url(payload["base_url"], settings)
    if "auth_style" in payload:
        if payload["auth_style"] not in AUTH_STYLES:
            raise HubError("VALIDATION_FAILED", "Authentication must be bearer, header or none", 422)
        row.auth_style = payload["auth_style"]
    if "auth_header" in payload:
        header = payload["auth_header"] or ""
        if header and (not isinstance(header, str) or not HEADER_RE.fullmatch(header) or header.lower() in FORBIDDEN_HEADERS):
            raise HubError("VALIDATION_FAILED", "The key header name is not allowed", 422)
        row.auth_header = header
    if row.auth_style == "header" and not row.auth_header:
        raise HubError("VALIDATION_FAILED", "Name the header that carries the key, for example api-key", 422)
    if row.auth_style != "header":
        row.auth_header = ""
    if payload.get("clear_api_key") is True:
        row.api_key_ciphertext, row.api_key_hint = "", ""
    key = payload.get("api_key")
    if key not in (None, ""):
        if not isinstance(key, str) or len(key) > 1000 or re.search(r"\s", key):
            raise HubError("VALIDATION_FAILED", "The API key must be one line of at most 1000 characters", 422)
        row.api_key_ciphertext = encrypt_secret(settings.secret_encryption_key, key)
        row.api_key_hint = key[-4:] if len(key) >= 12 else ""
    if "headers" in payload:
        row.headers = _headers(payload["headers"] or {}, row.auth_header)
    for name, allowed in (("token_param", TOKEN_PARAMS), ("tool_schema", TOOL_SCHEMAS)):
        if name in payload:
            if payload[name] not in allowed:
                raise HubError("VALIDATION_FAILED", f"{name} must be one of {', '.join(allowed)}", 422)
            setattr(row, name, payload[name])
    for name in ("streaming", "enabled"):
        if name in payload:
            if type(payload[name]) is not bool:
                raise HubError("VALIDATION_FAILED", f"{name} must be true or false", 422)
            setattr(row, name, payload[name])
    if "default_model" in payload:
        model = payload["default_model"] or ""
        if model and (not isinstance(model, str) or not MODEL_RE.fullmatch(model)):
            raise HubError("VALIDATION_FAILED", "The default model name is invalid", 422)
        row.default_model = model


def _audit(db: Session, admin: AdminUser, action: str, row: ModelProvider, result: str = "success",
           error_code: str | None = None) -> None:
    record_audit(db, action=action, actor_ref=f"admin:{admin.id}", result=result, tool_key=row.key, error_code=error_code)


def create(db: Session, admin: AdminUser, payload, settings: Settings) -> ModelProvider:
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise HubError("VALIDATION_FAILED", "Provider settings are invalid", 422)
    key = payload.get("key")
    if not isinstance(key, str) or not KEY_RE.fullmatch(key) or key in RESERVED:
        raise HubError("VALIDATION_FAILED", "Key must be 2 to 32 lowercase letters, digits, - or _, and not a reserved name", 422)
    if db.scalar(select(func.count()).select_from(ModelProvider).where(ModelProvider.key == key)):
        raise HubError("CONFLICT", f"A provider with the key {key} already exists", 409)
    if "name" not in payload or "base_url" not in payload:
        raise HubError("VALIDATION_FAILED", "A provider needs a name and a base URL", 422)
    row = ModelProvider(key=key, name="", base_url="", auth_style="bearer", auth_header="", api_key_ciphertext="",
                        api_key_hint="", headers={}, token_param="max_tokens", tool_schema="full", streaming=True,
                        default_model="", models=[], enabled=True, status="untested", status_message="",
                        created_by=admin.id, created_at=utcnow(), updated_at=utcnow())
    _apply(row, payload, settings)
    db.add(row)
    db.flush()
    _audit(db, admin, "provider.create", row)
    return row


def require(db: Session, provider_id: str) -> ModelProvider:
    row = db.get(ModelProvider, provider_id)
    if row is None:
        raise HubError("NOT_FOUND", "Model provider was not found", 404)
    return row


def update(db: Session, admin: AdminUser, row: ModelProvider, payload, settings: Settings) -> ModelProvider:
    if not isinstance(payload, dict) or set(payload) - (FIELDS - {"key"}):
        raise HubError("VALIDATION_FAILED", "Provider settings are invalid (the key cannot change)", 422)
    connection = (row.base_url, row.auth_style, row.auth_header, row.api_key_ciphertext, json.dumps(row.headers or {}))
    _apply(row, payload, settings)
    if connection != (row.base_url, row.auth_style, row.auth_header, row.api_key_ciphertext, json.dumps(row.headers or {})):
        row.status, row.status_message = "untested", ""
    row.updated_at = utcnow()
    db.flush()
    _audit(db, admin, "provider.update", row)
    return row


def delete(db: Session, admin: AdminUser, row: ModelProvider) -> None:
    used = _usage(db).get(row.key)
    if used:
        raise HubError("CONFLICT", f"Used by the chat of {', '.join(sorted(used))}. Choose another provider there first.", 409)
    _audit(db, admin, "provider.delete", row)
    db.delete(row)


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else error if isinstance(error, str) else None
    return re.sub(r"\s+", " ", message)[:200] if isinstance(message, str) else ""


async def test(db: Session, admin: AdminUser, row: ModelProvider, settings: Settings) -> ModelProvider:
    """List the provider's models; if it has no model list, send a one-token chat to the default model."""

    endpoint = Endpoint(row.name, row.base_url, _auth_headers(row, settings), row.token_param)
    status, message, models = "error", "", list(row.models or [])
    try:
        code, found, detail = await _openai_models(endpoint, settings)
        if code < 400:
            models = found
            status, message = "ok", f"Connected. {len(models)} models available."
        elif code in (401, 403):
            message = f"The provider rejected the key ({code}). {detail}".strip()
        elif code in (404, 405) and row.default_model:
            body = {"model": row.default_model, "messages": [{"role": "user", "content": "ping"}]}
            if row.token_param != "none":
                body[row.token_param] = 1
            async with await open_client(endpoint, settings) as client:
                chat = await client.post("/chat/completions", json=body)
            if chat.status_code < 400:
                status, message = "ok", f"Connected. This provider has no model list; {row.default_model} answered."
            else:
                message = f"Chat test failed ({chat.status_code}). {_error_text(chat)}".strip()
        elif code in (404, 405):
            message = "No model list at this address. Check the base URL, or set a default model and test again."
        else:
            message = f"The provider answered {code}. {detail}".strip()
    except HubError as exc:
        message = exc.message
    except (httpx.HTTPError, ValueError) as exc:
        message = f"Could not reach the provider ({type(exc).__name__})."
    row.status, row.status_message, row.models, row.checked_at = status, message[:300], models, utcnow()
    _audit(db, admin, "provider.test", row, "success" if status == "ok" else "error",
           None if status == "ok" else "PROVIDER_UNREACHABLE")
    db.flush()
    return row


# Model lists ------------------------------------------------------------------------------
# Fetched from each provider so nobody types model names; kept for a few hours, refreshed on demand.

CLAUDE_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "hint": "Most capable. Best for reports and multi-step questions."},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "hint": "Fast and capable. A good everyday choice."},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "hint": "Fastest and cheapest. Best for short lookups."},
]
CLAUDE_MODEL_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.-]{0,79}$")
CATALOG_TTL = 6 * 3600
_claude: dict = {"at": 0.0, "key": "", "models": []}
_gateway: dict = {"at": 0.0, "models": []}


async def _claude_models(settings: Settings) -> list[dict]:
    """Active Claude models that take the chat's request shape: adaptive thinking and an effort level."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=1, timeout=20)
    try:
        found = []
        async for model in client.models.list(limit=100):
            caps = model.capabilities
            if model.lifecycle != "active" or not CLAUDE_MODEL_RE.fullmatch(model.id):
                continue
            if caps is not None and not (caps.thinking.types.adaptive.supported and caps.effort.supported):
                continue
            found.append({"id": model.id, "label": model.display_name, "max_tokens": model.max_tokens,
                          "effort": caps is None or caps.effort.supported})
        return found
    finally:
        await client.close()


def claude_model_info(model: str) -> dict | None:
    """What the last fetched list says about a Claude model (output limit, effort), if it was listed."""

    return next((item for item in _claude["models"] if item["id"] == model), None)


async def _openai_models(endpoint: Endpoint, settings: Settings) -> tuple[int, list[str], str]:
    """Status, model ids and the provider's error text from GET /models."""

    async with await open_client(endpoint, settings) as client:
        response = await client.get("/models")
        if response.status_code >= 400:
            return response.status_code, [], _error_text(response)
        body = response.json()
    items = body.get("data") if isinstance(body, dict) else body
    found = sorted({str(item.get("id")) for item in items or [] if isinstance(item, dict) and item.get("id")})
    return response.status_code, [model for model in found if MODEL_RE.fullmatch(model)][:MAX_MODELS], ""


def _stale(at: float) -> bool:
    return time.time() - at > CATALOG_TTL


def _fetch_failure(exc: Exception) -> str:
    if isinstance(exc, HubError):
        return exc.message
    if isinstance(exc, anthropic.AuthenticationError):
        return "Anthropic rejected the Hub's API key."
    return f"Could not load the model list ({type(exc).__name__})."


async def model_catalog(db: Session, provider: str, settings: Settings, *, refresh: bool = False) -> dict:
    """The models an app's chat can pick for one provider, fetched live when missing, stale or asked for."""

    error = None
    if provider == ANTHROPIC:
        recommended = [dict(item) for item in CLAUDE_MODELS]
        if not settings.anthropic_api_key:
            return {"provider": provider, "models": recommended, "source": "builtin", "fetched_at": None,
                    "default_model": "claude-opus-5-5", "error": "The Hub has no ANTHROPIC_API_KEY yet; showing the recommended models."}
        fingerprint = hashlib.sha256(settings.anthropic_api_key.encode()).hexdigest()[:16]
        source = "cache"
        if refresh or _stale(_claude["at"]) or _claude["key"] != fingerprint or not _claude["models"]:
            try:
                _claude.update(models=await _claude_models(settings), at=time.time(), key=fingerprint)
                source = "live"
            except Exception as exc:  # the recommended list still works without the catalog
                error = _fetch_failure(exc)
        listed = {item["id"]: item for item in _claude["models"]}
        models = [{**item, "label": listed.get(item["id"], item)["label"]} for item in recommended]
        models += [{"id": item["id"], "label": item["label"], "hint": ""} for item in _claude["models"]
                   if item["id"] not in {model["id"] for model in recommended}]
        return {"provider": provider, "models": models, "source": source if _claude["models"] else "builtin",
                "fetched_at": _iso(_claude["at"]), "default_model": "claude-opus-5-5", "error": error}
    if provider == ENV_GATEWAY:
        source = "cache"
        if refresh or _stale(_gateway["at"]) or not _gateway["models"]:
            try:
                status, models, detail = await _openai_models(endpoint_for(db, provider, settings), settings)
                if status >= 400:
                    error = f"The gateway answered {status}. {detail}".strip()
                else:
                    _gateway.update(models=models, at=time.time())
                    source = "live"
            except Exception as exc:
                error = _fetch_failure(exc)
        return {"provider": provider, "models": [{"id": model, "label": model} for model in _gateway["models"]],
                "source": source, "fetched_at": _iso(_gateway["at"]), "default_model": "", "error": error}
    row = db.scalar(select(ModelProvider).where(ModelProvider.key == provider))
    if row is None:
        raise HubError("NOT_FOUND", "Model provider was not found", 404)
    source = "cache"
    checked = as_utc(row.checked_at).timestamp() if row.checked_at else 0.0
    if refresh or not row.models or _stale(checked):
        try:
            status, models, detail = await _openai_models(endpoint_for(db, provider, settings), settings)
            if status >= 400:
                error = f"{row.name} answered {status}. {detail}".strip()
            else:
                fetched, source, default = models, "live", row.default_model
                try:
                    row.models, row.checked_at = models, utcnow()
                    row.status, row.status_message = "ok", f"Connected. {len(models)} models available."
                    db.flush()
                except SQLAlchemyError:
                    # The list is still shown; it is only not cached (for example while SQLite is busy).
                    db.rollback()
                    return {"provider": provider, "models": [{"id": model, "label": model} for model in fetched],
                            "source": source, "fetched_at": utcnow().isoformat(), "default_model": default, "error": None}
        except Exception as exc:
            error = _fetch_failure(exc)
    return {"provider": provider, "models": [{"id": model, "label": model} for model in row.models or []],
            "source": source, "fetched_at": as_utc(row.checked_at).isoformat() if row.checked_at else None,
            "default_model": row.default_model, "error": error}


def _iso(at: float) -> str | None:
    return datetime.fromtimestamp(at, timezone.utc).isoformat() if at else None
