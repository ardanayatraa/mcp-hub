"""Embedded chat tool choice, ending a refused session, and fitting a custom API's values to the field types."""

import httpx
from app.chat import providers
from app.persistence.models import EmbedLink
from app.persistence.session import open_session
from app.tools.runtime import fit_rows
from sqlalchemy import select
from tests import helpers
from tests.helpers import api
from tests.integration.test_embed import SPEC, chat, connect, shop, sign_in_token
from tests.integration.test_switches_and_chat import (  # noqa: F401 - fixture
    enable_chat,
    events,
    model,
)

TWO_ENDPOINTS = {**SPEC, "resources": {**SPEC["resources"], "catalog": {
    "name": "Catalogue", "fields": {"id": "integer", "code": "string"},
    "endpoints": [{"name": "search", "path": "/api/orders", "result_path": "data"}]}}}


def test_widget_can_narrow_the_tools_its_chat_offers(admin, monkeypatch, model):  # noqa: F811 - fixture
    script, record = model
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source(shop):
        cid, widget = connect(admin)
        api(admin, "PUT", f"/connectors/{cid}/custom-api", TWO_ENDPOINTS, expect=200)
        saved = api(admin, "PUT", f"/connectors/{cid}/embed", {"allowed_tools": ["shop__order__my_orders"]},
                    expect=200).json()["data"]
        assert saved["allowed_tools"] == ["shop__order__my_orders"]
        session = sign_in_token(client, widget, "tok_andi_0123456789").json()["data"]["session"]

        script += [providers.Step(text="Halo.")]
        events(chat(client, widget, session))
        assert "shop__order__my_orders" in record["tools"]
        assert "shop__catalog__search" not in record["tools"] and "run_report" not in record["tools"]

        # A tool the widget does not allow is refused even if the model asks for it.
        # Each conversation replays the scripted steps from the start, so give this one its own.
        script[:] = [providers.Step(calls=[providers.ToolCall("c1", "shop__catalog__search", {})], stop="tool_use"),
                     providers.Step(text="Tidak bisa.")]
        stream = events(chat(client, widget, session))
        failed = [data for name, data in stream if name == "tool" and data.get("status") == "error"]
        assert failed and failed[0]["error"]["code"] in {"UNKNOWN_TOOL", "PERMISSION_DENIED"}

        # null brings every tool back; bad names are refused.
        assert api(admin, "PUT", f"/connectors/{cid}/embed", {"allowed_tools": None}, expect=200).json()["data"]["allowed_tools"] is None
        for bad in ("all", ["Bad Name"], [1], ["x"] * 301):
            api(admin, "PUT", f"/connectors/{cid}/embed", {"allowed_tools": bad}, expect=422)


def test_a_token_the_app_refuses_ends_the_chat_session(admin, monkeypatch, model):  # noqa: F811 - fixture
    script, _record = model
    helpers.dns(monkeypatch)
    client = admin["client"]
    spec = {**SPEC, "user_auth": {}}
    with helpers.source(shop):
        cid, widget = connect(admin)
        api(admin, "PUT", f"/connectors/{cid}/custom-api", spec, expect=200)
        session = sign_in_token(client, widget, "tok_gone_0123456789").json()["data"]["session"]
        script += [providers.Step(calls=[providers.ToolCall("c1", "shop__order__my_orders", {})], stop="tool_use"),
                   providers.Step(text="Gagal.")]
        events(chat(client, widget, session))
        with open_session() as db:
            assert db.scalars(select(EmbedLink)).one().revoked_at is not None
        assert chat(client, widget, session).status_code == 401  # the page has to hand over a new token


def test_values_are_fitted_to_the_reviewed_types():
    schema = {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {
        "price": {"type": "integer"}, "rate": {"type": "number"}, "active": {"type": "boolean"},
        "title": {"type": "string", "maxLength": 10}, "tags": {"type": "string", "maxLength": 200},
        "note": {"type": ["string", "null"], "maxLength": 50}, "stock": {"type": "integer"}}}}
    rows = fit_rows([{"price": "2000", "rate": "4.5", "active": "1", "title": "Nasi goreng spesial pedas",
                      "tags": ["pedas", "nasi"], "note": None, "stock": None, "extra": {"x": 1}},
                     {"price": "abc", "rate": True, "active": "maybe", "title": 12345, "tags": {"a": 1},
                      "note": "ok", "stock": 3.0}], schema)
    assert rows[0] == {"price": 2000, "rate": 4.5, "active": True, "title": "Nasi gore…", "tags": '["pedas","nasi"]',
                       "note": None, "extra": {"x": 1}}  # stock: null is not allowed, so it is left out
    assert rows[1] == {"title": "12345", "tags": '{"a":1}', "note": "ok", "stock": 3}


def test_a_numeric_string_from_the_api_no_longer_fails_the_answer(admin, monkeypatch, model):  # noqa: F811
    script, record = model
    helpers.dns(monkeypatch)
    client = admin["client"]

    def strings(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/orders" and request.headers.get("authorization") == "Bearer tok_andi_0123456789":
            return httpx.Response(200, json={"data": [{"id": "1", "code": "INV-A1", "total": "2000.00"}]})
        return shop(request)

    with helpers.source(strings):
        cid, widget = connect(admin)
        api(admin, "PUT", f"/connectors/{cid}/custom-api", {**SPEC, "resources": {"order": {
            **SPEC["resources"]["order"], "fields": {"id": "integer", "code": "string", "total": "number"}}}}, expect=200)
        session = sign_in_token(client, widget, "tok_andi_0123456789").json()["data"]["session"]
        script += [providers.Step(calls=[providers.ToolCall("c1", "shop__order__my_orders", {})], stop="tool_use"),
                   providers.Step(text="Satu.")]
        events(chat(client, widget, session))
        result = next(r for r in record["results"][-1])
        assert not result.is_error and '"total": 2000.0' in result.content and '"id": 1' in result.content
