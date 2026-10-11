# Product Requirements Document (PRD)

# Python MCP Data & Skill Hub

> **Document version:** 1.2 — requirements reconciliation (54 controls)  
> **Date:** October 10, 2026  
> **Status:** Revised PRD — scope baselined; detailed technical design and threat model required before build  
> **Product:** Python MCP Hub + Web Admin UI  
> **Reference application:** Your App (framework-agnostic example)  
> **Target integrations:** Any application implementing the Connector API Contract  
> **Primary priorities:** Data security, modular connectors, and reusable skills

**Naming convention:** *Your App* is a generic connected application, built with Laravel, Node.js, or another stack. *App B* and *App C* represent additional connected applications. **Connected Application** means any application integrated with the Hub; none of these names is a product dependency.

---

## 0. Executive Summary

Build **Python MCP Data & Skill Hub**, a centralized platform exposing AI tools, JSON processing, reporting, analytics, visualization, and secure CRUD orchestration through the **Model Context Protocol (MCP)**. A dedicated **Web Admin UI** lets administrators add application connectors, discover published capabilities, enable modules, configure access limits, inspect tools, assign reusable skills, and audit activity. Applications implementing the supported connector contract can be onboarded without changing the Python core.

**Non-negotiable architectural decisions:**

1. **Connected Applications own business data.** They alone query their business databases and commit CRUD transactions. The Hub never receives connected-application database credentials.
2. **Model Discovery is not unrestricted ORM/table exposure.** Applications publish only developer-reviewed, allowlisted capabilities.
3. **Sensitive data is removed before it leaves the source application.** Additional guards operate at Hub ingress and before any LLM input. Hiding values in the UI is not sufficient.
4. **MCP is neither an AI model nor a business database.** It exposes callable tools and structured results; an AI client/orchestrator decides when to call them.
5. **Generic CRUD is a validated command contract, not arbitrary model execution.** Reads process authorized datasets; writes are prepared and committed by the owning application.
6. **The Admin UI is the control plane; MCP runtime is the execution plane.** They share policy and registry services while keeping authorization boundaries separate.
7. **Browser automation is explicitly out of scope.**
8. **Secure tool gateway, not an autonomous agent:** MCP exposes permitted tools but does not bypass source authorization, discover unrestricted endpoints, or dispatch unreviewed AI-selected HTTP methods.
9. **Read-only P0 MVP:** write generation, proposals and approvals, OpenAPI import, and OAuth connector management are progressively introduced after the read-only security baseline passes.

---

## 1. Background and Problem Statement

Business applications need AI features for answering questions about current data, proposing business operations, generating reports, filtering records, calculating metrics, rendering chart specifications, and exporting results. Building these capabilities independently in each application duplicates code, weakens governance, and complicates maintenance.

**Core problems:**

- Duplicate AI tools and analytics skills across applications.
- Adding a module requires code changes in multiple services.
- No central UI for connector setup, contract verification, and access configuration.
- Overexposed personal data due to broad API responses.
- Generic CRUD that bypasses record authorization or business rules.
- Large reporting jobs without proper queues, job status, and private artifact management.

### 1.1 Vision

One Python MCP Hub serving multiple applications through a **standard Connector API Contract**, **reusable tools and skills**, and **privacy by design**.

### 1.2 Goals

| ID | Goal | Success measure |
|---|---|---|
| G-01 | UI-based onboarding | Compatible apps connect without modifying or redeploying Python core |
| G-02 | Dynamic capability discovery | Developer-published modules are discoverable but disabled by default |
| G-03 | Secure CRUD orchestration | Authorized read/prepare/commit, with no direct business DB access |
| G-04 | Reusable data skills | One filter/aggregate/report skill works with datasets from at least two connectors |
| G-05 | PII isolation | Blocked PII does not reach tool output or LLM input in canary tests |
| G-06 | Operational visibility | Every tool execution has a trace ID, duration, outcome, and safe audit event |
| G-07 | Incremental delivery | A complete single-application workflow ships before broad feature expansion |

### 1.3 Non-Goals

- Browser Use, browser automation, scraping, or RPA.
- Generating arbitrary SQL against connected business databases.
- Executing user-uploaded Python scripts from the Admin UI.
- Granting Hub administrators universal access to customer business data.
- Replicating connected-application databases into the Hub.
- Running a general-purpose, model-directed HTTP proxy that accepts arbitrary URLs or HTTP methods at execution time.
- LLM training or fine-tuning.
- Public connector/skill marketplace in MVP.
- A vector-database RAG product in MVP; provide only an extension point for a later phase.

---

## 2. Personas, Actors, and Trust Boundaries

| Actor | Responsibilities | Authority boundary |
|---|---|---|
| Platform Super Admin | Hub operations, environments, global policies | No automatic access to customer business records |
| Connector Developer | Build application API/manifest and verify compatibility | Cannot override end-user or record permissions |
| Application Admin | Connect applications and configure module/skill access | Limited by developer-approved capabilities |
| AI End User | Use tools and skills through an application's AI chat | Limited to their own authorized records/actions |
| Approver | Authorize high-risk operations | Approval applies to one specific actor/action/payload |
| Auditor | Review execution and policy events | No raw secrets or personal data in routine logs |
| AI Client / Orchestrator | Select and call tools for user requests | Model output never establishes authorization |

**Trust boundaries:**

- **Connected Application Backend:** owns database access, end-user login, tenant scopes, record/field policies, business validation, and transaction commits.
- **Application Privacy Gateway:** removes blocked fields before JSON leaves the application.
- **Python Hub:** owns connector metadata, registries, tool execution, skills, processing, and safe audit metadata; it is not the final authority for business permissions.
- **LLM Provider:** receives only necessary, authorized context. Prompts, tool arguments, retrieved text, and tool output are untrusted inputs.
- **Admin UI:** manages Hub configuration; it never reads application database tables directly.

---

## 3. Logical Architecture

```text
[Your App AI Chat / AI Client]                         [MCP Hub Admin UI (Vue)]
             |                                                |
      Authenticated User                              Admin API (FastAPI)
             |                                                |
      Application AI Gateway --------------------------- [Config & Registries]
             |                                                |
       MCP Tool Call -----> [MCP Python Runtime] <--------------+
                                  |
                       [Policy & Privacy Guard]
                                  |
                           [Tool / Skill Engine]
                                  |
                       [Data Processor / Reporter]
                                  |
                        [Connector Contract Adapter]
                                  |
             Connected App API <---- authenticated, scoped ---->
                 |
     [Business Policy + PII Allowlist + Query + CRUD Commit]
                 |
             [Application DB]

     Hub PostgreSQL = configuration, metadata, jobs, and audits;
     NOT a replica of connected applications' business databases.
```

### 3.1 Data Flow Modes

**Mode A — Push JSON (MVP default for dataset skills):** The Connected Application reads its database, applies record scope and field allowlists, then passes an approved JSON dataset to an MCP tool through its AI Gateway. The Hub processes that input and returns results. The Hub never requests business data directly in this mode.

**Mode B — Controlled Pull (optional, Phase 2 for business datasets):** The Hub calls a constrained application query endpoint with a valid service identity and verified end-user delegation. The application defines the query, scopes, and output fields. **This never grants direct database access.**

**REST-to-MCP mapping note (P0):** A reviewed read-only REST endpoint can be invoked through the Hub even during Phase 1; this is distinct from generic free-form `query` over all models. API ownership and per-user source authorization remain mandatory. **A shared connector API key is only service authentication, not proof of end-user permission.** In P0, private record endpoints must receive source-verified delegated user context (a scoped token specifically meant for the source API, or a verifiable first-party gateway identity) and enforce source-side row/field/tenant permissions. If such delegation is unavailable, **do not publish that endpoint**; use source-initiated Push JSON for private user-scoped datasets or public/non-sensitive aggregate endpoints. Never let an AI-provided `user_id` determine authorization.

**CRUD writes (Phase 2):** The Hub produces a proposed command. The application UI/backend obtains approval when necessary and invokes **its own commit handler**. The application returns a JSON receipt. Direct external MCP-client commits through the Hub require a separate delegated-auth design and are **outside MVP scope**.

### 3.2 Deployment Architecture

- **Web UI:** Vue 3, TypeScript, Tailwind CSS.
- **Backend:** Python 3.12+; FastAPI for Admin API; official MCP Python SDK v2 (`MCPServer`) for the MCP runtime. One repository with separately protected ASGI applications/routes.
- **Hub metadata DB:** PostgreSQL via SQLAlchemy 2.x and Alembic migrations; use isolated connection roles.
- **Queue:** Redis with Celery or another vetted Python worker chosen in detailed design.
- **HTTP client / validation:** httpx for upstream connectors, Pydantic v2 for all tool/configuration schemas; the MCP SDK may use its own HTTP transport dependencies.
- **Processing:** Standard Python first; Pandas or Polars if dataset sizes justify the dependency.
- **Exports:** openpyxl for XLSX; ReportLab or a vetted template renderer for PDF.
- **Deployment:** Docker Compose for MVP, Nginx reverse proxy, TLS/HTTPS, Docker health checks and environment-specific configuration (dev/staging/prod).
- **Source control/build:** Git, reproducible lockfiles (`uv.lock` for Python and `pnpm-lock.yaml` or equivalent for UI), dependency vulnerability checks, CI tests and gated CD.
- **Transport:** Streamable HTTP is primary; local STDIO is optional P2 and must use the same policy checks.
- **MCP profiles:** one default profile P0; multiple logical MCP server profiles with client/tool allowlists P1. No unbounded user-defined Python server processes.

Target MCP transport: **Streamable HTTP**, using the planned **MCP 2026-07-28** specification and client compatibility testing. Honor version-specific behavior including stateless requests and tool-list caching; do not assume older session or HTTP GET streaming behavior by default.

---

### 3.3 Protocol and Compatibility Baseline

- Follow the official Python SDK **v2 stable line**, not a handwritten JSON-RPC/MCP implementation. Pin a tested 2.x minor/patch in the lockfile; review SDK upgrades in CI.
- Target the MCP **2026-07-28** specification while testing fallback interoperability for selected older clients. The specification is versioned independently of the SDK.
- Validate the Streamable HTTP `Origin` header on every inbound request; reject disallowed origins with HTTP 403. Protect DNS rebinding, local binding, TLS and bearer token scope.
- Expose tool discovery and execution through the SDK; dynamically selected tool visibility does **not** grant authorization. The Hub re-evaluates policy on every call.
- Treat public specifications as the wire contract and this PRD's REST paths as **application-specific** contracts, not MCP protocol requirements.

## 4. Scope and Priorities

**P0 — Phase 1 (Read-only MVP):** Python 3.12+, official MCP SDK, FastAPI Admin API, Vue 3/TypeScript/Tailwind UI, PostgreSQL/SQLAlchemy/Alembic, authentication, Docker Compose/Nginx/TLS, connector onboarding, API Key/Bearer auth, manual **read-only REST-to-MCP mapping**, tool builder GUI, dynamic read-only registry, tool preview/test, source manifest discovery, permission, field allowlist, PII ingress/egress controls, in-memory JSON processing, audit/health, CI and a reference generic application (Your App). MVP has **one MCP runtime profile** and Streamable HTTP.

**P1 — Phase 2 (Business Operations):** reviewed OpenAPI import, versioned CRUD generator, prepare/approve/commit, per-model write controls, approval UI, advanced PII policy management, multiple MCP server profiles / scoped tool exposure, analytics, reports/export, controlled pull after verified delegation, stronger worker/job support, and a second application. **Core PII filtering is already mandatory in P0; Phase 2 adds management flexibility.**

**P2 — Phase 3 (Advanced):** connector OAuth 2.0 lifecycle, full multi-tenancy enhancements, circuit-breaker tuning and advanced observability, optional STDIO for local clients, RAG, scheduled/cross-app workflows, advanced performance optimization and developer SDK templates. External MCP client delegation is enabled only after an explicit threat model and interoperability testing.

---

## 5. Admin UI — Information Architecture

```text
Dashboard
Apps & Connectors
  - App List
  - Add Connector Wizard
  - Connector Detail / Health
  - Manifest Sync / Version History
Modules
  - Discovered Modules
  - Enabled Modules
  - Operation Permissions
  - Field Privacy Policy
Tools
  - Registry / Versions
  - Tool Builder GUI (Read-only in MVP)
  - REST-to-MCP Mappings
  - OpenAPI Import / Review (P1)
  - Inspector / Dry Run
MCP Servers
  - Server Profiles / Client Tool Exposure (P1)
Skills
  - Built-in Skill Library
  - Skill Assignment by App
Operations
  - Approvals
  - Processing Jobs
  - Reports / Artifacts
Observability
  - Execution Logs / Audit
  - Metrics / Connector Errors
Security
  - Policy Configuration
  - Credential Rotation
  - Service Identities
Settings
  - Admin Users / Roles
  - Environments
```

### 5.1 Dashboard (P0)

- **FR-UI-01:** Show active/failing connectors, enabled modules, available tools, success/failure rates, retries, latency, and pending approvals.
- **FR-UI-02:** Every metric supports time range, environment scope, and drill-down into execution logs.
- **FR-UI-03:** Operational views do not display raw PII from tool results.

### 5.2 Add Connector Wizard (P0)

1. **Application:** Name, `app_key`, environment, and connector type (HTTP Contract / Data Push).
2. **Endpoint:** Base URL, manifest path, TLS verification, and network/SSRF validation.
3. **Authentication:** Scoped service credentials or approved OAuth/OIDC mechanism; store securely and support rotation.
4. **Test Connection:** Authenticated health check; no production writes.
5. **Discover Capabilities:** Fetch and validate the manifest; show developer-published modules.
6. **Module Policy:** Select modules/operations and configure privacy restrictions that **cannot be weaker** than the application's policies.
7. **Review & Publish:** Preview settings, test synthetic JSON, then activate.

**Acceptance:** Any application implementing the standard contract can be activated without writing a dedicated Python connector. Non-conforming APIs require a reviewed developer adapter; the UI must not execute arbitrary uploaded code.

### 5.3 Module Manager (P0)

- Show module key, description, schema version, application, discovered/enabled status, operations, privacy status, and last sync.
- **Add Module** lists only unactivated modules from the validated manifest, **not every ORM class or database table**.
- Activation is scoped by application/environment; new modules are **disabled by default**.
- Field policy options: `allowed_for_ai`, `blocked`, `aggregate_only`, `secure_form_only`. Application policies define the upper bound of access.
- Policy changes take effect on subsequent operations. Runtime reauthorization is mandatory even if a client caches a tool list.

### 5.4 Tool Inspector (P0)

- Display input/output schemas, synthetic sample payloads, correlation ID, and results.
- Require **Dry Run** for write proposals. Production commits are unavailable from the Inspector without additional controls.
- Hide secrets, sensitive stack traces, and private record data from errors.

### 5.5 Skill Manager (P1)

- Built-in skill catalog with versions, schemas, tool dependencies, status, application scopes, resource budgets, and execution history.
- Admins may enable/disable approved skills, not upload arbitrary `handler.py` scripts for execution.
- Developers ship new skills through code review, tests, build, and deployment.

---

### 5.6 Tool Builder GUI and REST-to-MCP (P0 read-only; P1 writes)

**P0 Tool Builder form:** connector, tool key/description, endpoint **from an approved connector base URL**, HTTP method (GET and safe POST-based queries only), path-parameter mappings, query/body parameters, Pydantic/JSON Schema input and output definitions, max payload, timeout, pagination, error mapping, field/privacy rules, risk classification, and audit level. Restrict parameters to allowlisted fields, types, enums and bounded values. Path templates must be resolved by the adapter, **not raw model-generated URLs**.

**P0 manual REST-to-MCP conversion:** Administrators can register an existing read-only REST operation as an MCP tool through the UI without changing Python source. Publishing user-scoped resources requires a verifiable source-user authorization mechanism, not merely one shared service credential. The tool remains `draft` until schema validation, network/SSRF checks, safe Test Tool execution, and authorized publish. A generic HTTP adapter executes fixed vetted mappings. The admin may not supply arbitrary script, shell command or dynamic transport headers containing secrets.

**P1 write mappings:** POST/PATCH/DELETE are **not exposed as arbitrary HTTP proxy functions**; only registered business commands with prepare/approve/commit handlers and idempotency can be published. A permission-aware CRUD generator creates **draft** tools from developer-approved model capabilities; each generated operation is independently reviewed and activated.

**P1 OpenAPI import:** Import OpenAPI 3.x from an uploaded JSON/YAML file or a network-allowlisted HTTPS URL. Parser produces *draft candidates only* (operationId, method, path, parameter schema, responses and auth requirements). Validate external references and restrict/disable remote `$ref` retrieval; reject executable extensions and oversized/recursive schemas. Admin previews per-operation data sensitivity, edits mappings, tests against synthetic/staging data, then explicitly publishes. Importing an OpenAPI spec never auto-enables write tools.

### 5.7 MCP Server Management (P1)

Support multiple **managed MCP server instances**, initially hosted as separately configured SDK server profiles (`default`, `your-app`, `partner-client`) and optionally co-located under one ASGI deployment. Each server instance has a canonical endpoint/mount, independent enabled/disabled state and health, approved connector/tool versions, permitted client audiences, quotas, and policy version. The UI can create/configure, pause, resume, discover, and test instances. Per-instance **tool publishing** is independent, but the Hub's security policies always apply. Never spawn an arbitrary process or execute uploaded code from a GUI definition. Later physically isolate instances as independent deployments where scale or compliance requires it. Tool-name collisions are prevented by namespaced identifiers. Every `tools/list` and `tools/call` is scoped to verified caller identity and server policy; a profile URL by itself is not authorization. Infrastructure deployment/restarts remain controlled by operations. 


## 6. Connector Contract for Connected Applications

### 6.1 Contract Principles

Connectors do not perform unrestricted ORM introspection. They operate on a **validated capability manifest** and an **authenticated JSON API**.

These endpoints describe the product's **application integration contract**, not mandatory MCP protocol routes:

| Method | Application endpoint | Purpose | MVP |
|---|---|---|---|
| GET | `/api/ai/v1/health` | Service health | Yes |
| GET | `/api/ai/v1/capabilities` | Safe capability manifest | Yes |
| POST | `/api/ai/v1/query` | Authorized query (Controlled Pull) | Optional P1 |
| POST | `/api/ai/v1/commands/prepare` | Validate a proposed write | Phase 2 |
| POST | `/api/ai/v1/commands/commit` | Commit through the owning application | Phase 2; app approval flow only |
| GET | `/api/ai/v1/commands/{id}` | Command status and reconciliation | P1 |

Push-mode datasets can be supplied as MCP tool input from the Application AI Gateway, without using the query endpoint.

### 6.2 Example Module Capability Manifest

```json
{
  "contract_version": "1.0",
  "application": "your_app",
  "manifest_version": "2026-10-10.1",
  "modules": [
    {
      "key": "projects",
      "name": "Projects",
      "description": "Project management resource in the connected app",
      "schema_version": "1.0",
      "supported_operations": ["read", "create", "update"],
      "readable_fields": ["ref", "name", "status", "created_at"],
      "writable_fields": ["name", "status"],
      "filters": {
        "status": {"type": "string", "enum": ["active", "pending", "completed"]}
      },
      "max_page_size": 50,
      "risk": {"read": "low", "create": "medium", "update": "medium"}
    }
  ]
}
```

`application`, `module.key`, and `schema_version` are stable identifiers. Breaking contract changes require a schema-version increment. The manifest defines **maximum supported capabilities**, not an end user's permissions.

### 6.3 Standard JSON Response Envelope

```json
{
  "success": true,
  "request_id": "req_01JEXAMPLE",
  "module": "projects",
  "schema_version": "1.0",
  "data": [{"ref": "prj_125", "name": "Website Villa", "status": "active"}],
  "meta": {
    "as_of": "2026-10-10T09:00:00+08:00",
    "timezone": "Asia/Makassar",
    "scope": "authorized_records",
    "coverage": "complete",
    "total_count": 1,
    "has_more": false
  }
}
```

If `coverage=partial`, the AI **must not** claim the result includes all matching data. `total_count` is included only if the application computes it within the caller's authorized scope. Never leak emails, phone numbers, or sensitive identifiers through `meta`, error messages, tracing, or record references.

### 6.4 Error Envelope

```json
{
  "success": false,
  "request_id": "req_01JEXAMPLE",
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Operation is not permitted"
  }
}
```

Use appropriate HTTP status codes: `400` malformed request; `401` unauthenticated; `403` forbidden; `404` missing or intentionally hidden resource; `409` conflict/idempotency collision; `422` validation failure; `429` rate limit; `5xx` service errors. Avoid revealing inaccessible object existence.

---

### 6.5 Connector Authentication Profiles and Lifecycle

- **P0:** API Key and scoped Bearer Token authentication. Store only encrypted secrets/secret references. Never echo credentials to LLM inputs, output, event streams, or diagnostics; support revoke/rotate.
- **P2:** OAuth 2.0 connector flow with explicit issuer, audience, expiry, scope and redirect URI validation; approved client credentials or authorization-code/PKCE flow as appropriate. Separate MCP client OAuth tokens from upstream API credentials; no transparent token passthrough.
- All connector calls enforce bounded timeouts, rate limits, TLS verification, egress rules, DNS/IP/redirect protection and credential origin pinning. A connector can be paused without affecting others.
- Health UI records status, response latency and categorized failure (TLS, DNS, authorization, timeout, schema mismatch). Redact request headers and response bodies by default.
- An application manifest describes maximum operations but never establishes a runtime user's access; downstream API must reauthorize each call.


## 7. CRUD Orchestration and Runtime Tool Design

### 7.1 MCP Tool Registry (P0)

Prefer **stable global MCP tools** rather than adding/removing Python functions globally for each user. Runtime authorization is mandatory.

| MCP tool | Main input | Output | MVP |
|---|---|---|---|
| `list_capabilities` | App key | Modules available to the caller | Yes |
| `process_dataset` | Safe dataset, operation, parameters | Transformation or aggregate | Yes |
| `prepare_crud_command` | App, module, operation, payload | Structured proposal, **not a commit** | P1 |
| `validate_crud_proposal` | Proposal reference | Validation/approval requirement | P1 |
| `get_operation_status` | Operation reference | Commit/job status | P1 |
| `generate_report` | Authorized dataset ref and template | Report job/artifact ref | P1 |
| `create_chart_spec` | Safe dataset and chart type | JSON chart specification | P1 |

Stable tools plus caller-scoped capability discovery reduce cross-user tool-list leakage and cache inconsistencies. `tools/list` is **not** an authorization boundary; every `tools/call` revalidates access. Return structured JSON (`structuredContent` where client support permits) with a safe fallback.

**Dynamic registry lifecycle:** `draft → validated → approved → published → disabled → archived`. Tools have globally unique **namespaced keys** such as `your_app.projects.read`, semantic versions, immutable published schemas, owner identity, connector binding, policy version, and a manifest/source hash. Publishing creates a reviewed tool revision; edit creates a new revision. Tool names returned to clients use a stable MCP-safe mapping and cannot collide. Verify approval on publish and authorization on **every** call, even when MCP clients cache `tools/list`.

**No arbitrary AI routing:** Never accept raw `base_url`, free-form HTTP method, database model class or endpoint path from an AI call. The request supplies a published tool identifier and schema-bounded arguments; the server resolves its fixed approved route from the registry. Generic built-in tools may remain globally registered, but data scope still comes from trusted request identity. In P0 only read-only mappings are publishable.

### 7.1.1 REST-to-MCP Tool Mapping (P0)

Example **admin-authored draft definition** (never sent as an unrestricted AI tool argument):

```json
{
  "tool_key": "your_app.projects.list",
  "version": "1.0.0",
  "connector_key": "your_app",
  "http": {
    "method": "GET",
    "path_template": "/api/v1/projects",
    "timeout_ms": 5000
  },
  "input_schema": {
    "type": "object",
    "properties": {
      "status": {"type": "string", "enum": ["active", "completed"]},
      "limit": {"type": "integer", "minimum": 1, "maximum": 50}
    },
    "additionalProperties": false
  },
  "output_policy": {"allow_fields": ["ref", "status", "created_at"]},
  "risk": "read_only",
  "status": "draft"
}
```

Production publishing requires connector-owner approval and a validated source-side data/field policy. A read-only **HTTP method** is not sufficient proof of safety: validate side effects and disallow state-changing query endpoints.


### 7.2 CRUD Read

- `module_key` must be a registry alias, **never** an arbitrary `App\\Models\\...` class or table name.
- Push mode receives approved datasets; optional Pull mode calls a constrained application query endpoint.
- Filtering/sorting is limited to fields and operators explicitly declared in the schema.
- Record scope, tenant filters, and field minimization belong to the Connected Application.
- Pagination, payload limits, and dataset `coverage` metadata are mandatory.

### 7.3 CRUD Create / Update / Delete (P1 — Phase 2)

1. AI creates a **proposed action** based on a user request.
2. Hub validates input schema, enabled module, operation policy, and internal constraints.
3. Connected Application `commands/prepare` verifies **user authority, values, relationships, and business rules**, then issues a `proposal_ref`, safe summary, expiry, and approval requirement.
4. If required, the user approves the exact action through a trusted application UI, not through a model-generated boolean.
5. Connected Application rechecks role/record/field permissions and record version before commit.
6. Connected Application executes a business command handler in a transaction and returns a minimal receipt.
7. AI can claim success only after a confirmed `committed` status.

**Default policy:** Simple creates may auto-commit only under an explicit low-risk policy. Sensitive updates and bulk changes require approval. Deletes and privilege changes are denied by default or subject to strict approval. The owning application can reject any proposal.

### 7.4 Example Prepare Command (P1)

```json
{
  "app_key": "your_app",
  "module": "projects",
  "operation": "create",
  "payload": {"name": "Website Villa", "status": "pending"},
  "idempotency_key": "7b497724-8bb1-4be0-a7f5-6b0d36ccb32e"
}
```

Prepare response:

```json
{
  "success": true,
  "proposal_ref": "prop_7bc9",
  "approval_required": true,
  "summary": "Create project Website Villa with pending status",
  "expires_at": "2026-10-10T09:10:00+08:00"
}
```

The application must bind `proposal_ref` server-side to user identity, app, tenant, payload hash, operation, policy version, and expiration. **Never accept** AI-generated `approved=true` as proof of approval. Revalidate at commit and enforce idempotency, transactions, concurrency control, and auditing.

### 7.5 Example Laravel Connector Implementation (Optional)

If a Connected Application uses Laravel:

- Use `config/ai_modules.php` as the developer allowlist for modules, handlers, fields, and operations.
- Use an `AiModuleRegistry` service to publish capabilities.
- Use Policies/Gates for function-level and record-level authorization with tenant scoping.
- Return only AI-safe fields using DTOs/API Resources and closed output schemas.
- Use registered query/filter handlers; **never execute arbitrary SQL or dynamic Eloquent class injection**.
- Route commands through existing application business services, not bypass controllers.
- Store admin status/permissions in the application's own DB, never exceeding developer limits.

The Hub may cache capability metadata but is **not the final authority**. Application-side disable/revoke actions must be enforced on the next execution.

---

### 7.6 Tool Testing and Lifecycle Requirements

- Tool Inspector test cases: valid/invalid input, authentication failure, denied permission, malformed upstream JSON, wrong content type, timeout, rate limit, oversized payload, private field and nested PII canaries.
- P0 tool testing uses synthetic data, mocked adapters or safe staging endpoints; write tools are unavailable for production execution before Phase 2's approval gateway.
- Input/output Pydantic and JSON Schema validation must run on **every** execution, not only at tool registration. If schema validation fails, fail closed.
- Test result displays request ID, redacted input, safe normalized JSON response, duration, status code, schema failures and policy decision.
- Tool publish requires verified endpoint, privilege grant, accepted test suite and approval; disabling must block execution even if tool discovery was cached.


## 8. Privacy and Sensitive Data Protection (P0 — Release Blocking)

### 8.1 Field Classification

| Policy | Behavior | Examples |
|---|---|---|
| `blocked` | Value must not leave the application for Hub/LLM | Passwords, tokens, phone numbers, emails, national IDs |
| `secure_form_only` | Value entered directly in application UI; never through AI chat | Customer email/phone during create/update |
| `aggregate_only` | Application computes statistics; individual values stay private | Salaries, balances, sensitive metrics |
| `allowed` | May leave only when user/tenant/record access and necessity are verified | Project status, activity timestamps |

**Default deny:** No field is exposed until explicitly allowlisted. Developer/organization privacy rules are hard limits; an admin cannot change `blocked` to `allowed`.

### 8.2 Privacy Gates

1. **Source Application Gate:** Select allowlisted fields, serialize via safe DTO/API Resource, apply tenant/record/field permissions. Never return raw `Model::all()` output.
2. **Hub Input Gate:** Validate JSON schema, nested fields/arrays, dataset size, and content classification; reject invalid input.
3. **LLM Egress Gate:** Send only the required safe summary/results. Inspect tool output, prompt templates, errors, logs, RAG documents, and attachments before any model request.
4. **Output Gate:** Protect exports, logs, links, and frontend views from unintended disclosure. This does not replace the first three gates.

**Regex/PII detectors are defense in depth**, not proof that text is safe. Reject ambiguous free text or summarize it within the source application if safe filtering cannot be guaranteed.

### 8.3 Sensitive Information in User Input

If a user enters an email or phone number in an AI Chat field that is sent to a model, **the value has already reached the model before any tool runs**. For customer Create/Update with PII, AI returns intent and opens a **secure application form**. The user supplies private fields directly to the application backend, never the LLM.

### 8.4 Mandatory Privacy Tests

- Inject canary emails, phone numbers, and national IDs into blocked fields; none may appear in LLM requests, tool results, files, logs, or errors.
- Inspect nested `notes`, `description`, `metadata`, attachments, and error messages.
- Audit events contain metadata, not raw payloads or tokens.
- Aggregations respect tenant/record scope; no leaks through unrestricted global counts.
- Misconfigured admin settings cannot weaken developer-locked policies.
- Temporary jobs and artifacts honor TTL and verified deletion policies.

---
## 9. Data Processing Skills

### 9.1 P0: Built-in Data Tools

- `filter` with allowlisted operators such as `eq`, `in`, `gte`, `lte`, and `between`, validated against field types.
- `sort` restricted to allowlisted fields and directions.
- `count`, `sum`, `avg`, `group_by`, and basic time-series summaries.
- `transform` for non-sensitive field mapping, date normalization, and null handling.
- Mandatory timezone, reference time (`as_of`), completeness, and numeric-precision validation.

### 9.2 P1: Reusable Skills

| Skill | Input | Output |
|---|---|---|
| Reporting | Safe datasets/aggregates and report template | JSON summary, PDF, XLSX, or CSV |
| Visualization | Safe dataset/aggregates and chart type | JSON chart specification for ECharts/Chart.js |
| Analytics | Authorized dataset and metric definitions | Data-grounded quantitative insights |
| Export | Approved dataset/report result | Private artifact with short-lived signed access |
| Workflow | Validated tool steps and dependencies | Step status, outputs, and audit events |

**No arbitrary Python code from a manifest may execute.** Skill handlers and dependencies must be allowlisted and developer-released. `SKILL.md` may describe instructions/workflows but must not automatically be treated as executable code.

### 9.3 P2: RAG (Optional)

RAG is appropriate for semantic retrieval of authorized documents, SOPs, and knowledge content. Live transactional data, inactive-user counts, and current project states continue to come from the Connected Application. Retrieval must enforce tenant/role/record authorization **before** material enters the AI context. The document index must track source updates and deletions.

### 9.4 Example: Users Inactive for at Least Three Days

1. The Connected Application defines what *active* means (login versus meaningful activity) and supplies a timezone-aware reference time.
2. The application retrieves authorized records or computes an aggregate directly if individual identities are unnecessary.
3. The Hub receives only approved `last_active_at`/status values or an aggregate `total_inactive`, with no email/phone.
4. The Hub returns counts/filters and explicit `scope`, `coverage`, and `as_of` metadata.
5. If the UI must show names, the application fetches identity data through its own authenticated frontend API; the AI model never receives those identities.
6. `last_active_at=null` follows an explicit **never active** policy and is not silently counted as "inactive for 3 days."

---

## 10. Security, Identity, and Authorization (P0)

### 10.1 Authentication

- **Admin UI:** Secure login; MFA for administrators; `HttpOnly`, `Secure`, and `SameSite` cookies; CSRF protection.
- **MCP HTTP:** Authenticate all private endpoints; validate token issuer, audience, expiration, scope, signature, clock skew and revocation as supported. Apply Origin validation for Streamable HTTP to reduce DNS rebinding exposure.
- **Service-to-service:** Connector identity must be separate from end-user identity; support API Key and Bearer in P0, OAuth 2.0 connectors in P2; use scoped identities, rotation, and a proper secret store.
- **Never:** Blindly forward a raw MCP client token to the Connected Application if that token's audience is not the application API. Use an explicitly designed delegation/token-exchange flow or the first-party Application Gateway.

### 10.2 Layered Authorization

Each request checks **app, tenant, user, module, operation, record, field, consent/approval, and environment**. Hub Admin policies are additional restrictions, **not substitutes** for the Connected Application's own authorization (for example, Laravel Policies).

### 10.3 Connector Security (SSRF)

- Do not allow arbitrary connector URLs to reach loopback, link-local, cloud metadata, or private IP addresses unless explicitly approved by infrastructure policy.
- Validate DNS resolution and re-resolution, resolved target IP, port, redirects, TLS certificates, and HTTP methods.
- Send connector credentials only to authorized origins; never forward them to an unrelated redirected host.
- Restrict network egress to approved application destinations; validate redirect targets independently at each hop, pin credentials to the expected upstream origin and re-check address resolution to mitigate DNS rebinding.

### 10.4 Tool and Skill Risk Controls

- Every tool uses structured input validation, explicit JSON types, and maximum lengths.
- Tool lists may be cached, but **every `tools/call` must re-evaluate authorization**.
- Large reads enforce pagination, quotas, size limits, and resource budgets.
- Creates/updates require idempotency keys. Updates should enforce optimistic concurrency (`expected_version`/ETag) where supported.
- Deletes and bulk updates require explicit approval; offer preview and soft delete when applicable.
- Use audit integrity and command-status reconciliation to avoid false success claims after timeouts or uncertain commits.
- Treat tool output, descriptions imported from OpenAPI, third-party manifest names, retrieved documents, and database strings as **untrusted content** to resist prompt injection and tool poisoning. Never let tool metadata change system instructions or trusted policies.

### 10.5 LLM Boundary and Observability

- Do not log raw sensitive payloads, access tokens, or full prompts by default.
- Structured logs include trace ID, hashed principal/reference, app/module/tool, status, duration, and error code.
- Validate tool output schemas and JSON before forwarding results to the model.
- Prevent CSV/Excel formula injection when exporting user-supplied text.
- Enforce retention/deletion rules on all temporary datasets and artifacts; temporary JSON is in-memory by default with capped size, and any optional dataset reference has tenant-scoped TTL and revocation.

---

### 10.6 Failure Handling and Security Release Gates

- **Fail closed:** If token verification, policy lookup, tenant scope, privacy filtering, tool schema, approval verification or source authorization fails, do not run the tool or return data; log only redacted decision metadata.
- **Rate limiting:** Per client, app, tenant, tool and upstream; enforce concurrency and request-body limits at ingress and workers.
- **Retry policy:** Automatically retry only idempotent reads under bounded exponential backoff and jitter. For writes, retry only with an upstream-supported idempotency key and a separate operation-status reconciliation path; otherwise return an uncertain state for investigation.
- **Circuit breakers:** Basic upstream failure isolation and timeout in P0; configurable thresholds, half-open recovery and operational UI are P2.
- **Approvals:** High-risk bulk deletion, financial changes and security/role changes require an explicit human decision bound to exact payload, target, actor, policy version and expiry; default deny absent valid approval.
- **Release gate:** No sensitive production writes until token audience, object/field/tenant authorization, PII canary tests, idempotency, approvals and rollback/recovery have passed in staging.


## 11. Hub Persistence and Database Model

The Hub database stores configuration and operational metadata, **not permanent copies of business datasets**.

| Entity | Key fields (conceptual) | Notes |
|---|---|---|
| `applications` | id, key, name, environment, status | Unique `(key, environment)` |
| `mcp_server_profiles` | id, key, endpoint, client_policy, status | Multiple logical servers (P1) |
| `mcp_profile_tools` | profile_id, tool_id, enabled, policy_version | Caller-filtered exposure (P1) |
| `connectors` | id, app_id, type, base_url, auth_type, status | Versioned configuration |
| `connector_secrets` | connector_id, secret_ref, rotated_at | Store vault references, not plaintext secrets |
| `connector_health_checks` | connector_id, status, latency, last_error | Operational history |
| `module_definitions` | app_id, module_key, schema_version, manifest_hash | Manifest synchronization |
| `module_settings` | module_id, enabled, policy_version | Disabled by default |
| `field_policies` | module_id, field_path, classification, source | Developer hard limits cannot be weakened |
| `tool_definitions` | tool_key, version, connector_id, mapping_id, input/output_schema, status, approved_by, hash | Immutable published versions and namespaced uniqueness |
| `rest_tool_mappings` | id, connector_id, endpoint_path, fixed_method, timeout, policy | Read-only REST-to-MCP mapping (P0) |
| `openapi_import_jobs` | id, connector_id, source_digest, review_status | Draft-only import (P1) |
| `skill_definitions` | skill_key, version, status, handler_ref | Do not store executable scripts in DB |
| `skill_app_assignments` | skill_id, app_id, enabled, limits | Application-scoped assignment |
| `approval_requests` | id, actor_ref, proposal_hash, expires_at, status | Single-use, bound approval |
| `command_executions` | id, idempotency_key, app_id, status, request_id | Scoped uniqueness |
| `processing_jobs` | id, owner_ref, job_type, status, result_ref | Worker/job state |
| `report_artifacts` | id, owner_ref, object_key, expires_at | Private storage |
| `audit_events` | id, trace_id, action, actor_ref, result, created_at | No raw PII |

Use SQLAlchemy 2.x declarative models, Alembic migration scripts, transactional changes and tested down/forward migration procedures. Minimum indexes: `(app_id,module_key)`, `(connector_id,status)`, `(trace_id)`, `(owner_ref,created_at)`. Enforce idempotency uniqueness within `(app_id, actor_scope, key)`. Design cleanup, deletion, and retention from the beginning.

---

## 12. Admin API, MCP Endpoint, and Structured Output

### 12.1 Admin REST API (Examples)

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/admin/v1/connectors` | Register a connector |
| POST | `/api/admin/v1/connectors/{id}/test` | Validate health and credentials |
| POST | `/api/admin/v1/connectors/{id}/discover` | Fetch/validate capability manifest |
| GET | `/api/admin/v1/modules` | List module registry |
| PATCH | `/api/admin/v1/modules/{id}/settings` | Enable/disable and restrict policies |
| GET | `/api/admin/v1/tools` | List built-in and published tools |
| POST | `/api/admin/v1/tools` | Create reviewed draft REST-to-MCP mapping |
| PATCH | `/api/admin/v1/tools/{id}` | Edit draft; published revisions are immutable |
| POST | `/api/admin/v1/tools/{id}/publish` | Approve and publish version after checks |
| POST | `/api/admin/v1/openapi/import` | Parse into draft candidates only (P1) |
| GET | `/api/admin/v1/mcp-profiles` | List logical MCP server profiles (P1) |
| POST | `/api/admin/v1/mcp-profiles` | Create reviewed server profile (P1) |
| POST | `/api/admin/v1/tools/dry-run` | Test without production writes |
| GET | `/api/admin/v1/skills` | List skills |
| GET | `/api/admin/v1/executions` | Audit tool executions |
| GET | `/api/admin/v1/jobs` | Processing job status |

### 12.2 MCP Transport

- Canonical endpoint: `POST https://hub.example.com/mcp` for Streamable HTTP; a per-profile mounted path is optional P1.
- Per-app endpoints such as `/mcp/your-app` are **optional** and never replace authentication or caller scoping. Prefer one global endpoint in MVP.
- Delegate wire-level MCP handling (JSON-RPC, protocol headers, discovery, error framing) to the official Python SDK. **Do not invent a custom MCP wire protocol.**
- Do not require `GET /mcp` for the targeted 2026-07-28 transport version; validate actual client interoperability against the applicable specification. An optional STDIO transport for trusted local development is P2.
- Tool responses use validated JSON with `success`, `data`, `meta`, `trace_id`, and declared output schemas.

### 12.3 Example Processed Dataset Result

```json
{
  "success": true,
  "data": {"inactive_user_count": 12, "period_days": 3},
  "meta": {
    "as_of": "2026-10-10T09:00:00+08:00",
    "scope": "authorized_users",
    "coverage": "complete",
    "contains_personal_data": false
  },
  "trace_id": "tr_0182c3"
}
```

**Note:** The value `12` is illustrative; production results must come from validated, appropriately scoped data.

---

## 13. Target Project Structure

```text
mcp-hub/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI ASGI entry
│   │   ├── config.py                  # Environment/config validation
│   │   ├── api/v1/                    # Admin REST
│   │   │   ├── auth.py
│   │   │   ├── connectors.py
│   │   │   ├── modules.py
│   │   │   ├── tools.py
│   │   │   ├── skills.py
│   │   │   ├── approvals.py
│   │   │   └── executions.py
│   │   ├── mcp/
│   │   │   ├── server.py              # MCPServer registration
│   │   │   ├── profiles.py            # P1 server profiles & client tool scopes
│   │   │   ├── tool_router.py
│   │   │   └── request_context.py
│   │   ├── connectors/
│   │   │   ├── contracts.py
│   │   │   ├── http_adapter.py
│   │   │   ├── auth_profiles.py       # API Key/Bearer; P2 OAuth
│   │   │   ├── discovery.py
│   │   │   ├── ssrf_guard.py
│   │   │   └── registry.py
│   │   ├── capabilities/
│   │   │   ├── registry.py
│   │   │   └── policy_service.py
│   │   ├── tools/
│   │   │   ├── builder.py             # Admin-controlled tool draft
│   │   │   ├── rest_mapper.py         # Fixed REST-to-MCP mappings
│   │   │   ├── openapi_importer.py     # P1 draft-only importer
│   │   │   ├── process_dataset.py
│   │   │   ├── prepare_command.py
│   │   │   └── list_capabilities.py
│   │   ├── skills/
│   │   │   ├── registry.py
│   │   │   ├── executor.py
│   │   │   ├── analytics/
│   │   │   ├── reporting/
│   │   │   └── visualization/
│   │   ├── privacy/
│   │   │   ├── schema_guard.py
│   │   │   ├── pii_inspector.py
│   │   │   └── output_guard.py
│   │   ├── security/
│   │   │   ├── auth.py
│   │   │   ├── authorization.py
│   │   │   ├── approval.py
│   │   │   └── audit.py
│   │   ├── services/
│   │   │   ├── processing.py
│   │   │   ├── commands.py
│   │   │   └── reporting.py
│   │   ├── persistence/
│   │   │   ├── models/             # SQLAlchemy 2.x
│   │   │   ├── migrations/         # Alembic
│   │   │   └── session.py
│   │   └── jobs/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── security/
│   │   └── contract/
│   ├── uv.lock
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   ├── components/
│   │   ├── services/
│   │   ├── router/
│   │   └── stores/
│   ├── pnpm-lock.yaml
│   └── package.json
├── infra/
│   ├── compose.yml
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── docs/
│   ├── CONNECTOR_CONTRACT.md
│   ├── SECURITY.md
│   ├── API.md
│   └── ARCHITECTURE.md
├── .env.example
├── .github/workflows/ci.yml
├── README.md
└── PRD.md
```

**Modularity rule:** `connectors/http_adapter.py` reads connector configurations from the Hub DB. Do not create a new Python file automatically for every onboarded application. If an API is nonstandard, implement a versioned adapter through normal development and deployment, never with arbitrary code submitted through the Admin UI.

---

## 14. Non-Functional Requirements (NFR)

| ID | Category | Initial requirement |
|---|---|---|
| NFR-01 | Availability | Initial internal target of at least 99.5% monthly after monitoring exists; revisit SLA at scale |
| NFR-02 | Latency | p95 small-JSON processing <=3 seconds, **excluding** source-app/AI-provider time; benchmark required |
| NFR-03 | Payload | Per-tool request size/record limits; initial example 1 MB/50 records pending load tests |
| NFR-04 | Background jobs | Large exports/reports run asynchronously; progress and cancellation targeted for P1 |
| NFR-05 | Retention | Temporary datasets and artifacts have TTL; audit metadata retention follows organizational policy |
| NFR-06 | Secrets | Secret manager/encrypted store or injected environment; never in Git or UI responses |
| NFR-07 | Isolation | Tenant-aware queries; auth-scoped cache keys or no shared caching of personal data |
| NFR-08 | Observability | Correlated metrics/errors/traces without raw sensitive payloads |
| NFR-09 | Compatibility | MCP client conformance and manifest schema contract tests |
| NFR-10 | Recoverability | Hub DB backups, restore drills, job retries, and commit-status reconciliation |
| NFR-11 | Change safety | Versioned manifests, DB migrations, rollback strategy, and policy-diff review |
| NFR-12 | Concurrency | Define per-tool and connector concurrent-call budgets; benchmark CPU/RAM under representative loads |
| NFR-13 | API resilience | Timeout, bounded read retry, safe write reconciliation, per-upstream circuit breaker and quotas |
| NFR-14 | Delivery | Git versioning, locked dependencies, automated CI security/contract tests, gated CD, tested rollback |
| NFR-15 | Recovery | Scheduled metadata backup, encrypted backup storage, restoration exercises and RPO/RTO goals established before production |
| NFR-16 | Network transport | Streamable HTTP Origin validation, secure local binding, HTTPS and compatible-client verification |

These numeric values are **initial design targets**, not measured production results.

---

## 15. Acceptance Criteria / UAT

### UAT-01 — Add Connector via UI

**Given** Your App implements the Connector Contract, **when** an admin enters a valid URL/credential, runs Test Connection, and discovers capabilities, **then** the UI lists approved capabilities without changing Python core files.

### UAT-02 — Add Module

**Given** a manifest includes `projects`, **when** the admin enables `projects.read`, **then** the capability becomes available. Modules missing from the manifest cannot be added by supplying arbitrary model names.

### UAT-03 — Disabled or Revoked Access

**Given** a previously enabled module, **when** the application disables it or revokes a user's access, **then** the next call is denied even if the MCP client caches a tool name or older capability list.

### UAT-04 — Users Inactive for Three Days

**Given** an authorized dataset with `last_active_at` and `as_of`, **when** AI requests users inactive for >=3 days, **then** the count/list follows the configured timezone and activity definition, reports data `coverage`, and exposes no blocked PII to the model.

### UAT-05 — PII Leak Prevention

**Given** canary emails/phone numbers/national IDs are stored in blocked fields, **when** reads, filters, reports, errors, and exports run, **then** these values appear in no tool output, LLM request, log, error, or artifact.

### UAT-06 — Create Project (P1)

**Given** a user has project-create permission, **when** AI submits a proposal and the user authorizes it, **then** the Connected Application revalidates and commits it. MCP reports success only after an official commit receipt.

### UAT-07 — Privilege Escalation Attempt

**Given** a staff user, **when** the payload includes `role=admin`, an unrelated `tenant_id`, or an unregistered field, **then** it is rejected and no record is modified.

### UAT-08 — Retry and Idempotency (P1)

**Given** a create succeeded but its response timed out, **when** the request is retried with the same idempotency key, **then** only one record exists and its status can be reconciled.

### UAT-09 — Multi-Tenant Isolation

**Given** tenants A and B, **when** user A reads, counts, exports, or searches records, **then** tenant B data cannot be inferred through record lists, counts, errors, or analytics.

### UAT-10 — Connector SSRF

**Given** a connector URL points to loopback, link-local, cloud metadata, or redirects to a prohibited host, **when** the connection is tested, **then** the request is blocked and a safe audit reason is recorded.

### UAT-11 — Reusable Cross-Application Skill (P1)

**Given** Your App and App B are connected, **when** the same reporting skill processes both authorized datasets, **then** outputs follow the skill contract without rewriting reporting logic.

### UAT-12 — Compatibility and Security Regression

**Given** an MCP SDK, dependency, or manifest upgrade, **when** CI runs, **then** MCP conformance, schema contract, privacy regression, and authorization tests must pass before release.

---

### UAT-13 — Read-only REST-to-MCP Builder (P0)

**Given** a developer-allowlisted GET endpoint, **when** an admin maps its parameters/schema using the Tool Builder GUI and publishes after validation, **then** an authorized MCP client discovers and executes the fixed tool without source changes; a disabled, unauthorized, or unapproved mapping fails closed.

### UAT-14 — OpenAPI Import Review (P1)

**Given** a vetted OpenAPI spec, **when** the admin imports it, **then** only draft candidates appear, no write operation publishes automatically, risky references are rejected, and each operation requires explicit verification/approval.

### UAT-15 — Multiple MCP Server Profiles (P1)

**Given** two server profiles with different client tool policies, **when** clients list or execute tools, **then** each receives only authorized tools and direct calls to out-of-profile tools are denied.

### UAT-16 — Credential Rotation, Recovery, and Degraded Upstream

**Given** a revoked credential, restored metadata backup or failing upstream, **when** health or a tool execution runs, **then** credential access is denied after revocation, restored config remains encrypted/valid, and bounded timeout/circuit-breaker controls prevent cascading failures.



## 16. Testing and Quality Gates

- **Unit tests:** Schema validation, authentication policy, JSON processor, masking, `coverage` checks, policy evaluation, fixed REST mapping, tool registry/version collisions and command signatures.
- **Contract tests:** Manifest/schema, standard error format, versioning, optional Laravel example connector, fixed REST mappings, unknown-field rejection and imported OpenAPI draft schemas (P1).
- **Integration tests:** Application Gateway -> MCP runtime -> JSON result, API Key/Bearer auth, REST-to-MCP discovery/execution, OAuth (P2), approval/commit reconciliation (P1).
- **Security tests:** BOLA/BOPLA/BFLA, mass assignment, cross-tenant count leaks, SSRF, prompt injection, PII canaries, replay attacks, token audience, credential leaks, formula injection.
- **Load tests:** Pagination, concurrent client calls, large datasets, report jobs, quotas, connector timeouts, queue saturation, CPU/RAM trends and p95 latency.
- **Failure tests:** Redis outage, metadata DB outage, connector disable, interrupted commit, duplicate tool invocation, expired proposal, circuit-breaker threshold, backup restore and failed deployment rollback.

**Release blockers:** Authorization bypass, PII leakage, cross-tenant leak, unresolved double commits (P1), arbitrary SQL/class execution, credential exposure, exploitable connector SSRF, unsafe OpenAPI auto-publication or MCP transport conformance failures. CI/CD must block promotion while any critical release gate fails.

---

## 17. Implementation Roadmap

### Phase 1 — Read-only MVP (P0)

**1A — Foundation:** Python 3.12+, FastAPI, official MCP SDK v2, Vue 3/TypeScript/Tailwind, PostgreSQL + SQLAlchemy + Alembic; Git, lockfiles, CI/CD, Docker Compose/Nginx/HTTPS and admin authentication.

**1B — Connector & Tool GUI:** Register Your App using API Key/Bearer with the Add Connector Wizard; health/latency checks; manifest discovery; Module Manager; manually map one approved read-only REST operation to an MCP tool; Tool Builder schema/timeout/field controls; draft-review-publish versioning; inspect/test using synthetic data.

**1C — Safe Runtime:** Streamable HTTP, read-only registry and permissions, tenant/user-aware source delegation, bounded data push/processing, privacy and field allowlists, PII canary verification, error sanitization, rate limits, structured logs, audit, uptime and operational checks.

**Phase 1 exit:** All seven MVP acceptance checks in Section 20 pass; read-only REST-to-MCP tool onboarding does not require Python code changes. No automatic write mapping is available.

### Phase 2 — Business Operations (P1)

Implement reviewed OpenAPI import; safe CRUD Generator from developer-approved model allowlists; prepare/approve/commit; read/update/delete business action policy; enhanced PII Policy Manager; multiple logical MCP server profiles and client tool exposure; controlled pull where delegation is proven; report/analytics/export skills; job workers and a second application. Require source-owned commit receipts, idempotency and approval tests before production writes.

### Phase 3 — Advanced Platform (P2)

Add OAuth 2.0 connector setup/rotation, advanced tenant isolation and policy deployment, configurable circuit breakers and observability, optional local STDIO, RAG with authorization-aware indexing, cross-app workflows, scheduled jobs and targeted performance optimization.

**Mandatory sequencing:** Source-side privacy enforcement, every-call authorization, controlled tool mapping, MCP compatibility tests and CI security gates **precede** production CRUD write capabilities.

---

## 18. Initial Backlog — Epics and User Stories

| ID | Epic | User story | Priority |
|---|---|---|---|
| EP-01 | Foundation | As an admin, I can sign in and view a secure dashboard | P0 |
| EP-02 | Connector | As an admin, I can add a connector using a guided wizard | P0 |
| EP-03 | Discovery | As an admin, I can view developer-published application modules | P0 |
| EP-04 | Module Policy | As an admin, I can enable/disable modules and restrict operations | P0 |
| EP-05 | Privacy | As an admin, I can verify email/phone data never reaches AI | P0 |
| EP-06 | Tool Inspector | As an admin, I can test tools using synthetic datasets | P0 |
| EP-07 | Processing | As an end user, I can analyze authorized JSON data through AI tools | P0 |
| EP-08 | CRUD | As an end user, I can propose creates and obtain source-app commits safely | P1 |
| EP-14 | REST-to-MCP | As an admin, I can publish a reviewed read-only REST endpoint as an MCP tool through the UI | P0 |
| EP-15 | Tool Builder | As an admin, I can configure fixed method/path, Pydantic schema, timeout, and field policy without code | P0 |
| EP-16 | OpenAPI | As an admin, I can review imported OpenAPI operations as disabled draft tools | P1 |
| EP-17 | MCP Servers | As an admin, I can configure multiple MCP server instances and scope their tools to allowed clients | P1 |
| EP-18 | Recovery | As an operator, I can restore config and safely recover interrupted operations | P0 |
| EP-09 | Audit | As an auditor, I can trace each execution by correlation ID | P0 |
| EP-10 | Reporting | As an end user, I can generate reports and secure exports | P1 |
| EP-11 | Skills | As an admin, I can assign reusable skills to applications | P1 |
| EP-12 | Multi-App | As an admin, I can connect a second standards-compliant application | P1 |
| EP-13 | RAG | As an end user, I can semantically search authorized documents | P2 |

---

## 19. Risks, Trade-Offs, and Open Decisions

| Issue | Decision / trade-off |
|---|---|
| Push JSON only in MVP | Clear privacy boundary, but the application orchestrates reads and tool calls; selected for MVP |
| Controlled Pull | More flexible for generic MCP clients, but adds delegation and attack surface; P1 |
| One `/mcp` endpoint | P0 default; P1 logical profiles can expose separate paths, but identity/policy—not URL—determines access |
| REST-to-MCP | Only fixed allowlisted read-only mappings in P0; arbitrary proxy tool requests are forbidden |
| OpenAPI import | P1 draft-only parser with explicit admin review, no auto-publication |
| Multi-server | Start with logical profiles in one runtime; split deployments only when independent scaling/compliance warrants |
| Automatic discovery of all ORM models | Rejected; use reviewed allowlist manifests to protect hidden data and business rules |
| Generic writes without approval | Only under explicit low-risk policies; otherwise prepare/approve/commit |
| Whole datasets processed in Hub | Fine for small datasets, poor for massive/PII-heavy data; aggregate at source when practical |
| Skill uploads via UI | Rejected in MVP due to remote-code-execution risk; deploy reviewed handlers |
| Hub metadata database | Required for config/audit; must not become a permanent business-data mirror |
| Frontend framework | Vue 3 + TypeScript selected for modularity; can be revisited during design |
| Tenant model | Determine per-app versus per-organization isolation before final migrations |
| End-user identity | MVP uses first-party Application Gateway; external delegated OAuth clients targeted for P2 |
| User `name` field | Blocked from model context by default; application UI fetches identity itself if required |

**Decisions required before P0 implementation is finalized:**

1. Deployment target (private VPS, hostname, ingress and firewall rules).
2. Identity provider for Admin UI and connector service identities.
3. Tenant model and authoritative role scopes in the first Connected Application.
4. Minimal reviewed modules and fields for the first integration (`projects`, `tasks`, aggregate-only `users`).
5. Approval workflow and approver roles in the Connected Application UI.
6. Worker queue and private file-storage choices.
7. Approved staging/testing base URLs and egress CIDR/domain policy.
8. MCP client compatibility matrix and version-pinning policy.
9. Default privacy-field policy, audit retention, and breach-response escalation owners.

These open items do not block initial scaffolding, but must be resolved before their respective features ship.

---

## 20. MVP Definition of Done — Seven Mandatory Checks

The **Phase 1 MVP** is complete only when all seven items pass with written test evidence:

- [ ] **MVP-01 — Add a connected application through the UI.** An admin connects **Your App** using API Key or Bearer Token, tests health/authentication, and persists encrypted connector configuration.
- [ ] **MVP-02 — REST endpoint becomes a reviewed MCP tool.** A published, allowlisted read-only REST mapping is configured in Tool Builder GUI with schemas, timeout, fixed endpoint and privacy fields; no Python connector source edit is necessary.
- [ ] **MVP-03 — Client discovers and executes the tool.** At least one tested MCP client can discover it and obtain a validated JSON result over Streamable HTTP.
- [ ] **MVP-04 — Unauthorized access is rejected.** Denied users, out-of-scope tenants, disabled modules and unapproved tool mappings cannot execute, even with direct API calls or cached tool lists.
- [ ] **MVP-05 — Sensitive fields never reach the AI or logs.** Email, phone, national ID, credentials and blocked nested free text are absent from LLM requests, tool output and routine logs; canary tests pass.
- [ ] **MVP-06 — Restart does not lose configuration.** PostgreSQL/Alembic data and encrypted credential references persist across service restarts; a backup restore is demonstrated.
- [ ] **MVP-07 — Automated tests pass.** Unit, integration, MCP interoperability, schema, security and basic load/smoke tests pass under locked dependencies in CI.

**Additional P0 gates (not substitutes for the seven):** no business DB connection; reviewed module allowlist; field/row authorization by source API; request Origin/TLS and egress protections; audit traceability; error redaction; per-tool quotas and timeouts; documented deployment/rollback; and application/source governance.

**Phase 2 write release gate:** Do not enable production Create/Update/Delete until authorization, PII, approvals, idempotency, concurrency, failure reconciliation and business-handler integration tests pass.

---

## 21. Technical References

References reviewed for this revision dated October 10, 2026:

1. [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — Python server SDK, tools, Streamable HTTP, client/server examples.
2. [MCP Python SDK Documentation](https://py.sdk.modelcontextprotocol.io/) — SDK usage and API details.
3. [Model Context Protocol Specification, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) — target protocol and interoperability guidance.
4. [MCP 2026-07-28 Release Notes](https://blog.modelcontextprotocol.io/posts/2026-07-28/) — stateless transport and authorization changes.
5. [OWASP API Security Top 10 (2023)](https://api-security.owasp.org/editions/2023/en/0x11-t10/) — object/property/function authorization, resource consumption, SSRF.
6. [Python SDK v2 What’s New](https://py.sdk.modelcontextprotocol.io/whats-new/) — `MCPServer`, protocol compatibility and tools.
7. [MCP 2026-07-28 Streamable HTTP Transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) — endpoint and Origin rules.


## Appendix A — Compliance Traceability (54 Requirements)

All 54 provided requirements are specified below. **P0** means required for the read-only MVP, **P1** business operations, and **P2** advanced. A requirement marked P1/P2 is documented now, not necessarily implemented in Phase 1. Compliance below means **PRD coverage**, not working production implementation.

| ID | Requirement | PRD section(s) | Delivery |
|---|---|---|---|
| R-01 | Python 3.12+ FastAPI | 3.2, 17 | P0 |
| R-02 | Official MCP Python SDK | 3.2–3.3 | P0 |
| R-03 | Streamable HTTP / optional STDIO | 3.3, 12.2 | P0/P2 |
| R-04 | Vue 3 TypeScript Tailwind | 3.2, 5 | P0 |
| R-05 | PostgreSQL metadata | 3.2, 11 | P0 |
| R-06 | SQLAlchemy / Alembic | 3.2, 11 | P0 |
| R-07 | Pydantic validation | 3.2, 5.6, 7.6 | P0 |
| R-08 | Redis + workers when needed | 3.2, 9 | P1 |
| R-09 | Docker Compose Nginx HTTPS | 3.2, 17 | P0 |
| R-10 | Git lockfiles CI/CD | 3.2, 16–17 | P0 |
| R-11 | Connector manager CRUD/lifecycle | 5.2, 6.5 | P0 |
| R-12 | API Key Bearer OAuth2 | 6.5, 10.1 | P0/P2 |
| R-13 | REST-to-MCP converter | 5.6, 7.1.1 | P0 |
| R-14 | OpenAPI reviewed import | 5.6 | P1 |
| R-15 | Dynamic versioned tool registry | 7.1 | P0 |
| R-16 | Multiple managed MCP servers | 5.7, 12.2 | P1 |
| R-17 | Tool Builder GUI | 5.6 | P0 |
| R-18 | Safe CRUD generator | 5.6, 7.3 | P1 |
| R-19 | Tool test/dry run | 5.4, 7.6 | P0 |
| R-20 | Connector health / latency | 5.1–5.2, 6.5 | P0 |
| R-21 | Admin/MCP authentication | 10.1 | P0 |
| R-22 | RBAC/ABAC scopes | 10.2 | P0 |
| R-23 | Deny by default | 8, 10 | P0 |
| R-24 | Runtime auth every call | 7.1, 10.2 | P0 |
| R-25 | Source API authorizes | 2, 6, 10.2 | P0 |
| R-26 | Encrypted/rotated credentials | 6.5, 10.1 | P0 |
| R-27 | OAuth issuer/audience/scope | 6.5, 10.1 | P2 |
| R-28 | SSRF protections | 10.3 | P0 |
| R-29 | PII filtering | 8 | P0 |
| R-30 | Field allowlist | 8 | P0 |
| R-31 | Prompt injection / tool poisoning | 10.4 | P0 |
| R-32 | Fail closed | 10.6 | P0 |
| R-33 | Audit without secrets | 10.5, 11 | P0 |
| R-34 | Sensitive action approval | 7.3, 10.6 | P1 |
| R-35 | API-first, no source DB access | 3, 6 | P0 |
| R-36 | Developer model allowlist | 5.3, 6.2 | P0 |
| R-37 | Explicit CRUD mapping | 5.6, 7 | P0/P1 |
| R-38 | Verified user context | 2, 10 | P0 |
| R-39 | Response sanitization | 8, 10.5 | P0 |
| R-40 | Temporary in-memory processing | 3.1, 9 | P0 |
| R-41 | Tenant dataset isolation | 8, 10.2 | P0 |
| R-42 | Data TTL / retention | 8, 10.5 | P0 |
| R-43 | Pagination / limits | 7.2, 14 | P0 |
| R-44 | Safe writes, idempotency | 7.3–7.4, 10.4 | P1 |
| R-45 | Unit tests | 16 | P0 |
| R-46 | Integration tests | 16 | P0 |
| R-47 | MCP compatibility | 3.3, 16 | P0 |
| R-48 | Security regression tests | 15–16 | P0 |
| R-49 | Latency concurrency RAM/CPU | 14, 16 | P0 |
| R-50 | Timeout rate limit retries breakers | 10.6, 14 | P0/P2 |
| R-51 | Health/metrics/structured logs | 5, 10.5 | P0 |
| R-52 | Backup recovery rollback | 14, 16, 20 | P0 |
| R-53 | Required five docs | 13, 20 | P0 |
| R-54 | Release gate sensitive production | 10.6, 16, 20 | P0/P1 |

### Appendix A.1 — Reconciliation Summary

The v1.1 PRD already covered application-owned databases, data privacy, module allowlists, source authorization, JSON processing, audit, and secure write proposals. v1.2 adds **manual REST-to-MCP**, **Tool Builder GUI**, **reviewed OpenAPI import**, **MCP server profiles**, **dynamic versioned tools**, **API Key/Bearer/OAuth lifecycle**, **SQLAlchemy/Alembic**, **STDIO as optional**, **CI/CD lockfiles**, and more precise resiliency/backup controls. Write workflows were moved from MVP to **Phase 2** to match the supplied phased acceptance criteria.

### Appendix A.2 — Security Interpretation

Admin-reviewed tool publication is not the same as business-data permission. Read/write access must still be checked by the source application at operation time, with verified user context and row/field restrictions. A dynamically imported OpenAPI definition is untrusted metadata, not permission to call arbitrary endpoints. The Hub remains a **secure tool gateway**, not a model-directed unrestricted HTTP proxy.

---

**Final product direction:** Python MCP Hub is a **tool-and-skill platform with an Admin UI and a standardized Connector Contract**. Each Connected Application remains the **trusted owner and final authority for its business data**. Start with Your App using secure read-only REST-to-MCP mapping, approved JSON processing and privacy filtering; enable write workflows only after Phase 2 authorization and release tests pass.
