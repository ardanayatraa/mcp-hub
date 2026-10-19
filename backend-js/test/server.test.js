import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import argon2 from "argon2";
import { loadConfig } from "../server/config.js";
import { HubDatabase, SCHEMA_REVISION } from "../server/database.js";
import { createHubServer } from "../server/main.js";
import { decryptSecret, encryptSecret, now, totp } from "../server/security.js";

test("Node Fernet reads Python ciphertext and writes decryptable ciphertext", () => {
  const key = "-QX2HiL_OQ92CbkEnTXa2JfMq6_auWXWqsDUhcIOLbA=";
  const python = "gAAAAABqztm4Ep8K0UNjkN4cpNLjfv6-_omtVKZfDt784B01lsYfRKv1oRKClXLklBtupLLdFczBCKcZtQiHGyOgdrWIfOxJfXnqj60u0BCiAxsR7jZyEes=";
  assert.equal(decryptSecret(key, python), "cross-language-test");
  assert.equal(decryptSecret(key, encryptSecret(key, "roundtrip")), "roundtrip");
});

test("Node auth uses the existing Hub tables, cookie, CSRF and Argon2 hash format", async () => {
  const db = new HubDatabase("sqlite+pysqlite:///:memory:");
  db.sqlite.exec(`
    CREATE TABLE alembic_version (version_num TEXT NOT NULL);
    CREATE TABLE admin_users (id TEXT PRIMARY KEY, email TEXT, password_hash TEXT,
      role TEXT, mfa_enabled INTEGER, is_active INTEGER, totp_secret_encrypted TEXT, last_totp_counter INTEGER);
    CREATE TABLE admin_sessions (id TEXT PRIMARY KEY, user_id TEXT, token_hash TEXT,
      csrf_token TEXT, expires_at TEXT, created_at TEXT);
    CREATE TABLE mfa_challenges (id TEXT PRIMARY KEY, user_id TEXT, purpose TEXT, expires_at TEXT, used_at TEXT);
    CREATE TABLE audit_events (id TEXT PRIMARY KEY, trace_id TEXT, action TEXT, actor_ref TEXT,
      result TEXT, error_code TEXT, retry_count INTEGER, created_at TEXT);
  `);
  await db.run("INSERT INTO alembic_version (version_num) VALUES (?)", [SCHEMA_REVISION]);
  await db.assertCurrent();
  await db.run(`INSERT INTO admin_users (id, email, password_hash, role, mfa_enabled, is_active)
    VALUES (?, ?, ?, ?, ?, ?)`, [randomUUID(), "admin@example.com", await argon2.hash("StrongPass123"),
    "super_admin", false, true]);
  const config = { ...loadConfig(), allowedHosts: [] };
  const server = createHubServer({ db, config });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.deepEqual(await (await fetch(`${url}/health`)).json(), { status: "ok" });
    assert.deepEqual(await (await fetch(`${url}/ready`)).json(), { status: "ready" });
    const refused = await fetch(`${url}/api/admin/v1/auth/me`);
    assert.equal(refused.status, 401);
    const login = await fetch(`${url}/api/admin/v1/auth/login`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "admin@example.com", password: "StrongPass123" }) });
    assert.equal(login.status, 200);
    const cookie = login.headers.get("set-cookie").split(";")[0];
    const { data } = await login.json();
    assert.equal(data.user.role, "super_admin");
    const me = await fetch(`${url}/api/admin/v1/auth/me`, { headers: { Cookie: cookie } });
    assert.equal((await me.json()).data.csrf_token, data.csrf_token);
    const noCsrf = await fetch(`${url}/api/admin/v1/auth/logout`, { method: "POST", headers: { Cookie: cookie } });
    assert.equal(noCsrf.status, 403);
    const logout = await fetch(`${url}/api/admin/v1/auth/logout`, { method: "POST",
      headers: { Cookie: cookie, "X-CSRF-Token": data.csrf_token } });
    assert.equal(logout.status, 200);
    assert.equal((await fetch(`${url}/api/admin/v1/auth/me`, { headers: { Cookie: cookie } })).status, 401);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await db.close();
  }
});

test("TOTP uses the same 30-second SHA1 format as Python", () => {
  assert.equal(totp("JBSWY3DPEHPK3PXP", Math.floor(now() / 30)).length, 6);
  assert.match(totp("JBSWY3DPEHPK3PXP", 1), /^\d{6}$/);
});
