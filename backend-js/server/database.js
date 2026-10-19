import { DatabaseSync } from "node:sqlite";
import { resolve } from "node:path";
import { Pool } from "pg";
import { HubSdkError } from "../src/errors.js";

export const SCHEMA_REVISION = "f3a8d2c6b1e4";

export function sqlitePath(url) {
  if (url === "sqlite+pysqlite:///:memory:" || url === "sqlite:///:memory:") return ":memory:";
  const match = /^sqlite(?:\+pysqlite)?:\/\/\/(.+)$/.exec(url);
  if (!match) throw new HubSdkError("Unsupported DATABASE_URL", "UNSAFE_CONFIGURATION", 500);
  return resolve(decodeURIComponent(match[1]));
}

function pgSql(sql) {
  let index = 0;
  return sql.replace(/\?/g, () => `$${++index}`);
}

export class HubDatabase {
  constructor(url) {
    this.url = url;
    if (url.startsWith("postgres")) {
      this.kind = "postgres";
      this.pool = new Pool({ connectionString: url.replace(/^postgresql\+psycopg:/, "postgresql:"), max: 10 });
    } else {
      this.kind = "sqlite";
      this.sqlite = new DatabaseSync(sqlitePath(url), { timeout: 15000 });
      this.sqlite.exec("PRAGMA foreign_keys = ON");
      this.sqlitePending = Promise.resolve();
    }
  }

  sqliteAll(sql, params = []) {
    return this.sqlite.prepare(sql).all(...params.map((value) =>
      typeof value === "boolean" ? Number(value) : value));
  }

  sqliteOne(sql, params = []) {
    return this.sqlite.prepare(sql).get(...params.map((value) =>
      typeof value === "boolean" ? Number(value) : value)) ?? null;
  }

  sqliteRun(sql, params = []) {
    return this.sqlite.prepare(sql).run(...params.map((value) =>
      typeof value === "boolean" ? Number(value) : value)).changes;
  }

  async all(sql, params = [], connection) {
    if (this.kind === "sqlite") { await this.sqlitePending; return this.sqliteAll(sql, params); }
    return (await (connection ?? this.pool).query(pgSql(sql), params)).rows;
  }

  async one(sql, params = [], connection) {
    if (this.kind === "sqlite") { await this.sqlitePending; return this.sqliteOne(sql, params); }
    return (await (connection ?? this.pool).query(pgSql(sql), params)).rows[0] ?? null;
  }

  async run(sql, params = [], connection) {
    if (this.kind === "sqlite") { await this.sqlitePending; return this.sqliteRun(sql, params); }
    return (await (connection ?? this.pool).query(pgSql(sql), params)).rowCount;
  }

  async transaction(fn) {
    if (this.kind === "sqlite") {
      const previous = this.sqlitePending;
      let release;
      this.sqlitePending = new Promise((resolve) => { release = resolve; });
      await previous;
      const tx = { all: async (sql, params) => this.sqliteAll(sql, params),
        one: async (sql, params) => this.sqliteOne(sql, params),
        run: async (sql, params) => this.sqliteRun(sql, params) };
      let began = false;
      try {
        this.sqlite.exec("BEGIN IMMEDIATE"); began = true;
        const value = await fn(tx);
        this.sqlite.exec("COMMIT"); return value;
      }
      catch (error) { if (began) this.sqlite.exec("ROLLBACK"); throw error; }
      finally { release(); }
    }
    const connection = await this.pool.connect();
    try {
      await connection.query("BEGIN");
      const tx = { all: (sql, params) => this.all(sql, params, connection),
        one: (sql, params) => this.one(sql, params, connection),
        run: (sql, params) => this.run(sql, params, connection) };
      const value = await fn(tx);
      await connection.query("COMMIT");
      return value;
    } catch (error) { await connection.query("ROLLBACK"); throw error; }
    finally { connection.release(); }
  }

  async assertCurrent() {
    const exists = this.kind === "sqlite"
      ? await this.one("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'")
      : await this.one("SELECT to_regclass('public.alembic_version') AS name");
    if (!exists || (this.kind === "postgres" && !exists.name)) {
      throw new HubSdkError("Hub database has no schema. Migrate the existing database before starting Node backend.",
        "SCHEMA_MISMATCH", 500);
    }
    const row = await this.one("SELECT version_num FROM alembic_version");
    if (row?.version_num !== SCHEMA_REVISION) {
      throw new HubSdkError(`Hub schema revision ${row?.version_num ?? "missing"}; expected ${SCHEMA_REVISION}`,
        "SCHEMA_MISMATCH", 500);
    }
  }

  async ready() {
    await this.one("SELECT 1 AS ok");
    return true;
  }

  async close() {
    if (this.kind === "sqlite") this.sqlite.close();
    else await this.pool.end();
  }
}
