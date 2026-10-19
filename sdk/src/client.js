import { HubSdkError } from "./errors.js";
import { signDelegation } from "./tokens.js";

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;

function required(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError(`${label} must be a nonempty string`);
  return value;
}

function endpoint(baseUrl, path) {
  const parsed = new URL(required(baseUrl, "baseUrl"));
  if (!(["https:", "http:"].includes(parsed.protocol)) || !parsed.hostname || parsed.username ||
      parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/") {
    throw new TypeError("baseUrl must be an HTTP(S) origin without credentials, path, query or fragment");
  }
  return new URL(path, parsed).toString();
}

async function responseText(response) {
  const reader = response.body?.getReader();
  if (!reader) return "";
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_RESPONSE_BYTES) throw new HubSdkError("Hub response is too large", "INVALID_RESPONSE", response.status);
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function jsonResponse(response) {
  let body;
  try { body = JSON.parse(await responseText(response)); } catch { body = null; }
  if (!response.ok || body?.success === false) {
    throw new HubSdkError(body?.error?.message ?? "Hub request failed", body?.error?.code ?? "HTTP_ERROR", response.status);
  }
  if (!body || typeof body !== "object") throw new HubSdkError("Invalid Hub response", "INVALID_RESPONSE", response.status);
  return body;
}

function toolPayload(result) {
  if (!result || typeof result !== "object") throw new HubSdkError("Invalid MCP tool result", "INVALID_RESPONSE");
  if (result.isError === true) {
    const message = result.content?.find?.((part) => part.type === "text")?.text ?? "MCP tool failed";
    const match = /^([A-Z_]+): ([^\n]*)/.exec(message);
    throw new HubSdkError(match?.[2] ?? "MCP tool failed", match?.[1] ?? "TOOL_ERROR");
  }
  let payload = result.structuredContent;
  if (payload?.result && typeof payload.result === "object") payload = payload.result;
  if (payload === undefined) {
    try { payload = JSON.parse(result.content?.find?.((part) => part.type === "text")?.text); }
    catch { throw new HubSdkError("Invalid MCP tool result", "INVALID_RESPONSE"); }
  }
  if (!payload || payload.success !== true) throw new HubSdkError("Invalid MCP tool result", "INVALID_RESPONSE");
  return payload;
}

function parseEvent(frame) {
  let event = "message";
  const data = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trimStart();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try { return { event, data: JSON.parse(data.join("\n")) }; }
  catch { throw new HubSdkError("Invalid chat event", "INVALID_RESPONSE"); }
}

export class HubClient {
  #fetch;
  #requestId = 0;

  constructor({ baseUrl, clientKey, appKey, delegationSecret, origin, timeoutMs = 30000,
                protocolVersion = "2026-07-28", fetch: fetchImpl = globalThis.fetch }) {
    this.mcpUrl = endpoint(baseUrl, "/mcp");
    this.chatConfigUrl = endpoint(baseUrl, "/chat/v1/config");
    this.chatTurnUrl = endpoint(baseUrl, "/chat/v1/turn");
    this.clientKey = required(clientKey, "clientKey");
    this.appKey = required(appKey, "appKey");
    this.delegationSecret = required(delegationSecret, "delegationSecret");
    this.origin = origin;
    if (origin !== undefined) required(origin, "origin");
    if (!Number.isInteger(timeoutMs) || timeoutMs < 1) throw new RangeError("timeoutMs must be positive");
    this.timeoutMs = timeoutMs;
    this.protocolVersion = required(protocolVersion, "protocolVersion");
    if (typeof fetchImpl !== "function") throw new TypeError("fetch must be a function");
    this.#fetch = fetchImpl;
  }

  delegationFor(actor) {
    if (!actor || typeof actor !== "object") throw new TypeError("actor is required");
    return signDelegation({ appKey: this.appKey, tenantId: actor.tenantId,
      userRef: actor.userRef, secret: this.delegationSecret });
  }

  #headers(actor, extra = {}) {
    return { Authorization: `Bearer ${this.clientKey}`, ...(this.origin ? { Origin: this.origin } : {}),
      ...(actor ? { "X-Hub-Delegation": this.delegationFor(actor) } : {}), ...extra };
  }

  async #send(url, init) {
    try {
      return await this.#fetch(url, { ...init, redirect: "error", signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (error) {
      if (error instanceof HubSdkError) throw error;
      throw new HubSdkError("Hub is unavailable", "HUB_UNAVAILABLE");
    }
  }

  async #rpc(method, params, actor) {
    const payload = { ...params, _meta: {
      "io.modelcontextprotocol/protocolVersion": this.protocolVersion,
      "io.modelcontextprotocol/clientCapabilities": {},
      "io.modelcontextprotocol/clientInfo": { name: "mcp-hub-backend-sdk", version: "1.0.0" },
    } };
    const response = await this.#send(this.mcpUrl, {
      method: "POST",
      headers: this.#headers(actor, { Accept: "application/json, text/event-stream", "Content-Type": "application/json",
        "MCP-Protocol-Version": this.protocolVersion, "MCP-Method": method,
        ...(typeof params.name === "string" ? { "MCP-Name": params.name } : {}) }),
      body: JSON.stringify({ jsonrpc: "2.0", id: ++this.#requestId, method, params: payload }),
    });
    const body = await jsonResponse(response);
    if (body.jsonrpc !== "2.0" || body.error || !body.result || typeof body.result !== "object") {
      throw new HubSdkError(body.error?.message ?? "Invalid MCP response", body.error?.code ?? "INVALID_RESPONSE", response.status);
    }
    return body.result;
  }

  async listTools(actor) {
    const result = await this.#rpc("tools/list", {}, actor);
    if (!Array.isArray(result.tools)) throw new HubSdkError("Invalid tool list", "INVALID_RESPONSE");
    return result.tools;
  }

  async callTool(name, args = {}, actor) {
    required(name, "name");
    if (!args || typeof args !== "object" || Array.isArray(args)) throw new TypeError("args must be an object");
    return toolPayload(await this.#rpc("tools/call", { name, arguments: args }, actor));
  }

  async listPrompts(actor) {
    const result = await this.#rpc("prompts/list", {}, actor);
    if (!Array.isArray(result.prompts)) throw new HubSdkError("Invalid prompt list", "INVALID_RESPONSE");
    return result.prompts;
  }

  async getPrompt(name, args = {}, actor) {
    required(name, "name");
    return this.#rpc("prompts/get", { name, arguments: args }, actor);
  }

  async getChatConfig() {
    const response = await this.#send(this.chatConfigUrl, { method: "GET", headers: this.#headers() });
    const body = await jsonResponse(response);
    if (!body.data || typeof body.data !== "object") throw new HubSdkError("Invalid chat config", "INVALID_RESPONSE");
    return body.data;
  }

  async chatTurn(request, actor) {
    const response = await this.#send(this.chatTurnUrl, { method: "POST",
      headers: this.#headers(actor, { "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify({ ...request, stream: false }) });
    const body = await jsonResponse(response);
    if (!body.data || typeof body.data !== "object") throw new HubSdkError("Invalid chat response", "INVALID_RESPONSE");
    return body.data;
  }

  async *streamChatTurn(request, actor) {
    const response = await this.#send(this.chatTurnUrl, { method: "POST",
      headers: this.#headers(actor, { "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify({ ...request, stream: true }) });
    if (!response.ok) { await jsonResponse(response); return; }
    if (!response.headers.get("content-type")?.toLowerCase().includes("text/event-stream") || !response.body) {
      throw new HubSdkError("Invalid chat stream", "INVALID_RESPONSE", response.status);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let doneEvent = false;
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        if (buffer.length > MAX_RESPONSE_BYTES) throw new HubSdkError("Chat event is too large", "INVALID_RESPONSE");
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          const frame = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          const item = parseEvent(frame);
          if (!item) continue;
          if (item.event === "error") throw new HubSdkError(item.data?.message ?? "Chat failed", item.data?.code ?? "CHAT_ERROR");
          yield item;
          if (item.event === "done") { doneEvent = true; return; }
        }
      }
      if (!doneEvent) throw new HubSdkError("Chat stream ended without done", "INVALID_RESPONSE");
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}
