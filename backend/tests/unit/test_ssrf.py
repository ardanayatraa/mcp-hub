import socket

import pytest
from app.config import Settings
from app.connectors.ssrf_guard import validate_destination
from app.errors import HubError
from tests import helpers


def _settings(**overrides) -> Settings:
    base = dict(
        environment="test",
        allow_insecure_http=True,
        egress_allow_private=False,
        egress_allow_loopback=False,
        egress_allowed_ports="80,443,8080",
        secret_encryption_key="WyzcJBTgZUDuBhqKXe8GWpoJSvp2nR5J9ag3X5fMf5g=",
        session_signing_key="test",
    )
    base.update(overrides)
    return Settings(**base)


def test_metadata_and_loopback_and_private_are_blocked():
    settings = _settings()
    for url in (
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1/admin",
        "http://10.1.1.1/internal",
        "http://192.168.1.20/db",
        "file:///etc/passwd",
        "http://user:pass@example.com/",
    ):
        with pytest.raises(HubError) as raised:
            validate_destination(url, settings)
        assert raised.value.code == "SSRF_BLOCKED"


def test_private_stays_blocked_when_rfc1918_is_explicitly_allowed():
    settings = _settings(egress_allow_private=True)
    with pytest.raises(HubError):
        validate_destination("http://169.254.169.254/", settings)


def test_public_host_is_allowed_when_every_address_is_public(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr("app.connectors.ssrf_guard._resolve_host", fake_getaddrinfo)
    host, port, addresses = validate_destination("https://projects.example/api", _settings(allow_insecure_http=False))
    assert host == "projects.example"
    assert port == 443
    assert addresses == ["93.184.216.34"]


def test_rebinding_to_a_private_address_is_rejected(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port))]

    monkeypatch.setattr("app.connectors.ssrf_guard._resolve_host", fake_getaddrinfo)
    with pytest.raises(HubError) as raised:
        validate_destination("https://projects.example/api", _settings(allow_insecure_http=False))
    assert raised.value.code == "SSRF_BLOCKED"


def test_fake_connector_dns_does_not_change_database_resolution(monkeypatch):
    resolver = socket.getaddrinfo
    helpers.dns(monkeypatch)
    assert socket.getaddrinfo is resolver
    assert validate_destination("https://projects.test/api", _settings())[2] == ["93.184.216.34"]
