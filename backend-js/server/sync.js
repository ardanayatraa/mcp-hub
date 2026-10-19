import { HubSdkError } from "../src/errors.js";
import { connectorSecrets, mcpName } from "./catalog.js";
import { id, json, bool } from "./admin-common.js";
import { digest, validateManifest } from "./manifest.js";
import { isSensitivePath } from "./privacy.js";
import { iso } from "./security.js";
import { joinSourceUrl, sourceRequest } from "./source-http.js";

const rank = { blocked: 0, secure_form_only: 0, aggregate_only: 1, allowed_for_ai: 2, allowed: 2 };
const fail = (message) => new HubSdkError(message, "SCHEMA_MISMATCH", 422);

export async function fetchConnectorManifest(db, config, connector) {
  const secrets = await connectorSecrets(db, config, connector.id);
  const response = await sourceRequest({ method: "GET",
    url: joinSourceUrl(connector.base_url, connector.manifest_path), config,
    headers: { Authorization: `Bearer ${secrets.bearer}`, Accept: "application/json" },
    timeoutMs: connector.timeout_ms, tlsVerify: bool(connector.tls_verify), retries: 1 });
  if (response.status === 401) throw new HubSdkError("Connector credentials were rejected", "UPSTREAM_UNAUTHORIZED", 401);
  if (response.status === 403) throw new HubSdkError("Connector cannot read the manifest", "PERMISSION_DENIED", 403);
  if (response.status >= 400) throw fail("Capability manifest request failed");
  let document;
  try { document = JSON.parse(response.body); } catch { throw fail("Capability manifest was not valid JSON"); }
  return validateManifest(document, connector.app_key, connector.connector_type === "source_managed");
}

function baseline(module) {
  return module.readable_fields.map((field) => {
    let classification = isSensitivePath(field) ? "blocked"
      : module.field_policies?.[field] ?? "allowed_for_ai";
    if (!(classification in rank)) classification = "blocked";
    return { field, classification,
      locked: isSensitivePath(field) || ["blocked", "secure_form_only"].includes(classification) };
  });
}

async function mergePolicies(tx, moduleId, module, managed) {
  const old = new Map((await tx.all("SELECT * FROM field_policies WHERE module_id = ?", [moduleId]))
    .map((row) => [row.field_path, row]));
  for (const policy of baseline(module)) {
    const existing = old.get(policy.field);
    if (!existing) {
      await tx.run(`INSERT INTO field_policies
        (id, module_id, field_path, classification, source, locked)
        VALUES (?, ?, ?, ?, ?, ?)`,
      [id(), moduleId, policy.field, policy.classification, "developer", policy.locked]);
    } else if (managed || rank[policy.classification] < rank[existing.classification] || policy.locked) {
      await tx.run(`UPDATE field_policies SET classification = ?, source = ?,
        locked = ? WHERE id = ?`,
      [policy.classification, "developer", managed ? policy.locked : policy.locked || bool(existing.locked), existing.id]);
    }
  }
}

const pagination = (route) => ({
  ...(route.input_schema.properties?.limit?.type === "integer" ? { limit_parameter: "limit" } : {}),
  ...(route.input_schema.properties?.cursor?.type === "string" ? { cursor_parameter: "cursor" } : {}),
});

function sourceTool(module, route, connector, app, policyVersion) {
  const template = route.kind === "write" ? route.operation : "read";
  const fields = Object.keys(route.output_schema.items.properties);
  const visible = new Map(baseline(module).map((item) => [item.field, item.classification]));
  const allow = template === "read"
    ? fields.filter((field) => ["allowed", "allowed_for_ai"].includes(visible.get(field)) && !isSensitivePath(field))
    : fields.filter((field) => !isSensitivePath(field));
  if (template === "read" && !allow.length) throw fail("Source route has no AI-visible fields");
  const output = structuredClone(route.output_schema);
  output.items.properties = Object.fromEntries(
    Object.entries(output.items.properties).filter(([field]) => allow.includes(field)));
  output.items.required = (output.items.required ?? []).filter((field) => allow.includes(field));
  const mapping = {
    method: route.method, path_template: route.path_template,
    timeout_ms: connector.timeout_ms, max_payload_bytes: 1_048_576,
    safe_query: route.safe_query, requires_user_context: route.requires_user_context,
    tenant_field: route.tenant_field, pagination: template === "read" ? pagination(route) : {},
    audit_level: "standard", error_mapping: {},
  };
  return { tool_key: route.tool_key, mcp_name: mcpName(route.tool_key, app.environment),
    module_key: module.key, template, title: null, description: route.description,
    input_schema: route.input_schema, output_schema: output,
    output_policy: { allow_fields: allow }, report_spec: null,
    risk: template === "read" ? "read_only" : "write", mapping, policy_version: policyVersion };
}

function fingerprint(tool, mapping, moduleHash, version) {
  return digest({ key: tool.tool_key, version, source: moduleHash,
    description: tool.description, input: tool.input_schema, output: tool.output_schema,
    policy: tool.output_policy, risk: tool.risk, mapping,
    ...(tool.template !== "read" ? { template: tool.template } : {}) });
}

function nextVersion(version) {
  const parts = version.split(".").map(Number);
  return parts.length === 3 && parts.every(Number.isInteger)
    ? `${parts[0]}.${parts[1]}.${parts[2] + 1}` : "1.0.1";
}

async function syncTool(tx, connector, app, module, moduleRow, setting, route) {
  const built = sourceTool(module, route, connector, app, setting.policy_version);
  const existing = await tx.one(`SELECT * FROM tool_definitions WHERE connector_id = ?
    AND tool_key = ? AND status != 'archived' ORDER BY created_at DESC LIMIT 1`,
  [connector.id, built.tool_key]);
  const mapping = built.mapping;
  if (!existing) {
    const mappingId = id(), toolId = id(), version = "1.0.0";
    await tx.run(`INSERT INTO rest_tool_mappings (id, connector_id, method, path_template,
      timeout_ms, max_payload_bytes, query_params, pagination, error_mapping, safe_query,
      requires_user_context, tenant_field, audit_level)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [mappingId, connector.id, mapping.method, mapping.path_template, mapping.timeout_ms,
      mapping.max_payload_bytes, "[]", JSON.stringify(mapping.pagination), "{}",
      mapping.safe_query, mapping.requires_user_context, mapping.tenant_field, mapping.audit_level]);
    await tx.run(`INSERT INTO tool_definitions (id, tool_key, mcp_name, version, connector_id,
      mapping_id, module_key, template, title, description, input_schema, output_schema,
      output_policy, report_spec, risk, status, content_hash, policy_version, owner_id,
      created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [toolId, built.tool_key, built.mcp_name, version, connector.id, mappingId,
      module.key, built.template, built.title, built.description, JSON.stringify(built.input_schema),
      JSON.stringify(built.output_schema), JSON.stringify(built.output_policy), null, built.risk,
      "published", fingerprint(built, mapping, moduleRow.manifest_hash, version),
      setting.policy_version, connector.id, iso(), iso()]);
    return toolId;
  }
  let version = existing.version;
  const current = fingerprint(built, mapping, moduleRow.manifest_hash, version);
  if (current !== existing.content_hash) version = nextVersion(version);
  await tx.run(`UPDATE rest_tool_mappings SET method = ?, path_template = ?, timeout_ms = ?,
    max_payload_bytes = ?, pagination = ?, error_mapping = ?, safe_query = ?,
    requires_user_context = ?, tenant_field = ?, audit_level = ? WHERE id = ?`,
  [mapping.method, mapping.path_template, mapping.timeout_ms, mapping.max_payload_bytes,
    JSON.stringify(mapping.pagination), "{}", mapping.safe_query, mapping.requires_user_context,
    mapping.tenant_field, mapping.audit_level, existing.mapping_id]);
  await tx.run(`UPDATE tool_definitions SET mcp_name = ?, version = ?, module_key = ?,
    template = ?, description = ?, input_schema = ?, output_schema = ?, output_policy = ?,
    risk = ?, status = ?, approved_by = NULL, content_hash = ?, policy_version = ?,
    updated_at = ? WHERE id = ?`,
  [built.mcp_name, version, module.key, built.template, built.description,
    JSON.stringify(built.input_schema), JSON.stringify(built.output_schema),
    JSON.stringify(built.output_policy), built.risk, "published",
    fingerprint(built, mapping, moduleRow.manifest_hash, version),
    setting.policy_version, iso(), existing.id]);
  return existing.id;
}

export async function synchronizeConnector(db, config, connector) {
  const manifest = await fetchConnectorManifest(db, config, connector);
  const managed = connector.connector_type === "source_managed";
  return db.transaction(async (tx) => {
    const app = await tx.one("SELECT * FROM applications WHERE id = ?", [connector.app_id]);
    const oldSnapshot = await tx.one(`SELECT id FROM contract_snapshots
      WHERE connector_id = ? AND manifest_hash = ?`, [connector.id, manifest.manifest_hash]);
    if (!oldSnapshot) await tx.run(`INSERT INTO contract_snapshots
      (id, connector_id, manifest_hash, manifest_version, manifest_json, created_at)
      VALUES (?, ?, ?, ?, ?, ?)`,
    [id(), connector.id, manifest.manifest_hash, manifest.manifest_version,
      JSON.stringify(manifest), iso()]);
    const current = new Map(manifest.modules.map((module) => [module.key, module]));
    const existingRows = await tx.all("SELECT * FROM module_definitions WHERE app_id = ?", [app.id]);
    const results = [];
    for (const old of existingRows) if (!current.has(old.module_key)) {
      const setting = await tx.one("SELECT * FROM module_settings WHERE module_id = ?", [old.id]);
      if (setting && (bool(setting.enabled) || json(setting.operations_enabled, []).length)) {
        await tx.run(`UPDATE module_settings SET enabled = ?, operations_enabled = ?,
          policy_version = policy_version + 1 WHERE id = ?`, [false, "[]", setting.id]);
      }
      results.push({ id: old.id, module_key: old.module_key, name: old.name,
        change: "removed", enabled: false });
    }
    const wantedTools = new Set();
    for (const module of manifest.modules) {
      const existing = existingRows.find((row) => row.module_key === module.key);
      const fingerprintHash = digest(module);
      const moduleId = existing?.id ?? id();
      const changed = existing && JSON.stringify(json(existing.manifest_json)) !== JSON.stringify(module);
      if (!existing) {
        await tx.run(`INSERT INTO module_definitions (id, app_id, module_key, name, description,
          schema_version, manifest_hash, manifest_json, supported_operations, readable_fields,
          writable_fields, filters, max_page_size, risk, last_synced_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [moduleId, app.id, module.key, module.name, module.description, module.schema_version,
          fingerprintHash, JSON.stringify(module), JSON.stringify(module.supported_operations),
          JSON.stringify(module.readable_fields), JSON.stringify(module.writable_fields),
          JSON.stringify(module.filters), module.max_page_size, JSON.stringify(module.risk), iso()]);
        await tx.run(`INSERT INTO module_settings
          (id, module_id, enabled, operations_enabled, policy_version)
          VALUES (?, ?, ?, ?, ?)`, [id(), moduleId, false, "[]", 1]);
      } else {
        await tx.run(`UPDATE module_definitions SET name = ?, description = ?, schema_version = ?,
          manifest_hash = ?, manifest_json = ?, supported_operations = ?, readable_fields = ?,
          writable_fields = ?, filters = ?, max_page_size = ?, risk = ?, last_synced_at = ?
          WHERE id = ?`,
        [module.name, module.description, module.schema_version, fingerprintHash,
          JSON.stringify(module), JSON.stringify(module.supported_operations),
          JSON.stringify(module.readable_fields), JSON.stringify(module.writable_fields),
          JSON.stringify(module.filters), module.max_page_size, JSON.stringify(module.risk), iso(), moduleId]);
      }
      await mergePolicies(tx, moduleId, module, managed);
      let setting = await tx.one("SELECT * FROM module_settings WHERE module_id = ?", [moduleId]);
      if (managed) {
        const operations = module.enableable_operations;
        if (bool(setting.enabled) !== !!operations.length ||
            JSON.stringify(json(setting.operations_enabled, [])) !== JSON.stringify(operations)) {
          await tx.run(`UPDATE module_settings SET enabled = ?, operations_enabled = ?,
            policy_version = policy_version + 1, report_endpoint = NULL WHERE id = ?`,
          [!!operations.length, JSON.stringify(operations), setting.id]);
          setting = await tx.one("SELECT * FROM module_settings WHERE id = ?", [setting.id]);
        }
        for (const route of [...module.read_endpoints, ...(module.write_endpoints ?? [])]) {
          if (!operations.includes(route.operation ?? "read")) continue;
          const toolId = await syncTool(tx, connector, app, module,
            { manifest_hash: fingerprintHash }, setting, route);
          wantedTools.add(toolId);
        }
      } else if (changed) {
        await tx.run(`UPDATE module_settings SET enabled = ?, operations_enabled = ?,
          policy_version = policy_version + 1 WHERE id = ?`, [false, "[]", setting.id]);
      }
      results.push({ id: moduleId, module_key: module.key, name: module.name,
        description: module.description, schema_version: module.schema_version,
        supported_operations: module.supported_operations, readable_fields: module.readable_fields,
        change: existing ? changed ? "changed" : "unchanged" : "new",
        enabled: managed ? !!module.enableable_operations.length : !!existing && !changed && bool(setting.enabled) });
    }
    if (managed) {
      const existingTools = await tx.all(`SELECT id FROM tool_definitions WHERE connector_id = ?
        AND status != 'archived'`, [connector.id]);
      for (const tool of existingTools) if (!wantedTools.has(tool.id)) {
        await tx.run(`UPDATE tool_definitions SET status = 'disabled', updated_at = ?
          WHERE id = ?`, [iso(), tool.id]);
      }
    }
    return { modules: results };
  });
}
