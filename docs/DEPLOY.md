# Deploying to production

For aaPanel with deployment after a passing `main` build, use
[the automated aaPanel deployment guide](DEPLOY_AAPANEL_OTOMATIS.md). It keeps
server credentials outside releases and does not overwrite panel configuration.

One Hub serves every app. It needs a Linux server (2 vCPU and 4 GB RAM is plenty for a
few apps), PostgreSQL 16, a dedicated Redis, a domain name with a TLS certificate, and a reverse proxy in front
of it. `infra/compose.yml` is a development stack; use it as a reference, not as is.

## 1. Environment

The Hub refuses to start in production when any of these is unsafe, and names the problem.

| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | `postgresql+psycopg://hub:<password>@<db-host>:5432/hub` |
| `RATE_LIMIT_BACKEND` | `redis`; production rejects in-process counters |
| `RATE_LIMIT_REDIS_URL`, `RATE_LIMIT_REDIS_PASSWORD` | Private Redis URL and a random password of at least 32 characters. Use `rediss://` when TLS is needed. All workers use the same URL, database and namespace. |
| `RATE_LIMIT_NAMESPACE` | Deployment-specific prefix, such as `mcp-hub`; do not change it during an ordinary restart |
| `SECRET_ENCRYPTION_KEY` | A Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep it in your secret manager; without it stored keys cannot be read. |
| `SESSION_SIGNING_KEY` | 32+ random characters: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_INITIAL_EMAIL`, `ADMIN_INITIAL_PASSWORD` | The first super admin. Not the example password. |
| `COOKIE_SECURE` | `true` |
| `MFA_REQUIRED` | `true` requires authenticator MFA for legacy accounts; invited team accounts use a password after activation. Root always uses an authenticator in production. |
| `ADMIN_CONSOLE_URL` | Public HTTPS URL of the admin UI for invitation links; defaults to `MCP_ISSUER_URL`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS_MODE` | Authenticated TLS SMTP for activation codes. Use `starttls` on port 587 or `ssl` on 465. Keep credentials in the server env file. |
| `ALLOWED_HOSTS` | `hub.example.com` (the public name; add others only if used) |
| `ALLOWED_ORIGINS` | `https://hub.example.com` |
| `MCP_PUBLIC_URL`, `MCP_ISSUER_URL` | `https://hub.example.com/mcp`, `https://hub.example.com` |
| `EGRESS_ALLOWED_HOSTS` or `EGRESS_ALLOWED_CIDRS` | The apps the Hub may call, such as `app.example.com` |
| `FORWARDED_ALLOW_IPS` | The reverse proxy's address (`127.0.0.1` when it runs on the same server) |
| `MODEL_EGRESS_ALLOWED_HOSTS` | Optional: limit where AI providers may live |
| `ASSISTANT_REPO_PATH` | Optional: the repository checkout the console **Assistant** reads, mounted read-only (for example `/repo`). Without it in a container, the Assistant is off. |

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

All workers share rate budgets through Redis. Concurrency bulkheads remain per
process; account for the number of workers when sizing source and model capacity.
Restart the process on failure (systemd `Restart=always`, or the container's restart
policy). `GET /ready` returns 200 once both metadata storage and the configured
limiter answer; Redis failures reject limited requests with 503, without a memory fallback.

Keep Redis on a private network with authentication and `maxmemory-policy noeviction`.
Use a dedicated database/instance and size it for active users and budgets; monitor
memory and rejected writes. Eviction would discard security counters. Keep persistence
enabled in production (AOF with `appendfsync always` when every admitted request must
survive a crash), and protect the data volume. Loss/restoration of this metadata resets
rate windows; drain public traffic for the longest configured window before reopening
after counter loss. The development Compose Redis deliberately has no persistence.

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

Sign in as the first root admin and scan the authenticator QR code within `MFA_ENROLL_HOURS` (72).
Root uses authenticator MFA in production even if `MFA_REQUIRED=false`. If the window passed,
run on the server: `python -m app.bootstrap --reset-mfa admin@example.com`. Set SMTP first,
then add other admins under **Access → Team** without entering an email. Hub admins can also
invite members there; their Team list excludes root. Choose the link lifetime (1 day, 1 week,
1 month, or never), then copy the
activation link and share it privately. The member enters their real email, verifies an
emailed code, and sets a password. Later sign-ins use email and password. Root can
issue a new link when the previous one expires.

## 5. Connect apps

For each app: **Apps → Connect** (its address and keys), enable its data sources, then
issue a client key under **Access**. For a Laravel app with the adapter from
`integrations/laravel`, set in its `.env`:

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
- [ ] Shared authenticated Redis with no eviction and tested failure/recovery
- [ ] Backend processes restarted automatically, behind the proxy
- [ ] Root has authenticator MFA; invited admins can receive their one-time activation code over authenticated TLS SMTP
- [ ] Each app's allowed models and token budget set
