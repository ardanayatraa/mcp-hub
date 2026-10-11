# Security

The connected application is the authority for its data. The Hub adds restrictions on
top of the app's own checks. It never replaces them.

## Admins

- Argon2 passwords (12+ characters, upper, lower, digit). Unknown emails take the same verification path as known ones.
- Session cookie: `HttpOnly`, `SameSite=Strict`, `Secure` in production. Every non-GET request needs the `X-CSRF-Token`.
- TOTP MFA with single-use, expiring challenges and replay-protected codes. Production refuses to start without `MFA_REQUIRED=true`.
- Login and MFA attempts are rate limited without logging the submitted address or code.
- Roles: `super_admin` (everything, users and backups), `app_admin` and `auditor` (only assigned apps; auditors are read-only and never see tokens or hashes). The last active super admin cannot be demoted or disabled. Disabled admins lose access on their next request.

## Client keys (MCP callers)

- Token format `hub_<random>`. Only the SHA-256 hash is stored, and the token is shown once.
- Bound to one app and environment, with an expiry from 1 to 365 days. Revocation is immediate.
- Scope `mcp:tools` reads. `tools:write` is a separate, explicit permission for create/update/delete tools. An optional tool allowlist narrows a key further.
- `tools/list` is filtered per key. Every `tools/call` re-checks the key, app status, data source, operation, contract fingerprint, schemas and delegation. Cached tool names cannot bypass a change.

## Users behind a key

A client key proves which app gateway is calling, not which user. User-scoped routes need
`X-Hub-Delegation`, an HMAC token the app signs for the signed-in user. It is valid for at
most 150 seconds and bound to `aud=mcp-hub` and the app key. The Hub then sends the app a
60-second assertion bound to the app's base URL, and the app re-checks the user on every
call. Arguments such as `user_id`, `tenant_id`, `role`, `approved`, `url`, `path` and
`method` are rejected anywhere in a tool call.

Rows returned by user-scoped routes must carry the tenant field. Rows for any other
tenant are dropped and the answer is marked `partial`.

## Writes

Create/update/delete tools need all of the following:

1. a route the app declared in `write_endpoints`;
2. the operation enabled on the data source by an admin;
3. a published tool that passed a dry-run test (write tools are never sent from the test console);
4. a client key with write permission;
5. a valid user delegation.

The Hub sends an `Idempotency-Key`, never retries a write, and checks that the receipt
belongs to the same tenant. The app decides whether to apply the change or return a
proposal for the user to confirm in its own UI. A model-generated "approved" flag is never
accepted.

## Personal data

- **Field visibility** is default-deny. Fields come from the app's allowlist. Names that indicate personal or secret data (email, phone, password, token, secret, national id, `user_id`, `tenant_id`, names, address, birth date, including word variants such as `owner_email` and `contactPhone`) are always blocked and locked. Admins can tighten a field, or relax it back to the developer's level, never beyond.
- **Read tools** project records to allowlisted fields and fail closed when an allowed value looks like an email, phone number, national id, SSN or credential, or is nested.
- **Reports** use visible fields freely. *Totals only* fields allow only sums and averages, which are hidden for groups of fewer than 3 records. Unsafe visible values are replaced by null and counted in `notes`, never returned.
- **Inputs** containing detected personal data are rejected. Users enter such data in the app's own secure forms.
- **Metadata** (`as_of`, timezone, scope, cursor, counts) is validated and screened as well.
- Detectors are defense in depth. The app must still classify and minimize fields before sending them.

## User memory

Memory is off until an admin turns it on for an app. When it is on:

- A memory belongs to the user named by the verified `X-Hub-Delegation` token. The Hub
  stores a keyed hash of app, tenant and user, never a value the model supplies, so one
  user can never read another user's memory.
- Content is encrypted with `SECRET_ENCRYPTION_KEY` before it is stored. It is checked for
  personal data and credentials on the way in (the same guard as every tool call) and
  again on the way out.
- Administrators see settings and counts only. The admin API has no route that returns
  memory content, and backups never include it.
- Each app sets a retention period (7 to 365 days) and a note limit. Expired memories are
  deleted on the user's next call and by the purge operation; admins can delete all of an
  app's memories at once. Deleting the app deletes them too.
- Memory is user context, not instructions: tool results say so, and the model is never
  trained on it.

## Hub chat

- The Claude key (`ANTHROPIC_API_KEY`) lives in the Hub's environment. OpenAI-compatible provider
  keys are added by super admins under **AI providers**, encrypted with `SECRET_ENCRYPTION_KEY`,
  never returned (only the last four characters), and included in backups as ciphertext. Apps and
  browsers never see any model key; apps call `/chat/v1` from their server with a client key.
- Provider addresses follow the connector egress rules: HTTPS unless `ALLOW_INSECURE_HTTP`, no
  credentials in the URL, private and loopback addresses only when `EGRESS_ALLOW_PRIVATE` /
  `EGRESS_ALLOW_LOOPBACK` allow them, ports from `MODEL_EGRESS_ALLOWED_PORTS`, and only
  `MODEL_EGRESS_ALLOWED_HOSTS` when that list is set. Each turn resolves the host again and pins
  the connection to the checked addresses; redirects are not followed.
- The Hub stores no conversation. The app sends the visible history each turn; history entries
  with personal data are dropped and a new message with personal data is refused before any
  model call.
- The system prompt states the safety rules first; an admin's instructions are added after them
  and checked for personal data. Tool results, memories and earlier messages are marked as data.
- Every tool call in a chat goes through the same dispatch as MCP: key permission, tool switch,
  personal-data check, source permissions and audit. Write tools only produce proposals.
- Per-user limits: `CHAT_RATE_LIMIT` per minute and the app's daily message limit, keyed by the
  signed user (or the client key without one). Counters are per process.
- The model provider receives an opaque per-user hash (`metadata.user_id`) for abuse detection,
  never a name or email. Claude Opus and Sonnet requests opt in to server-side fallback
  (`fallbacks: "default"`): a declined request is retried on Anthropic's fallback model.

## Egress and upstream calls

- HTTPS only, unless `ALLOW_INSECURE_HTTP` is set for development. URLs with credentials, metadata hosts, link-local addresses and ports outside the allowlist are refused. Private and loopback addresses need explicit development flags. Production needs `EGRESS_ALLOWED_HOSTS` or `EGRESS_ALLOWED_CIDRS`.
- DNS is resolved, checked, and the connection pinned to the checked IP, keeping the original Host and TLS name. Redirects are never followed and proxy variables are ignored.
- Responses are streamed and cut at the size cap. Attempts share one deadline. Only GET retries. Five consecutive upstream failures open a 30-second circuit.
- Paused or archived apps refuse every call immediately.

## Limits

Defaults: 60 calls per key and tool per minute, 8 concurrent calls per tool and per
upstream host, 50 records per page or read call, and 1000 records or 20 seconds per report.
Request bodies are capped (admin 1 MB, MCP 2 MB). The counters are in memory: run one
worker.

## Audit

Every tool call and admin change records action, actor id, app, tool, result, error code,
duration, retries and trace id. Payloads, results, prompts, tokens and secrets are never
stored or logged. JSON logging drops free-form messages and exception text. The UI shows
key names and admin emails by resolving ids at display time.

## Production configuration

`ENVIRONMENT=production` refuses to start with insecure cookies, MFA off, insecure HTTP/TLS,
private or loopback egress, no egress allowlist, SQLite, or missing encryption/session
keys. The Compose file is a development stack.
