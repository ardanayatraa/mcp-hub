"""Run inside the release virtualenv. Never emit settings or database connection details."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def inspect():
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from app.config import get_settings
    from app.persistence import SCHEMA_REVISION
    from sqlalchemy import create_engine

    settings = get_settings()
    if settings.environment != "production" or not settings.database_url.startswith("postgresql"):
        raise RuntimeError("Production PostgreSQL settings are required")
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if head != SCHEMA_REVISION:
        raise RuntimeError("Release schema version is inconsistent")
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_heads()
    finally:
        engine.dispose()
    return {"current": list(current), "target": head}


def backup(binary: str, output: str):
    from app.config import get_settings
    from sqlalchemy.engine import make_url

    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("PostgreSQL backup is required")
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("PG"):
            environment.pop(key, None)
    for key, value in {"PGHOST": url.host, "PGPORT": url.port, "PGUSER": url.username, "PGDATABASE": url.database}.items():
        if value is not None:
            environment[key] = str(value)
    for name, variable in {"sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT",
                           "sslkey": "PGSSLKEY", "connect_timeout": "PGCONNECT_TIMEOUT", "channel_binding": "PGCHANNELBINDING"}.items():
        if name in url.query:
            environment[variable] = str(url.query[name])
    environment.setdefault("PGCONNECT_TIMEOUT", "10")
    target = Path(output)
    if target.exists() or target.is_symlink():
        raise RuntimeError("Backup target already exists")
    temporary = target.with_name(target.name+"."+uuid.uuid4().hex+".tmp")
    password_file = target.with_name(".pgpass-"+uuid.uuid4().hex)
    try:
        if url.password is not None:
            parts = [url.host or "*", str(url.port or 5432), url.database or "*", url.username or "*", url.password]
            if any("\n" in part or "\r" in part for part in parts):
                raise RuntimeError("Password file values must use one line")
            with password_file.open("x") as handle:
                os.chmod(password_file, 0o600)
                handle.write(":".join(part.replace("\\", "\\\\").replace(":", "\\:") for part in parts)+"\n")
            environment["PGPASSFILE"] = str(password_file)
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            result = subprocess.run([binary, "--format=custom", "--no-password"],
                                    env=environment, stdout=handle, stderr=subprocess.DEVNULL, timeout=300)
            handle.flush()
            os.fsync(handle.fileno())
        if result.returncode or temporary.stat().st_size == 0:
            raise RuntimeError("Database backup failed")
        os.link(temporary, target)  # do not replace a backup created concurrently
    finally:
        temporary.unlink(missing_ok=True)
        password_file.unlink(missing_ok=True)
    return {"backup": "created"}


if __name__ == "__main__":
    try:
        from app.config import Settings, get_settings
        for name in Settings.model_fields:
            os.environ.pop(name.upper(), None)
        get_settings.cache_clear()
        command = sys.argv[1]
        if command == "inspect" and len(sys.argv) == 2:
            result = inspect()
        elif command == "backup" and len(sys.argv) == 4:
            result = backup(sys.argv[2], sys.argv[3])
        else:
            raise RuntimeError("Unsupported operation")
        print(json.dumps(result))
    except Exception:
        # Driver and subprocess errors may contain a password or connection string.
        print(json.dumps({"error": "RUNTIME_CHECK_FAILED"}))
        sys.exit(1)
