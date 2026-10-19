import { createHash } from "node:crypto";
import { HubError } from "./errors.js";
import { decryptSecret, sha256, truthy } from "./security.js";
import { validateManifest, digest } from "./manifest.js";
import { isSensitivePath, treeContainsPii } from "./privacy.js";
import { joinSourceUrl, sourceRequest } from "./source-http.js";
import { REPORT_INPUT } from "./report.js";
import { MEMORY_TOOLS, memorySetting } from "./memory.js";

const parsed = (value, fallback) => {
  if (value === null || value === undefined) return fallback;
  return typeof value === "string" ? JSON.parse(value) : value;
};
const allowed = (caller, name) => caller.allowedTools === null || caller.allowedTools.includes(name);
const dateMs = (value) => value instanceof Date ? value.getTime()
  : Date.parse(typeof value === "string" && !/[zZ]|[+-]\d\d:\d\d$/.test(value)
    ? `${value.replace(" ", "T")}Z` : value);

export async function resolveCaller(db, rawToken) {
  if (!rawToken) return null;
  const identity = await db.one("SELECT * FROM service_identities WHERE token_hash = ?", [sha256(rawToken)]);
  if (!identity || identity.revoked_at ||
      (identity.expires_at && dateMs(identity.expires_at) < Date.now())) return null;
  const scopes = parsed(identity.scopes, []);
  if (!scopes.includes("mcp:tools")) return null;
  const application = await db.one("SELECT * FROM applications WHERE id = ?", [identity.app_id]);
  if (!application || application.status !== "active") return null;
  const connector = await db.one("SELECT * FROM connectors WHERE app_id = ?", [application.id]);
  return { identity, application, connector, scopes,
    allowedTools: parsed(identity.allowed_tools, null), actorRef: `service:${identity.id}` };
}

export async function connectorSecrets(db, config, connectorId) {
  const row = await db.one(`SELECT * FROM connector_secrets
    WHERE connector_id = ? AND revoked_at IS NULL ORDER BY rotated_at DESC LIMIT 1`, [connectorId]);
  if (!row) throw new HubError("Connector credential is not available", "SECRET_UNAVAILABLE", 409);
  return { bearer: decryptSecret(config.secretEncryptionKey, row.secret_ciphertext),
    delegation: decryptSecret(config.secretEncryptionKey, row.delegation_ciphertext) };
}

export async function liveManifest(db, config, caller) {
  const { connector, application } = caller;
  if (!connector || connector.status !== "active") throw new HubError("Connector is not active", "CONNECTOR_INACTIVE", 409);
  const secrets = await connectorSecrets(db, config, connector.id);
  const request = await sourceRequest({ method: "GET",
    url: joinSourceUrl(connector.base_url, connector.manifest_path), config,
    headers: { Authorization: `Bearer ${secrets.bearer}`, Accept: "application/json" },
    timeoutMs: connector.timeout_ms, tlsVerify: truthy(connector.tls_verify), retries: 1 });
  if (request.status === 401) throw new HubError("Connector credentials were rejected", "UPSTREAM_UNAUTHORIZED", 401);
  if (request.status === 403) throw new HubError("Connector cannot read the manifest", "PERMISSION_DENIED", 403);
  if (request.status >= 400) throw new HubError("Capability manifest request failed", "SCHEMA_MISMATCH", 422);
  let document;
  try { document = JSON.parse(request.body); }
  catch { throw new HubError("Capability manifest was not valid JSON", "SCHEMA_MISMATCH", 422); }
  return { manifest: validateManifest(document, application.key, connector.connector_type === "source_managed"), secrets };
}

export function mcpName(toolKey, environment) {
  let name = toolKey.replaceAll(".", "__");
  if (environment !== "dev") {
    const suffix = `__${environment}`;
    if (name.length + suffix.length > 64) name = `${name.slice(0, 40)}__${createHash("sha256").update(name).digest("hex").slice(0, 8)}`;
    name += suffix;
  }
  if (name.length > 64) throw new HubError("MCP tool name is too long", "SCHEMA_MISMATCH", 422);
  return name;
}

function policyMap(module, storedPolicies) {
  const result = {};
  for (const field of module.readable_fields ?? []) {
    result[field] = isSensitivePath(field) ? "blocked"
      : (module.field_policies?.[field] ?? "allowed_for_ai");
  }
  for (const row of storedPolicies ?? []) {
    if (row.field_path in result && row.classification) result[row.field_path] = row.classification;
  }
  return result;
}

export function reportRoute(module, preferred) {
  const candidates = (module.read_endpoints ?? []).filter((route) => {
    const required = new Set(route.input_schema.required ?? []);
    return route.output_schema.maxItems > 1 && [...required].every((key) => ["limit", "cursor"].includes(key));
  });
  if (preferred) return candidates.find((route) => `${route.method} ${route.path_template}` === preferred) ?? null;
  return candidates.sort((a, b) => {
    const score = (route) => ["limit", "cursor"].filter((key) => key in route.input_schema.properties).length;
    return score(b) - score(a);
  })[0] ?? null;
}

function sourceFields(module, route, policies) {
  const entries = route?.output_schema?.items?.properties ?? {};
  return Object.entries(entries).flatMap(([name, schema]) => {
    const classification = policies[name] ?? "blocked";
    if (classification === "blocked" || classification === "secure_form_only" || isSensitivePath(name)) return [];
    return [{ name, type: schema.type, ...(schema.enum ? { values: schema.enum } : {}),
      ...(classification === "aggregate_only" ? { aggregate_only: true } : {}) }];
  });
}

function sourceView(module, operations, policies, preferred) {
  const route = reportRoute(module, preferred);
  return { source: module.key, name: module.name, description: module.description,
    operations, reportable: !!route, fields: route ? sourceFields(module, route, policies)
      : module.readable_fields.flatMap((name) => {
        const classification = policies[name] ?? "blocked";
        return classification === "blocked" || classification === "secure_form_only" || isSensitivePath(name)
          ? [] : [{ name, ...(classification === "aggregate_only" ? { aggregate_only: true } : {}) }];
      }) };
}

function title(key) {
  const parts = key.split(".");
  const action = parts.at(-1).replaceAll("_", " ");
  return `${action.charAt(0).toUpperCase()}${action.slice(1)} ${parts.at(-2).replaceAll("_", " ")}`;
}

export async function catalogForCaller(db, config, caller, { ignoreSwitches = false } = {}) {
  if (!caller.connector || caller.connector.status !== "active") return { tools: [], sources: [], secrets: null };
  const off = ignoreSwitches ? new Set() : new Set((await db.all(
    "SELECT tool_name FROM tool_switches WHERE app_id = ?", [caller.application.id]))
    .map((row) => row.tool_name));
  const tools = [];
  const sources = [];
  const sourceModules = new Map();
  let secrets = null;
  if (caller.connector.connector_type === "source_managed") {
    const live = await liveManifest(db, config, caller);
    secrets = live.secrets;
    for (const module of live.manifest.modules) {
      const policies = policyMap(module);
      sources.push(sourceView(module, module.enableable_operations, policies, null));
      sourceModules.set(module.key, { module, policies, operations: module.enableable_operations,
        route: reportRoute(module, null) });
      for (const route of [...module.read_endpoints, ...(module.write_endpoints ?? [])]) {
        const operation = route.operation ?? "read";
        if (!module.enableable_operations.includes(operation)) continue;
        const name = mcpName(route.tool_key, caller.application.environment);
        if (!allowed(caller, name) || off.has(name) ||
            (operation !== "read" && !caller.scopes.includes("tools:write"))) continue;
        const fields = Object.keys(route.output_schema.items.properties);
        const allowFields = operation === "read"
          ? fields.filter((field) => ["allowed", "allowed_for_ai"].includes(policies[field]))
          : fields.filter((field) => !isSensitivePath(field));
        if (operation === "read" && !allowFields.length) continue;
        tools.push({ name, key: route.tool_key, title: title(route.tool_key),
          description: route.description, inputSchema: route.input_schema, outputSchema: route.output_schema,
          route, module, policies, allowFields, operation, connector: caller.connector });
      }
    }
  } else {
    const rows = await db.all(`SELECT m.*, s.enabled, s.operations_enabled, s.report_endpoint
      FROM module_definitions m JOIN module_settings s ON s.module_id = m.id
      WHERE m.app_id = ?`, [caller.application.id]);
    for (const row of rows) {
      if (!truthy(row.enabled)) continue;
      const module = { ...parsed(row.manifest_json, {}), key: row.module_key, name: row.name,
        description: row.description, readable_fields: parsed(row.readable_fields, []) };
      const policies = policyMap(module, await db.all("SELECT * FROM field_policies WHERE module_id = ?", [row.id]));
      const operations = parsed(row.operations_enabled, []);
      sources.push(sourceView(module, operations, policies, row.report_endpoint));
      sourceModules.set(module.key, { module, policies, operations, route: reportRoute(module, row.report_endpoint) });
      const stored = await db.all(`SELECT t.*, r.method, r.path_template, r.timeout_ms, r.max_payload_bytes,
        r.safe_query, r.requires_user_context, r.tenant_field, r.pagination, r.error_mapping, r.audit_level
        FROM tool_definitions t JOIN rest_tool_mappings r ON r.id = t.mapping_id
        WHERE t.connector_id = ? AND t.module_key = ? AND t.status = 'published'`,
      [caller.connector.id, row.module_key]);
      for (const tool of stored) {
        const operation = ["create", "update", "delete"].includes(tool.template) ? tool.template : "read";
        if (!operations.includes(operation) || !allowed(caller, tool.mcp_name) || off.has(tool.mcp_name) ||
            (operation !== "read" && !caller.scopes.includes("tools:write"))) continue;
        const route = [...(module.read_endpoints ?? []), ...(module.write_endpoints ?? [])]
          .find((item) => item.method === tool.method && item.path_template === tool.path_template);
        if (!route || route.requires_user_context !== truthy(tool.requires_user_context) ||
            route.tenant_field !== tool.tenant_field) continue;
        // A changed manual contract needs a new test and publication in the admin UI.
        const mapping = { method: tool.method, path_template: tool.path_template,
          timeout_ms: tool.timeout_ms, max_payload_bytes: tool.max_payload_bytes,
          safe_query: truthy(tool.safe_query), requires_user_context: truthy(tool.requires_user_context),
          tenant_field: tool.tenant_field, pagination: parsed(tool.pagination, {}),
          audit_level: tool.audit_level, error_mapping: parsed(tool.error_mapping, {}) };
        const fingerprint = digest({ key: tool.tool_key, version: tool.version, source: row.manifest_hash,
          description: tool.description, input: parsed(tool.input_schema, {}),
          output: parsed(tool.output_schema, {}), policy: parsed(tool.output_policy, {}),
          risk: tool.risk, mapping,
          ...(tool.template !== "read" ? { template: tool.template } : {}),
          ...(tool.report_spec ? { report: parsed(tool.report_spec, {}) } : {}),
          ...(tool.title ? { title: tool.title } : {}) });
        if (fingerprint !== tool.content_hash) continue;
        tools.push({ name: tool.mcp_name, key: tool.tool_key, title: tool.title || title(tool.tool_key),
          description: tool.description, inputSchema: parsed(tool.input_schema, {}),
          outputSchema: parsed(tool.output_schema, {}), route, module, policies,
          allowFields: parsed(tool.output_policy, {}).allow_fields ?? [], operation,
          connector: caller.connector, mapping,
          ...(tool.template === "report" ? { operation: "saved_report",
            reportSpec: parsed(tool.report_spec, {}) } : {}) });
      }
    }
  }
  if (treeContainsPii(sources)) throw new HubError("Data source metadata is blocked by privacy policy", "PII_DETECTED", 422);
  if (allowed(caller, "list_data_sources") && !off.has("list_data_sources")) {
    tools.unshift({ name: "list_data_sources", key: "list_data_sources", title: "List data sources",
      description: "List the data sources this client may read, with field names, types and allowed operations.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} }, operation: "builtin" });
  }
  if (allowed(caller, "run_report") && !off.has("run_report")) {
    tools.push({ name: "run_report", key: "run_report", title: "Run report",
      description: "Read authorized records from one data source and return records, totals or grouped metrics with a summary.",
      inputSchema: REPORT_INPUT, operation: "builtin" });
  }
  const memory = await memorySetting(db, caller.application.id);
  if (truthy(memory.enabled)) for (const tool of MEMORY_TOOLS) {
    if (allowed(caller, tool.name) && !off.has(tool.name)) {
      tools.push({ ...tool, key: tool.name, operation: "memory" });
    }
  }
  return { tools, sources, sourceModules, secrets };
}
