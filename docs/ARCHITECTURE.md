# Architecture

```text
 Admin UI (Vue 3)  ── cookie + CSRF ──►  FastAPI  /api/admin/v1  ─┐
                                                                 ├─►  Hub database (PostgreSQL; SQLite for dev)
 AI client / app gateway ── bearer key ──►  MCP SDK app  /mcp  ──┘     config, encrypted secrets, audit
                                                │
                                   reviewed route + app credential + user assertion
                                                ▼
                                   Connected app (owns data and permissions)
```

One process serves both: `app.main:create_app` registers the admin routers, then mounts the
official MCP SDK Streamable HTTP app at `/`, so `/mcp` never shadows `/api`, `/health` or
`/ready`. Startup refuses a migrated database whose Alembic revision is older than the code.

## Backend layout

| Package | Responsibility |
|---|---|
| `app/api/v1` | Thin admin routers: `auth`, `connectors` (apps), `modules` (data sources), `tools`, `access` (client keys, users), `activity` (dashboard, audit), `system` (info, backup). `configuration.py` holds the strict request models. |
| `app/services` | Admin workflows: connecting apps, building/testing/publishing tools, dashboard numbers, backup/restore. |
| `app/mcp/server.py` | `HubMCPServer`: `tools/list` and `tools/call` read the database per request, scoped to the calling key. One audit event per call. |
| `app/tools` | `definitions` (templates, fingerprint), `runtime` (read/report/write pipelines and the source client), `report_engine` (filtering, grouping, metrics, summary), `catalog` (built-ins and visible tools), `schema_tools` (schema validation). |
| `app/connectors` | Manifest validation, reviewed-route policy, discovery, the HTTP adapter (SSRF checks, IP pinning, no redirects, streamed size caps, GET-only retries) and auth headers. |
| `app/capabilities` | Data source operations and field policy. |
| `app/privacy` | Output projection, PII detectors and response metadata checks. |
| `app/security` | Admin sessions/MFA, roles, client keys, crypto, audit, rate and concurrency limits. |
| `app/persistence` | SQLAlchemy models, sessions and Alembic migrations. |

## How a tool call runs

1. The SDK verifies the bearer key (`mcp:tools` scope) and Origin/Host.
2. `HubMCPServer.call_tool` reloads the key and app, rejects personal data and identity/routing arguments, and checks the key's tool allowlist and write permission.
3. The runtime reloads the tool, the app connector (active, circuit closed), the data source (operation enabled) and the reviewed route. It then compares the tool's fingerprint (configuration plus that module's contract hash) and validates the arguments against both the tool's and the route's schemas.
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

Vue 3, TypeScript, Tailwind and Pinia, with no UI library. Six pages (Overview, Apps, Tools,
Access, Activity, Settings) plus guided flows: the connect-app wizard, the new-tool
templates and the report playground. `src/services/hub.ts` is the typed API client;
`src/components` holds the reusable parts (report builder, parameter editor, schema form,
result view). Theme tokens are CSS variables with a dark variant that follows the OS.

## Operational limits

- Rate limits and concurrency budgets are in memory: run one worker process.
- SQLite is for development (file databases use a connection pool and a 15 s lock wait). Use PostgreSQL in production; it is enforced there.
- `run_report` reads at most `REPORT_MAX_RECORDS` records within `REPORT_TIMEOUT_SECONDS`, page by page. For larger data, give the app an aggregate route.
