// Typed client for the admin API. Every call goes through api() for CSRF and error handling.
import { api } from "@/services/api";

export type JsonSchema = {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  maxItems?: number;
  description?: string;
  title?: string;
  additionalProperties?: boolean;
};

export interface Health { status: string; latency_ms: number | null; error_category: string | null; checked_at?: string; created_at?: string; hint?: string | null }

export interface AppSummary {
  id: string;
  app_id: string;
  app_key: string;
  name: string;
  environment: string;
  base_url: string;
  manifest_path: string;
  health_path: string;
  auth_type: string;
  connector_type: "http_contract" | "data_push" | "source_managed";
  source_sync_error?: { code: string; message: string };
  status: "draft" | "active" | "paused" | "archived";
  tls_verify: boolean;
  timeout_ms: number;
  secret_configured: boolean;
  secret_updated_at: string | null;
  failure_count: number;
  circuit_open: boolean;
  health: Health | null;
  contract: { version: string; synced_at: string } | null;
  sources_total: number;
  sources_enabled: number;
  tools_published: number;
  tools_total: number;
  created_at: string;
  delegation_secret?: string;
}

export interface AppDetail extends AppSummary {
  health_history: Health[];
  contracts: { version: string; hash: string; created_at: string; modules: string[] }[];
}

export interface FieldRow { field_path: string; classification: string; baseline: string; source: string; locked: boolean; type: string | null }

export interface Endpoint {
  key: string;
  kind: "read" | "write";
  operation: string;
  method: string;
  path_template: string;
  requires_user_context: boolean;
  public_aggregate: boolean;
  safe_query: boolean;
  tenant_field: string | null;
  input_schema: JsonSchema;
  output_schema: JsonSchema;
  max_items: number | null;
  dataset: boolean;
}

export interface DataSource {
  id: string;
  app_id: string;
  app_key: string;
  app_name: string;
  environment: string;
  connector_id: string | null;
  module_key: string;
  name: string;
  description: string;
  supported_operations: string[];
  enableable_operations: string[];
  operations_enabled: string[];
  enabled: boolean;
  report_endpoint: string | null;
  report_endpoint_effective: string | null;
  report_endpoint_auto: string | null;
  last_synced_at: string;
  tools: number;
  fields: FieldRow[];
  endpoints: Endpoint[];
}

export interface ReportSpec {
  filters?: { field: string; op: string; value?: unknown }[];
  group_by?: string[];
  time_bucket?: { field: string; interval: string } | null;
  metrics?: { fn: string; field?: string }[];
  sort?: { by: string; direction: string } | null;
  limit?: number;
  columns?: string[];
  allow_filters?: boolean;
}

export interface Tool {
  id: string;
  tool_key: string;
  mcp_name: string;
  title: string | null;
  display_title: string;
  description: string;
  template: string;
  operation: string;
  version: string;
  status: "draft" | "published" | "disabled" | "archived";
  stale: boolean;
  tested: boolean;
  source_managed: boolean;
  connector_id: string;
  app_id: string;
  app_key: string;
  app_name: string;
  environment: string;
  module_key: string;
  module_name: string;
  method: string;
  path_template: string;
  input_schema: JsonSchema;
  output_schema: JsonSchema;
  allow_fields: string[];
  report: ReportSpec | null;
  timeout_ms: number;
  max_payload_bytes: number;
  requires_user_context: boolean;
  risk: string;
  last_test: { passed: boolean; mode: string; error_code: string | null; created_at: string; current: boolean } | null;
  mcp_tool: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
  /** Calls over the last days; only on the tool's own page. */
  usage?: ToolUsage;
}

export interface Template { key: string; label: string; operation: string; summary: string }

export interface BuiltinTool { name: string; title: string; description: string; inputSchema: JsonSchema; requires: "memory" | null }

export interface McpTool {
  name: string;
  title?: string;
  description?: string;
  inputSchema: JsonSchema;
  annotations?: { readOnlyHint?: boolean; destructiveHint?: boolean };
}

export interface SkillArgument { name: string; description: string; required: boolean }

export interface Skill {
  id: string;
  key: string;
  title: string;
  description: string;
  instructions: string;
  arguments: SkillArgument[];
  tools: string[];
  enabled: boolean;
  connector_id: string | null;
  app_id: string;
  app_key: string | null;
  app_name: string | null;
  environment: string | null;
  unavailable_tools: string[];
  created_at: string;
  updated_at: string;
}

export type SkillDraft = Pick<Skill, "key" | "title" | "description" | "instructions" | "arguments" | "tools" | "enabled">;

export interface McpPrompt { name: string; title?: string; description?: string; arguments?: SkillArgument[] }

export interface AgentView {
  app: { connector_id: string; app_key: string; name: string; environment: string; status: string };
  key: { id: string | null; name: string; write: boolean; allowed_tools: string[] | null };
  instructions: string;
  memory_enabled: boolean;
  tools: McpTool[];
  prompts: McpPrompt[];
  sync_error: { code: string; message: string } | null;
}

export interface GeneratedTool { id: string; tool_key: string; mcp_name: string; template: string; title: string; module_name: string; status: string; note: string | null }

export interface GeneratedTools {
  /** "source_managed": the app decides its tools and they were re-read from it. */
  mode: "generated" | "source_managed";
  created: GeneratedTool[];
  /** Drafts finished, tools re-tested after a contract change, or tools the app allowed again. */
  repaired: GeneratedTool[];
  skipped: { tool_key: string; reason: string }[];
  unchanged: number;
  published: number;
}

export interface ToolSwitchRow {
  name: string;
  title: string;
  /** hub: list_data_sources and run_report · memory: the memory tools · app: the app's own tools */
  kind: "hub" | "memory" | "app";
  group: string;
  template: string;
  status: string;
  write: boolean;
  /** A full read/write key would see it right now, before switches. */
  live: boolean;
  note: string | null;
  enabled: boolean;
  tool_id?: string;
}

export interface ToolSwitches { tools: ToolSwitchRow[]; total: number; off: number; reaching_ai: number }

export interface ModelProvider {
  id: string;
  key: string;
  name: string;
  base_url: string;
  /** bearer: Authorization header · header: a named header such as api-key · none: local servers */
  auth_style: "bearer" | "header" | "none";
  auth_header: string;
  api_key_set: boolean;
  api_key_hint: string;
  headers: Record<string, string>;
  token_param: "max_tokens" | "max_completion_tokens" | "none";
  tool_schema: "full" | "basic";
  streaming: boolean;
  default_model: string;
  models: string[];
  enabled: boolean;
  status: "untested" | "ok" | "error";
  status_message: string;
  checked_at: string | null;
  used_by: string[];
  ready: boolean;
}

export interface BuiltinProvider { key: string; name: string; ready: boolean; configured_by: string; used_by: string[] }

export interface ProviderPreset {
  key: string;
  name: string;
  base_url: string;
  hint: string;
  auth_style?: ModelProvider["auth_style"];
  auth_header?: string;
  token_param?: ModelProvider["token_param"];
  tool_schema?: ModelProvider["tool_schema"];
  headers?: Record<string, string>;
}

export type ProviderDraft = Partial<Pick<ModelProvider, "key" | "name" | "base_url" | "auth_style" | "auth_header" | "headers"
  | "token_param" | "tool_schema" | "streaming" | "default_model" | "enabled">> & { api_key?: string; clear_api_key?: boolean };

export interface ModelCatalog {
  provider: string;
  models: { id: string; label: string; hint?: string }[];
  /** live: fetched now · cache: fetched in the last few hours · builtin: the recommended Claude models */
  source: "live" | "cache" | "builtin";
  fetched_at: string | null;
  default_model: string;
  error: string | null;
}

export interface ChatSettings {
  enabled: boolean;
  /** "anthropic", "openai_compatible" (the gateway in the Hub's environment) or a provider key. */
  provider: string;
  model: string;
  effort: "low" | "medium" | "high";
  instructions: string;
  welcome_message: string;
  suggestions: string[];
  max_steps: number;
  daily_limit: number;
  /** Claude retries a declined request on a fallback model, server-side. */
  fallbacks: boolean;
  updated_at: string | null;
  options: {
    providers: { id: string; label: string; kind: "anthropic" | "openai_compatible"; ready: boolean; models: string[]; default_model: string }[];
    models: { id: string; label: string; hint: string }[];
    efforts: ChatSettings["effort"][];
    max_steps: [number, number];
    daily_limit: [number, number];
  };
}

export type ChatSettingsUpdate = Partial<Omit<ChatSettings, "fallbacks" | "updated_at" | "options">>;

export interface ChatToolEvent {
  id: string;
  name: string;
  title: string;
  status: "running" | "done" | "error";
  write?: boolean;
  error?: { code: string; message: string };
}

export interface ChatProposal { tool: string; title: string; operation: string | null; data: unknown; trace_id: string }

export interface MemorySettings {
  enabled: boolean;
  retention_days: number;
  max_notes: number;
  max_profile_keys: number;
  retention_choices: number[];
  users: number;
  notes: number;
  profile_entries: number;
  tools: string[];
}

export interface TestResult {
  passed: boolean;
  mode: string;
  trace_id: string;
  duration_ms: number;
  error_code: string | null;
  error_message: string | null;
  preview: Record<string, any> | null;
  checks?: Record<string, boolean>;
  request?: { method: string; path: string; fields: string[]; sent: boolean } | null;
}

export interface ClientKey {
  id: string;
  name: string;
  app_id: string;
  app_key: string | null;
  app_name: string | null;
  environment: string | null;
  write: boolean;
  allowed_tools: string[] | null;
  expires_at: string | null;
  status: "active" | "expired" | "revoked";
  last_used_at: string | null;
  created_at: string;
  token?: string;
}

export interface AdminUserRow { id: string; email: string; role: string; mfa_enabled: boolean; is_active: boolean; app_ids: string[]; created_at: string }

/** A readable name for a tool key: what it does, where it lives, and a link to its page. */
export interface ToolCard {
  tool_id: string | null;
  title: string;
  /** list, count, get, report, create, update, delete, read, hub or memory */
  kind: string;
  app_name: string | null;
  module_name: string | null;
  mcp_name: string;
  status: string;
}

export interface ToolUsage {
  days: number;
  calls: number;
  success: number;
  denied: number;
  failed: number;
  success_rate: number | null;
  p95_ms: number | null;
  avg_ms: number | null;
  last_used_at: string | null;
  series: { day: string; calls: number; failed: number }[];
}

export interface AuditRow {
  trace_id: string;
  action: string;
  actor_ref: string;
  app_key: string | null;
  module_key: string | null;
  tool_key: string | null;
  environment: string | null;
  result: string;
  error_code: string | null;
  duration_ms: number | null;
  retry_count: number;
  created_at: string;
  /** Set for events about a tool. */
  tool?: ToolCard | null;
}

export interface CallPoint { start: string; calls: number; failed: number }

export interface Overview {
  apps_total: number;
  connectors_active: number;
  connectors_failing: number;
  modules_enabled: number;
  tools_published: number;
  tools_draft: number;
  keys_active: number;
  executions: number;
  success: number;
  denied: number;
  failure: number;
  success_rate: number | null;
  latency_p95_ms: number;
  retries: number;
  top_tools: { tool_key: string; calls: number; tool?: ToolCard | null }[];
  /** Missing from Hub servers older than this admin UI. */
  series?: CallPoint[];
  recent: AuditRow[];
  checklist: { app_connected: boolean; source_enabled: boolean; tool_published: boolean; key_created: boolean };
}

export interface SystemInfo {
  version: string;
  environment: string;
  mcp_url: string;
  limits: Record<string, number>;
  security: Record<string, boolean>;
}

const json = (body: unknown) => ({ body: JSON.stringify(body) });
const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", ...(body === undefined ? {} : json(body)) });
const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", ...json(body) });
const remove = <T>(path: string) => api<T>(path, { method: "DELETE" });

export const hub = {
  overview: (period: string) => api<Overview>(`/dashboard?period=${period}`),
  system: () => api<SystemInfo>("/system"),

  apps: () => api<AppSummary[]>("/connectors"),
  app: (id: string) => api<AppDetail>(`/connectors/${id}`),
  createApp: (body: Record<string, unknown>) => post<AppSummary>("/connectors", body),
  updateApp: (id: string, body: Record<string, unknown>) => patch<AppSummary>(`/connectors/${id}`, body),
  deleteApp: (id: string) => remove(`/connectors/${id}`),
  testApp: (id: string) => post<Health>(`/connectors/${id}/test`),
  syncApp: (id: string) => post<{ modules: { id: string; module_key: string; name: string; change: string; enabled: boolean }[] }>(`/connectors/${id}/discover`),
  appAction: (id: string, action: "activate" | "pause" | "archive") => post<AppSummary>(`/connectors/${id}/${action}`),
  rotateSecret: (id: string, body: { secret?: string; delegation_secret?: string }) => post(`/connectors/${id}/rotate`, body),

  sources: (connectorId?: string) => api<DataSource[]>(`/modules${connectorId ? `?connector_id=${connectorId}` : ""}`),
  updateSource: (id: string, body: Record<string, unknown>) => patch<DataSource>(`/modules/${id}/settings`, body),

  tools: () => api<Tool[]>("/tools"),
  tool: (id: string) => api<Tool>(`/tools/${id}`),
  templates: () => api<Template[]>("/tools/templates"),
  builtins: () => api<BuiltinTool[]>("/tools/builtins"),
  createTool: (body: Record<string, unknown>) => post<Tool>("/tools", body),
  updateTool: (id: string, body: Record<string, unknown>) => patch<Tool>(`/tools/${id}`, body),
  deleteTool: (id: string) => remove(`/tools/${id}`),
  testTool: (id: string, body: Record<string, unknown>) => post<TestResult>(`/tools/${id}/test`, body),
  publishTool: (id: string) => post<Tool>(`/tools/${id}/publish`),
  disableTool: (id: string) => post<Tool>(`/tools/${id}/disable`),
  testBuiltin: (name: string, body: Record<string, unknown>) => post<TestResult>(`/tools/builtins/${name}/test`, body),
  generateTools: (body: { connector_id: string; publish: boolean }) => post<GeneratedTools>("/tools/generate", body),
  agentView: (connectorId: string, options: { keyId?: string; write?: boolean }) => api<AgentView>(
    `/tools/agent-view?${new URLSearchParams({ connector_id: connectorId, ...(options.keyId ? { key_id: options.keyId } : {}),
                                               write: String(Boolean(options.write)) }).toString()}`),

  skills: (connectorId?: string) => api<Skill[]>(`/skills${connectorId ? `?connector_id=${encodeURIComponent(connectorId)}` : ""}`),
  skillTemplates: () => api<SkillDraft[]>("/skills/templates"),
  createSkill: (body: SkillDraft & { connector_id: string }) => post<Skill>("/skills", body),
  updateSkill: (id: string, body: Partial<SkillDraft>) => patch<Skill>(`/skills/${id}`, body),
  deleteSkill: (id: string) => remove(`/skills/${id}`),
  previewSkill: (body: { connector_id: string; skill: SkillDraft; arguments: Record<string, string> }) =>
    post<{ text: string }>("/skills/preview", body),

  memory: (connectorId: string) => api<MemorySettings>(`/connectors/${connectorId}/memory`),
  updateMemory: (connectorId: string, body: Partial<Pick<MemorySettings, "enabled" | "retention_days" | "max_notes">>) =>
    patch<MemorySettings>(`/connectors/${connectorId}/memory`, body),
  purgeMemory: (connectorId: string) => remove<{ removed: number }>(`/connectors/${connectorId}/memory`),

  toolSwitches: (connectorId: string) => api<ToolSwitches>(`/connectors/${connectorId}/tool-switches`),
  updateToolSwitches: (connectorId: string, tools: Record<string, boolean>) =>
    api<ToolSwitches>(`/connectors/${connectorId}/tool-switches`, { method: "PUT", body: JSON.stringify({ tools }) }),
  providers: () => api<{ builtin: BuiltinProvider[]; providers: ModelProvider[] }>("/model-providers"),
  providerPresets: () => api<ProviderPreset[]>("/model-providers/presets"),
  createProvider: (body: ProviderDraft) => post<ModelProvider>("/model-providers", body),
  updateProvider: (id: string, body: ProviderDraft) => patch<ModelProvider>(`/model-providers/${id}`, body),
  testProvider: (id: string) => post<ModelProvider>(`/model-providers/${id}/test`),
  providerModels: (key: string, refresh = false) =>
    api<ModelCatalog>(`/model-providers/${encodeURIComponent(key)}/models${refresh ? "?refresh=true" : ""}`),
  deleteProvider: (id: string) => remove(`/model-providers/${id}`),
  chat: (connectorId: string) => api<ChatSettings>(`/connectors/${connectorId}/chat`),
  updateChat: (connectorId: string, body: ChatSettingsUpdate) => patch<ChatSettings>(`/connectors/${connectorId}/chat`, body),

  keys: (appId?: string) => api<ClientKey[]>(`/service-identities${appId ? `?app_id=${encodeURIComponent(appId)}` : ""}`),
  createKey: (body: Record<string, unknown>) => post<ClientKey>("/service-identities", body),
  updateKey: (id: string, body: Record<string, unknown>) => patch<ClientKey>(`/service-identities/${id}`, body),
  revokeKey: (id: string) => post(`/service-identities/${id}/revoke`),

  users: () => api<AdminUserRow[]>("/users"),
  createUser: (body: Record<string, unknown>) => post<AdminUserRow>("/users", body),
  updateUser: (id: string, body: Record<string, unknown>) => patch<AdminUserRow>(`/users/${id}`, body),

  activity: (query: URLSearchParams) => api<AuditRow[]>(`/executions?${query.toString()}`),
  exportBackup: () => post<unknown>("/operations/export"),
  importBackup: (document: unknown) => post<Record<string, number>>("/operations/import", document),
  purge: () => post<{ removed: Record<string, number> }>("/operations/purge"),
};
