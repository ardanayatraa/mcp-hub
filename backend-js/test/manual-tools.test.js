import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { randomBytes, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import test from "node:test";
import argon2 from "argon2";
import { HubClient } from "../src/index.js";
import { loadConfig } from "../server/config.js";
import { HubDatabase } from "../server/database.js";
import { createHubServer } from "../server/main.js";
import { encryptSecret, sha256 } from "../server/security.js";
import { digest } from "../server/manifest.js";

test("manual tool create, sample test, publish and MCP call use the old Hub tables", async () => {
  const db = new HubDatabase("sqlite+pysqlite:///:memory:");
  const schema = JSON.parse(readFileSync(new URL("../server/schema.sqlite.json", import.meta.url)));
  for (const row of schema.filter((item) => item.type === "table")) db.sqlite.exec(row.sql);
  for (const row of schema.filter((item) => item.type === "index")) db.sqlite.exec(row.sql);
  const source = createServer((request, response) => {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ success: true, data: [{ ref: "project_1" }],
      meta: { as_of: new Date().toISOString(), timezone: "UTC", scope: "authorized_records",
        coverage: "complete", total_count: 1 } }));
  });
  await new Promise((resolve) => source.listen(0, "127.0.0.1", resolve));
  const sourceBase = `http://127.0.0.1:${source.address().port}`;
  const encryptionKey = randomBytes(32).toString("base64url") + "=";
  const config = { ...loadConfig(), secretEncryptionKey: encryptionKey,
    allowInsecureHttp: true, egressAllowLoopback: true,
    egressAllowedPorts: [source.address().port], allowedHosts: [] };
  const now = new Date().toISOString(), appId = randomUUID(), connectorId = randomUUID();
  const moduleId = randomUUID(), adminId = randomUUID(), clientKey = "manual_client_key";
  const route = { kind: "read", operation: "read", method: "GET", path_template: "/projects",
    tool_key: "your_app.projects.list", description: "List authorized projects",
    requires_user_context: false, tenant_field: null, safe_query: false,
    input_schema: { type: "object", additionalProperties: false, properties: {} },
    output_schema: { type: "array", maxItems: 50, items: { type: "object",
      additionalProperties: false, required: ["ref"], properties: { ref: { type: "string" } } } } };
  const module = { key: "projects", name: "Projects", description: "Projects",
    readable_fields: ["ref"], read_endpoints: [route], write_endpoints: [] };
  await db.run(`INSERT INTO admin_users (id,email,password_hash,role,mfa_enabled,is_active,created_at)
    VALUES (?,?,?,?,?,?,?)`, [adminId, "admin@example.com", await argon2.hash("StrongPass123"),
    "super_admin", false, true, now]);
  await db.run(`INSERT INTO applications (id,key,name,environment,status,created_at)
    VALUES (?,?,?,?,?,?)`, [appId, "your_app", "Your App", "dev", "active", now]);
  await db.run(`INSERT INTO connectors (id,app_id,connector_type,base_url,manifest_path,health_path,
    auth_type,status,tls_verify,timeout_ms,failure_count,created_at,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`, [connectorId, appId, "http_contract", sourceBase,
    "/capabilities", "/health", "bearer", "active", true, 5000, 0, now, now]);
  await db.run(`INSERT INTO connector_secrets (id,connector_id,secret_ciphertext,
    delegation_ciphertext,rotated_at) VALUES (?,?,?,?,?)`, [randomUUID(), connectorId,
    encryptSecret(encryptionKey, "source-secret"),
    encryptSecret(encryptionKey, "delegation-secret"), now]);
  await db.run(`INSERT INTO module_definitions (id,app_id,module_key,name,description,schema_version,
    manifest_hash,manifest_json,supported_operations,readable_fields,writable_fields,filters,
    max_page_size,risk,last_synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
  [moduleId, appId, "projects", "Projects", "Projects", "1.0", digest(module), JSON.stringify(module),
    '["read"]', '["ref"]', "[]", "[]", 50, "{}", now]);
  await db.run(`INSERT INTO module_settings (id,module_id,enabled,operations_enabled,policy_version)
    VALUES (?,?,?,?,?)`, [randomUUID(), moduleId, true, '["read"]', 1]);
  await db.run(`INSERT INTO field_policies (id,module_id,field_path,classification,source,locked)
    VALUES (?,?,?,?,?,?)`, [randomUUID(), moduleId, "ref", "allowed_for_ai", "developer", false]);
  await db.run(`INSERT INTO service_identities (id,app_id,name,token_hash,scopes,allowed_tools,
    created_at) VALUES (?,?,?,?,?,?,?)`, [randomUUID(), appId, "gateway", sha256(clientKey),
    '["mcp:tools"]', null, now]);
  const hub = createHubServer({ db, config });
  await new Promise((resolve) => hub.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${hub.address().port}`;
  try {
    const login = await fetch(`${base}/api/admin/v1/auth/login`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        email: "admin@example.com", password: "StrongPass123" }) });
    assert.equal(login.status, 200);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    const csrf = (await login.json()).data.csrf_token;
    const admin = async (path, method, body) => {
      const response = await fetch(`${base}/api/admin/v1${path}`, { method,
        headers: { Cookie: cookie, "X-CSRF-Token": csrf, "Content-Type": "application/json" },
        ...(body ? { body: JSON.stringify(body) } : {}) });
      return { status: response.status, body: await response.json() };
    };
    const created = await admin("/tools", "POST", { connector_id: connectorId,
      module_key: "projects", tool_key: "projects.list", template: "read" });
    assert.equal(created.status, 201, JSON.stringify(created.body));
    const toolId = created.body.data.id;
    assert.equal(created.body.data?.status, "draft", JSON.stringify(created.body));
    const tested = await admin(`/tools/${toolId}/test`, "POST", { mode: "sample" });
    assert.equal(tested.body.data.passed, true, JSON.stringify(tested.body));
    const published = await admin(`/tools/${toolId}/publish`, "POST");
    assert.equal(published.body.data.status, "published", JSON.stringify(published.body));
    const client = new HubClient({ baseUrl: base, clientKey, appKey: "your_app",
      delegationSecret: "delegation-secret" });
    const listed = await client.listTools({ tenantId: "t_1", userRef: "u_1" });
    assert.ok(listed.some((tool) => tool.name === "your_app__projects__list"));
    const result = await client.callTool("your_app__projects__list", {},
      { tenantId: "t_1", userRef: "u_1" });
    assert.deepEqual(result.data, [{ ref: "project_1" }]);
    const disabled = await admin(`/tools/${toolId}/disable`, "POST");
    assert.equal(disabled.body.data.status, "disabled");
    const generated = await admin("/tools/generate", "POST", { connector_id: connectorId });
    assert.equal(generated.status, 201, JSON.stringify(generated.body));
    assert.equal(generated.body.data.mode, "generated");
    assert.ok(generated.body.data.skipped.some((item) => item.tool_key === "your_app.projects.list"));
    const builtin = await admin("/tools/builtins/list_data_sources/test", "POST",
      { connector_id: connectorId });
    assert.equal(builtin.body.data.passed, true, JSON.stringify(builtin.body));
    const exported = await admin("/operations/export", "POST");
    assert.equal(exported.body.data.format, "mcp-hub-metadata-v1");
    assert.equal(exported.body.data.tables.tool_definitions.length, 2);
    const rejected = await admin("/operations/import", "POST", {
      format: "mcp-hub-metadata-v1", tables: { unknown_table: [] } });
    assert.equal(rejected.status, 422);
    const imported = await admin("/operations/import", "POST", exported.body.data);
    assert.equal(imported.body.data.tool_definitions, 2, JSON.stringify(imported.body));
    assert.equal((await db.one("SELECT status FROM tool_definitions WHERE id = ?", [toolId])).status,
      "disabled");
  } finally {
    await new Promise((resolve) => hub.close(resolve));
    await new Promise((resolve) => source.close(resolve));
    await db.close();
  }
});
