import { randomUUID } from "node:crypto";
import { HubError } from "./errors.js";
import { requireAdmin } from "./auth.js";
import { iso, token } from "./security.js";

export const json = (value, fallback = null) => value == null ? fallback
  : typeof value === "string" ? JSON.parse(value) : value;
export const bool = (value) => value === true || value === 1;
export const timestamp = (value) => value == null ? null
  : value instanceof Date ? value.toISOString()
    : /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value.replace(" ", "T")
      : `${value.replace(" ", "T")}Z`;
export const bad = (message = "Request is invalid") =>
  new HubError(message, "VALIDATION_FAILED", 422);
export const missing = (message = "Resource was not found") =>
  new HubError(message, "NOT_FOUND", 404);
export const conflict = (message) => new HubError(message, "CONFLICT", 409);
export const id = () => randomUUID();

export function role(user, allowed) {
  if (!allowed.includes(user.role)) {
    throw new HubError("Operation is not permitted", "PERMISSION_DENIED", 403);
  }
}

export async function adminContext(db, config, request, write = false) {
  const { user } = await requireAdmin(db, config, request,
    !["GET", "HEAD", "OPTIONS"].includes(request.method));
  role(user, write ? ["super_admin", "app_admin"] : ["super_admin", "app_admin", "auditor"]);
  const allowed = user.role === "super_admin" ? null : new Set(
    (await db.all("SELECT app_id FROM admin_application_scopes WHERE user_id = ?", [user.id]))
      .map((row) => row.app_id));
  return { user, allowed };
}

export function appAccess(context, appId) {
  if (context.allowed !== null && !context.allowed.has(appId)) {
    throw new HubError("Application is outside this administrator scope", "PERMISSION_DENIED", 403);
  }
}

export async function bundle(db, context, connectorId) {
  const row = await db.one(`SELECT c.*, a.key AS app_key, a.name AS app_name,
    a.environment, a.status AS app_status, a.created_at AS app_created_at
    FROM connectors c JOIN applications a ON a.id = c.app_id WHERE c.id = ?`, [connectorId]);
  if (!row) throw missing("Connector was not found");
  appAccess(context, row.app_id);
  return row;
}

export async function audit(db, context, action, app = null, extra = {}) {
  await db.run(`INSERT INTO audit_events (id, trace_id, action, actor_ref, app_key, module_key,
    tool_key, environment, result, error_code, duration_ms, retry_count, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  [id(), `tr_${token(12)}`, action, `admin:${context.user.id}`,
    app?.app_key ?? app?.key ?? null, extra.module_key ?? null, extra.tool_key ?? null,
    app?.environment ?? null, extra.result ?? "success", extra.error_code ?? null,
    extra.duration_ms ?? null, 0, iso()]);
}

export function pick(body, keys) {
  if (!body || typeof body !== "object" || Array.isArray(body) ||
      Object.keys(body).some((key) => !keys.includes(key))) throw bad();
  return body;
}

export function textField(value, name, min = 1, max = 200) {
  if (typeof value !== "string" || value.trim().length < min || value.trim().length > max) {
    throw bad(`${name} must be ${min} to ${max} characters`);
  }
  return value.trim();
}
