import { createCipheriv, createDecipheriv, createHmac, createHash, randomBytes, timingSafeEqual } from "node:crypto";
import argon2 from "argon2";
import { HubSdkError } from "../src/errors.js";

export const sha256 = (value) => createHash("sha256").update(value).digest("hex");
export const token = (bytes = 32) => randomBytes(bytes).toString("base64url");
export const now = () => Math.floor(Date.now() / 1000);
export const iso = () => new Date().toISOString();
export const truthy = (value) => value === true || value === 1 || value === "1";

function fernetKey(key) {
  const decoded = Buffer.from(key, "base64url");
  if (decoded.length !== 32 || decoded.toString("base64url") !== key.replace(/=+$/, "")) {
    throw new HubSdkError("SECRET_ENCRYPTION_KEY is not a valid Fernet key", "UNSAFE_CONFIGURATION", 500);
  }
  return decoded;
}

export function encryptSecret(key, value) {
  const material = fernetKey(key);
  const timestamp = Buffer.alloc(8);
  timestamp.writeBigUInt64BE(BigInt(now()));
  const iv = randomBytes(16);
  const cipher = createCipheriv("aes-128-cbc", material.subarray(16), iv);
  const body = Buffer.concat([Buffer.from([0x80]), timestamp, iv,
    cipher.update(Buffer.from(value, "utf8")), cipher.final()]);
  const digest = createHmac("sha256", material.subarray(0, 16)).update(body).digest();
  return Buffer.concat([body, digest]).toString("base64url") + "=".repeat((4 - (Buffer.concat([body, digest]).toString("base64url").length % 4)) % 4);
}

export function decryptSecret(key, value) {
  const material = fernetKey(key);
  try {
    const raw = Buffer.from(value, "base64url");
    if (raw.length < 73 || raw[0] !== 0x80) throw new Error();
    const signed = raw.subarray(0, -32);
    const digest = raw.subarray(-32);
    const expected = createHmac("sha256", material.subarray(0, 16)).update(signed).digest();
    if (!timingSafeEqual(digest, expected)) throw new Error();
    const decipher = createDecipheriv("aes-128-cbc", material.subarray(16), raw.subarray(9, 25));
    return Buffer.concat([decipher.update(raw.subarray(25, -32)), decipher.final()]).toString("utf8");
  } catch {
    throw new HubSdkError("Stored credential could not be decrypted", "SECRET_UNAVAILABLE", 500);
  }
}

export async function verifyPassword(hash, password) {
  try { return await argon2.verify(hash, password); } catch { return false; }
}

export function passwordIsAcceptable(value) {
  return typeof value === "string" && value.length >= 12 && value.length <= 200 &&
    /[a-z]/.test(value) && /[A-Z]/.test(value) && /\d/.test(value);
}

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
export function base32(bytes) {
  let bits = 0; let value = 0; let output = "";
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) { output += BASE32[(value >>> (bits -= 5)) & 31]; }
  }
  if (bits) output += BASE32[(value << (5 - bits)) & 31];
  return output;
}

function fromBase32(input) {
  let bits = 0; let value = 0; const bytes = [];
  for (const letter of input.replace(/=+$/, "").toUpperCase()) {
    const digit = BASE32.indexOf(letter);
    if (digit < 0) throw new Error("invalid base32");
    value = (value << 5) | digit;
    bits += 5;
    if (bits >= 8) { bytes.push((value >>> (bits -= 8)) & 255); }
  }
  return Buffer.from(bytes);
}

export function totp(secret, counter) {
  const challenge = Buffer.alloc(8);
  challenge.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac("sha1", fromBase32(secret)).update(challenge).digest();
  const offset = hmac[19] & 15;
  return ((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

export function verifyTotp(secret, code, lastCounter) {
  const current = Math.floor(now() / 30);
  for (const counter of [current, current - 1, current + 1]) {
    if ((lastCounter === null || lastCounter === undefined || counter > lastCounter) &&
      typeof code === "string" && code.trim() === totp(secret, counter)) return counter;
  }
  return null;
}

export function signMfa(config, challengeId) {
  const raw = Buffer.from(JSON.stringify({ challengeId, exp: now() + 300 }));
  return `${raw.toString("base64url")}.${createHmac("sha256", config.sessionSigningKey).update(raw).digest("base64url")}`;
}

export function readMfa(config, value) {
  try {
    const [encoded, signature] = value.split(".");
    const raw = Buffer.from(encoded, "base64url");
    const actual = Buffer.from(signature, "base64url");
    const expected = createHmac("sha256", config.sessionSigningKey).update(raw).digest();
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) throw new Error();
    const data = JSON.parse(raw.toString("utf8"));
    if (!data.challengeId || !Number.isInteger(data.exp) || data.exp <= now()) throw new Error();
    return data.challengeId;
  } catch { throw new HubSdkError("MFA challenge expired", "UNAUTHENTICATED", 401); }
}

const rateBuckets = new Map();
export function hit(key, limit, seconds) {
  const time = Date.now();
  const remaining = (rateBuckets.get(key) ?? []).filter((when) => time - when < seconds * 1000);
  if (remaining.length >= limit) throw new HubSdkError("Too many requests", "RATE_LIMITED", 429);
  remaining.push(time);
  rateBuckets.set(key, remaining);
}
