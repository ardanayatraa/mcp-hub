# Deploying to production

One Hub serves every app. It needs a Linux server (2 vCPU and 4 GB RAM is plenty for a
few apps), PostgreSQL 16, a domain name with a TLS certificate, and a reverse proxy in front
of it. `infra/compose.yml` is a development stack; use it as a reference, not as is.

## 1. Environment

The Hub refuses to start in production when any of these is unsafe, and names the problem.

| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | `postgresql+psycopg://hub:<password>@<db-host>:5432/hub` |
| `SECRET_ENCRYPTION_KEY` | A Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep it in your secret manager; without it stored keys cannot be read. |
| `SESSION_SIGNING_KEY` | 32+ random characters: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_INITIAL_EMAIL`, `ADMIN_INITIAL_PASSWORD` | The first super admin. Not the example password. |
| `COOKIE_SECURE` | `true` |
| `MFA_REQUIRED` | `true` is recommended. `false` lets admins sign in with the password alone. |
| `ALLOWED_HOSTS` | `hub.example.com` (the public name; add others only if used) |
| `ALLOWED_ORIGINS` | `https://hub.example.com` |
| `MCP_PUBLIC_URL`, `MCP_ISSUER_URL` | `https://hub.example.com/mcp`, `https://hub.example.com` |
| `EGRESS_ALLOWED_HOSTS` or `EGRESS_ALLOWED_CIDRS` | The apps the Hub may call, such as `app.example.com` |
| `FORWARDED_ALLOW_IPS` | The reverse proxy's address (`127.0.0.1` when it runs on the same server) |
| `MODEL_EGRESS_ALLOWED_HOSTS` | Optional: limit where AI providers may live |

Leave `ALLOW_INSECURE_HTTP`, `ALLOW_INSECURE_TLS`, `EGRESS_ALLOW_PRIVATE` and
`EGRESS_ALLOW_LOOPBACK` unset. Optional tuning (`GATEWAY_APP_RATE_LIMIT`,
`AUDIT_RETENTION_DAYS`, `PURGE_INTERVAL_HOURS`, `MFA_ENROLL_HOURS`) is listed in
`.env.example`.

## 2. Start the backend

With the backend image (`infra/Dockerfile.backend`, which runs as an unprivileged user), the
container does this on every start. Without Docker, from `backend/`:

```bash
uv sync --frozen --no-dev
uv run alembic upgrade head          # applies new migrations; back up first on upgrades
uv run python -m app.bootstrap       # creates the first super admin once
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Run **one** process (no `--workers`): rate limits are counted in memory. Restart it on
failure (systemd `Restart=always`, or the container's restart policy). `GET /ready` returns
200 once the database answers; use it for health checks.

## 3. Reverse proxy

Build the admin UI (`cd frontend && pnpm install --frozen-lockfile && pnpm build`) and serve
`frontend/dist` with nginx, starting from `infra/nginx.conf`:

- set `server_name hub.example.com;` and your certificate paths (for example Let's Encrypt's
  `fullchain.pem` and `privkey.pem`);
- make the port-80 server `return 301 https://$host$request_uri;`;
- point every `proxy_pass` at the backend (`http://127.0.0.1:8000`);
- keep the header lines, `proxy_set_header X-Forwarded-For $remote_addr;` (it replaces any
  address the client sends) and the `/api/`, `/mcp`, `/chat/`, `/gateway/`, `/health`,
  `/ready`, `/assets/` and `/` locations.

Check with `nginx -t`, then `curl -I https://hub.example.com/` should show
`Strict-Transport-Security` and `Content-Security-Policy`.

## 4. First sign-in

Sign in as the first super admin. With `MFA_REQUIRED=true`, do it within `MFA_ENROLL_HOURS` (72)
and scan the QR code. If the window passed, run on the server:
`python -m app.bootstrap --reset-mfa admin@example.com`. Add the other admins under
**Access → Team**; with MFA required, each must set it up within the same window.

## 5. Connect apps

For each app: **Apps → Connect** (its address and keys), enable its data sources, then
issue a client key under **Access**. For HiReach, set in its `.env`:

```
MCP_HUB_URL=https://hub.example.com/mcp
MCP_HUB_TOKEN=<client key>
MCP_BRIDGE_URL=https://hub.example.com/gateway/mcp
MCP_BRIDGE_TOKEN=<client key>
```

Turn its **Chat** on, and under **Model gateway access** choose the models it may use and
a monthly token budget (super admins only). In production the model gateway rejects
both discovery and completions until both are set. An empty model list or a zero
budget is therefore not a production-wide allowance.

## 6. Operate

- **Backups:** schedule `pg_dump` off the server and practise a restore
  ([Backup](BACKUP.md)). Keep `SECRET_ENCRYPTION_KEY` with the dumps' access controls,
  not in them.
- **Upgrades:** dump the database, deploy the new version; migrations run at start.
- **Key rotation:** see [Security](SECURITY.md#secrets-at-rest).
- **Logs:** one JSON object per line with `event`, `error_code`, `trace_id` and, for
  requests, `method`, `path` and `status`. Prompts, answers, tokens and personal data
  are never logged. Watch for `gateway_model_error` and `purge_failed`.
- **Housekeeping:** expired activity, sessions and memories are purged every 6 hours.

## Checklist

- [ ] `ENVIRONMENT=production` starts without an `UNSAFE_CONFIGURATION` error
- [ ] HTTPS only, with a valid certificate and the HSTS header
- [ ] PostgreSQL with scheduled, tested off-server dumps
- [ ] Secrets in a secret manager or a root-only env file, never in git
- [ ] One backend process, restarted automatically, behind the proxy
- [ ] Every admin has MFA, or `MFA_REQUIRED=false` is deliberate and every admin has a strong, unique password
- [ ] Each app's allowed models and token budget set
