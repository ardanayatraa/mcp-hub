import { HubError } from "./errors.js";
import { adminContext, audit, bad, role } from "./admin-common.js";
import { iso } from "./security.js";

const ORDER = ["applications", "memory_settings", "model_providers", "chat_settings",
  "tool_switches", "skills", "admin_application_scopes", "connectors", "connector_secrets",
  "contract_snapshots", "module_definitions", "module_settings", "field_policies",
  "rest_tool_mappings", "tool_definitions", "tool_test_runs", "service_identities"];
const LEGACY = new Set(["mcp_server_profiles", "mcp_profile_tools", "skill_definitions"]);
const DATE = /^(\d{4}-\d\d-\d\d)[T ]\d\d:\d\d:\d\d/;
const quoted = (name) => `"${name.replaceAll('"', '""')}"`;

async function columns(db, table) {
  const rows = db.kind === "sqlite"
    ? await db.all(`PRAGMA table_info(${quoted(table)})`)
    : await db.all(`SELECT column_name AS name, data_type AS type,
      CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
      column_default AS dflt_value FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = ? ORDER BY ordinal_position`, [table]);
  return rows.map((row) => ({ name: row.name, type: String(row.type).toUpperCase(),
    required: !!row.notnull && row.dflt_value == null }));
}

function exported(value, column) {
  if (value == null) return null;
  if (column.type.includes("JSON")) return typeof value === "string" ? JSON.parse(value) : value;
  if (column.type.includes("BOOL")) return !!value;
  if (column.type.includes("DATE") && value instanceof Date) return value.toISOString();
  return value;
}

function imported(value, column) {
  if (value == null) return null;
  if (column.type.includes("JSON")) {
    if (!value || typeof value !== "object") throw bad("Backup JSON field is invalid");
    return JSON.stringify(value);
  }
  if (column.type.includes("BOOL")) {
    if (typeof value !== "boolean") throw bad("Backup Boolean field is invalid");
    return value;
  }
  if (column.type.includes("INT")) {
    if (!Number.isInteger(value)) throw bad("Backup integer field is invalid");
    return value;
  }
  if (column.type.includes("DATE")) {
    if (typeof value !== "string" || !DATE.test(value) || !Number.isFinite(Date.parse(value)))
      throw bad("Backup timestamp is invalid");
    return value;
  }
  if (typeof value !== "string") throw bad("Backup text field is invalid");
  return value;
}

export async function exportMetadata(db) {
  const tables = {};
  for (const table of ORDER) {
    const specs = await columns(db, table);
    const rows = await db.all(`SELECT * FROM ${quoted(table)}`);
    tables[table] = rows.map((row) => Object.fromEntries(specs.map((spec) =>
      [spec.name, exported(row[spec.name], spec)])));
  }
  return { format: "mcp-hub-metadata-v1", tables };
}

export async function importMetadata(db, document) {
  if (document?.format !== "mcp-hub-metadata-v1" || !document.tables ||
      typeof document.tables !== "object" || Array.isArray(document.tables) ||
      Object.keys(document.tables).some((name) => !ORDER.includes(name) && !LEGACY.has(name)))
    throw bad("Backup format or tables are invalid");
  const prepared = {};
  const admins = new Set((await db.all("SELECT id FROM admin_users")).map((row) => row.id));
  for (const table of ORDER) {
    const specs = await columns(db, table);
    const permitted = new Set(specs.map((spec) => spec.name));
    const rows = document.tables[table] ?? [];
    if (!Array.isArray(rows) || rows.length > 10000) throw bad("Backup table exceeds its record limit");
    prepared[table] = rows.map((raw) => {
      if (!raw || typeof raw !== "object" || Array.isArray(raw) ||
          Object.keys(raw).some((name) => !permitted.has(name))) throw bad("Backup record fields are invalid");
      const values = {};
      for (const spec of specs) {
        if (!(spec.name in raw)) {
          if (spec.required) throw bad("Backup required field is missing");
          continue;
        }
        values[spec.name] = imported(raw[spec.name], spec);
        if (values[spec.name] == null && spec.required) throw bad("Backup required field is missing");
      }
      if (table === "tool_definitions" && ["validated", "approved"].includes(values.status))
        values.status = "draft";
      return values;
    }).filter((row) => table !== "admin_application_scopes" || admins.has(row.user_id));
  }
  try {
    return await db.transaction(async (tx) => {
      for (const table of [...ORDER].reverse()) await tx.run(`DELETE FROM ${quoted(table)}`);
      const counts = {};
      for (const table of ORDER) {
        for (const row of prepared[table]) {
          const names = Object.keys(row);
          await tx.run(`INSERT INTO ${quoted(table)} (${names.map(quoted).join(",")})
            VALUES (${names.map(() => "?").join(",")})`, Object.values(row));
        }
        counts[table] = prepared[table].length;
      }
      return counts;
    });
  } catch {
    throw bad("Backup relationships are invalid");
  }
}

export async function purgeExpired(db, retentionDays) {
  const cutoff = new Date(Date.now() - retentionDays * 86400_000).toISOString();
  const removed = {};
  for (const table of ["audit_events", "connector_health_checks", "tool_test_runs", "admin_sessions"])
    removed[table] = await db.run(`DELETE FROM ${quoted(table)} WHERE created_at < ?`, [cutoff]);
  removed.mfa_challenges = await db.run("DELETE FROM mfa_challenges WHERE expires_at < ?", [iso()]);
  removed.expired_sessions = await db.run("DELETE FROM admin_sessions WHERE expires_at < ?", [iso()]);
  removed.expired_memories = await db.run("DELETE FROM user_memories WHERE expires_at < ?", [iso()]);
  return removed;
}

export async function handleBackup({ db, config, request, path, body }) {
  if (!path.startsWith("/operations/") || request.method !== "POST") return undefined;
  const context = await adminContext(db, config, request, true);
  role(context.user, ["super_admin"]);
  if (path === "/operations/export") {
    const document = await exportMetadata(db);
    await audit(db, context, "backup.export");
    return document;
  }
  if (path === "/operations/import") {
    const counts = await importMetadata(db, body);
    await audit(db, context, "backup.import");
    return counts;
  }
  if (path === "/operations/purge") {
    const removed = await purgeExpired(db, config.auditRetentionDays);
    await audit(db, context, "backup.purge");
    return { removed };
  }
  return undefined;
}
