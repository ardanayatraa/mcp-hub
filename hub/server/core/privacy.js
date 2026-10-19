import { HubError } from "./errors.js";

const sensitive = new Set([
  "email", "e_mail", "phone", "phone_number", "mobile", "password", "passwd", "token",
  "secret", "api_key", "authorization", "national_id", "nik", "ssn", "full_name",
  "first_name", "last_name", "address", "dob", "date_of_birth", "user_id", "tenant_id",
  "otp", "one_time_password", "pin", "cvv", "cvc", "verification_code", "auth_code",
  "security_code", "msisdn", "card_number", "credit_card", "iban", "account_number",
  "passport", "npwp", "ktp",
]);
const forbidden = new Set(["user_id", "tenant_id", "role", "approved", "password", "token",
  "secret", "authorization", "base_url", "method", "path", "url"]);
const detectors = [
  /(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])/i,
  /(?<![\w.+-])[\w.+-]+@(?:localhost|[a-z][a-z0-9_-]+)(?![\w.-])/i,
  /(?<!\d)(?:\+\d{8,15}|\d{10,15})(?!\d)/,
  /(?<!\d)\d{16}(?!\d)/,
  /\b\d{3}-\d{2}-\d{4}\b/,
  /\b(?:api[_ -]?key|password|passwd|authorization|bearer|secret|token)\s*[:=]\s*\S+|\b(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|AKIA[A-Z0-9]{16}|hub_[a-z0-9_-]{32,}|eyJ[a-z0-9_-]{10,}\.[a-z0-9_-]{20,})/i,
];
const formattedPhone = /(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]){2,4}\d{2,4}(?!\w)/g;

export function isSensitivePath(path) {
  for (const part of String(path).split(".")) {
    const words = part.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase().split(/[_-]+/).filter(Boolean);
    const candidates = new Set([part.toLowerCase(), ...words]);
    for (const size of [2, 3]) {
      for (let at = 0; at + size <= words.length; at++) candidates.add(words.slice(at, at + size).join("_"));
    }
    if ([...candidates].some((candidate) => sensitive.has(candidate))) return true;
  }
  return false;
}

export function containsPii(value) {
  if (detectors.some((pattern) => pattern.test(value))) return true;
  for (const match of value.matchAll(formattedPhone)) {
    if (match[0].replace(/\D/g, "").length >= 10) return true;
  }
  return false;
}

export function treeContainsPii(value) {
  const pending = [[value, 0]];
  let inspected = 0;
  while (pending.length) {
    const [item, depth] = pending.pop();
    if (++inspected > 10000 || depth > 16) return true;
    if (typeof item === "string" && containsPii(item)) return true;
    if (typeof item === "number" && (!Number.isFinite(item) ||
        (Number.isInteger(item) && containsPii(String(item))))) return true;
    if (Array.isArray(item)) for (const child of item) pending.push([child, depth + 1]);
    else if (item && typeof item === "object") {
      for (const [key, child] of Object.entries(item)) {
        pending.push([key, depth + 1], [child, depth + 1]);
      }
    }
  }
  return false;
}

export function rejectForbiddenKeys(value) {
  if (Array.isArray(value)) { value.forEach(rejectForbiddenKeys); return; }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (forbidden.has(key.toLowerCase())) {
        throw new HubError("Argument contains a field the model is not allowed to set", "PRIVILEGE_ESCALATION", 422);
      }
      rejectForbiddenKeys(item);
    }
  }
}

export function projectRecord(record, allowFields, policies) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new HubError("Tool output records must be objects", "VALIDATION_FAILED", 422);
  }
  const projected = {};
  for (const field of allowFields) {
    if (!Object.hasOwn(record, field) || isSensitivePath(field) ||
        !["allowed", "allowed_for_ai"].includes(policies[field])) continue;
    const value = record[field];
    if ((value !== null && typeof value === "object") || treeContainsPii(value)) {
      throw new HubError("Response blocked by privacy policy", "PII_DETECTED", 422);
    }
    if (value !== null && !["string", "number", "boolean"].includes(typeof value)) {
      throw new HubError("Response field has an unsupported type", "SCHEMA_MISMATCH", 422);
    }
    projected[field] = value;
  }
  return projected;
}
