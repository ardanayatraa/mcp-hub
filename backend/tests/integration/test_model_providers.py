"""OpenAI-compatible model providers: registry, connection test, and chat turns through them."""

import json
from types import SimpleNamespace

import httpx
import pytest
from app.chat import providers, registry
from app.persistence.models import ChatSetting, ModelProvider
from app.persistence.session import open_session
from app.tools import catalog
from sqlalchemy import select
from tests import helpers
from tests.helpers import api, connect_app, delegation, issue_key

SECRET = "sk-provider-secret-value-9876"


def add_provider(admin, **body):
    data = {"key": "acme", "name": "Acme AI", "base_url": "https://api.acme.test/v1", "api_key": SECRET, **body}
    return api(admin, "POST", "/model-providers", data, expect=201).json()["data"]


class Upstream:
    """A fake provider: answers in order and records every request."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


@pytest.fixture()
def upstream(monkeypatch):
    holder = SimpleNamespace(fake=Upstream())
    monkeypatch.setattr(registry, "resolve", lambda url, settings: ("api.acme.test", 443, ["93.184.216.34"]))
    monkeypatch.setattr(registry, "http_client", lambda endpoint, settings, destination: httpx.AsyncClient(
        base_url=endpoint.base_url, headers=endpoint.headers, transport=httpx.MockTransport(lambda r: holder.fake(r))))
    return holder


def sse(*chunks) -> httpx.Response:
    body = "".join(f"data: {json.dumps(chunk) if not isinstance(chunk, str) else chunk}\n\n" for chunk in chunks)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_providers_are_validated_and_keys_never_returned(admin):
    created = add_provider(admin, headers={"X-Title": "MCP Hub"}, default_model="acme-large")
    assert created["api_key_set"] is True and created["api_key_hint"] == "9876" and created["status"] == "untested"
    listing = api(admin, "GET", "/model-providers", expect=200)
    assert SECRET not in listing.text and SECRET not in json.dumps(created)
    assert listing.json()["data"]["builtin"][0]["key"] == "anthropic"
    db = open_session()
    try:
        stored = db.scalar(select(ModelProvider).where(ModelProvider.key == "acme"))
        assert SECRET not in stored.api_key_ciphertext  # encrypted at rest
    finally:
        db.close()

    bad = [
        {"key": "anthropic"}, {"key": "Acme Two"}, {"key": "acme"},
        {"key": "p2", "base_url": "http://10.1.2.3/v1"}, {"key": "p3", "base_url": "http://169.254.169.254/v1"},
        {"key": "p4", "base_url": "https://user:pw@api.acme.test/v1"}, {"key": "p5", "base_url": "https://api.acme.test/v1?x=1"},
        {"key": "p6", "auth_style": "header"}, {"key": "p7", "headers": {"Authorization": "Bearer x"}},
        {"key": "p8", "headers": {"X-Bad": "a\r\nInjected: 1"}}, {"key": "p9", "token_param": "tokens"},
        {"key": "p10", "api_key": "two words"},
    ]
    for override in bad:
        body = {"key": "x", "name": "X", "base_url": "https://api.acme.test/v1", **override}
        assert api(admin, "POST", "/model-providers", body).status_code in (409, 422), override

    updated = api(admin, "PATCH", f"/model-providers/{created['id']}", {"name": "Acme", "auth_style": "header",
                  "auth_header": "api-key", "clear_api_key": True}, expect=200).json()["data"]
    assert updated["auth_header"] == "api-key" and updated["api_key_set"] is False and updated["ready"] is False
    assert api(admin, "PATCH", f"/model-providers/{created['id']}", {"key": "other"}).status_code == 422


def test_only_super_admins_change_providers(admin):
    client = admin["client"]
    api(admin, "POST", "/users", {"email": "scoped@localhost", "password": "ChangeMe-Now-12", "role": "app_admin"}, expect=201)
    client.cookies.clear()
    login = client.post("/api/admin/v1/auth/login", json={"email": "scoped@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
    headers = {"X-CSRF-Token": login["csrf_token"]}
    assert client.get("/api/admin/v1/model-providers", headers=headers).status_code == 200
    body = {"key": "acme", "name": "Acme", "base_url": "https://api.acme.test/v1"}
    assert client.post("/api/admin/v1/model-providers", headers=headers, json=body).status_code == 403


def test_connection_test_lists_models(admin, upstream):
    provider = add_provider(admin)
    upstream.fake = Upstream(httpx.Response(200, json={"data": [{"id": "acme-small"}, {"id": "acme-large"}, {"id": "bad name"}]}))
    tested = api(admin, "POST", f"/model-providers/{provider['id']}/test", expect=200).json()["data"]
    assert tested["status"] == "ok" and tested["models"] == ["acme-large", "acme-small"]
    request = upstream.fake.requests[0]
    assert request.url.path == "/v1/models" and request.headers["Authorization"] == f"Bearer {SECRET}"
    upstream.fake = Upstream(httpx.Response(401, json={"error": {"message": "Invalid API key"}}))
    failed = api(admin, "POST", f"/model-providers/{provider['id']}/test", expect=200).json()["data"]
    assert failed["status"] == "error" and "Invalid API key" in failed["status_message"]
    assert failed["models"] == ["acme-large", "acme-small"]  # the last good list is kept


def test_chat_streams_through_a_registered_provider(admin, monkeypatch, upstream):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        add_provider(admin, auth_style="header", auth_header="api-key", token_param="max_completion_tokens",
                     tool_schema="basic")
        chat = api(admin, "PATCH", f"/connectors/{app['connector_id']}/chat",
                   {"enabled": True, "provider": "acme", "model": "acme-large"}, expect=200).json()["data"]
        acme = next(item for item in chat["options"]["providers"] if item["id"] == "acme")
        assert acme["ready"] is True and chat["fallbacks"] is False
        upstream.fake = Upstream(
            sse({"choices": [{"index": 0, "delta": {"role": "assistant", "content": "Checking. "}}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_a", "type": "function",
                                                                     "function": {"name": "run_report", "arguments": ""}}]}}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"source\": "}}]}}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"projects\"}"}}]}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}, "[DONE]"),
            sse({"choices": [{"index": 0, "delta": {"content": "You have 4 projects."}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}, "[DONE]"),
        )
        token = issue_key(admin)
        response = admin["client"].post("/chat/v1/turn", headers={"Authorization": f"Bearer {token}",
                                        "X-Hub-Delegation": delegation()}, json={"message": "How many projects?"})
        assert response.status_code == 200
        text = "".join(json.loads(line[6:])["delta"] for line in response.text.splitlines()
                       if line.startswith("data: ") and '"delta"' in line)
        assert text == "Checking. You have 4 projects."
        assert '"status": "done"' in response.text and '"name": "run_report"' in response.text

        first, second = upstream.fake.requests
        assert first.headers["api-key"] == SECRET and "authorization" not in first.headers
        body = json.loads(first.content)
        assert body["model"] == "acme-large" and body["stream"] is True and body["max_completion_tokens"] == 16000
        assert "max_tokens" not in body and body["tool_choice"] == "auto"
        report = next(tool for tool in body["tools"] if tool["function"]["name"] == "run_report")["function"]["parameters"]
        assert "additionalProperties" not in json.dumps(report) and "anyOf" not in json.dumps(report)
        follow_up = json.loads(second.content)["messages"]
        assert follow_up[-2]["tool_calls"][0] == {"id": "call_a", "type": "function", "function": {
            "name": "run_report", "arguments": "{\"source\": \"projects\"}"}}
        assert follow_up[-1]["role"] == "tool" and json.loads(follow_up[-1]["content"])["data"]["totals"]["count"] == 4


def test_provider_errors_are_explained_and_used_providers_are_kept(admin, monkeypatch, upstream):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        provider = add_provider(admin, streaming=False)
        api(admin, "PATCH", f"/connectors/{app['connector_id']}/chat", {"enabled": True, "provider": "acme", "model": "nope"},
            expect=200)
        upstream.fake = Upstream(httpx.Response(404, json={"error": {"message": "The model nope does not exist"}}))
        token = issue_key(admin)
        failed = admin["client"].post("/chat/v1/turn", headers={"Authorization": f"Bearer {token}"},
                                      json={"message": "Hi", "stream": False})
        assert failed.status_code == 502 and "does not exist" in failed.json()["error"]["message"]

        assert api(admin, "DELETE", f"/model-providers/{provider['id']}").status_code == 409  # Your App uses it
        api(admin, "PATCH", f"/model-providers/{provider['id']}", {"enabled": False}, expect=200)
        off = admin["client"].post("/chat/v1/turn", headers={"Authorization": f"Bearer {token}"}, json={"message": "Hi"})
        assert off.status_code == 503 and off.json()["error"]["code"] == "CHAT_NOT_CONFIGURED"
        api(admin, "PATCH", f"/connectors/{app['connector_id']}/chat", {"provider": "anthropic", "model": "claude-opus-5-5"},
            expect=200)
        api(admin, "DELETE", f"/model-providers/{provider['id']}", expect=200)
        assert api(admin, "PATCH", f"/connectors/{app['connector_id']}/chat", {"provider": "acme"}).status_code == 422


def test_basic_schema_keeps_only_what_strict_providers_accept():
    shaped = providers.basic_schema(catalog.REPORT_INPUT)
    text = json.dumps(shaped)
    for keyword in ("anyOf", "additionalProperties", "maxLength", "maxItems", '"null"'):
        assert keyword not in text
    assert shaped["required"] == ["source"] and shaped["properties"]["filters"]["items"]["properties"]["value"]["type"] == "string"


async def test_local_servers_without_ids_or_with_object_arguments(monkeypatch):
    replies = [httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [
        {"function": {"name": "run_report", "arguments": {"source": "projects"}}}]}}]})]

    async def open_client(endpoint, settings):
        return httpx.AsyncClient(base_url=endpoint.base_url, transport=httpx.MockTransport(lambda request: replies.pop(0)))

    monkeypatch.setattr(registry, "open_client", open_client)
    endpoint = registry.Endpoint("Ollama", "http://127.0.0.1:11434/v1", token_param="none", streaming=True)
    conversation = providers.OpenAICompatibleConversation(SimpleNamespace(chat_max_tokens=100), ChatSetting(model="qwen3"),
                                                          endpoint, "system", [{"role": "user", "content": "Hi"}], [])

    async def on_text(text):
        return None

    step = await conversation.step(on_text)
    assert step.calls[0].id == "call_1" and step.calls[0].arguments == {"source": "projects"}
    assert conversation.messages[-1]["tool_calls"][0]["function"]["arguments"] == "{\"source\": \"projects\"}"
    await conversation.close()


@pytest.fixture()
def fresh_catalog(monkeypatch):
    monkeypatch.setattr(registry, "_claude", {"at": 0.0, "key": "", "models": []})
    monkeypatch.setattr(registry, "_gateway", {"at": 0.0, "models": []})


def test_claude_models_are_fetched_once_and_recommended_first(admin, monkeypatch, fresh_catalog):
    from app.config import get_settings

    path = "/model-providers/anthropic/models"
    offline = api(admin, "GET", path, expect=200).json()["data"]
    assert offline["source"] == "builtin" and [m["id"] for m in offline["models"]][0] == "claude-opus-5-5"
    assert "ANTHROPIC_API_KEY" in offline["error"]

    calls = []

    async def listed(settings):
        calls.append(1)
        return [{"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "max_tokens": 128000, "effort": True},
                {"id": "claude-opus-5", "label": "Claude Opus 5", "max_tokens": 128000, "effort": True}]

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    monkeypatch.setattr(registry, "_claude_models", listed)
    live = api(admin, "GET", path, expect=200).json()["data"]
    ids = [m["id"] for m in live["models"]]
    assert live["source"] == "live" and ids[:3] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert ids[3] == "claude-opus-5" and live["models"][0]["hint"]
    assert api(admin, "GET", path, expect=200).json()["data"]["source"] == "cache" and len(calls) == 1
    api(admin, "GET", path + "?refresh=true", expect=200)
    assert len(calls) == 2

    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        chat = f"/connectors/{app['connector_id']}/chat"
        assert api(admin, "PATCH", chat, {"model": "claude-opus-5"}).status_code == 200  # a fetched model
        assert api(admin, "PATCH", chat, {"model": "gpt-4o"}).status_code == 422


def test_provider_models_load_by_themselves_and_stay_cached(admin, upstream, fresh_catalog):
    provider = add_provider(admin)
    assert provider["models"] == []
    upstream.fake = Upstream(httpx.Response(200, json={"data": [{"id": "acme-small"}, {"id": "acme-large"}]}))
    first = api(admin, "GET", "/model-providers/acme/models", expect=200).json()["data"]
    assert first["source"] == "live" and [m["id"] for m in first["models"]] == ["acme-large", "acme-small"]
    again = api(admin, "GET", "/model-providers/acme/models", expect=200).json()["data"]
    assert again["source"] == "cache" and len(upstream.fake.requests) == 1  # no second call within a few hours
    upstream.fake = Upstream(httpx.Response(200, json={"data": [{"id": "acme-new"}]}))
    refreshed = api(admin, "GET", "/model-providers/acme/models?refresh=true", expect=200).json()["data"]
    assert refreshed["source"] == "live" and [m["id"] for m in refreshed["models"]] == ["acme-new"]
    listing = api(admin, "GET", "/model-providers", expect=200).json()["data"]["providers"][0]
    assert listing["models"] == ["acme-new"] and listing["status"] == "ok"
    upstream.fake = Upstream(httpx.Response(503, json={"error": {"message": "maintenance"}}))
    failed = api(admin, "GET", "/model-providers/acme/models?refresh=true", expect=200).json()["data"]
    assert "maintenance" in failed["error"] and [m["id"] for m in failed["models"]] == ["acme-new"]  # the last good list stays
    assert api(admin, "GET", "/model-providers/nope/models").status_code == 404


async def test_claude_requests_follow_the_fetched_model_details(monkeypatch, fresh_catalog):
    from app.persistence.models import ChatSetting

    registry._claude["models"] = [{"id": "claude-small-x", "label": "Small", "max_tokens": 8000, "effort": False}]
    sent: list[dict] = []
    message = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Hi")])

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def __aiter__(self):
            async def gen():
                if False:
                    yield None
            return gen()

        async def get_final_message(self):
            return message

    class FakeClient:
        def __init__(self, **kwargs):
            self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **params: sent.append(params) or FakeStream()))

        async def close(self):
            return None

    monkeypatch.setattr(providers.anthropic, "AsyncAnthropic", FakeClient)
    settings = SimpleNamespace(anthropic_api_key="k", chat_timeout_seconds=30, chat_max_tokens=16000)
    conversation = providers.AnthropicConversation(settings, ChatSetting(model="claude-small-x", effort="medium"),
                                                   "system", [{"role": "user", "content": "Hi"}], [], None)

    async def on_text(text):
        return None

    await conversation.step(on_text)
    assert sent[0]["max_tokens"] == 8000 and "output_config" not in sent[0]


async def test_claude_model_list_through_the_real_sdk(monkeypatch):
    import httpx2

    def caps(adaptive: bool, effort: bool) -> dict:
        support = {"supported": effort}
        return {"thinking": {"supported": True, "types": {"adaptive": {"supported": adaptive}, "enabled": {"supported": not adaptive},
                                                          "disabled": {"supported": True}}},
                "effort": {"supported": effort, "low": support, "medium": support, "high": support, "max": support}}

    def model(model_id, lifecycle="active", adaptive=True, effort=True):
        return {"type": "model", "id": model_id, "display_name": model_id.replace("-", " ").title(), "created_at": "2026-09-01T00:00:00Z",
                "lifecycle": lifecycle, "max_input_tokens": 1000000, "max_tokens": 128000, "capabilities": caps(adaptive, effort)}

    page = {"data": [model("claude-opus-5-5"), model("claude-opus-4-1", lifecycle="deprecated"),
                     model("claude-haiku-4-5", adaptive=False, effort=False)],
            "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-haiku-4-5"}
    real = registry.anthropic.AsyncAnthropic
    monkeypatch.setattr(registry.anthropic, "AsyncAnthropic", lambda **kwargs: real(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json=page))), **kwargs))
    found = await registry._claude_models(SimpleNamespace(anthropic_api_key="k"))
    assert found == [{"id": "claude-opus-5-5", "label": "Claude Opus 5 5", "max_tokens": 128000, "effort": True}]
