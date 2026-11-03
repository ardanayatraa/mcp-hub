# Concepts and architecture

MCP Hub connects AI clients to business applications through reviewed tools. This guide covers the Python edition on `main`: a FastAPI backend, Vue admin UI, PostgreSQL in production, and Redis for shared rate limits.

## Responsibilities

| Component | Responsibilities |
|---|---|
| Hub | Connector configuration, encrypted secrets, tool catalog, profiles, model gateway, and audit metadata |
| Source application | Active accounts, tenant membership, record ownership, business validation, approval, and report files |
| AI client | Discover permitted tools and submit arguments that match their schemas |
| Laravel package | Source endpoints, Hub SDK, assertion verification, proposals, and UI protected by host permissions |

The Hub does not need credentials for your business database. Authorized records may pass through it during a request; the application retains ownership. Hub configuration and audit metadata are separate from business records. Optional memory stores encrypted user notes, while private exports remain in the Laravel application.

## Key terms

| Term | Meaning |
|---|---|
| App / connector | An application with a source URL, environment, and stable identity |
| Data source / resource | A reviewed module, such as `orders` |
| Tool | An operation with a fixed endpoint, schema, and permissions |
| Client key | A credential restricted to a particular application scope |
| Access profile | An additional restriction on resources and tools |
| Skill | Reusable instructions published as an MCP prompt |
| Delegation | Proof of the user context sent from the application server to the Hub |
| Assertion | Short-lived, single-use proof sent from the Hub to the source application |

## Request lifecycle

1. The application server resolves the actor from its authenticated user.
2. The client calls the Hub with a bearer key and delegation for user-scoped operations.
3. The Hub checks the key, profile, connector, grants, schema, and operation permissions.
4. The Hub calls a fixed endpoint with a service credential and actor assertion.
5. The application rejects replay and rechecks the account, tenant, policy, and record scope.
6. The Hub validates the response and projects permitted fields before returning the result.

## Connector modes

**`source_managed`** follows the application's permission manifest. A failed refresh denies discovery and calls instead of using stale grants. Manual tool and module settings are locked in the Hub.

**`http_contract`** uses a manual review, test, and publication workflow in the Hub. Choose it when Hub operators manage the tool contract.

See the [connector contract](../reference/connector-contract.md) for manifests, response envelopes, and schema limits.
