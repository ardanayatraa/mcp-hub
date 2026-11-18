"""Apps' servers learn the Hub's release from a response header; public probes and wrong keys do not."""

from app import __version__
from tests import helpers
from tests.helpers import api, connect_app, issue_key, mcp


def test_version_is_told_to_callers_with_a_key_and_nowhere_else(admin, monkeypatch):
    helpers.dns(monkeypatch)
    client = admin["client"]
    with helpers.source():
        connect_app(admin)
        token = issue_key(admin)
        listed = mcp(client, token, "tools/list")
    assert listed.status_code == 200 and listed.headers["X-Hub-Version"] == __version__ == "1.1.0"
    hello = mcp(client, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "test", "version": "1"}})
    assert hello.json()["result"]["serverInfo"]["version"] == __version__
    assert "X-Hub-Version" not in mcp(client, "hub_wrong_key", "tools/list").headers
    for path in ("/health", "/ready", "/api/admin/v1/auth/me"):
        assert "X-Hub-Version" not in client.get(path).headers, path
    assert api(admin, "GET", "/system", expect=200).json()["data"]["version"] == __version__
