# HiReach MCP local load verification (2026-10-13)

Target: local HiReach MySQL database `hireachtest`. The persistent fixture is marked
`MCPLOAD261013` and belongs only to users 5256 and 5257 (`@example.invalid`). It
contains two billing profiles and 1,520 synthetic blast messages: 1,200 visible
for account A, 300 visible for account B, and 20 soft-deleted for account A.
Messages have terminal statuses, dummy numbers, and were inserted without
dispatching SMS jobs. Existing business records were not intentionally changed.

Live verification through MCP Hub and HiReach:

- Source health and authentication, six published tools, owner-scoped counts and
  first pages, private field exclusion, and denied unauthenticated/invalid tools.
- Account A pagination: 24 pages of 50, all 1,200 unique records with no account B
  rows. The final page reports complete coverage.
- Reports: account A stops at the 1,000-record cap and reports partial coverage;
  account B counts all 300 and reports complete coverage.
- Billing profile update preparation: own proposal and idempotent replay succeed;
  conflicting reuse, cross-owner access, and invalid fields are denied. No
  proposal was committed and the profile was unchanged.
- HiReach AI: tool discovery and both capability and count chat requests returned
  HTTP 200; the count answer included 1,200. The first chat attempt returned
  HTTP 503 during model discovery, then succeeded on retry. A temporary Sanctum
  token was revoked after each run.

Automated results:

- MCP Hub: 219 tests passed; Ruff passed.
- HiReach `McpConnectorTest`: 72 passed. `AiIntegrationTest`: 51 passed.
- High-volume `ScaleAndIsolationTest`: 73 passed (one new scale test plus the 72
  inherited connector tests); the scale test has 693 assertions.
- Entire HiReach suite: 432 passed, 18 failed, 1 warning, 3 skipped. All MCP and AI
  integration tests above passed when the source project could write its test
  cache/export files. The remaining full-suite failures are outside those targeted
  files and were not resolved in this verification.

The live test encountered HiReach's 60-requests/minute throttle when phases were
combined; independent phases passed after the limit window cleared. A controller
fix now marks the final list page complete when `has_more` is false; regression
coverage was added in the source project and the Laravel overlay.

Important test isolation caveat: HiReach's `phpunit.xml` sets `APP_ENV=testing`
but leaves `DB_CONNECTION` and `DB_DATABASE` commented out. The broad suite used
local `hireachtest` and persisted additional test-generated records (post-fixture
audit: +96 users, +44 billing profiles, +96 blast messages). The marked MCP fixture
remained intact. These extra records were not deleted because they are not all
uniquely marked; future broad runs should use a dedicated test database.

Local verifier: `integrations/laravel/live_load_verify.py --phase
smoke|pages|reports|proposal`. The ignored `.verification/hireach-load-seed.json`,
`.verification/hireach-load-verify.json`, and
`.verification/hireach-ai-live-verify.json` hold machine-readable results without
committing credentials.

## Browser-session follow-up: User 4

The local Brave tab was signed in as the seeded HiReach `User 4` (ID 4). Its old
chat said it could not access Templates. Read-only inspection showed that
`hireachtest.templates` contained zero rows and the active AI integration had
registered only Billing Users and Blast Messages. The repository's
`ActionsAndTemplatesSeeder` would create one template for user 4, but it had not
been applied to this database. The earlier 1,520-message fixture belonged to
synthetic users 5256/5257, not the browser account. Before this follow-up, user
4 had 6 active blast rows and one billing profile; a stored older chat said 2.

The local-only, idempotency-guarded `.verification/seed-hireach-user4.php`
inserted 240 terminal-status dummy blast rows and 80 disabled templates for user
4, all marked `MCPUSER4-261013`. It also inserted 20 disabled templates for the
existing synthetic user 5256 to test owner isolation. No SMS jobs or template
actions were dispatched. The active AI integration now registers Templates with
name, type, enabled state and creation time only; access is read-only and scoped
to the current user. Create, update and delete remain disabled. This integration
setting applies to local users generally, but each user can query only their
own templates.

On the actual browser session, the AI answered: `berapa blast` = 246,
`berapa template saya?` = 80, and `Tampilkan template terakhir saya.` =
`MCPUSER4-261013 Template 079` (disabled). Its capability answer now includes
Templates alongside Billing Users and Blast Messages. The MCP verifier
`.verification/verify-hireach-user4-mcp.php` passed 11/11 checks: capabilities,
both account counts, blast count, 50+30 pagination, own and foreign lookups,
forbidden owner override/write, missing authentication, and temporary-token
catalog. The verifier revokes its temporary Sanctum token. The one-time MCP
assertion must be freshly signed for each request; reusing it correctly yields
403. The browser tab remains available with these chat answers.
