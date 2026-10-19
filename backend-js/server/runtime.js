import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import Ajv from "ajv";
import { HubSdkError } from "../src/errors.js";
import { connectorSecrets } from "./catalog.js";
import { isSensitivePath, projectRecord, rejectForbiddenKeys, treeContainsPii } from "./privacy.js";
import { iso, now, token } from "./security.js";
import { joinSourceUrl, sourceRequest } from "./source-http.js";
import { chartHint, parseSpec, prepareRows, runReport, sourceFields, summarize, validateSpec } from "./report.js";
import { hit } from "./security.js";
import { executeMemory } from "./memory.js";

const ajv = new Ajv({ strict: false, allErrors: true });
const safeUpstreamCodes = new Set(["PERMISSION_DENIED", "VALIDATION_FAILED", "NOT_FOUND", "RATE_LIMITED", "SCHEMA_MISMATCH"]);
const fail = (code, message, status) => { throw new HubSdkError(message, code, status); };

export function verifyDelegation(value, secret, appKey) {
  if (!value) return null;
  let payload;
  try {
    if (typeof value !== "string" || value.length > 4096 || value.split(".").length !== 2) throw new Error();
    const [encoded, signed] = value.split(".");
    if (!/^[A-Za-z0-9_-]+$/.test(encoded) || !/^[A-Za-z0-9_-]+$/.test(signed)) throw new Error();
    const raw = Buffer.from(encoded, "base64url");
    const signature = Buffer.from(signed, "base64url");
    const expected = createHmac("sha256", secret).update(raw).digest();
    if (signature.length !== expected.length || !timingSafeEqual(signature, expected)) throw new Error();
    payload = JSON.parse(raw.toString("utf8"));
  } catch { fail("PERMISSION_DENIED", "Delegated user context is not valid", 403); }
  if (!payload || payload.aud !== "mcp-hub" || payload.app_key !== appKey ||
      !Number.isInteger(payload.exp) || payload.exp <= now() || payload.exp > now() + 150 ||
      typeof payload.tenant_id !== "string" || !payload.tenant_id ||
      typeof payload.user_ref !== "string" || !payload.user_ref) {
    fail("PERMISSION_DENIED", "Delegated user context does not match this application", 403);
  }
  return payload;
}

export function signAssertion(payload, secret, audience) {
  const body = Buffer.from(JSON.stringify({ app_key: payload.app_key, tenant_id: payload.tenant_id,
    user_ref: payload.user_ref, aud: audience, jti: token(18), exp: now() + 60 }));
  return `${body.toString("base64url")}.${createHmac("sha256", secret).update(body).digest("base64url")}`;
}

function validate(schema, value, message, code = "VALIDATION_FAILED") {
  let valid;
  try { valid = ajv.compile(schema)(value); } catch { valid = false; }
  if (!valid) fail(code, message, 422);
}

function safeMeta(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("SCHEMA_MISMATCH", "Dataset metadata is required", 422);
  const selected = Object.fromEntries(["as_of", "timezone", "scope", "coverage"].map((key) => [key, value[key]]));
  if (treeContainsPii(selected)) fail("PII_DETECTED", "Response blocked by privacy policy", 422);
  if (Object.values(selected).some((item) => typeof item !== "string") ||
      !/^[a-z][a-z0-9_-]{0,63}$/.test(selected.scope) ||
      !["complete", "partial"].includes(selected.coverage)) fail("SCHEMA_MISMATCH", "Dataset metadata fields are invalid", 422);
  try {
    new Intl.DateTimeFormat("en", { timeZone: selected.timezone });
    if (!/(?:Z|[+-]\d\d:\d\d)$/.test(selected.as_of) || !Number.isFinite(Date.parse(selected.as_of))) throw new Error();
  } catch { fail("SCHEMA_MISMATCH", "Dataset time metadata is invalid", 422); }
  selected.contains_personal_data = false;
  if ("total_count" in value) {
    if (!Number.isInteger(value.total_count) || value.total_count < 0 || value.total_count > 1_000_000_000) {
      fail("SCHEMA_MISMATCH", "Dataset total count is invalid", 422);
    }
    selected.total_count = value.total_count;
  }
  if ("has_more" in value) {
    if (typeof value.has_more !== "boolean" || (value.has_more && value.coverage !== "partial")) {
      fail("SCHEMA_MISMATCH", "Dataset pagination is invalid", 422);
    }
    selected.has_more = value.has_more;
  }
  if (value.next_cursor !== null && value.next_cursor !== undefined) {
    if (typeof value.next_cursor !== "string" || value.next_cursor.length > 128 ||
        !/^[A-Za-z0-9_-]+$/.test(value.next_cursor) || treeContainsPii(value.next_cursor)) {
      fail("SCHEMA_MISMATCH", "Dataset cursor is invalid", 422);
    }
    selected.next_cursor = value.next_cursor;
  }
  return selected;
}

function renderPath(template, arguments_) {
  const args = { ...arguments_ };
  const path = template.replace(/\{([A-Za-z][A-Za-z0-9_]{0,40})\}/g, (_, name) => {
    if (!(name in args)) fail("VALIDATION_FAILED", "Required path argument is missing", 422);
    const value = String(args[name]);
    delete args[name];
    return encodeURIComponent(value);
  });
  return { path, args };
}

function parseRows(status, raw, maxRows, errorMapping = {}) {
  if (status === 401) fail("UPSTREAM_UNAUTHORIZED", "The connected application rejected the service credential", 401);
  if (status === 403) fail("PERMISSION_DENIED", "The connected application denied the request", 403);
  if (status === 404) fail("NOT_FOUND", "The connected application hid or could not find the resource", 404);
  if (status === 429) fail("RATE_LIMITED", "The connected application rate limited the request", 429);
  if (status >= 400) {
    const code = errorMapping[String(status)] ?? "UPSTREAM_ERROR";
    fail(code, "The connected application returned an error", code === "UPSTREAM_TIMEOUT" ? 504 : 502);
  }
  let document;
  try { document = JSON.parse(raw); } catch { fail("SCHEMA_MISMATCH", "Upstream response was not valid JSON", 502); }
  if (document?.success === false) {
    const code = safeUpstreamCodes.has(document.error?.code) ? document.error.code : "UPSTREAM_ERROR";
    fail(code, "The connected application rejected the request", 422);
  }
  if (!document || document.success !== true || !Array.isArray(document.data) ||
      document.data.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
    fail("SCHEMA_MISMATCH", "Upstream response records are invalid", 502);
  }
  if (document.data.length > maxRows) fail("PAYLOAD_TOO_LARGE", "Upstream response exceeds the record limit", 413);
  return { rows: document.data, meta: document.meta ?? {} };
}

function applyTenant(rows, meta, field, tenantId) {
  if (!field || rows.some((row) => typeof row[field] !== "string")) {
    fail("SCHEMA_MISMATCH", "Upstream tenant context is missing", 502);
  }
  const kept = rows.filter((row) => row[field] === tenantId).map((row) => {
    const copy = { ...row };
    delete copy[field];
    return copy;
  });
  if (kept.length !== rows.length) {
    const next = { ...meta, coverage: "partial" };
    delete next.total_count;
    delete next.next_cursor;
    return { rows: kept, meta: next, dropped: true };
  }
  return { rows: kept, meta, dropped: false };
}

async function audit(db, caller, tool, trace, result, code, durationMs, retryCount) {
  await db.run(`INSERT INTO audit_events
    (id, trace_id, action, actor_ref, app_key, module_key, tool_key, environment,
      result, error_code, duration_ms, retry_count, created_at)
    VALUES (?, ?, 'tool.execute', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  [randomUUID(), trace, caller.actorRef, caller.application.key, tool.module?.key ?? null,
    tool.key, caller.application.environment, result, code, durationMs, retryCount, iso()]);
}

async function runReportBuiltin({ db, config, caller, tool, args, delegationHeader, givenSecrets, trace }) {
  const source = args.source;
  if (typeof source !== "string" || !source || source.length > 130) {
    fail("VALIDATION_FAILED", "source must name a data source from list_data_sources", 422);
  }
  const key = source.startsWith(`${caller.application.key}.`)
    ? source.slice(caller.application.key.length + 1) : source;
  const record = tool.sourceModules.get(key);
  if (!record || !record.operations.includes("read")) fail("MODULE_DISABLED", "Data source is not enabled", 403);
  const { module, policies, route } = record;
  if (!route) fail("NOT_SUPPORTED", "This data source has no list route that reports can read", 422);
  const spec = parseSpec(Object.fromEntries(Object.entries(args).filter(([name]) => name !== "source")));
  const fields = sourceFields(route.output_schema, policies);
  validateSpec(spec, fields);
  const secrets = givenSecrets ?? await connectorSecrets(db, config, caller.connector.id);
  const delegation = verifyDelegation(delegationHeader, secrets.delegation, caller.application.key);
  if (route.requires_user_context && !delegation) {
    fail("PERMISSION_DENIED", "This data source requires source-verified user context", 403);
  }
  const properties = route.input_schema.properties ?? {};
  const pushed = {};
  for (const item of spec.filters) {
    const input = properties[item.field];
    if (item.op !== "eq" || !input || item.value === null || ["limit", "cursor"].includes(item.field)) continue;
    if (input.type === "string" && !input.enum) continue;
    if (ajv.compile(input)(item.value)) pushed[item.field] = item.value;
  }
  const pageSize = Math.min(module.max_page_size ?? 50, config.maxRecords, properties.limit?.maximum ?? 50);
  const deadline = Date.now() + config.reportTimeoutSeconds * 1000;
  const rows = [];
  let cursor = null;
  let pages = 0;
  let firstMeta = null;
  let lastMeta = null;
  let truncated = false;
  let retries = 0;
  while (true) {
    const arguments_ = { ...pushed };
    if (properties.limit?.type === "integer") arguments_.limit = pageSize;
    if (cursor !== null && properties.cursor?.type === "string") arguments_.cursor = cursor;
    validate(route.input_schema, arguments_, "Report page arguments are invalid");
    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      if (!pages) fail("UPSTREAM_TIMEOUT", "The connected application timed out", 504);
      truncated = true;
      break;
    }
    const headers = () => ({ Authorization: `Bearer ${secrets.bearer}`, Accept: "application/json",
      "X-Request-ID": `req_${token(12)}`,
      ...(delegation ? { "X-Hub-Assertion": signAssertion(delegation, secrets.delegation, caller.connector.base_url) } : {}) });
    let sent;
    try {
      sent = await sourceRequest({ method: route.method,
        url: joinSourceUrl(caller.connector.base_url, route.path_template), config, headers,
        params: route.method === "GET" ? arguments_ : undefined,
        jsonBody: route.method === "POST" ? arguments_ : undefined,
        timeoutMs: Math.min(remaining, caller.connector.timeout_ms), maxBytes: config.maxPayloadBytes,
        tlsVerify: caller.connector.tls_verify === true || caller.connector.tls_verify === 1,
        retries: route.method === "GET" ? 2 : 0 });
    } catch (cause) {
      if (pages && ["UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE"].includes(cause.code)) { truncated = true; break; }
      throw cause;
    }
    retries += sent.retryCount;
    const page = parseRows(sent.status, sent.body, pageSize);
    const scoped = route.requires_user_context
      ? applyTenant(page.rows, page.meta, route.tenant_field, delegation.tenant_id)
      : { rows: page.rows, meta: page.meta };
    safeMeta(scoped.meta);
    pages++;
    firstMeta ??= scoped.meta;
    lastMeta = scoped.meta;
    rows.push(...scoped.rows);
    const next = scoped.meta.has_more ? scoped.meta.next_cursor : null;
    if (rows.length >= config.reportMaxRecords) {
      truncated = !!next || rows.length > config.reportMaxRecords;
      break;
    }
    if (!next || !properties.cursor || next === cursor) break;
    cursor = next;
  }
  const scanned = rows.slice(0, config.reportMaxRecords);
  const meta = safeMeta(firstMeta);
  const coverage = truncated || lastMeta.coverage === "partial" ? "partial" : "complete";
  delete meta.has_more;
  delete meta.next_cursor;
  delete meta.total_count;
  meta.coverage = coverage;
  const prepared = prepareRows(scanned, fields);
  const result = runReport(prepared.rows, spec, fields, meta.timezone);
  if (prepared.hidden) result.notes = [...new Set([...result.notes,
    `${prepared.hidden} value(s) were hidden by the privacy filter.`])].sort();
  const summary = summarize(result, { label: `${caller.application.name} · ${module.name}`,
    scanned: scanned.length, coverage, truncated, filtered: !!spec.filters.length });
  Object.assign(meta, { source: module.key, records_read: scanned.length, pages, truncated });
  return { payload: { success: true, data: Object.fromEntries(["mode", "columns", "rows", "totals", "groups"]
    .map((name) => [name, result[name]])), summary, chart: chartHint(result), notes: result.notes,
  meta, trace_id: trace }, retries };
}

export async function executeTool({ db, config, caller, tool, arguments_: args,
                                    delegationHeader, secrets: givenSecrets }) {
  const trace = `tr_${token(12)}`;
  const started = Date.now();
  let retryCount = 0;
  try {
    if (!args || typeof args !== "object" || Array.isArray(args)) fail("VALIDATION_FAILED", "Tool arguments must be an object", 422);
    if (treeContainsPii(args)) fail("PII_DETECTED", "Input blocked by privacy policy", 422);
    rejectForbiddenKeys(args);
    hit(`tool:${caller.actorRef}:${tool.name}`, config.toolRateLimit, config.toolRateWindowSeconds);
    if (tool.operation === "builtin" && tool.name === "list_data_sources") {
      if (Object.keys(args).length) fail("VALIDATION_FAILED", "Tool arguments are invalid", 422);
      const payload = { success: true, data: tool.sources, meta: {
        scope: "enabled_sources", coverage: "complete", contains_personal_data: false }, trace_id: trace };
      await audit(db, caller, tool, trace, "success", null, Math.max(1, Date.now() - started), 0);
      return payload;
    }
    if (tool.operation === "builtin" && tool.name === "run_report") {
      const result = await runReportBuiltin({ db, config, caller, tool, args,
        delegationHeader, givenSecrets, trace });
      retryCount = result.retries;
      await audit(db, caller, tool, trace, "success", null, Math.max(1, Date.now() - started), retryCount);
      return result.payload;
    }
    if (tool.operation === "saved_report") {
      validate(tool.inputSchema, args, "Input does not match the saved report schema");
      const saved = tool.reportSpec;
      const result = await runReportBuiltin({ db, config, caller, tool,
        args: { ...saved, source: tool.module.key,
          limit: args.limit ?? saved.limit,
          filters: [...(saved.filters ?? []), ...(args.filters ?? [])] },
        delegationHeader, givenSecrets, trace });
      retryCount = result.retries;
      await audit(db, caller, tool, trace, "success", null, Math.max(1, Date.now() - started), retryCount);
      return result.payload;
    }
    if (tool.operation === "memory") {
      validate(tool.inputSchema, args, "Input does not match the memory tool schema");
      const payload = await executeMemory({ db, config, caller, tool, args,
        delegationHeader, givenSecrets, trace });
      await audit(db, caller, tool, trace, "success", null, Math.max(1, Date.now() - started), 0);
      return payload;
    }
    const route = tool.route;
    if (!route || caller.connector?.status !== "active") fail("CONNECTOR_INACTIVE", "Connector is not active", 409);
    validate(tool.inputSchema, args, "Input does not match the tool schema");
    validate(route.input_schema, args, "Input does not match the reviewed route");
    const secrets = givenSecrets ?? await connectorSecrets(db, config, caller.connector.id);
    const delegation = verifyDelegation(delegationHeader, secrets.delegation, caller.application.key);
    if (route.requires_user_context && !delegation) {
      fail("PERMISSION_DENIED", "A signed-in user context is required", 403);
    }
    const { path, args: remaining } = renderPath(route.path_template, args);
    const write = tool.operation !== "read";
    const mapping = tool.mapping ?? {};
    const headers = () => ({ Authorization: `Bearer ${secrets.bearer}`, Accept: "application/json",
      "X-Request-ID": `req_${token(12)}`,
      ...(write ? { "Idempotency-Key": trace } : {}),
      ...(delegation ? { "X-Hub-Assertion": signAssertion(delegation, secrets.delegation, caller.connector.base_url) } : {}) });
    const sent = await sourceRequest({ method: route.method, url: joinSourceUrl(caller.connector.base_url, path),
      config, headers, params: ["GET", "DELETE"].includes(route.method) ? remaining : undefined,
      jsonBody: ["GET", "DELETE"].includes(route.method) ? undefined : remaining,
      timeoutMs: mapping.timeout_ms ?? caller.connector.timeout_ms,
      maxBytes: mapping.max_payload_bytes ?? config.maxPayloadBytes,
      tlsVerify: caller.connector.tls_verify === true || caller.connector.tls_verify === 1,
      retries: route.method === "GET" ? 2 : 0, write });
    retryCount = sent.retryCount;
    const { rows, meta } = parseRows(sent.status, sent.body,
      Math.min(tool.module.max_page_size ?? 50, 50), mapping.error_mapping);
    const scoped = route.requires_user_context
      ? applyTenant(rows, meta, route.tenant_field, delegation.tenant_id)
      : { rows, meta, dropped: false };
    if (write && scoped.dropped) fail("SCHEMA_MISMATCH", "The application's receipt does not match the user context", 502);
    const policies = write
      ? Object.fromEntries(tool.allowFields.map((field) => [field, "allowed_for_ai"])) : tool.policies;
    const projected = scoped.rows.map((row) => projectRecord(row, tool.allowFields, policies));
    const output = { ...route.output_schema, items: { ...route.output_schema.items,
      required: (route.output_schema.items.required ?? []).filter((field) => tool.allowFields.includes(field)),
      properties: Object.fromEntries(Object.entries(route.output_schema.items.properties)
        .filter(([field]) => tool.allowFields.includes(field))) } };
    validate(output, projected, "Response does not match the reviewed output schema", "SCHEMA_MISMATCH");
    const payload = write
      ? { success: true, data: projected, meta: { operation: tool.operation, as_of: iso(),
        contains_personal_data: false,
        ...(typeof meta.requires_confirmation === "boolean" ? { requires_confirmation: meta.requires_confirmation } : {}) },
      trace_id: trace }
      : { success: true, data: projected, meta: safeMeta(scoped.meta), trace_id: trace };
    await audit(db, caller, tool, trace, "success", null, Math.max(1, Date.now() - started), retryCount);
    return payload;
  } catch (cause) {
    const error = cause instanceof HubSdkError ? cause
      : new HubSdkError("The tool failed unexpectedly", "INTERNAL", 500);
    await audit(db, caller, tool, trace, [401, 403].includes(error.status) ? "denied" : "error",
      error.code, Math.max(1, Date.now() - started), retryCount).catch(() => {});
    throw error;
  }
}
