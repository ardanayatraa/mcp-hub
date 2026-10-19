import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { seedAdmin } from "../server/core/bootstrap.js";
import { HubDatabase, SCHEMA_REVISION } from "../server/core/database.js";
import { migrateDatabase } from "../server/core/migrate.js";
import { verifyPassword } from "../server/core/security.js";

const sqliteUrl = (dir) => `sqlite+pysqlite:///${join(dir, "hub.db").replaceAll("\\", "/")}`;

test("an empty database is created at the current schema and gets its first admin", async () => {
  const dir = mkdtempSync(join(tmpdir(), "hub-migrate-"));
  const url = sqliteUrl(dir);
  let db;
  try {
    assert.deepEqual(await migrateDatabase(url), { revision: SCHEMA_REVISION, created: true });
    assert.deepEqual(await migrateDatabase(url), { revision: SCHEMA_REVISION, alreadyCurrent: true });
    db = new HubDatabase(url);
    await db.assertCurrent();
    assert.equal((await db.all("SELECT name FROM sqlite_master WHERE type = 'table'")).length, 24);

    const env = { ADMIN_INITIAL_EMAIL: " Admin@Example.com ", ADMIN_INITIAL_PASSWORD: "ChangeMe-Now-12" };
    await assert.rejects(seedAdmin(db, { ...env, ADMIN_INITIAL_PASSWORD: "too-weak" }), { code: "UNSAFE_CONFIGURATION" });
    assert.equal(await seedAdmin(db, env), "admin created");
    assert.equal(await seedAdmin(db, { ADMIN_INITIAL_EMAIL: env.ADMIN_INITIAL_EMAIL }), "admin already exists");
    const admin = await db.one("SELECT * FROM admin_users");
    assert.equal(admin.email, "admin@example.com");
    assert.equal(admin.role, "super_admin");
    assert.equal(await verifyPassword(admin.password_hash, env.ADMIN_INITIAL_PASSWORD), true);
  } finally {
    await db?.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a database with tables but no Hub revision is left untouched", async () => {
  const dir = mkdtempSync(join(tmpdir(), "hub-migrate-"));
  try {
    const other = new DatabaseSync(join(dir, "hub.db"));
    other.exec("CREATE TABLE someone_elses (id INTEGER)");
    other.close();
    await assert.rejects(migrateDatabase(sqliteUrl(dir)), /Unsupported Hub schema revision/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
