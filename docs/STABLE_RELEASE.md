# Stable release requirements

Scope: the existing Hub PRD and Laravel connector PRD, including P0 and the P1
business-operation features. Optional RAG/vector infrastructure and deployment of
connected applications remain outside the connector product scope.

The release is not ready merely because a version has no alpha suffix.

| Area | Required behavior | Current gap |
|---|---|---|
| Resource API | Reviewed reads and create/update/delete proposals | Implemented; local and hosted package compatibility matrices and isolated upgrade checks passed |
| Write approval | Authenticated application user, CSRF, exact proposal binding, revalidation, transactions, idempotency and status reconciliation | Isolated HTTP flow and independent native PostgreSQL worker races passed |
| Onboarding | One-use enrollment, installation/source binding, expiry, atomic claim, resume and read-only credentials | Persistent recovery/renewal UI and APIs implemented; expiry/replacement/claim verified on isolated fixtures |
| Application settings | Application-owned authorization, session/CSRF, no secrets in HTML, deny-by-default grants | Protected settings implemented; finish migration and release review |
| Application SDK | MCP client, scoped model listing/chat, bounded transport and safe errors | Implemented; isolated HTTP/chat/provider simulation passed |
| Developer setup | Model candidates without record reads, explicit reviewed registration and safe generator | Implemented with closed generated defaults; development guide added |
| Reporting/export | Actor-bound downloads, expiry, reauthorization and bounded output | Private queued CSV/XLSX/PDF implemented; worker/download, artifact and concurrency checks passed |
| Upgrade/migration | Repeatable installation, connection preservation, migration preview and rollback | Code-only pilot passed with environment/config hashes unchanged; original application untouched |
| Hub features | Tool management, source synchronization, chat/gateway, reporting, skills, audit and backup | Scoped profiles and reviewed OpenAPI draft import implemented; finish release review |
| Security | Permission/tenant boundaries, revocation, replay, SSRF/TLS, privacy, secret storage and dependency audit | Modern dependency audits clean; legacy host advisory/vendor review remains a real-application cutover gate |
| Compatibility | Laravel 5.8–13 retained, reference patches and real PHP runtimes | All thirteen hosted rows passed the final 116-test suite; separate PostgreSQL and asset jobs also passed |
| Release | Verified source/artifacts, recovery evidence, stable Composer installation without version suffix | Gate until the required work and evidence are complete |

## Write workflow contract

1. The authenticated Hub may request a proposal at
   POST /api/ai/v1/{resource}/commands/{operation}.
2. A signed, one-use actor assertion and the current resource policy are required.
   The resource must explicitly register the operation, a closed input schema and
   an application-owned command handler. Writes are off by default.
3. Preparation stores an encrypted, expiring payload. It returns an opaque
   proposal reference and safe status, never a committed success.
4. Confirmation belongs to the application's authenticated web session and CSRF
   boundary. AI arguments cannot approve a proposal. The application user must
   resolve to the exact proposal actor and tenant.
5. Commit locks the proposal, checks expiry/current permissions/configuration,
   invokes the application's business handler in a transaction, and records the
   result once. The handler must recheck record scope and concurrency/version
   constraints. A failed transaction must not leave a committed receipt.
6. Status and cancellation enforce the same actor boundary. Repeated commit of
   the same proposal returns the existing receipt without repeating the write.
7. The Hub exposes proposed versus committed state explicitly. Existing direct
   source write routes remain compatible; proposal routes declare their workflow.

## Release evidence

Record each check with its actual target (unit, isolated application, simulated
HTTP or live integration). A simulation does not establish production behavior.
Known upstream issues on EOL Laravel/PHP remain documented compatibility limits;
installing the connector does not restore upstream security maintenance.

Stable publication requires completion of the table, the compatibility matrix,
Hub regression checks, dependency reviews, source-to-Hub integration, and
installation/upgrade/recovery checks. No production data writes are used for
release verification.

## Work in progress (29 October 2026)

- Both repositories use feature/stable-1.0 branches. No stable tag, production
  deployment or aaPanel access has been performed.
- Hub baseline: 278 tests. Latest full SQLite regression: 363 passed and two
  PostgreSQL-only concurrency tests skipped (365 collected), including
  real Redis limits shared between independent processes, fail-closed readiness,
  enrollment replacement/renewal/disconnect, profiles, proposals and scalar contracts.
- Full PostgreSQL regression: 363 tests passed, including concurrent pairing
  replacement and OpenAPI import. Two further malformed export-event cases passed
  in a focused nine-case regression after that full collection.
  A real PostgreSQL upgrade/downgrade/upgrade preserved fixture identities,
  pairing rows and encrypted credentials. The equivalent SQLite test also runs
  with foreign-key enforcement enabled.
- Package development code now includes transactional CRUD proposals, canonical
  previews, record-version/scope checks, session/CSRF confirmation, encrypted
  metadata, durable SQL replay prevention, opaque actor-bound record references,
  pairing/resume, a Gateway SDK, protected settings/chat UI, candidate discovery,
  a closed resource generator, status/sync/disconnect and package-only migrations.
- All thirteen declared package compatibility rows passed locally, each collecting
  113 tests and skipping the two opt-in HTTP/native-PostgreSQL tests. This used
  actual PHP 7.2/7.3/8.0/8.4 containers and native PHP 7.4/8.1/8.2/8.3 runtimes.
  Three later manifest-boundary/privacy cases bring the final suites to 116 tests
  each, with the same two opt-in skips. All thirteen hosted CI combinations passed
  this final collection. Earlier isolated HTTP checks exercised transport separately.
  [Package PR #2](https://github.com/ardanayatraa/laravel-mcp-hub/pull/2) contains the
  reviewed branch; [CI run 40856404324](https://github.com/ardanayatraa/laravel-mcp-hub/actions/runs/40856404324)
  passed all fifteen jobs on commit `9b8e7628d2211221c57e068c1c7c3a2f96e31464`.
  A documentation-only follow-up at `5ff6b23` also passed all fifteen jobs in
  [CI run 40857417214](https://github.com/ardanayatraa/laravel-mcp-hub/actions/runs/40857417214).
- The separate native PostgreSQL package suite passed 71 assertions with
  independent synchronized workers: duplicate approvals produced one write,
  competing record updates produced one commit/version conflict, repeated
  preparation reused its receipt, wrong actors were denied, and concurrent
  exports stayed within the two-job actor capacity.
- Package maintenance now registers hourly pruning through the host scheduler;
  source readiness checks required nonce/command/export columns. References bind to
  source/environment as well as actor/tenant. Command scalar constraints reject
  null-only, duplicate-type and oversized schemas before Hub publication.
- MCP profiles restrict modules/tools across listing, direct calls, reports,
  skills and client-key previews. Tests cover app scope, CSRF, stale revisions,
  disabled bindings, backup/restore and preserving restrictions on key replacement.
  The Access UI was exercised against an isolated Hub. A real Laravel HTTP call
  saw exactly three selected read tools; disabling its profile refused the next
  call. This used dummy data, separate ports and no connected application's data.
- Isolated Laravel 13.39/PHP 8.3 and Hub integration: pairing/resume, two-actor
  scoped reads, proposal preparation, browser approval, CSRF/wrong-actor denial,
  committed status reconciliation and immediate source permission revocation
  were exercised. No connected application's business data was used.
- Real HTTP Gateway completion and browser chat/tool/proposal/cancellation were
  exercised with a local Postman model simulation. This establishes local
  interoperability, not production provider or aaPanel behavior.
- Recovery history, renewal/replacement/revocation controls and expiring one-use
  pairing codes are available in the application keys tab. Metadata reads no
  longer mutate expiry. Renewal checks app ownership before expiry changes;
  lifecycle mutations lock the connector before its enrollment consistently.
  Independent PostgreSQL workers accept exactly one concurrent replacement.
- OpenAPI JSON/YAML preview/import creates selected drafts only. It reuses the
  reviewed connector's endpoints, fields and constraints, rejects remote refs,
  YAML aliases/extensions/duplicate keys, and pins bounded HTTPS downloads without
  credentials or redirects. Tests cover fingerprint races, atomic imports,
  scope/CSRF before fetch and malformed documents. The browser created a draft
  whose Publish action remained disabled until a passing test.
- Source-owned exports include CSV/XLSX/PDF and bounded grouped numeric metrics.
  Seventeen package tests exercise authorization, encryption, expiry, changed
  grants/data, queue/account failures, formula/HTML injection and capacity.
  Real Laravel 13 database queue workers produced CSV/PDF; authenticated HTTP
  downloads returned 200 for the owner and 404 for another user. XLSX ZIP/XML/cell
  types were independently read; PDF text and rendered layout were checked.
  The Hub accepts the generated manifest and dispatches actor-bound export/status
  read tools with POST idempotency. Chat export events carry references only;
  the Laravel widget constructs its own authenticated same-origin route.
- The updated backend dependency audit found no known vulnerabilities. Modern
  package development dependencies also audit clean after symfony/mime was
  patched to 7.4.22. The PHP 7.2/Laravel 5.8 fixture reports 17 known historical
  upstream advisories in five packages; its baseline check passed. These are
  compatibility limitations, not security fixes or production audit exceptions.
- The aaPanel deployment guide and controller are prepared under deploy/aapanel.
  Nineteen tests passed in a local Linux container using temporary filesystem
  state, a simulated service and a fake pg_dump. Nginx syntax, workflow lint and
  shell lint were checked locally. Server credentials stay in shared/hub.env;
  deployments gate pending schema changes and never run database downgrades.
- .gitignore excludes local environments, keys, generated sandboxes, nested
  checkouts and QA images. HANDOFF.md was removed from staging and retained
  locally. .dockerignore restricts build context to required runtime source.
- A code-only private application pilot adopted the public path package without
  changing its environment or connector configuration. Its native connector suite
  passed 85 tests/1,052 assertions and its client suite passed 11 tests/33 assertions.
  Guarded migration/rollback tests preserve concurrent edits. The original
  application was not changed. Fresh installation exposed a host-owned vendor
  customization and 56 upstream findings across 17 host dependency packages;
  these require host review before real cutover. Fixture advisory exceptions
  must not be copied into that application.
- A local Postman metadata smoke test ran four fixed virtual users for 61 seconds
  with a 12-second delay per request: 16 requests, p95 330 ms, no request or
  assertion failures. This checks Source health/capabilities only and establishes
  no production capacity. An initial attempt reached an offline fixture; it was
  repeated after readiness was restored. Results were not uploaded to Postman.
- Workflow lint passed for Hub CI, aaPanel deployment and package tests. Export
  chat assets and Composer validation also passed. Metadata-only summaries are
  in [STABLE_LARAVEL_MATRIX.json](evidence/STABLE_LARAVEL_MATRIX.json) and
  [STABLE_REMAINING_FEATURES.json](evidence/STABLE_REMAINING_FEATURES.json).
- The Composer candidate archive passed inspection: 78 files, with runtime assets,
  translations and metadata migrations present and development/credential files
  excluded. Its contents match the committed source at `5ff6b23`, with normalized
  line endings; its SHA-256 is
  recorded in the metadata-only evidence. CI artifacts were downloaded and each
  final result/audit was checked, rather than relying only on the workflow badge.
- Remaining release work is review/merge of the publication branch and creating
  the stable release, together with Hub branch review/CI. A real application cutover
  additionally needs its host dependency/vendor review. Activating the aaPanel
  deployment remains a separate operator action; no server access is needed for
  these code changes.
- The existing local Hub remains on its existing schema on 18000 with no reload.
  Use the isolated test stack for new migrations; do not restart that live Hub.
