# CRUD proposals and approval

Create, update, and delete operations use proposals reviewed by the user within the application session. Preparing a proposal does not change business records.

## Activation requirements

The connection, `commands.enabled`, resource and operation grants, closed scalar schema, explicit handler, current policy, and client key write scope must all allow the action.

Implement an application-owned `CommandHandler`. `EloquentCommands` supports generic Eloquent transactions; `WritePolicy` validates business input and supplies server-owned ownership and default attributes. Start with the generator's disabled definitions.

## Transaction workflow

1. The Hub requests a proposal with a single-use actor assertion.
2. The application validates input and scope, then stores an encrypted payload with an expiry.
3. The receipt returns a `proposal_ref` with status `pending`.
4. The user reviews canonical values at `/mcp-hub/proposals/{proposal}`.
5. Approval or cancellation requires the exact actor and tenant's application session and CSRF protection.
6. Commit locks the proposal, rechecks permissions, schema, and record version, then applies the change and records the receipt in one transaction.

| Method | Default route | Result |
|---|---|---|
| POST | `/api/ai/v1/{resource}/commands/{operation}` | Expiring proposal |
| GET | `/api/ai/v1/{resource}/commands/{proposal}` | Actor-bound receipt |
| POST | `/mcp-hub/proposals/{proposal}` | User decision through the web session |

Operations are limited to `create`, `update`, and `delete`. The model cannot establish authorization by submitting `approved`, user IDs, tenant IDs, or destination endpoints.

## Idempotency and conflicts

The same key and payload return the existing receipt; a different payload is rejected. Reapproving a committed proposal does not repeat the write.

Pending is not business success. Expiry, revoked permissions, changed configuration, or a record-version conflict may require a new proposal. The UI must not turn a pending receipt into a committed result automatically.

!!! warning "External side effects belong to the application"
    A database rollback cannot undo an email, HTTP request, or observer side effect that has already been sent. Use the host's transactional outbox for external effects. The generic handler requires the same default transaction connection as the package metadata.

[Handler and WritePolicy interfaces](https://github.com/ardanayatraa/laravel-mcp-hub/tree/v1.0.0/src/Contracts)
