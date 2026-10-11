"""Model providers for the Hub chat.

A conversation object owns its provider's message format for the length of one turn: the
engine asks it for a step, runs the tool calls it returns, and hands back the results.
Prior turns arrive as plain text, so nothing provider-specific is ever stored.
"""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anthropic
import httpx
from mcp.types import Tool

from app.chat import registry
from app.chat.registry import Endpoint
from app.chat.settings import FALLBACK_MODELS
from app.config import Settings
from app.errors import HubError
from app.persistence.models import ChatSetting

OnText = Callable[[str], Awaitable[None]]
# Anthropic and OpenAI-style APIs cap tool names at 64 characters; Hub names may be longer.
MAX_TOOL_NAME = 64
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_HIDDEN_BEFORE_FALLBACK = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: object


@dataclass
class Step:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    # end | tool_use | max_tokens | refusal
    stop: str = "end"


@dataclass
class Result:
    call_id: str
    content: str
    is_error: bool = False


def wire_name(name: str) -> str:
    if len(name) <= MAX_TOOL_NAME:
        return name
    return f"{name[:MAX_TOOL_NAME - 9]}_{hashlib.sha256(name.encode()).hexdigest()[:8]}"


class Conversation:
    """One turn's exchange with a model."""

    names: dict[str, str]

    async def step(self, on_text: OnText, *, allow_tools: bool = True) -> Step:
        raise NotImplementedError

    def add_results(self, results: list[Result]) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    def hub_name(self, wire: str) -> str:
        return self.names.get(wire, wire)


def _model_error(exc: Exception) -> HubError:
    if isinstance(exc, anthropic.AuthenticationError):
        return HubError("CHAT_NOT_CONFIGURED", "The Hub's model key was rejected. Ask an admin to check it.", 503)
    if isinstance(exc, anthropic.RateLimitError):
        return HubError("MODEL_BUSY", "The AI model is busy. Try again in a moment.", 503)
    if isinstance(exc, anthropic.APIStatusError):
        return HubError("MODEL_ERROR", f"The AI model returned an error ({exc.status_code})", 502)
    return HubError("MODEL_UNREACHABLE", "The AI model could not be reached. Try again in a moment.", 502)


class AnthropicConversation(Conversation):
    def __init__(self, settings: Settings, config: ChatSetting, system: str, messages: list[dict], tools: list[Tool],
                 user_id: str | None) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=2,
                                               timeout=settings.chat_timeout_seconds)
        self.model, self.effort, self.max_tokens = config.model, config.effort, settings.chat_max_tokens
        # The fetched model list knows each model's output limit and whether it takes an effort level.
        info = registry.claude_model_info(config.model)
        if info and info.get("max_tokens"):
            self.max_tokens = min(self.max_tokens, info["max_tokens"])
        self.send_effort = not info or info.get("effort", True)
        self.system, self.messages, self.user_id = system, messages, user_id
        self.names = {wire_name(tool.name): tool.name for tool in tools}
        # Streamed requests stream tool inputs as generated; the Hub validates every input before running it.
        self.tools = [{"name": wire_name(tool.name), "description": tool.description or tool.title or tool.name,
                       "input_schema": tool.input_schema, "eager_input_streaming": True} for tool in tools]

    async def step(self, on_text: OnText, *, allow_tools: bool = True) -> Step:
        params: dict = {"model": self.model, "max_tokens": self.max_tokens, "system": self.system,
                        "messages": self.messages,
                        # Caches the system prompt, tools and history between the steps and turns of a chat.
                        "cache_control": {"type": "ephemeral"}}
        if self.send_effort:
            params["output_config"] = {"effort": self.effort}
        if self.tools:
            params["tools"] = self.tools
            if not allow_tools:
                params["tool_choice"] = {"type": "none"}
        if self.model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        if self.user_id:
            params["metadata"] = {"user_id": self.user_id}
        for attempt in range(3):
            try:
                async with self.client.beta.messages.stream(**params) as stream:
                    async for event in stream:
                        if event.type == "text":
                            await on_text(event.text)
                    message = await stream.get_final_message()
                break
            except ValueError:
                # Tool input JSON the SDK could not parse at all: no tool_use id to answer, so ask again.
                if attempt == 2:
                    raise HubError("MODEL_ERROR", "The AI model sent a malformed tool call", 502) from None
            except anthropic.APIError as exc:
                raise _model_error(exc) from exc
        content = list(message.content)
        boundary = max((index for index, block in enumerate(content) if block.type == "fallback"), default=-1)
        # After a mid-answer fallback, the declined model's internal blocks are not sent back.
        kept = [block for index, block in enumerate(content)
                if block.type != "fallback" and (index > boundary or block.type not in _HIDDEN_BEFORE_FALLBACK)]
        self.messages.append({"role": "assistant", "content": kept})
        text = "".join(block.text for block in kept if block.type == "text")
        calls = [ToolCall(block.id, block.name, block.input) for block in kept if block.type == "tool_use"]
        if message.stop_reason == "refusal":
            return Step(text=text, stop="refusal")
        if message.stop_reason == "max_tokens":
            return Step(text=text, stop="max_tokens")
        return Step(text=text, calls=calls, stop="tool_use" if calls else "end")

    def add_results(self, results: list[Result]) -> None:
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": item.call_id, "content": item.content, "is_error": item.is_error}
            for item in results]})

    async def close(self) -> None:
        await self.client.close()


BASIC_KEYWORDS = {"type", "properties", "required", "items", "enum", "description", "minimum", "maximum"}
MAX_STREAM_BYTES = 4 * 1024 * 1024


def basic_schema(schema):
    """A JSON schema strict providers accept: no anyOf, nulls, lengths or additionalProperties."""

    if not isinstance(schema, dict):
        return schema
    if "anyOf" in schema or "oneOf" in schema:
        variants = [item for item in schema.get("anyOf") or schema.get("oneOf") or [] if item.get("type") != "null"]
        merged = {**(variants[0] if variants else {"type": "string"}), **{key: value for key, value in schema.items()
                                                                           if key in ("description",)}}
        return basic_schema(merged)
    out = {}
    for key, value in schema.items():
        if key not in BASIC_KEYWORDS:
            continue
        if key == "type" and isinstance(value, list):
            value = next((item for item in value if item != "null"), "string")
        if key == "properties" and isinstance(value, dict):
            value = {name: basic_schema(item) for name, item in value.items()}
        elif key == "items":
            value = basic_schema(value)
        out[key] = value
    if out.get("type") == "object":
        out.setdefault("properties", {})
    return out


def _provider_error(status: int, body: bytes, label: str) -> HubError:
    detail = ""
    try:
        parsed = json.loads(body.decode("utf-8", "replace"))
        error = parsed.get("error") if isinstance(parsed, dict) else None
        message = error.get("message") if isinstance(error, dict) else error if isinstance(error, str) else None
        if isinstance(message, str):
            detail = " " + re.sub(r"\s+", " ", message)[:200]
    except ValueError:
        pass
    if status in (401, 403):
        return HubError("CHAT_NOT_CONFIGURED", f"{label} rejected the Hub's key. Ask an admin to check it.", 503)
    if status == 429:
        return HubError("MODEL_BUSY", f"{label} is busy or out of quota. Try again in a moment.{detail}", 503)
    return HubError("MODEL_ERROR", f"{label} returned an error ({status}).{detail}", 502)


class OpenAICompatibleConversation(Conversation):
    """Any Chat Completions provider: hosted, a company gateway or a local server. Streams when it can."""

    def __init__(self, settings: Settings, config: ChatSetting, endpoint: Endpoint, system: str, messages: list[dict],
                 tools: list[Tool]) -> None:
        self.settings, self.endpoint, self.client = settings, endpoint, None
        self.model, self.max_tokens = config.model, settings.chat_max_tokens
        self.messages = [{"role": "system", "content": system}] + [
            {"role": item["role"], "content": item["content"]} for item in messages]
        self.names = {wire_name(tool.name): tool.name for tool in tools}
        shape = basic_schema if endpoint.tool_schema == "basic" else (lambda schema: schema)
        self.tools = [{"type": "function", "function": {"name": wire_name(tool.name),
                                                         "description": tool.description or tool.title or tool.name,
                                                         "parameters": shape(tool.input_schema)}} for tool in tools]
        self.calls = 0

    async def step(self, on_text: OnText, *, allow_tools: bool = True) -> Step:
        if self.client is None:
            self.client = await registry.open_client(self.endpoint, self.settings)
        body: dict = {"model": self.model, "messages": self.messages}
        if self.endpoint.token_param != "none":
            body[self.endpoint.token_param] = self.max_tokens
        if self.tools:
            body["tools"] = self.tools
            body["tool_choice"] = "auto" if allow_tools else "none"
        if self.endpoint.streaming:
            body["stream"] = True
        try:
            async with self.client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code >= 400:
                    raise _provider_error(response.status_code, await response.aread(), self.endpoint.label)
                streamed = "text/event-stream" in response.headers.get("content-type", "")
                if streamed:
                    text, raw_calls, finish = await self._read_stream(response, on_text)
                else:
                    text, raw_calls, finish = await self._read_whole(response, on_text)
        except httpx.HTTPError as exc:
            raise HubError("MODEL_UNREACHABLE", f"{self.endpoint.label} could not be reached. Try again in a moment.",
                           502) from exc
        calls, echoed = [], []
        for item in raw_calls:
            self.calls += 1
            call_id = str(item.get("id") or f"call_{self.calls}")
            function = item.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments or "{}")
                except ValueError:
                    arguments = None
            name = str(function.get("name") or "")
            calls.append(ToolCall(call_id, name, arguments))
            echoed.append({"id": call_id, "type": "function", "function": {
                "name": name, "arguments": function.get("arguments") if isinstance(function.get("arguments"), str)
                else json.dumps(arguments if arguments is not None else {})}})
        message: dict = {"role": "assistant", "content": text or None}
        if echoed:
            message["tool_calls"] = echoed
        self.messages.append(message)
        if finish == "length":
            return Step(text=text, stop="max_tokens")
        if finish == "content_filter":
            return Step(text=text, stop="refusal")
        return Step(text=text, calls=calls, stop="tool_use" if calls else "end")

    async def _read_whole(self, response: httpx.Response, on_text: OnText) -> tuple[str, list[dict], str | None]:
        raw = await response.aread()
        try:
            choice = json.loads(raw)["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise HubError("MODEL_ERROR", f"{self.endpoint.label} sent an unreadable answer", 502) from exc
        text = message.get("content") or ""
        if text:
            await on_text(text)
        return text, list(message.get("tool_calls") or []), choice.get("finish_reason")

    async def _read_stream(self, response: httpx.Response, on_text: OnText) -> tuple[str, list[dict], str | None]:
        text: list[str] = []
        calls: dict[int, dict] = {}
        finish, size = None, 0
        async for line in response.aiter_lines():
            size += len(line)
            if size > MAX_STREAM_BYTES:
                raise HubError("MODEL_ERROR", f"{self.endpoint.label} sent an answer that is too large", 502)
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if isinstance(chunk.get("error"), (dict, str)):
                raise _provider_error(502, data.encode(), self.endpoint.label)
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text.append(delta["content"])
                    await on_text(delta["content"])
                for part in delta.get("tool_calls") or []:
                    index = part.get("index", len(calls))
                    slot = calls.setdefault(index, {"id": None, "function": {"name": "", "arguments": ""}})
                    if part.get("id"):
                        slot["id"] = part["id"]
                    function = part.get("function") or {}
                    name = function.get("name")
                    # Most providers send the name once; some repeat it in every chunk.
                    if name and name != slot["function"]["name"]:
                        slot["function"]["name"] = name if not slot["function"]["name"] else slot["function"]["name"] + name
                    arguments = function.get("arguments")
                    if isinstance(arguments, dict):
                        slot["function"]["arguments"] = arguments
                    elif isinstance(arguments, str) and isinstance(slot["function"]["arguments"], str):
                        slot["function"]["arguments"] += arguments
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
        return "".join(text), [calls[index] for index in sorted(calls)], finish

    def add_results(self, results: list[Result]) -> None:
        self.messages += [{"role": "tool", "tool_call_id": item.call_id, "content": item.content} for item in results]

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()


def start(settings: Settings, config: ChatSetting, *, endpoint: Endpoint | None, system: str, messages: list[dict],
          tools: list[Tool], user_id: str | None) -> Conversation:
    """Open a conversation for one turn. `messages` are prior turns and the new user message, as text.

    `endpoint` is None for Claude, otherwise the OpenAI-compatible provider to call.
    """

    if endpoint is not None:
        return OpenAICompatibleConversation(settings, config, endpoint, system, messages, tools)
    if not settings.anthropic_api_key:
        raise HubError("CHAT_NOT_CONFIGURED", "The Hub has no Anthropic API key yet. Ask an admin to add it.", 503)
    return AnthropicConversation(settings, config, system, messages, tools, user_id)
