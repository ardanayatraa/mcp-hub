"""The embedded chat: users sign in to the app inside the widget and read only their own data."""

import json

import httpx
from app.chat import providers
from app.persistence.models import EmbedLink
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import api
from tests.integration.test_switches_and_chat import (  # noqa: F401 - fixture
    enable_chat,
    events,
    model,
)

USERS = {"andi@shop.test": ("pass-andi-123", "tok_andi_0123456789", "Andi Pratama"),
         "budi@shop.test": ("pass-budi-123", "tok_budi_0123456789", "Budi Santoso")}
ORDERS = {"tok_andi_0123456789": [{"id": 1, "code": "INV-A1", "total": 2000}, {"id": 2, "code": "INV-A2", "total": 500}],
          "tok_budi_0123456789": [{"id": 9, "code": "INV-B9", "total": 7000}]}
SEEN: list[httpx.Request] = []

SPEC = {
    "user_auth": {"login_path": "/api/login", "fields": ["email", "password"], "token_path": "data.token",
                  "me_path": "/api/me", "name_path": "name"},
    "resources": {"order": {"name": "Orders", "alias": ["pesanan"],
                            "fields": {"id": "integer", "code": "string", "total": "number"},
                            "endpoints": [{"name": "my_orders", "path": "/api/orders", "result_path": "data"}]}},
}


def shop(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    if request.url.path == "/api/login" and request.method == "POST":
        body = json.loads(request.content)
        user = USERS.get(body.get("email"))
        if user is None or user[0] != body.get("password"):
            return httpx.Response(422, json={"message": "These credentials do not match our records."})
        return httpx.Response(200, json={"data": {"token": user[1]}})
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    if token not in ORDERS:
        return httpx.Response(401, json={"message": "Unauthenticated."})
    if request.url.path == "/api/me":
        return httpx.Response(200, json={"name": next(u[2] for u in USERS.values() if u[1] == token)})
    if request.url.path == "/api/orders":
        return httpx.Response(200, json={"data": ORDERS[token]})
    return httpx.Response(404)


def connect(admin, origins=("https://partner.test",)):
    created = api(admin, "POST", "/connectors", {
        "name": "Shop", "app_key": "shop", "environment": "dev", "base_url": "http://shop.test",
        "connector_type": "custom_api", "auth_type": "none"}, expect=201).json()["data"]
    cid = created["id"]
    api(admin, "PUT", f"/connectors/{cid}/custom-api", SPEC, expect=200)
    assert api(admin, "POST", f"/connectors/{cid}/test", expect=200).json()["data"]["status"] == "ok"
    api(admin, "POST", f"/connectors/{cid}/activate", expect=200)
    enable_chat(admin, cid, welcome_message="Halo!")
    widget = api(admin, "PUT", f"/connectors/{cid}/embed", {"enabled": True, "allowed_origins": list(origins),
                                                             "title": "Shop help"}, expect=200).json()["data"]
    return cid, widget


def sign_in(client, widget, email, password):
    return client.post(f"/api/embed/v1/w/{widget['public_id']}/sign-in", json={"fields": {"email": email, "password": password}})


def chat(client, widget, session, message="Pesanan saya?"):
    return client.post(f"/api/embed/v1/w/{widget['public_id']}/turn", json={"message": message},
                       headers={"Authorization": f"Bearer {session}"})


def test_each_user_reads_only_their_own_orders(admin, monkeypatch, model):  # noqa: F811 - the imported fixture
    script, record = model
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source(shop):
        _cid, widget = connect(admin)
        assert widget["snippet"].endswith(f'data-widget="{widget["public_id"]}" async></script>')
        assert sign_in(client, widget, "andi@shop.test", "wrong").status_code == 401
        andi = sign_in(client, widget, "andi@shop.test", "pass-andi-123").json()["data"]
        budi = sign_in(client, widget, "budi@shop.test", "pass-budi-123").json()["data"]
        assert andi["name"] == "Andi Pratama" and andi["session"].startswith("es_")

        config = client.get(f"/api/embed/v1/w/{widget['public_id']}/config",
                            headers={"Authorization": f"Bearer {andi['session']}"}).json()["data"]
        assert config["user"] == {"name": "Andi Pratama", "preview": False} and config["welcome_message"] == "Halo!"

        script += [providers.Step(calls=[providers.ToolCall("c1", "shop__order__my_orders", {})], stop="tool_use"),
                   providers.Step(text="Dua pesanan.")]
        stream = events(chat(client, widget, andi["session"]))
        result = next(r for r in record["results"][-1])
        assert "INV-A1" in result.content and "INV-B9" not in result.content
        assert ("done", stream[-1][1]) == stream[-1] and any(e == "text" for e, _ in stream)
        assert SEEN[-1].headers["authorization"] == "Bearer tok_andi_0123456789"

        script += [providers.Step(calls=[providers.ToolCall("c1", "shop__order__my_orders", {})], stop="tool_use"),
                   providers.Step(text="Satu pesanan.")]
        events(chat(client, widget, budi["session"]))
        result = next(r for r in record["results"][-1])
        assert "INV-B9" in result.content and "INV-A1" not in result.content

    with open_session() as db:
        stored = db.scalars(select(EmbedLink)).all()
        assert len(stored) == 2
        assert all("tok_" not in row.token_ciphertext and "Andi" not in (row.label_ciphertext or "") for row in stored)


def test_sessions_are_required_and_end(admin, monkeypatch, model):  # noqa: F811 - the imported fixture
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source(shop):
        cid, widget = connect(admin)
        assert chat(client, widget, "es_made_up").status_code == 401
        assert client.post(f"/api/embed/v1/w/{widget['public_id']}/turn", json={"message": "hi"}).status_code == 401
        andi = sign_in(client, widget, "andi@shop.test", "pass-andi-123").json()["data"]
        client.post(f"/api/embed/v1/w/{widget['public_id']}/sign-out", headers={"Authorization": f"Bearer {andi['session']}"})
        assert chat(client, widget, andi["session"]).status_code == 401

        budi = sign_in(client, widget, "budi@shop.test", "pass-budi-123").json()["data"]
        users = api(admin, "GET", f"/connectors/{cid}/embed/users", expect=200).json()["data"]
        assert [row["name"] for row in users] == ["Budi Santoso"]
        api(admin, "DELETE", f"/connectors/{cid}/embed/users/{users[0]['id']}", expect=200)
        assert chat(client, widget, budi["session"]).status_code == 401

        # A rotated snippet id stops the old one.
        old = widget["public_id"]
        api(admin, "POST", f"/connectors/{cid}/embed/rotate", expect=200)
        assert client.get(f"/api/embed/v1/w/{old}/config").status_code == 404


def test_page_is_framed_only_by_allowed_sites(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source(shop):
        _cid, widget = connect(admin, origins=["https://partner.test", "https://www.partner.test"])
        page = client.get(f"/api/embed/v1/w/{widget['public_id']}")
        assert page.status_code == 200 and "X-Frame-Options" not in page.headers
        csp = page.headers["Content-Security-Policy"]
        assert "frame-ancestors 'self' https://partner.test https://www.partner.test" in csp
        assert "script-src 'nonce-" in csp and "unsafe-inline" not in csp
        config = client.get(f"/api/embed/v1/w/{widget['public_id']}/config", headers={"Origin": "https://partner.test"})
        assert config.headers["access-control-allow-origin"] == "https://partner.test"
        other = client.get(f"/api/embed/v1/w/{widget['public_id']}/config", headers={"Origin": "https://evil.test"})
        assert "access-control-allow-origin" not in other.headers
        assert client.get("/api/embed/v1/embed.js").headers["content-type"].startswith("application/javascript")
        # Everything else stays unframeable.
        assert client.get("/api/admin/v1/connectors").headers["X-Frame-Options"] == "DENY"


def test_admin_preview_is_read_only_audited_and_short(admin, monkeypatch, model):  # noqa: F811 - the imported fixture
    script, _record = model
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source(shop):
        cid, widget = connect(admin)
        sign_in(client, widget, "andi@shop.test", "pass-andi-123")
        link = api(admin, "GET", f"/connectors/{cid}/embed/users", expect=200).json()["data"][0]
        token = api(admin, "POST", f"/connectors/{cid}/embed/preview", {"link_id": link["id"]}, expect=200).json()["data"]["token"]
        config = client.get(f"/api/embed/v1/w/{widget['public_id']}/config",
                            headers={"Authorization": f"Bearer {token}"}).json()["data"]
        assert config["user"] == {"name": "Andi Pratama", "preview": True}
        script += [providers.Step(text="Halo Andi.")]
        events(chat(client, widget, token))
        logs = api(admin, "GET", "/executions", expect=200).text
        assert "embed.preview_as_user" in logs or "chat.turn" in logs
        # A preview token for another widget is refused.
        assert chat(client, {"public_id": widget["public_id"]}, token + "x").status_code == 401


def test_embedding_needs_user_sign_in_and_valid_settings(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source(shop):
        created = api(admin, "POST", "/connectors", {
            "name": "Public", "app_key": "public_api", "environment": "dev", "base_url": "http://shop.test",
            "connector_type": "custom_api", "auth_type": "none"}, expect=201).json()["data"]
        cid = created["id"]
        api(admin, "PUT", f"/connectors/{cid}/custom-api", {"resources": SPEC["resources"]}, expect=200)
        assert "user_auth" in api(admin, "PUT", f"/connectors/{cid}/embed", {"enabled": True}, expect=422).text
        for bad in ({"allowed_origins": ["partner.test"]}, {"allowed_origins": ["https://*.partner.test"]},
                    {"allowed_origins": ["https://partner.test/path"]}, {"accent": "blue"}, {"position": "top"},
                    {"session_days": 0}, {"unknown": True}):
            api(admin, "PUT", f"/connectors/{cid}/embed", bad, expect=422)
        bad_auth = {**SPEC, "user_auth": {"login_path": "api/login"}}
        api(admin, "PUT", f"/connectors/{cid}/custom-api", bad_auth, expect=422)


def sign_in_token(client, widget, token):
    return client.post(f"/api/embed/v1/w/{widget['public_id']}/sign-in-token", json={"token": token})


def test_host_page_hands_over_its_users_token(admin, monkeypatch, model):  # noqa: F811 - the imported fixture
    script, record = model
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source(shop):
        _cid, widget = connect(admin)
        # Only a token the app itself accepts opens a session.
        assert sign_in_token(client, widget, "tok_made_up_0123456789").status_code == 401
        assert sign_in_token(client, widget, "short").status_code == 422
        opened = sign_in_token(client, widget, "tok_budi_0123456789").json()["data"]
        assert opened["name"] == "Budi Santoso" and opened["session"].startswith("es_")

        script += [providers.Step(calls=[providers.ToolCall("c1", "shop__order__my_orders", {})], stop="tool_use"),
                   providers.Step(text="Satu pesanan.")]
        events(chat(client, widget, opened["session"]))
        result = next(r for r in record["results"][-1])
        assert "INV-B9" in result.content and "INV-A1" not in result.content
        assert SEEN[-1].headers["authorization"] == "Bearer tok_budi_0123456789"

    with open_session() as db:
        link = db.scalars(select(EmbedLink)).one()
        assert "tok_" not in link.token_ciphertext


def test_host_sign_in_needs_me_path(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    spec = {**SPEC, "user_auth": {k: v for k, v in SPEC["user_auth"].items() if k not in ("me_path", "name_path")}}
    with helpers.source(shop):
        created = api(admin, "POST", "/connectors", {
            "name": "Shop", "app_key": "shop", "environment": "dev", "base_url": "http://shop.test",
            "connector_type": "custom_api", "auth_type": "none"}, expect=201).json()["data"]
        cid = created["id"]
        api(admin, "PUT", f"/connectors/{cid}/custom-api", spec, expect=200)
        api(admin, "POST", f"/connectors/{cid}/test", expect=200)
        api(admin, "POST", f"/connectors/{cid}/activate", expect=200)
        enable_chat(admin, cid)
        widget = api(admin, "PUT", f"/connectors/{cid}/embed", {"enabled": True}, expect=200).json()["data"]
        assert sign_in_token(client, widget, "tok_andi_0123456789").status_code == 422
