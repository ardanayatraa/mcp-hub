# MCP Hub

Connect business applications to AI clients through
reviewed, permission-checked [MCP](https://modelcontextprotocol.io) tools.

Each connected app keeps ownership of its data and decides, per request, what the
signed-in user may see. The Hub stores configuration, encrypted credentials and an
audit log. It never receives database credentials and never stores business records.

This branch, `mcp-js`, is the JavaScript edition: one [Nuxt](https://nuxt.com) app (`hub/`)
that serves the admin UI, the admin API, the MCP endpoint and the chat API, plus a small SDK
for app servers (`sdk/`). The Python edition (FastAPI + Vue) is on the `mcp-py` branch. Both
use the same API, database schema and revision ids, so a database works with either.

| Path | What it is |
|---|---|
| `hub/app/` | Admin UI: pages, layout, components (Vue, rendered in the browser) |
| `hub/server/core/` | The Hub: auth, connectors, policy, tools, MCP, chat, migrations |
| `hub/server/routes/`, `hub/server/api/` | Nitro routes that hand `/mcp`, `/chat/v1/*` and `/api/admin/v1/*` to the core |
| `hub/scripts/` | `npm run migrate` and `npm run bootstrap` |
| `sdk/` | `@mcp-hub/backend-sdk` for Node app servers ([README](sdk/README.md)) |

## Concepts

| In the admin UI | What it is |
|---|---|
| **App** | A connected application. It publishes a small JSON API: a health check, a capability manifest, and the routes the Hub may call. See [the connector contract](docs/CONNECTOR_CONTRACT.md). |
| **Data source** | A module in the app's manifest, for example `orders`. Off until an admin allows it. Each field is *Visible to AI*, *Totals only* or *Hidden*. |
| **Tool** | What an AI client can call. Two built-in tools work on every allowed data source; admins add custom tools from templates without writing code. |
| **Skill** | A reusable instruction, such as "Weekly report", that AI clients show like a slash command (an MCP prompt). Text only. |
| **Memory** | Off by default. When an app turns it on, AI clients can remember preferences and notes per signed-in user, encrypted and never visible to admins. |
| **Chat** | Off by default. An AI chat window an app shows its users: the Hub runs the model (Claude by default) with the app's tools; the app passes the signed-in user and builds the chat window its own way. Conversations are never stored. |
| **Tool switch** | An on/off switch per tool and app. Off hides a tool from every client key and the chat. |
| **Client key** | Lets one AI client (an MCP client or an app's AI gateway) use one app's tools. Read access by default; write tools need an extra permission. |

Built-in tools:

- **`list_data_sources`**: which data the client may read, with field names and types.
- **`run_report`**: the default reporting tool. It reads authorized records from a data source page by page, filters them, and returns records, totals or grouped metrics (count, sum, avg, min, max, by day/week/month/year) with a one-line summary.

Custom tool templates: **Read records** (one reviewed read route), **Report** (a saved
`run_report`), and **Create / Update / Delete** (a reviewed write route; the app validates
it and may ask the user to confirm). Details: [docs/TOOLS.md](docs/TOOLS.md).

## Quick start (local development)

Requires Node 24. The reference app needs Python 3.12 with `fastapi` and `uvicorn`.

```powershell
# 1. The Hub: admin UI, API and MCP endpoint in one process
cd hub
npm install
Copy-Item ..\.env.example .env       # then set the secrets and uncomment the local section
npm run migrate                       # creates the SQLite database
npm run bootstrap                     # creates admin@localhost from ADMIN_INITIAL_PASSWORD
npm run dev                           # http://localhost:3000

# 2. Reference app (another shell): a sample connected application on :8081
python -m pip install fastapi uvicorn
python reference/your_app/app.py
```

`hub/.env` needs at least `SECRET_ENCRYPTION_KEY`, `SESSION_SIGNING_KEY`,
`ADMIN_INITIAL_PASSWORD`, and for the reference app `COOKIE_SECURE=false`,
`ALLOW_INSECURE_HTTP=true`, `EGRESS_ALLOW_LOOPBACK=true` and `EGRESS_ALLOWED_PORTS=80,443,8081`.

Then, in the UI (about five minutes):

1. **Apps → Connect app**: name `Your App`, key `your_app`, base URL `http://127.0.0.1:8081`,
   bearer token `dev-your-app-key`, delegation secret `dev-delegation-secret` (under *Advanced*).
   The wizard tests the connection, syncs the contract and lets you allow data sources.
2. **Access → Create client key** for the app. Copy the key and the MCP client snippet.
3. Point an AI client at `http://localhost:3000/mcp` with `Authorization: Bearer <key>`.
   It can call `list_data_sources` and `run_report` immediately.
4. Optional: **Tools → New tool** to publish named tools (create, test with sample data, publish).
   **Tools → Report playground** previews `run_report` without an AI client.

The reference app's data is user-scoped, so calls also need an `X-Hub-Delegation` header
that the app gateway signs for the signed-in user (see the connector contract). The Hub
never accepts a user id from the model. The [SDK](sdk/README.md) signs it for you.

For production, `npm run build` and `npm start` (`node .output/server/index.mjs`).
`.output` is self-contained; set `HUB_AUTO_MIGRATE=true` to create or upgrade the schema and
the first admin on start, as the container does.
## Connecting an AI client

```json
{
  "mcpServers": {
    "mcp-hub": {
      "type": "http",
      "url": "https://hub.example.com/mcp",
      "headers": { "Authorization": "Bearer hub_..." }
    }
  }
}
```

Transport is Streamable HTTP (stateless, JSON responses), served by the official MCP TypeScript SDK. `tools/list` only shows
what the key may call, and every `tools/call` is authorized again from scratch.

## Giving an app its own AI chat

Set `ANTHROPIC_API_KEY` in the Hub's environment for Claude, or add any OpenAI-compatible provider
(OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Gemini, a gateway, Ollama, ...) under **AI providers**.
Then turn the chat on in the app's **Chat** tab, pick the provider and model, and call
`/chat/v1/turn` from the app's server ([API](docs/API.md#chat-endpoint)). The app designs its own
chat window and streams the answer to it; the in-app **Laravel guide** shows the server route and a
small browser helper.

## Compose

Copy `.env.example` to `.env`, fill in the secrets, then run
`docker compose --env-file .env -f infra/compose.yml up --build`. The UI is at
`https://localhost:8443` (development certificate). The Compose file is a development
stack: it allows private HTTP egress so the Hub can reach the reference app. Services:
PostgreSQL, the hub (`infra/Dockerfile.hub`, migrates on start), the reference app and an
nginx TLS edge.

Production refuses to start without PostgreSQL, HTTPS-only cookies, MFA, an egress
allowlist and disabled insecure HTTP/TLS. Run one process: rate limits are kept in
memory.
## Upgrading

Back up the database, then run `npm run migrate` in `hub/` (SQLite gets an automatic copy
first). It also accepts a database created by the Python edition. Published tools keep
working, and the Hub answers `503 NOT_READY` until the schema is current. See
[What changed in 1.0](docs/CHANGES.md).
## Tests

```powershell
cd hub
npm test             # contract, security, reporting, MCP and migration tests
npm run typecheck    # vue-tsc over the UI and server
npm run build
cd ../sdk
npm test
```
## Documentation

- [Tools and reporting](docs/TOOLS.md): templates, lifecycle, `run_report` reference
- [Connector contract](docs/CONNECTOR_CONTRACT.md): what a connected app implements
- [Admin and MCP API](docs/API.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security](docs/SECURITY.md) and [threat model](docs/THREAT_MODEL.md)
- [Backup, upgrade and rollback](docs/BACKUP.md)
- [What changed in 1.0](docs/CHANGES.md)
- [Laravel integration](integrations/laravel/README.md)
- [JavaScript SDK for app servers](sdk/README.md)
- [JavaScript backend SDK](backend-js/README.md)
- [Product requirements](PRD.md)
