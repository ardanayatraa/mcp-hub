# Tools and reporting

Everything an AI client can call is a tool. The Hub has two built-in tools, three memory
tools an app can turn on, and any number of custom tools that admins create from templates
in the UI. Skills (MCP prompts) package instructions that use those tools.

## What a client sees

`tools/list` returns, for the calling client key:

1. `list_data_sources` and `run_report`, unless the key is limited to selected tools;
2. `recall_memory`, `save_memory` and `forget_memory` when the app has memory turned on;
3. published custom tools of the key's app, when their data source has the needed
   operation enabled, their tested configuration still matches the app's contract, and
   (for write tools) the key has write permission.

Listing is not authorization. Every `tools/call` re-checks the key, the app status, the
data source, the operation, the field policy and the source contract before anything is
sent to the app, and the app re-checks the user.

**Tools → What the agent sees** shows this list for any app and client key (or for a new
read-only or read & write key), with each tool's inputs, the server instructions and the
skills the key is offered. It uses the same code as `tools/list` and `prompts/list`.

## Built-in: `list_data_sources`

No arguments. Returns each enabled data source with its key, operations, whether reports
can read it, and its usable fields:

```json
{"source": "orders", "name": "Orders", "operations": ["read"], "reportable": true,
 "fields": [{"name": "status", "type": "string", "values": ["open", "paid", "void"]},
            {"name": "total", "type": "number", "aggregate_only": true}]}
```

## Built-in: `run_report` (default reporting tool)

Reads the data source's list route page by page (up to `REPORT_MAX_RECORDS`, default
1000, within `REPORT_TIMEOUT_SECONDS`, default 20). It then filters and groups in memory
and returns a structured answer. Nothing is stored.

| Argument | Meaning |
|---|---|
| `source` | Data source key, e.g. `orders` (or `app_key.orders`). Required. |
| `filters` | Up to 10 `{field, op, value}`. Ops: `eq`, `ne`, `in` (list), `gt`/`gte`/`lt`/`lte` (number or ISO date), `between` (`[low, high]`, end date inclusive), `contains` (text), `is_null`, `not_null`. Text equality ignores case. |
| `group_by` | Up to two fields. |
| `time_bucket` | `{field, interval}` with `day`, `week`, `month` or `year`; adds a `period` column in the data's timezone. |
| `metrics` | Up to six `{fn, field}` with `count`, `sum`, `avg`, `min`, `max`. Groups default to `count`. |
| `sort` | `{by, direction}`: a field, `period` or a metric name such as `count` or `sum_total`. |
| `limit` | Rows or groups to return, 1–200 (default 50). |
| `columns` | Fields to show when listing records without grouping. |

Modes follow from the arguments: no grouping and no metrics lists **records**; metrics
without grouping return a **summary** row; `group_by` and/or `time_bucket` return
**groups**.

Answer shape:

```json
{
  "success": true,
  "data": {"mode": "groups", "columns": ["status", "count", "sum_total"],
           "rows": [{"status": "paid", "count": 41, "sum_total": 18230.5}], "totals": {"count": 57, "sum_total": 21011}, "groups": 3},
  "summary": "Your App · Orders: 57 record(s). 3 group(s) by status; count: paid: 41 (72%); open: 12 (21%); void: 4 (7%).",
  "chart": {"type": "bar", "x": "status", "y": ["count", "sum_total"]},
  "notes": [],
  "meta": {"coverage": "complete", "records_read": 57, "pages": 2, "truncated": false,
           "as_of": "2026-10-10T09:00:00+08:00", "timezone": "Asia/Makassar", "contains_personal_data": false},
  "trace_id": "tr_…"
}
```

`meta.coverage` is `partial` when the scan stopped early (record or time limit, or the app
failed mid-way) or when the app itself reported partial data. Clients must say so when
answering.

Examples:

```json
{"source": "orders", "group_by": ["status"], "metrics": [{"fn": "count"}, {"fn": "sum", "field": "total"}]}
{"source": "orders", "time_bucket": {"field": "created_at", "interval": "month"}}
{"source": "activity", "filters": [{"field": "last_active_at", "op": "lte", "value": "2026-10-07"}], "metrics": [{"fn": "count"}]}
{"source": "tickets", "filters": [{"field": "status", "op": "eq", "value": "open"}], "columns": ["ref", "subject", "created_at"], "sort": {"by": "created_at", "direction": "asc"}}
```

### Field rules

| Field visibility | In reports |
|---|---|
| Visible to AI | Filter, group, sort, show, and any metric. |
| Totals only | Only `sum` and `avg`. Hidden (null) for any group with fewer than 3 records, so single values cannot be inferred. Never filtered, grouped or shown. |
| Hidden | Not usable at all. Fields not in the policy are hidden by default. |

A visible value that looks like personal data (an email, phone number, national id or
credential) is replaced by null and counted in `notes`, rather than failing the whole
report. Read tools that return records verbatim still fail closed on such values.

Exact-match filters on parameters the app's list route accepts (enum, number, boolean)
are also sent to the app, so it returns less data.

## Custom tools

Create them under **Tools → New tool**. Every template binds to a route the app published
in its manifest; admins choose among reviewed routes and never type URLs.

| Template | Use it for | Runtime |
|---|---|---|
| **Read records** | Lists, lookups and counts the app already offers (`/orders/list`, `/orders/get`, `/orders/count`). | One call to the route; returns allowlisted records. |
| **Report** | A named, fixed report (for example "Orders by status this month"). | `run_report` with the saved spec. The AI can change `limit`, and add filters if you allow it. |
| **Create / Update / Delete** | Letting AI propose changes. | One call to the reviewed write route with an `Idempotency-Key`. The app validates it and may only return a proposal for the user to confirm. Never retried. |

Configuration needs no JSON editing:

- **Name**: `app_key.<words>`, shown to clients as `app_key__<words>`.
- **Description**: what the tool returns and when to use it. This is the main signal the AI uses to pick a tool. The Hub appends a short standard note (read-only, or what a write does).
- **Parameters** (read and write): choose which of the route's parameters the AI may set, describe them, and narrow enums or numeric ranges. You can't widen them, and parameters the route requires are always included.
- **Fields returned**: only fields marked *Visible to AI* can be returned by read tools.

### Lifecycle

```text
draft ──test passes──► publish ──► live ◄──► disabled
  ▲                                  │
  └──────── edit (goes offline) ─────┘
```

- **Test** runs the real pipeline. *Sample data* generates records shaped like the app's response, so nothing is sent. *Live data* calls the app; user-scoped routes need a delegation token signed by the app, and production apps allow live tests only for public aggregates. Write tools are always dry runs that show the request the Hub would send. Each test also runs safety checks: unknown arguments are rejected, malformed responses are rejected, and personal data is blocked or hidden.
- **Publish** needs a passing test of the current configuration, the app to be active, and the operation enabled on the data source.
- **Editing** a live tool takes it offline until it passes a test and is published again; the patch version increases.
- When the app's contract changes, that data source is switched off for review and its tools show **Needs re-test**. Re-test and publish to bind them to the new contract. Other data sources of the app are unaffected.

### Generate tools

**Tools → Generate tools** creates the recommended set for one app from the routes it
published on its allowed data sources:

| Route | Tool | After generating |
|---|---|---|
| A list route | `app.source.list` (or the route's last path segment) | Tested with sample data and published, when the data source allows reading |
| A lookup route (ends in a parameter or requires one) | `app.source.get` | Published only if the sample test passes; otherwise a draft to test with arguments |
| The data source's report route | `app.source.summary`: count by the first category field (or by month), plus the total of the first numeric field | Tested and published |
| A create, update or delete route | `app.source.create` and so on | Always a draft: review, test and publish it yourself |

Routes that already have a tool are skipped, so running it again only adds what is new.
Apps that follow their own permissions get their tools automatically and cannot use it.

## Skills (MCP prompts)

A skill is a named instruction an AI client shows like a slash command (`/weekly_report`).
Admins write it per app under **Tools → Skills**, starting from a template if they like:

- **Instructions** are written as the user's request. `{{name}}` placeholders are filled
  from the skill's arguments (at most 5, each marked required or optional).
- **Tools** lists the tools the skill relies on. A client key that cannot call all of them
  does not see the skill, so a skill never promises what the key cannot do.
- **Preview** shows the exact text a client receives.

Skills are text only: nothing runs on the Hub. Instructions and argument values are checked
for personal data, and text that tries to override the assistant's rules is refused.
`prompts/get` re-checks the key every time and records `skill.use` in the activity log.

## Memory (per app, opt-in)

With memory on (**App → Memory**), AI clients get three tools for the signed-in user:

| Tool | Does |
|---|---|
| `recall_memory` | Returns the user's profile preferences (`language`, `currency`, …) and notes, newest first. `query` filters notes. |
| `save_memory` | `{text, key?}`. With a key it replaces that preference (at most 20); without, it adds a note. The oldest note makes room when the app's limit is reached. |
| `forget_memory` | `{id}`, `{key}` or `{everything: true}`. |

Memory needs the signed `X-Hub-Delegation` header: it belongs to that user and no one
else. The model never learns or retrains; it reads the notes at the start of a
conversation. See [Security](SECURITY.md#user-memory) for how memory is protected.

## Tool switches (per app)

Every tool an app's AI could be offered has an on/off switch on the app's **Tools** tab: the
built-in tools, the memory tools and each app tool. A switch only removes: an off tool is left out
of `tools/list` for every client key of that app and of the Hub chat, calls to it fail with
`TOOL_DISABLED`, and skills that need it are hidden. **What the agent sees** reflects switches.

## Hub chat

An app can show its users a chat window instead of (or as well as) connecting MCP clients. The
Hub runs the model with the same tools, switches, permissions and audit as an MCP call, and the
app passes the signed-in user. Settings are on the app's **Chat** tab: Claude Opus 5.5 by default
(Sonnet 5.5 and Haiku 5.5 are faster), or any OpenAI-compatible provider a super admin added under
**AI providers** (OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Gemini, Together, a company gateway,
Ollama, ...). Pick a model that supports tool calling.
Skills appear as `/` commands. Write tools return proposals that the user confirms in the app.
The app builds its own chat window; see [API.md](API.md#chat-endpoint) and the in-app Laravel guide.

## Access: client keys

Keys are created under **Access**. A key belongs to one app.

| Setting | Effect |
|---|---|
| Read (always) | Built-in tools and published read/report tools of the app. |
| Allow write tools | Adds published create/update/delete tools. The data source must also have that operation enabled. |
| Only selected tools | An allowlist of tool names, built-ins included. Calls to anything else are denied. |
| Expiry | 30 days to 1 year. Revocation is immediate. |

Write calls also always need the user's delegation token, and the app makes the final
decision. Personal data (emails, phone numbers, ids) is rejected in any tool's arguments:
users enter it in the app's own forms, never through AI chat.
