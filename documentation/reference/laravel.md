# Artisan and configuration

## Commands

| Command | Purpose |
|---|---|
| `mcp-hub:install --dry-run --migrate` | Preview package configuration and migrations |
| `mcp-hub:install --migrate` | Create missing configuration and SQL metadata |
| `mcp-hub:connect --hub=...` | Pair through the hidden prompt |
| `mcp-hub:connect --resume` | Resume the saved proof |
| `mcp-hub:connect --hub=... --replace` | Install an administrator-issued replacement |
| `mcp-hub:connect --import-env` | Import a provisioned connection |
| `mcp-hub:status` | Inspect status metadata without secrets |
| `mcp-hub:doctor --online` | Diagnose local state and Hub connectivity |
| `mcp-hub:sync` | Sync the contract |
| `mcp-hub:disconnect` | Disable locally and request remote revocation |
| `mcp-hub:discover --schema` | Discover candidates from metadata |
| `make:mcp-resource orders --model=...` | Generate disabled definitions and policies |
| `mcp-hub:prune --days=30` | Clean up metadata and artifacts |

Use `php artisan help <command>` for the full options of the installed version.

## Environment variables

| Variable | Meaning |
|---|---|
| `MCP_HUB_APP_KEY` | Application identity |
| `MCP_HUB_ENVIRONMENT` | Connection environment |
| `MCP_HUB_BASE_URL` | Application source URL |
| `MCP_HUB_URL` | Hub `/mcp` endpoint |
| `MCP_HUB_CLIENT_KEY` | Laravel → Hub authentication |
| `MCP_HUB_APP_TOKEN` | Hub → Laravel authentication |
| `MCP_HUB_DELEGATION_SECRET` | Actor context signing secret |
| `MCP_HUB_ENABLED` | Connection override |
| `MCP_HUB_TIMEOUT` | General request timeout; default 12 seconds |
| `MCP_HUB_CHAT_TIMEOUT` | Chat SDK timeout; default 120 seconds |

Configured environment values take precedence over the saved bundle. Never print the environment for troubleshooting; diagnostics must hide secrets.

## Configuration keys

| Key | Default or behavior |
|---|---|
| `models` | Empty |
| `actor_resolver` | Resolver that denies access |
| `routes.enabled`, `routes.prefix` | `true`, `api/ai/v1` |
| `web.enabled`, `web.prefix` | `true`, `mcp-hub`; still protected by Gates |
| `commands.enabled`, `commands.ttl` | `false`, 300 seconds |
| `exports.enabled`, `exports.ttl` | `false`, 600 seconds |
| `record_references` | `opaque` |
| `maintenance.scheduled_prune` | `true`; the host scheduler must run |

Use scalars, arrays, and class strings for `config:cache` compatibility. See the [version 1.0.0 configuration](https://github.com/ardanayatraa/laravel-mcp-hub/blob/v1.0.0/config/mcp-hub.php).
