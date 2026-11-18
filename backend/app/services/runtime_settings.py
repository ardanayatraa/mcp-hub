"""Settings an administrator changes in the admin UI, without editing the environment or restarting.

A saved value overrides the environment value until it is reset. Every Hub process picks up a
change within a few seconds. Only settings that cannot lock administrators out or open private
networks are offered here: secure cookies, plain HTTP and private-network access stay in the
environment, and production keeps refusing unsafe values.
"""

import ipaddress
import re
import socket
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import HubError
from app.ids import as_utc, utcnow
from app.persistence.models import AdminUser, HubSetting
from app.security.audit import record_audit
from app.security.crypto import decrypt_secret, encrypt_secret

# Whole numbers an administrator may change, with the bounds the environment already enforces.
LIMITS: dict[str, tuple[int, int]] = {
    "max_records": (1, 50),
    "report_max_records": (50, 5000),
    "report_timeout_seconds": (1, 120),
    "tool_rate_limit": (1, 10000),
    "tool_rate_window_seconds": (1, 3600),
    "audit_retention_days": (1, 3650),
}
SMTP_FIELDS = ("smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from", "smtp_tls_mode")
SMTP_PORTS = {25, 465, 587, 2525}
KEYS = (*LIMITS, "mfa_required", "egress_allowed_hosts", "smtp")
# Shown read-only: changing these from the UI could lock everyone out or reach internal networks.
ENVIRONMENT_ONLY = ("cookie_secure", "allow_insecure_http", "egress_allow_private", "egress_allow_loopback",
                    "egress_allowed_cidrs", "egress_allowed_ports")
REFRESH_SECONDS = 5
HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
EMAIL_RE = re.compile(r"^[^@\s<>\"]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,24}$", re.IGNORECASE)

_lock = threading.Lock()
_baseline: dict[str, object] = {}  # environment values of the attributes an override has replaced
_last_refresh = 0.0


def _attributes(key: str) -> tuple[str, ...]:
    return SMTP_FIELDS if key == "smtp" else (key,)


def _apply(settings: Settings, rows: dict[str, dict]) -> None:
    """Put saved values on the shared settings object; restore the environment value where none is saved."""

    with _lock:
        for key in KEYS:
            row = rows.get(key)
            for name in _attributes(key):
                if row is None:
                    if name in _baseline:
                        setattr(settings, name, _baseline.pop(name))
                    continue
                _baseline.setdefault(name, getattr(settings, name))
                setattr(settings, name, _runtime_value(settings, key, name, row["value"]))


def _runtime_value(settings: Settings, key: str, name: str, value):
    if key == "egress_allowed_hosts":
        return ",".join(value)
    if key == "smtp":
        if name == "smtp_password":
            return decrypt_secret(settings.secret_encryption_key, value["password_ciphertext"]) if value.get("password_ciphertext") else ""
        return value[name.removeprefix("smtp_")]
    return value


def refresh(settings: Settings, db: Session | None = None, *, force: bool = False) -> None:
    """Re-read saved settings, at most every few seconds per process unless forced."""

    global _last_refresh
    if not force and time.monotonic() - _last_refresh < REFRESH_SECONDS:
        return
    _last_refresh = time.monotonic()
    from app.persistence.session import open_session

    own = db is None
    try:
        session = open_session() if own else db
    except RuntimeError:
        return
    try:
        # Each row holds {"value": ...}, so booleans and numbers survive a backup as JSON objects.
        rows = {row.key: {"value": row.value["value"]} for row in session.scalars(select(HubSetting))
                if row.key in KEYS and isinstance(row.value, dict) and "value" in row.value}
    except Exception:  # noqa: BLE001 - a database hiccup keeps the values already in effect
        return
    finally:
        if own:
            session.close()
    _apply(settings, rows)


def forget(settings: Settings) -> None:
    """Back to the environment values everywhere (tests and restores)."""

    global _last_refresh
    _apply(settings, {})
    _last_refresh = 0.0


def environment_value(settings: Settings, name: str):
    return _baseline.get(name, getattr(settings, name))


def view(db: Session, settings: Settings) -> dict:
    rows = {row.key: row for row in db.scalars(select(HubSetting))}

    def meta(key: str) -> dict:
        row = rows.get(key)
        return {"source": "hub" if row else "environment",
                "updated_at": as_utc(row.updated_at).isoformat() if row else None}

    limits = {key: {"value": getattr(settings, key), "environment": environment_value(settings, key), "min": low,
                    "max": high, **meta(key)} for key, (low, high) in LIMITS.items()}
    hosts = settings.csv(settings.egress_allowed_hosts)
    return {
        "limits": limits,
        "mfa_required": {"value": settings.mfa_required, "environment": environment_value(settings, "mfa_required"),
                         **meta("mfa_required")},
        "egress_allowed_hosts": {"value": hosts, "environment": settings.csv(environment_value(settings, "egress_allowed_hosts")),
                                 "cidrs": settings.csv(settings.egress_allowed_cidrs), **meta("egress_allowed_hosts")},
        "smtp": {"host": settings.smtp_host, "port": settings.smtp_port, "username": settings.smtp_username,
                 "from": settings.smtp_from, "tls_mode": settings.smtp_tls_mode, "password_set": bool(settings.smtp_password),
                 "ready": settings.smtp_configured, **meta("smtp")},
        "environment_only": {name: getattr(settings, name) for name in ENVIRONMENT_ONLY},
        "production": settings.environment == "production",
    }


def _whole(value, key: str) -> int:
    low, high = LIMITS[key]
    if type(value) is not int or not low <= value <= high:
        raise HubError("VALIDATION_FAILED", f"{key} must be a whole number from {low} to {high}", 422)
    return value


def _host(value, label: str, *, local_ok: bool = False) -> str:
    host = value.strip().lower().rstrip(".") if isinstance(value, str) else ""
    if local_ok and host == "localhost":
        return host
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not HOST_RE.match(host) or host == "localhost" or host.endswith(".localhost"):
        raise HubError("VALIDATION_FAILED", f"{label} must be a host name such as app.example.com", 422)
    return host


def _hosts(value, settings: Settings) -> list[str]:
    if not isinstance(value, list) or len(value) > 100:
        raise HubError("VALIDATION_FAILED", "Approved hosts must be a list of up to 100 host names", 422)
    # localhost is only meaningful where the environment already allows loopback calls (development).
    hosts = list(dict.fromkeys(_host(item, "Each approved host", local_ok=settings.egress_allow_loopback) for item in value))
    if settings.environment == "production" and not hosts and not settings.egress_allowed_cidrs:
        raise HubError("POLICY_LOCKED", "Production needs at least one approved host", 422)
    return hosts


def _public_mail_server(host: str, port: int, settings: Settings) -> None:
    """The mail server must be a public address, unless the environment allows private networks."""

    from app.connectors import ssrf_guard

    try:
        infos = ssrf_guard._resolve_host(host, port)
    except socket.gaierror as exc:
        raise HubError("VALIDATION_FAILED", "The mail server's host name could not be resolved", 422) from exc
    for info in infos:
        if not ssrf_guard._ip_allowed(ipaddress.ip_address(info[4][0]), settings):
            raise HubError("SSRF_BLOCKED", "The mail server is on a private or blocked network", 422)


def _smtp(value, current: dict | None, settings: Settings) -> dict:
    allowed = {"host", "port", "username", "password", "from", "tls_mode"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise HubError("VALIDATION_FAILED", "Email settings are invalid", 422)
    host = _host(value.get("host"), "The mail server")
    port = value.get("port")
    if type(port) is not int or port not in SMTP_PORTS:
        raise HubError("VALIDATION_FAILED", "The mail port must be 25, 465, 587 or 2525", 422)
    username = value.get("username")
    sender = value.get("from")
    tls_mode = value.get("tls_mode")
    if not isinstance(username, str) or not 1 <= len(username.strip()) <= 200:
        raise HubError("VALIDATION_FAILED", "Enter the mail account's user name", 422)
    if not isinstance(sender, str) or not EMAIL_RE.match(sender.strip()):
        raise HubError("VALIDATION_FAILED", "The sender must be an email address", 422)
    if tls_mode not in {"starttls", "ssl"}:
        raise HubError("VALIDATION_FAILED", "Encryption must be STARTTLS or SSL", 422)
    password = value.get("password")
    if password is None or password == "":
        # Left empty: keep the saved password, or the environment's while it is still in use.
        ciphertext = (current or {}).get("password_ciphertext")
        if ciphertext is None:
            if not settings.smtp_password:
                raise HubError("VALIDATION_FAILED", "Enter the mail account's password", 422)
            ciphertext = encrypt_secret(settings.secret_encryption_key, settings.smtp_password)
    elif isinstance(password, str) and len(password) <= 500:
        ciphertext = encrypt_secret(settings.secret_encryption_key, password)
    else:
        raise HubError("VALIDATION_FAILED", "The mail password is too long", 422)
    _public_mail_server(host, port, settings)
    return {"host": host, "port": port, "username": username.strip(), "from": sender.strip(), "tls_mode": tls_mode,
            "password_ciphertext": ciphertext}


def update(db: Session, admin: AdminUser, payload, settings: Settings) -> list[str]:
    """Save the given settings; null resets one to its environment value. Returns what changed."""

    if not isinstance(payload, dict) or not payload or set(payload) - set(KEYS):
        raise HubError("VALIDATION_FAILED", "Unknown setting", 422)
    current = {row.key: row for row in db.scalars(select(HubSetting))}
    values: dict[str, object] = {}
    for key, value in payload.items():
        if value is None:
            values[key] = None
        elif key in LIMITS:
            values[key] = _whole(value, key)
        elif key == "mfa_required":
            if type(value) is not bool:
                raise HubError("VALIDATION_FAILED", "mfa_required must be true or false", 422)
            values[key] = value
        elif key == "egress_allowed_hosts":
            values[key] = _hosts(value, settings)
        else:
            values[key] = _smtp(value, current["smtp"].value.get("value") if "smtp" in current else None, settings)
    if values.get("egress_allowed_hosts", "keep") is None and settings.environment == "production" \
            and not environment_value(settings, "egress_allowed_hosts") and not settings.egress_allowed_cidrs:
        raise HubError("POLICY_LOCKED", "Production needs at least one approved host", 422)
    for key, value in values.items():
        row = current.get(key)
        if value is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(HubSetting(key=key, value={"value": value}, updated_by=admin.id, updated_at=utcnow()))
        else:
            row.value, row.updated_by, row.updated_at = {"value": value}, admin.id, utcnow()
    changed = sorted(values)
    record_audit(db, action="settings.update", actor_ref=f"admin:{admin.id}", result="success",
                 tool_key=",".join(changed)[:120])
    db.flush()
    refresh(settings, db, force=True)
    return changed
