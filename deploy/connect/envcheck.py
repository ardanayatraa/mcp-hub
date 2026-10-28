"""Check (and optionally repair) the Hub .env before the stack starts.

Mirrors the production rules in backend/app/config.py, so a mistake is named here instead of
surfacing as "Host is not allowed" or a backend that refuses to boot.

  python envcheck.py                      report only; exit 1 when something blocks start-up
  ENVCHECK_FIX=1 python envcheck.py       also repair what is safe, after a timestamped backup
  ENVCHECK_DOMAIN=hub.example.com ...     make this host the Hub's address (adds it to the allow-lists)

Secrets are never generated, rotated or overwritten: a wrong key is reported, not replaced.
"""
import base64
import os
import shutil
import sys
import time
from urllib.parse import urlsplit

ENV_FILE = os.environ.get("ENVCHECK_FILE", "/work/.env")
FIX = os.environ.get("ENVCHECK_FIX", "0") == "1"
DOMAIN = os.environ.get("ENVCHECK_DOMAIN", "").strip().lower()

EXAMPLE_VALUES = {"replace-with-long-random-string", "replace-with-fernet-key", "ChangeMe-Now-12", "change-me"}
SMTP_KEYS = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")


def read_env(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    values = {}
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return lines, values


def csv(raw):
    return [item.strip() for item in raw.split(",") if item.strip()]


def valid_fernet(key):
    try:
        return len(base64.urlsafe_b64decode(key.encode())) == 32
    except Exception:
        return False


def main():
    if not os.path.exists(ENV_FILE):
        print(f"[ERROR] {ENV_FILE} not found. Copy .env.example to .env and fill it in.")
        return 1
    lines, env = read_env(ENV_FILE)
    errors, warnings, fixes = [], [], {}
    production = env.get("ENVIRONMENT", "production") == "production"

    def get(key):
        return fixes.get(key, env.get(key, ""))

    # The Hub's address: the requested domain, else what MCP_ISSUER_URL already says.
    if DOMAIN:
        issuer = f"https://{DOMAIN}"
        if get("MCP_ISSUER_URL") != issuer:
            fixes["MCP_ISSUER_URL"] = issuer
    issuer = get("MCP_ISSUER_URL").rstrip("/")
    if not issuer:
        errors.append("MCP_ISSUER_URL is empty (set it, or run with ENVCHECK_DOMAIN=your.domain)")
    parts = urlsplit(issuer)
    host = parts.netloc.lower()
    if issuer and not host:
        errors.append(f"MCP_ISSUER_URL is not a valid address: {issuer}")
    if issuer and host:
        if get("MCP_PUBLIC_URL") != issuer + "/mcp":
            fixes["MCP_PUBLIC_URL"] = issuer + "/mcp"
        if DOMAIN or not get("ADMIN_CONSOLE_URL"):
            if get("ADMIN_CONSOLE_URL") != issuer and (DOMAIN or env.get("ADMIN_CONSOLE_URL")):
                fixes["ADMIN_CONSOLE_URL"] = issuer
        hosts = csv(get("ALLOWED_HOSTS"))
        if host not in [h.lower() for h in hosts] and parts.hostname not in [h.lower() for h in hosts]:
            fixes["ALLOWED_HOSTS"] = ",".join(hosts + [host])
        origins = csv(get("ALLOWED_ORIGINS"))
        origin = f"{parts.scheme}://{host}"
        if origin not in origins:
            fixes["ALLOWED_ORIGINS"] = ",".join(origins + [origin])

    # Things only a person can decide. These are reported, never changed.
    for key in ("POSTGRES_PASSWORD", "SECRET_ENCRYPTION_KEY", "SESSION_SIGNING_KEY"):
        value = env.get(key, "")
        if not value or value in EXAMPLE_VALUES:
            errors.append(f"{key} is empty or still the example value")
    key = env.get("SECRET_ENCRYPTION_KEY", "")
    if key and key not in EXAMPLE_VALUES and not valid_fernet(key):
        errors.append("SECRET_ENCRYPTION_KEY is not a valid Fernet key (32 bytes, url-safe base64)")
    signing = env.get("SESSION_SIGNING_KEY", "")
    if signing and signing not in EXAMPLE_VALUES and len(signing) < 32:
        errors.append("SESSION_SIGNING_KEY must be 32+ characters")
    if env.get("ADMIN_INITIAL_PASSWORD", "") in EXAMPLE_VALUES and "ADMIN_INITIAL_PASSWORD" in env:
        errors.append("ADMIN_INITIAL_PASSWORD is the published example; choose your own")

    if production:
        if get("COOKIE_SECURE").lower() != "true":
            errors.append("COOKIE_SECURE must be true in production")
        if issuer and parts.scheme != "https":
            errors.append("MCP_ISSUER_URL must be an https address in production")
        if any(not o.startswith("https://") for o in csv(get("ALLOWED_ORIGINS"))):
            errors.append("ALLOWED_ORIGINS must contain only https origins in production")
        if not get("EGRESS_ALLOWED_HOSTS") and not get("EGRESS_ALLOWED_CIDRS"):
            errors.append("EGRESS_ALLOWED_HOSTS (or EGRESS_ALLOWED_CIDRS) must list the apps the Hub may call")
        if get("MFA_REQUIRED").lower() != "true":
            warnings.append("MFA_REQUIRED is not true (recommended in production)")
    given = [name for name in SMTP_KEYS if env.get(name)]
    if given and len(given) < len(SMTP_KEYS):
        missing = ", ".join(name for name in SMTP_KEYS if not env.get(name))
        warnings.append(f"SMTP is half-configured; missing {missing}")

    pending = {k: v for k, v in fixes.items() if env.get(k, "") != v}
    for name, value in pending.items():
        print(f"[{'FIXED' if FIX else 'FIXABLE'}] {name}={value}")

    if FIX and pending:
        backup = f"{ENV_FILE}.bak-{time.strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(ENV_FILE, backup)
        out, done = [], set()
        for line in lines:
            name = line.partition("=")[0].strip()
            if name in pending and not line.lstrip().startswith("#") and "=" in line:
                out.append(f"{name}={pending[name]}")
                done.add(name)
            else:
                out.append(line)
        out += [f"{name}={value}" for name, value in pending.items() if name not in done]
        # In place, not rename: a bind-mounted file cannot be replaced, only rewritten.
        with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(out) + "\n")
        print(f"Backup: {backup}")
        print("Now run `docker compose up -d` again so the containers read the new .env.")
        pending = {}

    for message in warnings:
        print(f"[WARN] {message}")
    blocking = list(errors)
    if pending:
        blocking += [f"{name} is inconsistent (run with ENVCHECK_FIX=1 to repair)" for name in pending]
    for message in blocking:
        print(f"[ERROR] {message}")
    if blocking:
        print(f"{len(blocking)} problem(s) block start-up.")
        return 1
    print("env OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
