# ruff: noqa: E402 - test environment must be set before importing the application.
import os
from collections.abc import Generator

os.environ["ENVIRONMENT"] = "test"
test_database_url = os.environ.get("HUB_TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
if not test_database_url.startswith("sqlite") and not test_database_url.split("?")[0].endswith("/hub_test"):
    raise RuntimeError("HUB_TEST_DATABASE_URL must target the disposable hub_test database")
os.environ["DATABASE_URL"] = test_database_url
os.environ["SECRET_ENCRYPTION_KEY"] = "WyzcJBTgZUDuBhqKXe8GWpoJSvp2nR5J9ag3X5fMf5g="
os.environ["SESSION_SIGNING_KEY"] = "test-session-signing-key-value"
os.environ["ADMIN_INITIAL_PASSWORD"] = "ChangeMe-Now-12"
os.environ["MFA_REQUIRED"] = "false"
os.environ["COOKIE_SECURE"] = "false"
os.environ["ALLOW_INSECURE_HTTP"] = "true"
os.environ["EGRESS_ALLOW_LOOPBACK"] = "false"
os.environ["EGRESS_ALLOW_PRIVATE"] = "false"
os.environ["EGRESS_ALLOWED_PORTS"] = "80,443,8080,8081"
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173,http://testserver"
os.environ["MCP_PUBLIC_URL"] = "http://testserver/mcp"
os.environ["MCP_ISSUER_URL"] = "http://127.0.0.1:8000"

import app.persistence.session as db_session
import pytest
from app.ids import new_id
from app.main import create_app
from app.persistence.base import Base
from app.persistence.models import AdminUser
from app.persistence.session import open_session
from app.security.passwords import hash_password
from app.security.rate_limit import reset_limits
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    reset_limits()
    # Each TestClient starts the MCP session manager, and that manager can run once.
    application = create_app()
    assert db_session.engine is not None
    Base.metadata.drop_all(db_session.engine)
    Base.metadata.create_all(db_session.engine)
    with TestClient(application) as test_client:
        db = open_session()
        try:
            db.add(
                AdminUser(
                    id=new_id(),
                    email="admin@localhost",
                    password_hash=hash_password("ChangeMe-Now-12"),
                    role="super_admin",
                )
            )
            db.commit()
        finally:
            db.close()
        yield test_client


@pytest.fixture()
def admin(client: TestClient) -> dict:
    response = client.post(
        "/api/admin/v1/auth/login",
        json={"email": "admin@localhost", "password": "ChangeMe-Now-12"},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    return {"csrf": body["csrf_token"], "client": client}


def auth_headers(admin: dict, extra: dict | None = None) -> dict:
    headers = {"X-CSRF-Token": admin["csrf"]}
    if extra:
        headers.update(extra)
    return headers
