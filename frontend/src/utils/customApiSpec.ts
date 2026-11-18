/** The visual editor's model of a custom API endpoint list, and its conversion to and from the saved JSON. */

export type FieldType = "string" | "integer" | "number" | "boolean";
export const FIELD_TYPES: FieldType[] = ["string", "integer", "number", "boolean"];

export interface Field { name: string; type: FieldType; nullable: boolean; maxLength: number | null }
export interface Param { name: string; type: FieldType; required: boolean; test: string }
export interface Header { name: string; value: string }
export interface Endpoint {
  name: string;
  path: string;
  result_path: string;
  description: string;
  params: Param[];
  headers: Header[];
}
export interface Resource { key: string; name: string; description: string; alias: string; fields: Field[]; endpoints: Endpoint[] }
export interface UserAuth { enabled: boolean; login_path: string; fields: string; token_path: string; me_path: string; name_path: string }
export interface Model { userAuth: UserAuth; resources: Resource[]; authHeader: string | null }

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, fallback = ""): string => (typeof value === "string" ? value : fallback);
const fieldType = (value: unknown): FieldType => (FIELD_TYPES.includes(value as FieldType) ? (value as FieldType) : "string");

export const slug = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);

export function emptyEndpoint(): Endpoint {
  return { name: "", path: "/", result_path: "", description: "", params: [], headers: [] };
}

export function emptyResource(): Resource {
  return { key: "", name: "", description: "", alias: "", fields: [{ name: "id", type: "integer", nullable: false, maxLength: null }],
           endpoints: [emptyEndpoint()] };
}

function fieldFrom(name: string, raw: unknown): Field {
  const spec = isObject(raw) ? raw : { type: raw };
  const kind = text(spec.type, "string");
  return { name, type: fieldType(kind.replace(/\?$/, "")), nullable: kind.endsWith("?"),
           maxLength: typeof spec.maxLength === "number" ? spec.maxLength : null };
}

export function fromSpec(spec: unknown): Model {
  const root = isObject(spec) ? spec : {};
  const auth = isObject(root.user_auth) ? root.user_auth : null;
  const fieldsRaw = auth && Array.isArray(auth.fields) ? auth.fields.filter((item): item is string => typeof item === "string") : ["email", "password"];
  const resources: Resource[] = Object.entries(isObject(root.resources) ? root.resources : {}).map(([key, value]) => {
    const body = isObject(value) ? value : {};
    const fields = Object.entries(isObject(body.fields) ? body.fields : {}).map(([name, raw]) => fieldFrom(name, raw));
    const endpoints = (Array.isArray(body.endpoints) ? body.endpoints : []).filter(isObject).map((item): Endpoint => {
      const required = new Set(Array.isArray(item.required) ? item.required.map(String) : []);
      const rawParams = item.params;
      const entries: [string, unknown][] = Array.isArray(rawParams) ? rawParams.map((name) => [String(name), "string"])
        : Object.entries(isObject(rawParams) ? rawParams : {});
      const headers = isObject(item.headers) ? Object.entries(item.headers).map(([name, value]) => ({ name, value: text(value) })) : [];
      return { name: text(item.name), path: text(item.path, "/"), result_path: text(item.result_path), description: text(item.description),
               params: entries.map(([name, type]) => ({ name, type: fieldType(type), required: required.has(name), test: "" })), headers };
    });
    const alias = Array.isArray(body.alias) ? body.alias.map(String).join(", ") : "";
    return { key, name: text(body.name), description: text(body.description), alias, fields, endpoints };
  });
  return {
    userAuth: { enabled: !!auth, login_path: auth ? text(auth.login_path, "/api/login") : "/api/login", fields: fieldsRaw.join(", "),
                token_path: auth ? text(auth.token_path, "token") : "token", me_path: auth ? text(auth.me_path, "/api/me") : "/api/me",
                name_path: auth ? text(auth.name_path, "name") : "name" },
    resources,
    authHeader: typeof root.auth_header === "string" ? root.auth_header : null,
  };
}

const words = (value: string): string[] => value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);

export function toSpec(model: Model): Json {
  const resources: Json = {};
  for (const resource of model.resources) {
    const fields: Json = {};
    for (const field of resource.fields.filter((item) => item.name.trim())) {
      const type = field.type + (field.nullable ? "?" : "");
      fields[field.name.trim()] = field.type === "string" && field.maxLength ? { type, maxLength: field.maxLength } : type;
    }
    const endpoints = resource.endpoints.map((endpoint) => {
      const params: Json = {};
      for (const param of endpoint.params.filter((item) => item.name.trim())) params[param.name.trim()] = param.type;
      const required = endpoint.params.filter((item) => item.required && item.name.trim()).map((item) => item.name.trim());
      const headers: Json = {};
      for (const header of endpoint.headers.filter((item) => item.name.trim())) headers[header.name.trim()] = header.value;
      const out: Json = { name: endpoint.name.trim(), path: endpoint.path.trim() };
      if (endpoint.result_path.trim()) out.result_path = endpoint.result_path.trim();
      if (endpoint.description.trim()) out.description = endpoint.description.trim();
      if (Object.keys(params).length) out.params = params;
      if (required.length) out.required = required;
      if (Object.keys(headers).length) out.headers = headers;
      return out;
    });
    const body: Json = { name: resource.name.trim() || resource.key, fields, endpoints };
    if (resource.description.trim()) body.description = resource.description.trim();
    if (words(resource.alias).length) body.alias = resource.alias.split(",").map((item) => item.trim()).filter(Boolean);
    resources[resource.key.trim()] = body;
  }
  const spec: Json = { resources };
  if (model.userAuth.enabled) {
    const auth: Json = { login_path: model.userAuth.login_path.trim(), fields: words(model.userAuth.fields),
                         token_path: model.userAuth.token_path.trim() || "token" };
    if (model.userAuth.me_path.trim()) {
      auth.me_path = model.userAuth.me_path.trim();
      auth.name_path = model.userAuth.name_path.trim() || "name";
    }
    spec.user_auth = auth;
  }
  if (model.authHeader) spec.auth_header = model.authHeader;
  return spec;
}

/** What the visual editor can check before sending, so most mistakes show next to the field. */
export function problems(model: Model): string[] {
  const out: string[] = [];
  const keys = new Set<string>();
  if (!model.resources.length) out.push("Add at least one endpoint.");
  for (const resource of model.resources) {
    const label = resource.name || resource.key || "New endpoint";
    if (!resource.name.trim() && !resource.key.trim()) out.push("Give every endpoint a name.");
    else if (!/^[a-z][a-z0-9_]{0,39}$/.test(resource.key)) out.push(`${label}: the name makes the key: start with a letter and use letters, digits or underscores.`);
    if (keys.has(resource.key)) out.push(`${label}: the key is used twice.`);
    keys.add(resource.key);
    if (!resource.fields.some((field) => field.name.trim())) out.push(`${label}: click Send, or add, at least one field AI may see.`);
    const names = new Set<string>();
    for (const endpoint of resource.endpoints) {
      const where = `${label} / ${endpoint.name || "endpoint"}`;
      if (!/^[a-z][a-z0-9_]{0,39}$/.test(endpoint.name)) out.push(`${where}: the name must be lowercase letters, digits or underscores.`);
      if (names.has(endpoint.name)) out.push(`${where}: the name is used twice.`);
      names.add(endpoint.name);
      if (!endpoint.path.startsWith("/")) out.push(`${label}: the address must start with /.`);
    }
    if (!resource.endpoints.length) out.push(`${label}: add at least one endpoint.`);
  }
  return out;
}
