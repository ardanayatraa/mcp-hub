"""The console assistant: read-only repository tools and the streamed answer (with a scripted model)."""

import pytest
from app.chat import assistant, providers
from app.config import get_settings
from app.errors import HubError
from tests.helpers import api
from tests.integration.test_switches_and_chat import Scripted, audits, events


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "README.md").write_text("# Hub\nConnect apps to AI.\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FLOW.md").write_text("\n".join(f"line {n} gateway" for n in range(1, 451)), encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_ENCRYPTION_KEY=gateway-secret\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET_ENCRYPTION_KEY=replace-with-fernet-key\n", encoding="utf-8")
    (tmp_path / ".verification").mkdir()
    (tmp_path / ".verification" / "hub.db").write_text("gateway", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("gateway", encoding="utf-8")
    return tmp_path


def test_repository_tools_stay_inside_and_never_show_secrets(repo):
    listed = assistant.list_files(repo, {}).splitlines()
    assert listed == ["docs/", ".env.example", "README.md"]
    found = assistant.search_repo(repo, {"query": "GATEWAY"})
    assert "docs/FLOW.md:1: line 1 gateway" in found and ".env:" not in found and "node_modules" not in found
    assert "more matches" in found  # capped at 40
    first = assistant.read_file(repo, {"path": "docs/FLOW.md"})
    assert first.startswith("docs/FLOW.md (450 lines)") and "400: line 400" in first and "start=401" in first
    assert "450: line 450" in assistant.read_file(repo, {"path": "docs/FLOW.md", "start": 401})
    for path in (".env", "../README.md", ".verification/hub.db", "node_modules/x.js", "/etc/passwd", "docs"):
        with pytest.raises(HubError, match="No such"):
            assistant.read_file(repo, {"path": path})
    with pytest.raises(HubError):
        assistant.list_files(repo, {"path": ".."})


@pytest.fixture()
def model(monkeypatch):
    record: dict = {}
    script: list = []
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")

    def start(settings, config, *, endpoint, system, messages, tools, user_id):
        record.update(system=system, tools=[tool.name for tool in tools], model=config.model)
        return Scripted(script, record)

    monkeypatch.setattr(providers, "start", start)
    return script, record


def test_assistant_answers_from_the_repository(admin, model):
    script, record = model
    options = api(admin, "GET", "/assistant", expect=200).json()["data"]
    assert options["available"] is True and options["default"] == {"provider": "anthropic", "model": "claude-opus-5-5"}
    script += [providers.Step(calls=[providers.ToolCall("c1", "read_file", {"path": "README.md"})], stop="tool_use"),
               providers.Step(text="The Hub connects apps to AI clients (README.md:1).")]
    got = events(api(admin, "POST", "/assistant",
                     {"message": "How does the Hub work?", "provider": "anthropic", "model": "claude-haiku-5-5"}))
    done = [data for kind, data in got if kind == "tool" and data["status"] == "done"]
    assert done[0]["name"] == "read_file" and done[0]["detail"] == "README.md"
    assert "".join(data["delta"] for kind, data in got if kind == "text").startswith("The Hub connects apps")
    assert record["model"] == "claude-haiku-5-5" and record["tools"] == ["list_files", "search_repo", "read_file"]
    assert "README.md" in record["system"] and "docs/" in record["system"] and ".verification" not in record["system"]
    sent = record["results"][0][0]
    assert sent.content.startswith("README.md (") and not sent.is_error
    assert audits("assistant.turn")[-1].result == "success"
    assert api(admin, "POST", "/assistant", {"message": "Hi"}).status_code == 422  # a model must be chosen
