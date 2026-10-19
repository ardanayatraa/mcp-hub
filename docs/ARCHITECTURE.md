# Architecture

This is the JavaScript edition (`mcp-js` branch). The Python edition (`mcp-py`) has the same
API, schema and behaviour with FastAPI, SQLAlchemy and Alembic.

```text
 Admin UI (Nuxt pages) ── cookie + CSRF ──►  /api/admin/v1  ─┐
                                                             ├─►  Hub database (PostgreSQL; SQLite for dev)
 AI client / app gateway ── bearer key ──►  /mcp, /chat/v1  ─┘     config, encrypted secrets, audit
                                                │
                                   reviewed route + app credential + user assertion
                                                ▼
                                   Connected app (owns data and permissions)
```

One Nuxt process serves everything. The admin UI renders in the browser (`ssr: false`).
Nitro routes in `hub/server/routes` and `hub/server/api` hand `/mcp`, `/chat/v1/*`,
`/api/admin/v1/*` and `/ready` to one Node request handler (`server/core/handler.js`).
`server/utils/hub.ts` opens the database on first use and refuses to serve (`503
NOT_READY`) until its schema revision is current.

## Server layout (`hub/server/core`)

| Module | Responsibility |
|---|---|
| `handler.js` | Security headers, Host/Origin checks and routing to the modules below. |
| `auth.js`, `security.js` | Admin sessions, CSRF, MFA (TOTP), Argon2 passwords, Fernet secrets, rate limits. |
| `admin-*.js`, `backup.js`, `skills.js`, `chat-settings.js` | Admin API: apps, data sources, tools, client keys, users, activity, backup/restore, skills, chat and providers. |
| `mcp.js` | The MCP endpoint (official TypeScript SDK, stateless JSON responses): `tools/list` and `prompts/list` per calling key. |
| `catalog.js` | Resolves a client key and builds the tools it may see from the database, dropping tools whose fingerprint no longer matches. |
| `runtime.js`, `report.js`, `memory.js` | Tool calls: read, `run_report` (filter, group, metrics, summary), writes as proposals, and user memory. One audit event per call. |
| `manifest.js`, `sync.js` | Manifest validation (same normalization and hash as Python) and contract sync. |
| `source-http.js` | Calls to apps: SSRF checks, IP pinning, no redirects, size and time caps. |
| `privacy.js` | Output projection and PII detectors. |
| `chat.js` | The chat API: model calls with the app's tools, streamed to the app. |
| `database.js`, `migrate.js`, `schema.sqlite.json`, `bootstrap.js` | Database access, schema creation and upgrades, first admin. |

## How a tool call runs

1. `mcp.js` checks Origin/Host and resolves the bearer key (`mcp:tools` scope).
2. The call reloads the key and app, rejects personal data and identity/routing arguments, and checks the key's tool allowlist and write permission.
3. The runtime reloads the tool, the app connector (active), the data source (operation enabled) and the reviewed route. It then compares the tool's fingerprint (configuration plus that module's contract hash) and validates the arguments against both the tool's and the route's schemas.
4. It verifies `X-Hub-Delegation`, signs a 60-second `X-Hub-Assertion` for the app, and calls the fixed route (pinned IP, no redirects, size and time caps).
5. Read: check the envelope and tenant, project to allowed fields, run the PII guard, and validate against both output schemas. Report: page through the list route, then mask unsafe values, filter, group and summarize. Write: no retry; the receipt is checked for tenant and personal data.
6. One audit row (action, actor, tool, result, error code, duration, retries; never payloads).

Tool exposure is computed from the database on every request, so publishing, disabling,
pausing or revoking has no cache or in-process registry to update.

## Data model

| Table | Holds |
|---|---|
| `applications`, `connectors`, `connector_secrets`, `connector_health_checks`, `contract_snapshots` | Connected apps, encrypted credentials, health and manifest history. |
| `module_definitions`, `module_settings`, `field_policies` | Data sources, enabled operations, report route, and field visibility. |
| `rest_tool_mappings`, `tool_definitions`, `tool_test_runs` | Tools: fixed route, template, schemas, report spec, status, fingerprint, test results. |
| `service_identities` | Client keys: token hash, app, scopes (`mcp:tools`, `tools:write`), tool allowlist, expiry, last use. |
| `admin_users`, `admin_sessions`, `admin_application_scopes`, `mfa_challenges` | Admin identities and access. |
| `audit_events` | Metadata-only activity log. |

Fingerprints: `content_hash` covers the tool configuration and its module's contract hash.
Tests record the fingerprint they ran against; publishing requires a passing test for the
current fingerprint. Contract changes are detected per module, so changing one data
source never invalidates tools of another.

## Frontend

Vue 3, TypeScript, Tailwind and Pinia in Nuxt, with no UI library. Pages live in
`hub/app/pages` (Overview, Apps, Tools, Access, AI providers, Activity, Settings, guides),
the sidebar shell in `layouts/default.vue`, and the sign-in and role checks in
`middleware/session.global.ts` (page rules come from `definePageMeta`). Guided flows: the
connect-app wizard, the new-tool templates and the report playground. `app/services/hub.ts`
is the typed API client; `app/components` holds the reusable parts (report builder,
parameter editor, schema form, result view). Theme tokens are CSS variables with a dark
variant that follows the OS.

## Operational limits

- Rate limits are in memory: run one process.
- SQLite is for development (one connection, writes serialized, 15 s lock wait). Use PostgreSQL in production; it is enforced there.
- `run_report` reads at most `REPORT_MAX_RECORDS` records within `REPORT_TIMEOUT_SECONDS`, page by page. For larger data, give the app an aggregate route.
