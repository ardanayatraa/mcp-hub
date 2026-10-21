"""Invitation activation and email login codes must not grant access before verification."""

from datetime import timedelta

from app.config import get_settings
from app.errors import HubError
from app.ids import utcnow
from app.persistence.models import AdminUser, MfaChallenge
from app.persistence.session import open_session
from app.security.crypto import sha256_hex
from sqlalchemy import select
from tests.helpers import api


def mailer(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_username", "sender@example.test")
    monkeypatch.setattr(settings, "smtp_password", "test-smtp-password")
    monkeypatch.setattr(settings, "smtp_from", "sender@example.test")
    invitations, codes = [], []
    monkeypatch.setattr("app.api.v1.access.send_invitation", lambda email, token: invitations.append((email, token)))
    monkeypatch.setattr("app.api.v1.auth.send_login_code", lambda email, code: codes.append((email, code)))
    return invitations, codes


def test_invite_activation_email_otp_and_root_boundary(admin, monkeypatch):
    invitations, codes = mailer(monkeypatch)
    created = api(admin, "POST", "/users", {"email": "peer@localhost", "role": "hub_admin"}, expect=201).json()["data"]
    assert created["pending_activation"] is True and created["auth_method"] == "email_otp"
    assert "password" not in created and "activation_token_hash" not in created
    first_token = invitations[0][1]
    client = admin["client"]
    client.cookies.clear()
    login_body = {"email": "peer@localhost", "password": "My-New-Password-123"}
    assert client.post("/api/admin/v1/auth/login", json=login_body).status_code == 401
    assert client.post("/api/admin/v1/auth/activate", json={"token": first_token,
                       "password": "weakpassword"}).status_code == 422

    # A root resend invalidates the earlier link.
    with open_session() as db:
        user = db.get(AdminUser, created["id"])
        user.activation_expires_at = utcnow() + timedelta(hours=23, minutes=58)
        db.commit()
    client.post("/api/admin/v1/auth/login", json={"email": "admin@localhost", "password": "ChangeMe-Now-12"})
    csrf = client.get("/api/admin/v1/auth/me").json()["data"]["csrf_token"]
    assert client.post(f"/api/admin/v1/users/{created['id']}/resend-invite",
                       headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.post(f"/api/admin/v1/users/{created['id']}/resend-invite",
                       headers={"X-CSRF-Token": csrf}).status_code == 429
    second_token = invitations[-1][1]
    assert second_token != first_token
    assert client.post("/api/admin/v1/auth/activate", json={"token": first_token,
                       "password": login_body["password"]}).status_code == 400
    assert client.post("/api/admin/v1/auth/activate", json={"token": second_token,
                       "password": login_body["password"]}).status_code == 200
    assert client.post("/api/admin/v1/auth/activate", json={"token": second_token,
                       "password": login_body["password"]}).status_code == 400

    client.cookies.clear()
    monkeypatch.setattr(get_settings(), "mfa_required", True)
    login = client.post("/api/admin/v1/auth/login", json=login_body)
    assert login.status_code == 200
    challenge = login.json()["data"]
    assert challenge["mfa_channel"] == "email" and "user" not in challenge
    assert len(codes) == 1 and codes[0][0] == "peer@localhost"
    with open_session() as db:
        stored = db.scalar(select(MfaChallenge).where(MfaChallenge.user_id == created["id"]))
        assert stored.code_hash != sha256_hex(codes[0][1])
        assert codes[0][1] not in str(stored.__dict__)
    wrong = client.post("/api/admin/v1/auth/mfa", json={"mfa_token": challenge["mfa_token"], "code": "000000" if codes[0][1] != "000000" else "999999"})
    assert wrong.status_code == 401
    verified = client.post("/api/admin/v1/auth/mfa", json={"mfa_token": challenge["mfa_token"], "code": codes[0][1]})
    assert verified.status_code == 200
    assert verified.json()["data"]["user"]["is_root"] is False
    assert client.post("/api/admin/v1/auth/mfa", json={"mfa_token": challenge["mfa_token"], "code": codes[0][1]}).status_code == 401
    assert client.get("/api/admin/v1/users").status_code == 403


def test_email_code_has_five_guesses_and_login_has_send_cooldown(admin, monkeypatch):
    invitations, codes = mailer(monkeypatch)
    created = api(admin, "POST", "/users", {"email": "codes@localhost", "role": "app_admin"}, expect=201).json()["data"]
    client = admin["client"]
    assert client.post("/api/admin/v1/auth/activate", json={"token": invitations[0][1],
                       "password": "My-New-Password-123"}).status_code == 200
    client.cookies.clear()
    body = {"email": "codes@localhost", "password": "My-New-Password-123"}
    first = client.post("/api/admin/v1/auth/login", json=body).json()["data"]
    assert client.post("/api/admin/v1/auth/login", json=body).status_code == 429
    wrong = "000000" if codes[0][1] != "000000" else "999999"
    for _ in range(5):
        assert client.post("/api/admin/v1/auth/mfa", json={"mfa_token": first["mfa_token"], "code": wrong}).status_code == 401
    assert client.post("/api/admin/v1/auth/mfa", json={"mfa_token": first["mfa_token"],
                       "code": codes[0][1]}).status_code == 401
    with open_session() as db:
        challenge = db.scalar(select(MfaChallenge).where(MfaChallenge.user_id == created["id"]))
        assert challenge.attempts == 5


def test_invite_requires_configured_mailer(admin):
    assert api(admin, "POST", "/users", {"email": "no-mail@localhost", "role": "hub_admin"}).status_code == 503
    with open_session() as db:
        assert db.scalar(select(AdminUser).where(AdminUser.email == "no-mail@localhost")) is None


def test_invite_rejects_multiple_recipient_addresses(admin, monkeypatch):
    mailer(monkeypatch)
    result = api(admin, "POST", "/users", {"email": "peer@localhost,attacker@localhost",
                                            "role": "hub_admin"})
    assert result.status_code == 422


def test_root_still_requires_authenticator_in_production(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "mfa_required", False)
    response = client.post("/api/admin/v1/auth/login", json={"email": "admin@localhost",
                                                       "password": "ChangeMe-Now-12"})
    assert response.status_code == 200
    assert response.json()["data"]["enrollment_required"] is True
    assert "user" not in response.json()["data"]


def test_invite_delivery_failure_rolls_back_and_expired_link_fails(admin, monkeypatch):
    invitations, _ = mailer(monkeypatch)
    def fail(_email, _token):
        raise HubError("EMAIL_UNAVAILABLE", "Email could not be delivered", 503)

    monkeypatch.setattr("app.api.v1.access.send_invitation", fail)
    assert api(admin, "POST", "/users", {"email": "failed@localhost", "role": "hub_admin"}).status_code == 503
    with open_session() as db:
        assert db.scalar(select(AdminUser).where(AdminUser.email == "failed@localhost")) is None
    monkeypatch.setattr("app.api.v1.access.send_invitation", lambda email, token: invitations.append((email, token)))
    created = api(admin, "POST", "/users", {"email": "expired@localhost", "role": "hub_admin"}, expect=201).json()["data"]
    with open_session() as db:
        user = db.get(AdminUser, created["id"])
        user.activation_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert admin["client"].post("/api/admin/v1/auth/activate", json={"token": invitations[-1][1],
                                "password": "My-New-Password-123"}).status_code == 400
