"""The monitoring board: clients with their state, the checks that stopped requests, and where traffic went."""

import json

import httpx
from app.services import monitoring
from tests import helpers
from tests.helpers import api, call, connect_app, delegation, issue_key, result

TOOL = "your_app__projects__list"


def board(admin, window: str = "5m") -> dict:
    return api(admin, "GET", f"/monitoring?window={window}", expect=200).json()["data"]


def test_a_stop_is_read_from_the_error_code():
    assert monitoring.stopped_at("success", None) is None
    assert monitoring.stopped_at("denied", "UNAUTHENTICATED") == "key"
    assert monitoring.stopped_at("error", "PII_DETECTED") == "privacy"
    assert monitoring.stopped_at("denied", "PERMISSION_DENIED") == "permissions"
    # Named like a model failure, but it is the app's allowlist that refused.
    assert monitoring.stopped_at("error", "MODEL_NOT_ALLOWED") == "permissions"
    assert monitoring.stopped_at("error", "RATE_LIMITED") == "limits"
    assert monitoring.stopped_at("error", "UPSTREAM_TIMEOUT") == "app"
    assert monitoring.stopped_at("error", "MODEL_BUSY") == "model"
    assert monitoring.stopped_at("error", "INTERNAL") == "hub"
    assert monitoring.destination("tool.execute", "list_data_sources") == "hub"
    assert monitoring.destination("tool.execute", "your_app.projects.list") == "app"
    assert monitoring.destination("chat.turn", None) == "model"


def test_board_follows_traffic_through_the_gates(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source():
        app = connect_app(admin)
        api(admin, "POST", "/tools/generate", {"connector_id": app["connector_id"]}, expect=201)
        token = issue_key(admin)

        quiet = board(admin)
        assert quiet["totals"] == {"requests": 0, "passed": 0, "blocked": 0, "failed": 0, "per_minute": 0.0}
        assert [(row["name"], row["state"], row["reason"]) for row in quiet["clients"]] == [("gateway", "on", None)]
        assert [(row["name"], row["state"]) for row in quiet["apps"]] == [("Your App", "on")]
        assert [gate["key"] for gate in quiet["gates"]] == ["key", "privacy", "permissions", "limits"]
        assert quiet["events"] == []

        for _ in range(2):
            result(call(client, token, TOOL, {}, delegation()))
        call(client, token, TOOL, {})  # no signed-in user: refused by permissions
        call(client, token, TOOL, {"status": helpers.CANARY}, delegation())  # personal data in the input
        result(call(client, token, "list_data_sources"))  # answered by the Hub itself
        # A wrong key is turned away before anything is logged, so it never reaches the board.
        assert helpers.mcp(client, "hub_not_a_key", "tools/list").status_code == 401
        data = board(admin)

    assert data["totals"] == {"requests": 5, "passed": 3, "blocked": 2, "failed": 0, "per_minute": 1.0}
    gates = {gate["key"]: gate for gate in data["gates"]}
    assert {key: gate["stopped"] for key, gate in gates.items()} == {"key": 0, "privacy": 1, "permissions": 1, "limits": 0}
    assert gates["privacy"]["codes"] == [{"code": "PII_DETECTED", "count": 1}]
    assert gates["permissions"]["codes"] == [{"code": "PERMISSION_DENIED", "count": 1}]

    (key,) = data["clients"]
    assert (key["kind"], key["state"], key["reason"], key["app"]) == ("key", "live", None, app["connector_id"])
    assert (key["requests"], key["blocked"], key["failed"]) == (5, 2, 0) and key["last_seen_at"]
    (source_app,) = data["apps"]
    assert (source_app["id"], source_app["state"], source_app["requests"], source_app["failed"]) == (app["connector_id"], "live", 2, 0)
    assert source_app["tools"] >= 1 and source_app["sources"] == 1 and source_app["health"]["status"] == "ok"
    assert data["hub"] == {"answered": 1}

    events = data["events"]
    assert len(events) == 5 and all(event["client"] == key["id"] and event["app"] == app["connector_id"] for event in events)
    newest = events[0]
    assert (newest["kind"], newest["label"], newest["destination"], newest["stopped_at"]) == ("tool", "List data sources", "hub", None)
    assert {(event["label"], event["destination"]) for event in events[1:]} == {("List projects", "app")}
    assert sorted(event["stopped_at"] or "passed" for event in events[1:]) == ["passed", "passed", "permissions", "privacy"]
    # Metadata only: no key, no personal data from the refused request.
    assert token not in json.dumps(data) and helpers.CANARY not in json.dumps(data)


def test_a_failing_app_and_switched_off_parts_show_their_state(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source():
        app = connect_app(admin)
        api(admin, "POST", "/tools/generate", {"connector_id": app["connector_id"]}, expect=201)
        token = issue_key(admin)
        spare = api(admin, "POST", "/service-identities", {"name": "spare", "app_key": "your_app", "environment": "dev"},
                    expect=201).json()["data"]

    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/projects"):
            return httpx.Response(500, json={"success": False, "error": {"code": "INTERNAL", "message": "down"}})
        return helpers.handler(request)

    with helpers.source(broken):
        call(client, token, TOOL, {}, delegation())
        data = board(admin)
    assert (data["totals"]["failed"], data["totals"]["blocked"]) == (1, 0)
    (source_app,) = data["apps"]
    assert (source_app["state"], source_app["reason"], source_app["requests"], source_app["failed"]) == ("warn", "failing", 1, 1)
    assert data["events"][0]["stopped_at"] == "app" and data["events"][0]["error_code"].startswith("UPSTREAM_")
    assert {row["name"]: row["state"] for row in data["clients"]} == {"gateway": "live", "spare": "on"}

    # A revoked key that never sent anything leaves the board; pausing the app switches the rest off.
    api(admin, "POST", f"/service-identities/{spare['id']}/revoke", expect=200)
    api(admin, "POST", f"/connectors/{app['connector_id']}/pause", expect=200)
    data = board(admin)
    assert [(row["name"], row["state"], row["reason"]) for row in data["clients"]] == [("gateway", "off", "app_off")]
    assert [(row["state"], row["reason"]) for row in data["apps"]] == [("off", "paused")]


def test_board_is_scoped_and_checks_its_window(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source():
        connect_app(admin)
        token = issue_key(admin)
        result(call(client, token, "list_data_sources"))
    assert api(admin, "GET", "/monitoring?window=2d").status_code == 422
    assert board(admin, "24h")["totals"]["requests"] == 1

    api(admin, "POST", "/users", {"email": "scoped@localhost", "password": "ChangeMe-Now-12", "role": "app_admin"}, expect=201)
    client.cookies.clear()
    client.post("/api/admin/v1/auth/login", json={"email": "scoped@localhost", "password": "ChangeMe-Now-12"})
    scoped = client.get("/api/admin/v1/monitoring").json()["data"]
    assert scoped["clients"] == [] and scoped["apps"] == [] and scoped["events"] == []
    assert scoped["totals"]["requests"] == 0
    client.cookies.clear()
    assert client.get("/api/admin/v1/monitoring").status_code == 401
