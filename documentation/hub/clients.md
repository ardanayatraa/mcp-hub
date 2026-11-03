# Clients, tools, and access profiles

A client key restricts a caller to an application and its permitted operations. It does not replace source user identity.

## Connect an MCP client

Create a key under Access, store the one-time token in the client's secret store, and configure the Streamable HTTP endpoint:

```json
{
  "mcpServers": {
    "mcp-hub": {
      "type": "http",
      "url": "https://hub.example.com/mcp",
      "headers": {"Authorization": "Bearer <CLIENT_KEY>"}
    }
  }
}
```

Wrapper configuration can differ between clients. For user-scoped resources, a trusted server also sends `X-Hub-Delegation`. A user ID in a conversation cannot establish identity.

## Tool catalog

| Tool | Purpose |
|---|---|
| `list_data_sources` | Discover permitted resources and fields |
| `run_report` | Filter records and compute totals or grouped metrics within time and record limits |
| Memory tools | Recall, save, or forget user memory when enabled |

Manual tools follow draft → test → publish. Source-managed tools follow manifest grants. Use **Tools → What the agent sees** to inspect a particular key's catalog. Discovery is not permanent authorization: every call rechecks access.

## Profiles

Effective access is the intersection of application permissions, resource grants, the profile, the key's tool allowlist, and write scope. A profile cannot expose fields forbidden by the developer or increase a model budget. An empty profile list grants no access in that dimension; a disabled profile blocks bound keys on their next call.

Test revocation using synthetic data: make an authorized call, revoke permission, then repeat it. The call must fail even if the client has cached the old catalog.

[Tools and reporting reference](../reference/tools.md) · [Profile API and revisions](../reference/profiles.md)
