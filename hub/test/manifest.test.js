import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { validateManifest } from "../server/core/manifest.js";
import { isSensitivePath, treeContainsPii, projectRecord } from "../server/core/privacy.js";

const input = { type: "object", additionalProperties: false, properties: {
  limit: { type: "integer", minimum: 1, maximum: 50 } } };
const output = { type: "array", maxItems: 50, items: { type: "object", additionalProperties: false,
  required: ["ref"], properties: { ref: { type: "string", maxLength: 64 } } } };

test("source-managed manifest is normalized and rejects cross-app routes", () => {
  const manifest = { contract_version: "1.0", application: "your_app", managed_by: "application",
    manifest_version: "1", modules: [{ key: "projects", name: "Projects", supported_operations: ["read"],
      readable_fields: ["ref"], read_endpoints: [{ method: "GET", path_template: "/api/v1/projects",
        requires_user_context: true, tenant_field: "tenant_id", tool_key: "your_app.projects.list",
        description: "List permitted projects", input_schema: input, output_schema: output }] }] };
  const normalized = validateManifest(manifest, "your_app", true);
  assert.equal(normalized.modules[0].read_endpoints[0].input_schema.properties.limit.minimum, 1);
  assert.match(normalized.manifest_hash, /^[a-f0-9]{64}$/);
  manifest.modules[0].read_endpoints[0].tool_key = "other.projects.list";
  assert.throws(() => validateManifest(manifest, "your_app", true), { code: "SCHEMA_MISMATCH" });
});

test("contract manifests need no tool keys and hash exactly like the Python edition", () => {
  // Served by reference/your_app; the expected hash is what the Python edition stores for it.
  const manifest = JSON.parse(readFileSync(new URL("./fixtures/your-app-manifest.json", import.meta.url), "utf8"));
  const normalized = validateManifest(manifest, "your_app");
  assert.equal(normalized.manifest_hash, "93661c95a0cf75e46c6281e2d9ea5451097435932ffa35a5b4f8484d2a784e91");
  const route = normalized.modules.find((module) => module.key === "projects").read_endpoints[0];
  assert.equal("tool_key" in route, false);
  assert.equal(route.output_schema.items.properties.status.maxLength, 200);
  assert.equal("maxLength" in route.input_schema.properties.status, false);
});

test("privacy guard recognizes sensitive names and values before exposing records", () => {
  assert.equal(isSensitivePath("owner_email"), true);
  assert.equal(isSensitivePath("contactPhone"), true);
  assert.equal(treeContainsPii({ nested: "canary@example.com" }), true);
  assert.deepEqual(projectRecord({ ref: "prj_1", secret: "hidden" }, ["ref", "secret"],
    { ref: "allowed_for_ai", secret: "allowed_for_ai" }), { ref: "prj_1" });
  assert.throws(() => projectRecord({ ref: "canary@example.com" }, ["ref"], { ref: "allowed_for_ai" }),
    { code: "PII_DETECTED" });
});
