"""A manual invitation requires control of the real email before password setup."""

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
    activation_codes = []
    monkeypatch.setattr("app.api.v1.auth.send_activation_code",
                        lambda email, code: activation_codes.append((email, code)))
    return activation_codes


def create_invite(admin, role="hub_admin"):
    created = api(admin, "POST", "/users", {"role": role}, expect=201).json()["data"]
    assert created["activation_url"].startswith("http://127.0.0.1:8000/activate#")
    assert created["email"] is None
    return created, created["activation_url"].split("#", 1)[1]


def get_code(client, token, email):
    response = client.post("/api/admin/v1/auth/activation-email", json={"token": token, "email": email})
    assert response.status_code == 200, response.text
    return response.json()["data"]["challenge_token"]


def verify_code(client, token, challenge_token, code):
    return client.post("/api/admin/v1/auth/activation-code", json={
        "token": token, "challenge_token": challenge_token, "code": code})


def test_link_real_email_code_password_and_login(admin, monkeypatch):
    activation_codes = mailer(monkeypatch)
    created, token = create_invite(admin)
    assert created["pending_activation"] is True and created["auth_method"] == "email_otp"
    assert "password" not in created and "activation_token_hash" not in created
    assert activation_codes == []
    client = admin["client"]
    client.cookies.clear()
    password = "My-New-Password-123"
    with open_session() as db:
        assert db.get(AdminUser, created["id"]).email is None
    assert client.post("/api/admin/v1/auth/activate", json={"token": token, "password": password}).status_code == 422
    challenge = get_code(client, token, "Real@Example.com")
    assert activation_codes[-1][0] == "real@example.com"
    wrong = "000000" if activation_codes[-1][1] != "000000" else "999999"
    assert verify_code(client, token, challenge, wrong).status_code == 401
    verified = verify_code(client, token, challenge, activation_codes[-1][1])
    assert verified.status_code == 200
    proof = verified.json()["data"]["proof_token"]
    assert verify_code(client, token, challenge, activation_codes[-1][1]).status_code == 401
    assert client.post("/api/admin/v1/auth/activate", json={"token": token, "proof_token": proof,
                       "password": "weakpassword"}).status_code == 422
    assert client.post("/api/admin/v1/auth/activate", json={"token": token, "proof_token": proof,
                       "password": password}).status_code == 200
    assert client.post("/api/admin/v1/auth/activate", json={"token": token, "proof_token": proof,
                       "password": password}).status_code == 400
    with open_session() as db:
        user = db.get(AdminUser, created["id"])
        assert user.email == "real@example.com" and user.activation_token_hash is None
        assert user.auth_method == "password"
        challenge_row = db.scalar(select(MfaChallenge).where(MfaChallenge.user_id == created["id"],
                                  MfaChallenge.purpose == "activation_code"))
        assert challenge_row.code_hash != sha256_hex(activation_codes[-1][1])
    monkeypatch.setattr(get_settings(), "mfa_required", True)
    monkeypatch.setattr(get_settings(), "smtp_password", "")
    login = client.post("/api/admin/v1/auth/login", json={"email": "real@example.com", "password": password})
    assert login.status_code == 200
    assert login.json()["data"]["user"]["is_root"] is False
    assert "mfa_token" not in login.json()["data"]
    assert len(activation_codes) == 1
    team = client.get("/api/admin/v1/users")
    assert team.status_code == 200
    assert [row["id"] for row in team.json()["data"]] == [created["id"]]
    assert "admin@localhost" not in team.text


def test_multiple_pending_links_need_no_email(admin, monkeypatch):
    mailer(monkeypatch)
    first, first_token = create_invite(admin)
    second, second_token = create_invite(admin, "auditor")
    assert first["id"] != second["id"] and first_token != second_token
    with open_session() as db:
        assert db.get(AdminUser, first["id"]).email is None
        assert db.get(AdminUser, second["id"]).email is None
    rows = api(admin, "GET", "/users", expect=200).json()["data"]
    assert [row["email"] for row in rows if row["id"] in {first["id"], second["id"]}] == [None, None]


def test_five_guesses_and_send_cooldown(admin, monkeypatch):
    activation_codes = mailer(monkeypatch)
    _, token = create_invite(admin)
    client = admin["client"]
    challenge = get_code(client, token, "first@example.com")
    assert client.post("/api/admin/v1/auth/activation-email", json={"token": token,
                       "email": "second@example.com"}).status_code == 429
    wrong = "000000" if activation_codes[-1][1] != "000000" else "999999"
    for _ in range(5):
        assert verify_code(client, token, challenge, wrong).status_code == 401
    assert verify_code(client, token, challenge, activation_codes[-1][1]).status_code == 401
    with open_session() as db:
        row = db.scalar(select(MfaChallenge).where(MfaChallenge.purpose == "activation_code"))
        assert row.attempts == 5


def test_new_link_invalidates_old_link(admin, monkeypatch):
    activation_codes = mailer(monkeypatch)
    created, old_token = create_invite(admin)
    challenge = get_code(admin["client"], old_token, "first@example.com")
    verified = verify_code(admin["client"], old_token, challenge, activation_codes[-1][1])
    assert verified.status_code == 200
    old_proof = verified.json()["data"]["proof_token"]
    with open_session() as db:
        user = db.get(AdminUser, created["id"])
        user.activation_expires_at = utcnow() + timedelta(hours=23, minutes=58)
        db.commit()
    response = api(admin, "POST", f"/users/{created['id']}/resend-invite", expect=200).json()["data"]
    new_token = response["activation_url"].split("#", 1)[1]
    assert new_token != old_token
    assert api(admin, "POST", f"/users/{created['id']}/resend-invite").status_code == 429
    assert admin["client"].post("/api/admin/v1/auth/activation-email", json={
        "token": old_token, "email": "real@example.com"}).status_code == 400
    assert admin["client"].post("/api/admin/v1/auth/activate", json={"token": new_token,
        "proof_token": old_proof, "password": "My-New-Password-123"}).status_code == 401
    get_code(admin["client"], new_token, "real@example.com")


def test_requires_mailer_and_rejects_multiple_addresses(admin, monkeypatch):
    assert api(admin, "POST", "/users", {"role": "hub_admin"}).status_code == 503
    with open_session() as db:
        assert db.scalar(select(AdminUser).where(AdminUser.role == "hub_admin")) is None
    mailer(monkeypatch)
    assert api(admin, "POST", "/users", {"email": "dummy@example.com",
               "role": "hub_admin"}).status_code == 422
    assert api(admin, "POST", "/users", {"email": "a@localhost,b@localhost",
               "role": "hub_admin"}).status_code == 422
    _, token = create_invite(admin)
    assert admin["client"].post("/api/admin/v1/auth/activation-email", json={
        "token": token, "email": "a@example.com,b@example.com"}).status_code == 422
    assert admin["client"].post("/api/admin/v1/auth/activation-email", json={
        "token": token, "email": "admin@localhost"}).status_code == 409


def test_delivery_failure_and_expired_link_do_not_activate(admin, monkeypatch):
    mailer(monkeypatch)
    created, token = create_invite(admin)

    def fail(_email, _code):
        raise HubError("EMAIL_UNAVAILABLE", "Email could not be delivered", 503)

    monkeypatch.setattr("app.api.v1.auth.send_activation_code", fail)
    assert admin["client"].post("/api/admin/v1/auth/activation-email", json={
        "token": token, "email": "real@example.com"}).status_code == 503
    with open_session() as db:
        assert db.scalar(select(MfaChallenge).where(MfaChallenge.user_id == created["id"])) is None
        user = db.get(AdminUser, created["id"])
        user.activation_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert admin["client"].post("/api/admin/v1/auth/activation-email", json={
        "token": token, "email": "real@example.com"}).status_code == 400


def test_root_still_requires_authenticator_in_production(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "mfa_required", False)
    response = client.post("/api/admin/v1/auth/login", json={"email": "admin@localhost",
                                                       "password": "ChangeMe-Now-12"})
    assert response.status_code == 200
    assert response.json()["data"]["enrollment_required"] is True
    assert "user" not in response.json()["data"]
