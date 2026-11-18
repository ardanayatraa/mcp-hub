"""Administrators change their own password; root hands out one-use reset links; both sign out other sessions."""

from datetime import timedelta

from app.ids import new_id, utcnow
from app.persistence.models import AdminSession, AdminUser, MfaChallenge
from app.persistence.session import open_session
from app.security.crypto import sha256_hex
from app.services import password_reset
from sqlalchemy import select
from tests.helpers import api

ROOT_PASSWORD = "ChangeMe-Now-12"


def sign_in(client, email: str, password: str):
    client.cookies.clear()
    return client.post("/api/admin/v1/auth/login", json={"email": email, "password": password})


def other_session(email: str) -> str:
    """A session on another device, which a password change must end."""

    with open_session() as db:
        user = db.scalar(select(AdminUser).where(AdminUser.email == email))
        row = AdminSession(id=new_id(), user_id=user.id, token_hash=sha256_hex(new_id()), csrf_token="x",
                           expires_at=utcnow() + timedelta(hours=1))
        db.add(row)
        db.commit()
        return row.id


def session_exists(session_id: str) -> bool:
    with open_session() as db:
        return db.get(AdminSession, session_id) is not None


def test_changing_your_password_needs_the_current_one_and_signs_out_elsewhere(admin):
    client = admin["client"]
    elsewhere = other_session("admin@localhost")
    for body, code in (({"current_password": "wrong-Password-1", "new_password": "Brand-New-Pass-1"}, 401),
                       ({"current_password": ROOT_PASSWORD, "new_password": "short"}, 422),
                       ({"current_password": ROOT_PASSWORD, "new_password": ROOT_PASSWORD}, 422)):
        assert api(admin, "POST", "/auth/password", body).status_code == code
    assert session_exists(elsewhere)
    api(admin, "POST", "/auth/password", {"current_password": ROOT_PASSWORD, "new_password": "Brand-New-Pass-1"}, expect=200)
    assert not session_exists(elsewhere)
    assert client.get("/api/admin/v1/auth/me").status_code == 200  # this session stays signed in
    assert sign_in(client, "admin@localhost", ROOT_PASSWORD).status_code == 401
    assert sign_in(client, "admin@localhost", "Brand-New-Pass-1").status_code == 200
    rows = [row["action"] for row in client.get("/api/admin/v1/executions?kind=admin",
                                                 headers={"X-CSRF-Token": client.post(
                                                     "/api/admin/v1/auth/login",
                                                     json={"email": "admin@localhost", "password": "Brand-New-Pass-1"}).json()["data"]["csrf_token"]}).json()["data"]]
    assert "auth.password_change" in rows


def test_root_reset_link_works_once_and_signs_the_admin_out(admin):
    client = admin["client"]
    peer = api(admin, "POST", "/users", {"email": "peer@localhost", "password": "Peer-Password-12", "role": "hub_admin"},
               expect=201).json()["data"]
    elsewhere = other_session("peer@localhost")
    link = api(admin, "POST", f"/users/{peer['id']}/password-reset", expect=200).json()["data"]
    assert "/reset-password#" in link["reset_url"] and link["expires_at"]
    token = link["reset_url"].split("#", 1)[1]
    # A newer link replaces an older one.
    newer = api(admin, "POST", f"/users/{peer['id']}/password-reset", expect=200).json()["data"]["reset_url"].split("#", 1)[1]
    assert client.post("/api/admin/v1/auth/password-reset", json={"token": token, "password": "Peer-Reset-Pass-1"}).status_code == 400
    assert client.post("/api/admin/v1/auth/password-reset", json={"token": newer, "password": "weak"}).status_code == 422
    assert client.post("/api/admin/v1/auth/password-reset", json={"token": newer, "password": "Peer-Reset-Pass-1"}).status_code == 200
    assert not session_exists(elsewhere)
    assert client.post("/api/admin/v1/auth/password-reset", json={"token": newer, "password": "Peer-Again-Pass-1"}).status_code == 400
    assert sign_in(client, "peer@localhost", "Peer-Password-12").status_code == 401
    peer_login = sign_in(client, "peer@localhost", "Peer-Reset-Pass-1")
    assert peer_login.status_code == 200
    # Only root hands out links, never for root itself.
    headers = {"X-CSRF-Token": peer_login.json()["data"]["csrf_token"]}
    root_id = client.get("/api/admin/v1/auth/me").json()["data"]["id"]
    assert client.post(f"/api/admin/v1/users/{root_id}/password-reset", headers=headers).status_code == 403
    login = sign_in(client, "admin@localhost", ROOT_PASSWORD).json()["data"]
    assert client.post(f"/api/admin/v1/users/{login['user']['id']}/password-reset",
                       headers={"X-CSRF-Token": login["csrf_token"]}).status_code == 409


def test_an_expired_link_is_refused_and_the_shell_can_issue_one_for_root(admin):
    client = admin["client"]
    with open_session() as db:
        root = db.scalar(select(AdminUser).where(AdminUser.email == "admin@localhost"))
        url, _expires = password_reset.issue(db, root, actor_ref="system:cli")
        db.commit()
    token = url.split("#", 1)[1]
    with open_session() as db:
        challenge = db.scalar(select(MfaChallenge).where(MfaChallenge.purpose == password_reset.PURPOSE))
        challenge.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.post("/api/admin/v1/auth/password-reset", json={"token": token, "password": "Root-Reset-Pass-1"}).status_code == 400
    with open_session() as db:
        root = db.scalar(select(AdminUser).where(AdminUser.email == "admin@localhost"))
        url, _expires = password_reset.issue(db, root, actor_ref="system:cli")
        db.commit()
    assert client.post("/api/admin/v1/auth/password-reset",
                       json={"token": url.split("#", 1)[1], "password": "Root-Reset-Pass-1"}).status_code == 200
    assert sign_in(client, "admin@localhost", "Root-Reset-Pass-1").status_code == 200
