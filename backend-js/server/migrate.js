import { copyFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { Pool } from "pg";
import { HubDatabase, SCHEMA_REVISION, sqlitePath } from "./database.js";
import { loadConfig } from "./config.js";
import { loadLocalEnv } from "./env.js";

const revisions = new Set(["3b9903ce10ea", "7c4210ab2201", "902b2fc08310",
  "5c2e8d1f4a7b", "a41d7e6c9b20", "c7f2a9d4e810", "e5b1c3d7f902", SCHEMA_REVISION]);
const schema = JSON.parse(readFileSync(fileURLToPath(
  new URL("./schema.sqlite.json", import.meta.url)), "utf8"));
const tables = schema.filter((row) => row.type === "table" && row.name !== "alembic_version");
const indexes = schema.filter((row) => row.type === "index");
const quote = (name) => `"${name.replaceAll('"', '""')}"`;

function currentRevision(db) {
  try { return db.prepare("SELECT version_num FROM alembic_version").get()?.version_num; }
  catch { return null; }
}

function verifyRevision(value) {
  if (!revisions.has(value)) throw new Error(`Unsupported Hub schema revision: ${value ?? "missing"}`);
}

function migrateSqlite(url) {
  const file = sqlitePath(url);
  if (file === ":memory:") throw new Error("Migration requires a persistent database");
  const original = new DatabaseSync(file, { timeout: 15000 });
  const revision = currentRevision(original);
  verifyRevision(revision);
  if (revision === SCHEMA_REVISION) { original.close(); return { revision, alreadyCurrent: true }; }
  original.exec("PRAGMA wal_checkpoint(TRUNCATE)");
  original.close();
  const backup = `${file}.pre-node-${new Date().toISOString().replaceAll(/[:.]/g, "-")}.bak`;
  copyFileSync(file, backup);
  const db = new DatabaseSync(file, { timeout: 15000 });
  db.exec("PRAGMA foreign_keys=OFF");
  db.exec("PRAGMA legacy_alter_table=ON");
  try {
    db.exec("BEGIN IMMEDIATE");
    for (const table of tables) {
      const old = db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?")
        .get(table.name);
      if (!old) { db.exec(table.sql); continue; }
      const temp = `__node_migrate_${table.name}`;
      const tempSql = table.sql.replace(/^CREATE TABLE\s+(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)/i,
        `CREATE TABLE ${quote(temp)}`);
      if (tempSql === table.sql) throw new Error(`Cannot migrate table ${table.name}`);
      db.exec(tempSql);
      const before = new Set(db.prepare(`PRAGMA table_info(${quote(table.name)})`).all()
        .map((row) => row.name));
      const target = db.prepare(`PRAGMA table_info(${quote(temp)})`).all()
        .map((row) => row.name).filter((name) => before.has(name));
      const columns = target.map(quote).join(", ");
      db.exec(`INSERT INTO ${quote(temp)} (${columns}) SELECT ${columns} FROM ${quote(table.name)}`);
      db.exec(`DROP TABLE ${quote(table.name)}`);
      db.exec(`ALTER TABLE ${quote(temp)} RENAME TO ${quote(table.name)}`);
    }
    for (const index of indexes) db.exec(index.sql.replace(/^CREATE (UNIQUE )?INDEX\s+/i,
      (_, unique) => `CREATE ${unique ?? ""}INDEX IF NOT EXISTS `));
    db.exec("UPDATE tool_definitions SET status='draft' WHERE status IN ('validated','approved')");
    db.exec("UPDATE connectors SET auth_type='bearer' WHERE auth_type <> 'bearer'");
    db.prepare("UPDATE alembic_version SET version_num=?").run(SCHEMA_REVISION);
    const problem = db.prepare("PRAGMA foreign_key_check").get();
    const integrity = db.prepare("PRAGMA integrity_check").get();
    if (problem || Object.values(integrity ?? {})[0] !== "ok") {
      throw new Error("Migrated database failed integrity checks");
    }
    db.exec("COMMIT");
    return { revision: SCHEMA_REVISION, from: revision, backup };
  } catch (error) {
    try { db.exec("ROLLBACK"); } catch {}
    throw error;
  } finally {
    db.exec("PRAGMA foreign_keys=ON");
    db.close();
  }
}

async function migratePostgres(url) {
  const pool = new Pool({ connectionString: url.replace(/^postgresql\+psycopg:/, "postgresql:"), max: 1 });
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const version = await client.query("SELECT version_num FROM alembic_version");
    const revision = version.rows[0]?.version_num;
    verifyRevision(revision);
    if (revision === SCHEMA_REVISION) {
      await client.query("COMMIT");
      return { revision, alreadyCurrent: true };
    }
    const existing = new Set((await client.query(`SELECT table_name FROM information_schema.tables
      WHERE table_schema = current_schema()`)).rows.map((row) => row.table_name));
    for (const table of tables) {
      if (existing.has(table.name)) continue;
      const sql = table.sql.replace(/^CREATE TABLE\s+/i, "CREATE TABLE IF NOT EXISTS ")
        .replace(/\bDATETIME\b/g, "TIMESTAMPTZ");
      await client.query(sql);
    }
    const additions = [
      ["admin_users", "last_totp_counter INTEGER"],
      ["tool_test_runs", "content_hash VARCHAR(64) NOT NULL DEFAULT ''"],
      ["tool_test_runs", "case_results JSON NOT NULL DEFAULT '{}'"],
      ["audit_events", "retry_count INTEGER NOT NULL DEFAULT 0"],
      ["rest_tool_mappings", "error_mapping JSON NOT NULL DEFAULT '{}'"],
      ["tool_definitions", "template VARCHAR(16) NOT NULL DEFAULT 'read'"],
      ["tool_definitions", "title VARCHAR(120)"],
      ["tool_definitions", "report_spec JSON"],
      ["tool_definitions", "updated_at TIMESTAMPTZ"],
      ["module_settings", "report_endpoint VARCHAR(320)"],
      ["service_identities", "allowed_tools JSON"],
      ["service_identities", "last_used_at TIMESTAMPTZ"],
    ];
    for (const [table, column] of additions) {
      await client.query(`ALTER TABLE ${quote(table)} ADD COLUMN IF NOT EXISTS ${column}`);
    }
    await client.query("ALTER TABLE chat_settings ALTER COLUMN model TYPE VARCHAR(120)");
    await client.query("ALTER TABLE tool_definitions DROP CONSTRAINT IF EXISTS uq_tool_key_version");
    await client.query("ALTER TABLE tool_definitions DROP CONSTRAINT IF EXISTS uq_tool_mcp_name");
    const newConstraint = await client.query(`SELECT 1 FROM pg_constraint
      WHERE conname = 'uq_tool_connector_key_version'`);
    if (!newConstraint.rowCount) await client.query(`ALTER TABLE tool_definitions
      ADD CONSTRAINT uq_tool_connector_key_version UNIQUE (connector_id, tool_key, version)`);
    for (const index of indexes) {
      const sql = index.sql.replace(/^CREATE (UNIQUE )?INDEX\s+/i,
        (_, unique) => `CREATE ${unique ?? ""}INDEX IF NOT EXISTS `);
      await client.query(sql);
    }
    await client.query("UPDATE tool_definitions SET status='draft' WHERE status IN ('validated','approved')");
    await client.query("UPDATE connectors SET auth_type='bearer' WHERE auth_type <> 'bearer'");
    await client.query("UPDATE alembic_version SET version_num=$1", [SCHEMA_REVISION]);
    await client.query("COMMIT");
    return { revision: SCHEMA_REVISION, from: revision,
      note: "Create a PostgreSQL backup before migration; this command does not create one." };
  } catch (error) {
    await client.query("ROLLBACK").catch(() => {});
    throw error;
  } finally { client.release(); await pool.end(); }
}

export async function migrateDatabase(url) {
  return url.startsWith("postgres") ? migratePostgres(url) : migrateSqlite(url);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  loadLocalEnv();
  const config = loadConfig();
  const result = await migrateDatabase(config.databaseUrl);
  const db = new HubDatabase(config.databaseUrl);
  await db.assertCurrent();
  await db.close();
  console.log(JSON.stringify(result));
}
