# Production and recovery

Use HTTPS, PostgreSQL, dedicated Redis, a reverse proxy, and managed secrets for production. Size the deployment using workload measurements rather than CI results.

## Core settings

| Setting | Purpose |
|---|---|
| `ENVIRONMENT=production` | Enable production configuration checks |
| `DATABASE_URL` | PostgreSQL with a restricted service account |
| `SECRET_ENCRYPTION_KEY` | Read encrypted credentials; required during recovery |
| `SESSION_SIGNING_KEY` | Sign sessions with a strong random key |
| `COOKIE_SECURE=true` | Send cookies over HTTPS only |
| `RATE_LIMIT_BACKEND=redis` | Share counters between processes |
| Redis URL/password/namespace | Private authenticated Redis and consistent rate-limit state |
| `ALLOWED_HOSTS`, `ALLOWED_ORIGINS` | Valid public hosts and origins |
| `MCP_PUBLIC_URL`, `MCP_ISSUER_URL` | Public endpoint identity |
| `EGRESS_ALLOWED_HOSTS` / `EGRESS_ALLOWED_CIDRS` | Permitted source destinations |
| `FORWARDED_ALLOW_IPS` | Trusted proxies only |

Production rejects unsafe configuration. Do not bypass readiness failures by disabling HTTP/TLS checks or switching to in-memory limits.

## Build and deployment

Use the backend and frontend lock files. Run Alembic through your deployment procedure; the backend rejects an outdated schema. The proxy serves `/api/`, `/mcp`, `/chat/`, `/gateway/`, `/health`, and `/ready`, alongside frontend assets.

`infra/compose.yml` is a development stack. Use the [complete deployment guide](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/DEPLOY.md), [aaPanel systemd guide](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/DEPLOY_AAPANEL_OTOMATIS.md), or [aaPanel Docker guide](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/DEPLOY_AAPANEL_DOCKER.md) for guarded deployment. The server retains ownership of secrets and panel configuration.

## Administration and operations

The root account uses authenticator MFA in production. Configure TLS SMTP before inviting members, assign application scopes by role, and configure each application's model allowlist and budget. Monitor readiness, error codes, trace IDs, and audit metadata without logging business payloads or secrets.

## Backup and restore

Keep protected database dumps off the server and test restoration into a disposable database. Preserve the matching encryption key; a dump alone cannot recover encrypted secrets.

Before upgrading, retain a consistent code version, lock files, configuration, and backup. Afterward, check login, readiness, catalogs, and scoped operations using synthetic data. Recover through a tested rollback procedure rather than automatically deleting tables.

[Hub backup and rollback](https://github.com/ardanayatraa/mcp-hub/blob/main/docs/BACKUP.md) · [Laravel maintenance](../laravel/upgrade.md)
