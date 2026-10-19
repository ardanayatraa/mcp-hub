import { hash as hashPassword } from "argon2";
import { HubError } from "./errors.js";
import { sha256, token, iso } from "./security.js";
import { adminContext, appAccess, audit, bad, bool, conflict, id, json, missing,
  pick, role, textField, timestamp } from "./admin-common.js";

const READ = "mcp:tools";
const WRITE = "tools:write";
const keys = ["list_data_sources", "run_report", "save_memory", "recall_memory", "forget_memory"];

async function identityView(db, row) {
  const app = await db.one("SELECT * FROM applications WHERE id = ?", [row.app_id]);
  const expired = row.expires_at && Date.parse(timestamp(row.expires_at)) <= Date.now();
  return { id: row.id, name: row.name, app_id: row.app_id,
    app_key: app?.key ?? null, app_name: app?.name ?? null,
    environment: app?.environment ?? null, scopes: json(row.scopes, []),
    write: json(row.scopes, []).includes(WRITE), allowed_tools: json(row.allowed_tools),
    expires_at: timestamp(row.expires_at), revoked: !!row.revoked_at,
    status: row.revoked_at ? "revoked" : expired ? "expired" : "active",
    last_used_at: timestamp(row.last_used_at), created_at: timestamp(row.created_at) };
}

async function allowedTools(db, appId, requested) {
  if (requested === null) return null;
  if (!Array.isArray(requested) || requested.some((name) => typeof name !== "string")) throw bad();
  const known = new Set(keys);
  for (const row of await db.all(`SELECT t.mcp_name FROM tool_definitions t JOIN connectors c
    ON c.id = t.connector_id WHERE c.app_id = ? AND t.status != 'archived'`, [appId])) known.add(row.mcp_name);
  const unique = [...new Set(requested)].sort();
  if (unique.some((name) => !known.has(name))) throw bad("Allowed tools must be built-in tools or tools of this app");
  return unique;
}

async function scopedIdentity(db, context, identityId) {
  const row = await db.one("SELECT * FROM service_identities WHERE id = ?", [identityId]);
  if (!row) throw missing("Client key was not found");
  appAccess(context, row.app_id);
  return row;
}

async function userView(db, row) {
  return { id: row.id, email: row.email, role: row.role,
    mfa_enabled: bool(row.mfa_enabled), is_active: bool(row.is_active),
    app_ids: (await db.all("SELECT app_id FROM admin_application_scopes WHERE user_id = ?", [row.id]))
      .map((item) => item.app_id), created_at: timestamp(row.created_at) };
}

async function setScopes(db, userId, appIds) {
  if (!Array.isArray(appIds) || appIds.some((value) => typeof value !== "string")) throw bad();
  for (const appId of new Set(appIds)) {
    if (!await db.one("SELECT id FROM applications WHERE id = ?", [appId])) throw bad("Application assignment is invalid");
  }
  await db.run("DELETE FROM admin_application_scopes WHERE user_id = ?", [userId]);
  for (const appId of new Set(appIds)) {
    await db.run("INSERT INTO admin_application_scopes (id, user_id, app_id) VALUES (?, ?, ?)",
      [id(), userId, appId]);
  }
}

export async function handleAccess({ db, config, request, path, url, body }) {
  const method = request.method;
  if (path === "/service-identities") {
    const context = await adminContext(db, config, request, method !== "GET");
    if (method === "GET") {
      const rows = await db.all("SELECT * FROM service_identities ORDER BY created_at DESC");
      const visible = rows.filter((row) => context.allowed === null || context.allowed.has(row.app_id));
      return Promise.all(visible.filter((row) => !url.searchParams.get("app_id") ||
        row.app_id === url.searchParams.get("app_id")).map((row) => identityView(db, row)));
    }
    if (method === "POST") {
      pick(body, ["name", "app_key", "environment", "write", "allowed_tools", "ttl_days"]);
      const name = textField(body.name ?? "gateway", "Name", 1, 120);
      const app = await db.one("SELECT * FROM applications WHERE key = ? AND environment = ?",
        [body.app_key, body.environment ?? "dev"]);
      if (!app) throw missing("Application was not found");
      appAccess(context, app.id);
      if (typeof (body.write ?? false) !== "boolean" || !Number.isInteger(body.ttl_days ?? 90) ||
          (body.ttl_days ?? 90) < 1 || (body.ttl_days ?? 90) > 365) throw bad();
      const allowed = await allowedTools(db, app.id, body.allowed_tools ?? null);
      const raw = `hub_${token(32)}`;
      const keyId = id();
      await db.run(`INSERT INTO service_identities (id, name, token_hash, app_id, scopes,
        allowed_tools, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [keyId, name, sha256(raw), app.id, JSON.stringify([READ, ...(body.write ? [WRITE] : [])]),
        allowed === null ? null : JSON.stringify(allowed),
        new Date(Date.now() + (body.ttl_days ?? 90) * 86_400_000).toISOString(), iso()]);
      await audit(db, context, "key.create", app);
      return { status: 201, data: { ...await identityView(db,
        await db.one("SELECT * FROM service_identities WHERE id = ?", [keyId])), token: raw } };
    }
  }
  const identityMatch = /^\/service-identities\/([^/]+)(?:\/(revoke))?$/.exec(path);
  if (identityMatch) {
    const context = await adminContext(db, config, request, true);
    const row = await scopedIdentity(db, context, identityMatch[1]);
    const app = await db.one("SELECT * FROM applications WHERE id = ?", [row.app_id]);
    if (method === "POST" && identityMatch[2] === "revoke") {
      await db.run("UPDATE service_identities SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        [iso(), row.id]);
      await audit(db, context, "key.revoke", app);
      return { revoked: true };
    }
    if (method === "PATCH" && !identityMatch[2]) {
      if (row.revoked_at) throw conflict("Revoked keys cannot be changed");
      pick(body, ["name", "write", "allowed_tools"]);
      const update = {};
      if ("name" in body) update.name = textField(body.name, "Name", 1, 120);
      if ("write" in body) {
        if (typeof body.write !== "boolean") throw bad();
        update.scopes = JSON.stringify([READ, ...(body.write ? [WRITE] : [])]);
      }
      if ("allowed_tools" in body) {
        const allowed = await allowedTools(db, row.app_id, body.allowed_tools);
        update.allowed_tools = allowed === null ? null : JSON.stringify(allowed);
      }
      for (const [field, value] of Object.entries(update)) {
        await db.run(`UPDATE service_identities SET ${field} = ? WHERE id = ?`, [value, row.id]);
      }
      await audit(db, context, "key.update", app);
      return identityView(db, await db.one("SELECT * FROM service_identities WHERE id = ?", [row.id]));
    }
  }
  if (path === "/users") {
    const context = await adminContext(db, config, request, method !== "GET");
    role(context.user, ["super_admin"]);
    if (method === "GET") return Promise.all(
      (await db.all("SELECT * FROM admin_users ORDER BY created_at")).map((row) => userView(db, row)));
    if (method === "POST") {
      pick(body, ["email", "password", "role", "app_ids"]);
      const email = textField(body.email, "Email", 3, 320).toLowerCase();
      if (!email.includes("@") || typeof body.password !== "string" ||
          body.password.length < 12 || !/[A-Z]/.test(body.password) ||
          !/[a-z]/.test(body.password) || !/\d/.test(body.password) ||
          !["super_admin", "app_admin", "auditor"].includes(body.role)) throw bad();
      if (await db.one("SELECT id FROM admin_users WHERE email = ?", [email])) throw conflict("An admin with that email already exists");
      const userId = id();
      await db.transaction(async (tx) => {
        await tx.run(`INSERT INTO admin_users (id, email, password_hash, role, mfa_enabled,
          is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [userId, email, await hashPassword(body.password), body.role, false, true, iso()]);
        await setScopes(tx, userId, body.app_ids ?? []);
      });
      await audit(db, context, "admin.create");
      return { status: 201, data: await userView(db,
        await db.one("SELECT * FROM admin_users WHERE id = ?", [userId])) };
    }
  }
  const userMatch = /^\/users\/([^/]+)$/.exec(path);
  if (userMatch && method === "PATCH") {
    const context = await adminContext(db, config, request, true);
    role(context.user, ["super_admin"]);
    const target = await db.one("SELECT * FROM admin_users WHERE id = ?", [userMatch[1]]);
    if (!target) throw missing("Administrator was not found");
    pick(body, ["role", "is_active", "app_ids", "password"]);
    if ("role" in body && !["super_admin", "app_admin", "auditor"].includes(body.role)) throw bad();
    if ("is_active" in body && typeof body.is_active !== "boolean") throw bad();
    const demoting = (body.role ?? target.role) !== "super_admin" || body.is_active === false;
    if (target.role === "super_admin" && demoting) {
      if (target.id === context.user.id) throw conflict("You cannot remove your own super admin access");
      const other = await db.one(`SELECT id FROM admin_users WHERE role = 'super_admin'
        AND is_active = ? AND id != ? LIMIT 1`, [true, target.id]);
      if (!other) throw conflict("At least one active super admin is required");
    }
    await db.transaction(async (tx) => {
      if ("role" in body) await tx.run("UPDATE admin_users SET role = ? WHERE id = ?", [body.role, target.id]);
      if ("is_active" in body) await tx.run("UPDATE admin_users SET is_active = ? WHERE id = ?", [body.is_active, target.id]);
      if ("app_ids" in body) await setScopes(tx, target.id, body.app_ids);
      if ("password" in body) {
        if (typeof body.password !== "string" || body.password.length < 12 ||
            !/[A-Z]/.test(body.password) || !/[a-z]/.test(body.password) || !/\d/.test(body.password)) throw bad();
        await tx.run("UPDATE admin_users SET password_hash = ? WHERE id = ?",
          [await hashPassword(body.password), target.id]);
        await tx.run("DELETE FROM admin_sessions WHERE user_id = ?", [target.id]);
      }
    });
    await audit(db, context, "admin.update");
    return userView(db, await db.one("SELECT * FROM admin_users WHERE id = ?", [target.id]));
  }
  return undefined;
}
