"""Migrations: populated round-trips keep FK children; the simplification upgrade keeps live tools."""

import json
from datetime import datetime, timedelta, timezone

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.config import get_settings
from app.ids import utcnow
from app.persistence import SCHEMA_REVISION
from app.persistence.models import AdminSession, AdminUser
from app.persistence.session import open_session
from app.security.passwords import hash_password
from app.services.backup import export_metadata
from sqlalchemy import MetaData, create_engine, inspect, select, text
from tests.security.test_prd_regressions import published  # noqa: F401

LEGACY = "902b2fc08310"


def test_code_expects_the_alembic_head():
    assert ScriptDirectory.from_config(Config("alembic.ini")).get_current_head() == SCHEMA_REVISION


def test_activated_email_code_admins_move_to_password_sign_in(tmp_path, monkeypatch):
    url = "sqlite+pysqlite:///" + (tmp_path / "peer-login.db").as_posix()
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "e8a1b7c4d930")
    engine = create_engine(url)
    with engine.begin() as connection:
        for user_id, email, token_hash in (("activated", "peer@example.com", None),
                                           ("pending", "old-temp@example.com", "a" * 64)):
            connection.execute(text("INSERT INTO admin_users (id, email, password_hash, role, auth_method, "
                                    "activation_token_hash, activation_expires_at, mfa_enabled, is_active, created_at) "
                                    "VALUES (:id, :email, :password_hash, 'hub_admin', 'email_otp', :token_hash, "
                                    ":expires_at, false, true, :created_at)"),
                               {"id": user_id, "email": email,
                                "password_hash": hash_password("Passw0rd-1234"), "token_hash": token_hash,
                                "expires_at": (utcnow() + timedelta(hours=24)).isoformat() if token_hash else None,
                                "created_at": utcnow().isoformat()})
    command.upgrade(config, "head")
    with engine.begin() as connection:
        rows = {row.id: row.auth_method for row in connection.execute(text("SELECT id, auth_method FROM admin_users"))}
        assert rows == {"activated": "password", "pending": "email_otp"}
        assert connection.scalar(text("SELECT activation_issued_at FROM admin_users WHERE id = 'pending'")) is not None
        connection.execute(text("UPDATE admin_users SET email = NULL WHERE id = 'pending'"))
    command.downgrade(config, "e8a1b7c4d930")
    with engine.connect() as connection:
        rows = {row.id: row for row in connection.execute(text("SELECT id, email, auth_method FROM admin_users"))}
        assert rows["activated"].auth_method == "email_otp"
        assert rows["pending"].email == "pending-pending@activation.invalid"
    engine.dispose()


def test_existing_super_admins_get_one_root_and_peer_roles(tmp_path, monkeypatch):
    url = "sqlite+pysqlite:///" + (tmp_path / "roles.db").as_posix()
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "a9d4c2e7f615")
    engine = create_engine(url)
    with engine.begin() as connection:
        for user_id, created_at in (("first", "2026-01-01 00:00:00"), ("second", "2026-02-01 00:00:00")):
            connection.execute(text(
                "INSERT INTO admin_users (id, email, password_hash, role, mfa_enabled, is_active, created_at) "
                "VALUES (:id, :email, 'hash', 'super_admin', false, true, :created_at)"
            ), {"id": user_id, "email": f"{user_id}@localhost", "created_at": created_at})
    command.upgrade(config, "head")
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, role, is_root, auth_method FROM admin_users ORDER BY created_at")).all()
        assert rows == [("first", "super_admin", 1, "totp"), ("second", "hub_admin", 0, "totp")]
    engine.dispose()


def test_populated_upgrade_downgrade_preserves_fk_children(published, tmp_path, monkeypatch):  # noqa: F811
    with open_session() as db:
        document = export_metadata(db)
        admins = [{c.name: getattr(row, c.name) for c in AdminUser.__table__.columns} for row in db.scalars(select(AdminUser))]
        sessions = [{c.name: getattr(row, c.name) for c in AdminSession.__table__.columns} for row in db.scalars(select(AdminSession))]
    url = "sqlite+pysqlite:///" + (tmp_path / "migration.db").as_posix()
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "3b9903ce10ea")
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    originals = {"admin_users": admins, "admin_sessions": sessions, **document["tables"]}
    counts = {}
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for name, rows in originals.items():
            if name not in metadata.tables:
                continue
            table = metadata.tables[name]
            for row in rows:
                values = {key: value for key, value in row.items() if key in table.columns}
                for column in table.columns:
                    if column.type.__class__.__name__ == "DATETIME" and isinstance(values.get(column.name), str):
                        values[column.name] = datetime.fromisoformat(values[column.name])
                connection.execute(table.insert().values(**values))
            counts[name] = len(rows)
    for destination, operation in [("head", command.upgrade), ("3b9903ce10ea", command.downgrade), ("head", command.upgrade)]:
        operation(config, destination)
        with engine.connect() as connection:
            for name, expected in counts.items():
                assert connection.scalar(text(f"SELECT COUNT(*) FROM {name}")) == expected, (destination, name)
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_simplification_upgrade_keeps_published_tools_and_is_reversible(tmp_path, monkeypatch):
    url = "sqlite+pysqlite:///" + (tmp_path / "legacy.db").as_posix()
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, LEGACY)
    engine = create_engine(url)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    schema = json.dumps({"type": "object", "additionalProperties": False, "properties": {}})
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO applications VALUES ('app', 'legacy', 'Legacy', 'dev', 'active', NULL, :now)"), {"now": now})
        connection.execute(text("INSERT INTO connectors VALUES ('con', 'app', 'http_contract', 'https://legacy.test', '/m', '/h', "
                                "'api_key', 'active', 1, 5000, 0, NULL, :now, :now)"), {"now": now})
        for tool_id, status in (("live", "published"), ("checked", "validated")):
            connection.execute(text("INSERT INTO rest_tool_mappings (id, connector_id, method, path_template, timeout_ms, "
                                    "max_payload_bytes, query_params, pagination, safe_query, requires_user_context, tenant_field, "
                                    "audit_level) VALUES (:id, 'con', 'GET', '/items', 5000, 1024, '[]', '{}', 0, 1, 'tenant_id', 'standard')"),
                               {"id": "map_" + tool_id})
            connection.execute(text("INSERT INTO tool_definitions VALUES (:id, :key, :name, '1.0.0', 'con', :map, 'items', 'Items', "
                                    ":schema, '{}', '{\"allow_fields\": []}', 'read_only', :status, NULL, 'hash', 1, 'owner', :now)"),
                               {"id": tool_id, "key": f"legacy.items.{tool_id}", "name": f"legacy__items__{tool_id}",
                                "map": "map_" + tool_id, "schema": schema, "status": status, "now": now})
        connection.execute(text("INSERT INTO mcp_server_profiles VALUES ('prof', 'default', '/mcp', '{}', 'active', :now)"), {"now": now})
        connection.execute(text("INSERT INTO mcp_profile_tools VALUES ('link', 'prof', 'live', 1, 1)"))
        connection.execute(text("INSERT INTO skill_definitions VALUES ('skill', 'process_dataset', '1.0.0', 'published', 'x', 'd', '{}')"))

    command.upgrade(config, "head")
    tables = set(inspect(engine).get_table_names())
    assert not tables & {"mcp_server_profiles", "mcp_profile_tools", "skill_definitions", "approval_requests", "processing_jobs"}
    with engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT id, status FROM tool_definitions")).all())
        assert rows == {"live": "published", "checked": "draft"}
        assert connection.scalar(text("SELECT template FROM tool_definitions WHERE id = 'live'")) == "read"
        # X-API-Key connectors now authenticate with the same secret as a bearer token.
        assert connection.scalar(text("SELECT auth_type FROM connectors WHERE id = 'con'")) == "bearer"

    command.downgrade(config, LEGACY)
    with engine.connect() as connection:
        linked = connection.execute(text("SELECT tool_id FROM mcp_profile_tools")).scalars().all()
        assert linked == ["live"]
        assert connection.scalar(text("SELECT key FROM mcp_server_profiles")) == "default"
        assert connection.scalar(text("SELECT COUNT(*) FROM tool_definitions")) == 2
    engine.dispose()
