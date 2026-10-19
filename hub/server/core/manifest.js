import { createHash } from "node:crypto";
import Ajv from "ajv";
import { HubError } from "./errors.js";
import { isSensitivePath, treeContainsPii } from "./privacy.js";

const ajv = new Ajv({ allErrors: true, strict: false });
const inputTypes = new Set(["string", "integer", "number", "boolean"]);
const allowedInputKeys = new Set(["type", "additionalProperties", "properties", "required", "title", "description"]);
const propertyKeys = new Set(["type", "enum", "minimum", "maximum", "minLength", "maxLength", "title", "description"]);
const allowedOutputKeys = new Set(["type", "maxItems", "items", "title", "description"]);
const forbiddenArguments = new Set(["user_id", "tenant_id", "role", "approved", "password", "token",
  "secret", "authorization", "base_url", "method", "path", "url"]);
const namePattern = /^[A-Za-z][A-Za-z0-9_]{0,40}$/;
const pathPattern = /^\/(?:[A-Za-z0-9._~-]+|\{[A-Za-z][A-Za-z0-9_]{0,40}\})(?:\/(?:[A-Za-z0-9._~-]+|\{[A-Za-z][A-Za-z0-9_]{0,40}\}))*$/;
const toolKeyPattern = /^[a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){1,4}$/;
const fail = (message) => { throw new HubError(message, "SCHEMA_MISMATCH", 422); };
const object = (value) => value && typeof value === "object" && !Array.isArray(value);
const only = (value, allowed) => Object.keys(value).every((key) => allowed.has(key));

function metadata(value) {
  for (const key of ["title", "description"]) {
    if (key in value && (typeof value[key] !== "string" || value[key].length > 300 || treeContainsPii(value[key]))) fail("Schema metadata is invalid");
  }
  if (value.enum && treeContainsPii(value.enum)) fail("Schema metadata is blocked by privacy policy");
}

function scalar(spec, input) {
  if (!object(spec) || !only(spec, propertyKeys)) fail("Schema property is invalid");
  metadata(spec);
  const types = Array.isArray(spec.type) ? spec.type : [spec.type];
  if (!types.length || new Set(types).size !== types.length ||
      types.filter((type) => inputTypes.has(type)).length !== 1 ||
      types.some((type) => !inputTypes.has(type) && type !== "null")) fail("Schema property type is invalid");
  if (input && spec.enum !== undefined) {
    if (!Array.isArray(spec.enum) || spec.enum.length < 1 || spec.enum.length > 20 ||
        spec.enum.some((value) => typeof value !== "string" || !value || value.length > 64 || treeContainsPii(value))) {
      fail("Schema enum is invalid");
    }
  }
  for (const key of ["minimum", "maximum", "minLength", "maxLength"]) {
    if (spec[key] !== undefined && !Number.isInteger(spec[key])) fail("Schema bound is invalid");
  }
  const result = { ...spec };
  if (types.includes("string") && !result.enum) result.maxLength ??= 200;
  if (input && result.maxLength > 200) fail("String inputs are limited to 200 characters");
  if (!input && types.includes("string") && (result.maxLength < 1 || result.maxLength > 2000)) fail("Output string length is invalid");
  if (input && types.some((type) => type === "number" || type === "integer")) {
    result.minimum ??= -1_000_000_000;
    result.maximum ??= 1_000_000_000;
  }
  return result;
}

export function validateInputSchema(value) {
  if (!object(value) || value.type !== "object" || value.additionalProperties !== false || !only(value, allowedInputKeys)) {
    fail("Input schema must be a closed object");
  }
  if (JSON.stringify(value).includes('"$ref"') || JSON.stringify(value).includes("contentMediaType")) fail("Input schema cannot contain references");
  metadata(value);
  const properties = value.properties ?? {};
  if (!object(properties) || Object.keys(properties).length > 30) fail("Input properties are invalid");
  const required = value.required ?? [];
  if (!Array.isArray(required) || required.some((key) => typeof key !== "string" || !(key in properties))) fail("Required inputs are invalid");
  const normalized = {};
  for (const [name, spec] of Object.entries(properties)) {
    if (!namePattern.test(name) || forbiddenArguments.has(name.toLowerCase())) fail("Input property is invalid");
    normalized[name] = scalar(spec, true);
  }
  const result = { ...value, properties: normalized };
  try { ajv.compile(result); } catch { fail("Input schema is invalid"); }
  return result;
}

export function validateOutputSchema(value, fields, maxRecords) {
  if (!object(value) || value.type !== "array" || !only(value, allowedOutputKeys) ||
      JSON.stringify(value).includes('"$ref"')) fail("Output schema must be an array without references");
  metadata(value);
  const item = value.items;
  if (!object(item) || item.type !== "object" || item.additionalProperties !== false ||
      !only(item, allowedInputKeys) || !object(item.properties) ||
      JSON.stringify(Object.keys(item.properties).sort()) !== JSON.stringify([...fields].sort())) {
    fail("Output record schema fields must match the allowlist");
  }
  const properties = {};
  for (const [name, spec] of Object.entries(item.properties)) {
    if (!namePattern.test(name)) fail("Output field is invalid");
    properties[name] = scalar(spec, false);
  }
  const maxItems = value.maxItems ?? maxRecords;
  if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > maxRecords) fail("Output record limit exceeds source policy");
  const result = { ...value, maxItems, items: { ...item, properties } };
  try { ajv.compile(result); } catch { fail("Output schema is invalid"); }
  return result;
}

function validatePath(path, schema) {
  if (typeof path !== "string" || !pathPattern.test(path) || path.includes("..")) fail("Path is not allowlisted");
  for (const match of path.matchAll(/\{([A-Za-z][A-Za-z0-9_]{0,40})\}/g)) {
    if (!(match[1] in schema.properties)) fail("Path placeholder is not an input property");
  }
  return path;
}

function endpoint(raw, readable, writable, page, operations, write) {
  if (!object(raw)) fail("Endpoint definition is invalid");
  const method = raw.method ?? "GET";
  if (write ? !["POST", "PUT", "PATCH", "DELETE"].includes(method)
    : (method !== "GET" && !(method === "POST" && raw.safe_query === true))) fail("Endpoint method is invalid");
  if (write && !["create", "update", "delete"].includes(raw.operation)) fail("Write operation is invalid");
  if (write && !operations.includes(raw.operation)) fail("Write operation is not supported");
  const input = validateInputSchema(raw.input_schema ?? {});
  const path = validatePath(raw.path_template, input);
  if (write && Object.keys(input.properties).some((field) => ![...readable, ...writable].includes(field) || isSensitivePath(field))) {
    fail("Write inputs must be declared non-sensitive fields");
  }
  const requiresUser = raw.requires_user_context ?? true;
  if (typeof requiresUser !== "boolean" || (write && !requiresUser)) fail("Endpoint user context is invalid");
  if (!requiresUser && raw.public_aggregate !== true) fail("Unscoped route must be public aggregate");
  const tenant = requiresUser ? raw.tenant_field : null;
  if (requiresUser && (typeof tenant !== "string" || !namePattern.test(tenant))) fail("Private endpoint must declare tenant field");
  const fields = Object.keys(raw.output_schema?.items?.properties ?? {});
  if (!fields.length || (!write && fields.some((field) => !readable.includes(field))) ||
      (write && fields.some(isSensitivePath))) fail("Output fields are outside source policy");
  const output = validateOutputSchema(raw.output_schema ?? {}, fields, write ? 50 : page);
  if (typeof raw.tool_key !== "string" || !toolKeyPattern.test(raw.tool_key)) fail("Source tool key is invalid");
  const description = String(raw.description ?? `Use the reviewed ${path} route.`).trim();
  if (description.length < 3 || description.length > 300 || treeContainsPii(description) ||
      /ignore previous|ignore all previous|system prompt|disregard|<\||```/i.test(description)) fail("Tool description is invalid");
  return { ...(write ? { operation: raw.operation } : {}), method, path_template: path,
    input_schema: input, output_schema: output, requires_user_context: requiresUser,
    tenant_field: tenant, safe_query: !write && method === "POST", public_aggregate: !requiresUser,
    tool_key: raw.tool_key, description };
}

function quote(value) {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (char) =>
    `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

export function pythonJson(value) {
  if (value === null) return "null";
  if (typeof value === "string") return quote(value);
  if (typeof value === "number" || typeof value === "boolean") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(pythonJson).join(", ")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map((key) => `${quote(key)}: ${pythonJson(value[key])}`).join(", ")}}`;
  throw new TypeError("Unsupported canonical JSON value");
}

export const digest = (value) => createHash("sha256").update(pythonJson(value)).digest("hex");

export function validateManifest(document, appKey, sourceManaged = false) {
  if (!object(document) || document.contract_version !== "1.0" || document.application !== appKey ||
      (sourceManaged && document.managed_by !== "application")) fail("Connector manifest is invalid");
  if (!Array.isArray(document.modules) || document.modules.length > 100 ||
      (!sourceManaged && !document.modules.length)) fail("Manifest modules are invalid");
  const seenModules = new Set();
  const seenTools = new Set();
  const modules = document.modules.map((raw) => {
    if (!object(raw) || typeof raw.key !== "string" || !/^[a-z][a-z0-9_]{0,62}$/.test(raw.key) ||
        seenModules.has(raw.key)) fail("Module key is invalid");
    seenModules.add(raw.key);
    const operations = raw.supported_operations ?? [];
    if (!Array.isArray(operations) || operations.some((op) => !["read", "create", "update", "delete"].includes(op))) fail("Module operations are invalid");
    const readable = raw.readable_fields ?? [];
    const writable = raw.writable_fields ?? [];
    for (const fields of [readable, writable]) {
      if (!Array.isArray(fields) || fields.length > 100 || new Set(fields).size !== fields.length ||
          fields.some((field) => typeof field !== "string" || !/^[A-Za-z][A-Za-z0-9_]{0,62}$/.test(field))) fail("Module fields are invalid");
    }
    const page = raw.max_page_size ?? 50;
    if (!Number.isInteger(page) || page < 1 || page > 50) fail("Module page limit is invalid");
    if (!Array.isArray(raw.read_endpoints ?? []) || !Array.isArray(raw.write_endpoints ?? []) ||
        (raw.read_endpoints ?? []).length > 100 || (raw.write_endpoints ?? []).length > 50) fail("Endpoint list is invalid");
    const reads = (raw.read_endpoints ?? []).map((item) => endpoint(item, readable, writable, page, operations, false));
    const writes = (raw.write_endpoints ?? []).map((item) => endpoint(item, readable, writable, page, operations, true));
    const seenRoutes = new Set();
    for (const route of [...reads, ...writes]) {
      if (!route.tool_key.startsWith(`${appKey}.${raw.key}.`) || seenTools.has(route.tool_key)) fail("Tool key is outside source module");
      const key = `${route.method} ${route.path_template}`;
      if (seenRoutes.has(key)) fail("Duplicate source endpoint");
      seenRoutes.add(key);
      seenTools.add(route.tool_key);
    }
    const policies = object(raw.field_policies) ? raw.field_policies : {};
    const entry = { key: raw.key, name: String(raw.name || raw.key).slice(0, 200),
      description: String(raw.description || "").slice(0, 500),
      schema_version: String(raw.schema_version || "1.0").slice(0, 32),
      supported_operations: [...operations], readable_fields: [...readable], writable_fields: [...writable],
      filters: object(raw.filters) ? raw.filters : {}, max_page_size: page,
      risk: object(raw.risk) ? raw.risk : {}, field_policies: policies,
      enableable_operations: ["read", "create", "update", "delete"].filter((op) =>
        operations.includes(op) && (op === "read" || writes.some((route) => route.operation === op))),
      read_endpoints: reads };
    if (writes.length) entry.write_endpoints = writes;
    return entry;
  });
  const result = { contract_version: "1.0", application: appKey,
    manifest_version: String(document.manifest_version || "unversioned").slice(0, 64), modules };
  result.manifest_hash = digest({ application: appKey, modules });
  if (sourceManaged) result.managed_by = "application";
  return result;
}
