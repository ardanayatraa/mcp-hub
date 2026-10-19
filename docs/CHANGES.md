# What changed after 1.0

## JavaScript edition (`mcp-js` branch)

- **One Nuxt app.** `hub/` serves the admin UI (Nuxt pages and layout, rendered in the
  browser), the admin API, `/mcp` and `/chat/v1/*`. The Python edition (FastAPI + Vue) is
  on the `mcp-py` branch. Both use the same API, schema and revision ids.
- **No Python needed to start.** `npm run migrate` creates an empty SQLite or PostgreSQL
  database (and still upgrades older ones); `npm run bootstrap` creates the first admin.
  The container does both on start (`HUB_AUTO_MIGRATE=true`).
- **Contract apps sync.** Apps that publish an ordinary manifest (no `tool_key` on each
  route) now sync; only source-managed apps name their tools. Output string fields get a
  200-character limit even with an enum. The manifest hash now matches the Python edition.
- The Node SDK for app servers moved to `sdk/` (`@mcp-hub/backend-sdk`).
- Local development runs on port 3000; allowed hosts, origins and the MCP URL default to it.

## Bearer tokens everywhere

- **The Hub calls apps with `Authorization: Bearer <token>` only.** `X-API-Key` is gone.
  Existing apps keep their saved secret: the upgrade (migration `f3a8d2c6b1e4`) switches
  every connector to bearer, so only the app has to read the other header. In Laravel,
  replace `$request->header('X-API-Key')` with `$request->bearerToken()`; the Laravel guide
  now uses `VerifyHubToken` and `MCP_HUB_APP_TOKEN`.
- AI clients already used `Authorization: Bearer <client key>` for the MCP endpoint; nothing
  changes for them.

## Security hardening (OWASP API Security Top 10 2023, ASVS)

- **One-time user assertions.** Every request the Hub sends an app, retries included,
  carries a fresh `X-Hub-Assertion` with a random `jti`. Apps accept each `jti` once, so a
  captured header cannot be replayed (API2). The Laravel guide's `HubToken` does this.
- **Laravel guide middleware** refuses plain HTTP in production (`MCP_HUB_REQUIRE_HTTPS`) and
  answers with `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` (API8).
- **HiReach adapter:** writes are denied by default (a model needs a Laravel policy or an
  explicit authorize rule, API3/API5); the only AI write today is a user updating their own
  billing profile; blast message writes are off; `Idempotency-Key` returns the first
  proposal instead of preparing another (API6); one-time assertions, HTTPS and no-store as above.

## Checklists for tools and skills

- **Connect wizard → Choose tools.** Every tool of the new app, grouped by data source, with a
  tick box. Reading tools start ticked; create, update and delete start unticked and are greyed
  out, with the reason, where the app's API offers no such route. Unticked tools are switched
  off; ticked write tools get a sample test (nothing reaches the app) and are published on
  **Activate app**.
- **App → Skills tab.** The ready-made skills and the app's own as a checklist; ticking a
  ready-made skill adds it. Skills that need an unavailable tool (for example memory while it
  is off) cannot be ticked.
- **Client keys.** On a read-only key, tools that change data cannot be ticked under **Only
  selected tools**.
- `POST /tools/{id}/test` accepts `fill_required: true` (sample mode, no `arguments`) to fill the
  required inputs itself; without it, missing inputs still fail as before.

## Tools page

- **All tools**: every tool (Hub tools, memory tools and each app's tools) in one table with
  search, filters by app, kind and status, sortable columns, 7-day calls and pages of 10 to
  100 rows.
- **Capabilities**: what this MCP can do right now, with the technical detail (report filter
  operators, totals, time buckets and limits; confirmation for writes; skills; memory; chat;
  switches; safety limits), how AI clients connect, and a per-app matrix. Backed by
  `GET /tools/capabilities`.

## Light and dark mode

- Light, Dark or System from the top bar or the account menu; the choice is remembered.

# What changed in 1.0

1.0 is the first stable release. The Hub now covers the whole path from an app's data to an
answer: reading, reporting and changing data (create, update, delete), an AI chat any app can
embed, and the controls to decide what the AI may use. Everything below is covered by the test
suite and was exercised end to end against a Laravel app built from the in-app guide.

## Highlights

- **Create, update and delete.** Write routes return proposals; the signed-in user confirms
  each change in the app before it is applied. The in-app Laravel guide now builds the full
  set: list, get, prepare create/update/delete, a `hub_proposals` table, a confirm page and
  JSON routes, and a feature test for every path.
- **Hub chat.** Apps call `/chat/v1/turn` from their server and stream the answer (text, tool
  progress, change proposals) into their own chat window. The Hub runs the model with the
  app's tools and rules and stores no conversation.
- **Any model.** Claude by default (Opus 5.5, with server-side fallback on Opus and Sonnet), or
  any OpenAI-compatible provider added under **AI providers** (OpenAI, OpenRouter, Groq,
  DeepSeek, Mistral, Gemini, Together, Fireworks, xAI, Cerebras, Azure, Ollama, LM Studio, a
  company gateway). Keys are encrypted; model lists load by themselves.
- **Tool switches.** Every tool of every app has an on/off switch; off hides it from every
  client key and the chat and refuses calls.
- **Skills and memory.** Reusable instructions served as MCP prompts and chat commands, and
  opt-in per-user memory, encrypted and never visible to admins.
- **Readable tools.** `shop.orders.count` reads "Count orders" everywhere, with an icon for
  what it does, links to its page, and 7-day usage (calls, success rate, response time).
- **Documentation in the app.** A User guide and a Laravel guide with a downloadable
  starter kit.

## Fixes

- Generated "get one" tools (routes such as `GET /orders/{ref}`) now pass their sample test
  and publish: the test fills required inputs and never samples more rows than the route returns.
- Generated tool titles read naturally ("Create an order", "List blast messages").
- Names that point at credentials or one person (`otp`, `pin`, `cvv`, `msisdn`, card and
  account numbers, KTP, NPWP, passport) are always hidden from the AI.
- A model list that was fetched is still shown when the database is too busy to cache it.

## Upgrading from 0.2

Back up the database, then run `uv run --frozen alembic upgrade head` (head `e5b1c3d7f902`).
The migrations only add tables (skills, memory, tool switches, chat settings, model providers)
and widen one column; published tools keep working. To use the chat, set `ANTHROPIC_API_KEY`
or add a provider under **AI providers**. Details: [BACKUP.md](BACKUP.md).

# What changed in 0.2

0.2 simplifies the Hub around one goal: connecting an app, choosing what AI may read, and
getting answers (including reports) out of it should take minutes and no MCP knowledge.
The security model is unchanged or stronger.

## Audit findings in 0.1

| Area | Problem |
|---|---|
| Scope | 9 of 24 tables and about 15 modules were Phase 2 placeholders (approvals, jobs, OpenAPI import, MCP profiles, skill assignment). Their UI pages only showed `NOT_IN_PHASE` errors. |
| Tool workflow | Six steps for one read tool (create, test, approve, publish, plus immutable revisions). The builder required hand-editing JSON schemas, pagination and error mappings. Approval was the same admin clicking twice. |
| AI usefulness | Admin-written descriptions were discarded: every tool reached the model as "Read-only data tool X". There was no reporting tool. `process_dataset` needed a source-signed digest of the dataset, so AI clients could not use it. |
| MCP runtime | Each published tool was compiled into Python source with `exec()` and registered in-process, then its schema was overridden anyway. Every publish/disable had to resync that registry. |
| Contract changes | The manifest hash covered all modules, so any change to one module disabled every data source of the app and invalidated every tool. |
| Field policy | Admins could tighten a field but never relax it back to the developer default. |
| Bugs | A public-aggregate tool failed whenever a delegation header was sent. On SQLite, all requests shared one connection, so parallel requests (the admin UI makes them) returned spurious 401/500s and could crash the process. Sensitive-name detection missed variants such as `owner_email`. |
| UI | 13 pages with dense, inconsistent screens and placeholder buttons; no guided setup, no data preview, no way to see what the AI receives. |

## What 0.2 does

- **Default reporting tool `run_report`** plus `list_data_sources`. Pages through any allowed data source; filters, groups (with time buckets) and computes count/sum/avg/min/max; returns rows, totals, a one-line summary, a chart hint and an honest coverage flag. "Totals only" fields are aggregated but never shown, and are hidden for groups smaller than 3. Unsafe values are masked, not leaked.
- **Templates instead of a builder**: Read records, Report (a saved `run_report`) and Create/Update/Delete. Defaults come from the app's contract; parameters and fields are chosen with checkboxes; descriptions reach the AI.
- **Simple lifecycle**: draft, then a passing test, then publish; disable and delete are available. Tests run the real pipeline on generated sample data (or live data where safe) and show the exact result and the exact tool definition the AI receives. Write tools only ever dry-run in the console.
- **Optional writes** behind four independent gates: a declared write route, the operation enabled on the data source, a write-permitted client key, and user delegation. The app decides, and may return a proposal for the user to confirm.
- **Access management**: client keys with read or read+write, an optional tool allowlist, expiry and last-used time; team members with roles and app assignments.
- **Database-driven MCP runtime**: `tools/list` and `tools/call` read the database per request. There is no `exec()` and nothing to resync.
- **Per-module contract tracking**: only a changed data source goes back to review. Unchanged tools stay live, including across the upgrade.
- **Redesigned admin UI**: Overview with a setup checklist and a client-config snippet, Apps (connect wizard, data sources, connection, history), Tools (templates, test console, report playground), Access, Activity, Settings. Light and dark themes, works on mobile.
- **Fixes**: SQLite connection pooling, public-aggregate delegation handling, word-based sensitive-name detection, field policies that can be relaxed back to the developer level, validation errors that name the field and rule (never the value).

## Removed

| Removed | Why / replacement |
|---|---|
| `process_dataset` MCP tool (push mode) | Unusable by AI clients (needed a source-signed dataset digest). Replaced by `run_report`, which pulls through the same reviewed routes and delegation. |
| `list_capabilities` | Renamed `list_data_sources`; it no longer takes a redundant `app_key`. |
| Approve step, `/tools/{id}/approve`, `/tools/{id}/revise`, `/tools/dry-run` | Test then publish. Editing a tool creates the next patch version in place. |
| `/connectors/{id}/revoke`, `/connectors/{id}/resume` | Use pause/activate, rotate, or archive. |
| `/users/{id}/scopes` | `PATCH /users/{id}` (role, active, apps). |
| Phase 2 placeholder routes and pages: approvals, jobs, OpenAPI import, MCP profiles, skills | They never worked. Writes are now real (with gates); the rest can come back when built. |

## Upgrade steps

1. Back up the database (and export configuration from the old UI if you like).
2. `cd backend && uv sync --frozen && uv run --frozen alembic upgrade head`.
3. Start the Hub. Existing published tools are served unchanged, with the same names, schemas and response format.
4. Scripts that used the admin API: drop the `/approve` call (test, then publish) and read test safety checks from `checks` (the old `cases` key is still returned).

For the Laravel integration, see its [README](../integrations/laravel/README.md#upgrading-the-hub-to-02).
