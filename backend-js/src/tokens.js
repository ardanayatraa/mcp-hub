import { createHmac, timingSafeEqual } from "node:crypto";
import { HubSdkError } from "./errors.js";

const denied = () => new HubSdkError("Hub user context is invalid", "PERMISSION_DENIED", 403);
const encoded = (value) => Buffer.from(value).toString("base64url");

function required(value, label) {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError(`${label} must be a nonempty string`);
  }
  return value;
}

export function signDelegation({ appKey, tenantId, userRef, secret, ttlSeconds = 90 }) {
  required(appKey, "appKey");
  required(tenantId, "tenantId");
  required(userRef, "userRef");
  required(secret, "secret");
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 1 || ttlSeconds > 120) {
    throw new RangeError("ttlSeconds must be between 1 and 120");
  }
  const raw = Buffer.from(JSON.stringify({
    app_key: appKey,
    tenant_id: tenantId,
    user_ref: userRef,
    aud: "mcp-hub",
    exp: Math.floor(Date.now() / 1000) + ttlSeconds,
  }));
  return `${encoded(raw)}.${createHmac("sha256", secret).update(raw).digest("base64url")}`;
}

function decodePart(part) {
  if (!/^[A-Za-z0-9_-]+$/.test(part)) throw denied();
  const decoded = Buffer.from(part, "base64url");
  if (decoded.toString("base64url") !== part) throw denied();
  return decoded;
}

export async function verifyAssertion({ token, appKey, audience, secret, consumeJti }) {
  required(appKey, "appKey");
  required(audience, "audience");
  required(secret, "secret");
  if (typeof consumeJti !== "function") throw new TypeError("consumeJti is required");
  if (typeof token !== "string" || token.length > 4096 || token.split(".").length !== 2) throw denied();
  let payload;
  try {
    const [body, signature] = token.split(".");
    const raw = decodePart(body);
    const actual = decodePart(signature);
    const expected = createHmac("sha256", secret).update(raw).digest();
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) throw denied();
    payload = JSON.parse(raw.toString("utf8"));
  } catch {
    throw denied();
  }
  const now = Math.floor(Date.now() / 1000);
  if (!payload || typeof payload !== "object" || Array.isArray(payload) ||
      payload.app_key !== appKey || payload.aud !== audience ||
      !Number.isInteger(payload.exp) || payload.exp <= now || payload.exp > now + 150 ||
      typeof payload.tenant_id !== "string" || !payload.tenant_id ||
      typeof payload.user_ref !== "string" || !payload.user_ref ||
      typeof payload.jti !== "string" || !/^[A-Za-z0-9_-]{16,64}$/.test(payload.jti)) throw denied();
  // consumeJti must be an atomic, shared one-time insert in a multi-worker deployment.
  if (await consumeJti(payload.jti, payload.exp) !== true) throw denied();
  return { tenantId: payload.tenant_id, userRef: payload.user_ref };
}

export class MemoryReplayStore {
  #seen = new Map();

  async consume(jti, exp) {
    const now = Math.floor(Date.now() / 1000);
    for (const [key, until] of this.#seen) if (until <= now) this.#seen.delete(key);
    if (this.#seen.has(jti)) return false;
    this.#seen.set(jti, exp);
    return true;
  }
}

export class HubSourceAuth {
  constructor({ appKey, audience, bearerToken, delegationSecret, consumeJti, authorize }) {
    this.appKey = required(appKey, "appKey");
    this.audience = required(audience, "audience");
    this.bearerToken = required(bearerToken, "bearerToken");
    this.delegationSecret = required(delegationSecret, "delegationSecret");
    if (typeof consumeJti !== "function") throw new TypeError("consumeJti is required");
    if (typeof authorize !== "function") throw new TypeError("authorize is required");
    this.consumeJti = consumeJti;
    this.authorize = authorize;
  }

  verifyBearer(headers) {
    const value = new Headers(headers).get("authorization") ?? "";
    const actual = Buffer.from(value);
    const expected = Buffer.from(`Bearer ${this.bearerToken}`);
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      throw new HubSdkError("Authentication is required", "UNAUTHENTICATED", 401);
    }
  }

  async authenticate(headers, permission) {
    this.verifyBearer(headers);
    required(permission, "permission");
    const { tenantId, userRef } = await verifyAssertion({
      token: new Headers(headers).get("x-hub-assertion"),
      appKey: this.appKey,
      audience: this.audience,
      secret: this.delegationSecret,
      consumeJti: this.consumeJti,
    });
    const result = await this.authorize({ tenantId, userRef, permission });
    if (!result || result.active !== true || result.allowed !== true || result.tenantId !== tenantId) {
      throw denied();
    }
    return { tenantId, userRef, actor: result.actor };
  }
}
