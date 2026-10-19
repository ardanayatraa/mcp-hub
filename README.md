# MCP Hub

Connect business applications to AI clients through
reviewed, permission-checked [MCP](https://modelcontextprotocol.io) tools.

Each connected app keeps ownership of its data and decides, per request, what the
signed-in user may see. The Hub stores configuration, encrypted credentials and an
audit log. It never receives database credentials and never stores business records.

This branch, `mcp-py`, is the Python edition: a FastAPI server (`backend/`) and a Vue admin UI
(`frontend/`). The JavaScript edition, one Nuxt app with the same API and database schema, is on
the `mcp-js` branch.

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

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22 and pnpm.

```powershell
# 1. Hub API + MCP endpoint
cd backend
uv sync --frozen --group dev
$env:ENVIRONMENT = "dev"
$env:DATABASE_URL = "sqlite+pysqlite:///./hub.db"
$env:SECRET_ENCRYPTION_KEY = "<fernet key>"   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
$env:SESSION_SIGNING_KEY = "<long random string>"
$env:ADMIN_INITIAL_PASSWORD = "ChangeMe-Now-12"
$env:COOKIE_SECURE = "false"
$env:ALLOW_INSECURE_HTTP = "true"
$env:EGRESS_ALLOW_LOOPBACK = "true"
$env:EGRESS_ALLOWED_PORTS = "80,443,8081"
$env:ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
uv run --frozen alembic upgrade head
uv run python -m app.bootstrap        # creates admin@localhost
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Reference app (another shell): a sample connected application on :8081
uv run --project backend python reference/your_app/app.py

# 3. Admin UI (another shell)
cd frontend
pnpm install --frozen-lockfile
pnpm dev                              # http://127.0.0.1:5173
```

Then, in the UI (about five minutes):

1. **Apps → Connect app**: name `Your App`, key `your_app`, base URL `http://127.0.0.1:8081`,
   bearer token `dev-your-app-key`, delegation secret `dev-delegation-secret` (under *Advanced*).
   The wizard tests the connection, syncs the contract and lets you allow data sources.
2. **Access → Create client key** for the app. Copy the key and the MCP client snippet.
3. Point an AI client at `http://127.0.0.1:8000/mcp` with `Authorization: Bearer <key>`.
   It can call `list_data_sources` and `run_report` immediately.
4. Optional: **Tools → New tool** to publish named tools (create, test with sample data, publish).
   **Tools → Report playground** previews `run_report` without an AI client.

The reference app's data is user-scoped, so calls also need an `X-Hub-Delegation` header
that the app gateway signs for the signed-in user (see the connector contract). The Hub
never accepts a user id from the model.

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

Transport is Streamable HTTP, served by the official MCP Python SDK. `tools/list` only shows
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
stack: it allows private HTTP egress so the Hub can reach the reference app.

Production refuses to start without PostgreSQL, HTTPS-only cookies, MFA, an egress
allowlist and disabled insecure HTTP/TLS. Run one worker process: rate limits are kept in
memory.

## Upgrading

Back up the database, then run `uv run --frozen alembic upgrade head`. Published tools keep
working, and the Hub refuses to start until the schema is current. See
[What changed in 1.0](docs/CHANGES.md).

## Tests

```powershell
cd backend
uv run ruff check app tests ../reference/your_app
uv run pytest
cd ../frontend
pnpm build      # type-checks with vue-tsc
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
- [Product requirements](PRD.md)
