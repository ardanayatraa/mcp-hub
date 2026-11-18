"""Settings changed in the admin UI take effect at once, reset to the environment, and stay within safe bounds."""

import json
import socket

import pytest
from app.config import get_settings
from app.connectors import ssrf_guard
from app.errors import HubError
from app.persistence.models import HubSetting
from app.persistence.session import open_session
from app.services import runtime_settings
from sqlalchemy import select
from tests import helpers
from tests.helpers import api, call, connect_app, issue_key, result

SMTP = {"host": "smtp.example.com", "port": 587, "username": "sender@example.com", "password": "mail-secret-123",
        "from": "hub@example.com", "tls_mode": "starttls"}


@pytest.fixture(autouse=True)
def environment_values_afterwards():
    yield
    runtime_settings.forget(get_settings())


def sign_in_as(client, email: str) -> dict:
    client.cookies.clear()
    login = client.post("/api/admin/v1/auth/login", json={"email": email, "password": "ChangeMe-Now-12"}).json()["data"]
    return {"X-CSRF-Token": login["csrf_token"]}


def test_a_limit_takes_effect_at_once_and_resets_to_the_environment(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source():
        connect_app(admin)
        token = issue_key(admin)
        start = api(admin, "GET", "/hub-settings", expect=200).json()["data"]
        assert start["limits"]["tool_rate_limit"] == {"value": 60, "environment": 60, "min": 1, "max": 10000,
                                                      "source": "environment", "updated_at": None}
        saved = api(admin, "PATCH", "/hub-settings", {"tool_rate_limit": 1}, expect=200).json()["data"]
        assert saved["limits"]["tool_rate_limit"]["value"] == 1 and saved["limits"]["tool_rate_limit"]["source"] == "hub"
        assert api(admin, "GET", "/system", expect=200).json()["data"]["limits"]["tool_rate_limit"] == 1
        result(call(client, token, "list_data_sources"))
        assert "RATE_LIMITED" in helpers.error_text(call(client, token, "list_data_sources"))

        reset = api(admin, "PATCH", "/hub-settings", {"tool_rate_limit": None}, expect=200).json()["data"]
        assert reset["limits"]["tool_rate_limit"] == {"value": 60, "environment": 60, "min": 1, "max": 10000,
                                                      "source": "environment", "updated_at": None}
    rows = api(admin, "GET", "/executions?kind=admin", expect=200).json()["data"]
    assert [row["tool_key"] for row in rows if row["action"] == "settings.update"] == ["tool_rate_limit", "tool_rate_limit"]


def test_values_outside_the_safe_bounds_are_refused(admin):
    for body in ({"max_records": 51}, {"report_max_records": 10}, {"tool_rate_limit": True}, {"audit_retention_days": "30"},
                 {"mfa_required": "yes"}, {"cookie_secure": False}, {"egress_allow_private": True}, {}, []):
        assert api(admin, "PATCH", "/hub-settings", body).status_code == 422, body
    for hosts in (["localhost"], ["*.example.com"], ["app.localhost"], ["bad host"], "app.example.com"):
        assert api(admin, "PATCH", "/hub-settings", {"egress_allowed_hosts": hosts}).status_code == 422, hosts
    assert get_settings().max_records == 50


def test_localhost_is_approved_only_where_loopback_calls_are_allowed(admin, monkeypatch):
    assert api(admin, "PATCH", "/hub-settings", {"egress_allowed_hosts": ["localhost"]}).status_code == 422
    monkeypatch.setattr(get_settings(), "egress_allow_loopback", True)
    api(admin, "PATCH", "/hub-settings", {"egress_allowed_hosts": ["localhost", "app.example.com"]}, expect=200)
    assert get_settings().egress_allowed_hosts == "localhost,app.example.com"


def test_only_root_changes_settings_and_hub_admins_read_them(admin):
    client = admin["client"]
    for email, role in (("peer@localhost", "hub_admin"), ("scoped@localhost", "app_admin")):
        api(admin, "POST", "/users", {"email": email, "password": "ChangeMe-Now-12", "role": role}, expect=201)
    peer = sign_in_as(client, "peer@localhost")
    assert client.get("/api/admin/v1/hub-settings", headers=peer).status_code == 200
    assert client.patch("/api/admin/v1/hub-settings", headers=peer, json={"max_records": 10}).status_code == 403
    assert client.post("/api/admin/v1/hub-settings/test-email", headers=peer).status_code == 403
    scoped = sign_in_as(client, "scoped@localhost")
    assert client.get("/api/admin/v1/hub-settings", headers=scoped).status_code == 403
    assert get_settings().max_records == 50


def test_approved_hosts_and_sign_in_policy(admin):
    settings = get_settings()
    api(admin, "PATCH", "/hub-settings", {"egress_allowed_hosts": ["App.Example.com", "app.example.com"],
                                          "mfa_required": True}, expect=200)
    assert settings.egress_allowed_hosts == "app.example.com" and settings.mfa_required is True
    with pytest.raises(HubError) as blocked:
        ssrf_guard.validate_destination("https://other.example.org/api", settings)
    assert blocked.value.code == "SSRF_BLOCKED"
    view = api(admin, "GET", "/hub-settings", expect=200).json()["data"]
    assert view["egress_allowed_hosts"]["value"] == ["app.example.com"] and view["mfa_required"]["source"] == "hub"
    assert view["environment_only"]["egress_allow_private"] is False
    api(admin, "PATCH", "/hub-settings", {"egress_allowed_hosts": None, "mfa_required": None}, expect=200)
    assert settings.egress_allowed_hosts == "" and settings.mfa_required is False


def test_email_settings_are_stored_encrypted_and_never_shown(admin, monkeypatch):
    helpers.dns(monkeypatch)
    settings = get_settings()
    view = api(admin, "PATCH", "/hub-settings", {"smtp": SMTP}, expect=200).json()["data"]["smtp"]
    assert view["ready"] is True and view["password_set"] is True and view["host"] == "smtp.example.com"
    assert "mail-secret-123" not in json.dumps(view) and settings.smtp_password == "mail-secret-123"
    with open_session() as db:
        stored = db.scalar(select(HubSetting).where(HubSetting.key == "smtp")).value
    assert "mail-secret-123" not in json.dumps(stored)
    # Saving again without a password keeps the one already stored.
    api(admin, "PATCH", "/hub-settings", {"smtp": {**SMTP, "password": "", "port": 465, "tls_mode": "ssl"}}, expect=200)
    assert settings.smtp_password == "mail-secret-123" and settings.smtp_port == 465

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout, context=None):
            sent.append((host, port))
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def login(self, user, password): sent.append((user, password == "mail-secret-123"))
        def send_message(self, message): sent.append(message["To"])

    monkeypatch.setattr("app.security.mailer.smtplib.SMTP_SSL", FakeSMTP)
    assert api(admin, "POST", "/hub-settings/test-email", expect=200).json()["data"]["sent_to"] == "admin@localhost"
    assert sent == [("smtp.example.com", 465), ("sender@example.com", True), "admin@localhost"]

    for body, code in (({**SMTP, "port": 2222}, 422), ({**SMTP, "from": "not-an-email"}, 422), ({**SMTP, "host": "localhost"}, 422)):
        assert api(admin, "PATCH", "/hub-settings", {"smtp": body}).status_code == code
    monkeypatch.setattr(ssrf_guard, "_resolve_host",
                        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))])
    assert api(admin, "PATCH", "/hub-settings", {"smtp": SMTP}).json()["error"]["code"] == "SSRF_BLOCKED"
    api(admin, "PATCH", "/hub-settings", {"smtp": None}, expect=200)
    assert settings.smtp_host == "" and settings.smtp_password == "" and not settings.smtp_configured


def test_another_process_picks_up_a_saved_value(admin):
    with open_session() as db:  # as if another worker saved it
        db.add(HubSetting(key="report_timeout_seconds", value={"value": 45}))
        db.commit()
    runtime_settings._last_refresh = 0.0
    api(admin, "GET", "/system", expect=200)
    assert get_settings().report_timeout_seconds == 45


def test_saved_settings_travel_in_the_backup(admin):
    api(admin, "PATCH", "/hub-settings", {"max_records": 25}, expect=200)
    sealed, document = helpers.export_backup(admin)
    assert document["tables"]["hub_settings"][0]["value"] == {"value": 25}
    api(admin, "PATCH", "/hub-settings", {"max_records": None}, expect=200)
    assert get_settings().max_records == 50
    api(admin, "POST", "/operations/import", sealed, expect=200)
    assert get_settings().max_records == 25
