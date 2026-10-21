# Admin API and MCP endpoint

## Admin API

Base path `/api/admin/v1`. Responses are `{"success": true, "data": …}` or
`{"success": false, "error": {"code", "message"}}`. Messages never echo submitted
secrets or record values; validation errors name the field, not the value.

Authentication is a session cookie from `POST /auth/login`. Every request except GET needs
the `X-CSRF-Token` header returned by login and `GET /auth/me`.

Roles: `super_admin` (the initial root, including team access and restore), `hub_admin`
(all apps and Hub settings except team access and restore), `app_admin` (assigned apps:
configure, test, publish, issue keys), and `auditor` (read-only on assigned apps).

### Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | `{email, password}`. Returns `{user, csrf_token}`, or an MFA challenge/enrollment. |
| POST | `/auth/activation-email` | `{token, email}` sends a six-digit code to the real email; returns `challenge_token`. |
| POST | `/auth/activation-code` | `{token, challenge_token, code}` verifies the email and returns a short-lived `proof_token`. |
| POST | `/auth/activate` | `{token, proof_token, password}` sets the verified email and password. Single use; does not sign in. |
| POST | `/auth/mfa` | `{mfa_token, code}`; single use, replay-protected. |
| POST | `/auth/logout` | |
| GET | `/auth/me` | Current admin and CSRF token. |

Root can create a Team user with `POST /users` and `{role, app_ids}`. The response shows
`activation_url` once; no email is collected or sent at creation. Root shares the link
privately. The recipient enters their email, verifies the code, and sets a password. Root can issue
a replacement link with `POST /users/{id}/resend-invite`; it invalidates the previous
link and activation challenges. Password-based creation is accepted only for non-production
compatibility and requires `email`; production requires activation.
After activation, invited admins sign in with email and password without another email code.
Root sign-in still requires an authenticator in production.

### Apps (connectors)

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/connectors` | List with health and counts; create (`name, app_key, environment, base_url, secret`, optional `delegation_secret`, `manifest_path`, `health_path`, `timeout_ms`, `tls_verify`). A blank delegation secret is generated and returned once. `secret` is the bearer token the Hub sends as `Authorization: Bearer <token>`; `auth_type` may be left out and only `bearer` is accepted. |
| GET, PATCH, DELETE | `/connectors/{id}` | Detail with health and contract history; edit settings (changing the address returns the app to setup); delete only draft or archived apps. |
| POST | `/connectors/{id}/test` | Health check: `{status, latency_ms, error_category, hint}`. |
| POST | `/connectors/{id}/discover` | Sync the manifest; returns each data source with `change` (`new`, `changed`, `unchanged`, `removed`). |
| POST | `/connectors/{id}/activate` | Needs a passing test and a synced contract. Also resumes a paused app. |
| POST | `/connectors/{id}/pause` | Blocks every tool of the app immediately. |
| POST | `/connectors/{id}/rotate` | `{secret?, delegation_secret?}`: replace the app's bearer token, its delegation secret, or both (at least one). The detail and list views report `secret_updated_at`; secrets are never returned. |
| POST | `/connectors/{id}/archive` | Permanent: revokes credentials and client keys, archives tools. |

### Data sources (modules)

Connectors also accept `connector_type: source_managed` on create/update. For this mode,
models and tool definitions follow the authenticated application's saved grants automatically
on each MCP list/call and when admin connector/module/tool lists are opened. Current
source-managed catalogs and counts omit disabled/removed model and tool grants; metadata
history is retained. Refresh contacts only sources inside the administrator's application
scope. A failed/invalid source refresh returns an error, not a stale catalog. Connector
metadata stays accessible for repair and includes `source_sync_error`; its current
catalog counts are withheld and the UI shows unavailable counts instead of stale grants.
Module settings and manual tool mutations return `POLICY_LOCKED`.
See [the source-managed contract](CONNECTOR_CONTRACT.md#permissions-managed-by-the-application).

| Method | Path | Notes |
|---|---|---|
| GET | `/modules?connector_id=` | Fields with visibility, developer limit and type; reviewed routes; report route. |
| PATCH | `/modules/{id}/settings` | `{enabled, operations, fields: [{field_path, classification}], report_endpoint}`. Operations are limited to what the manifest supports and declares routes for; field changes cannot exceed the developer limit. |

### Tools

| Method | Path | Notes |
|---|---|---|
| GET | `/tools` | Custom tools with status, `stale`, `tested`, last test and the exact MCP definition. `?include_archived=true`. |
| GET | `/tools/templates` | `read`, `report`, `create`, `update`, `delete`. |
| GET | `/tools/capabilities` | What the Hub can do for the apps you may see: `version`, `protocol` (endpoint, transport, methods, auth), `summary` (apps, live tools by kind, skills, memory, chat, keys), `report` (filter operators, metrics, intervals, limits), `limits`, an `apps` matrix and 7-day `usage` by tool key or name. Scoped admins see only their apps and their calls. |
| GET | `/tools/builtins` | Definitions of `list_data_sources`, `run_report` and the memory tools (`requires: "memory"`). |
| POST | `/tools/generate` | `{connector_id, publish?}`. Creates tools for every published route of the app's allowed data sources; returns `{created, skipped, published}`. |
| GET | `/tools/agent-view` | `?connector_id=&key_id=` or `&write=true`. What `tools/list` and `prompts/list` return for that key, plus the server instructions. |
| POST | `/tools/builtins/{name}/test` | Preview a built-in for one app: `{connector_id, mode: sample\|live, arguments, delegation?}`. |
| POST | `/tools` | Create a draft: `{connector_id, module_key, template, tool_key, title?, description?}` plus, for read/write, `method`, `path_template`, `input_schema?`, `allow_fields?`; for report, `report: {group_by, time_bucket, metrics, filters, sort, limit, columns, allow_filters}`. Omitted values default from the source contract. |
| GET, PATCH, DELETE | `/tools/{id}` | Edit (a live tool goes back to draft); delete when not live. |
| POST | `/tools/{id}/test` | `{mode: sample\|live, arguments, tenant_id?, sample?, delegation?}`; in sample mode, `fill_required: true` without `arguments` fills the required inputs. Returns `{passed, preview, checks, request?, error_code, error_message, trace_id}`. |
| POST | `/tools/{id}/publish` | Needs a passing test of the current configuration, an active app and the operation enabled. |
| POST | `/tools/{id}/disable` | |

### Skills

| Method | Path | Description |
|---|---|---|
| GET | `/skills` | Skills, optionally `?connector_id=`. Each lists `unavailable_tools` that keep it hidden from clients. |
| GET | `/skills/templates` | Starter skills. |
| POST | `/skills` | `{connector_id, key, title, description, instructions, arguments: [{name, description, required}], tools, enabled}`. |
| PATCH, DELETE | `/skills/{id}` | |
| POST | `/skills/preview` | `{connector_id, skill, arguments}` returns the rendered `text`. |

### Memory

| Method | Path | Description |
|---|---|---|
| GET | `/connectors/{id}/memory` | Settings and counts (`users`, `notes`, `profile_entries`). Never content. |
| PATCH | `/connectors/{id}/memory` | `{enabled?, retention_days?: 7\|30\|90\|180\|365, max_notes?: 5..200}`. |
| DELETE | `/connectors/{id}/memory` | Deletes every memory of the app. |

### AI providers

Claude and the OpenAI-compatible model providers the chat can use. Listing is open to every admin role; changes need super admin.

| Method | Path | Description |
|---|---|---|
| GET | `/model-providers` | `{builtin: [Claude, and the environment gateway when set], providers: [...]}`. Claude has `key_source` (`hub`, `environment` or `null`) and `api_key_hint`. Each provider has `api_key_set` and `api_key_hint` (last 4 characters), never the key; `models` from the last test; `used_by` app names. |
| PUT | `/model-providers/anthropic/key` | `{api_key}`. Saves the Claude key encrypted; it wins over `ANTHROPIC_API_KEY` and applies without a restart. Returns the Claude entry, never the key. |
| DELETE | `/model-providers/anthropic/key` | Removes the saved Claude key; `ANTHROPIC_API_KEY` applies again when set. |
| GET | `/model-providers/presets` | OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Gemini, Together, Fireworks, xAI, Cerebras, Azure OpenAI, Ollama, LM Studio, other. |
| POST | `/model-providers` | `{key, name, base_url, auth_style?: bearer\|header\|none, auth_header?, api_key?, headers?, token_param?: max_tokens\|max_completion_tokens\|none, tool_schema?: full\|basic, streaming?, default_model?, enabled?}`. The key is stored encrypted. |
| PATCH | `/model-providers/{id}` | Same fields except `key`; `clear_api_key: true` removes the saved key. Changing the address or key resets the status to untested. |
| GET | `/model-providers/{key}/models?refresh=` | The models a chat can pick: `{models: [{id, label, hint?}], source: live\|cache\|builtin, fetched_at, default_model, error}`. `key` is `anthropic`, `openai_compatible` or a provider key. Claude lists active models that support adaptive thinking and effort (recommended ones first); other providers come from their `/models`. Fetched when missing or older than 6 hours, or with `refresh=true`; a failed fetch keeps the last list and explains why. |
| POST | `/model-providers/{id}/test` | Lists `/models` (or, without a list, sends a one-token chat to `default_model`) and stores `status`, `status_message`, `models`. |
| DELETE | `/model-providers/{id}` | 409 while an app's chat uses it. |

### Tool switches

| Method | Path | Description |
|---|---|---|
| GET | `/connectors/{id}/tool-switches` | Every tool the app's AI could be offered (`kind`: hub, memory, app) with `enabled`, `live` (a full key would see it before switches) and a `note` when it is not live. Also `total`, `off`, `reaching_ai`. |
| PUT | `/connectors/{id}/tool-switches` | `{tools: {name: true\|false}}`, 1 to 500 names known to the app. Off hides the tool from every key and the chat and refuses calls (`TOOL_DISABLED`). Audited as `tool.switch_on` / `tool.switch_off`. |

### Chat settings

| Method | Path | Description |
|---|---|---|
| GET | `/connectors/{id}/chat` | Settings plus `fallbacks` (server-side fallback active), `gateway_usage` (this month's gateway calls, errors and tokens, per model) and `options` (providers with `ready`, Claude models, efforts, limits). |
| PATCH | `/connectors/{id}/chat` | `{enabled?, provider?: anthropic\|openai_compatible\|<provider key>, model?, effort?: low\|medium\|high, instructions? (≤4000), welcome_message? (≤300), suggestions? (≤6 × 120), max_steps?: 1..12, daily_limit?: 0..5000, gateway_models?: ["provider/model" or "provider/*", ≤200] (empty: every model), monthly_token_limit?: 0 (none)..2e9}`. Text with personal data is refused. |
| GET | `/connectors/{id}/chat/gateway-models` | Every model the Hub can reach now (`{models: [{id, provider, name}]}`), to choose the app's allowed models. |
| POST | `/connectors/{id}/chat/try` | Streams a read-only answer (same events as `/chat/v1/turn`) as the admin, without a signed-in app user. |

### Access

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/service-identities` | Client keys. Create: `{name, app_key, environment, ttl_days, write, allowed_tools}`. The token is returned once and stored hashed. |
| PATCH | `/service-identities/{id}` | `{name?, write?, allowed_tools?}` (null means all tools). |
| POST | `/service-identities/{id}/revoke` | Immediate. |
| GET, POST | `/users` | Super admin only. Create: `{email, role, password, app_ids}`. |
| PATCH | `/users/{id}` | `{role?, is_active?, app_ids?}`. The last active super admin cannot be removed. |

### Activity and system

| Method | Path | Notes |
|---|---|---|
| GET | `/dashboard?period=24h\|7d\|30d` | Counts, success rate, p95 latency, top tools, recent events, setup checklist. |
| GET | `/executions` | Audit log. Filters: `trace_id, tool_key, app_key, result, kind=calls\|admin, period, from_time, to_time, before, limit`. |
| GET | `/system` | Version, MCP URL, limits and security posture (no secrets). |
| POST | `/operations/export` | Super admin. Configuration backup; secrets stay ciphertext. |
| POST | `/operations/import` | Super admin. Replaces exported tables after validating the whole document. |
| POST | `/operations/purge` | Super admin. Deletes activity and test records older than the retention period, and expired memories. |

## Chat endpoint

Called by the app's server, never by the browser: the client
key is secret. The Hub stores no conversation; the app sends the visible history on each turn.

- `Authorization: Bearer <client key>` (required)
- `X-Hub-Delegation: <token signed by the app>`: the signed-in user, for memory and user-scoped tools

| Method | Path | Description |
|---|---|---|
| GET | `/chat/v1/config` | `{enabled, app: {name}, welcome_message, suggestions, skills: [{key, title, description, arguments}], memory}`. Everything empty while the chat is off. |
| POST | `/chat/v1/turn` | `{message (≤4000), history?: [{role: user\|assistant, text}] (≤40), skill?, skill_arguments?, locale?, stream?: true}`. |

Refusals before any model call are plain JSON errors: `CHAT_DISABLED` (403), `PII_DETECTED` (422),
`RATE_LIMITED` / `DAILY_LIMIT` (429), `CHAT_NOT_CONFIGURED` (503), `PERMISSION_DENIED` (403, invalid
user context). Otherwise the answer streams as Server-Sent Events:

| Event | Data |
|---|---|
| `start` | `{trace_id}` |
| `text` | `{delta}`: the next piece of the answer (Markdown) |
| `tool` | `{id, name, title, status: running\|done\|error, write?, error?: {code, message}}` |
| `proposal` | `{tool, title, operation, data: [receipt], trace_id}`: a change the user must confirm in the app |
| `notice` | `{code, message}`: `STEP_LIMIT`, `TRUNCATED`, `DECLINED`, `HISTORY_TRIMMED` |
| `error` | `{code, message, trace_id}` |
| `done` | `{trace_id, steps, tools, proposals, notices}` |

With `"stream": false` the same summary returns once as `{success, data: {text, tools, proposals, notices, steps, trace_id}}`.
Each turn is audited as `chat.turn`; its tool calls are audited as `tool.execute` under the same trace.

## Model gateway

For apps that run their own chat (their own tools, their own model picker) but keep the model keys
on the Hub. Called from the app's server with a client key, like the chat endpoint. The app may use
it while its **Chat** is on in the Hub and the app is active, and only with the models its admin
allowed under **Model gateway access** (every model while that list is empty; others get
`403 MODEL_NOT_ALLOWED`).

Limits: the chat rate limit applies per `metadata.end_user_id` and `GATEWAY_APP_RATE_LIMIT` (default
300 per minute) per app, since the app chooses the user ids. The daily limit counts questions per
user: only calls whose last message is the user's, so tool rounds that continue an answer do not use
it up. The monthly token budget (input plus output, all models) refuses calls with
`429 BUDGET_EXCEEDED` once this month's usage reaches it; the call that crosses it still completes.

Tool schemas sent with PHP's empty arrays (`"properties": []`) are repaired to objects. A provider
that answers 502/503 or cannot be connected to gets one more try after half a second. A provider's
error text is logged with the trace id (personal data withheld). Each call is audited as
`model.chat` (model, result, duration) and counted per app, model and month (calls, errors, tokens);
messages are never stored.

Model ids name their provider: `anthropic/claude-opus-5-5`, `openai/gpt-4.1`, `openrouter/meta-llama/llama-3.1-8b-instruct`
(provider key, `/`, the provider's model id). The list holds every ready provider under **AI
providers**: Claude when its key is set, the environment gateway, and each enabled OpenAI-compatible
provider, with model lists fetched from the providers.

| Method | Path | Description |
|---|---|---|
| GET | `/gateway/v1/models` | `{object: "list", default, data: [{id, object: "model", owned_by, name}]}`. `default` is the app's Chat model when it is listed. |
| POST | `/gateway/v1/chat/completions` | OpenAI chat completions: `{model, messages, tools?, tool_choice?, temperature?, top_p?, max_tokens?, metadata?}`. Function calling works with every provider; Claude turns are converted both ways. `"stream": true` returns the answer as one SSE chunk and `[DONE]`. |
| POST | `/gateway/mcp` | JSON-RPC (plain JSON, no session): `tools/list`, and `tools/call` with `list_ai_models` (`{data: [{id, provider, name}], default}`) or `chat_ai` (the completion body above, answered as `structuredContent.result`). The model bridge for apps that run their own chat: set `MCP_BRIDGE_URL` to this address and `MCP_BRIDGE_TOKEN` to a client key. |

## MCP endpoint

`POST /mcp` (Streamable HTTP, official MCP Python SDK). Headers:

- `Authorization: Bearer <client key>` (required)
- `X-Hub-Delegation: <token signed by the app>` for user-scoped data
- `Origin` must be in `ALLOWED_ORIGINS` when present (DNS-rebinding protection)

`prompts/list` and `prompts/get` serve the app's skills to keys that can call every tool
the skill names.

Tool names: built-ins `list_data_sources` and `run_report`; memory tools `recall_memory`,
`save_memory` and `forget_memory` when the app turned memory on; custom tools use the tool key
with dots replaced by `__` (for example `your_app__orders__list`). Apps outside the `dev`
environment get an environment suffix.

Results arrive as `structuredContent`, with the same JSON as text content:

- read tools: `{success, data: [records], meta: {as_of, timezone, scope, coverage, contains_personal_data: false, total_count?, has_more?, next_cursor?}, trace_id}`
- write tools: `{success, data: [receipt], meta: {operation, as_of, contains_personal_data: false, requires_confirmation?}, trace_id}`
- reports: see [TOOLS.md](TOOLS.md#built-in-run_report-default-reporting-tool)

Errors are tool results with `isError: true` and text `CODE: message (trace tr_…)`. Codes
include `UNAUTHENTICATED`, `PERMISSION_DENIED`, `MODULE_DISABLED`, `CONNECTOR_INACTIVE`,
`VALIDATION_FAILED`, `POLICY_LOCKED`, `PII_DETECTED`, `PRIVILEGE_ESCALATION`, `CONFLICT`
(contract changed, the tool needs a new test), `RATE_LIMITED`, `UPSTREAM_*` and
`SCHEMA_MISMATCH`.

`GET /health` (process) and `GET /ready` (database) are unauthenticated.
