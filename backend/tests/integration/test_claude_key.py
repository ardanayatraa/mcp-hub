"""The Claude API key saved under AI providers: stored encrypted, never returned, wins over the environment."""

from app.chat import providers, registry
from app.config import get_settings
from app.persistence.models import ModelProvider
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import api, connect_app, delegation, issue_key
from tests.integration.test_switches_and_chat import Scripted, enable_chat, events, turn

SAVED = "sk-ant-saved-in-the-hub-4321"
ENV = "sk-ant-from-the-environment-0000"
KEY = "/model-providers/anthropic/key"


def claude(admin) -> dict:
    return api(admin, "GET", "/model-providers", expect=200).json()["data"]["builtin"][0]


def stored_key() -> str:
    db = open_session()
    try:
        return registry.claude_settings(db, get_settings()).anthropic_api_key
    finally:
        db.close()


def test_saved_claude_key_is_encrypted_never_returned_and_wins(admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    before = claude(admin)
    assert before["key"] == "anthropic" and before["ready"] is False and before["key_source"] is None

    saved = api(admin, "PUT", KEY, {"api_key": SAVED}, expect=200)
    view = saved.json()["data"]
    assert view["ready"] is True and view["key_source"] == "hub" and view["api_key_hint"] == "4321"
    listing = api(admin, "GET", "/model-providers", expect=200)
    assert SAVED not in saved.text and SAVED not in listing.text
    assert all(row["key"] != "anthropic" for row in listing.json()["data"]["providers"])
    db = open_session()
    try:
        row = db.scalar(select(ModelProvider).where(ModelProvider.key == "anthropic"))
        assert SAVED not in row.api_key_ciphertext  # encrypted at rest
        assert registry.endpoint_for(db, "anthropic", get_settings()) is None  # usable without the environment
        row_id = row.id
    finally:
        db.close()
    assert stored_key() == SAVED

    # The saved key is not a generic provider: it changes only through its own endpoints.
    assert api(admin, "PATCH", f"/model-providers/{row_id}", {"name": "x"}).status_code == 404
    assert api(admin, "DELETE", f"/model-providers/{row_id}").status_code == 404
    for body in ({}, {"api_key": ""}, {"api_key": "two words"}, {"api_key": "k" * 1001}, {"api_key": SAVED, "x": 1}):
        assert api(admin, "PUT", KEY, body).status_code == 422, body

    # A saved key wins over ANTHROPIC_API_KEY; removing it falls back to the environment.
    monkeypatch.setattr(get_settings(), "anthropic_api_key", ENV)
    assert stored_key() == SAVED and claude(admin)["key_source"] == "hub"
    cleared = api(admin, "DELETE", KEY, expect=200).json()["data"]
    assert cleared["key_source"] == "environment" and cleared["ready"] is True and stored_key() == ENV
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    assert claude(admin)["ready"] is False


def test_only_super_admins_change_the_claude_key(admin):
    client = admin["client"]
    api(admin, "POST", "/users", {"email": "scoped@localhost", "password": "ChangeMe-Now-12", "role": "app_admin"}, expect=201)
    client.cookies.clear()
    login = client.post("/api/admin/v1/auth/login", json={"email": "scoped@localhost", "password": "ChangeMe-Now-12"}).json()["data"]
    headers = {"X-CSRF-Token": login["csrf_token"]}
    assert client.put(f"/api/admin/v1{KEY}", headers=headers, json={"api_key": SAVED}).status_code == 403
    assert client.delete(f"/api/admin/v1{KEY}", headers=headers).status_code == 403


def test_chat_uses_the_saved_claude_key(admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    seen: dict = {}

    def start(settings, config, *, endpoint, system, messages, tools, user_id):
        seen.update(key=settings.anthropic_api_key, endpoint=endpoint)
        return Scripted([providers.Step(text="Hi there.")], {})

    monkeypatch.setattr(providers, "start", start)
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        enable_chat(admin, app["connector_id"])
        token = issue_key(admin)
        refused = turn(admin, token, {"message": "Hello"}, delegation(), stream=False)
        assert refused.status_code == 503 and refused.json()["error"]["code"] == "CHAT_NOT_CONFIGURED"
        api(admin, "PUT", KEY, {"api_key": SAVED}, expect=200)
        got = events(turn(admin, token, {"message": "Hello"}, delegation()))
        assert got[-1][0] == "done" and seen == {"key": SAVED, "endpoint": None}


def test_rotating_the_encryption_key_keeps_every_secret_readable(admin, monkeypatch):
    import pytest
    from app.rotate_keys import rotate
    from cryptography.fernet import Fernet

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    api(admin, "PUT", KEY, {"api_key": SAVED}, expect=200)
    old, new = get_settings().secret_encryption_key, Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "secret_encryption_key", new)
    monkeypatch.setattr(get_settings(), "secret_encryption_key_previous", old)
    assert stored_key() == SAVED  # the old key still reads during the rotation
    with open_session() as db:
        assert rotate(db) >= 1
        db.commit()
    monkeypatch.setattr(get_settings(), "secret_encryption_key_previous", "")
    assert stored_key() == SAVED  # now readable with the new key alone
    monkeypatch.setattr(get_settings(), "secret_encryption_key", old)
    with pytest.raises(Exception, match="could not be decrypted"):
        stored_key()
