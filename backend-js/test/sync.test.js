import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import test from "node:test";
import { HubDatabase } from "../server/database.js";
import { loadConfig } from "../server/config.js";
import { synchronizeConnector } from "../server/sync.js";
import { encryptSecret } from "../server/security.js";

test("source-managed discover writes old Hub tables and retires withdrawn grants", async () => {
  const db = new HubDatabase("sqlite+pysqlite:///:memory:");
  db.sqlite.exec(`
    CREATE TABLE applications (id TEXT PRIMARY KEY, key TEXT, name TEXT, environment TEXT, status TEXT);
    CREATE TABLE connectors (id TEXT PRIMARY KEY, app_id TEXT, app_key TEXT, connector_type TEXT,
      base_url TEXT, manifest_path TEXT, timeout_ms INTEGER, tls_verify INTEGER, status TEXT);
    CREATE TABLE connector_secrets (id TEXT PRIMARY KEY, connector_id TEXT, secret_ciphertext TEXT,
      delegation_ciphertext TEXT, rotated_at TEXT, revoked_at TEXT);
    CREATE TABLE contract_snapshots (id TEXT PRIMARY KEY, connector_id TEXT, manifest_hash TEXT,
      manifest_version TEXT, manifest_json TEXT, created_at TEXT);
    CREATE TABLE module_definitions (id TEXT PRIMARY KEY, app_id TEXT, module_key TEXT, name TEXT,
      description TEXT, schema_version TEXT, manifest_hash TEXT, manifest_json TEXT,
      supported_operations TEXT, readable_fields TEXT, writable_fields TEXT, filters TEXT,
      max_page_size INTEGER, risk TEXT, last_synced_at TEXT);
    CREATE TABLE module_settings (id TEXT PRIMARY KEY, module_id TEXT, enabled INTEGER,
      operations_enabled TEXT, policy_version INTEGER, report_endpoint TEXT);
    CREATE TABLE field_policies (id TEXT PRIMARY KEY, module_id TEXT, field_path TEXT,
      classification TEXT, source TEXT, locked INTEGER);
    CREATE TABLE rest_tool_mappings (id TEXT PRIMARY KEY, connector_id TEXT, method TEXT,
      path_template TEXT, timeout_ms INTEGER, max_payload_bytes INTEGER, query_params TEXT,
      pagination TEXT, error_mapping TEXT, safe_query INTEGER, requires_user_context INTEGER,
      tenant_field TEXT, audit_level TEXT);
    CREATE TABLE tool_definitions (id TEXT PRIMARY KEY, tool_key TEXT, mcp_name TEXT,
      version TEXT, connector_id TEXT, mapping_id TEXT, module_key TEXT, template TEXT,
      title TEXT, description TEXT, input_schema TEXT, output_schema TEXT, output_policy TEXT,
      report_spec TEXT, risk TEXT, status TEXT, approved_by TEXT, content_hash TEXT,
      policy_version INTEGER, owner_id TEXT, created_at TEXT, updated_at TEXT);
  `);
  let granted = true;
  const source = createServer((request, response) => {
    const module = { key: "projects", name: "Projects", supported_operations: ["read"],
      readable_fields: ["ref", "email"], field_policies: { email: "blocked" },
      read_endpoints: [{ method: "GET", path_template: "/projects",
        tool_key: "your_app.projects.list", description: "List projects",
        requires_user_context: true, tenant_field: "tenant_id",
        input_schema: { type: "object", additionalProperties: false, properties: {} },
        output_schema: { type: "array", maxItems: 50, items: { type: "object",
          additionalProperties: false, required: ["ref"], properties: {
            ref: { type: "string" }, email: { type: "string" } } } } }] };
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ contract_version: "1.0", application: "your_app",
      managed_by: "application", modules: granted ? [module] : [] }));
  });
  await new Promise((resolve) => source.listen(0, "127.0.0.1", resolve));
  const port = source.address().port;
  const key = randomBytes(32).toString("base64url");
  const appId = randomUUID(), connectorId = randomUUID();
  const base = `http://127.0.0.1:${port}`;
  await db.run("INSERT INTO applications VALUES (?, ?, ?, ?, ?)",
    [appId, "your_app", "Your App", "dev", "active"]);
  await db.run("INSERT INTO connectors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    [connectorId, appId, "your_app", "source_managed", base, "/capabilities", 5000, true, "active"]);
  await db.run("INSERT INTO connector_secrets VALUES (?, ?, ?, ?, ?, ?)",
    [randomUUID(), connectorId, encryptSecret(key, "source-secret"),
      encryptSecret(key, "delegation-secret"), new Date().toISOString(), null]);
  const config = { ...loadConfig(), secretEncryptionKey: key, allowInsecureHttp: true,
    egressAllowLoopback: true, egressAllowedPorts: [port] };
  const connector = await db.one("SELECT * FROM connectors WHERE id = ?", [connectorId]);
  try {
    const first = await synchronizeConnector(db, config, connector);
    assert.equal(first.modules[0].change, "new");
    const tool = await db.one("SELECT * FROM tool_definitions");
    assert.equal(tool.status, "published");
    assert.deepEqual(JSON.parse(tool.output_policy).allow_fields, ["ref"]);
    const second = await synchronizeConnector(db, config, connector);
    assert.equal(second.modules[0].change, "unchanged");
    assert.equal((await db.one("SELECT version FROM tool_definitions")).version, "1.0.0");
    granted = false;
    const withdrawn = await synchronizeConnector(db, config, connector);
    assert.equal(withdrawn.modules[0].change, "removed");
    assert.equal((await db.one("SELECT status FROM tool_definitions")).status, "disabled");
    assert.equal((await db.one("SELECT enabled FROM module_settings")).enabled, 0);
  } finally {
    await new Promise((resolve) => source.close(resolve));
    await db.close();
  }
});
