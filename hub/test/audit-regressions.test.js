import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { seedAdmin } from "../server/core/bootstrap.js";
import { loadConfig } from "../server/core/config.js";
import { HubDatabase } from "../server/core/database.js";
import { createHubServer } from "../server/core/handler.js";
import { migrateDatabase } from "../server/core/migrate.js";
import { hit } from "../server/core/security.js";

async function hub(t) {
  const dir = mkdtempSync(join(tmpdir(), "hub-audit-"));
  const url = `sqlite+pysqlite:///${join(dir, "hub.db").replaceAll("\\", "/")}`;
  await migrateDatabase(url);
  const db = new HubDatabase(url);
  await seedAdmin(db, { ADMIN_INITIAL_EMAIL: "admin@example.com", ADMIN_INITIAL_PASSWORD: "StrongPass123" });
  const server = createHubServer({ db, config: { ...loadConfig(), allowedHosts: [] } });
  let detached = 0;
  // Nitro's graceful shutdown reads req.socket when a response finishes.
  server.on("request", (request, response) => response.on("finish", () => { if (!request.socket) detached++; }));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    await db.close();
    rmSync(dir, { recursive: true, force: true });
  });
  return { base: `http://127.0.0.1:${server.address().port}`, detached: () => detached };
}

test("missing body fields on SQLite are refused like on PostgreSQL, not a server error", async (t) => {
  const { base } = await hub(t);
  const login = await fetch(`${base}/api/admin/v1/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: "admin@example.com", password: "StrongPass123" }) });
  const headers = { "Content-Type": "application/json", Cookie: login.headers.get("set-cookie").split(";")[0],
    "X-CSRF-Token": (await login.json()).data.csrf_token };
  for (const path of ["/service-identities", "/skills", "/skills/preview", "/tools", "/tools/generate",
    "/tools/builtins/list_data_sources/test"]) {
    const response = await fetch(`${base}/api/admin/v1${path}`, { method: "POST", headers, body: "{}" });
    assert.notEqual(response.status, 500, path);
    assert.equal((await response.json()).success, false, path);
  }
});

test("an oversized body gets 413 without detaching the request socket", async (t) => {
  const { base, detached } = await hub(t);
  const body = JSON.stringify({ name: "x".repeat(2 * 1024 * 1024) });
  for (const path of ["/api/admin/v1/auth/login", "/chat/v1/turn"]) {
    const status = await fetch(`${base}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body })
      .then((response) => response.status, () => "reset");
    assert.ok([413, "reset"].includes(status), `${path}: ${status}`);
  }
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(detached(), 0);
  assert.equal((await fetch(`${base}/health`)).status, 200);
});

test("rate limit buckets expire and their number is capped", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: 1_000_000 });
  let added = 0;
  for (;; added++) {
    try { hit(`audit-cap:${added}`, 5, 1); } catch (error) { assert.equal(error.code, "RATE_LIMITED"); break; }
  }
  assert.ok(added > 9_900 && added <= 10_000, `${added} buckets before the cap`);
  assert.throws(() => hit("audit-cap:new", 5, 1), { code: "RATE_LIMITED" });
  t.mock.timers.tick(2_000);
  assert.doesNotThrow(() => hit("audit-cap:after-expiry", 5, 1));
  for (let index = 0; index < 5; index++) hit("audit-cap:busy", 5, 60);
  assert.throws(() => hit("audit-cap:busy", 5, 60), { message: "Too many requests" });
});
