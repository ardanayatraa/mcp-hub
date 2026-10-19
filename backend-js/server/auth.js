import { randomUUID, randomBytes } from "node:crypto";
import argon2 from "argon2";
import { HubSdkError } from "../src/errors.js";
import { base32, decryptSecret, encryptSecret, hit, iso, now, readMfa, sha256,
  signMfa, token, truthy, verifyPassword, verifyTotp } from "./security.js";

const dummyHash = argon2.hash("dummy-password-not-used");
const userView = (user) => ({ id: user.id, email: user.email, role: user.role, mfa_enabled: truthy(user.mfa_enabled) });

function parseDate(value) {
  if (value instanceof Date) return value.getTime();
  if (typeof value !== "string") return 0;
  const normalized = value.replace(" ", "T");
  return Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(normalized) ? normalized : `${normalized}Z`);
}

function cookies(request) {
  const result = {};
  for (const part of (request.headers.cookie ?? "").split(";")) {
    const at = part.indexOf("=");
    if (at > 0) result[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  }
  return result;
}

function cookie(config, raw, expires = false) {
  const attributes = [`${config.cookieName}=${raw}`, "HttpOnly", "SameSite=Strict", "Path=/",
    config.cookieSecure ? "Secure" : "", expires ? "Max-Age=0" : `Max-Age=${config.sessionHours * 3600}`];
  return attributes.filter(Boolean).join("; ");
}

async function audit(db, action, actorRef, result, errorCode = null) {
  await db.run(`INSERT INTO audit_events
    (id, trace_id, action, actor_ref, result, error_code, retry_count, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 0, ?)`,
  [randomUUID(), `tr_${token(12)}`, action, actorRef, result, errorCode, iso()]);
}

async function makeSession(db, config, user) {
  const raw = token(32);
  const csrf = token(24);
  await db.run(`INSERT INTO admin_sessions
    (id, user_id, token_hash, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)`,
  [randomUUID(), user.id, sha256(raw), csrf, new Date(Date.now() + config.sessionHours * 3600_000).toISOString(), iso()]);
  return { raw, csrf };
}

export async function requireAdmin(db, config, request, csrf = false) {
  const raw = cookies(request)[config.cookieName];
  if (!raw) throw new HubSdkError("Authentication is required", "UNAUTHENTICATED", 401);
  const session = await db.one("SELECT * FROM admin_sessions WHERE token_hash = ?", [sha256(raw)]);
  if (!session || parseDate(session.expires_at) <= Date.now()) {
    throw new HubSdkError("Authentication is required", "UNAUTHENTICATED", 401);
  }
  const user = await db.one("SELECT * FROM admin_users WHERE id = ?", [session.user_id]);
  if (!user || !truthy(user.is_active)) throw new HubSdkError("Authentication is required", "UNAUTHENTICATED", 401);
  if (csrf && request.headers["x-csrf-token"] !== session.csrf_token) {
    throw new HubSdkError("CSRF token is missing or invalid", "PERMISSION_DENIED", 403);
  }
  return { user, session };
}

export async function handleAuth({ db, config, request, response, path, body, send }) {
  const method = request.method;
  if (method === "POST" && path === "/auth/login") {
    hit(`login:${request.socket.remoteAddress ?? "unknown"}`, config.loginRateLimit, 60);
    const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
    if (!email.includes("@") || email.length > 320 || typeof body?.password !== "string") {
      throw new HubSdkError("Request is invalid", "VALIDATION_FAILED", 422);
    }
    const user = await db.one("SELECT * FROM admin_users WHERE email = ?", [email]);
    const valid = await verifyPassword(user?.password_hash ?? await dummyHash, body.password);
    if (!user || !truthy(user.is_active) || !valid) {
      await audit(db, "auth.login", "anonymous", "denied", "UNAUTHENTICATED");
      throw new HubSdkError("Invalid credentials", "UNAUTHENTICATED", 401);
    }
    if (truthy(user.mfa_enabled)) {
      const challengeId = randomUUID();
      await db.run("INSERT INTO mfa_challenges (id, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
        [challengeId, user.id, "mfa", new Date(Date.now() + 300_000).toISOString()]);
      await audit(db, "auth.mfa_challenge", `admin:${user.id}`, "success");
      return send(response, 200, { mfa_required: true, mfa_token: signMfa(config, challengeId) });
    }
    if (config.mfaRequired) {
      const secret = base32(randomBytes(20));
      await db.run("UPDATE admin_users SET totp_secret_encrypted = ?, mfa_enabled = ? WHERE id = ?",
        [encryptSecret(config.secretEncryptionKey, secret), false, user.id]);
      const challengeId = randomUUID();
      await db.run("INSERT INTO mfa_challenges (id, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
        [challengeId, user.id, "enroll", new Date(Date.now() + 300_000).toISOString()]);
      const uri = `otpauth://totp/MCP%20Hub:${encodeURIComponent(user.email)}?secret=${secret}&issuer=MCP%20Hub`;
      return send(response, 200, { enrollment_required: true, mfa_token: signMfa(config, challengeId), otpauth_uri: uri });
    }
    const session = await makeSession(db, config, user);
    await audit(db, "auth.login", `admin:${user.id}`, "success");
    response.setHeader("Set-Cookie", cookie(config, session.raw));
    return send(response, 200, { user: userView(user), csrf_token: session.csrf });
  }
  if (method === "POST" && path === "/auth/mfa") {
    hit(`mfa:${request.socket.remoteAddress ?? "unknown"}`, config.mfaRateLimit, 60);
    const challengeId = readMfa(config, body?.mfa_token);
    hit(`mfa-challenge:${challengeId}`, config.mfaRateLimit, 300);
    const challenge = await db.one("SELECT * FROM mfa_challenges WHERE id = ?", [challengeId]);
    if (!challenge || challenge.used_at || parseDate(challenge.expires_at) <= Date.now()) {
      throw new HubSdkError("MFA challenge expired", "UNAUTHENTICATED", 401);
    }
    const user = await db.one("SELECT * FROM admin_users WHERE id = ?", [challenge.user_id]);
    const secret = user?.totp_secret_encrypted
      ? decryptSecret(config.secretEncryptionKey, user.totp_secret_encrypted) : "";
    const counter = user && truthy(user.is_active) && !(challenge.purpose === "enroll" && truthy(user.mfa_enabled))
      ? verifyTotp(secret, body?.code, user.last_totp_counter) : null;
    if (counter === null) {
      await audit(db, "auth.mfa", "anonymous", "denied", "UNAUTHENTICATED");
      throw new HubSdkError("Invalid credentials", "UNAUTHENTICATED", 401);
    }
    const result = await db.transaction(async (tx) => {
      const consumed = await tx.run("UPDATE mfa_challenges SET used_at = ? WHERE id = ? AND used_at IS NULL",
        [iso(), challengeId]);
      const updated = await tx.run(`UPDATE admin_users SET last_totp_counter = ?, mfa_enabled = ?
        WHERE id = ? AND is_active = ? AND (last_totp_counter IS NULL OR last_totp_counter < ?)`,
      [counter, true, user.id, true, counter]);
      if (consumed !== 1 || updated !== 1) throw new HubSdkError("MFA challenge was already used", "UNAUTHENTICATED", 401);
      const session = await makeSession(tx, config, user);
      await audit(tx, "auth.login", `admin:${user.id}`, "success");
      return session;
    });
    response.setHeader("Set-Cookie", cookie(config, result.raw));
    return send(response, 200, { user: { ...userView(user), mfa_enabled: true }, csrf_token: result.csrf });
  }
  if (method === "GET" && path === "/auth/me") {
    const { user, session } = await requireAdmin(db, config, request);
    return send(response, 200, { ...userView(user), csrf_token: session.csrf_token });
  }
  if (method === "POST" && path === "/auth/logout") {
    const { user, session } = await requireAdmin(db, config, request, true);
    await db.run("DELETE FROM admin_sessions WHERE id = ?", [session.id]);
    await audit(db, "auth.logout", `admin:${user.id}`, "success");
    response.setHeader("Set-Cookie", cookie(config, "", true));
    return send(response, 200, { signed_out: true });
  }
  return false;
}
