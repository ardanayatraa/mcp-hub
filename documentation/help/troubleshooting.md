# Troubleshooting

Start with `php artisan mcp-hub:status` and `php artisan mcp-hub:doctor --online`. Record the error code, time, and trace ID; exclude secrets and business payloads.

| Symptom | Check | Action |
|---|---|---|
| Doctor or health returns 503 | Is security metadata present? | Review the dry run and execute package migrations |
| Empty tool catalog | Are the registry and grants enabled? | Implement the resolver and policies, review resources, then sync |
| Source catalog unavailable | Is the manifest valid and reachable? | Fix the source; failed refreshes do not use stale grants |
| Source returns 401 | Do app tokens match on both sides? | Review provisioning without printing tokens |
| User operation returns 403 | Are delegation, actor, policy, and profile valid? | Check current account, tenant, and permissions |
| Settings or chat returns 403 | Are host Gates and guard available? | Define Gates using host permissions |
| Web mutation returns 419 | Do the session and CSRF token belong to the same application? | Fix session and origin handling; do not disable CSRF |
| Pairing interrupted | Was the encrypted proof saved? | Run `connect --resume` |
| Replacement has no effect | Do old environment values override the bundle? | Review pinned configuration through the operator |
| Models missing or denied | Are allowlists and budgets configured? | Configure application model access |
| Proposal conflicts or expires | Did the record version, policy, or expiry change? | Prepare a new proposal and request approval again |
| Export remains pending or fails | Are the worker, queue, and storage ready? | Fix the worker; crashed jobs need a new request and key |
| Download returns 409 | Did the data or grant snapshot change? | Create a new export |
| Download returns 410 | Has the TTL expired? | Create a new export |
| Composer conflict | Are PHP, framework, and Guzzle constraints compatible? | Review solver output and the lock file without security or platform bypasses. Package 1.0.0 needs Guzzle 7; on a fresh Laravel 13 (Guzzle 8) require 1.0.1 or later |
| Pairing works, `doctor --online` shows `operation: FAIL` | Is the package 1.0.0? | 1.0.0 sends an `Origin` the Hub's `/mcp` rejects. Update the package, or add the Laravel source URL to the Hub's `ALLOWED_ORIGINS` |
| Chat says it cannot create or change data | Does the message ask for the change? Does the client key allow writes? | Ask with a verb such as "buatkan", "ubah", "batalkan", "create"; turn on write for the app's key under Access |
| App login returns 429 after Hub activity | Does a host route use plain `throttle:N,M`? | Package 1.0.1 uses its own counters; on 1.0.0 give host throttles a named prefix |

## Distinguish URLs and credentials

`MCP_HUB_URL` points to the Hub's `/mcp` endpoint. `MCP_HUB_BASE_URL` points to the source. The client key authenticates Laravel to the Hub; the app token authenticates the Hub to Laravel. The delegation secret signs actor context and is not a general API token.

## Worker checks

Web and queue workers must use the same release, configuration, APP_KEY, database, and private filesystem. Restart workers through the host's deployment procedure after changes. Refresh cached configuration through a controlled deployment process.

## Issue reports

Include package and server versions, PHP and Laravel versions, the error code, and reproduction steps using synthetic data. Identify whether the case comes from a unit test, simulation, staging, or production. Remove tokens, codes, user identities, internal addresses, and business records from public reports.
