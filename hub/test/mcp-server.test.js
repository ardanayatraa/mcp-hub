import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { createServer } from "node:http";
import test from "node:test";
import { HubClient, HubSourceAuth, MemoryReplayStore } from "../../sdk/src/index.js";
import { loadConfig } from "../server/core/config.js";
import { HubDatabase } from "../server/core/database.js";
import { createHubServer } from "../server/core/handler.js";
import { encryptSecret, sha256 } from "../server/core/security.js";

test("standalone Node MCP lists and calls a live source-managed read tool", async () => {
  const appKey = "your_app";
  const shared = "test-delegation-secret-with-32-bytes";
  const sourceBearer = "test-source-service-key";
  const clientKey = "hub_test_client_key";
  const encryptionKey = randomBytes(32).toString("base64url") + "=";
  let sourceAuth;
  const source = createServer(async (request, response) => {
    const send = (status, body) => { response.writeHead(status, { "Content-Type": "application/json" }); response.end(JSON.stringify(body)); };
    try {
      sourceAuth.verifyBearer(request.headers);
      if (request.url === "/api/ai/v1/capabilities") return send(200, {
        contract_version: "1.0", application: appKey, managed_by: "application", modules: [{
          key: "projects", name: "Projects", supported_operations: ["read"], readable_fields: ["ref"],
          read_endpoints: [{ method: "GET", path_template: "/api/v1/projects",
            tool_key: "your_app.projects.list", description: "List authorized projects",
            requires_user_context: true, tenant_field: "tenant_id",
            input_schema: { type: "object", additionalProperties: false, properties: {} },
            output_schema: { type: "array", maxItems: 50, items: { type: "object",
              additionalProperties: false, required: ["ref"], properties: { ref: { type: "string" } } } } }] }] });
      if (request.url === "/api/v1/projects") {
        const who = await sourceAuth.authenticate(request.headers, "projects.read");
        return send(200, { success: true, data: [{ ref: "prj_1", tenant_id: who.tenantId }],
          meta: { as_of: new Date().toISOString(), timezone: "UTC", scope: "authorized_records",
            coverage: "complete", total_count: 1 } });
      }
      return send(404, { success: false });
    } catch { return send(403, { success: false, error: { code: "PERMISSION_DENIED" } }); }
  });
  await new Promise((resolve) => source.listen(0, "127.0.0.1", resolve));
  const sourceBase = `http://127.0.0.1:${source.address().port}`;
  const replay = new MemoryReplayStore();
  sourceAuth = new HubSourceAuth({ appKey, audience: sourceBase, bearerToken: sourceBearer,
    delegationSecret: shared, consumeJti: replay.consume.bind(replay),
    authorize: async ({ tenantId, userRef }) => ({ active: true, allowed: true, tenantId,
      actor: { userRef } }) });
  const db = new HubDatabase("sqlite+pysqlite:///:memory:");
  db.sqlite.exec(`
    CREATE TABLE applications (id TEXT PRIMARY KEY, key TEXT, name TEXT, environment TEXT, status TEXT);
    CREATE TABLE connectors (id TEXT PRIMARY KEY, app_id TEXT, connector_type TEXT, base_url TEXT,
      manifest_path TEXT, timeout_ms INTEGER, tls_verify INTEGER, status TEXT);
    CREATE TABLE connector_secrets (id TEXT PRIMARY KEY, connector_id TEXT, secret_ciphertext TEXT,
      delegation_ciphertext TEXT, rotated_at TEXT, revoked_at TEXT);
    CREATE TABLE service_identities (id TEXT PRIMARY KEY, app_id TEXT, token_hash TEXT,
      scopes TEXT, allowed_tools TEXT, expires_at TEXT, revoked_at TEXT);
    CREATE TABLE tool_switches (app_id TEXT, tool_name TEXT);
    CREATE TABLE skills (id TEXT PRIMARY KEY, app_id TEXT, key TEXT, title TEXT,
      description TEXT, instructions TEXT, arguments TEXT, tools TEXT, enabled INTEGER);
    CREATE TABLE memory_settings (app_id TEXT PRIMARY KEY, enabled INTEGER,
      retention_days INTEGER, max_notes INTEGER, updated_at TEXT);
    CREATE TABLE user_memories (id TEXT PRIMARY KEY, app_id TEXT, subject TEXT,
      kind TEXT, key TEXT, content_ciphertext TEXT, created_at TEXT, updated_at TEXT,
      expires_at TEXT);
    CREATE TABLE chat_settings (app_id TEXT PRIMARY KEY, enabled INTEGER,
      provider TEXT, model TEXT, effort TEXT, instructions TEXT, welcome_message TEXT,
      suggestions TEXT, max_steps INTEGER, daily_limit INTEGER, updated_at TEXT);
    CREATE TABLE audit_events (id TEXT PRIMARY KEY, trace_id TEXT, action TEXT, actor_ref TEXT,
      app_key TEXT, module_key TEXT, tool_key TEXT, environment TEXT, result TEXT,
      error_code TEXT, duration_ms INTEGER, retry_count INTEGER, created_at TEXT);
  `);
  const appId = randomUUID();
  const connectorId = randomUUID();
  await db.run("INSERT INTO applications VALUES (?, ?, ?, ?, ?)", [appId, appKey, "Your App", "dev", "active"]);
  await db.run("INSERT INTO connectors VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [connectorId, appId,
    "source_managed", sourceBase, "/api/ai/v1/capabilities", 5000, true, "active"]);
  await db.run("INSERT INTO connector_secrets VALUES (?, ?, ?, ?, ?, ?)", [randomUUID(), connectorId,
    encryptSecret(encryptionKey, sourceBearer), encryptSecret(encryptionKey, shared), new Date().toISOString(), null]);
  await db.run("INSERT INTO service_identities VALUES (?, ?, ?, ?, ?, ?, ?)", [randomUUID(), appId,
    sha256(clientKey), JSON.stringify(["mcp:tools"]), null, null, null]);
  await db.run(`INSERT INTO skills (id, app_id, key, title, description, instructions,
    arguments, tools, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  [randomUUID(), appId, "project_overview", "Project overview", "Summarize projects",
    "Summarize {{period}} projects using the approved project list tool.",
    JSON.stringify([{ name: "period", description: "Time period", required: true }]),
    JSON.stringify(["your_app__projects__list"]), true]);
  await db.run("INSERT INTO memory_settings VALUES (?, ?, ?, ?, ?)",
    [appId, true, 90, 50, new Date().toISOString()]);
  await db.run("INSERT INTO chat_settings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    [appId, true, "openai_compatible", "test-model", "medium", "",
      "Welcome", JSON.stringify(["Show projects"]), 3, 20, new Date().toISOString()]);
  const model = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    const usedTool = body.messages.some((message) => message.role === "tool");
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ choices: [{ finish_reason: usedTool ? "stop" : "tool_calls",
      message: usedTool ? { role: "assistant", content: "The app has project data." }
        : { role: "assistant", content: null, tool_calls: [{
          id: "call_1", type: "function", function: {
            name: "list_data_sources", arguments: "{}" } }] } }] }));
  });
  await new Promise((resolve) => model.listen(0, "127.0.0.1", resolve));
  const config = { ...loadConfig(), allowedHosts: [], allowInsecureHttp: true,
    egressAllowLoopback: true, egressAllowedPorts: [source.address().port],
    modelEgressAllowedPorts: [model.address().port],
    chatOpenaiBaseUrl: `http://127.0.0.1:${model.address().port}/v1`,
    secretEncryptionKey: encryptionKey };
  const hub = createHubServer({ db, config });
  await new Promise((resolve) => hub.listen(0, "127.0.0.1", resolve));
  try {
    const client = new HubClient({ baseUrl: `http://127.0.0.1:${hub.address().port}`,
      clientKey, appKey, delegationSecret: shared });
    const actor = { tenantId: "tenant_a", userRef: "user_1" };
    const listed = await client.listTools(actor);
    assert.ok(listed.some((tool) => tool.name === "your_app__projects__list"));
    assert.ok(listed.some((tool) => tool.name === "recall_memory"));
    const saved = await client.callTool("save_memory", { key: "language", text: "Use Indonesian" }, actor);
    assert.equal(saved.data.kind, "profile");
    const recalled = await client.callTool("recall_memory", {}, actor);
    assert.equal(recalled.data.profile.language, "Use Indonesian");
    const forgotten = await client.callTool("forget_memory", { key: "language" }, actor);
    assert.equal(forgotten.data.removed, 1);
    const prompts = await client.listPrompts(actor);
    assert.ok(prompts.some((prompt) => prompt.name === "project_overview"));
    const prompt = await client.getPrompt("project_overview", { period: "this week" }, actor);
    assert.match(prompt.messages[0].content.text, /this week/);
    const chatConfig = await client.getChatConfig();
    assert.equal(chatConfig.enabled, true);
    const chat = await client.chatTurn({ message: "What data is available?" }, actor);
    assert.match(chat.text, /project data/);
    assert.equal(chat.tools[0].name, "list_data_sources");
    const stream = [];
    for await (const event of client.streamChatTurn({ message: "Summarize" }, actor)) {
      stream.push(event.event);
    }
    assert.ok(stream.includes("tool"));
    assert.ok(stream.includes("done"));
    const result = await client.callTool("your_app__projects__list", {}, actor);
    assert.deepEqual(result.data, [{ ref: "prj_1" }]);
    assert.equal(result.meta.contains_personal_data, false);
    const report = await client.callTool("run_report", { source: "projects", metrics: [{ fn: "count" }] }, actor);
    assert.equal(report.data.totals.count, 1);
    assert.equal(report.data.mode, "summary");
  } finally {
    await new Promise((resolve) => hub.close(resolve));
    await db.close();
    await new Promise((resolve) => model.close(resolve));
    await new Promise((resolve) => source.close(resolve));
  }
});
