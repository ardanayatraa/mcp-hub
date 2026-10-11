"""Per-app tool switches and the Hub-hosted chat (with a scripted model)."""

import json
from types import SimpleNamespace

import httpx
import pytest
from app.chat import providers
from app.config import get_settings
from app.persistence.models import AuditEvent
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import api, call, connect_app, delegation, error_text, issue_key, listed, mcp

SWITCHES = "/connectors/{}/tool-switches"


def generate(admin, connector_id):
    return api(admin, "POST", "/tools/generate", {"connector_id": connector_id}, expect=201).json()["data"]


def switch(admin, connector_id, **tools):
    return api(admin, "PUT", SWITCHES.format(connector_id), {"tools": tools}, expect=200).json()["data"]


def audits(action: str) -> list[AuditEvent]:
    db = open_session()
    try:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.created_at)))
    finally:
        db.close()


def test_switched_off_tools_disappear_and_are_refused(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        generate(admin, app["connector_id"])
        token = issue_key(admin)
        skill = {"connector_id": app["connector_id"], "key": "weekly_report", "title": "Weekly report",
                 "description": "Weekly report", "instructions": "Report on projects with run_report.",
                 "arguments": [], "tools": ["run_report"]}
        api(admin, "POST", "/skills", skill, expect=201)
        assert "run_report" in listed(admin["client"], token)

        view = switch(admin, app["connector_id"], run_report=False, your_app__projects__list=False)
        rows = {row["name"]: row for row in view["tools"]}
        assert rows["run_report"]["enabled"] is False and rows["list_data_sources"]["enabled"] is True
        assert rows["your_app__projects__list"]["kind"] == "app" and rows["save_memory"]["kind"] == "memory"
        assert rows["save_memory"]["note"] == "Memory is off for this app" and view["off"] == 2

        names = listed(admin["client"], token)
        assert "run_report" not in names and "your_app__projects__list" not in names and "list_data_sources" in names
        assert "TOOL_DISABLED" in error_text(call(admin["client"], token, "run_report", {"source": "projects"}, delegation()))
        assert "TOOL_DISABLED" in error_text(call(admin["client"], token, "your_app__projects__list", {}, delegation()))
        prompts = mcp(admin["client"], token, "prompts/list").json()["result"]["prompts"]
        assert prompts == []  # a skill needing a switched-off tool hides with it
        agent = api(admin, "GET", f"/tools/agent-view?connector_id={app['connector_id']}", expect=200).json()["data"]
        assert "run_report" not in [tool["name"] for tool in agent["tools"]]

        switch(admin, app["connector_id"], run_report=True)
        assert "run_report" in listed(admin["client"], token)
        assert {event.tool_key for event in audits("tool.switch_off")} == {"run_report", "your_app__projects__list"}
        assert [event.tool_key for event in audits("tool.switch_on")] == ["run_report"]


def test_tool_switch_updates_are_validated(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        path = SWITCHES.format(app["connector_id"])
        assert api(admin, "PUT", path, {"tools": {"not_a_tool": False}}).status_code == 422
        assert api(admin, "PUT", path, {"tools": {"run_report": "off"}}).status_code == 422
        assert api(admin, "PUT", path, {"tools": {}}).status_code == 422
        assert api(admin, "GET", path, expect=200).json()["data"]["off"] == 0


# Chat ---------------------------------------------------------------------------------


class Scripted(providers.Conversation):
    """A model that plays back fixed steps and records what the Hub sent it."""

    def __init__(self, steps: list[providers.Step], record: dict) -> None:
        self.steps, self.record, self.names = list(steps), record, {}

    async def step(self, on_text, *, allow_tools=True):
        self.record.setdefault("allow_tools", []).append(allow_tools)
        step = self.steps.pop(0)
        if step.text:
            await on_text(step.text)
        return step

    def add_results(self, results):
        self.record.setdefault("results", []).append(results)


@pytest.fixture()
def model(monkeypatch):
    """Install a scripted model; returns (set_steps, record)."""

    record: dict = {}
    script: list = []
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")

    def start(settings, config, *, endpoint, system, messages, tools, user_id):
        record.update(system=system, messages=messages, tools=[tool.name for tool in tools], user_id=user_id,
                      model=config.model)
        return Scripted(script, record)

    monkeypatch.setattr(providers, "start", start)
    return script, record


def enable_chat(admin, connector_id, **extra):
    return api(admin, "PATCH", f"/connectors/{connector_id}/chat", {"enabled": True, **extra}, expect=200).json()["data"]


def turn(admin, token, body, user=None, stream=True):
    headers = {"Authorization": f"Bearer {token}"}
    if user:
        headers["X-Hub-Delegation"] = user
    return admin["client"].post("/chat/v1/turn", headers=headers, json={**body, "stream": stream})


def events(response) -> list[tuple[str, dict]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if lines:
            parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def test_chat_settings_are_validated(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        path = f"/connectors/{app['connector_id']}/chat"
        view = api(admin, "GET", path, expect=200).json()["data"]
        assert view["enabled"] is False and view["model"] == "claude-opus-5-5" and view["fallbacks"] is True
        assert api(admin, "PATCH", path, {"model": "gpt-x"}).status_code == 422  # Claude provider takes listed models
        assert api(admin, "PATCH", path, {"instructions": "Escalate to boss@example.com"}).status_code == 422
        assert api(admin, "PATCH", path, {"max_steps": 50}).status_code == 422
        assert api(admin, "PATCH", path, {"unknown": 1}).status_code == 422
        saved = enable_chat(admin, app["connector_id"], model="claude-haiku-5-5", suggestions=["How many projects?"])
        assert saved["enabled"] is True and saved["fallbacks"] is False  # Haiku has no server-side fallback
        gateway = api(admin, "PATCH", path, {"provider": "openai_compatible", "model": "telixcell/chat-1"}, expect=200)
        assert gateway.json()["data"]["model"] == "telixcell/chat-1"


def test_chat_turn_streams_answer_and_tool_calls(admin, monkeypatch, model):
    script, record = model
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        enable_chat(admin, app["connector_id"], instructions="Call projects 'campaigns'.", welcome_message="Hi!")
        token = issue_key(admin)
        script += [providers.Step(text="Let me check. ", calls=[providers.ToolCall("c1", "run_report", {"source": "projects"})],
                                  stop="tool_use"),
                   providers.Step(text="You have 4 campaigns.")]
        history = [{"role": "assistant", "text": "Hi!"}, {"role": "user", "text": "Hello"},
                   {"role": "assistant", "text": "Hello! How can I help?"}]
        got = events(turn(admin, token, {"message": "How many projects?", "history": history, "locale": "id"},
                          delegation()))
        kinds = [kind for kind, _ in got]
        assert kinds[0] == "start" and kinds[-1] == "done"
        tools = [data for kind, data in got if kind == "tool"]
        assert [tool["status"] for tool in tools] == ["running", "done"] and tools[1]["name"] == "run_report"
        assert "".join(data["delta"] for kind, data in got if kind == "text") == "Let me check. You have 4 campaigns."
        sent = json.loads(record["results"][0][0].content)
        assert sent["success"] is True and sent["data"]["totals"]["count"] == 4
        # The leading assistant greeting is dropped so the model sees a user-first conversation.
        assert [item["role"] for item in record["messages"]] == ["user", "assistant", "user"]
        assert "Call projects 'campaigns'." in record["system"] and "Answer in Indonesian" in record["system"]
        assert "run_report" in record["tools"] and record["user_id"] and record["model"] == "claude-opus-5-5"
        trace = got[0][1]["trace_id"]
        turn_audit = audits("chat.turn")[-1]
        assert turn_audit.result == "success" and turn_audit.trace_id == trace
        assert [event.trace_id for event in audits("tool.execute")][-1] == trace  # a turn's calls share its trace


def test_chat_refuses_before_calling_the_model(admin, monkeypatch, model):
    script, record = model
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        token = issue_key(admin)
        off = turn(admin, token, {"message": "Hi"})
        assert off.status_code == 403 and off.json()["error"]["code"] == "CHAT_DISABLED"
        enable_chat(admin, app["connector_id"])
        pii = turn(admin, token, {"message": "Email me at someone@example.com"})
        assert pii.status_code == 422 and pii.json()["error"]["code"] == "PII_DETECTED"
        assert turn(admin, "not-a-key", {"message": "Hi"}).status_code == 401
        assert turn(admin, token, {"message": ""}).status_code == 422
        forged = turn(admin, token, {"message": "Hi"}, user=delegation(app_key="other_app"))
        assert forged.status_code == 403
        assert "messages" not in record  # the model was never called


def test_chat_only_offers_switched_on_tools_and_honours_the_step_limit(admin, monkeypatch, model):
    script, record = model
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        enable_chat(admin, app["connector_id"], max_steps=1)
        switch(admin, app["connector_id"], run_report=False)
        token = issue_key(admin)
        script += [providers.Step(calls=[providers.ToolCall("c1", "run_report", {"source": "projects"})], stop="tool_use"),
                   providers.Step(calls=[providers.ToolCall("c2", "list_data_sources", {})], stop="tool_use")]
        body = turn(admin, token, {"message": "Report please"}, delegation(), stream=False).json()["data"]
        assert "run_report" not in record["tools"]
        assert body["tools"][0]["error"]["code"] == "UNKNOWN_TOOL"  # a switched-off tool cannot be called anyway
        assert record["allow_tools"] == [True, False]
        assert [notice["code"] for notice in body["notices"]] == ["STEP_LIMIT"]


def test_chat_shows_write_requests_as_proposals(admin, monkeypatch, model):
    from tests.integration.test_access import connect_managed, managed_manifest

    script, record = model
    helpers.dns(monkeypatch)
    monkeypatch.setattr(helpers, "MANIFEST", managed_manifest())
    with helpers.source():
        app = connect_managed(admin)
        enable_chat(admin, app["id"], suggestions=["Create a project"])
        writer = issue_key(admin, write=True)
        config = admin["client"].get("/chat/v1/config", headers={"Authorization": f"Bearer {writer}"}).json()["data"]
        assert config["enabled"] is True and config["suggestions"] == ["Create a project"]
        name = "your_app__projects__prepare_create"
        script += [providers.Step(calls=[providers.ToolCall("c1", name, {"name": "Clinic"})], stop="tool_use"),
                   providers.Step(text="Please confirm the request below.")]
        got = events(turn(admin, writer, {"message": "Create project Clinic"}, delegation()))
        proposal = next(data for kind, data in got if kind == "proposal")
        assert proposal["tool"] == name and proposal["operation"] == "create"
        assert proposal["data"][0]["proposal_ref"] == "prop_test1"
        assert [data["tools"][0]["write"] for kind, data in got if kind == "done"] == [True]


def test_chat_config_hides_everything_while_off(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        connect_app(admin)
        token = issue_key(admin)
        config = admin["client"].get("/chat/v1/config", headers={"Authorization": f"Bearer {token}"})
        assert config.status_code == 200 and config.json()["data"]["enabled"] is False
        assert config.json()["data"]["skills"] == []


# Providers ----------------------------------------------------------------------------


class FakeStream:
    def __init__(self, message, texts):
        self.message, self.texts = message, texts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for text in self.texts:
                yield SimpleNamespace(type="text", text=text)
        return gen()

    async def get_final_message(self):
        return self.message


async def test_anthropic_conversation_requests_and_fallback_echo(monkeypatch):
    from app.persistence.models import ChatSetting
    from mcp.types import Tool

    sent: list[dict] = []
    message = SimpleNamespace(stop_reason="tool_use", content=[
        SimpleNamespace(type="thinking", thinking="", signature="s"),
        SimpleNamespace(type="tool_use", id="old", name="run_report", input={}),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="text", text="Checking."),
        SimpleNamespace(type="tool_use", id="t1", name="run_report", input={"source": "projects"}),
    ])

    class FakeClient:
        def __init__(self, **kwargs):
            self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

        def stream(self, **params):
            sent.append(params)
            return FakeStream(message, ["Checking."])

        async def close(self):
            return None

    monkeypatch.setattr(providers.anthropic, "AsyncAnthropic", FakeClient)
    settings = SimpleNamespace(anthropic_api_key="k", chat_timeout_seconds=30, chat_max_tokens=16000)
    config = ChatSetting(model="claude-opus-5-5", effort="medium", provider="anthropic")
    tool = Tool(name="run_report", description="Report", input_schema={"type": "object"})
    conversation = providers.AnthropicConversation(settings, config, "system", [{"role": "user", "content": "Hi"}],
                                                   [tool], "u1")
    streamed: list[str] = []

    async def on_text(text):
        streamed.append(text)

    step = await conversation.step(on_text)
    assert streamed == ["Checking."] and [call.id for call in step.calls] == ["t1"] and step.stop == "tool_use"
    params = sent[0]
    assert params["fallbacks"] == "default" and params["betas"] == [providers.FALLBACK_BETA]
    assert params["output_config"] == {"effort": "medium"} and params["cache_control"] == {"type": "ephemeral"}
    assert params["tools"][0]["eager_input_streaming"] is True and "tool_choice" not in params
    echoed = conversation.messages[-1]["content"]
    assert [block.type for block in echoed] == ["text", "tool_use"]  # declined model's blocks are not sent back
    conversation.add_results([providers.Result("t1", "{}")])
    await conversation.step(on_text, allow_tools=False)
    assert sent[1]["tool_choice"] == {"type": "none"}


async def test_openai_compatible_conversation(monkeypatch):
    from app.persistence.models import ChatSetting
    from mcp.types import Tool

    bodies: list[dict] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions" and request.headers["Authorization"] == "Bearer g"
        if len(bodies) == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
                "content": None, "tool_calls": [{"id": "x1", "type": "function", "function": {
                    "name": "run_report", "arguments": "{\"source\": \"projects\"}"}}]}}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "Done."}}]})

    async def open_client(endpoint, settings):
        return httpx.AsyncClient(base_url=endpoint.base_url, headers=endpoint.headers,
                                 transport=httpx.MockTransport(gateway))

    monkeypatch.setattr(providers.registry, "open_client", open_client)
    settings = SimpleNamespace(chat_timeout_seconds=30, chat_max_tokens=1000)
    config = ChatSetting(model="telixcell/chat-1", provider="openai_compatible")
    endpoint = providers.Endpoint("Gateway", "http://gateway.test/v1", {"Authorization": "Bearer g"}, streaming=False)
    tool = Tool(name="run_report", description="Report", input_schema={"type": "object"})
    conversation = providers.OpenAICompatibleConversation(settings, config, endpoint, "system",
                                                          [{"role": "user", "content": "Hi"}], [tool])
    texts: list[str] = []

    async def on_text(text):
        texts.append(text)

    first = await conversation.step(on_text)
    assert first.calls[0].arguments == {"source": "projects"} and bodies[0]["tool_choice"] == "auto"
    conversation.add_results([providers.Result("x1", "{\"count\": 3}")])
    second = await conversation.step(on_text)
    assert second.text == "Done." and texts == ["Done."]
    assert bodies[1]["messages"][-1] == {"role": "tool", "tool_call_id": "x1", "content": "{\"count\": 3}"}
    await conversation.close()


async def test_anthropic_conversation_through_the_real_sdk(monkeypatch):
    """The SDK serializes the request the Hub builds and parses a streamed tool call back."""

    import httpx2
    from app.persistence.models import ChatSetting
    from mcp.types import Tool

    captured: list[dict] = []
    frames = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "One moment."}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
            "type": "tool_use", "id": "toolu_1", "name": "run_report", "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": "{\"source\": \"projects\"}"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                           "usage": {"output_tokens": 20}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in frames)

    def api_handler(request):
        captured.append({"body": json.loads(request.content), "beta": request.headers.get("anthropic-beta")})
        return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})

    real = providers.anthropic.AsyncAnthropic
    monkeypatch.setattr(providers.anthropic, "AsyncAnthropic", lambda **kwargs: real(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(api_handler)), **kwargs))
    settings = SimpleNamespace(anthropic_api_key="k", chat_timeout_seconds=30, chat_max_tokens=16000)
    config = ChatSetting(model="claude-opus-5-5", effort="high", provider="anthropic")
    tool = Tool(name="run_report", description="Report", input_schema={"type": "object"})
    conversation = providers.AnthropicConversation(settings, config, "system", [{"role": "user", "content": "Hi"}],
                                                   [tool], "u1")
    texts: list[str] = []

    async def on_text(text):
        texts.append(text)

    step = await conversation.step(on_text)
    await conversation.close()
    assert texts == ["One moment."] and step.calls[0].arguments == {"source": "projects"}
    sent = captured[0]
    assert sent["beta"] == providers.FALLBACK_BETA and sent["body"]["fallbacks"] == "default"
    assert sent["body"]["output_config"] == {"effort": "high"} and sent["body"]["stream"] is True
    assert sent["body"]["tools"][0]["eager_input_streaming"] is True and sent["body"]["metadata"] == {"user_id": "u1"}
