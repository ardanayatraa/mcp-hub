import { HubSdkError } from "../src/errors.js";

const integer = (key, fallback, low, high) => {
  const value = Number(process.env[key] ?? fallback);
  if (!Number.isInteger(value) || value < low || value > high) {
    throw new HubSdkError(`${key} must be between ${low} and ${high}`, "UNSAFE_CONFIGURATION", 500);
  }
  return value;
};
const bool = (key, fallback = false) => {
  const value = (process.env[key] ?? String(fallback)).toLowerCase();
  if (!["true", "false", "1", "0"].includes(value)) {
    throw new HubSdkError(`${key} must be true or false`, "UNSAFE_CONFIGURATION", 500);
  }
  return value === "true" || value === "1";
};
const csv = (key, fallback = "") => (process.env[key] ?? fallback).split(",").map((part) => part.trim()).filter(Boolean);

export function loadConfig() {
  const config = {
    environment: process.env.ENVIRONMENT ?? "dev",
    databaseUrl: process.env.DATABASE_URL ?? "sqlite+pysqlite:///./hub.db",
    host: process.env.HOST ?? "127.0.0.1",
    port: integer("PORT", 8000, 1, 65535),
    secretEncryptionKey: process.env.SECRET_ENCRYPTION_KEY ?? "",
    sessionSigningKey: process.env.SESSION_SIGNING_KEY ?? "",
    cookieName: process.env.COOKIE_NAME ?? "hub_session",
    cookieSecure: bool("COOKIE_SECURE"),
    mfaRequired: bool("MFA_REQUIRED"),
    sessionHours: integer("SESSION_HOURS", 8, 1, 24),
    allowedOrigins: csv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
    allowedHosts: csv("ALLOWED_HOSTS", "localhost,127.0.0.1,localhost:8000,127.0.0.1:8000"),
    mcpPublicUrl: process.env.MCP_PUBLIC_URL ?? "http://127.0.0.1:8000/mcp",
    mcpIssuerUrl: process.env.MCP_ISSUER_URL ?? "http://127.0.0.1:8000",
    allowInsecureHttp: bool("ALLOW_INSECURE_HTTP"),
    allowInsecureTls: bool("ALLOW_INSECURE_TLS"),
    egressAllowPrivate: bool("EGRESS_ALLOW_PRIVATE"),
    egressAllowLoopback: bool("EGRESS_ALLOW_LOOPBACK"),
    egressAllowedHosts: csv("EGRESS_ALLOWED_HOSTS"),
    egressAllowedCidrs: csv("EGRESS_ALLOWED_CIDRS"),
    egressAllowedPorts: csv("EGRESS_ALLOWED_PORTS", "80,443").map(Number),
    maxPayloadBytes: integer("MAX_PAYLOAD_BYTES", 1_048_576, 1024, 1_048_576),
    maxRecords: integer("MAX_RECORDS", 50, 1, 50),
    reportMaxRecords: integer("REPORT_MAX_RECORDS", 1000, 50, 5000),
    reportTimeoutSeconds: integer("REPORT_TIMEOUT_SECONDS", 20, 1, 120),
    toolRateLimit: integer("TOOL_RATE_LIMIT", 60, 1, 10000),
    toolRateWindowSeconds: integer("TOOL_RATE_WINDOW_SECONDS", 60, 1, 3600),
    auditRetentionDays: integer("AUDIT_RETENTION_DAYS", 90, 1, 3650),
    loginRateLimit: integer("LOGIN_RATE_LIMIT", 10, 1, 100),
    mfaRateLimit: integer("MFA_RATE_LIMIT", 10, 1, 100),
    anthropicApiKey: process.env.ANTHROPIC_API_KEY ?? "",
    chatOpenaiBaseUrl: process.env.CHAT_OPENAI_BASE_URL ?? "",
    chatOpenaiApiKey: process.env.CHAT_OPENAI_API_KEY ?? "",
    chatMaxTokens: integer("CHAT_MAX_TOKENS", 16000, 1024, 64000),
    chatTimeoutSeconds: integer("CHAT_TIMEOUT_SECONDS", 120, 10, 600),
    chatRateLimit: integer("CHAT_RATE_LIMIT", 20, 1, 1000),
    modelEgressAllowedHosts: csv("MODEL_EGRESS_ALLOWED_HOSTS"),
    modelEgressAllowedPorts: csv("MODEL_EGRESS_ALLOWED_PORTS", "443,80,11434,1234").map(Number),
  };
  if (!["dev", "test", "staging", "production"].includes(config.environment)) {
    throw new HubSdkError("Invalid ENVIRONMENT", "UNSAFE_CONFIGURATION", 500);
  }
  if (config.environment === "production") {
    const problems = [];
    if (!config.cookieSecure) problems.push("COOKIE_SECURE must be true");
    if (!config.mfaRequired) problems.push("MFA_REQUIRED must be true");
    if (config.allowInsecureHttp || config.allowInsecureTls) problems.push("insecure HTTP/TLS is disabled in production");
    if (config.egressAllowPrivate || config.egressAllowLoopback) problems.push("private and loopback egress are disabled in production");
    if (!config.secretEncryptionKey || !config.sessionSigningKey) problems.push("encryption and session keys are required");
    if (!config.egressAllowedHosts.length && !config.egressAllowedCidrs.length) problems.push("approved egress hosts or CIDRs are required");
    if (!config.databaseUrl.startsWith("postgres")) problems.push("PostgreSQL metadata storage is required");
    if (problems.length) throw new HubSdkError(problems.join("; "), "UNSAFE_CONFIGURATION", 500);
  }
  return config;
}
