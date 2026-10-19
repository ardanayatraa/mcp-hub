import assert from "node:assert/strict";
import { createHmac, randomBytes } from "node:crypto";
import test from "node:test";
import { HubClient, HubSdkError, HubSourceAuth, MemoryReplayStore, signDelegation, verifyAssertion } from "../src/index.js";

const now = () => Math.floor(Date.now() / 1000);
const secret = "a-long-shared-delegation-secret-12345";
const actor = { tenantId: "tenant_a", userRef: "user_1" };

function signed(payload) {
  const raw = Buffer.from(JSON.stringify(payload));
  return `${raw.toString("base64url")}.${createHmac("sha256", secret).update(raw).digest("base64url")}`;
}

function assertion(overrides = {}) {
  return signed({ app_key: "your_app", aud: "https://source.example", exp: now() + 60,
    tenant_id: actor.tenantId, user_ref: actor.userRef, jti: randomBytes(18).toString("base64url"), ...overrides });
}

function mockFetch(handler) {
  const calls = [];
  return { calls, fetch: async (url, init) => { calls.push({ url, init }); return handler(url, init); } };
}

test("delegation token matches Hub's signed payload contract", () => {
  const token = signDelegation({ appKey: "your_app", ...actor, secret });
  const [body, signature] = token.split(".");
  const raw = Buffer.from(body, "base64url");
  assert.equal(createHmac("sha256", secret).update(raw).digest("base64url"), signature);
  const payload = JSON.parse(raw.toString());
  assert.deepEqual({ app_key: payload.app_key, aud: payload.aud, tenant_id: payload.tenant_id,
    user_ref: payload.user_ref }, { app_key: "your_app", aud: "mcp-hub", tenant_id: "tenant_a", user_ref: "user_1" });
  assert.ok(payload.exp > now() && payload.exp <= now() + 120);
  assert.throws(() => signDelegation({ appKey: "your_app", ...actor, secret, ttlSeconds: 151 }), RangeError);
});

test("source authentication checks bearer, assertion, replay and current permission", async () => {
  const replay = new MemoryReplayStore();
  let allowed = true;
  const auth = new HubSourceAuth({ appKey: "your_app", audience: "https://source.example",
    bearerToken: "source-service-key", delegationSecret: secret,
    consumeJti: replay.consume.bind(replay),
    authorize: async ({ tenantId, userRef, permission }) => ({ active: true, allowed,
      tenantId, actor: { id: userRef, permission } }) });
  const headers = { authorization: "Bearer source-service-key", "x-hub-assertion": assertion() };
  assert.deepEqual(await auth.authenticate(headers, "projects.read"), {
    ...actor, actor: { id: "user_1", permission: "projects.read" } });
  await assert.rejects(auth.authenticate(headers, "projects.read"), { code: "PERMISSION_DENIED" });
  allowed = false;
  await assert.rejects(auth.authenticate({ ...headers, "x-hub-assertion": assertion() }, "projects.read"),
    { code: "PERMISSION_DENIED" });
  assert.throws(() => auth.verifyBearer({ authorization: "Bearer wrong" }), { code: "UNAUTHENTICATED" });
});

test("assertions fail closed on wrong audience, expiry, tampering and missing replay store", async () => {
  const options = { appKey: "your_app", audience: "https://source.example", secret,
    consumeJti: async () => true };
  const valid = assertion();
  const tampered = `${valid.slice(0, -1)}${valid.endsWith("A") ? "B" : "A"}`;
  for (const token of [assertion({ aud: "mcp-hub" }), assertion({ exp: now() - 1 }),
    assertion({ exp: now() + 151 }), assertion({ tenant_id: "" }), assertion({ jti: "short" }),
    tampered]) {
    await assert.rejects(verifyAssertion({ ...options, token }), { code: "PERMISSION_DENIED" });
  }
  await assert.rejects(verifyAssertion({ ...options, token: assertion(), consumeJti: async () => false }),
    { code: "PERMISSION_DENIED" });
  await assert.rejects(verifyAssertion({ ...options, token: assertion(), consumeJti: undefined }), TypeError);
});

test("MCP calls send fresh delegated context and return structured tool data", async () => {
  const { calls, fetch } = mockFetch((_url, init) => {
    const request = JSON.parse(init.body);
    const result = request.method === "tools/list"
      ? { tools: [{ name: "your_app__projects__list", inputSchema: { type: "object" } }] }
      : { structuredContent: { success: true, data: [{ ref: "prj_1" }], meta: { contains_personal_data: false } } };
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: request.id, result }),
      { status: 200, headers: { "content-type": "application/json" } });
  });
  const client = new HubClient({ baseUrl: "https://hub.example", clientKey: "hub-client-key",
    appKey: "your_app", delegationSecret: secret, origin: "https://source.example", fetch });
  assert.equal((await client.listTools(actor))[0].name, "your_app__projects__list");
  const payload = await client.callTool("your_app__projects__list", { limit: 1 }, actor);
  assert.deepEqual(payload.data, [{ ref: "prj_1" }]);
  assert.equal(calls[1].url, "https://hub.example/mcp");
  assert.equal(calls[1].init.headers.Authorization, "Bearer hub-client-key");
  assert.equal(calls[1].init.headers["MCP-Method"], "tools/call");
  assert.equal(calls[1].init.headers["MCP-Name"], "your_app__projects__list");
  const signedActor = JSON.parse(Buffer.from(calls[1].init.headers["X-Hub-Delegation"].split(".")[0], "base64url"));
  assert.equal(signedActor.user_ref, "user_1");
  assert.deepEqual(JSON.parse(calls[1].init.body).params.arguments, { limit: 1 });
});

test("MCP tool errors and chat refusals retain safe Hub codes", async () => {
  let mode = "tool";
  const { fetch } = mockFetch(() => mode === "tool"
    ? new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { isError: true,
      content: [{ type: "text", text: "PERMISSION_DENIED: Operation is not permitted (trace tr_1)" }] } }), { status: 200 })
    : new Response(JSON.stringify({ success: false, error: { code: "CHAT_DISABLED", message: "Chat is disabled" } }),
      { status: 403 }));
  const client = new HubClient({ baseUrl: "https://hub.example", clientKey: "key",
    appKey: "your_app", delegationSecret: secret, fetch });
  await assert.rejects(client.callTool("read", {}, actor), { code: "PERMISSION_DENIED" });
  mode = "chat";
  await assert.rejects(client.chatTurn({ message: "hello" }, actor), { code: "CHAT_DISABLED", status: 403 });
});

test("chat stream parses fragmented SSE events and requires done", async () => {
  const body = new ReadableStream({ start(controller) {
    for (const chunk of ["event: start\ndata: {\"trace_id\":\"tr_1\"}\n\nevent: te",
      "xt\ndata: {\"delta\":\"Hi\"}\n\n: keep-alive\n\nevent: done\ndata: {\"trace_id\":\"tr_1\"}\n\n"]) {
      controller.enqueue(new TextEncoder().encode(chunk));
    }
    controller.close();
  } });
  const { fetch } = mockFetch(() => new Response(body, { headers: { "content-type": "text/event-stream" } }));
  const client = new HubClient({ baseUrl: "https://hub.example", clientKey: "key",
    appKey: "your_app", delegationSecret: secret, fetch });
  const events = [];
  for await (const item of client.streamChatTurn({ message: "hello" }, actor)) events.push(item);
  assert.deepEqual(events.map((item) => item.event), ["start", "text", "done"]);
  assert.equal(events[1].data.delta, "Hi");
});
