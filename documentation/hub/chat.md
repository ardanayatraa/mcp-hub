# Chat and the model gateway

Provider credentials stay in the Hub. Application servers use scoped client keys; browsers never receive provider keys, Hub client keys, or delegation secrets.

| Integration | API | Use case |
|---|---|---|
| Hub chat | `/chat/v1/config`, `/chat/v1/turn` | Conversations using Hub tools and chat settings |
| Model gateway | `/gateway/v1/models`, `/gateway/v1/chat/completions` | Application-managed orchestration |
| Laravel SDK/UI | `Gateway`, `/mcp-hub/chat` | Integration with host identity and permissions |

## Configuration

Add a provider under AI providers, save its key, test the connection, then select the application's chat provider and model. Set its gateway model allowlist and monthly budget. Enable chat when using Hub chat, then call the API from the application server with actor context.

!!! important "Production model access must be configured"
    Production rejects discovery and completions until the allowlist and budget are set. An empty list or a zero budget does not mean unlimited access.

## History and memory

Hub chat does not persist conversation history; the application sends history with each request. Memory is a separate optional feature, encrypted per user. Audit metadata and report files have different lifecycles.

Laravel's `Gateway::turn()` uses non-streaming JSON. The Hub streaming contract is documented in the [API reference](../reference/admin-api.md) for custom clients.

Show a pending proposal as awaiting user approval. Approval remains inside the application's authenticated session. See [Laravel chat](../laravel/chat.md) and [CRUD proposals](../laravel/commands.md).
