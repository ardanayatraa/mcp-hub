import { randomBytes } from "node:crypto";
import { HubError } from "./errors.js";
import { encryptSecret, iso, truthy } from "./security.js";
import { isSensitivePath } from "./privacy.js";
import { adminContext, appAccess, audit, bad, bool, bundle, conflict, id, json,
  missing, pick, role, textField, timestamp } from "./admin-common.js";
import { catalogForCaller, connectorSecrets } from "./catalog.js";
import { joinSourceUrl, sourceRequest, validateDestination } from "./source-http.js";
import { synchronizeConnector } from "./sync.js";
import { MEMORY_TOOLS, memoryAdminView, updateMemorySetting } from "./memory.js";
import { visibleSkills } from "./skills.js";

async function refreshManaged(db, config, context, filter = {}) {
  const failures = {};
  for (const row of await allConnectors(db, context, filter.environment)) {
    if (row.connector_type !== "source_managed" || row.status !== "active" ||
        (filter.connectorId && row.id !== filter.connectorId) ||
        (filter.appKey && row.app_key !== filter.appKey)) continue;
    try { await synchronizeConnector(db, config, row); }
    catch (error) {
      if (!filter.metadata) throw error;
      failures[row.id] = { code: error?.code ?? "SCHEMA_MISMATCH",
        message: error?.message ?? "Source synchronization failed" };
    }
  }
  return failures;
}

async function connectorView(db, row) {
  const latest = await db.one(`SELECT * FROM connector_health_checks WHERE connector_id = ?
    ORDER BY created_at DESC LIMIT 1`, [row.id]);
  const secret = await db.one(`SELECT rotated_at FROM connector_secrets WHERE connector_id = ?
    AND revoked_at IS NULL ORDER BY rotated_at DESC LIMIT 1`, [row.id]);
  const contract = await db.one(`SELECT manifest_version, created_at FROM contract_snapshots
    WHERE connector_id = ? ORDER BY created_at DESC LIMIT 1`, [row.id]);
  const moduleRows = await db.all(`SELECT s.enabled FROM module_settings s
    JOIN module_definitions m ON m.id = s.module_id WHERE m.app_id = ?`, [row.app_id]);
  const toolRows = await db.all(`SELECT status FROM tool_definitions WHERE connector_id = ?`, [row.id]);
  const managed = row.connector_type === "source_managed";
  return { id: row.id, app_id: row.app_id, app_key: row.app_key, name: row.app_name,
    environment: row.environment, connector_type: row.connector_type,
    base_url: row.base_url, manifest_path: row.manifest_path, health_path: row.health_path,
    auth_type: row.auth_type, status: row.status, tls_verify: bool(row.tls_verify),
    timeout_ms: row.timeout_ms, secret_configured: !!secret,
    secret_updated_at: timestamp(secret?.rotated_at), failure_count: row.failure_count,
    circuit_open: !!row.circuit_open_until && Date.parse(timestamp(row.circuit_open_until)) > Date.now(),
    health: latest ? { status: latest.status, latency_ms: latest.latency_ms,
      error_category: latest.error_category, checked_at: timestamp(latest.created_at) } : null,
    contract: contract ? { version: contract.manifest_version, synced_at: timestamp(contract.created_at) } : null,
    sources_total: managed ? moduleRows.filter((item) => bool(item.enabled)).length : moduleRows.length,
    sources_enabled: moduleRows.filter((item) => bool(item.enabled)).length,
    tools_published: toolRows.filter((item) => item.status === "published").length,
    tools_total: toolRows.filter((item) => managed ? item.status === "published" : item.status !== "archived").length,
    created_at: timestamp(row.created_at) };
}

async function allConnectors(db, context, environment) {
  const rows = await db.all(`SELECT c.*, a.key AS app_key, a.name AS app_name, a.environment
    FROM connectors c JOIN applications a ON a.id = c.app_id ORDER BY a.name`);
  return rows.filter((row) => (context.allowed === null || context.allowed.has(row.app_id)) &&
    (!environment || row.environment === environment));
}

async function moduleView(db, row) {
  const manifest = json(row.manifest_json, {});
  const policies = await db.all("SELECT * FROM field_policies WHERE module_id = ? ORDER BY field_path", [row.id]);
  const routes = [...(manifest.read_endpoints ?? []), ...(manifest.write_endpoints ?? [])];
  const types = {};
  for (const route of routes) for (const [name, spec] of Object.entries(route.output_schema?.items?.properties ?? {})) {
    types[name] ??= (Array.isArray(spec.type) ? spec.type.find((kind) => kind !== "null") : spec.type) ?? "string";
  }
  const report = routes.find((route) => route.output_schema?.maxItems > 1 &&
    (route.input_schema?.required ?? []).every((key) => ["limit", "cursor"].includes(key)));
  const tools = await db.one(`SELECT count(*) AS n FROM tool_definitions
    WHERE connector_id = ? AND module_key = ? AND status = 'published'`, [row.connector_id, row.module_key]);
  const baseline = Object.fromEntries(
    Object.entries(manifest.field_policies ?? {}).map(([key, classification]) =>
      [key, typeof classification === "string" ? classification : classification?.classification]));
  return { id: row.id, app_id: row.app_id, app_key: row.app_key, app_name: row.app_name,
    environment: row.environment, connector_id: row.connector_id, module_key: row.module_key,
    name: row.name, description: row.description, schema_version: row.schema_version,
    supported_operations: json(row.supported_operations, []),
    enableable_operations: manifest.enableable_operations ?? json(row.supported_operations, []),
    readable_fields: json(row.readable_fields, []), read_endpoints: manifest.read_endpoints ?? [],
    endpoints: routes.map((route) => ({ key: route.key, kind: route.kind,
      operation: route.operation ?? "read", method: route.method,
      path_template: route.path_template, requires_user_context: route.requires_user_context,
      public_aggregate: route.public_aggregate, safe_query: route.safe_query,
      tenant_field: route.tenant_field, input_schema: route.input_schema,
      output_schema: route.output_schema, max_items: route.output_schema?.maxItems,
      dataset: route === report })),
    enabled: bool(row.enabled), operations_enabled: json(row.operations_enabled, []),
    policy_version: row.policy_version, report_endpoint: row.report_endpoint,
    report_endpoint_effective: report?.key ?? null, report_endpoint_auto: report?.key ?? null,
    last_synced_at: timestamp(row.last_synced_at), tools: Number(tools?.n ?? 0),
    fields: policies.map((policy) => ({ field_path: policy.field_path,
      classification: policy.classification, baseline: baseline[policy.field_path] ?? "blocked",
      source: policy.source, locked: bool(policy.locked), type: types[policy.field_path] ?? null })) };
}

async function modules(db, context, query) {
  const rows = await db.all(`SELECT m.*, s.enabled, s.operations_enabled, s.policy_version,
    s.report_endpoint, a.key AS app_key, a.name AS app_name, a.environment,
    c.id AS connector_id, c.connector_type
    FROM module_definitions m JOIN module_settings s ON s.module_id = m.id
    JOIN applications a ON a.id = m.app_id JOIN connectors c ON c.app_id = m.app_id
    ORDER BY a.name, m.name`);
  return Promise.all(rows.filter((row) =>
    (context.allowed === null || context.allowed.has(row.app_id)) &&
    (!query.get("connector_id") || query.get("connector_id") === row.connector_id) &&
    (!query.get("app_key") || query.get("app_key") === row.app_key) &&
    (!query.get("environment") || query.get("environment") === row.environment) &&
    (row.connector_type !== "source_managed" || bool(row.enabled))).map((row) => moduleView(db, row)));
}

async function toolView(db, row) {
  const last = await db.one(`SELECT * FROM tool_test_runs WHERE tool_id = ?
    ORDER BY created_at DESC LIMIT 1`, [row.id]);
  const policy = json(row.output_policy, {});
  const schema = json(row.input_schema, {});
  return { id: row.id, tool_key: row.tool_key, mcp_name: row.mcp_name,
    title: row.title, display_title: row.title ?? row.tool_key, description: row.description,
    template: row.template, operation: ["create", "update", "delete"].includes(row.template) ? row.template : "read",
    version: row.version, status: row.status, connector_id: row.connector_id, app_id: row.app_id,
    app_key: row.app_key, app_name: row.app_name, environment: row.environment,
    source_managed: row.connector_type === "source_managed", module_key: row.module_key,
    module_name: row.module_name ?? row.module_key, method: row.method, path_template: row.path_template,
    input_schema: schema, output_schema: json(row.output_schema, {}), output_policy: policy,
    allow_fields: policy.allow_fields ?? [], report: json(row.report_spec), timeout_ms: row.timeout_ms,
    max_payload_bytes: row.max_payload_bytes, pagination: json(row.pagination, {}),
    error_mapping: json(row.error_mapping, {}), audit_level: row.audit_level,
    requires_user_context: bool(row.requires_user_context), tenant_field: row.tenant_field,
    safe_query: bool(row.safe_query), risk: row.risk, approved_by: row.approved_by,
    content_hash: row.content_hash, stale: false, tested: !!last?.passed,
    last_test: last ? { passed: bool(last.passed), mode: last.mode,
      error_code: last.error_code, created_at: timestamp(last.created_at),
      current: last.content_hash === row.content_hash } : null,
    mcp_tool: { name: row.mcp_name, title: row.title ?? row.tool_key,
      description: row.description, inputSchema: schema },
    created_at: timestamp(row.created_at), updated_at: timestamp(row.updated_at) };
}

async function tools(db, context) {
  const rows = await db.all(`SELECT t.*, c.app_id, c.connector_type, a.key AS app_key,
    a.name AS app_name, a.environment, m.name AS module_name, r.method, r.path_template,
    r.timeout_ms, r.max_payload_bytes, r.pagination, r.error_mapping, r.audit_level,
    r.requires_user_context, r.tenant_field, r.safe_query
    FROM tool_definitions t JOIN connectors c ON c.id = t.connector_id
    JOIN applications a ON a.id = c.app_id
    LEFT JOIN module_definitions m ON m.app_id = c.app_id AND m.module_key = t.module_key
    JOIN rest_tool_mappings r ON r.id = t.mapping_id ORDER BY t.created_at DESC`);
  return Promise.all(rows.filter((row) => row.status !== "archived" &&
    (row.connector_type !== "source_managed" || row.status === "published") &&
    (context.allowed === null || context.allowed.has(row.app_id))).map((row) => toolView(db, row)));
}

async function healthCheck(db, config, context, row) {
  if (row.status === "archived") throw conflict("Archived apps cannot be tested");
  const secrets = await connectorSecrets(db, config, row.id);
  let status = "ok", category = null, elapsedMs = null;
  try {
    const result = await sourceRequest({ method: "GET",
      url: joinSourceUrl(row.base_url, row.health_path), config,
      headers: { Authorization: `Bearer ${secrets.bearer}`, Accept: "application/json" },
      timeoutMs: row.timeout_ms, tlsVerify: bool(row.tls_verify), retries: 0 });
    elapsedMs = result.elapsedMs;
    if ([401, 403].includes(result.status)) category = "authorization";
    else if (result.status >= 400) category = "network";
    else {
      let document;
      try { document = JSON.parse(result.body); } catch {}
      if (document?.status !== "ok" && document?.status !== "healthy" && document?.success !== true) category = "schema";
    }
  } catch (error) {
    category = { CONNECTOR_DNS: "dns", UPSTREAM_TIMEOUT: "timeout",
      UPSTREAM_UNAUTHORIZED: "authorization", SCHEMA_MISMATCH: "schema" }[error?.code] ?? "network";
  }
  if (category) status = "fail";
  await db.run(`INSERT INTO connector_health_checks
    (id, connector_id, status, latency_ms, error_category, created_at)
    VALUES (?, ?, ?, ?, ?, ?)`, [id(), row.id, status, elapsedMs, category, iso()]);
  await audit(db, context, "connector.test", row, { result: category ? "error" : "success",
    error_code: category, duration_ms: elapsedMs });
  return { status, latency_ms: elapsedMs, error_category: category, hint: {
    authorization: "The application rejected the bearer token. Check its Authorization header.",
    dns: "The host name could not be resolved.", timeout: "The application did not answer in time.",
    network: "The application could not be reached or the address is blocked.",
    schema: "The health endpoint did not return a healthy response." }[category] ?? null };
}

async function toolSwitchView(db, config, row) {
  const identity = { id: "preview", app_id: row.app_id,
    scopes: ["mcp:tools", "tools:write"], allowed_tools: null };
  const caller = { identity, application: { id: row.app_id, key: row.app_key,
    name: row.app_name, environment: row.environment, status: row.app_status },
  connector: row, scopes: identity.scopes, allowedTools: null, actorRef: "admin:preview" };
  const live = row.status === "active" ? new Set((await catalogForCaller(db, config, caller,
    { ignoreSwitches: true }))
    .tools.map((tool) => tool.name)) : new Set();
  const off = new Set((await db.all("SELECT tool_name FROM tool_switches WHERE app_id = ?", [row.app_id]))
    .map((item) => item.tool_name));
  const memory = await memoryAdminView(db, row.app_id);
  const builtin = [
    { name: "list_data_sources", title: "List data sources", kind: "hub", group: "Hub tools",
      template: "read", status: "published", write: false },
    { name: "run_report", title: "Run report", kind: "hub", group: "Hub tools",
      template: "report", status: "published", write: false },
    ...MEMORY_TOOLS.map((tool) => ({ name: tool.name, title: tool.title,
      kind: "memory", group: "Memory", template: tool.name === "recall_memory" ? "read" : "update",
      status: "published", write: tool.name !== "recall_memory" })),
  ];
  const modules = new Map((await db.all("SELECT module_key, name FROM module_definitions WHERE app_id = ?",
    [row.app_id])).map((item) => [item.module_key, item.name]));
  const appTools = (await db.all(`SELECT id, mcp_name, title, tool_key, template, status,
    module_key FROM tool_definitions WHERE connector_id = ? AND status != 'archived'
    ORDER BY module_key, tool_key`, [row.id])).map((tool) => ({
    name: tool.mcp_name, title: tool.title || tool.tool_key, kind: "app",
    group: modules.get(tool.module_key) ?? tool.module_key, template: tool.template,
    status: tool.status, write: ["create", "update", "delete"].includes(tool.template),
    tool_id: tool.id }));
  const rows = [...builtin, ...appTools].map((tool) => ({
    ...tool, live: live.has(tool.name), enabled: !off.has(tool.name),
    note: live.has(tool.name) ? null : tool.kind === "memory" && !memory.enabled
      ? "Memory is off for this app" : tool.status === "draft"
        ? "Draft: publish it on its page first" : tool.status === "disabled"
          ? "Disabled on its page" : row.status !== "active" ? "Activate the app first"
            : "Its data source or operation is not allowed yet" }));
  return { tools: rows, total: rows.length,
    off: rows.filter((item) => !item.enabled).length,
    reaching_ai: rows.filter((item) => item.enabled && item.live).length };
}

export async function handleResources({ db, config, request, path, url, body }) {
  const method = request.method;
  if (path === "/system" && method === "GET") {
    await adminContext(db, config, request);
    return { version: "0.1.0-node", environment: config.environment, mcp_url: config.mcpPublicUrl,
      limits: { records_per_call: config.maxRecords, report_max_records: config.reportMaxRecords,
        report_timeout_seconds: config.reportTimeoutSeconds, tool_rate_limit: config.toolRateLimit,
        tool_rate_window_seconds: config.toolRateWindowSeconds, audit_retention_days: 90 },
      security: { mfa_required: config.mfaRequired, secure_cookies: config.cookieSecure,
        egress_allowlist: !!(config.egressAllowedHosts.length || config.egressAllowedCidrs.length),
        insecure_http_allowed: config.allowInsecureHttp,
        private_egress_allowed: config.egressAllowPrivate || config.egressAllowLoopback } };
  }
  if (path === "/connectors") {
    const context = await adminContext(db, config, request, method !== "GET");
    if (method === "GET") {
      const environment = url.searchParams.get("environment");
      const failures = await refreshManaged(db, config, context, { environment, metadata: true });
      return Promise.all((await allConnectors(db, context, environment)).map(async (row) => {
        const view = await connectorView(db, row);
        return failures[row.id] ? { ...view, sources_total: 0, sources_enabled: 0,
          tools_total: 0, tools_published: 0, source_sync_error: failures[row.id] } : view;
      }));
    }
    if (method === "POST") {
      const appKey = textField(body.app_key, "App key", 1, 64);
      if (!/^[a-z][a-z0-9_]*$/.test(appKey)) throw bad("App key must be lowercase letters, digits and underscores");
      const environment = body.environment ?? "dev";
      if (!["dev", "test", "staging", "production"].includes(environment) ||
          !["http_contract", "data_push", "source_managed"].includes(body.connector_type ?? "http_contract") ||
          (body.auth_type ?? "bearer") !== "bearer") throw bad();
      const baseUrl = textField(body.base_url, "Base URL", 1, 2048).replace(/\/$/, "");
      await validateDestination(baseUrl + "/", config);
      const manifestPath = body.manifest_path ?? "/api/ai/v1/capabilities";
      const healthPath = body.health_path ?? "/api/ai/v1/health";
      joinSourceUrl(baseUrl, manifestPath); joinSourceUrl(baseUrl, healthPath);
      if (body.tls_verify === false && !config.allowInsecureTls) throw bad("TLS verification cannot be disabled");
      const secret = textField(body.secret, "Secret", 8, 500);
      const delegation = body.delegation_secret || randomBytes(32).toString("base64url");
      textField(delegation, "Delegation secret", 8, 500);
      const timeout = body.timeout_ms ?? 5000;
      if (!Number.isInteger(timeout) || timeout < 100 || timeout > 30000) throw bad();
      const existing = await db.one("SELECT * FROM applications WHERE key = ? AND environment = ?",
        [appKey, environment]);
      if (existing) appAccess(context, existing.id);
      else role(context.user, ["super_admin"]);
      if (existing && await db.one("SELECT id FROM connectors WHERE app_id = ?", [existing.id])) {
        throw conflict("This app and environment is already connected");
      }
      const appId = existing?.id ?? id(), connectorId = id();
      await db.transaction(async (tx) => {
        if (!existing) await tx.run(`INSERT INTO applications
          (id, key, name, environment, status, created_at) VALUES (?, ?, ?, ?, ?, ?)`,
        [appId, appKey, body.name?.trim() || appKey, environment, "active", iso()]);
        await tx.run(`INSERT INTO connectors (id, app_id, connector_type, base_url, manifest_path,
          health_path, auth_type, status, tls_verify, timeout_ms, failure_count, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [connectorId, appId, body.connector_type ?? "http_contract", baseUrl, manifestPath,
          healthPath, "bearer", "draft", body.tls_verify !== false, timeout, 0, iso(), iso()]);
        await tx.run(`INSERT INTO connector_secrets (id, connector_id, secret_ciphertext,
          delegation_ciphertext, rotated_at) VALUES (?, ?, ?, ?, ?)`,
        [id(), connectorId, encryptSecret(config.secretEncryptionKey, secret),
          encryptSecret(config.secretEncryptionKey, delegation), iso()]);
      });
      const row = await bundle(db, context, connectorId);
      await audit(db, context, "connector.create", row);
      const view = await connectorView(db, row);
      return { status: 201, data: { ...view,
        ...(body.delegation_secret ? { delegation_secret_set: true } : { delegation_secret: delegation }) } };
    }
  }
  const match = /^\/connectors\/([^/]+)(?:\/(.*))?$/.exec(path);
  if (match) {
    const context = await adminContext(db, config, request, method !== "GET");
    const row = await bundle(db, context, match[1]);
    const action = match[2] ?? "";
    if (action === "memory") {
      if (method === "GET") return memoryAdminView(db, row.app_id);
      if (method === "PATCH") {
        if (row.status === "archived" && body.enabled === true) {
          throw conflict("Archived apps cannot turn memory on");
        }
        const result = await updateMemorySetting(db, row.app_id, body);
        await audit(db, context, "memory.settings", row);
        return result;
      }
      if (method === "DELETE") {
        const removed = await db.run("DELETE FROM user_memories WHERE app_id = ?", [row.app_id]);
        await audit(db, context, "memory.purge", row);
        return { removed };
      }
    }
    if (action === "tool-switches") {
      if (method === "GET") {
        await refreshManaged(db, config, context, { connectorId: row.id });
        return toolSwitchView(db, config, row);
      }
      if (method === "PUT") {
        const changes = body.tools;
        if (!changes || typeof changes !== "object" || Array.isArray(changes) ||
            !Object.keys(changes).length || Object.keys(changes).length > 500) {
          throw bad("Send tools as an object of 1 to 500 name: true/false pairs");
        }
        await refreshManaged(db, config, context, { connectorId: row.id });
        const known = new Set((await toolSwitchView(db, config, row)).tools.map((tool) => tool.name));
        for (const [name, on] of Object.entries(changes)) {
          if (!known.has(name) || typeof on !== "boolean") throw bad(`Unknown tool or invalid value: ${name}`);
        }
        for (const [name, on] of Object.entries(changes)) {
          const existing = await db.one(`SELECT id FROM tool_switches
            WHERE app_id = ? AND tool_name = ?`, [row.app_id, name]);
          if (on && existing) {
            await db.run("DELETE FROM tool_switches WHERE id = ?", [existing.id]);
            await audit(db, context, "tool.switch_on", row, { tool_key: name });
          } else if (!on && !existing) {
            await db.run(`INSERT INTO tool_switches
              (id, app_id, tool_name, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)`,
            [id(), row.app_id, name, context.user.id, iso()]);
            await audit(db, context, "tool.switch_off", row, { tool_key: name });
          }
        }
        return toolSwitchView(db, config, row);
      }
    }
    if (method === "GET" && !action) {
      const failures = await refreshManaged(db, config, context, { connectorId: row.id, metadata: true });
      const view = await connectorView(db, row);
      const health = await db.all(`SELECT * FROM connector_health_checks WHERE connector_id = ?
        ORDER BY created_at DESC LIMIT 20`, [row.id]);
      const contracts = await db.all(`SELECT * FROM contract_snapshots WHERE connector_id = ?
        ORDER BY created_at DESC LIMIT 20`, [row.id]);
      return { ...view, ...(failures[row.id] ? { sources_total: 0, sources_enabled: 0,
        tools_total: 0, tools_published: 0, source_sync_error: failures[row.id] } : {}),
        health_history: health.map((item) => ({
        status: item.status, latency_ms: item.latency_ms, error_category: item.error_category,
        hint: null, created_at: timestamp(item.created_at) })),
        contracts: contracts.map((item) => ({ version: item.manifest_version,
          hash: item.manifest_hash, created_at: timestamp(item.created_at),
          modules: json(item.manifest_json, {}).modules?.map((module) => module.key) ?? [] })) };
    }
    if (method === "POST" && action === "test") return healthCheck(db, config, context, row);
    if (method === "POST" && action === "discover") {
      if (row.status === "archived") throw conflict("Archived apps cannot be synchronized");
      const result = await synchronizeConnector(db, config, row);
      await audit(db, context, "connector.discover", row);
      return result;
    }
    if (method === "POST" && ["activate", "pause", "archive"].includes(action)) {
      if (row.status === "archived") throw conflict("Archived apps cannot be changed");
      if (action === "activate") {
        const health = await db.one(`SELECT status FROM connector_health_checks WHERE connector_id = ?
          ORDER BY created_at DESC LIMIT 1`, [row.id]);
        const contract = await db.one(`SELECT manifest_json FROM contract_snapshots WHERE connector_id = ?
          ORDER BY created_at DESC LIMIT 1`, [row.id]);
        const source = await db.one(`SELECT id FROM module_definitions WHERE app_id = ? LIMIT 1`, [row.app_id]);
        if (health?.status !== "ok" || !contract || !source ||
            (row.connector_type === "source_managed" && json(contract.manifest_json).managed_by !== "application")) {
          throw bad("Activation needs a passing connection test and a synced contract");
        }
      }
      const status = { activate: "active", pause: "paused", archive: "archived" }[action];
      await db.transaction(async (tx) => {
        await tx.run("UPDATE connectors SET status = ?, updated_at = ? WHERE id = ?", [status, iso(), row.id]);
        if (action === "archive") {
          await tx.run("UPDATE connector_secrets SET revoked_at = ? WHERE connector_id = ? AND revoked_at IS NULL",
            [iso(), row.id]);
          await tx.run("UPDATE tool_definitions SET status = 'archived' WHERE connector_id = ?", [row.id]);
          await tx.run("UPDATE service_identities SET revoked_at = ? WHERE app_id = ? AND revoked_at IS NULL",
            [iso(), row.app_id]);
        }
      });
      await audit(db, context, `connector.${action}`, row);
      return connectorView(db, { ...row, status });
    }
    if (method === "POST" && action === "rotate") {
      if (row.status === "archived") throw conflict("Archived apps cannot rotate credentials");
      const bearer = body.secret ?? null, delegation = body.delegation_secret ?? null;
      if (!bearer && !delegation) throw bad("Provide a new secret, a new delegation secret, or both");
      if (bearer) textField(bearer, "Secret", 8, 500);
      if (delegation) textField(delegation, "Delegation secret", 8, 500);
      const old = await db.one(`SELECT * FROM connector_secrets WHERE connector_id = ?
        ORDER BY rotated_at DESC LIMIT 1`, [row.id]);
      if (!old) throw conflict("Credential history is unavailable");
      await db.transaction(async (tx) => {
        await tx.run(`UPDATE connector_secrets SET revoked_at = ?
          WHERE connector_id = ? AND revoked_at IS NULL`, [iso(), row.id]);
        await tx.run(`INSERT INTO connector_secrets (id, connector_id, secret_ciphertext,
          delegation_ciphertext, rotated_at) VALUES (?, ?, ?, ?, ?)`,
        [id(), row.id, bearer ? encryptSecret(config.secretEncryptionKey, bearer) : old.secret_ciphertext,
          delegation ? encryptSecret(config.secretEncryptionKey, delegation) : old.delegation_ciphertext, iso()]);
      });
      await audit(db, context, "connector.rotate", row);
      return { rotated: true };
    }
  }
  if (path === "/modules" && method === "GET") {
    const context = await adminContext(db, config, request);
    await refreshManaged(db, config, context, { connectorId: url.searchParams.get("connector_id"),
      environment: url.searchParams.get("environment"), appKey: url.searchParams.get("app_key") });
    return modules(db, context, url.searchParams);
  }
  if (path === "/tools" && method === "GET") {
    const context = await adminContext(db, config, request);
    await refreshManaged(db, config, context);
    return tools(db, context);
  }
  if (path === "/tools/agent-view" && method === "GET") {
    const context = await adminContext(db, config, request);
    const row = await bundle(db, context, url.searchParams.get("connector_id"));
    await refreshManaged(db, config, context, { connectorId: row.id });
    let identity, key;
    if (url.searchParams.get("key_id")) {
      identity = await db.one("SELECT * FROM service_identities WHERE id = ?",
        [url.searchParams.get("key_id")]);
      if (!identity || identity.app_id !== row.app_id) throw missing("Client key was not found for this app");
      if (identity.revoked_at) throw conflict("This client key is revoked and sees nothing");
      key = { id: identity.id, name: identity.name,
        write: json(identity.scopes, []).includes("tools:write"),
        allowed_tools: json(identity.allowed_tools) };
    } else {
      const write = url.searchParams.get("write") === "true";
      identity = { id: "preview", app_id: row.app_id,
        scopes: ["mcp:tools", ...(write ? ["tools:write"] : [])], allowed_tools: null };
      key = { id: null, name: write ? "Read & write key" : "Read-only key",
        write, allowed_tools: null };
    }
    const caller = { identity, application: { id: row.app_id, key: row.app_key,
      name: row.app_name, environment: row.environment, status: row.app_status },
    connector: row, scopes: json(identity.scopes, []),
    allowedTools: json(identity.allowed_tools), actorRef: `admin:${context.user.id}` };
    const catalog = await catalogForCaller(db, config, caller);
    const prompts = await visibleSkills(db, caller, catalog.tools.map((tool) => tool.name));
    const memory = await memoryAdminView(db, row.app_id);
    return { app: { connector_id: row.id, app_key: row.app_key, name: row.app_name,
      environment: row.environment, status: row.status }, key,
      instructions: "Tools here read authorized application data. Start with list_data_sources.",
      memory_enabled: memory.enabled,
      tools: catalog.tools.map((tool) => ({
        name: tool.name, title: tool.title, description: tool.description,
        inputSchema: tool.inputSchema })),
      prompts: prompts.map((skill) => ({ name: skill.key, title: skill.title,
        description: skill.description, arguments: json(skill.arguments, []) })),
      sync_error: null };
  }
  if (path === "/tools/generate" && method === "POST") {
    const context = await adminContext(db, config, request, true);
    const row = await bundle(db, context, body.connector_id);
    if (row.connector_type === "source_managed") {
      if (row.status !== "active") throw conflict("Activate the app first: tools follow its own permissions");
      const before = new Map((await db.all(`SELECT id, status FROM tool_definitions
        WHERE connector_id = ?`, [row.id])).map((item) => [item.id, item.status]));
      await synchronizeConnector(db, config, row);
      const current = await db.all(`SELECT t.id, t.tool_key, t.mcp_name, t.template,
        t.title, t.module_key, t.status, m.name AS module_name
        FROM tool_definitions t LEFT JOIN module_definitions m ON m.app_id = ?
        AND m.module_key = t.module_key WHERE t.connector_id = ? AND t.status != 'archived'
        ORDER BY t.tool_key`, [row.app_id, row.id]);
      const item = (tool, note) => ({ id: tool.id, tool_key: tool.tool_key,
        mcp_name: tool.mcp_name, template: tool.template, title: tool.title ?? tool.tool_key,
        module_name: tool.module_name ?? tool.module_key, status: tool.status, note });
      const created = current.filter((tool) => tool.status === "published" && !before.has(tool.id))
        .map((tool) => item(tool, null));
      const repaired = current.filter((tool) => tool.status === "published" &&
        before.has(tool.id) && before.get(tool.id) !== "published")
        .map((tool) => item(tool, "Allowed again in the app"));
      const skipped = current.filter((tool) => tool.status === "disabled" &&
        before.get(tool.id) === "published").map((tool) => ({
          tool_key: tool.tool_key, reason: `No longer allowed in ${row.app_name}` }));
      const unchanged = current.filter((tool) => tool.status === "published" &&
        before.get(tool.id) === "published").length;
      await audit(db, context, "tool.generate", row);
      return { status: 201, data: { mode: "source_managed", created, repaired, skipped,
        unchanged, published: created.length + repaired.length } };
    }
  }
  const toolMatch = /^\/tools\/([^/]+)$/.exec(path);
  if (toolMatch && method === "GET") {
    const context = await adminContext(db, config, request);
    await refreshManaged(db, config, context);
    const rows = await tools(db, context);
    return rows.find((item) => item.id === toolMatch[1]) ?? (() => { throw missing("Tool was not found"); })();
  }
  const moduleMatch = /^\/modules\/([^/]+)\/settings$/.exec(path);
  if (moduleMatch && method === "PATCH") {
    const context = await adminContext(db, config, request, true);
    const row = await db.one(`SELECT m.*, s.id AS setting_id, s.enabled, s.operations_enabled,
      s.policy_version, s.report_endpoint, c.id AS connector_id, c.connector_type,
      a.key AS app_key, a.name AS app_name, a.environment
      FROM module_definitions m JOIN module_settings s ON s.module_id = m.id
      JOIN connectors c ON c.app_id = m.app_id JOIN applications a ON a.id = m.app_id
      WHERE m.id = ?`, [moduleMatch[1]]);
    if (!row) throw missing("Data source was not found");
    appAccess(context, row.app_id);
    if (row.connector_type === "source_managed") {
      throw new HubError("Manage models, fields and operations in the connected application",
        "POLICY_LOCKED", 409);
    }
    const module = json(row.manifest_json, {});
    const enabled = body.enabled ?? bool(row.enabled);
    if (typeof enabled !== "boolean") throw bad();
    let operations = body.operations ?? (enabled ? json(row.operations_enabled, []).length
      ? json(row.operations_enabled, []) : ["read"] : []);
    if (!Array.isArray(operations) || operations.some((op) => typeof op !== "string")) throw bad();
    operations = [...new Set(operations)];
    if (operations.some((op) => !json(row.supported_operations, []).includes(op))) {
      throw bad("Operation is not in the developer manifest");
    }
    if (operations.some((op) => !(module.enableable_operations ?? ["read"]).includes(op))) {
      throw new HubError("The application does not publish a reviewed route for that operation",
        "NOT_SUPPORTED", 422);
    }
    if (enabled && !operations.length) throw bad("Choose at least one operation to enable this data source");
    const updates = body.fields ?? [];
    if (!Array.isArray(updates) || updates.length > 100) throw bad();
    const policies = new Map((await db.all("SELECT * FROM field_policies WHERE module_id = ?", [row.id]))
      .map((item) => [item.field_path, item]));
    const rank = { blocked: 0, secure_form_only: 0, aggregate_only: 1, allowed_for_ai: 2, allowed: 2 };
    const changes = [];
    for (const update of updates) {
      const old = policies.get(update?.field_path);
      const baseline = isSensitivePath(update?.field_path) ? "blocked"
        : module.field_policies?.[update?.field_path] ?? "allowed_for_ai";
      if (!old || !json(row.readable_fields, []).includes(update.field_path) ||
          !(update.classification in rank)) throw bad("Field policy update is invalid");
      if (old.classification === update.classification) continue;
      if (bool(old.locked) || ["blocked", "secure_form_only"].includes(baseline) ||
          isSensitivePath(update.field_path) || rank[update.classification] > rank[baseline]) {
        throw new HubError("This field policy is locked by the developer or hub", "POLICY_LOCKED", 422);
      }
      changes.push({ id: old.id, classification: update.classification,
        source: update.classification === baseline ? "developer" : "admin" });
    }
    let reportEndpoint = row.report_endpoint;
    if ("report_endpoint" in body) {
      reportEndpoint = body.report_endpoint || null;
      if (reportEndpoint && ![...(module.read_endpoints ?? [])].some((route) =>
        `${route.method} ${route.path_template}` === reportEndpoint && route.output_schema?.maxItems > 1)) {
        throw bad("Report endpoint must be a reviewed list route of this data source");
      }
    }
    await db.transaction(async (tx) => {
      await tx.run(`UPDATE module_settings SET enabled = ?, operations_enabled = ?,
        policy_version = policy_version + 1, report_endpoint = ? WHERE id = ?`,
      [enabled, JSON.stringify(enabled ? operations : []), reportEndpoint, row.setting_id]);
      for (const change of changes) await tx.run(`UPDATE field_policies SET classification = ?,
        source = ? WHERE id = ?`, [change.classification, change.source, change.id]);
    });
    await audit(db, context, "module.update", row, { module_key: row.module_key });
    const current = await db.one(`SELECT m.*, s.enabled, s.operations_enabled, s.policy_version,
      s.report_endpoint, a.key AS app_key, a.name AS app_name, a.environment,
      c.id AS connector_id FROM module_definitions m JOIN module_settings s ON s.module_id = m.id
      JOIN applications a ON a.id = m.app_id JOIN connectors c ON c.app_id = m.app_id
      WHERE m.id = ?`, [row.id]);
    return moduleView(db, current);
  }
  if (match && method === "PATCH" && !match[2]) {
    const context = await adminContext(db, config, request, true);
    const row = await bundle(db, context, match[1]);
    if (row.status === "archived") throw conflict("Archived apps cannot be changed");
    pick(body, ["connector_type", "name", "base_url", "manifest_path", "health_path",
      "timeout_ms", "tls_verify"]);
    const changes = {};
    if ("connector_type" in body) {
      if (!["http_contract", "source_managed"].includes(body.connector_type)) throw bad();
      changes.connector_type = body.connector_type;
    }
    if ("name" in body) changes.name = textField(body.name, "Name", 1, 200);
    if ("base_url" in body) {
      changes.base_url = textField(body.base_url, "Base URL", 1, 2048).replace(/\/$/, "");
      await validateDestination(changes.base_url + "/", config);
    }
    for (const key of ["manifest_path", "health_path"]) {
      if (key in body) changes[key] = body[key];
      joinSourceUrl(changes.base_url ?? row.base_url, changes[key] ?? row[key]);
    }
    if ("timeout_ms" in body) {
      if (!Number.isInteger(body.timeout_ms) || body.timeout_ms < 100 || body.timeout_ms > 30000) throw bad();
      changes.timeout_ms = body.timeout_ms;
    }
    if ("tls_verify" in body) {
      if (typeof body.tls_verify !== "boolean" || (!body.tls_verify && !config.allowInsecureTls)) throw bad();
      changes.tls_verify = body.tls_verify;
    }
    const sourceChanged = ["base_url", "manifest_path", "connector_type"].some((key) =>
      key in changes && changes[key] !== row[key]);
    await db.transaction(async (tx) => {
      if ("name" in changes) await tx.run("UPDATE applications SET name = ? WHERE id = ?", [changes.name, row.app_id]);
      for (const key of ["connector_type", "base_url", "manifest_path", "health_path", "timeout_ms", "tls_verify"]) {
        if (key in changes) await tx.run(`UPDATE connectors SET ${key} = ? WHERE id = ?`,
          [changes[key], row.id]);
      }
      if (sourceChanged) {
        await tx.run("UPDATE connectors SET status = 'draft' WHERE id = ?", [row.id]);
        await tx.run(`UPDATE module_settings SET enabled = ?, operations_enabled = ?,
          policy_version = policy_version + 1 WHERE module_id IN
          (SELECT id FROM module_definitions WHERE app_id = ?)`, [false, "[]", row.app_id]);
      }
      await tx.run("UPDATE connectors SET updated_at = ? WHERE id = ?", [iso(), row.id]);
    });
    await audit(db, context, "connector.update", row);
    return connectorView(db, await bundle(db, context, row.id));
  }
  if (match && method === "DELETE" && !match[2]) {
    const context = await adminContext(db, config, request, true);
    const row = await bundle(db, context, match[1]);
    if (!["draft", "archived"].includes(row.status)) throw conflict("Archive the app before deleting it");
    await audit(db, context, "connector.delete", row);
    await db.run("DELETE FROM applications WHERE id = ?", [row.app_id]);
    return { deleted: true };
  }
  return undefined;
}
