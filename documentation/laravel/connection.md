# Pairing and configuration

Pairing binds an application, environment, and source URL to the Hub. Use a single-use code from an administrator with access to that application.

## Application identity

```dotenv
MCP_HUB_APP_KEY=your_app
MCP_HUB_ENVIRONMENT=production
MCP_HUB_BASE_URL=https://app.example.com
```

Match the source URL registered in the Hub. The environment and source URL are part of the proposal, record-reference, and artifact bindings. Operator-managed environment values take precedence over the saved connection bundle.

## Pair using the hidden prompt

```bash
php artisan mcp-hub:connect --hub=https://hub.example.com
php artisan mcp-hub:status
php artisan mcp-hub:doctor --online
```

Enter the code at the hidden prompt. The `--code` option is available for controlled automation, but the prompt avoids placing the code in shell history. Do not put codes or proofs in URLs, logs, or screenshots.

The installation proof is encrypted before the claim completes. Activation follows health and contract validation. Keep `storage/app/mcp-hub` private, writable by the application, and persistent across deployments.

## Recovery

| Situation | Action |
|---|---|
| Pairing response was lost | `php artisan mcp-hub:connect --resume` |
| Code expired or claim cannot be recovered | Ask an authorized administrator for a replacement |
| Replacement is available | Connect using `--hub=... --replace` |
| Resources or contract changed | `php artisan mcp-hub:sync` |
| Connection must be revoked | `php artisan mcp-hub:disconnect` |

Replacement revokes old credentials, preserves profile and tool restrictions, and does not grant write scope. Disconnect disables the local connection first; remote revocation stays pending until the Hub acknowledges it.

## Import an existing connection

For already provisioned credentials, configure `MCP_HUB_URL`, `MCP_HUB_CLIENT_KEY`, `MCP_HUB_APP_TOKEN`, and `MCP_HUB_DELEGATION_SECRET` in addition to the identity settings above.

```bash
php artisan mcp-hub:connect --import-env --dry-run
php artisan mcp-hub:connect --import-env
```

The app token and delegation secret require at least 32 random characters. The connection copy is stored encrypted at `storage/app/mcp-hub/connection.enc` using `APP_KEY`.

`MCP_HUB_URL` points to the Hub's `/mcp` endpoint; `MCP_HUB_BASE_URL` points to the Laravel source. HTTP is permitted only for loopback in local/testing environments. Use HTTPS in production.

## Network requirements

The Hub calls `MCP_HUB_BASE_URL`, so the Hub's egress allowlist (`EGRESS_ALLOWED_HOSTS`, `EGRESS_ALLOWED_PORTS`) must permit that host and port. Laravel's calls to the Hub are server-to-server: since package 1.0.1 they send no `Origin` header, and the Hub's `ALLOWED_ORIGINS` does not need the Laravel URL. Package 1.0.0 sent its source URL as `Origin`, which the Hub's `/mcp` endpoint rejects unless it is listed; with 1.0.0, pairing succeeds but `php artisan mcp-hub:doctor --online` reports `operation: FAIL`. Upgrade with `composer update ardanayatraa/laravel-mcp-hub`, or add the source URL to `ALLOWED_ORIGINS`.
