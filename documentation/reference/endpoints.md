# Endpoint map

The Hub and Laravel use different hosts and authentication methods. Keep them separate when configuring or debugging a connection.

## Hub host

| Prefix or endpoint | Caller | Purpose |
|---|---|---|
| `/api/admin/v1` | Admin UI or operator | Session and CSRF for configuration and lifecycle actions |
| `/mcp` | MCP client or application server | Client key; delegation for user-scoped access |
| `/gateway/v1/models` | Application server | Allowed model catalog |
| `/gateway/v1/chat/completions` | Application server | Completions governed by gateway policy |
| `/chat/v1/config`, `/chat/v1/turn` | Application server | Hub chat with actor context |
| `/health`, `/ready` | Deployment probes | Process health and service readiness |

## Laravel host

These are configurable default prefixes.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/ai/v1/health` | Health and metadata readiness |
| GET | `/api/ai/v1/capabilities` | Current manifest and grants |
| GET | `/api/ai/v1/{resource}/list` | Scoped pagination |
| GET | `/api/ai/v1/{resource}/get` | Scoped exact lookup |
| GET | `/api/ai/v1/{resource}/count` | Scoped count |
| POST | `/api/ai/v1/{resource}/commands/{operation}` | CRUD proposal |
| GET | `/api/ai/v1/{resource}/commands/{proposal}` | Proposal receipt |
| POST | `/api/ai/v1/{resource}/exports` | Private report job |
| GET | `/api/ai/v1/{resource}/exports/{reference}` | Export receipt |
| GET | `/mcp-hub` | Settings protected by the manage Gate |
| GET/POST | `/mcp-hub/chat` | Chat protected by the chat Gate |
| GET/POST | `/mcp-hub/proposals/{proposal}` | User review and decision |
| GET | `/mcp-hub/exports/{reference}` | Private download protected by the export Gate |

Source endpoints use a service bearer token; actor-scoped operations also require a single-use assertion. Web endpoints use sessions, Gates, and CSRF for mutations.

## Complete contracts

- [Admin and MCP API](admin-api.md): request fields, responses, streaming, and errors.
- [Connector contract](connector-contract.md): manifests, schemas, and identity.
- [Tools and reporting](tools.md): filters, metrics, pagination, and coverage.
- [Artisan and configuration](laravel.md): application settings and maintenance.
