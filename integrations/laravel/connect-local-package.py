"""Align the reviewed local app with its dedicated PHP runtime; no credential output."""
import argparse
import asyncio
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
state_path = root / ".verification/laravel-connection.json"
state = json.loads(state_path.read_text())
source = Path(state["source_path"]).resolve()
assert source.name == "hireach" and source.parent == root.parent, "Unexpected local application"
env_path = source / ".env"
values = dotenv_values(env_path)
hub = (values.get("MCP_HUB_URL") or state["hub_url"]).removesuffix("/mcp")
assert urlsplit(hub).hostname in ("localhost", "127.0.0.1") and urlsplit(hub).port == 18000
target = "http://127.0.0.1:18881"
service_token = values.get("MCP_HUB_APP_TOKEN") or values.get("MCP_HUB_SOURCE_KEY") or state["source_key"]
client = httpx.Client(base_url=hub, timeout=15, trust_env=False)
deadline = time.monotonic() + 15
while True:
    try:
        client.get("/health").raise_for_status()
        break
    except httpx.HTTPError:
        if time.monotonic() >= deadline:
            raise RuntimeError("Local Hub did not become ready") from None
        time.sleep(0.25)
health = httpx.get(target + "/api/ai/v1/health", headers={"Authorization": "Bearer " + service_token},
                   trust_env=False, timeout=15)
assert health.status_code == 200, "Dedicated local source health check failed"
launcher = (root / ".verification/start-hub.ps1").read_text(encoding="utf-8-sig")
# This is a local server-maintenance command, operating on the owner's SQLite
# metadata with existing shell access. It uses the normal validators and audit
# services; no administrator password, MFA state, or login session is changed.
for match in re.finditer(r"""\$env:([A-Z_]+)\s*=\s*(['"])(.*?)\2""", launcher):
    os.environ[match.group(1)] = match.group(3).replace("''", "'").replace("$taskRoot", root.as_posix())
dev = dotenv_values(root / "dev.env")
if dev.get("SECRET_ENCRYPTION_KEY"):
    os.environ["SECRET_ENCRYPTION_KEY"] = dev["SECRET_ENCRYPTION_KEY"]
sys.path.insert(0, str(root / "backend"))
from sqlalchemy import select
from app.config import get_settings
from app.persistence.models import AdminUser, Application, Connector
from app.persistence.session import init_engine, open_session
from app.security.authorization import require_app_access, require_role, ADMIN_ROLES
from app.security.crypto import decrypt_secret
from app.security.auth import lookup_service_token
from app.services import connectors as service

settings = get_settings()
assert settings.database_url.startswith("sqlite"), "Maintenance command is local-only"
database_path = Path(settings.database_url.split("///", 1)[1]).resolve()
assert database_path.is_relative_to(root / ".verification") and database_path.is_file(), "Unexpected metadata database"
assert "18881" in settings.csv(settings.egress_allowed_ports), "Dedicated runtime port is not allowed by the Hub"
init_engine(settings.database_url)
db = open_session()
admin = db.scalar(select(AdminUser).where(AdminUser.is_root.is_(True), AdminUser.is_active.is_(True)))
assert admin is not None, "Local root administrator is unavailable"
application = db.scalar(select(Application).where(Application.key == "hireach", Application.environment == "dev"))
assert application is not None, "Local application connector was not found"
require_role(admin.role, ADMIN_ROLES)
require_app_access(db, admin, application.id)
connector = db.scalar(select(Connector).where(Connector.app_id == application.id))
assert connector is not None, "Local application connector was not found"
stored_token = decrypt_secret(settings.secret_encryption_key, service.connector_secret(db, connector.id).secret_ciphertext)
assert hmac.compare_digest(stored_token, service_token), "Existing service credentials differ; no rotation performed"
current_client_key = values.get("MCP_HUB_CLIENT_KEY") or values.get("MCP_HUB_TOKEN")
identity = lookup_service_token(db, current_client_key)
assert identity is not None and identity.app_id == application.id, "Existing client key is not valid for this application"
stored_delegation = decrypt_secret(settings.secret_encryption_key, service.connector_secret(db, connector.id).delegation_ciphertext)
assert hmac.compare_digest(stored_delegation, values["MCP_HUB_DELEGATION_SECRET"]), "Existing delegation credentials differ"
print("Local source health is OK. Plan: use the dedicated PHP runtime and source-managed permissions.")
if not args.apply:
    print("Dry-run passed. No application settings or connector configuration changed.")
    raise SystemExit(0)
backup = root / ".verification/hireach-package-backup"
backup.mkdir(exist_ok=True)
for path, name in ((env_path, "environment-before-local-runtime"), (state_path, "connection-before-local-runtime.json")):
    if not (backup / name).exists():
        shutil.copy2(path, backup / name)
if not (backup / "connector-before-local-runtime.json").exists():
    (backup / "connector-before-local-runtime.json").write_text(json.dumps(service.connector_view(db, connector, application), indent=2))
previous_env = env_path.read_bytes()
previous_state = state_path.read_bytes()
database_backup = backup / "hub-before-local-runtime.db"
if not database_backup.exists():
    with sqlite3.connect(database_path) as source_database, sqlite3.connect(database_backup) as backup_database:
        source_database.backup(backup_database)
lines = previous_env.decode("utf-8-sig").splitlines()
remaining = {"MCP_HUB_BASE_URL": target, "MCP_HUB_SOURCE_URL": target}
updated = []
for line in lines:
    key = line.split("=", 1)[0].strip()
    if key in ("MCP_HUB_BASE_URL", "MCP_HUB_SOURCE_URL"):
        if key in remaining:
            updated.append(key + "=" + remaining.pop(key))
    else:
        updated.append(line)
updated += [key + "=" + value for key, value in remaining.items()]
try:
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    state["source_url"] = target
    state["source_key"] = service_token
    state["delegation_secret"] = values["MCP_HUB_DELEGATION_SECRET"]
    state["token"] = current_client_key
    state["identity_id"] = identity.id
    state["expires_at"] = identity.expires_at.isoformat() if identity.expires_at else None
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    subprocess.run([shutil.which("php"), "artisan", "config:clear"], cwd=source, check=True, capture_output=True)
    service.edit_connector(db, admin, connector, application, {"base_url": target, "connector_type": "source_managed"}, settings)
    assert asyncio.run(service.test_connector(db, admin, connector, application, settings))["status"] == "ok"
    db.flush()
    asyncio.run(service.discover(db, admin, connector, application, settings))
    db.flush()
    service.activate(db, admin, connector, application)
    db.commit()
except Exception:
    db.rollback()
    env_path.write_bytes(previous_env)
    state_path.write_bytes(previous_state)
    subprocess.run([shutil.which("php"), "artisan", "config:clear"], cwd=source, capture_output=True)
    raise
finally:
    db.close()
print("Local connector active with the dedicated PHP runtime. Existing credentials and application grants retained.")
