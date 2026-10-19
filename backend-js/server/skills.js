import { HubSdkError } from "../src/errors.js";
import { adminContext, appAccess, audit, bad, bool, bundle, conflict, id, json,
  missing, pick, timestamp } from "./admin-common.js";
import { treeContainsPii } from "./privacy.js";
import { iso } from "./security.js";

const keyPattern = /^[a-z][a-z0-9_]{1,63}$/;
const argumentPattern = /^[a-z][a-z0-9_]{0,31}$/;
const placeholders = /\{\{\s*([a-z][a-z0-9_]{0,31})\s*\}\}/g;
const banned = ["ignore previous", "ignore all previous", "disregard previous",
  "disregard all previous", "system prompt", "<|"];

export const SKILL_TEMPLATES = [
  { key: "data_overview", title: "Data overview",
    description: "Explain which data the assistant can answer questions about.",
    instructions: "Call list_data_sources, describe each data source and suggest two questions I could ask.",
    arguments: [], tools: ["list_data_sources"] },
  { key: "periodic_report", title: "Periodic report",
    description: "A short report on one data source for a period.",
    instructions: "Prepare a report on {{source}} for {{period}}. Use run_report and explain the main numbers.",
    arguments: [{ name: "source", description: "Data source key", required: true },
      { name: "period", description: "For example this month", required: false }],
    tools: ["list_data_sources", "run_report"] },
  { key: "needs_attention", title: "Records needing attention",
    description: "Find records that need follow-up and suggest next steps.",
    instructions: "Using run_report on {{source}}, find records that need attention ({{rule}}).",
    arguments: [{ name: "source", description: "Data source key", required: true },
      { name: "rule", description: "What needs attention", required: false }],
    tools: ["run_report"] },
  { key: "explain_number", title: "Explain a number",
    description: "Answer a numeric question and show how it was calculated.",
    instructions: "Answer {{question}}. Use list_data_sources and run_report. Show the filters.",
    arguments: [{ name: "question", description: "Question to answer", required: true }],
    tools: ["list_data_sources", "run_report"] },
  { key: "personal_briefing", title: "Personal briefing",
    description: "A briefing using saved preferences.",
    instructions: "Call recall_memory first, then give a briefing on {{topic}} using run_report.",
    arguments: [{ name: "topic", description: "Briefing topic", required: true }],
    tools: ["recall_memory", "run_report", "save_memory"] },
];

function clean(value, field, min, max, multiline = false) {
  if (typeof value !== "string") throw bad(`${field} is required`);
  const result = multiline ? value.replace(/\r\n/g, "\n").split("\n")
    .map((line) => [...line].filter((ch) => !/[\x00-\x08\x0b-\x1f\x7f]/.test(ch)).join("").trimEnd())
    .join("\n").replace(/\n{3,}/g, "\n\n").trim()
    : value.replace(/[\x00-\x1f\x7f]/g, " ").trim().replace(/\s+/g, " ");
  if (result.length < min || result.length > max) throw bad(`${field} must be ${min} to ${max} characters`);
  if (treeContainsPii(result)) throw new HubSdkError(`${field} contains personal data or a credential`, "PII_DETECTED", 422);
  if (banned.some((word) => result.toLowerCase().includes(word))) throw bad(`${field} contains invalid instructions`);
  return result;
}

async function availableTools(db, appId) {
  const names = new Set(["list_data_sources", "run_report", "save_memory", "recall_memory", "forget_memory"]);
  const rows = await db.all(`SELECT t.mcp_name FROM tool_definitions t JOIN connectors c ON c.id = t.connector_id
    WHERE c.app_id = ? AND t.status != 'archived'`, [appId]);
  for (const row of rows) names.add(row.mcp_name);
  return names;
}

async function validateSkill(db, appId, data) {
  if (!data || typeof data !== "object" || !keyPattern.test(data.key ?? "")) throw bad("Skill key is invalid");
  if (!Array.isArray(data.arguments ?? []) || data.arguments.length > 5) throw bad("A skill can have at most 5 arguments");
  const args = [];
  const seen = new Set();
  for (const item of data.arguments ?? []) {
    if (!item || typeof item !== "object" || !argumentPattern.test(item.name ?? "") || seen.has(item.name)) {
      throw bad("Argument names must be unique lowercase words");
    }
    seen.add(item.name);
    args.push({ name: item.name, description: clean(item.description || item.name, "Argument description", 1, 200),
      required: item.required === true });
  }
  const instructions = clean(data.instructions, "Instructions", 10, 4000, true);
  for (const match of instructions.matchAll(placeholders)) {
    if (!seen.has(match[1])) throw bad(`Placeholder {{${match[1]}}} has no matching argument`);
  }
  const toolNames = data.tools ?? [];
  if (!Array.isArray(toolNames) || toolNames.length > 10 ||
      toolNames.some((name) => typeof name !== "string")) throw bad("A skill can name at most 10 tools");
  const known = await availableTools(db, appId);
  if (toolNames.some((name) => !known.has(name))) throw bad("Skill names a tool outside this app");
  if (typeof (data.enabled ?? true) !== "boolean") throw bad("enabled must be true or false");
  return { key: data.key, title: clean(data.title, "Title", 1, 120),
    description: clean(data.description, "Description", 3, 300),
    instructions, arguments: args, tools: [...new Set(toolNames)], enabled: data.enabled ?? true };
}

export function renderSkill(skill, values = {}) {
  if (!values || typeof values !== "object" || Array.isArray(values)) throw bad("Skill arguments must be an object");
  const declared = new Map(json(skill.arguments, []).map((item) => [item.name, item]));
  for (const name of Object.keys(values)) if (!declared.has(name)) throw bad(`Unknown argument: ${name}`);
  const filled = {};
  for (const [name, item] of declared) {
    const value = values[name];
    if (value == null || (typeof value === "string" && !value.trim())) {
      if (item.required) throw bad(`Argument ${name} is required`);
      filled[name] = "not specified";
    } else filled[name] = clean(String(value), `Argument ${name}`, 1, 300);
  }
  let text = skill.instructions.replace(placeholders, (_, name) => filled[name] ?? `{{${name}}}`);
  const tools = json(skill.tools, []);
  if (tools.length) text += `\n\nTools for this task: ${tools.join(", ")}.`;
  return text;
}

async function view(db, row) {
  const app = await db.one("SELECT * FROM applications WHERE id = ?", [row.app_id]);
  const connector = await db.one("SELECT * FROM connectors WHERE app_id = ?", [row.app_id]);
  const available = await availableTools(db, row.app_id);
  return { id: row.id, key: row.key, title: row.title, description: row.description,
    instructions: row.instructions, arguments: json(row.arguments, []), tools: json(row.tools, []),
    enabled: bool(row.enabled), connector_id: connector?.id ?? null, app_id: row.app_id,
    app_key: app?.key ?? null, app_name: app?.name ?? null,
    environment: app?.environment ?? null,
    unavailable_tools: json(row.tools, []).filter((name) => !available.has(name)),
    created_at: timestamp(row.created_at), updated_at: timestamp(row.updated_at) };
}

export async function visibleSkills(db, caller, toolNames) {
  if (caller.connector?.status !== "active") return [];
  const names = new Set(toolNames);
  const rows = await db.all(`SELECT * FROM skills WHERE app_id = ? AND enabled = ?
    ORDER BY key`, [caller.application.id, true]);
  return rows.filter((row) => json(row.tools, []).every((name) => names.has(name)));
}

export async function handleSkills({ db, config, request, path, url, body }) {
  const method = request.method;
  if (path === "/skills/templates" && method === "GET") {
    await adminContext(db, config, request);
    return SKILL_TEMPLATES;
  }
  if (path === "/skills") {
    const context = await adminContext(db, config, request, method !== "GET");
    if (method === "GET") {
      let appId = null;
      if (url.searchParams.get("connector_id")) {
        appId = (await bundle(db, context, url.searchParams.get("connector_id"))).app_id;
      }
      const rows = await db.all("SELECT * FROM skills ORDER BY app_id, title");
      return Promise.all(rows.filter((row) =>
        (context.allowed === null || context.allowed.has(row.app_id)) &&
        (!appId || row.app_id === appId)).map((row) => view(db, row)));
    }
    if (method === "POST") {
      const connector = await bundle(db, context, body.connector_id);
      if (connector.status === "archived") throw conflict("Archived apps cannot get new skills");
      const data = await validateSkill(db, connector.app_id, body);
      if (await db.one("SELECT id FROM skills WHERE app_id = ? AND key = ?",
        [connector.app_id, data.key])) throw conflict("This app already has a skill with that key");
      const skillId = id();
      await db.run(`INSERT INTO skills (id, app_id, key, title, description, instructions,
        arguments, tools, enabled, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [skillId, connector.app_id, data.key, data.title, data.description,
        data.instructions, JSON.stringify(data.arguments), JSON.stringify(data.tools),
        data.enabled, context.user.id, iso(), iso()]);
      await audit(db, context, "skill.create", connector, { tool_key: data.key });
      return { status: 201, data: await view(db, await db.one("SELECT * FROM skills WHERE id = ?", [skillId])) };
    }
  }
  if (path === "/skills/preview" && method === "POST") {
    const context = await adminContext(db, config, request, true);
    const connector = await bundle(db, context, body.connector_id);
    const data = await validateSkill(db, connector.app_id,
      { ...body.skill, key: body.skill?.key || "preview" });
    return { text: renderSkill(data, body.arguments ?? {}) };
  }
  const match = /^\/skills\/([^/]+)$/.exec(path);
  if (match) {
    const context = await adminContext(db, config, request, true);
    const old = await db.one("SELECT * FROM skills WHERE id = ?", [match[1]]);
    if (!old) throw missing("Skill was not found");
    appAccess(context, old.app_id);
    const app = await db.one("SELECT * FROM applications WHERE id = ?", [old.app_id]);
    if (method === "DELETE") {
      await db.run("DELETE FROM skills WHERE id = ?", [old.id]);
      await audit(db, context, "skill.delete", app, { tool_key: old.key });
      return { deleted: true };
    }
    if (method === "PATCH") {
      pick(body, ["key", "title", "description", "instructions", "arguments", "tools", "enabled"]);
      const data = await validateSkill(db, old.app_id, {
        key: old.key, title: old.title, description: old.description,
        instructions: old.instructions, arguments: json(old.arguments, []),
        tools: json(old.tools, []), enabled: bool(old.enabled), ...body });
      if (data.key !== old.key && await db.one("SELECT id FROM skills WHERE app_id = ? AND key = ?",
        [old.app_id, data.key])) throw conflict("This app already has a skill with that key");
      await db.run(`UPDATE skills SET key = ?, title = ?, description = ?, instructions = ?,
        arguments = ?, tools = ?, enabled = ?, updated_at = ? WHERE id = ?`,
      [data.key, data.title, data.description, data.instructions,
        JSON.stringify(data.arguments), JSON.stringify(data.tools), data.enabled, iso(), old.id]);
      await audit(db, context, "skill.update", app, { tool_key: data.key });
      return view(db, await db.one("SELECT * FROM skills WHERE id = ?", [old.id]));
    }
  }
  return undefined;
}
