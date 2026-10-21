"""The model gateway: apps list every model the Hub holds keys for and call them, OpenAI style or as an MCP bridge."""

import json
from types import SimpleNamespace

import httpx
from app.chat import gateway, registry
from app.config import get_settings
from app.persistence.models import AuditEvent
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import api, connect_app, issue_key
from tests.integration.test_model_providers import (  # noqa: F401
    SECRET,
    Upstream,
    add_provider,
    upstream,
)
from tests.integration.test_switches_and_chat import enable_chat

CLAUDE_KEY = "sk-ant-gateway-test-key-1111"


def ready_app(admin, monkeypatch, upstream_fake, chat=True):  # noqa: F811
    """A connected app with a key, an Acme provider whose models were tested, and a saved Claude key."""

    helpers.dns(monkeypatch)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    monkeypatch.setattr(registry, "_claude_models", _no_live_claude_models)
    app = connect_app(admin)
    provider = add_provider(admin)
    upstream_fake.fake = Upstream(httpx.Response(200, json={"data": [{"id": "acme-small"}, {"id": "acme-large"}]}))
    api(admin, "POST", f"/model-providers/{provider['id']}/test", expect=200)
    api(admin, "PUT", "/model-providers/anthropic/key", {"api_key": CLAUDE_KEY}, expect=200)
    if chat:
        enable_chat(admin, app["connector_id"])
    return app, issue_key(admin)


async def _no_live_claude_models(settings):
    return []


def call(admin, token, method, path, body=None):
    headers = {"Authorization": f"Bearer {token}"}
    if method == "GET":
        return admin["client"].get(path, headers=headers)
    return admin["client"].post(path, headers=headers, json=body)


def mcp(admin, token, name, arguments=None):
    response = call(admin, token, "POST", "/gateway/mcp", {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                                          "params": {"name": name, "arguments": arguments or {}}})
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/json")
    return response.json()["result"]


def test_models_from_every_ready_provider_reach_the_app(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        listing = call(admin, token, "GET", "/gateway/v1/models").json()
        ids = [row["id"] for row in listing["data"]]
        assert "anthropic/claude-opus-5-5" in ids and {"acme/acme-large", "acme/acme-small"} <= set(ids)
        assert listing["default"] == "anthropic/claude-opus-5-5"  # the app's Chat model
        assert next(row for row in listing["data"] if row["id"] == "acme/acme-large")["name"] == "acme-large · Acme AI"
        assert CLAUDE_KEY not in json.dumps(listing) and SECRET not in json.dumps(listing)

        bridged = mcp(admin, token, "list_ai_models")
        assert bridged["isError"] is False and bridged["structuredContent"]["result"]["data"] == [
            {"id": row["id"], "provider": row["owned_by"], "name": row["name"]} for row in listing["data"]]
        tools = call(admin, token, "POST", "/gateway/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
        assert [tool["name"] for tool in tools["result"]["tools"]] == ["list_ai_models", "chat_ai"]


def test_models_need_a_key_and_the_apps_chat_on(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream, chat=False)
        assert call(admin, "hub_not_a_key", "GET", "/gateway/v1/models").status_code == 401
        refused = call(admin, token, "GET", "/gateway/v1/models")
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "CHAT_DISABLED"
        bridged = mcp(admin, token, "list_ai_models")
        assert bridged["isError"] is True and bridged["content"][0]["text"].startswith("CHAT_DISABLED")


def test_production_gateway_requires_explicit_models_and_budget(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, token = ready_app(admin, monkeypatch, upstream)
        monkeypatch.setattr(get_settings(), "environment", "production")
        path = f"/connectors/{app['connector_id']}/chat"
        listing = call(admin, token, "GET", "/gateway/v1/models")
        assert listing.status_code == 403 and listing.json()["error"]["code"] == "MODEL_ACCESS_UNCONFIGURED"
        request = {"model": "acme/acme-small", "messages": [{"role": "user", "content": "Hi"}]}
        rejected = call(admin, token, "POST", "/gateway/v1/chat/completions", request)
        assert rejected.status_code == 403 and rejected.json()["error"]["code"] == "MODEL_ACCESS_UNCONFIGURED"

        api(admin, "PATCH", path, {"gateway_models": ["acme/acme-small"]}, expect=200)
        listing = call(admin, token, "GET", "/gateway/v1/models")
        assert listing.status_code == 403 and listing.json()["error"]["code"] == "TOKEN_BUDGET_UNCONFIGURED"
        api(admin, "PATCH", path, {"monthly_token_limit": 1000}, expect=200)
        listing = call(admin, token, "GET", "/gateway/v1/models").json()
        assert [row["id"] for row in listing["data"]] == ["acme/acme-small"]
        rejected = call(admin, token, "POST", "/gateway/v1/chat/completions", {**request, "model": "acme/acme-large"})
        assert rejected.status_code == 403 and rejected.json()["error"]["code"] == "MODEL_NOT_ALLOWED"


def test_rotating_end_users_cannot_escape_the_app_budget(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        monkeypatch.setattr(get_settings(), "gateway_app_rate_limit", 2)
        upstream.fake = Upstream(*[httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
                                   for _ in range(3)])
        statuses = [call(admin, token, "POST", "/gateway/v1/chat/completions", {
            "model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}],
            "metadata": {"end_user_id": f"user-{n}"}}).status_code for n in range(3)]
        assert statuses == [200, 200, 429] and len(upstream.fake.requests) == 2


def test_provider_errors_are_logged_without_personal_data(admin, monkeypatch, upstream, caplog):  # noqa: F811
    # Alembic's fileConfig (run by the migration tests in this process) disables existing loggers.
    monkeypatch.setattr(gateway.logger, "disabled", False)
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        body = {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}]}
        upstream.fake = Upstream(httpx.Response(400, json={"error": {"message": "Invalid schema for function 'x'"}}),
                                 httpx.Response(400, json={"error": {"message": "Rejected for owner canary@example.com"}}))
        with caplog.at_level("WARNING", logger="hub.gateway"):
            assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code == 502
            assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code == 502
        details = [record.detail for record in caplog.records if record.getMessage() == "gateway_model_error"]
        assert "Invalid schema for function 'x'" in details[0] and details[1] == "(withheld: personal data)"


def test_pausing_the_app_stops_its_model_calls(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, token = ready_app(admin, monkeypatch, upstream)
        assert call(admin, token, "GET", "/gateway/v1/models").status_code == 200
        api(admin, "POST", f"/connectors/{app['connector_id']}/pause", expect=200)
        paused = call(admin, token, "POST", "/gateway/v1/chat/completions",
                      {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}]})
        assert paused.status_code == 409 and paused.json()["error"]["code"] == "CONNECTOR_INACTIVE"


def test_openai_providers_get_the_tools_and_answer_with_tool_calls(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        tools = [{"type": "function", "function": {"name": "count_projects", "description": "Count projects",
                                                   "parameters": {"type": "object", "properties": {}}}}]
        upstream.fake = Upstream(httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "count_projects", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}))
        body = {"model": "acme/acme-large", "messages": [{"role": "user", "content": "How many projects?"}],
                "tools": tools, "tool_choice": "auto", "metadata": {"end_user_id": "42"}}
        answer = call(admin, token, "POST", "/gateway/v1/chat/completions", body).json()
        assert answer["model"] == "acme/acme-large" and answer["choices"][0]["finish_reason"] == "tool_calls"
        assert answer["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "count_projects"
        sent = upstream.fake.requests[0]
        assert sent.url.path == "/v1/chat/completions" and sent.headers["Authorization"] == f"Bearer {SECRET}"
        forwarded = json.loads(sent.content)
        assert forwarded["model"] == "acme-large" and forwarded["tools"][0]["function"]["name"] == "count_projects"
        assert forwarded["tool_choice"] == "auto" and "metadata" not in forwarded and token not in sent.content.decode()

        upstream.fake = Upstream(httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "You have 4 projects."}}]}))
        body["messages"] += [answer["choices"][0]["message"], {"role": "tool", "tool_call_id": "c1", "content": "{\"count\": 4}"}]
        final = mcp(admin, token, "chat_ai", body)["structuredContent"]["result"]
        assert final["choices"][0]["message"]["content"] == "You have 4 projects."
        assert json.loads(upstream.fake.requests[0].content)["messages"][-1] == {
            "role": "tool", "content": "{\"count\": 4}", "tool_call_id": "c1"}
        db = open_session()
        try:
            events = db.scalars(select(AuditEvent).where(AuditEvent.action == "model.chat")).all()
            assert [event.tool_key for event in events] == ["acme/acme-large", "acme/acme-large"]
            assert {event.result for event in events} == {"success"}
        finally:
            db.close()


def test_claude_gets_converted_turns_and_its_tool_use_comes_back_openai_style(admin, monkeypatch, upstream):  # noqa: F811
    seen: dict = {}

    class FakeMessages:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Checking. "),
                         SimpleNamespace(type="tool_use", id="toolu_1", name="count_projects", input={"status": "active"})],
                stop_reason="tool_use", usage=SimpleNamespace(input_tokens=20, output_tokens=5))

    class FakeClient:
        def __init__(self, **kwargs):
            seen["api_key"] = kwargs["api_key"]
            self.messages = FakeMessages()

        async def close(self):
            return None

    monkeypatch.setattr(gateway.anthropic, "AsyncAnthropic", FakeClient)
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        body = {"model": "anthropic/claude-opus-5-5", "tool_choice": "required", "messages": [
            {"role": "system", "content": "Be brief."}, {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": [{"type": "text", "text": "Active projects?"}]},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "toolu_0", "type": "function", "function": {"name": "count_projects", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "toolu_0", "content": "{\"count\": 9}"},
            {"role": "user", "content": "Only active ones."}],
            "tools": [{"type": "function", "function": {"name": "count_projects", "parameters": {
                "type": "object", "properties": {"status": {"type": "string"}}}}}]}
        answer = call(admin, token, "POST", "/gateway/v1/chat/completions", body).json()
    assert seen["api_key"] == CLAUDE_KEY and seen["model"] == "claude-opus-5-5" and seen["system"] == "Be brief."
    assert [turn["role"] for turn in seen["messages"]] == ["user", "assistant", "user"]
    assert seen["messages"][1]["content"] == [{"type": "tool_use", "id": "toolu_0", "name": "count_projects", "input": {}}]
    assert seen["messages"][2]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_0", "content": "{\"count\": 9}"},
                                              {"type": "text", "text": "Only active ones."}]
    assert seen["tools"][0]["input_schema"]["properties"] == {"status": {"type": "string"}}
    assert seen["tool_choice"] == {"type": "any"}
    message = answer["choices"][0]["message"]
    assert answer["choices"][0]["finish_reason"] == "tool_calls" and message["content"] == "Checking. "
    assert message["tool_calls"] == [{"id": "toolu_1", "type": "function",
                                      "function": {"name": "count_projects", "arguments": "{\"status\": \"active\"}"}}]
    assert answer["usage"] == {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}


def test_php_empty_arrays_reach_providers_as_objects(admin, monkeypatch, upstream):  # noqa: F811
    """Laravel encodes empty maps as []: "properties": [], "parameters": [], "arguments": "[]"."""

    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        upstream.fake = Upstream(httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "Done."}}]}))
        body = {"model": "acme/acme-large", "tool_choice": "required", "messages": [
            {"role": "user", "content": "How many templates?"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "count_templates", "arguments": "[]"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{\"count\": 80}"}],
            "tools": [{"type": "function", "function": {"name": "count_templates", "parameters": {
                "type": "object", "additionalProperties": False, "properties": [], "required": []}}},
                {"type": "function", "function": {"name": "ping", "parameters": []}},
                {"type": "function", "function": {"name": "nested", "parameters": {"type": "object", "properties": {
                    "filter": {"type": "object", "properties": []}, "rows": {"type": "array", "items": {"type": "object"}}}}}}]}
        assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code == 200
        sent = json.loads(upstream.fake.requests[0].content)
        assert sent["tools"][0]["function"]["parameters"]["properties"] == {}
        assert sent["tools"][1]["function"]["parameters"] == {"type": "object", "properties": {}}
        nested = sent["tools"][2]["function"]["parameters"]["properties"]
        assert nested["filter"]["properties"] == {} and nested["rows"]["items"] == {"type": "object", "properties": {}}
        assert sent["messages"][1]["tool_calls"][0]["function"]["arguments"] == "{}"


def test_requests_are_validated_before_any_provider_is_called(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        upstream.fake = Upstream()
        user = [{"role": "user", "content": "Hi"}]
        for body in ({"model": "acme-large", "messages": user}, {"model": "ghost/model-x", "messages": user},
                     {"model": "acme/acme-large", "messages": []}, {"model": "acme/acme-large", "messages": [{"role": "bot"}]},
                     {"model": "acme/acme-large", "messages": [{"role": "tool", "content": "x"}]},
                     {"model": "acme/acme-large", "messages": user, "tools": [{"type": "function"}]},
                     {"model": "acme/acme-large", "messages": user, "tool_choice": "sometimes"},
                     {"model": "acme/acme-large", "messages": user, "max_tokens": 10 ** 9}):
            assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code == 422, body
        bridged = mcp(admin, token, "chat_ai", {"model": "acme/acme-large", "messages": []})
        assert bridged["isError"] is True and bridged["content"][0]["text"].startswith("VALIDATION_FAILED")
        unknown = call(admin, token, "POST", "/gateway/mcp", {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}).json()
        assert unknown["error"]["code"] == -32601
        assert not [sent for sent in upstream.fake.requests if sent.url.path.endswith("/chat/completions")]


def ok_answer(tokens=(10, 5)):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}],
                                     "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}})


def test_only_the_allowed_models_are_listed_and_callable(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, token = ready_app(admin, monkeypatch, upstream)
        chat = f"/connectors/{app['connector_id']}/chat"
        everything = api(admin, "GET", f"{chat}/gateway-models", expect=200).json()["data"]["models"]
        assert {"acme/acme-large", "anthropic/claude-opus-5-5"} <= {row["id"] for row in everything}
        api(admin, "PATCH", chat, {"gateway_models": ["unknown/x"]}, expect=422)
        api(admin, "PATCH", chat, {"gateway_models": ["acme/acme-small"]}, expect=200)
        listing = call(admin, token, "GET", "/gateway/v1/models").json()
        assert [row["id"] for row in listing["data"]] == ["acme/acme-small"] and listing["default"] == "acme/acme-small"
        refused = call(admin, token, "POST", "/gateway/v1/chat/completions",
                       {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}]})
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "MODEL_NOT_ALLOWED"
        assert not [sent for sent in upstream.fake.requests if sent.url.path.endswith("/chat/completions")]
        api(admin, "PATCH", chat, {"gateway_models": ["acme/*"]}, expect=200)
        assert {row["id"] for row in call(admin, token, "GET", "/gateway/v1/models").json()["data"]} == {
            "acme/acme-small", "acme/acme-large"}
        with open_session() as db:
            assert db.scalar(select(AuditEvent).where(AuditEvent.error_code == "MODEL_NOT_ALLOWED")) is not None


def test_usage_is_counted_and_the_monthly_budget_stops_the_app(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, token = ready_app(admin, monkeypatch, upstream)
        chat = f"/connectors/{app['connector_id']}/chat"
        api(admin, "PATCH", chat, {"monthly_token_limit": 25}, expect=200)
        upstream.fake = Upstream(ok_answer((10, 5)), httpx.Response(500, json={}), ok_answer((8, 4)))
        body = {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}]}
        statuses = [call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code for _ in range(4)]
        # 15 tokens, a failed call, 12 more (27 >= 25), then the budget refuses before the provider is asked.
        assert statuses[0] == 200 and statuses[1] >= 500 and statuses[2] == 200
        assert statuses[3] == 429 and len(upstream.fake.requests) == 3
        usage = api(admin, "GET", chat, expect=200).json()["data"]["gateway_usage"]
        assert usage["calls"] == 3 and usage["errors"] == 1
        assert usage["prompt_tokens"] == 18 and usage["completion_tokens"] == 9
        assert usage["models"] == [{"model": "acme/acme-large", "calls": 3, "errors": 1, "tokens": 27}]
        api(admin, "PATCH", chat, {"monthly_token_limit": 0}, expect=200)
        upstream.fake = Upstream(ok_answer())
        assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code == 200


def test_the_daily_limit_counts_questions_not_tool_rounds(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, token = ready_app(admin, monkeypatch, upstream)
        api(admin, "PATCH", f"/connectors/{app['connector_id']}/chat", {"daily_limit": 1}, expect=200)
        upstream.fake = Upstream(*[ok_answer() for _ in range(3)])
        question = [{"role": "user", "content": "How many projects?"}]
        tool_round = [*question, {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "count_projects", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{\"count\": 3}"}]
        meta = {"end_user_id": "7"}
        sent = [call(admin, token, "POST", "/gateway/v1/chat/completions",
                     {"model": "acme/acme-large", "messages": messages, "metadata": meta}).status_code
                for messages in (question, tool_round, tool_round, question)]
        assert sent == [200, 200, 200, 429]


def test_a_briefly_unavailable_provider_gets_one_more_try(admin, monkeypatch, upstream):  # noqa: F811
    monkeypatch.setattr(gateway, "RETRY_DELAY", 0)
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        body = {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}]}
        upstream.fake = Upstream(httpx.Response(503, json={}), ok_answer())
        assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code == 200
        upstream.fake = Upstream(httpx.Response(503, json={}), httpx.Response(503, json={}))
        assert call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code >= 500
        assert len(upstream.fake.requests) == 2


def test_only_super_admins_change_model_access_and_budget(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, _ = ready_app(admin, monkeypatch, upstream)
        chat = f"/api/admin/v1/connectors/{app['connector_id']}/chat"
        api(admin, "POST", "/users", {"email": "scoped@localhost", "password": "ChangeMe-Now-12", "role": "app_admin",
                                      "app_ids": [app["app_id"]]}, expect=201)
        client = admin["client"]
        client.cookies.clear()
        login = client.post("/api/admin/v1/auth/login", json={"email": "scoped@localhost", "password": "ChangeMe-Now-12"})
        headers = {"X-CSRF-Token": login.json()["data"]["csrf_token"]}
        assert client.patch(chat, headers=headers, json={"daily_limit": 50}).status_code == 200
        for body in ({"monthly_token_limit": 0}, {"gateway_models": []}, {"daily_limit": 5, "gateway_models": []}):
            assert client.patch(chat, headers=headers, json=body).status_code == 403
        assert client.get(chat, headers=headers).json()["data"]["daily_limit"] == 50


def test_refused_models_are_rate_limited_and_openai_user_names_the_end_user(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        app, token = ready_app(admin, monkeypatch, upstream)
        api(admin, "PATCH", f"/connectors/{app['connector_id']}/chat", {"gateway_models": ["acme/acme-small"]}, expect=200)
        monkeypatch.setattr(get_settings(), "chat_rate_limit", 2)
        body = {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}], "user": "u-9"}
        codes = [call(admin, token, "POST", "/gateway/v1/chat/completions", body).status_code for _ in range(3)]
        assert codes == [403, 403, 429]
        other = call(admin, token, "POST", "/gateway/v1/chat/completions", {**body, "user": "u-10"})
        assert other.status_code == 403  # a different end user has its own budget


def test_streamed_tool_calls_carry_their_index(admin, monkeypatch, upstream):  # noqa: F811
    with helpers.source():
        _, token = ready_app(admin, monkeypatch, upstream)
        upstream.fake = Upstream(httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "one", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "two", "arguments": "{}"}}]}}]}))
        response = call(admin, token, "POST", "/gateway/v1/chat/completions",
                        {"model": "acme/acme-large", "messages": [{"role": "user", "content": "Hi"}], "stream": True})
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1] == "[DONE]"
        chunk = json.loads(events[0])
        assert chunk["object"] == "chat.completion.chunk"
        assert [(c["index"], c["id"]) for c in chunk["choices"][0]["delta"]["tool_calls"]] == [(0, "a"), (1, "b")]
