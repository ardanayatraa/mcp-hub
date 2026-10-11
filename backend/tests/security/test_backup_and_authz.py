import json

from app.persistence.models import ConnectorSecret
from app.persistence.session import open_session
from app.security.crypto import decrypt_secret
from app.services.backup import export_metadata, import_metadata
from sqlalchemy import select
from tests import helpers
from tests.helpers import (
    api,
    call,
    connect_app,
    create_tool,
    delegation,
    error_text,
    issue_key,
    publish,
)

KEY = "WyzcJBTgZUDuBhqKXe8GWpoJSvp2nR5J9ag3X5fMf5g="


def test_disabled_data_source_denies_cached_tool_names(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
        tool = publish(admin, create_tool(admin, app["connector_id"], allow_fields=["ref", "status"])["id"])
        token = issue_key(admin)
        api(admin, "PATCH", f"/modules/{app['modules']['projects']}/settings", {"enabled": False, "operations": []}, expect=200)
        assert "MODULE_DISABLED" in error_text(call(admin["client"], token, tool["mcp_name"], {}, delegation()))
        assert tool["mcp_name"] not in helpers.listed(admin["client"], token)
        api(admin, "PATCH", f"/modules/{app['modules']['projects']}/settings", {"enabled": True}, expect=200)
        assert helpers.result(call(admin["client"], token, tool["mcp_name"], {}, delegation()))["success"] is True


def test_metadata_backup_round_trip_keeps_ciphertext(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        connect_app(admin)
    with open_session() as db:
        document = export_metadata(db)
        original = db.scalar(select(ConnectorSecret)).secret_ciphertext
        assert "dev-your-app-key" not in json.dumps(document)
        import_metadata(db, document)
        db.commit()
        restored = db.scalar(select(ConnectorSecret))
        assert restored.secret_ciphertext == original
        assert decrypt_secret(KEY, restored.secret_ciphertext) == "dev-your-app-key"
