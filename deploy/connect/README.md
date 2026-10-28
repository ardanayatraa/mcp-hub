# Connect overlay: UI + API behind one door, and an `.env` check

An optional overlay for the production `compose.yml` (see `docs/DEPLOY.md`). It adds services and
changes nothing that already works: `compose.yml`, `.env` and the Caddyfile stay as they are until you
choose to switch.

| Service | What it does |
|---|---|
| `envcheck` | Runs before the backend. Stops the stack with a plain message when `.env` is wrong. |
| `edge` | Nginx on `127.0.0.1:8200`: serves `./frontend` and proxies `/api`, `/mcp`, `/chat`, `/gateway`, `/health`, `/ready` to the backend **by name** (re-resolved every 10 s, so a recreated backend never leaves it pointing at an old IP). |

The backend also trusts `X-Forwarded-For` from the edge's fixed address (`HUB_EDGE_IP`, default
`172.31.250.10` inside the existing `172.31.250.0/24` network) instead of from the gateway.

## Use (on the server, in `/opt/mcp-hub`)

```bash
F="-f compose.yml -f src/deploy/connect/compose.connect.yml"
docker compose $F run --rm envcheck        # report only; changes nothing
docker compose $F up -d                    # start; envcheck gates the backend
```

Then point Caddy at the edge (`caddy.snippet`) and `sudo systemctl reload caddy`. Until you do, Caddy
keeps serving as before and the edge is simply an extra local port you can test with
`curl http://127.0.0.1:8200/ready`.

## What `envcheck` checks

Mirrors `backend/app/config.py`: keys present and not the example values, a valid Fernet key, a
32+ character session key, `COOKIE_SECURE=true` and https in production, egress hosts set, and that the
Hub's own domain is in `ALLOWED_HOSTS`, `ALLOWED_ORIGINS`, `MCP_PUBLIC_URL`, `MCP_ISSUER_URL` and
`ADMIN_CONSOLE_URL`. Warnings (MFA off, half-configured SMTP) never block.

## Repairing `.env`

```bash
ENVCHECK_FIX=1 docker compose $F run --rm envcheck
ENVCHECK_DOMAIN=mcp.example.com ENVCHECK_FIX=1 docker compose $F run --rm envcheck   # new domain
docker compose $F up -d        # again: containers read .env only when they are created
```

- A timestamped backup (`.env.bak-<time>`) is written first.
- Only inconsistent lines change. A domain is **added** to `ALLOWED_HOSTS` / `ALLOWED_ORIGINS`, never
  swapped in, so the old domain keeps working. Every other line, comment and order is left as it is.
- Secrets (`POSTGRES_PASSWORD`, `SECRET_ENCRYPTION_KEY`, `SESSION_SIGNING_KEY`, passwords) are
  reported when wrong, never generated or replaced: replacing the encryption key would make stored
  keys unreadable.

## Roll back

Remove `-f src/deploy/connect/compose.connect.yml` from the command and restore the Caddy block from
`/etc/caddy/Caddyfile.bak-*`. Nothing else was modified.
