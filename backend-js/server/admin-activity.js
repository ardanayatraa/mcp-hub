import { adminContext, bad, timestamp } from "./admin-common.js";

const windows = { "24h": 86_400_000, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000 };
const toMs = (value) => value == null ? null : Date.parse(timestamp(value));

function period(url, fallback = null) {
  const choice = url.searchParams.get("period") ?? fallback;
  if (choice && !(choice in windows)) throw bad("Period must be 24h, 7d or 30d");
  const from = choice ? new Date(Date.now() - windows[choice]).toISOString()
    : url.searchParams.get("from_time");
  const to = url.searchParams.get("to_time");
  for (const value of [from, to, url.searchParams.get("before")]) {
    if (value && (!/(?:Z|[+-]\d\d:\d\d)$/.test(value) || !Number.isFinite(Date.parse(value)))) {
      throw bad("Time filter must use an ISO timestamp with timezone");
    }
  }
  return { from, to };
}

async function appScope(db, context) {
  if (context.allowed === null) return null;
  const rows = await db.all("SELECT id, key, environment FROM applications");
  return new Set(rows.filter((row) => context.allowed === null || context.allowed.has(row.id))
    .map((row) => `${row.key}|\0${row.environment}`));
}

const visible = (event, scope) => scope === null ||
  scope.has(`${event.app_key}|\0${event.environment}`);
const eventView = (event) => ({ trace_id: event.trace_id, action: event.action,
  actor_ref: event.actor_ref, app_key: event.app_key, module_key: event.module_key,
  tool_key: event.tool_key, environment: event.environment, result: event.result,
  error_code: event.error_code, duration_ms: event.duration_ms,
  retry_count: event.retry_count, created_at: timestamp(event.created_at), tool: null });

async function events(db, context, url, limit = 20000) {
  const scope = await appScope(db, context);
  const { from, to } = period(url);
  const params = [];
  let where = "WHERE 1 = 1";
  if (from) { where += " AND created_at >= ?"; params.push(from); }
  if (to) { where += " AND created_at <= ?"; params.push(to); }
  if (url.searchParams.get("before")) {
    where += " AND created_at < ?"; params.push(url.searchParams.get("before"));
  }
  if (url.searchParams.get("trace_id")) {
    where += " AND trace_id = ?"; params.push(url.searchParams.get("trace_id"));
  }
  if (url.searchParams.get("environment")) {
    where += " AND environment = ?"; params.push(url.searchParams.get("environment"));
  }
  if (url.searchParams.get("app_key")) {
    where += " AND app_key = ?"; params.push(url.searchParams.get("app_key"));
  }
  if (url.searchParams.get("result")) {
    where += " AND result = ?"; params.push(url.searchParams.get("result"));
  }
  if (url.searchParams.get("kind") === "calls") where += " AND action = 'tool.execute'";
  if (url.searchParams.get("kind") === "admin") where += " AND action != 'tool.execute'";
  if (url.searchParams.get("tool_key")) {
    where += " AND tool_key LIKE ?";
    params.push(`%${url.searchParams.get("tool_key").slice(0, 80)}%`);
  }
  return (await db.all(`SELECT * FROM audit_events ${where} ORDER BY created_at DESC LIMIT ?`,
    [...params, limit])).filter((row) => visible(row, scope));
}

function percentile(values, percentile_) {
  if (!values.length) return 0;
  values.sort((a, b) => a - b);
  return values[Math.max(0, Math.ceil(values.length * percentile_) - 1)];
}

export async function handleActivity({ db, config, request, path, url }) {
  if (request.method !== "GET" || !["/executions", "/dashboard"].includes(path)) return undefined;
  const context = await adminContext(db, config, request);
  period(url);
  if (path === "/executions") {
    const count = Number(url.searchParams.get("limit") ?? 100);
    if (!Number.isInteger(count)) throw bad();
    return (await events(db, context, url, 10000))
      .slice(0, Math.max(1, Math.min(count, 200))).map(eventView);
  }
  const selected = (await db.all(`SELECT c.*, a.key AS app_key, a.name AS app_name,
    a.environment FROM connectors c JOIN applications a ON a.id = c.app_id`))
    .filter((row) => (context.allowed === null || context.allowed.has(row.app_id)) &&
      (!url.searchParams.get("environment") || row.environment === url.searchParams.get("environment")));
  const appIds = new Set(selected.map((row) => row.app_id));
  const connectorIds = new Set(selected.map((row) => row.id));
  const modules = (await db.all(`SELECT m.app_id, s.enabled FROM module_definitions m
    JOIN module_settings s ON s.module_id = m.id`)).filter((row) => appIds.has(row.app_id));
  const tools = (await db.all("SELECT connector_id, status FROM tool_definitions"))
    .filter((row) => connectorIds.has(row.connector_id));
  const keys = (await db.all("SELECT app_id, revoked_at, expires_at FROM service_identities"))
    .filter((row) => appIds.has(row.app_id) && !row.revoked_at &&
      (!row.expires_at || toMs(row.expires_at) > Date.now()));
  const start = url.searchParams.get("period") ? Date.now() - windows[url.searchParams.get("period")]
    : url.searchParams.get("from_time") ? Date.parse(url.searchParams.get("from_time"))
      : Date.now() - windows["24h"];
  const end = url.searchParams.get("to_time") ? Date.parse(url.searchParams.get("to_time")) : Date.now();
  if (start > end) throw bad("Time window is invalid");
  const callsUrl = new URL(url);
  callsUrl.searchParams.set("from_time", new Date(start).toISOString());
  callsUrl.searchParams.set("to_time", new Date(end).toISOString());
  callsUrl.searchParams.delete("period");
  const allEvents = await events(db, context, callsUrl, 100000);
  const calls = allEvents.filter((row) => row.action === "tool.execute");
  const success = calls.filter((row) => row.result === "success").length;
  const denied = calls.filter((row) => row.result === "denied").length;
  const counts = new Map();
  for (const call of calls) counts.set(call.tool_key ?? "unknown",
    (counts.get(call.tool_key ?? "unknown") ?? 0) + 1);
  const span = Math.max(3_600_000, end - start);
  const step = [3_600_000, 10_800_000, 21_600_000, 43_200_000, 86_400_000, 604_800_000]
    .find((value) => span / value <= 48) ?? 604_800_000;
  const length = Math.min(49, Math.ceil(span / step));
  const series = Array.from({ length }, (_, index) => {
    const low = start + index * step, high = index === length - 1 ? end + 1 : low + step;
    const matches = calls.filter((row) => toMs(row.created_at) >= low && toMs(row.created_at) < high);
    return { start: new Date(low).toISOString(), calls: matches.length,
      failed: matches.filter((row) => row.result !== "success").length };
  });
  const published = tools.filter((row) => row.status === "published").length;
  const enabled = modules.filter((row) => row.enabled === true || row.enabled === 1).length;
  return { from: new Date(start).toISOString(), to: new Date(end).toISOString(),
    environment: url.searchParams.get("environment"), apps_total: selected.filter((row) => row.status !== "archived").length,
    connectors_active: selected.filter((row) => row.status === "active").length,
    connectors_failing: selected.filter((row) => row.failure_count > 0).length,
    modules_enabled: enabled, tools_published: published,
    tools_draft: tools.filter((row) => row.status === "draft").length,
    keys_active: keys.length, executions: calls.length, success, denied,
    failure: calls.length - success, success_rate: calls.length ? success / calls.length : null,
    latency_p95_ms: percentile(calls.map((row) => row.duration_ms ?? 0), 0.95),
    retries: calls.reduce((sum, row) => sum + (row.retry_count ?? 0), 0),
    top_tools: [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
      .map(([tool_key, count]) => ({ tool_key, calls: count, tool: null })),
    series, recent: allEvents.filter((row) => !row.action.startsWith("auth."))
      .slice(0, 8).map(eventView),
    checklist: { app_connected: selected.some((row) => row.status === "active"),
      source_enabled: enabled > 0, tool_published: published > 0, key_created: keys.length > 0 } };
}
