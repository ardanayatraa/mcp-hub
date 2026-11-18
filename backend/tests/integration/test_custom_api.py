"""A custom API connection: the admin lists endpoints, the Hub builds read tools from them."""

import httpx
from tests import helpers
from tests.helpers import api, call, issue_key, listed, result

SPEC = {"resources": {"product": {
    "name": "Products", "alias": ["produk", "menu"],
    "fields": {"id": "integer", "title": "string", "price": "number", "description": {"type": "string", "maxLength": 1000}},
    "endpoints": [
        {"name": "cari_produk", "path": "/products/search", "params": {"q": "string", "limit": "integer"},
         "required": ["q"], "result_path": "products"},
        {"name": "detail_produk", "path": "/products/{id}"},
        {"name": "daftar_produk", "path": "/products", "result_path": "products"},
    ]}}}

PRODUCTS = [{"id": 1, "title": "Nasi", "price": 2000, "description": "Nasi putih", "images": ["a.png"], "brand": "x"},
            {"id": 2, "title": "Teh", "price": 500, "description": "Teh manis", "images": [], "brand": "y"}]
SEEN: list[httpx.Request] = []


def dummyjson(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    path = request.url.path
    if path == "/products/search":
        query = request.url.params.get("q", "").lower()
        found = [row for row in PRODUCTS if query in row["title"].lower()]
        return httpx.Response(200, json={"products": found, "total": len(found), "skip": 0, "limit": 30})
    if path == "/products":
        return httpx.Response(200, json={"products": PRODUCTS, "total": 2, "skip": 0, "limit": 30})
    if path.startswith("/products/"):
        row = next((row for row in PRODUCTS if str(row["id"]) == path.rsplit("/", 1)[1]), None)
        return httpx.Response(200, json=row) if row else httpx.Response(404, json={"message": "not found"})
    return httpx.Response(404)


def connect(admin, spec=SPEC):
    created = api(admin, "POST", "/connectors", {
        "name": "Dummy", "app_key": "dummy", "environment": "dev", "base_url": "http://dummyjson.test",
        "connector_type": "custom_api", "auth_type": "none"}, expect=201).json()["data"]
    assert created["connector_type"] == "custom_api" and created["auth_type"] == "none"
    saved = api(admin, "PUT", f"/connectors/{created['id']}/custom-api", spec, expect=200).json()["data"]
    assert set(saved["custom_spec"]["resources"]) == {"product"}
    return created["id"]


def test_endpoint_list_becomes_read_tools_with_no_credentials_sent(admin, monkeypatch):
    helpers.dns(monkeypatch)
    SEEN.clear()
    with helpers.source(dummyjson):
        connector_id = connect(admin)
        tested = api(admin, "POST", f"/connectors/{connector_id}/test", expect=200).json()["data"]
        assert tested["status"] == "ok"
        assert SEEN[-1].url.path == "/products" and "authorization" not in SEEN[-1].headers
        api(admin, "POST", f"/connectors/{connector_id}/activate", expect=200)

        token = issue_key(admin, app_key="dummy")
        names = listed(admin["client"], token)
        assert {"dummy__product__cari_produk", "dummy__product__detail_produk", "dummy__product__daftar_produk"} <= set(names)

        found = result(call(admin["client"], token, "dummy__product__cari_produk", {"q": "nasi"}))
        assert [row["title"] for row in found["data"]] == ["Nasi"]
        assert all(set(row) <= {"id", "title", "price", "description"} for row in found["data"])  # brand/images dropped

        one = result(call(admin["client"], token, "dummy__product__detail_produk", {"id": "2"}))
        assert one["data"][0]["price"] == 500
        assert "authorization" not in SEEN[-1].headers


def test_unknown_input_and_missing_required_are_rejected(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source(dummyjson):
        connector_id = connect(admin)
        api(admin, "POST", f"/connectors/{connector_id}/activate", expect=422)  # no passing test yet
        api(admin, "POST", f"/connectors/{connector_id}/test", expect=200)
        api(admin, "POST", f"/connectors/{connector_id}/activate", expect=200)
        token = issue_key(admin, app_key="dummy")
        assert call(admin["client"], token, "dummy__product__cari_produk", {}).json()["result"]["isError"] is True
        assert call(admin["client"], token, "dummy__product__cari_produk",
                    {"q": "x", "host": "evil.test"}).json()["result"]["isError"] is True


def test_only_get_and_valid_shapes_are_accepted(admin, monkeypatch):
    helpers.dns(monkeypatch)
    created = api(admin, "POST", "/connectors", {
        "name": "Dummy", "app_key": "dummy", "environment": "dev", "base_url": "http://dummyjson.test",
        "connector_type": "custom_api", "auth_type": "none"}, expect=201).json()["data"]
    url = f"/connectors/{created['id']}/custom-api"
    post = {"resources": {"product": {"fields": {"id": "integer"},
                                      "endpoints": [{"name": "tambah", "method": "POST", "path": "/products/add"}]}}}
    assert "only GET" in api(admin, "PUT", url, post, expect=422).json()["error"]["message"]
    for bad in ({}, {"resources": {}}, {"resources": {"Bad Key": {}}},
                {"resources": {"p": {"fields": {"id": "object"}, "endpoints": [{"name": "a", "path": "/a"}]}}},
                {"resources": {"p": {"fields": {"id": "integer"}, "endpoints": [{"name": "a", "path": "no-slash"}]}}},
                {"resources": {"p": {"fields": {"id": "integer"}, "endpoints": [{"name": "a", "path": "/a/../b"}]}}}):
        api(admin, "PUT", url, bad, expect=422)


def test_none_auth_is_only_for_custom_api(admin):
    api(admin, "POST", "/connectors", {"name": "X", "app_key": "other", "environment": "dev",
                                       "base_url": "http://projects.test", "auth_type": "none"}, expect=422)
    api(admin, "POST", "/connectors", {"name": "X", "app_key": "other", "environment": "dev",
                                       "base_url": "http://projects.test", "auth_type": "bearer",
                                       "secret": "short"}, expect=422)


def test_connection_settings_save_and_type_cannot_change(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source(dummyjson):
        connector_id = connect(admin)
        same = {"name": "Dummy 2", "base_url": "http://dummyjson.test", "timeout_ms": 4000, "connector_type": "custom_api"}
        assert api(admin, "PATCH", f"/connectors/{connector_id}", same, expect=200).json()["data"]["name"] == "Dummy 2"
        api(admin, "PATCH", f"/connectors/{connector_id}", {"connector_type": "source_managed"}, expect=409)
