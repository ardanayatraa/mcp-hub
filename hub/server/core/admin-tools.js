import { randomUUID } from "node:crypto";
import Ajv from "ajv";
import { HubError } from "./errors.js";
import { adminContext, audit, bad, bundle, conflict, id, json, missing, textField } from "./admin-common.js";
import { catalogForCaller, mcpName } from "./catalog.js";
import { digest, validateInputSchema, validateOutputSchema } from "./manifest.js";
import { isSensitivePath, treeContainsPii } from "./privacy.js";
import { parseSpec, sourceFields, validateSpec, REPORT_INPUT, prepareRows, runReport,
  chartHint, summarize } from "./report.js";
import { iso } from "./security.js";
import { validateDestination } from "./source-http.js";

const ajv = new Ajv({ strict: false, allErrors: true });
const templates = new Set(["read", "report", "create", "update", "delete"]);
const write = new Set(["create", "update", "delete"]);
const editable = new Set(["title", "description", "method", "path_template", "input_schema",
  "output_schema", "allow_fields", "report", "timeout_ms", "max_payload_bytes", "pagination",
  "error_mapping", "audit_level", "requires_user_context", "tenant_field", "safe_query", "risk"]);
const failure = (message, code = "VALIDATION_FAILED", status = 422) => new HubError(message, code, status);
const object = (value) => value && typeof value === "object" && !Array.isArray(value);
const asJson = (value) => JSON.stringify(value);

async function scoped(db, context, toolId) {
  const tool = await db.one("SELECT * FROM tool_definitions WHERE id = ?", [toolId]);
  if (!tool) throw missing("Tool was not found");
  const connector = await bundle(db, context, tool.connector_id);
  const mapping = await db.one("SELECT * FROM rest_tool_mappings WHERE id = ?", [tool.mapping_id]);
  const module = await db.one("SELECT * FROM module_definitions WHERE app_id = ? AND module_key = ?",
    [connector.app_id, tool.module_key]);
  if (!mapping || !module) throw missing("Tool route was not found");
  return { tool, connector, mapping, module };
}

function manual(connector) {
  if (connector.connector_type === "source_managed")
    throw failure("Manage models, fields and operations in the connected application", "POLICY_LOCKED", 409);
}

function fingerprint(tool, mapping, module) {
  const route = Object.fromEntries(["method", "path_template", "timeout_ms", "max_payload_bytes",
    "safe_query", "requires_user_context", "tenant_field", "pagination", "audit_level",
    "error_mapping"].map((key) => [key, ["pagination", "error_mapping"].includes(key)
    ? json(mapping[key], {}) : ["safe_query", "requires_user_context"].includes(key)
      ? !!mapping[key] : mapping[key]]));
  const payload = { key: tool.tool_key, version: tool.version, source: module.manifest_hash,
    description: tool.description, input: json(tool.input_schema), output: json(tool.output_schema),
    policy: json(tool.output_policy), risk: tool.risk, mapping: route };
  if (tool.template !== "read") payload.template = tool.template;
  if (tool.report_spec) payload.report = json(tool.report_spec);
  if (tool.title) payload.title = tool.title;
  return digest(payload);
}

async function build(db, connector, module, data) {
  const template = data.template ?? "read";
  if (!templates.has(template)) throw bad("Unknown tool template");
  const manifest = json(module.manifest_json);
  const setting = await db.one("SELECT * FROM module_settings WHERE module_id = ?", [module.id]);
  const routes = [...(manifest.read_endpoints ?? []), ...(manifest.write_endpoints ?? [])];
  const operation = write.has(template) ? template : "read";
  const candidates = routes.filter((route) => (route.operation ?? "read") === operation &&
    route.kind === (write.has(template) ? "write" : "read") &&
    (template !== "report" || (route.output_schema.maxItems > 1 &&
      (route.input_schema.required ?? []).every((name) => ["limit", "cursor"].includes(name)))));
  const route = data.path_template ? routes.find((item) => item.path_template === data.path_template &&
    (!data.method || item.method === data.method)) : candidates.length === 1 ? candidates[0] :
      template === "report" ? candidates[0] : null;
  if (!route) throw bad("Choose one of the data source's reviewed endpoints");
  if (!candidates.includes(route)) throw failure("This template needs a reviewed route of the data source");
  for (const key of ["requires_user_context", "tenant_field", "safe_query"]) {
    if (data[key] != null && data[key] !== route[key])
      throw failure("Mapping cannot weaken source authorization requirements", "POLICY_LOCKED");
  }
  const risk = write.has(template) ? "write" : "read_only";
  if (data.risk != null && data.risk !== risk) throw bad("Tool risk does not match its template");
  const toolKey = String(data.tool_key ?? "").trim();
  const fullKey = toolKey.startsWith(`${connector.app_key}.`) ? toolKey : `${connector.app_key}.${toolKey}`;
  if (!/^[a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){1,4}$/.test(fullKey)) throw bad("Tool key is invalid");
  const title = data.title == null ? null : String(data.title).trim().slice(0, 120) || null;
  if (title && (treeContainsPii(title) || /ignore previous|system prompt|<\|/i.test(title))) throw bad("Tool title was rejected");
  const description = textField(data.description || `${template === "report" ? "Summarize" :
    write.has(template) ? template[0].toUpperCase() + template.slice(1) : "Read"} ${module.name} records from ${connector.app_name}.`,
  "Description", 3, 1000);
  if (treeContainsPii(description) || /ignore previous|system prompt|<\||```/i.test(description)) throw bad("Tool description was rejected");
  let input, output, allow, report = null;
  const routeFields = Object.keys(route.output_schema.items.properties);
  if (template === "report") {
    report = parseSpec(data.report ?? {}, true);
    const policyRows = await db.all("SELECT field_path, classification FROM field_policies WHERE module_id = ?", [module.id]);
    validateSpec(report, sourceFields(route.output_schema,
      Object.fromEntries(policyRows.map((item) => [item.field_path, item.classification]))));
    input = { type: "object", additionalProperties: false, properties: {
      limit: REPORT_INPUT.properties.limit,
      ...(report.allow_filters ? { filters: REPORT_INPUT.properties.filters } : {}) } };
    output = {}; allow = [];
  } else {
    input = validateInputSchema(data.input_schema || route.input_schema);
    if (Object.keys(input.properties).some((name) => !(name in route.input_schema.properties)) ||
        (route.input_schema.required ?? []).some((name) => !(input.required ?? []).includes(name)))
      throw failure("Input parameters are outside the reviewed source route", "POLICY_LOCKED");
    if ([...route.path_template.matchAll(/\{(\w+)\}/g)].some((match) => !(match[1] in input.properties)))
      throw bad("Path placeholder is not an input property");
    const policies = await db.all("SELECT field_path, classification FROM field_policies WHERE module_id = ?", [module.id]);
    const visible = new Set(policies.filter((p) => ["allowed", "allowed_for_ai"].includes(p.classification) &&
      !isSensitivePath(p.field_path)).map((p) => p.field_path));
    allow = data.allow_fields?.length ? data.allow_fields : routeFields.filter((name) => write.has(template) ?
      !isSensitivePath(name) : visible.has(name));
    if (!Array.isArray(allow) || (!write.has(template) && !allow.length) ||
        allow.some((name) => !routeFields.includes(name) || isSensitivePath(name) ||
          (!write.has(template) && !visible.has(name))))
      throw failure("Output fields are outside the visible source policy", "POLICY_LOCKED");
    const projected = structuredClone(route.output_schema);
    projected.items.properties = Object.fromEntries(Object.entries(projected.items.properties)
      .filter(([name]) => allow.includes(name)));
    projected.items.required = (projected.items.required ?? []).filter((name) => allow.includes(name));
    output = validateOutputSchema(data.output_schema || projected, allow,
      write.has(template) ? 50 : module.max_page_size);
  }
  const timeout = data.timeout_ms ?? 5000, maxPayload = data.max_payload_bytes ?? 1_048_576;
  if (!Number.isInteger(timeout) || timeout < 100 || timeout > 30000 ||
      !Number.isInteger(maxPayload) || maxPayload < 1024 || maxPayload > 1_048_576) throw bad("Timeout or response size limit is out of range");
  const pagination = data.pagination ?? Object.fromEntries(["limit", "cursor"].filter((name) =>
    name in input.properties).map((name) => [`${name}_parameter`, name]));
  if (!object(pagination) || Object.entries(pagination).some(([key, name]) =>
    !["limit_parameter", "cursor_parameter"].includes(key) ||
    input.properties[name]?.type !== (key === "limit_parameter" ? "integer" : "string"))) throw bad("Pagination mapping is invalid");
  if (!object(data.error_mapping ?? {}) || Object.keys(data.error_mapping ?? {}).some((key) =>
    !["400", "401", "403", "404", "409", "422", "429", "500", "502", "503", "504"].includes(key))) throw bad("Error mapping is invalid");
  const mapping = { method: route.method, path_template: route.path_template, timeout_ms: timeout,
    max_payload_bytes: maxPayload, safe_query: route.safe_query, requires_user_context: route.requires_user_context,
    tenant_field: route.tenant_field, pagination, error_mapping: data.error_mapping ?? {},
    audit_level: data.audit_level ?? "standard" };
  if (!["minimal", "standard", "detailed"].includes(mapping.audit_level)) throw bad("Audit level is invalid");
  return { template, tool_key: fullKey, title, description, input_schema: input,
    output_schema: output, output_policy: { allow_fields: allow }, report_spec: report, risk,
    module_key: module.module_key, policy_version: setting.policy_version, mapping };
}

async function view(db, toolId) {
  const row = await db.one(`SELECT t.*, c.app_id, c.connector_type, a.key AS app_key, a.name AS app_name,
    a.environment, m.name AS module_name, r.method, r.path_template, r.timeout_ms,
    r.max_payload_bytes, r.pagination, r.error_mapping, r.audit_level, r.requires_user_context,
    r.tenant_field, r.safe_query FROM tool_definitions t
    JOIN connectors c ON c.id = t.connector_id JOIN applications a ON a.id = c.app_id
    JOIN module_definitions m ON m.app_id = a.id AND m.module_key = t.module_key
    JOIN rest_tool_mappings r ON r.id = t.mapping_id WHERE t.id = ?`, [toolId]);
  const last = await db.one("SELECT * FROM tool_test_runs WHERE tool_id = ? ORDER BY created_at DESC LIMIT 1", [toolId]);
  return { ...row, source_managed: false, display_title: row.title || row.tool_key,
    input_schema: json(row.input_schema), output_schema: json(row.output_schema),
    output_policy: json(row.output_policy), allow_fields: json(row.output_policy).allow_fields,
    report: json(row.report_spec), pagination: json(row.pagination), error_mapping: json(row.error_mapping),
    requires_user_context: !!row.requires_user_context, safe_query: !!row.safe_query,
    tested: !!last?.passed, last_test: last ? { passed: !!last.passed, mode: last.mode,
      error_code: last.error_code, created_at: last.created_at, current: last.content_hash === row.content_hash } : null,
    mcp_tool: { name: row.mcp_name, title: row.title || row.tool_key,
      description: row.description, inputSchema: json(row.input_schema) } };
}

async function save(db, connector, built, owner, existing = null) {
  const mappingId = existing?.mapping_id ?? id(), toolId = existing?.id ?? id();
  if (!existing) {
    await db.run(`INSERT INTO rest_tool_mappings (id, connector_id, method, path_template,
      timeout_ms, max_payload_bytes, query_params, pagination, error_mapping, safe_query,
      requires_user_context, tenant_field, audit_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [mappingId, connector.id, built.mapping.method, built.mapping.path_template,
      built.mapping.timeout_ms, built.mapping.max_payload_bytes, "[]", asJson(built.mapping.pagination),
      asJson(built.mapping.error_mapping), built.mapping.safe_query, built.mapping.requires_user_context,
      built.mapping.tenant_field, built.mapping.audit_level]);
    await db.run(`INSERT INTO tool_definitions (id, tool_key, mcp_name, version, connector_id, mapping_id,
      module_key, template, title, description, input_schema, output_schema, output_policy,
      report_spec, risk, status, content_hash, policy_version, owner_id, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [toolId, built.tool_key, mcpName(built.tool_key, connector.environment), "1.0.0",
      connector.id, mappingId, built.module_key, built.template, built.title, built.description,
      asJson(built.input_schema), asJson(built.output_schema), asJson(built.output_policy),
      built.report_spec && asJson(built.report_spec), built.risk, "draft", "", built.policy_version,
      owner, iso(), iso()]);
  } else {
    await db.run(`UPDATE rest_tool_mappings SET method = ?, path_template = ?, timeout_ms = ?,
      max_payload_bytes = ?, pagination = ?, error_mapping = ?, safe_query = ?,
      requires_user_context = ?, tenant_field = ?, audit_level = ? WHERE id = ?`,
    [built.mapping.method, built.mapping.path_template, built.mapping.timeout_ms,
      built.mapping.max_payload_bytes, asJson(built.mapping.pagination), asJson(built.mapping.error_mapping),
      built.mapping.safe_query, built.mapping.requires_user_context, built.mapping.tenant_field,
      built.mapping.audit_level, mappingId]);
    await db.run(`UPDATE tool_definitions SET title = ?, description = ?, input_schema = ?,
      output_schema = ?, output_policy = ?, report_spec = ?, risk = ?, updated_at = ? WHERE id = ?`,
    [built.title, built.description, asJson(built.input_schema), asJson(built.output_schema),
      asJson(built.output_policy), built.report_spec && asJson(built.report_spec),
      built.risk, iso(), toolId]);
  }
  const updated = await db.one("SELECT * FROM tool_definitions WHERE id = ?", [toolId]);
  const mapping = await db.one("SELECT * FROM rest_tool_mappings WHERE id = ?", [mappingId]);
  const module = await db.one("SELECT * FROM module_definitions WHERE app_id = ? AND module_key = ?",
    [connector.app_id, built.module_key]);
  const hash = fingerprint(updated, mapping, module);
  if (existing && hash !== existing.content_hash && ["published", "disabled"].includes(existing.status)) {
    const [major, minor, patch] = existing.version.split(".").map(Number);
    const version = `${major}.${minor}.${patch + 1}`;
    await db.run("UPDATE tool_definitions SET version = ?, status = 'draft' WHERE id = ?", [version, toolId]);
    updated.version = version;
  }
  await db.run("UPDATE tool_definitions SET content_hash = ? WHERE id = ?",
    [fingerprint(updated, mapping, module), toolId]);
  return view(db, toolId);
}

function sampleValue(name, spec, index) {
  if (spec.enum?.length) return spec.enum[index % spec.enum.length];
  const type = Array.isArray(spec.type) ? spec.type.find((x) => x !== "null") : spec.type;
  if (type === "boolean") return index % 2 === 0;
  if (type === "integer") return Math.min(spec.maximum ?? 1e9, Math.max(spec.minimum ?? 0, (index + 1) * 3));
  if (type === "number") return Math.min(spec.maximum ?? 1e9, Math.max(spec.minimum ?? 0, (index + 1) * 12.5));
  return `Sample ${name.replaceAll("_", " ")} ${index + 1}`.slice(0, spec.maxLength ?? 200);
}

async function sampleTest(db, scopedRow, payload) {
  const { tool, mapping, module } = scopedRow;
  const schema = json(tool.input_schema), output = json(tool.output_schema);
  const manifest = json(module.manifest_json);
  const route = [...(manifest.read_endpoints ?? []), ...(manifest.write_endpoints ?? [])]
    .find((item) => item.method === mapping.method && item.path_template === mapping.path_template);
  if (!route) throw failure("Reviewed source route has changed", "SCHEMA_MISMATCH");
  const args = payload.arguments ?? (payload.fill_required ? Object.fromEntries(
    (schema.required ?? []).map((name) => [name, sampleValue(name, schema.properties[name], 0)])) : {});
  if (!object(args) || !ajv.compile(schema)(args)) throw bad("Test arguments do not match the tool input schema");
  const count = Math.min(route.output_schema.maxItems ?? 3, tool.template === "report" ? 12 :
    write.has(tool.template) ? 1 : 3);
  const rows = payload.sample?.data ?? Array.from({ length: count }, (_, index) => Object.fromEntries(
    Object.entries(route.output_schema.items.properties).map(([name, spec]) =>
      [name, sampleValue(name, spec, index)])));
  if (!Array.isArray(rows) || rows.some((row) => !object(row))) throw bad("Sample data must contain records");
  const allow = json(tool.output_policy).allow_fields;
  const projected = rows.map((row) => Object.fromEntries(allow.map((name) => [name, row[name]])));
  if (tool.template !== "report" && !ajv.compile(output)(projected)) throw failure("Sample output does not match the tool schema", "SCHEMA_MISMATCH");
  if (treeContainsPii(projected)) throw failure("Sample output contains personal data", "PII_DETECTED");
  return { preview: { success: true, data: projected, meta: { scope: "sample_records", coverage: "complete" } },
    checks: { unknown_input_rejected: schema.additionalProperties === false,
      invalid_output_rejected: tool.template === "report" || !ajv.compile(output)("invalid"),
      pii_rejected: true } };
}

export async function handleAdminTools({ db, config, request, path, body }) {
  const method = request.method;
  const builtinMatch = /^\/tools\/builtins\/(list_data_sources|run_report)\/test$/.exec(path);
  if (builtinMatch && method === "POST") {
    const context = await adminContext(db, config, request, true);
    const connector = await bundle(db, context, body.connector_id);
    const caller = { identity: { id: "preview", app_id: connector.app_id,
      scopes: ["mcp:tools"], allowed_tools: null },
    application: { id: connector.app_id, key: connector.app_key, name: connector.app_name,
      environment: connector.environment, status: connector.app_status }, connector,
    scopes: ["mcp:tools"], allowedTools: null, actorRef: `admin:${context.user.id}` };
    const started = Date.now(), trace = `tr_${randomUUID()}`, mode = body.mode ?? "sample";
    let preview = null, error = null;
    try {
      const catalog = await catalogForCaller(db, config, caller);
      if (builtinMatch[1] === "list_data_sources") {
        preview = { success: true, data: catalog.sources,
          meta: { scope: "enabled_sources", coverage: "complete", contains_personal_data: false },
          trace_id: trace };
      } else {
        if (mode !== "sample") throw failure("Live report test requires signed source delegation", "NOT_SUPPORTED");
        const args = body.arguments ?? {};
        if (!ajv.compile(REPORT_INPUT)(args)) throw bad("Report arguments are invalid");
        const key = args.source.startsWith(`${connector.app_key}.`) ?
          args.source.slice(connector.app_key.length + 1) : args.source;
        const record = catalog.sourceModules.get(key);
        if (!record?.route) throw bad("This data source has no report route");
        const spec = parseSpec(Object.fromEntries(Object.entries(args).filter(([name]) => name !== "source")));
        const fields = sourceFields(record.route.output_schema, record.policies);
        validateSpec(spec, fields);
        const count = Math.min(12, record.route.output_schema.maxItems ?? 12);
        const rows = body.sample?.data ?? Array.from({ length: count }, (_, index) =>
          Object.fromEntries(Object.entries(record.route.output_schema.items.properties)
            .map(([name, field]) => [name, sampleValue(name, field, index)])));
        if (!Array.isArray(rows) || rows.some((row) => !object(row))) throw bad("Sample records are invalid");
        const prepared = prepareRows(rows, fields);
        const result = runReport(prepared.rows, spec, fields, "UTC");
        preview = { success: true, data: Object.fromEntries(["mode", "columns", "rows", "totals", "groups"]
          .map((name) => [name, result[name]])),
        summary: summarize(result, { label: `${connector.app_name} · ${record.module.name}`,
          scanned: rows.length, coverage: "complete", truncated: false, filtered: !!spec.filters.length }),
        chart: chartHint(result), notes: result.notes,
        meta: { scope: "sample_records", coverage: "complete", source: key,
          records_read: rows.length, pages: 1, truncated: false }, trace_id: trace };
      }
    } catch (cause) { error = cause instanceof HubError ? cause : failure("Test failed", "SCHEMA_MISMATCH"); }
    await audit(db, context, "tool.test", connector, { tool_key: builtinMatch[1],
      result: error ? "error" : "success", error_code: error?.code ?? null });
    return { passed: !error, mode, trace_id: trace, duration_ms: Date.now() - started,
      error_code: error?.code ?? null, error_message: error?.message ?? null, preview };
  }
  if (path === "/tools/generate" && method === "POST") {
    const context = await adminContext(db, config, request, true);
    const connector = await bundle(db, context, body.connector_id);
    if (connector.connector_type === "source_managed") return undefined;
    if (connector.status === "archived") throw conflict("Archived apps cannot get new tools");
    const publish = body.publish !== false;
    const created = [], repaired = [], skipped = [];
    let unchanged = 0;
    const modules = await db.all("SELECT * FROM module_definitions WHERE app_id = ? ORDER BY module_key",
      [connector.app_id]);
    if (!modules.length) skipped.push({ tool_key: connector.app_key,
      reason: "No data sources yet: test the connection and sync the contract first" });
    for (const module of modules) {
      const setting = await db.one("SELECT * FROM module_settings WHERE module_id = ?", [module.id]);
      if (!setting?.enabled) {
        skipped.push({ tool_key: `${connector.app_key}.${module.module_key}`,
          reason: `${module.name} is not allowed yet` });
        continue;
      }
      const operations = json(setting.operations_enabled, []);
      const manifest = json(module.manifest_json);
      const routes = [...(manifest.read_endpoints ?? []), ...(manifest.write_endpoints ?? [])];
      const dataset = (manifest.read_endpoints ?? []).find((route) => route.output_schema.maxItems > 1 &&
        (route.input_schema.required ?? []).every((name) => ["limit", "cursor"].includes(name)));
      const plans = routes.map((route) => ({ template: route.kind === "write" ? route.operation : "read", route }));
      if (dataset) plans.push({ template: "report", route: dataset });
      for (const { template, route } of plans) {
        const prior = await db.one(`SELECT t.*, r.method, r.path_template FROM tool_definitions t
          JOIN rest_tool_mappings r ON r.id = t.mapping_id WHERE t.connector_id = ?
          AND t.template = ? AND r.method = ? AND r.path_template = ?
          AND t.status != 'archived' ORDER BY CASE WHEN t.status = 'published' THEN 0 ELSE 1 END LIMIT 1`,
        [connector.id, template, route.method, route.path_template]);
        if (prior?.status === "published" && prior.content_hash === fingerprint(prior,
          await db.one("SELECT * FROM rest_tool_mappings WHERE id = ?", [prior.mapping_id]), module)) {
          unchanged++; continue;
        }
        if (prior?.status === "disabled") {
          skipped.push({ tool_key: prior.tool_key, reason: "Disabled by an admin; enable it on its page" });
          continue;
        }
        const segments = route.path_template.split("/").filter(Boolean);
        const last = segments.at(-1) ?? "list";
        const action = template === "report" ? "summary" : write.has(template) ? template :
          last.startsWith("{") ? "get" : last === module.module_key ? "list" :
            last.toLowerCase().replace(/[^a-z0-9_]/g, "_") || "list";
        const baseKey = `${connector.app_key}.${module.module_key}.${action}`;
        let key = prior?.tool_key ?? baseKey, suffix = 2;
        while (!prior && await db.one("SELECT id FROM tool_definitions WHERE connector_id = ? AND tool_key = ?",
          [connector.id, key])) key = `${baseKey}_${suffix++}`;
        const data = { template, tool_key: key, method: route.method,
          path_template: route.path_template, description: route.description,
          ...(template === "report" ? { report: { metrics: [{ fn: "count" }] } } : {}) };
        try {
          const built = await build(db, connector, module, data);
          const saved = await save(db, connector, built, context.user.id, prior);
          let note = write.has(template) ? "Draft: review the request, test it and publish it yourself" :
            !publish ? "Draft: test and publish when ready" :
              !operations.includes("read") ? "Draft: allow reading this data source to publish it" : null;
          if (!note) {
            const updated = await scoped(db, context, saved.id);
            try {
              const sample = await sampleTest(db, updated, { fill_required: true });
              const checks = sample.checks;
              const hash = fingerprint(updated.tool, updated.mapping, module);
              await db.run(`INSERT INTO tool_test_runs (id, tool_id, mode, passed, content_hash,
                case_results, trace_id, duration_ms, error_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
              [id(), saved.id, "sample", true, hash, asJson(checks), `tr_${randomUUID()}`, 1, null, iso()]);
              if (connector.status === "active") {
                await validateDestination(new URL("/", connector.base_url), config);
                await db.run(`UPDATE tool_definitions SET status = 'published', approved_by = ?,
                  policy_version = ?, updated_at = ? WHERE id = ?`,
                [context.user.id, setting.policy_version, iso(), saved.id]);
              } else note = "Tested. Activate the app to publish it";
            } catch (error) { note = `Draft: the sample test did not pass (${error?.message ?? "invalid sample"})`; }
          }
          const viewRow = await view(db, saved.id);
          const item = { id: saved.id, tool_key: saved.tool_key, mcp_name: saved.mcp_name,
            template, title: saved.title || saved.tool_key, module_name: module.name,
            status: viewRow.status, note };
          (prior ? repaired : created).push(item);
        } catch (error) {
          skipped.push({ tool_key: key, reason: error?.message ?? "Could not generate tool" });
        }
      }
    }
    await audit(db, context, "tool.generate", connector);
    return { status: 201, data: { mode: "generated", created, repaired, skipped, unchanged,
      published: [...created, ...repaired].filter((item) => item.status === "published").length } };
  }
  if (path === "/tools" && method === "POST") {
    const context = await adminContext(db, config, request, true);
    const connector = await bundle(db, context, body.connector_id);
    manual(connector);
    if (connector.status === "archived") throw conflict("Archived apps cannot get new tools");
    const module = await db.one("SELECT * FROM module_definitions WHERE app_id = ? AND module_key = ?",
      [connector.app_id, body.module_key]);
    if (!module) throw bad("Data source is not in the discovered contract");
    const built = await build(db, connector, module, body);
    if (await db.one("SELECT id FROM tool_definitions WHERE connector_id = ? AND tool_key = ?",
      [connector.id, built.tool_key])) throw conflict("A tool with this name already exists");
    const result = await save(db, connector, built, context.user.id);
    await audit(db, context, "tool.create", connector, { module_key: built.module_key, tool_key: built.tool_key });
    return { status: 201, data: result };
  }
  const match = /^\/tools\/([^/]+)(?:\/(test|publish|disable))?$/.exec(path);
  if (!match || !(method === "PATCH" || method === "DELETE" || method === "POST")) return undefined;
  const context = await adminContext(db, config, request, true);
  const item = await scoped(db, context, match[1]);
  manual(item.connector);
  const { tool, connector, mapping, module } = item;
  if (method === "PATCH" && !match[2]) {
    if (tool.status === "archived") throw conflict("Archived tools cannot be changed");
    if (!object(body) || Object.keys(body).some((key) => !editable.has(key))) throw bad();
    const current = { template: tool.template, tool_key: tool.tool_key, title: tool.title,
      description: tool.description, method: mapping.method, path_template: mapping.path_template,
      input_schema: json(tool.input_schema), output_schema: json(tool.output_schema),
      allow_fields: json(tool.output_policy).allow_fields, report: json(tool.report_spec),
      timeout_ms: mapping.timeout_ms, max_payload_bytes: mapping.max_payload_bytes,
      pagination: json(mapping.pagination), error_mapping: json(mapping.error_mapping),
      audit_level: mapping.audit_level };
    const merged = { ...current, ...body };
    if (body.method || body.path_template) for (const key of ["input_schema", "output_schema", "allow_fields", "pagination"])
      if (!(key in body)) delete merged[key];
    if (body.allow_fields && !body.output_schema) delete merged.output_schema;
    const built = await build(db, connector, module, merged);
    const result = await save(db, connector, built, context.user.id, tool);
    await audit(db, context, "tool.update", connector, { module_key: tool.module_key, tool_key: tool.tool_key });
    return result;
  }
  if (method === "DELETE" && !match[2]) {
    if (tool.status === "published") throw conflict("Disable the tool before deleting it");
    await db.run("DELETE FROM tool_definitions WHERE id = ?", [tool.id]);
    await db.run("DELETE FROM rest_tool_mappings WHERE id = ?", [tool.mapping_id]);
    await audit(db, context, "tool.delete", connector, { module_key: tool.module_key, tool_key: tool.tool_key });
    return { deleted: true };
  }
  if (method !== "POST") return undefined;
  if (match[2] === "test") {
    const mode = body.mode === "synthetic" ? "sample" : body.mode ?? "sample";
    if (mode !== "sample") throw failure("Live test requires a signed source delegation", "NOT_SUPPORTED");
    const started = Date.now(), trace = `tr_${randomUUID()}`;
    let passed = false, preview = null, checks = {}, error = null;
    try {
      const result = await sampleTest(db, item, body);
      preview = result.preview; checks = result.checks; passed = Object.values(checks).every(Boolean);
    } catch (e) { error = e instanceof HubError ? e : failure("Test failed", "SCHEMA_MISMATCH"); }
    const hash = fingerprint(tool, mapping, module);
    await db.run(`INSERT INTO tool_test_runs (id, tool_id, mode, passed, content_hash,
      case_results, trace_id, duration_ms, error_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [id(), tool.id, mode, passed, hash, asJson(checks), trace, Date.now() - started, error?.code ?? null, iso()]);
    await audit(db, context, "tool.test", connector, { module_key: tool.module_key, tool_key: tool.tool_key,
      result: passed ? "success" : "error", error_code: error?.code ?? null });
    return { passed, mode, trace_id: trace, duration_ms: Date.now() - started,
      error_code: error?.code ?? null, error_message: error?.message ?? null,
      preview, checks, request: null, cases: checks };
  }
  if (match[2] === "publish") {
    if (tool.status === "archived") throw conflict("Archived tools cannot be published");
    if (connector.status !== "active") throw conflict("Activate the app before publishing its tools");
    await validateDestination(new URL("/", connector.base_url), config);
    const setting = await db.one("SELECT * FROM module_settings WHERE module_id = ?", [module.id]);
    const operation = write.has(tool.template) ? tool.template : "read";
    if (!setting.enabled || !json(setting.operations_enabled, []).includes(operation))
      throw failure(`Allow ${operation} on the ${module.name} data source first`, "MODULE_DISABLED", 403);
    const hash = fingerprint(tool, mapping, module);
    const test = await db.one(`SELECT * FROM tool_test_runs WHERE tool_id = ? AND passed = ?
      AND content_hash = ? ORDER BY created_at DESC LIMIT 1`, [tool.id, true, hash]);
    if (!test || Object.values(json(test.case_results, {})).some((passed) => !passed))
      throw conflict("Run a passing test of the current configuration before publishing");
    await db.run("UPDATE tool_definitions SET status = 'published', content_hash = ?, approved_by = ?, policy_version = ?, updated_at = ? WHERE id = ?",
      [hash, context.user.id, setting.policy_version, iso(), tool.id]);
    await audit(db, context, "tool.publish", connector, { module_key: tool.module_key, tool_key: tool.tool_key });
    return view(db, tool.id);
  }
  if (match[2] === "disable") {
    if (tool.status !== "published") throw conflict("Only a published tool can be disabled");
    await db.run("UPDATE tool_definitions SET status = 'disabled', updated_at = ? WHERE id = ?", [iso(), tool.id]);
    await audit(db, context, "tool.disable", connector, { module_key: tool.module_key, tool_key: tool.tool_key });
    return view(db, tool.id);
  }
  return undefined;
}
