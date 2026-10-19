import { HubError } from "./errors.js";
import { adminContext, audit, bad, bool, bundle, conflict, id, json, missing,
  pick, role, textField, timestamp } from "./admin-common.js";
import { treeContainsPii } from "./privacy.js";
import { decryptSecret, encryptSecret, iso } from "./security.js";
import { sourceRequest, validateDestination } from "./source-http.js";

const modelPattern = /^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,119}$/;
const keyPattern = /^[a-z][a-z0-9_-]{1,31}$/;
const headersForbidden = new Set(["host", "content-length", "content-type", "transfer-encoding",
  "connection", "cookie", "authorization", "accept", "accept-encoding", "te", "upgrade",
  "proxy-authorization"]);
const claudeModels = [
  { id: "claude-opus-5-5", label: "Claude Opus 5.5",
    hint: "Most capable. Best for reports and multi-step questions." },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5",
    hint: "Fast and capable. A good everyday choice." },
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5",
    hint: "Fastest and cheapest. Best for short lookups." },
];
export const PROVIDER_PRESETS = [
  { key: "openai", name: "OpenAI", base_url: "https://api.openai.com/v1",
    token_param: "max_completion_tokens", hint: "API key from platform.openai.com." },
  { key: "openrouter", name: "OpenRouter", base_url: "https://openrouter.ai/api/v1",
    headers: { "X-Title": "MCP Hub" }, hint: "One key for many models." },
  { key: "groq", name: "Groq", base_url: "https://api.groq.com/openai/v1", hint: "Fast open models." },
  { key: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", hint: "DeepSeek API key." },
  { key: "mistral", name: "Mistral", base_url: "https://api.mistral.ai/v1", hint: "Mistral API key." },
  { key: "gemini", name: "Google Gemini",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    tool_schema: "basic", hint: "AI Studio key." },
  { key: "together", name: "Together AI", base_url: "https://api.together.xyz/v1", hint: "Open models." },
  { key: "fireworks", name: "Fireworks AI", base_url: "https://api.fireworks.ai/inference/v1",
    hint: "Hosted open models." },
  { key: "xai", name: "xAI", base_url: "https://api.x.ai/v1", hint: "Grok models." },
  { key: "cerebras", name: "Cerebras", base_url: "https://api.cerebras.ai/v1", hint: "Fast inference." },
  { key: "azure", name: "Azure OpenAI",
    base_url: "https://YOUR-RESOURCE.openai.azure.com/openai/v1",
    auth_style: "header", auth_header: "api-key", token_param: "max_completion_tokens",
    hint: "Replace YOUR-RESOURCE and use your deployment name." },
  { key: "ollama", name: "Ollama (local)", base_url: "http://127.0.0.1:11434/v1",
    auth_style: "none", hint: "Local model with tool support." },
  { key: "lmstudio", name: "LM Studio (local)", base_url: "http://127.0.0.1:1234/v1",
    auth_style: "none", hint: "Local model server." },
  { key: "custom", name: "Other OpenAI-compatible", base_url: "",
    hint: "Any endpoint that serves /chat/completions." },
];

export function modelConfig(config) {
  return { ...config, egressAllowedHosts: config.modelEgressAllowedHosts,
    egressAllowedCidrs: [], egressAllowedPorts: config.modelEgressAllowedPorts };
}

export async function providerEndpoint(db, config, key) {
  if (key === "anthropic") {
    if (!config.anthropicApiKey) throw new HubError(
      "The Hub has no Anthropic API key yet. Ask an admin to add it.", "CHAT_NOT_CONFIGURED", 503);
    return { kind: "anthropic", label: "Claude (Anthropic)", baseUrl: "https://api.anthropic.com",
      headers: { "x-api-key": config.anthropicApiKey, "anthropic-version": "2023-06-01" },
      tokenParam: "max_tokens", toolSchema: "full" };
  }
  if (key === "openai_compatible") {
    if (!config.chatOpenaiBaseUrl) throw new HubError(
      "The OpenAI-compatible gateway is not configured on the Hub", "CHAT_NOT_CONFIGURED", 503);
    return { kind: "openai", label: "Gateway (environment)",
      baseUrl: config.chatOpenaiBaseUrl.replace(/\/$/, ""),
      headers: config.chatOpenaiApiKey ? { Authorization: `Bearer ${config.chatOpenaiApiKey}` } : {},
      tokenParam: "max_tokens", toolSchema: "full" };
  }
  const row = await db.one("SELECT * FROM model_providers WHERE key = ?", [key]);
  if (!row || !bool(row.enabled)) throw new HubError(
    "This chat's model provider is missing or turned off. Ask an admin.",
    "CHAT_NOT_CONFIGURED", 503);
  if (row.auth_style !== "none" && !row.api_key_ciphertext) throw new HubError(
    `${row.name} has no API key yet. Ask an admin to add it.`, "CHAT_NOT_CONFIGURED", 503);
  const headers = json(row.headers, {});
  if (row.auth_style !== "none") {
    const secret = decryptSecret(config.secretEncryptionKey, row.api_key_ciphertext);
    headers[row.auth_style === "bearer" ? "Authorization" : row.auth_header] =
      row.auth_style === "bearer" ? `Bearer ${secret}` : secret;
  }
  return { kind: "openai", label: row.name, baseUrl: row.base_url, headers,
    tokenParam: row.token_param, toolSchema: row.tool_schema, streaming: bool(row.streaming) };
}

async function usedBy(db, key) {
  return (await db.all(`SELECT a.name FROM chat_settings c JOIN applications a
    ON a.id = c.app_id WHERE c.provider = ? ORDER BY a.name`, [key])).map((row) => row.name);
}

export async function providerView(db, row) {
  return { id: row.id, key: row.key, name: row.name, base_url: row.base_url,
    auth_style: row.auth_style, auth_header: row.auth_header,
    api_key_set: !!row.api_key_ciphertext, api_key_hint: row.api_key_hint,
    headers: json(row.headers, {}), token_param: row.token_param,
    tool_schema: row.tool_schema, streaming: bool(row.streaming),
    default_model: row.default_model, models: json(row.models, []),
    enabled: bool(row.enabled), status: row.status, status_message: row.status_message,
    checked_at: timestamp(row.checked_at), used_by: await usedBy(db, row.key),
    ready: bool(row.enabled) && (row.auth_style === "none" || !!row.api_key_ciphertext) };
}

export async function chatSetting(db, appId) {
  return await db.one("SELECT * FROM chat_settings WHERE app_id = ?", [appId])
    ?? { app_id: appId, enabled: false, provider: "anthropic", model: "claude-opus-5-5",
      effort: "medium", instructions: "", welcome_message: "", suggestions: [],
      max_steps: 6, daily_limit: 200, updated_at: null };
}

export async function chatAdminView(db, config, appId) {
  const setting = await chatSetting(db, appId);
  const providers = await db.all("SELECT * FROM model_providers ORDER BY name");
  const options = [
    { id: "anthropic", label: "Claude (Anthropic)", kind: "anthropic",
      ready: !!config.anthropicApiKey, models: [], default_model: "claude-opus-5-5" },
    ...(config.chatOpenaiBaseUrl || setting.provider === "openai_compatible"
      ? [{ id: "openai_compatible", label: "Gateway (environment)",
        kind: "openai_compatible", ready: !!config.chatOpenaiBaseUrl,
        models: [], default_model: "" }] : []),
    ...providers.filter((row) => bool(row.enabled) || row.key === setting.provider)
      .map((row) => ({ id: row.key, label: row.name, kind: "openai_compatible",
        ready: bool(row.enabled) && (row.auth_style === "none" || !!row.api_key_ciphertext),
        models: json(row.models, []), default_model: row.default_model })),
  ];
  return { enabled: bool(setting.enabled), provider: setting.provider, model: setting.model,
    effort: setting.effort, instructions: setting.instructions,
    welcome_message: setting.welcome_message, suggestions: json(setting.suggestions, []),
    max_steps: setting.max_steps, daily_limit: setting.daily_limit,
    fallbacks: setting.provider === "anthropic" &&
      ["claude-opus-5-5", "claude-sonnet-5-5"].includes(setting.model),
    updated_at: timestamp(setting.updated_at),
    options: { providers: options, models: claudeModels,
      efforts: ["low", "medium", "high"], max_steps: [1, 12], daily_limit: [0, 5000] } };
}

export async function updateChatSetting(db, config, appId, body) {
  pick(body, ["enabled", "provider", "model", "effort", "instructions",
    "welcome_message", "suggestions", "max_steps", "daily_limit"]);
  if (!Object.keys(body).length) throw bad("Chat settings are invalid");
  const old = await chatSetting(db, appId);
  const next = { ...old, ...body };
  if (typeof next.enabled !== "boolean" && next.enabled !== 0 && next.enabled !== 1) throw bad();
  if (next.provider !== "anthropic" && next.provider !== "openai_compatible" &&
      !await db.one("SELECT id FROM model_providers WHERE key = ?", [next.provider])) {
    throw bad("Choose Claude or a provider added under AI providers");
  }
  if (!modelPattern.test(next.model) ||
      (next.provider === "anthropic" && !/^claude-[a-z0-9][a-z0-9.-]{0,79}$/.test(next.model))) throw bad("Model name is invalid");
  if (!["low", "medium", "high"].includes(next.effort) ||
      !Number.isInteger(next.max_steps) || next.max_steps < 1 || next.max_steps > 12 ||
      !Number.isInteger(next.daily_limit) || next.daily_limit < 0 || next.daily_limit > 5000) throw bad();
  for (const [field, max] of [["instructions", 4000], ["welcome_message", 300]]) {
    if (typeof next[field] !== "string" || next[field].length > max ||
        treeContainsPii(next[field])) throw bad(`${field} is invalid`);
  }
  if (!Array.isArray(next.suggestions) || next.suggestions.length > 6 ||
      next.suggestions.some((text) => typeof text !== "string" || text.length > 120 ||
        treeContainsPii(text))) throw bad("Suggestions are invalid");
  await db.run(`INSERT INTO chat_settings (app_id, enabled, provider, model, effort,
    instructions, welcome_message, suggestions, max_steps, daily_limit, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(app_id) DO UPDATE SET
    enabled = excluded.enabled, provider = excluded.provider, model = excluded.model,
    effort = excluded.effort, instructions = excluded.instructions,
    welcome_message = excluded.welcome_message, suggestions = excluded.suggestions,
    max_steps = excluded.max_steps, daily_limit = excluded.daily_limit,
    updated_at = excluded.updated_at`,
  [appId, !!next.enabled, next.provider, next.model, next.effort, next.instructions,
    next.welcome_message, JSON.stringify(next.suggestions), next.max_steps,
    next.daily_limit, iso()]);
  return chatAdminView(db, config, appId);
}

function validateProviderBody(body, old) {
  pick(body, [...(old ? [] : ["key"]), "name", "base_url", "auth_style", "auth_header", "api_key",
    "clear_api_key", "headers", "token_param", "tool_schema", "streaming",
    "default_model", "enabled"]);
  const data = { ...old, ...(old ? { headers: json(old.headers, {}) } : {}), ...body };
  if (!old) {
    if (!keyPattern.test(data.key ?? "") ||
        ["anthropic", "openai_compatible", "claude", "hub", "none"].includes(data.key)) {
      throw bad("Provider key is invalid");
    }
  }
  data.name = textField(data.name, "Name", 1, 80);
  data.base_url = textField(data.base_url, "Base URL", 1, 500).replace(/\/$/, "")
    .replace(/\/chat\/completions$/, "");
  let url;
  try { url = new URL(data.base_url); } catch { throw bad("Provider URL is invalid"); }
  if (!["http:", "https:"].includes(url.protocol) || url.search || url.hash ||
      url.username || url.password) throw bad("Provider URL is invalid");
  if (!["bearer", "header", "none"].includes(data.auth_style ?? "bearer") ||
      !["max_tokens", "max_completion_tokens", "none"].includes(data.token_param ?? "max_tokens") ||
      !["full", "basic"].includes(data.tool_schema ?? "full")) throw bad("Provider settings are invalid");
  if (data.auth_style === "header" && !/^[A-Za-z0-9-]{1,64}$/.test(data.auth_header ?? "")) throw bad();
  if (data.headers != null && (typeof data.headers !== "object" || Array.isArray(data.headers) ||
      Object.keys(data.headers).length > 10 || Object.entries(data.headers).some(([key, value]) =>
        !/^[A-Za-z0-9-]{1,64}$/.test(key) || headersForbidden.has(key.toLowerCase()) ||
        typeof value !== "string" || value.length > 200 || treeContainsPii(value)))) throw bad("Provider headers are invalid");
  if (data.default_model && !modelPattern.test(data.default_model)) throw bad("Default model is invalid");
  if (typeof (data.streaming ?? true) !== "boolean" || typeof (data.enabled ?? true) !== "boolean") throw bad();
  if (body.api_key && (typeof body.api_key !== "string" || body.api_key.length > 500)) throw bad();
  return data;
}

async function modelList(db, config, key, refresh = false) {
  if (key === "anthropic") return { provider: key, models: claudeModels, source: "builtin",
    fetched_at: null, default_model: "claude-opus-5-5",
    error: config.anthropicApiKey ? null : "The Hub has no ANTHROPIC_API_KEY yet." };
  const row = key === "openai_compatible" ? null
    : await db.one("SELECT * FROM model_providers WHERE key = ?", [key]);
  if (key !== "openai_compatible" && !row) throw missing("Model provider was not found");
  if (!refresh && row?.models && json(row.models, []).length) {
    return { provider: key, models: json(row.models, []).map((model) => ({ id: model, label: model })),
      source: "cache", fetched_at: timestamp(row.checked_at),
      default_model: row.default_model, error: null };
  }
  let models = json(row?.models, []);
  try {
    const endpoint = await providerEndpoint(db, config, key);
    const result = await sourceRequest({ method: "GET",
      url: `${endpoint.baseUrl}/models`, config: modelConfig(config),
      headers: { ...endpoint.headers, Accept: "application/json" },
      timeoutMs: 20_000, retries: 0 });
    if (result.status >= 400) throw new Error(`Provider answered ${result.status}`);
    const parsed = JSON.parse(result.body);
    models = [...new Set((Array.isArray(parsed) ? parsed : parsed.data ?? [])
      .map((item) => item?.id).filter((id) => typeof id === "string" && modelPattern.test(id)))].sort().slice(0, 500);
    if (row) await db.run("UPDATE model_providers SET models = ?, checked_at = ? WHERE id = ?",
      [JSON.stringify(models), iso(), row.id]);
    return { provider: key, models: models.map((model) => ({ id: model, label: model })),
      source: "live", fetched_at: iso(), default_model: row?.default_model ?? "", error: null };
  } catch (error) {
    return { provider: key, models: models.map((model) => ({ id: model, label: model })),
      source: "cache", fetched_at: timestamp(row?.checked_at),
      default_model: row?.default_model ?? "", error: error.message };
  }
}

export async function handleChatSettings({ db, config, request, path, url, body }) {
  const method = request.method;
  const chatMatch = /^\/connectors\/([^/]+)\/chat$/.exec(path);
  if (chatMatch) {
    const context = await adminContext(db, config, request, method !== "GET");
    const connector = await bundle(db, context, chatMatch[1]);
    if (method === "GET") return chatAdminView(db, config, connector.app_id);
    if (method === "PATCH") {
      if (connector.status === "archived" && body.enabled === true) throw conflict("Archived apps cannot turn chat on");
      const result = await updateChatSetting(db, config, connector.app_id, body);
      await audit(db, context, "chat.settings", connector);
      return result;
    }
  }
  if (path === "/model-providers/presets" && method === "GET") {
    await adminContext(db, config, request);
    return PROVIDER_PRESETS;
  }
  if (path === "/model-providers") {
    const context = await adminContext(db, config, request, method !== "GET");
    if (method === "GET") {
      const providers = await db.all("SELECT * FROM model_providers ORDER BY name");
      return { builtin: [
        { key: "anthropic", name: "Claude (Anthropic)", ready: !!config.anthropicApiKey,
          configured_by: "ANTHROPIC_API_KEY", used_by: await usedBy(db, "anthropic") },
        ...(config.chatOpenaiBaseUrl || (await usedBy(db, "openai_compatible")).length
          ? [{ key: "openai_compatible", name: "Gateway (environment)",
            ready: !!config.chatOpenaiBaseUrl, configured_by: "CHAT_OPENAI_BASE_URL",
            used_by: await usedBy(db, "openai_compatible") }] : []),
      ], providers: await Promise.all(providers.map((row) => providerView(db, row))) };
    }
    role(context.user, ["super_admin"]);
    if (method === "POST") {
      const data = validateProviderBody(body, null);
      await validateDestination(data.base_url + "/chat/completions", modelConfig(config))
        .catch((error) => { if (error.code !== "CONNECTOR_DNS") throw error; });
      if (await db.one("SELECT id FROM model_providers WHERE key = ?", [data.key])) throw conflict("Provider key already exists");
      const providerId = id();
      const ciphertext = data.api_key ? encryptSecret(config.secretEncryptionKey, data.api_key) : "";
      await db.run(`INSERT INTO model_providers (id, key, name, base_url, auth_style, auth_header,
        api_key_ciphertext, api_key_hint, headers, token_param, tool_schema, streaming,
        default_model, models, enabled, status, status_message, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [providerId, data.key, data.name, data.base_url, data.auth_style ?? "bearer",
        data.auth_header ?? "", ciphertext, data.api_key?.slice(-4) ?? "",
        JSON.stringify(data.headers ?? {}), data.token_param ?? "max_tokens",
        data.tool_schema ?? "full", data.streaming ?? true, data.default_model ?? "",
        "[]", data.enabled ?? true, "untested", "", context.user.id, iso(), iso()]);
      await audit(db, context, "provider.create");
      return { status: 201, data: await providerView(db,
        await db.one("SELECT * FROM model_providers WHERE id = ?", [providerId])) };
    }
  }
  const modelsMatch = /^\/model-providers\/([^/]+)\/models$/.exec(path);
  if (modelsMatch && method === "GET") {
    await adminContext(db, config, request);
    return modelList(db, config, decodeURIComponent(modelsMatch[1]),
      url.searchParams.get("refresh") === "true");
  }
  const match = /^\/model-providers\/([^/]+)(?:\/(test))?$/.exec(path);
  if (match) {
    const context = await adminContext(db, config, request, true);
    role(context.user, ["super_admin"]);
    const row = await db.one("SELECT * FROM model_providers WHERE id = ?", [match[1]]);
    if (!row) throw missing("Model provider was not found");
    if (method === "DELETE" && !match[2]) {
      if ((await usedBy(db, row.key)).length) throw conflict("Choose another provider for apps using this one");
      await db.run("DELETE FROM model_providers WHERE id = ?", [row.id]);
      await audit(db, context, "provider.delete");
      return { deleted: true };
    }
    if (method === "PATCH" && !match[2]) {
      const data = validateProviderBody(body, row);
      await validateDestination(data.base_url + "/chat/completions", modelConfig(config))
        .catch((error) => { if (error.code !== "CONNECTOR_DNS") throw error; });
      const ciphertext = body.clear_api_key ? "" : body.api_key
        ? encryptSecret(config.secretEncryptionKey, body.api_key) : row.api_key_ciphertext;
      await db.run(`UPDATE model_providers SET name = ?, base_url = ?, auth_style = ?,
        auth_header = ?, api_key_ciphertext = ?, api_key_hint = ?, headers = ?,
        token_param = ?, tool_schema = ?, streaming = ?, default_model = ?,
        enabled = ?, status = ?, status_message = ?, updated_at = ? WHERE id = ?`,
      [data.name, data.base_url, data.auth_style, data.auth_header ?? "",
        ciphertext, body.clear_api_key ? "" : body.api_key?.slice(-4) ?? row.api_key_hint,
        JSON.stringify(data.headers ?? {}), data.token_param, data.tool_schema,
        data.streaming, data.default_model ?? "", data.enabled,
        "untested", "", iso(), row.id]);
      await audit(db, context, "provider.update");
      return providerView(db, await db.one("SELECT * FROM model_providers WHERE id = ?", [row.id]));
    }
    if (method === "POST" && match[2] === "test") {
      const listing = await modelList(db, config, row.key, true);
      const status = listing.error ? "error" : "ok";
      await db.run(`UPDATE model_providers SET status = ?, status_message = ?,
        checked_at = ? WHERE id = ?`,
      [status, listing.error ?? `Connected. ${listing.models.length} models available.`,
        iso(), row.id]);
      await audit(db, context, "provider.test", null, {
        result: status === "ok" ? "success" : "error" });
      return providerView(db, await db.one("SELECT * FROM model_providers WHERE id = ?", [row.id]));
    }
  }
  return undefined;
}
