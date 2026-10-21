"""Per-app settings of the Hub-hosted chat. The Hub keeps settings only, never conversations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat import registry
from app.config import Settings
from app.errors import HubError
from app.ids import as_utc, utcnow
from app.persistence.models import Application, ChatSetting, ModelProvider
from app.privacy.pii_inspector import tree_contains_pii

CLAUDE_MODELS = registry.CLAUDE_MODELS
DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high")
# Claude Haiku has no server-side fallback; the larger models retry a declined request on another model.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
MODEL_RE = registry.MODEL_RE
MAX_INSTRUCTIONS = 4000
MAX_SUGGESTIONS = 6
FIELDS = {"enabled", "provider", "model", "effort", "instructions", "welcome_message", "suggestions", "max_steps",
          "daily_limit", "gateway_models", "monthly_token_limit"}
# Allowed gateway models and the token budget: super admins only.
COST_FIELDS = {"gateway_models", "monthly_token_limit"}
MAX_GATEWAY_MODELS = 200
MAX_MONTHLY_TOKENS = 2_000_000_000


def setting(db: Session, app_id: str) -> ChatSetting:
    """The app's chat settings, or the default (off) when never configured. Not added to the session."""

    return db.get(ChatSetting, app_id) or ChatSetting(
        app_id=app_id, enabled=False, provider="anthropic", model=DEFAULT_MODEL, effort="medium", instructions="",
        welcome_message="", suggestions=[], max_steps=6, daily_limit=200, gateway_models=[], monthly_token_limit=0)


def provider_options(db: Session, settings: Settings, current: str) -> list[dict]:
    """Claude, the environment gateway when configured (or in use), then every registered provider."""

    options = [{"id": registry.ANTHROPIC, "label": "Claude (Anthropic)", "kind": "anthropic",
                "ready": bool(registry.claude_settings(db, settings).anthropic_api_key), "models": [],
                "default_model": DEFAULT_MODEL}]
    if settings.chat_openai_base_url or current == registry.ENV_GATEWAY:
        options.append({"id": registry.ENV_GATEWAY, "label": "Gateway (environment)", "kind": "openai_compatible",
                        "ready": bool(settings.chat_openai_base_url), "models": [], "default_model": ""})
    for row in db.scalars(select(ModelProvider).where(ModelProvider.key != registry.ANTHROPIC).order_by(ModelProvider.name)):
        if row.enabled or row.key == current:
            options.append({"id": row.key, "label": row.name, "kind": "openai_compatible",
                            "ready": registry.view(row)["ready"], "models": list(row.models or []),
                            "default_model": row.default_model})
    return options


def admin_view(db: Session, application: Application, settings: Settings) -> dict:
    config = setting(db, application.id)
    return {"enabled": config.enabled, "provider": config.provider, "model": config.model, "effort": config.effort,
            "instructions": config.instructions, "welcome_message": config.welcome_message,
            "suggestions": list(config.suggestions or []), "max_steps": config.max_steps,
            "daily_limit": config.daily_limit,
            "gateway_models": list(config.gateway_models or []),
            "monthly_token_limit": config.monthly_token_limit or 0,
            "gateway_usage": usage_view(db, application.id),
            "fallbacks": config.provider == "anthropic" and config.model in FALLBACK_MODELS,
            "updated_at": as_utc(config.updated_at).isoformat() if config.updated_at else None,
            "options": {"providers": provider_options(db, settings, config.provider),
                        "models": CLAUDE_MODELS, "efforts": list(EFFORTS), "max_steps": [1, 12],
                        "daily_limit": [0, 5000], "monthly_token_limit": [0, MAX_MONTHLY_TOKENS]}}


def model_allowed(patterns, model_id: str) -> bool:
    """Whether a gateway model id is open to the app: an exact id, or provider/* for a whole provider."""

    if not patterns:
        return True
    provider = model_id.split("/", 1)[0]
    return any(item == model_id or (item.endswith("/*") and item[:-2] == provider) for item in patterns)


def _gateway_models(db: Session, items) -> list[str]:
    if not isinstance(items, list) or len(items) > MAX_GATEWAY_MODELS:
        raise HubError("VALIDATION_FAILED", f"Allow at most {MAX_GATEWAY_MODELS} models", 422)
    cleaned: list[str] = []
    for item in items:
        provider, _, model = item.partition("/") if isinstance(item, str) else ("", "", "")
        if (not provider or len(item) > 160 or not registry.exists(db, provider)
                or not (model == "*" or MODEL_RE.fullmatch(model))):
            raise HubError("VALIDATION_FAILED", "Each allowed model is provider/model or provider/* "
                           "for a provider on the Hub", 422)
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


def usage_view(db: Session, app_id: str) -> dict:
    """This month's gateway calls and tokens for the app, busiest models first."""

    from app.persistence.models import GatewayUsage

    period = utcnow().strftime("%Y-%m")
    rows = list(db.scalars(select(GatewayUsage).where(GatewayUsage.app_id == app_id, GatewayUsage.period == period)))
    rows.sort(key=lambda row: row.prompt_tokens + row.completion_tokens, reverse=True)
    return {"period": period, "calls": sum(row.calls for row in rows), "errors": sum(row.errors for row in rows),
            "prompt_tokens": sum(row.prompt_tokens for row in rows),
            "completion_tokens": sum(row.completion_tokens for row in rows),
            "models": [{"model": row.model, "calls": row.calls, "errors": row.errors,
                        "tokens": row.prompt_tokens + row.completion_tokens} for row in rows[:20]]}


def _text(value, field: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise HubError("VALIDATION_FAILED", f"{field} must be text of at most {maximum} characters", 422)
    cleaned = value.strip()
    if tree_contains_pii(cleaned):
        raise HubError("PII_DETECTED", f"{field} contains personal data or a credential", 422)
    return cleaned


def update_settings(db: Session, application: Application, payload) -> ChatSetting:
    if not isinstance(payload, dict) or not payload or set(payload) - FIELDS:
        raise HubError("VALIDATION_FAILED", "Chat settings are invalid", 422)
    row = db.get(ChatSetting, application.id)
    if row is None:
        row = setting(db, application.id)
        db.add(row)
    if "enabled" in payload:
        if type(payload["enabled"]) is not bool:
            raise HubError("VALIDATION_FAILED", "enabled must be true or false", 422)
        row.enabled = payload["enabled"]
    if "provider" in payload:
        if not isinstance(payload["provider"], str) or not registry.exists(db, payload["provider"]):
            raise HubError("VALIDATION_FAILED", "Choose Claude or a provider added under AI providers", 422)
        row.provider = payload["provider"]
    if "model" in payload:
        model = payload["model"]
        if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
            raise HubError("VALIDATION_FAILED", "Model name is invalid", 422)
        row.model = model
    if row.provider == "anthropic" and not registry.CLAUDE_MODEL_RE.fullmatch(row.model):
        raise HubError("VALIDATION_FAILED", "Choose a Claude model from the list", 422)
    if "effort" in payload:
        if payload["effort"] not in EFFORTS:
            raise HubError("VALIDATION_FAILED", "Effort must be low, medium or high", 422)
        row.effort = payload["effort"]
    if "instructions" in payload:
        row.instructions = _text(payload["instructions"], "Instructions", MAX_INSTRUCTIONS)
    if "welcome_message" in payload:
        row.welcome_message = _text(payload["welcome_message"], "Welcome message", 300)
    if "suggestions" in payload:
        items = payload["suggestions"]
        if not isinstance(items, list) or len(items) > MAX_SUGGESTIONS:
            raise HubError("VALIDATION_FAILED", f"Add at most {MAX_SUGGESTIONS} suggestions", 422)
        row.suggestions = [text for text in (_text(item, "A suggestion", 120) for item in items) if text]
    if "max_steps" in payload:
        if type(payload["max_steps"]) is not int or not 1 <= payload["max_steps"] <= 12:
            raise HubError("VALIDATION_FAILED", "Tool steps per answer must be between 1 and 12", 422)
        row.max_steps = payload["max_steps"]
    if "daily_limit" in payload:
        if type(payload["daily_limit"]) is not int or not 0 <= payload["daily_limit"] <= 5000:
            raise HubError("VALIDATION_FAILED", "Messages per user per day must be between 0 (no limit) and 5000", 422)
        row.daily_limit = payload["daily_limit"]
    if "gateway_models" in payload:
        row.gateway_models = _gateway_models(db, payload["gateway_models"])
    if "monthly_token_limit" in payload:
        limit = payload["monthly_token_limit"]
        if type(limit) is not int or not 0 <= limit <= MAX_MONTHLY_TOKENS:
            raise HubError("VALIDATION_FAILED", "Tokens per month must be 0 (no budget) or a positive number", 422)
        row.monthly_token_limit = limit
    row.updated_at = utcnow()
    db.flush()
    return row
