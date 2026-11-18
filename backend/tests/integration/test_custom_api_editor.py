"""Custom API editor support: API-key header auth, static endpoint headers and the test request."""

import httpx
from tests import helpers
from tests.helpers import api, call, issue_key, result

SEEN: list[httpx.Request] = []
SPEC = {"resources": {"item": {
    "name": "Items", "fields": {"id": "integer", "title": "string"},
    "endpoints": [{"name": "list", "path": "/items", "result_path": "data",
                   "headers": {"Accept-Language": "id", "X-Region": "bali"}}]}}}


def keyed(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    if request.headers.get("x-api-key") != "key-1234567890":
        return httpx.Response(401, json={"message": "bad key"})
    if request.url.path == "/items":
        return httpx.Response(200, json={"data": [{"id": 1, "title": "Nasi"}], "meta": {"page": 1}})
    if request.url.path == "/products/search":
        return httpx.Response(200, json={"products": [
            {"id": 1, "title": "A", "price": 9.5, "stock": None, "email": "someone@example.com", "tags": ["x"]},
            {"id": 2, "title": "B", "price": 10, "stock": 3, "email": "other@example.com", "tags": []}],
            "total": 2})
    return httpx.Response(404)


def connect(admin, auth_type="header", **extra):
    body = {"name": "Keyed", "app_key": "keyed", "environment": "dev", "base_url": "http://keyed.test",
            "connector_type": "custom_api", "auth_type": auth_type, **extra}
    return api(admin, "POST", "/connectors", body, expect=201).json()["data"]["id"]


def test_api_key_header_and_static_headers_reach_the_api(admin, monkeypatch):
    helpers.dns(monkeypatch)
    SEEN.clear()
    with helpers.source(keyed):
        cid = connect(admin, auth_header="X-API-Key", secret="key-1234567890")
        saved = api(admin, "PUT", f"/connectors/{cid}/custom-api", SPEC, expect=200).json()["data"]
        assert saved["custom_spec"]["auth_header"] == "X-API-Key"  # kept without being sent again
        assert saved["custom_spec"]["resources"]["item"]["endpoints"][0]["headers"]["X-Region"] == "bali"
        assert api(admin, "POST", f"/connectors/{cid}/test", expect=200).json()["data"]["status"] == "ok"
        api(admin, "POST", f"/connectors/{cid}/activate", expect=200)
        token = issue_key(admin, app_key="keyed")
        rows = result(call(admin["client"], token, "keyed__item__list", {}))
        assert rows["data"][0]["title"] == "Nasi"
        sent = SEEN[-1].headers
        assert sent["x-api-key"] == "key-1234567890" and sent["accept-language"] == "id" and sent["x-region"] == "bali"


def test_header_auth_and_headers_are_validated(admin, monkeypatch):
    helpers.dns(monkeypatch)
    api(admin, "POST", "/connectors", {"name": "K", "app_key": "k1", "environment": "dev", "base_url": "http://keyed.test",
                                        "auth_type": "header", "auth_header": "X-Key", "secret": "key-1234567890"}, expect=422)
    for bad in ({"auth_header": "Authorization"}, {"auth_header": "bad name"}, {"auth_header": ""}):
        api(admin, "POST", "/connectors", {"name": "K", "app_key": "k2", "environment": "dev",
                                            "base_url": "http://keyed.test", "connector_type": "custom_api",
                                            "auth_type": "header", "secret": "key-1234567890", **bad}, expect=422)
    cid = connect(admin, auth_type="none")
    for headers in ({"Authorization": "Bearer x"}, {"Cookie": "a=b"}, {"X-Hub-Assertion": "x"}, {"Bad Name": "x"},
                    {"X-Ok": ""}, {f"X-H{i}": "v" for i in range(11)}):
        spec = {"resources": {"item": {**SPEC["resources"]["item"],
                                       "endpoints": [{"name": "list", "path": "/items", "headers": headers}]}}}
        api(admin, "PUT", f"/connectors/{cid}/custom-api", spec, expect=422)


def test_test_request_describes_the_answer_without_leaking_personal_data(admin, monkeypatch):
    helpers.dns(monkeypatch)
    SEEN.clear()
    with helpers.source(keyed):
        cid = connect(admin, auth_header="X-API-Key", secret="key-1234567890")
        found = api(admin, "POST", f"/connectors/{cid}/custom-api/probe",
                    {"path": "/products/search", "params": {"q": "a"}}, expect=200).json()["data"]
        assert found["status"] == 200 and found["result_path"] == "products" and found["count"] == 2
        assert found["fields"] == {"id": "integer", "title": "string", "price": "number", "stock": "integer?",
                                   "email": "string"}
        assert "email" in found["sensitive"]
        assert "someone@example.com" not in str(found["sample"]) and "••••" in str(found["sample"])
        assert SEEN[-1].url.params["q"] == "a" and SEEN[-1].headers["x-api-key"] == "key-1234567890"
        # An error from the API is reported, not raised.
        assert api(admin, "POST", f"/connectors/{cid}/custom-api/probe", {"path": "/nope"},
                   expect=200).json()["data"]["status"] == 404
        for bad in ({"path": "no-slash"}, {"path": "/a/../b"}, {"path": "/x/{id}"}, {"path": "/x", "params": []},
                    {"path": "/x", "headers": {"Authorization": "x"}}):
            api(admin, "POST", f"/connectors/{cid}/custom-api/probe", bad, expect=422)
