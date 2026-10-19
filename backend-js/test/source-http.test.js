import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { loadConfig } from "../server/config.js";
import { joinSourceUrl, sourceRequest, validateDestination } from "../server/source-http.js";

test("connector transport pins an allowed address, refuses redirects and limits response size", async () => {
  const server = createServer((_request, response) => {
    if (_request.url === "/redirect") { response.writeHead(302, { Location: "https://example.com" }); response.end(); }
    else if (_request.url === "/large") { response.writeHead(200, { "Content-Type": "application/json" }); response.end("x".repeat(100)); }
    else { response.writeHead(200, { "Content-Type": "application/json" }); response.end('{"status":"ok"}'); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const config = { ...loadConfig(), allowInsecureHttp: true, egressAllowLoopback: true,
    egressAllowedPorts: [port] };
  const base = `http://127.0.0.1:${port}`;
  try {
    assert.equal(joinSourceUrl(base, "/health"), `${base}/health`);
    assert.equal((await sourceRequest({ method: "GET", url: `${base}/health`, config,
      headers: { Accept: "application/json" } })).status, 200);
    await assert.rejects(sourceRequest({ method: "GET", url: `${base}/redirect`, config }), { code: "SSRF_BLOCKED" });
    await assert.rejects(sourceRequest({ method: "GET", url: `${base}/large`, config, maxBytes: 32 }),
      { code: "PAYLOAD_TOO_LARGE" });
    await assert.rejects(validateDestination(`${base}/health`, { ...config, egressAllowLoopback: false }),
      { code: "SSRF_BLOCKED" });
    await assert.rejects(validateDestination("http://169.254.169.254/latest/meta-data", config),
      { code: "SSRF_BLOCKED" });
  } finally { await new Promise((resolve) => server.close(resolve)); }
});
