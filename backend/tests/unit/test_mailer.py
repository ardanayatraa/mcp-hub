"""Admin email must use authenticated TLS rather than a plaintext SMTP fallback."""

from app.config import get_settings
from app.security import mailer


def test_smtp_uses_starttls_before_authentication_and_delivery(monkeypatch):
    settings = get_settings()
    for name, value in {"smtp_host": "smtp.example.test", "smtp_port": 587,
                        "smtp_username": "sender@example.test", "smtp_password": "test-password",
                        "smtp_from": "sender@example.test", "smtp_tls_mode": "starttls"}.items():
        monkeypatch.setattr(settings, name, value)
    events = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example.test", 587, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def ehlo(self):
            events.append("ehlo")

        def starttls(self, *, context):
            assert context is not None
            events.append("starttls")

        def login(self, username, password):
            assert (username, password) == ("sender@example.test", "test-password")
            events.append("login")

        def send_message(self, message):
            assert message["To"] == "person@example.test"
            assert "123456" in message.get_content()
            events.append("send")

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    mailer.send_login_code("person@example.test", "123456")
    assert events == ["ehlo", "starttls", "ehlo", "login", "send"]
