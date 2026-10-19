# JavaScript backend SDK

Node.js 22+ SDK for a server that connects to MCP Hub. It has no runtime dependencies.
Keep the Hub client key, source bearer token and delegation secret on the server.

## Use Hub tools and chat

Install from this repository:

```bash
npm install ./backend-js
```

```js
import { HubClient } from "@mcp-hub/backend-sdk";

const hub = new HubClient({
  baseUrl: process.env.MCP_HUB_BASE_URL, // e.g. https://hub.example.com
  clientKey: process.env.MCP_HUB_CLIENT_KEY, // Access > client key, issued for this app
  appKey: "your_app",
  delegationSecret: process.env.MCP_HUB_DELEGATION_SECRET,
  origin: process.env.APP_ORIGIN, // include if Hub ALLOWED_ORIGINS requires it
});

// Build actor from the authenticated server session, never from browser request JSON.
const actor = { tenantId: session.tenantId, userRef: session.userRef };
const tools = await hub.listTools(actor);
const result = await hub.callTool("your_app__projects__list", { limit: 10 }, actor);
console.log(result.data, result.meta, result.trace_id);

const config = await hub.getChatConfig();
const answer = await hub.chatTurn({ message: "Show my projects", history: [] }, actor);
for await (const { event, data } of hub.streamChatTurn({ message: "Show my projects" }, actor)) {
  // Forward start/text/tool/proposal/notice/done to your own authenticated UI.
  console.log(event, data);
}
```

`listTools`, `callTool`, `listPrompts`, `getPrompt`, `chatTurn` and `streamChatTurn`
mint a short-lived `X-Hub-Delegation` token for the supplied actor. Use a fresh actor
from your application's authenticated request and check that the account is active.
`getChatConfig` needs only the client key. The client throws `HubSdkError` with `code`
and `status` for Hub refusals and invalid responses. A `tools/call` error is thrown,
even though MCP returns HTTP 200 for tool failures.

The SDK uses Hub's stateless JSON MCP response mode. It sends the same MCP request
metadata and method headers as the Laravel adapter. `baseUrl` is the Hub origin,
without `/mcp` or `/chat/v1`.

## Authenticate Hub requests to your source API

The Hub uses a **different** bearer token when it calls your source application.
Set that value as `MCP_SOURCE_BEARER_TOKEN` in your app and as the connector's
`secret` in Hub. The delegation secret must match the connector's delegation secret.

```js
import { HubSourceAuth } from "@mcp-hub/backend-sdk";

const sourceAuth = new HubSourceAuth({
  appKey: "your_app",
  audience: "https://app.example.com", // exact connector base URL in Hub
  bearerToken: process.env.MCP_SOURCE_BEARER_TOKEN,
  delegationSecret: process.env.MCP_HUB_DELEGATION_SECRET,
  consumeJti: async (jti, exp) => {
    // Redis example: one atomic add shared by every app worker.
    const ttl = Math.max(1, exp - Math.floor(Date.now() / 1000) + 5);
    return (await redis.set(`hub:assertion:${jti}`, "1", { NX: true, EX: ttl })) === "OK";
  },
  authorize: async ({ tenantId, userRef, permission }) => {
    const user = await db.users.findByRef(userRef); // your application owns this lookup
    return {
      actor: user,
      active: user?.active === true,
      tenantId: user?.tenantId,
      allowed: user ? await can(user, permission) : false,
    };
  },
});

// In authenticated health and capabilities handlers:
sourceAuth.verifyBearer(request.headers);

// In EVERY user-scoped read or write handler:
const { actor, tenantId } = await sourceAuth.authenticate(request.headers, "projects.read");
// Query only rows currently permitted for actor and tenantId.
// Include tenant_id in each source row; Hub strips it before returning data to AI.
```

`authenticate` verifies the source bearer credential, HMAC signature, application,
audience, 60-second assertion expiry, one-time `jti`, and your live account and
permission checks. `consumeJti` must be atomic and shared across workers. The exported
`MemoryReplayStore` is only for a single-process local example or tests.
Handle `HubSdkError` as `{success:false,error:{code,message}}` with its `status`.

Your application still supplies `/api/ai/v1/health`, `/api/ai/v1/capabilities` and
the reviewed data routes. Return the exact manifest and response shapes in the
[connector contract](../docs/CONNECTOR_CONTRACT.md). Source routes must return
only explicitly allowed fields, recheck row ownership on each call, and make writes
proposals for confirmation in the app.

## Run tests

```bash
cd backend-js
npm test
```
