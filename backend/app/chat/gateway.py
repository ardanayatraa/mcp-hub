"""Model gateway: an app picks a model from every provider the Hub holds keys for, and calls it through the Hub.

The keys stay on the Hub. The app gets one model list (Claude, the environment gateway and every
enabled OpenAI-compatible provider) and OpenAI-style chat completions, including function calling,
so its own chat keeps its own tools and its own model picker. Two surfaces share this module:

- /gateway/v1/models and /gateway/v1/chat/completions, for any OpenAI-style client;
- /gateway/mcp with the tools list_ai_models and chat_ai, the model bridge apps with their own chat speak.

An app may use it while its Chat is on in the Hub, and only the models its admin allowed (all of
them while the list is empty). The chat rate limit applies per end user and GATEWAY_APP_RATE_LIMIT
per app; the daily limit counts questions (calls that end with a user message), so tool rounds do
not use it up; the monthly token budget stops the app once its usage reaches it. Each call is
audited (model, result, duration) and counted per app, model and month; messages are never stored.
"""

import asyncio
import json
import logging
import time

import anthropic
import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite

from app.chat import providers, registry
from app.chat import settings as chat_settings
from app.config import Settings
from app.errors import HubError
from app.ids import new_id, new_trace_id, utcnow
from app.persistence.models import GatewayUsage
from app.privacy.pii_inspector import tree_contains_pii
from app.security.audit import record_audit
from app.security.clients import Caller
from app.security.rate_limit import hit

logger = logging.getLogger("hub.gateway")
SEPARATOR = "/"
ROLES = {"system", "user", "assistant", "tool"}
MAX_MESSAGES = 200
MAX_TOOLS = 128
TOOL_CHOICES = {"auto", "none", "required"}
# A provider that is briefly down or overloaded gets one more try; Claude's SDK retries on its own.
RETRY_STATUSES = {502, 503}
RETRY_DELAY = 0.5


def gateway_id(provider: str, model: str) -> str:
    """Model ids name their provider: anthropic/claude-opus-5-5, openai/gpt-4.1, openrouter/meta-llama/llama-3.1-8b-instruct."""

    return f"{provider}{SEPARATOR}{model}"


def split_id(value) -> tuple[str, str]:
    if not isinstance(value, str) or SEPARATOR not in value:
        raise HubError("VALIDATION_FAILED", "Pick a model from the list (provider/model)", 422)
    provider, model = value.split(SEPARATOR, 1)
    if not provider or not registry.MODEL_RE.fullmatch(model):
        raise HubError("VALIDATION_FAILED", "Pick a model from the list (provider/model)", 422)
    return provider, model


def require_access(db, caller: Caller, settings: Settings):
    """The app's chat settings, when its Chat is on and the app is active in the Hub."""

    if caller.connector is None or caller.connector.status != "active":
        raise HubError("CONNECTOR_INACTIVE", "This app is not active on the Hub", 409)
    config = chat_settings.setting(db, caller.application.id)
    if not config.enabled:
        raise HubError("CHAT_DISABLED", "Models are off for this app. Turn on its Chat in the Hub.", 403)
    if settings.environment == "production":
        if not config.gateway_models:
            raise HubError("MODEL_ACCESS_UNCONFIGURED", "Set this app's allowed models before using the gateway.", 403)
        if not config.monthly_token_limit:
            raise HubError("TOKEN_BUDGET_UNCONFIGURED", "Set this app's monthly token budget before using the gateway.", 403)
    return config


async def catalog(db, settings: Settings, caller: Caller) -> dict:
    """Every model the app may pick now, and the default: the app's Chat model when it is listed."""

    config = require_access(db, caller, settings)
    rows = [row for row in await every_model(db, settings, config.gateway_models)
            if chat_settings.model_allowed(config.gateway_models, row["id"])]
    preferred = gateway_id(config.provider, config.model) if config.model else ""
    default = preferred if any(row["id"] == preferred for row in rows) else (rows[0]["id"] if rows else None)
    return {"data": rows, "default": default}


async def every_model(db, settings: Settings, patterns=None) -> list[dict]:
    """Every model of every ready provider; with patterns, only the providers they name are asked."""

    providers_named = {item.split(SEPARATOR, 1)[0] for item in patterns or []}
    rows = []
    for option in chat_settings.provider_options(db, settings, ""):
        if not option["ready"] or (providers_named and option["id"] not in providers_named):
            continue
        listing = await registry.model_catalog(db, option["id"], settings)
        for item in listing["models"]:
            rows.append({"id": gateway_id(option["id"], item["id"]), "provider": option["id"],
                         "name": f"{item.get('label') or item['id']} · {option['label']}"})
    return rows


# Usage ------------------------------------------------------------------------------------


def _period() -> str:
    return utcnow().strftime("%Y-%m")


def month_tokens(db, app_id: str) -> int:
    total = db.scalar(select(func.coalesce(func.sum(GatewayUsage.prompt_tokens + GatewayUsage.completion_tokens), 0))
                      .where(GatewayUsage.app_id == app_id, GatewayUsage.period == _period()))
    return int(total or 0)


def record_usage(db, app_id: str, model: str, usage: dict | None, failed: bool) -> None:
    """Add one call to the app's monthly counts, in one statement so parallel calls never lose a count."""

    usage = usage or {}
    prompt, completion = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    dialect = postgresql if db.get_bind().dialect.name == "postgresql" else sqlite
    statement = dialect.insert(GatewayUsage).values(
        id=new_id(), app_id=app_id, period=_period(), model=model[:160], calls=1, errors=int(failed),
        prompt_tokens=prompt, completion_tokens=completion, updated_at=utcnow())
    db.execute(statement.on_conflict_do_update(
        index_elements=["app_id", "period", "model"],
        set_={"calls": GatewayUsage.calls + 1, "errors": GatewayUsage.errors + int(failed),
              "prompt_tokens": GatewayUsage.prompt_tokens + prompt,
              "completion_tokens": GatewayUsage.completion_tokens + completion, "updated_at": utcnow()}))


# Requests ---------------------------------------------------------------------------------


def _text(content) -> str | None:
    """OpenAI content is a string or a list of parts; only text parts are forwarded."""

    if content is None or isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content
                       if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
    raise HubError("VALIDATION_FAILED", "Message content must be text", 422)


def _tool_calls(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_TOOLS:
        raise HubError("VALIDATION_FAILED", "tool_calls must be a list", 422)
    calls = []
    for call in raw:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise HubError("VALIDATION_FAILED", "Each tool call needs a function name", 422)
        arguments = function.get("arguments")
        if arguments == [] or (isinstance(arguments, str) and arguments.strip() in ("", "[]")):
            arguments = "{}"  # PHP's empty array; providers expect an object
        calls.append({"id": str(call.get("id") or ""), "type": "function",
                      "function": {"name": function["name"], "arguments": arguments if isinstance(arguments, str)
                                   else json.dumps(arguments if arguments is not None else {})}})
    return calls


OBJECT_KEYWORDS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
LIST_KEYWORDS = ("anyOf", "oneOf", "allOf", "prefixItems")


def object_schema(schema):
    """A tool's JSON Schema with PHP's empty arrays read as empty objects.

    PHP encodes an empty associative array as [], so Laravel apps send "properties": [] and even
    "parameters": []. Strict providers refuse the whole request for it; the Hub repairs it once here.
    """

    if schema == [] or schema is None:
        return {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        return schema
    fixed = dict(schema)
    for key in OBJECT_KEYWORDS:
        if key in fixed:
            value = fixed[key]
            fixed[key] = {name: object_schema(item) for name, item in value.items()} if isinstance(value, dict) else (
                {} if value == [] else value)
    for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains"):
        if isinstance(fixed.get(key), dict):
            fixed[key] = object_schema(fixed[key])
    for key in LIST_KEYWORDS:
        if isinstance(fixed.get(key), list):
            fixed[key] = [object_schema(item) if isinstance(item, dict) else item for item in fixed[key]]
    if fixed.get("type") == "object" and "properties" not in fixed:
        fixed["properties"] = {}
    return fixed


def parse(payload, settings: Settings) -> dict:
    """The vetted request: only these fields reach a provider."""

    if not isinstance(payload, dict):
        raise HubError("VALIDATION_FAILED", "Send the model and the messages", 422)
    split_id(payload.get("model"))
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list) or not 1 <= len(raw_messages) <= MAX_MESSAGES:
        raise HubError("VALIDATION_FAILED", f"messages must hold 1 to {MAX_MESSAGES} messages", 422)
    messages = []
    for raw in raw_messages:
        if not isinstance(raw, dict) or raw.get("role") not in ROLES:
            raise HubError("VALIDATION_FAILED", "Each message needs a role: system, user, assistant or tool", 422)
        message = {"role": raw["role"], "content": _text(raw.get("content"))}
        if raw["role"] == "assistant":
            message["tool_calls"] = _tool_calls(raw.get("tool_calls"))
        if raw["role"] == "tool":
            if not isinstance(raw.get("tool_call_id"), str) or not raw["tool_call_id"]:
                raise HubError("VALIDATION_FAILED", "A tool message needs its tool_call_id", 422)
            message["tool_call_id"] = raw["tool_call_id"]
        messages.append(message)
    tools = payload.get("tools") or []
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise HubError("VALIDATION_FAILED", f"tools must be a list of at most {MAX_TOOLS} functions", 422)
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str) or (
                "parameters" in function and not isinstance(function["parameters"], dict | list | None)):
            raise HubError("VALIDATION_FAILED", "Each tool needs a function name and object parameters", 422)
        if "parameters" in function and isinstance(function["parameters"], list) and function["parameters"]:
            raise HubError("VALIDATION_FAILED", "Each tool needs a function name and object parameters", 422)
        function["parameters"] = object_schema(function.get("parameters"))
    choice = payload.get("tool_choice")
    if choice is not None and choice not in TOOL_CHOICES and not (
            isinstance(choice, dict) and isinstance((choice.get("function") or {}).get("name"), str)):
        raise HubError("VALIDATION_FAILED", "tool_choice must be auto, none, required or one function", 422)
    request = {"model": payload["model"], "messages": messages, "tools": tools, "tool_choice": choice}
    for name, low, high in (("temperature", 0, 2), ("top_p", 0, 1)):
        value = payload.get(name)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
                raise HubError("VALIDATION_FAILED", f"{name} must be between {low} and {high}", 422)
            request[name] = value
    tokens = payload.get("max_tokens")
    if tokens is not None:
        if isinstance(tokens, bool) or not isinstance(tokens, int) or not 1 <= tokens <= settings.chat_max_tokens:
            raise HubError("VALIDATION_FAILED", f"max_tokens must be between 1 and {settings.chat_max_tokens}", 422)
        request["max_tokens"] = tokens
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    # metadata.end_user_id (the bridge) or OpenAI's own top-level user field.
    user = metadata.get("end_user_id", payload.get("user"))
    valid = isinstance(user, str | int) and not isinstance(user, bool) and str(user).strip()
    request["end_user"] = str(user).strip()[:64] if valid else "app"
    return request


# Completions ------------------------------------------------------------------------------


async def complete(db, settings: Settings, caller: Caller, payload) -> dict:
    """One chat completion through the chosen provider, answered in the OpenAI shape."""

    config = require_access(db, caller, settings)
    request = parse(payload, settings)
    provider, model = split_id(request["model"])
    if not registry.exists(db, provider):
        raise HubError("VALIDATION_FAILED", "This model's provider is not on the Hub", 422)
    app = caller.application
    trace, started = new_trace_id(), time.monotonic()
    # Rate limits come first, so refused calls cannot flood the audit trail either.
    # end_user_id is the app's word, so one key also has an app-wide budget nobody can spread around.
    hit(f"gateway-app:{app.id}", settings.gateway_app_rate_limit, 60)
    hit(f"gateway:{app.id}:{request['end_user']}", settings.chat_rate_limit, 60)
    if not chat_settings.model_allowed(config.gateway_models, request["model"]):
        _audit(db, caller, request["model"], trace, started, "MODEL_NOT_ALLOWED")
        raise HubError("MODEL_NOT_ALLOWED", "This app may not use that model. Pick one from the model list.", 403)
    if config.monthly_token_limit and month_tokens(db, app.id) >= config.monthly_token_limit:
        _audit(db, caller, request["model"], trace, started, "BUDGET_EXCEEDED")
        raise HubError("BUDGET_EXCEEDED", "This app has used its model tokens for this month. "
                       "An admin can raise the budget in the Hub.", 429)
    # The daily limit counts questions: a call that answers a tool result continues the same one.
    if config.daily_limit and request["messages"][-1]["role"] == "user":
        hit(f"gateway-day:{app.id}:{request['end_user']}", config.daily_limit, 86400)
    settings = registry.claude_settings(db, settings)
    endpoint = registry.endpoint_for(db, provider, settings)
    try:
        if endpoint is None:
            answer = await _claude(settings, model, request)
        else:
            answer = await _openai(settings, endpoint, model, request)
    except HubError as exc:
        _audit(db, caller, request["model"], trace, started, exc.code)
        record_usage(db, app.id, request["model"], None, True)
        # The audit row keeps the code; the provider's own words go to the log for whoever debugs it.
        detail = exc.message[:300]
        logger.warning("gateway_model_error", extra={"trace_id": trace, "app_key": app.key, "tool_key": request["model"][:120],
                                                    "error_code": exc.code,
                                                    "detail": "(withheld: personal data)" if tree_contains_pii(detail) else detail})
        raise
    _audit(db, caller, request["model"], trace, started, None)
    record_usage(db, app.id, request["model"], answer.get("usage"), False)
    return {"id": f"chatcmpl-{trace}", "object": "chat.completion", "created": int(time.time()),
            "model": request["model"], **answer}


def _audit(db, caller: Caller, model: str, trace: str, started: float, error: str | None) -> None:
    record_audit(db, action="model.chat", actor_ref=caller.actor_ref, trace_id=trace, app_key=caller.application.key,
                 tool_key=model[:120], environment=caller.application.environment,
                 result="error" if error else "success", error_code=error,
                 duration_ms=int((time.monotonic() - started) * 1000))


def _choice(content: str | None, calls: list[dict], finish: str) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = calls
    return {"index": 0, "message": message, "finish_reason": finish}


async def _openai(settings: Settings, endpoint: registry.Endpoint, model: str, request: dict) -> dict:
    body: dict = {"model": model, "messages": request["messages"], "stream": False}
    for message in body["messages"]:
        if message["role"] == "assistant" and not message.get("tool_calls"):
            message.pop("tool_calls", None)
    if request["tools"]:
        shape = providers.basic_schema if endpoint.tool_schema == "basic" else (lambda schema: schema)
        body["tools"] = [{"type": "function", "function": {
            "name": tool["function"]["name"], "description": tool["function"].get("description", ""),
            "parameters": shape(tool["function"].get("parameters") or {"type": "object", "properties": {}})}}
            for tool in request["tools"]]
        if request["tool_choice"] is not None:
            body["tool_choice"] = request["tool_choice"]
    if "max_tokens" in request and endpoint.token_param != "none":
        body[endpoint.token_param] = request["max_tokens"]
    for name in ("temperature", "top_p"):
        if name in request:
            body[name] = request[name]
    try:
        async with await registry.open_client(endpoint, settings) as client:
            for attempt in range(2):
                try:
                    response = await client.post("/chat/completions", json=body)
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if attempt:  # the request never left, so one more try is safe
                        raise
                else:
                    if response.status_code not in RETRY_STATUSES or attempt:
                        break
                await asyncio.sleep(RETRY_DELAY)
    except httpx.HTTPError as exc:
        raise HubError("MODEL_UNREACHABLE", f"{endpoint.label} could not be reached. Try again in a moment.", 502) from exc
    if response.status_code >= 400:
        raise providers._provider_error(response.status_code, response.content, endpoint.label)
    try:
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HubError("MODEL_ERROR", f"{endpoint.label} returned an answer the Hub could not read", 502) from exc
    calls = _tool_calls(message.get("tool_calls"))
    answer = {"choices": [_choice(_text(message.get("content")), calls, str(choice.get("finish_reason") or "stop"))]}
    if isinstance(data.get("usage"), dict):
        answer["usage"] = {key: data["usage"][key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                           if isinstance(data["usage"].get(key), int)}
    return answer


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """OpenAI messages as Claude's system text and alternating user/assistant turns."""

    system, turns = [], []
    for message in messages:
        text = message.get("content") or ""
        if message["role"] == "system":
            if text:
                system.append(text)
            continue
        if message["role"] == "user":
            role, blocks = "user", ([{"type": "text", "text": text}] if text else [])
        elif message["role"] == "assistant":
            role, blocks = "assistant", ([{"type": "text", "text": text}] if text else [])
            for call in message.get("tool_calls") or []:
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except ValueError:
                    arguments = {}
                blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                               "input": arguments if isinstance(arguments, dict) else {}})
        else:
            role, blocks = "user", [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": text}]
        if not blocks:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})
    # Claude starts with the user; an opening greeting from the app is dropped.
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if not turns:
        raise HubError("VALIDATION_FAILED", "Send at least one user message", 422)
    return "\n\n".join(system), turns


def _claude_tool_choice(choice):
    if choice is None or choice == "auto":
        return {"type": "auto"}
    if choice == "none":
        return {"type": "none"}
    if choice == "required":
        return {"type": "any"}
    return {"type": "tool", "name": choice["function"]["name"]}


async def _claude(settings: Settings, model: str, request: dict) -> dict:
    system, turns = to_anthropic(request["messages"])
    limit = request.get("max_tokens") or settings.chat_max_tokens
    info = registry.claude_model_info(model)
    if info and info.get("max_tokens"):
        limit = min(limit, info["max_tokens"])
    kwargs: dict = {"model": model, "max_tokens": limit, "messages": turns}
    if system:
        kwargs["system"] = system
    if request["tools"]:
        kwargs["tools"] = [{"name": tool["function"]["name"], "description": tool["function"].get("description", ""),
                            "input_schema": tool["function"].get("parameters") or {"type": "object", "properties": {}}}
                           for tool in request["tools"]]
        kwargs["tool_choice"] = _claude_tool_choice(request["tool_choice"])
    for name in ("temperature", "top_p"):
        if name in request:
            kwargs[name] = request[name]
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=2,
                                      timeout=settings.chat_timeout_seconds)
    try:
        response = await client.messages.create(**kwargs)
    except anthropic.APIError as exc:
        raise providers._model_error(exc) from exc
    finally:
        await client.close()
    text = "".join(block.text for block in response.content if block.type == "text")
    calls = [{"id": block.id, "type": "function", "function": {"name": block.name, "arguments": json.dumps(block.input)}}
             for block in response.content if block.type == "tool_use"]
    finish = {"tool_use": "tool_calls", "max_tokens": "length"}.get(response.stop_reason or "", "stop")
    usage = {"prompt_tokens": response.usage.input_tokens, "completion_tokens": response.usage.output_tokens,
             "total_tokens": response.usage.input_tokens + response.usage.output_tokens}
    return {"choices": [_choice(text or None, calls, finish)], "usage": usage}
