import { lookup } from "node:dns/promises";
import http from "node:http";
import https from "node:https";
import { isIP } from "node:net";
import ipaddr from "ipaddr.js";
import { HubSdkError } from "../src/errors.js";

const blockedHosts = new Set(["metadata.google.internal", "metadata.google", "instance-data", "metadata"]);
const error = (code, message, status = 422) => new HubSdkError(message, code, status);

function allowedIp(value, config) {
  let address;
  try { address = ipaddr.parse(value); } catch { return false; }
  if (address.kind() === "ipv6" && address.isIPv4MappedAddress()) return allowedIp(address.toIPv4Address().toString(), config);
  const kind = address.range();
  if (kind === "loopback") return config.egressAllowLoopback;
  if (["private", "uniqueLocal"].includes(kind)) return config.egressAllowPrivate;
  return kind === "unicast";
}

function inApprovedNetwork(value, cidrs) {
  const address = ipaddr.parse(value);
  return cidrs.some((cidr) => {
    try {
      const network = ipaddr.parseCIDR(cidr);
      return address.kind() === network[0].kind() && address.match(network);
    } catch { throw error("UNSAFE_CONFIGURATION", "Invalid egress CIDR", 500); }
  });
}

export async function validateDestination(rawUrl, config) {
  let url;
  try { url = new URL(rawUrl); } catch { throw error("SSRF_BLOCKED", "Connector URL is invalid"); }
  if (url.username || url.password) throw error("SSRF_BLOCKED", "Credentials in the connector URL are not allowed");
  if (url.protocol !== "https:" && !(url.protocol === "http:" && config.allowInsecureHttp)) {
    throw error("SSRF_BLOCKED", "Connector URL scheme is not allowed");
  }
  const host = url.hostname.toLowerCase().replace(/\.$/, "").replace(/^\[|\]$/g, "");
  if (!host || blockedHosts.has(host) || host.endsWith(".localhost")) {
    throw error("SSRF_BLOCKED", "Connector host is not allowed");
  }
  const port = Number(url.port || (url.protocol === "https:" ? 443 : 80));
  if (!config.egressAllowedPorts.includes(port)) throw error("SSRF_BLOCKED", "Connector port is not allowed");
  const approvedHost = config.egressAllowedHosts.includes(host);
  if (config.egressAllowedHosts.length && !approvedHost && !config.egressAllowedCidrs.length) {
    throw error("SSRF_BLOCKED", "Connector host is outside approved egress destinations");
  }
  let addresses;
  try {
    addresses = isIP(host) ? [{ address: host, family: isIP(host) }] : await lookup(host, { all: true });
  } catch { throw error("CONNECTOR_DNS", "Connector host could not be resolved"); }
  if (!addresses.length) throw error("CONNECTOR_DNS", "Connector host could not be resolved");
  for (const row of addresses) {
    if (!allowedIp(row.address, config)) throw error("SSRF_BLOCKED", "Destination address is not allowed");
    if ((config.egressAllowedHosts.length || config.egressAllowedCidrs.length) && !approvedHost &&
        !inApprovedNetwork(row.address, config.egressAllowedCidrs)) {
      throw error("SSRF_BLOCKED", "Destination is outside approved egress destinations");
    }
  }
  return { url, host, port, addresses };
}

export function joinSourceUrl(base, path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || path.includes("\\")) {
    throw error("VALIDATION_FAILED", "Connector path must be a rooted relative path");
  }
  const url = new URL(path.slice(1), base.replace(/\/$/, "") + "/");
  if (url.origin !== new URL(base).origin) throw error("SSRF_BLOCKED", "Resolved URL escaped connector origin");
  return url.toString();
}

function requestOnce({ method, url, ip, family, headers, jsonBody, timeoutMs, maxBytes, tlsVerify }) {
  return new Promise((resolve, reject) => {
    const body = jsonBody === undefined ? undefined : Buffer.from(JSON.stringify(jsonBody));
    const options = {
      method, hostname: url.hostname.replace(/^\[|\]$/g, ""), port: url.port || undefined,
      path: `${url.pathname}${url.search}`, headers: { ...headers,
        ...(body ? { "Content-Type": "application/json", "Content-Length": String(body.length) } : {}) },
      lookup: (_host, _options, callback) => callback(null, ip, family),
      rejectUnauthorized: tlsVerify,
      timeout: timeoutMs,
    };
    const library = url.protocol === "https:" ? https : http;
    const request = library.request(options, (response) => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
        response.resume();
        reject(error("SSRF_BLOCKED", "Redirects are not allowed for connector calls"));
        return;
      }
      const contentType = (response.headers["content-type"] ?? "").split(";", 1)[0].trim().toLowerCase();
      if (response.statusCode >= 200 && response.statusCode < 300 &&
          contentType !== "application/json" && !contentType.endsWith("+json")) {
        response.resume();
        reject(error("SCHEMA_MISMATCH", "Upstream response must use a JSON content type", 502));
        return;
      }
      const chunks = [];
      let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size > maxBytes) {
          response.destroy(error("PAYLOAD_TOO_LARGE", "Upstream payload exceeds the limit", 413));
        } else chunks.push(chunk);
      });
      response.on("error", reject);
      response.on("end", () => resolve({ status: response.statusCode,
        body: Buffer.concat(chunks).toString("utf8") }));
    });
    request.on("timeout", () => request.destroy(error("UPSTREAM_TIMEOUT", "The connected application timed out", 504)));
    request.on("error", reject);
    request.end(body);
  });
}

export async function sourceRequest({ method, url, config, headers, params, jsonBody,
                                      timeoutMs = 5000, maxBytes = 1_048_576,
                                      retries = 2, tlsVerify = true, write = false }) {
  const allowed = write ? ["GET", "POST", "PUT", "PATCH", "DELETE"] : ["GET", "POST"];
  if (!allowed.includes(method)) throw error("VALIDATION_FAILED", "This HTTP method is not allowed for the request");
  if (!tlsVerify && !config.allowInsecureTls) throw error("UNSAFE_CONFIGURATION", "TLS verification cannot be disabled");
  const started = Date.now();
  let count = 0;
  while (true) {
    const elapsed = Date.now() - started;
    if (elapsed >= timeoutMs) throw error("UPSTREAM_TIMEOUT", "The connected application timed out", 504);
    const target = new URL(url);
    for (const [key, value] of Object.entries(params ?? {})) target.searchParams.set(key, String(value));
    const { addresses } = await validateDestination(target.toString(), config);
    try {
      const result = await requestOnce({ method, url: target, ip: addresses[0].address,
        family: addresses[0].family, headers: typeof headers === "function" ? headers() : headers,
        jsonBody, timeoutMs: timeoutMs - elapsed, maxBytes, tlsVerify });
      if (method === "GET" && [502, 503, 504].includes(result.status) && count < retries) {
        await new Promise((resolve) => setTimeout(resolve, 50 * 2 ** count));
        count++;
        continue;
      }
      return { ...result, elapsedMs: Date.now() - started, retryCount: count };
    } catch (cause) {
      if (cause instanceof HubSdkError && !["UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE"].includes(cause.code)) throw cause;
      if (method === "GET" && count < retries) {
        await new Promise((resolve) => setTimeout(resolve, 50 * 2 ** count));
        count++;
        continue;
      }
      if (cause instanceof HubSdkError) throw cause;
      throw error("UPSTREAM_UNAVAILABLE", "The connected application could not be reached", 502);
    }
  }
}
