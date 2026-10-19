import { createServer } from "node:http";
import { HubError } from "./errors.js";
import { handleAuth } from "./auth.js";
import { handleAccess } from "./admin-access.js";
import { handleResources } from "./admin-resources.js";
import { handleSkills } from "./skills.js";
import { handleActivity } from "./admin-activity.js";
import { handleCapabilities } from "./admin-capabilities.js";
import { handleChatSettings } from "./chat-settings.js";
import { handleAdminTools } from "./admin-tools.js";
import { handleBackup } from "./backup.js";
import { handleChat, handleAdminChatTry } from "./chat.js";
import { createMcpEndpoint } from "./mcp.js";

function send(response, status, data) {
  if (response.writableEnded) return;
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify({ success: true, data }));
}

function sendResult(response, result) {
  return result && Number.isInteger(result.status) && Object.hasOwn(result, "data")
    ? send(response, result.status, result.data) : send(response, 200, result);
}

function fail(response, error) {
  if (response.writableEnded) return;
  const known = error instanceof HubError;
  response.writeHead(known ? error.status || 500 : 500,
    { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify({ success: false, error: {
    code: known ? error.code : "INTERNAL",
    message: known ? error.message : "The request could not be completed",
  } }));
}

// An oversized body is refused without destroying the request stream: destroying it
// detaches req.socket before the response finishes, which crashes socket-tracking
// listeners such as Nitro's graceful shutdown. The connection closes after the answer.
async function readJson(request, response, limit) {
  const tooLarge = () => {
    response.setHeader("Connection", "close");
    return new HubError("Request body is too large", "PAYLOAD_TOO_LARGE", 413);
  };
  if (Number(request.headers["content-length"] ?? 0) > limit) throw tooLarge();
  let length = 0;
  const chunks = [];
  await new Promise((resolve, reject) => {
    const onData = (chunk) => {
      length += chunk.length;
      if (length <= limit) return chunks.push(chunk);
      request.off("data", onData);
      request.off("end", resolve);
      request.pause();
      reject(tooLarge());
    };
    request.on("data", onData);
    request.once("end", resolve);
    request.once("error", reject);
  });
  if (!length) return {};
  try {
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error();
    return body;
  } catch { throw new HubError("Request body must be JSON", "VALIDATION_FAILED", 422); }
}

// One Node request handler for the Hub API, MCP and chat endpoints. Nitro mounts it on
// those paths (server/routes, server/api); tests serve it with createHubServer.
export function createHubHandler({ db, config }) {
  const mcp = createMcpEndpoint({ db, config });
  return async (request, response) => {
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("X-Frame-Options", "DENY");
    response.setHeader("Referrer-Policy", "no-referrer");
    response.setHeader("Cache-Control", "no-store");
    const origin = request.headers.origin;
    if (origin && config.allowedOrigins.includes(origin)) {
      response.setHeader("Access-Control-Allow-Origin", origin);
      response.setHeader("Access-Control-Allow-Credentials", "true");
      response.setHeader("Vary", "Origin");
    }
    try {
      const host = request.headers.host ?? "";
      if (config.allowedHosts.length && !config.allowedHosts.includes(host)) {
        throw new HubError("Request was rejected", "HTTP_ERROR", 400);
      }
      const url = new URL(request.url, `http://${host}`);
      if (request.method === "GET" && url.pathname === "/health") {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ status: "ok" }));
        return;
      }
      if (request.method === "GET" && url.pathname === "/ready") {
        await db.ready();
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ status: "ready" }));
        return;
      }
      if (request.method === "OPTIONS" && origin && config.allowedOrigins.includes(origin)) {
        response.writeHead(204, { "Access-Control-Allow-Methods": "GET,POST,PATCH,PUT,DELETE",
          "Access-Control-Allow-Headers": "Content-Type,X-CSRF-Token" });
        response.end();
        return;
      }
      if (url.pathname === "/mcp" || url.pathname === "/mcp/") {
        await mcp(request, response);
        return;
      }
      if (url.pathname.startsWith("/chat/v1/")) {
        const body = request.method === "POST" ? await readJson(request, response, config.maxPayloadBytes) : {};
        const handled = await handleChat({ db, config, request, response,
          path: url.pathname, body, send });
        if (!handled) throw new HubError("Request was rejected", "HTTP_ERROR", 404);
        return;
      }
      if (url.pathname.startsWith("/api/admin/v1/auth/")) {
        const body = ["POST", "PATCH", "PUT"].includes(request.method)
          ? await readJson(request, response, config.maxPayloadBytes) : {};
        const handled = await handleAuth({ db, config, request, response,
          path: url.pathname.slice("/api/admin/v1".length), body, send });
        if (handled === false) throw new HubError("Request was rejected", "HTTP_ERROR", 404);
        return;
      }
      if (url.pathname.startsWith("/api/admin/v1/")) {
        const body = ["POST", "PATCH", "PUT"].includes(request.method)
          ? await readJson(request, response, config.maxPayloadBytes) : {};
        const adminPath = url.pathname.slice("/api/admin/v1".length);
        if (await handleAdminChatTry({ db, config, request, response,
          path: adminPath, body })) return;
        const result = await handleAccess({ db, config, request, url,
          path: adminPath, body });
        if (result !== undefined) {
          return sendResult(response, result);
        }
        const capabilities = await handleCapabilities({ db, config, request,
          path: url.pathname.slice("/api/admin/v1".length) });
        if (capabilities !== undefined) return send(response, 200, capabilities);
        const chatSettings = await handleChatSettings({ db, config, request, url,
          path: url.pathname.slice("/api/admin/v1".length), body });
        if (chatSettings !== undefined) {
          return sendResult(response, chatSettings);
        }
        const adminTools = await handleAdminTools({ db, config, request,
          path: url.pathname.slice("/api/admin/v1".length), body });
        if (adminTools !== undefined) {
          return sendResult(response, adminTools);
        }
        const backup = await handleBackup({ db, config, request,
          path: url.pathname.slice("/api/admin/v1".length), body });
        if (backup !== undefined) return sendResult(response, backup);
        const resources = await handleResources({ db, config, request, url,
          path: url.pathname.slice("/api/admin/v1".length), body });
        if (resources !== undefined) {
          return sendResult(response, resources);
        }
        const skills = await handleSkills({ db, config, request, url,
          path: url.pathname.slice("/api/admin/v1".length), body });
        if (skills !== undefined) {
          return sendResult(response, skills);
        }
        const activity = await handleActivity({ db, config, request, url,
          path: url.pathname.slice("/api/admin/v1".length) });
        if (activity !== undefined) return send(response, 200, activity);
      }
      throw new HubError("Request was rejected", "HTTP_ERROR", 404);
    } catch (error) {
      if (!(error instanceof HubError)) {
        console.error(JSON.stringify({ event: "request_failed", error_type: error?.constructor?.name ?? "Error" }));
      }
      fail(response, error);
    }
  };
}

export function createHubServer({ db, config }) {
  return createServer(createHubHandler({ db, config }));
}
