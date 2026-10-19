import { adminContext, bool, json } from "./admin-common.js";
import { MEMORY_TOOLS } from "./memory.js";
import { FILTER_OPS, INTERVALS, MAX_LIMIT, METRIC_FUNCTIONS, REPORT_INPUT } from "./report.js";

const templates = [
  { key: "read", label: "Read records", operation: "read",
    summary: "Expose one reviewed read route: list, look up or count records." },
  { key: "report", label: "Report", operation: "read",
    summary: "A saved summary of a data source." },
  ...["create", "update", "delete"].map((key) => ({
    key, label: `${key[0].toUpperCase()}${key.slice(1)} record`, operation: key,
    summary: `Send a ${key} request to the connected application.` })),
];

const kind = (tool) => ["create", "update", "delete", "report"].includes(tool.template)
  ? tool.template : ["list", "count", "get"].includes(tool.tool_key.split(".").at(-1))
    ? tool.tool_key.split(".").at(-1) : "read";

export async function handleCapabilities({ db, config, request, path }) {
  if (request.method !== "GET" || !["/tools/templates", "/tools/builtins",
    "/tools/capabilities"].includes(path)) return undefined;
  const context = await adminContext(db, config, request);
  if (path === "/tools/templates") return templates;
  const builtins = [
    { name: "list_data_sources", title: "List data sources",
      description: "List data sources this client may read.",
      inputSchema: { type: "object", additionalProperties: false, properties: {} },
      requires: null },
    { name: "run_report", title: "Run report",
      description: "Read authorized records and return records, totals or grouped metrics.",
      inputSchema: REPORT_INPUT, requires: null },
    ...MEMORY_TOOLS.map((tool) => ({ ...tool, requires: "memory" })),
  ];
  if (path === "/tools/builtins") return builtins;
  const apps = (await db.all(`SELECT c.*, a.key AS app_key, a.name AS app_name, a.environment
    FROM connectors c JOIN applications a ON a.id = c.app_id WHERE c.status != 'archived'
    ORDER BY a.name`)).filter((row) => context.allowed === null || context.allowed.has(row.app_id));
  const ids = new Set(apps.map((row) => row.app_id));
  const connectorIds = new Set(apps.map((row) => row.id));
  const tools = (await db.all(`SELECT connector_id, tool_key, mcp_name, template, status
    FROM tool_definitions WHERE status != 'archived'`)).filter((row) => connectorIds.has(row.connector_id));
  const sourceRows = (await db.all(`SELECT m.app_id, s.enabled FROM module_definitions m
    JOIN module_settings s ON s.module_id = m.id`)).filter((row) => ids.has(row.app_id));
  const switches = (await db.all("SELECT app_id, tool_name FROM tool_switches"))
    .filter((row) => ids.has(row.app_id));
  const off = new Set(switches.map((row) => `${row.app_id}|${row.tool_name}`));
  const skills = (await db.all("SELECT app_id FROM skills WHERE enabled = ?", [true]))
    .filter((row) => ids.has(row.app_id));
  const memories = new Set((await db.all("SELECT app_id FROM memory_settings WHERE enabled = ?", [true]))
    .map((row) => row.app_id));
  const chats = (await db.all("SELECT * FROM chat_settings")).filter((row) => ids.has(row.app_id));
  const keys = (await db.all("SELECT app_id, scopes FROM service_identities WHERE revoked_at IS NULL"))
    .filter((row) => ids.has(row.app_id));
  const byKind = Object.fromEntries(["list", "count", "get", "read", "report", "create",
    "update", "delete"].map((name) => [name, 0]));
  const matrix = apps.map((app) => {
    const mine = tools.filter((tool) => tool.connector_id === app.id);
    const live = mine.filter((tool) => tool.status === "published" &&
      !off.has(`${app.app_id}|${tool.mcp_name}`));
    const kinds = Object.fromEntries(Object.keys(byKind).map((name) => [name, 0]));
    for (const tool of live) { kinds[kind(tool)]++; byKind[kind(tool)]++; }
    const chat = chats.find((row) => row.app_id === app.app_id);
    return { connector_id: app.id, name: app.app_name, app_key: app.app_key,
      status: app.status, mode: app.connector_type,
      sources_on: sourceRows.filter((row) => row.app_id === app.app_id && bool(row.enabled)).length,
      tools_total: mine.length, tools_live: live.length,
      switched_off: switches.filter((row) => row.app_id === app.app_id).length,
      kinds, skills: skills.filter((row) => row.app_id === app.app_id).length,
      memory: memories.has(app.app_id), chat: !!chat && bool(chat.enabled),
      chat_model: chat && bool(chat.enabled) ? `${chat.provider} · ${chat.model}` : null };
  });
  const usageRows = await db.all(`SELECT tool_key, count(*) AS calls FROM audit_events
    WHERE action = 'tool.execute' AND created_at >= ? GROUP BY tool_key`,
  [new Date(Date.now() - 7 * 86_400_000).toISOString()]);
  return { version: "0.1.0-node", protocol: {
    endpoint: config.mcpPublicUrl, transport: "Streamable HTTP, stateless JSON responses",
    methods: ["initialize", "tools/list", "tools/call", "prompts/list", "prompts/get"],
    auth: "Authorization: Bearer <client key>",
    user_context: "X-Hub-Delegation, signed by the app, valid up to 150 seconds",
    app_auth: "Authorization: Bearer <app token>, plus X-Hub-Assertion for the signed-in user",
    chat: "/chat/v1/config and /chat/v1/turn (Server-Sent Events)",
    sdk: "Official MCP TypeScript SDK" },
    summary: { apps: apps.length, apps_active: apps.filter((row) => row.status === "active").length,
      data_sources_on: matrix.reduce((sum, row) => sum + row.sources_on, 0),
      tools_total: tools.length + builtins.length,
      tools_live: matrix.reduce((sum, row) => sum + row.tools_live, 0) + 2,
      by_kind: byKind, skills: skills.length, memory_apps: memories.size,
      chat_apps: matrix.filter((row) => row.chat).length, switched_off: switches.length,
      client_keys: keys.length, write_keys: keys.filter((row) =>
        json(row.scopes, []).includes("tools:write")).length },
    report: { filters: FILTER_OPS, metrics: METRIC_FUNCTIONS, intervals: INTERVALS,
      max_group_by: 2, max_metrics: 6, max_filters: 10, max_rows: MAX_LIMIT,
      max_records_read: config.reportMaxRecords, timeout_seconds: config.reportTimeoutSeconds },
    limits: { tool_calls: `${config.toolRateLimit} per ${config.toolRateWindowSeconds} s per client key and tool`,
      page_size: config.maxRecords, chat_messages: "20 per minute per user",
      payload_bytes: config.maxPayloadBytes }, apps: matrix,
    usage: Object.fromEntries(usageRows.map((row) => [row.tool_key, Number(row.calls)])) };
}
