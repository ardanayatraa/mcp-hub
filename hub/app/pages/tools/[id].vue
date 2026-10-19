<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "#imports";

import CodeBlock from "@/components/CodeBlock.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import CopyButton from "@/components/CopyButton.vue";
import UsageBars from "@/components/UsageBars.vue";
import ParamEditor from "@/components/ParamEditor.vue";
import ReportBuilder from "@/components/ReportBuilder.vue";
import ResultView from "@/components/ResultView.vue";
import SchemaForm from "@/components/SchemaForm.vue";
import { hub, type DataSource, type JsonSchema, type ReportSpec, type TestResult, type Tool } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { badgeClass, errorMessage, prettyJson, templateInfo, timeAgo, toolStatus } from "@/utils/format";
import { reportFields, visibleFieldNames } from "@/utils/sources";
import { kindStyle, toolKind } from "@/utils/toolKinds";

const route = useRoute();
const router = useRouter();
const session = useSession();
const toast = useToast();
const id = String(route.params.id);
const tool = ref<Tool | null>(null);
const source = ref<DataSource | undefined>();
const busy = ref(false);
const mode = ref<"sample" | "live">("sample");
const args = ref<Record<string, unknown>>({});
const tenant = ref("sample_tenant");
const delegation = ref("");
const result = ref<TestResult | null>(null);
const editing = ref(false);
const confirmDelete = ref(false);
const form = ref({ title: "", description: "", timeout_ms: 5000 });
const editSchema = ref<JsonSchema | null>(null);
const editFields = ref<string[]>([]);
const editReport = ref<ReportSpec>({});

const CHECKS: Record<string, string> = {
  unknown_input_rejected: "Unknown arguments are rejected",
  invalid_output_rejected: "Malformed responses are rejected",
  pii_rejected: "Emails and phone numbers are blocked",
  numeric_pii_rejected: "ID-like numbers are blocked",
  pii_masked: "Emails and phone numbers are hidden",
  numeric_pii_masked: "ID-like numbers are hidden",
};

async function load() {
  try {
    tool.value = await hub.tool(id);
    source.value = (await hub.sources(tool.value.connector_id)).find((item) => item.module_key === tool.value?.module_key);
  } catch (exc) {
    toast.error(errorMessage(exc));
  }
}
onMounted(load);

const isWrite = computed(() => ["create", "update", "delete"].includes(tool.value?.template ?? ""));
const kind = computed(() => kindStyle(tool.value ? toolKind(tool.value.template, tool.value.tool_key) : null));
const successTone = computed(() => {
  const rate = tool.value?.usage?.success_rate;
  return rate === null || rate === undefined ? "" : rate >= 0.95 ? "text-ok" : rate >= 0.8 ? "text-warn" : "text-bad";
});
// Parameters as people read them: "status: open | done", "limit: 1–50".
const parameters = computed(() => {
  const schema = tool.value?.input_schema;
  const required = new Set(schema?.required ?? []);
  return Object.entries(schema?.properties ?? {}).map(([name, raw]) => {
    const prop = raw as { type?: string | string[]; enum?: unknown[]; minimum?: number; maximum?: number; maxLength?: number };
    const type = Array.isArray(prop.type) ? prop.type.filter((item) => item !== "null").join(" | ") : prop.type ?? "any";
    const detail = prop.enum ? prop.enum.join(" | ")
      : prop.minimum !== undefined || prop.maximum !== undefined ? `${prop.minimum ?? ""}–${prop.maximum ?? ""}` : type;
    return { name, detail, required: required.has(name) };
  });
});
const route_ = computed(() => source.value?.endpoints.find((item) => item.method === tool.value?.method && item.path_template === tool.value?.path_template));
const liveBlocked = computed(() => isWrite.value ? "Write tools are only tested with sample data; nothing is sent to the app." : "");
const next = computed(() => {
  const value = tool.value;
  if (!value) return null;
  if (value.source_managed) return { tone: value.status === "published" ? "ok" : "neutral", text: `Managed automatically by ${value.app_name}. Change access in the application.` };
  if (value.status === "published" && value.stale) return { tone: "warn", text: "The app's contract changed. Run a test against the new contract, then publish again." };
  if (value.status === "published") return { tone: "ok", text: `Live. Client keys with access see it as ${value.mcp_name}.` };
  if (value.status === "disabled") return { tone: "neutral", text: "Disabled: AI clients cannot see or call it. Publish to turn it back on." };
  if (value.tested) return { tone: "brand", text: "The latest test passed. Publish to make it available to AI clients." };
  return { tone: "brand", text: "Draft. Run a test with sample data to check it, then publish." };
});

async function runTest() {
  if (!tool.value) return;
  busy.value = true;
  result.value = null;
  try {
    const body: Record<string, unknown> = { mode: mode.value, arguments: args.value };
    if (mode.value === "sample") body.tenant_id = tenant.value || "sample_tenant";
    else if (delegation.value) body.delegation = delegation.value;
    result.value = await hub.testTool(tool.value.id, body);
    tool.value = await hub.tool(id);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function act(task: () => Promise<Tool>, message: string) {
  busy.value = true;
  try {
    tool.value = await task();
    toast.ok(message);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

function publish() {
  if (tool.value) void act(() => hub.publishTool(id), "Published: AI clients can use it now");
}

function disable() {
  if (tool.value) void act(() => hub.disableTool(id), "Tool disabled");
}

function openEdit() {
  if (!tool.value) return;
  form.value = { title: tool.value.title ?? "", description: tool.value.description, timeout_ms: tool.value.timeout_ms };
  editSchema.value = tool.value.input_schema;
  editFields.value = [...tool.value.allow_fields];
  editReport.value = { ...(tool.value.report ?? {}) };
  editing.value = true;
}

async function saveEdit() {
  if (!tool.value) return;
  const wasLive = tool.value.status === "published";
  const body: Record<string, unknown> = { title: form.value.title || null, description: form.value.description, timeout_ms: form.value.timeout_ms };
  if (tool.value.template === "report") body.report = editReport.value;
  else Object.assign(body, { input_schema: editSchema.value, allow_fields: editFields.value });
  busy.value = true;
  try {
    tool.value = await hub.updateTool(tool.value.id, body);
    editing.value = false;
    result.value = null;
    toast.ok(wasLive && tool.value.status === "draft" ? "Saved. The tool is offline until you test and publish it again." : "Saved");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function remove() {
  if (!tool.value) return;
  busy.value = true;
  try {
    await hub.deleteTool(tool.value.id);
    toast.ok("Tool deleted");
    await router.push("/tools");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

function toggleField(field: string) {
  editFields.value = editFields.value.includes(field) ? editFields.value.filter((item) => item !== field) : [...editFields.value, field];
}
</script>

<template>
  <template v-if="tool">
    <RouterLink to="/tools" class="mb-3 inline-flex items-center gap-1 text-xs font-medium text-subtle hover:text-ink">
      <AppIcon name="chevron-left" :size="14" /> Tools</RouterLink>

    <section class="card mb-6 overflow-hidden">
      <div class="flex flex-wrap items-start gap-5 p-6">
        <span class="grid h-14 w-14 shrink-0 place-items-center rounded-xl" :class="kind.tile"><AppIcon :name="kind.icon" :size="26" /></span>
        <div class="min-w-0 flex-1">
          <p class="text-xs font-medium uppercase tracking-wide text-subtle">{{ kind.label }} tool</p>
          <h1 class="mt-0.5 text-2xl font-semibold tracking-tight text-ink">{{ tool.display_title }}</h1>
          <p class="mt-1 max-w-2xl text-sm text-subtle">{{ tool.description }}</p>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <RouterLink :to="`/apps/${tool.connector_id}`" class="badge-outline gap-1.5 hover:bg-muted"><AppIcon name="apps" :size="12" /> {{ tool.app_name }}</RouterLink>
            <RouterLink :to="`/apps/${tool.connector_id}?source=${tool.module_key}`" class="badge-outline gap-1.5 hover:bg-muted">
              <AppIcon name="database" :size="12" /> {{ tool.module_name }}</RouterLink>
            <span :class="badgeClass(toolStatus(tool).tone)">{{ toolStatus(tool).label }}</span>
            <span v-if="tool.source_managed" class="badge-neutral gap-1"><AppIcon name="refresh" :size="12" /> Follows {{ tool.app_name }}</span>
            <span v-if="isWrite" class="badge-warn">Asks the user to confirm</span>
          </div>
          <p class="mt-3 flex flex-wrap items-center gap-2 text-xs text-subtle">
            <span>Name for AI clients</span><code class="code">{{ tool.mcp_name }}</code><CopyButton :text="tool.mcp_name" />
          </p>
        </div>
        <div v-if="session.canWrite && !tool.source_managed && tool.status !== 'archived'" class="flex flex-wrap gap-2">
          <button class="btn-secondary" type="button" :disabled="busy" @click="openEdit"><AppIcon name="pencil" :size="16" /> Edit</button>
          <button v-if="tool.status === 'published' && !tool.stale" class="btn-secondary" type="button" :disabled="busy"
                  @click="disable"><AppIcon name="pause" :size="16" /> Disable</button>
          <button v-else class="btn-primary" type="button" :disabled="busy || !tool.tested"
                  :title="tool.tested ? '' : 'Run a passing test first'"
                  @click="publish"><AppIcon name="bolt" :size="16" /> Publish</button>
          <button v-if="tool.status !== 'published'" class="btn-ghost" type="button" title="Delete" @click="confirmDelete = true"><AppIcon name="trash" :size="16" /></button>
        </div>
      </div>
      <div v-if="next" class="flex items-start gap-2.5 border-t px-6 py-3 text-sm"
           :class="{ ok: 'border-ok/20 bg-ok-soft', warn: 'border-warn/30 bg-warn-soft', brand: 'border-brand/20 bg-brand-soft', neutral: 'border-line bg-muted/60' }[next.tone]">
        <AppIcon :name="next.tone === 'ok' ? 'check' : next.tone === 'warn' ? 'alert' : 'info'" :size="16" class="mt-0.5 shrink-0" />
        <p class="text-ink">{{ next.text }}</p>
      </div>
      <dl v-if="tool.usage" class="grid grid-cols-2 border-t border-line lg:grid-cols-4">
        <div class="border-b border-r border-line p-5 lg:border-b-0">
          <dt class="text-xs text-subtle">Calls, last {{ tool.usage.days }} days</dt>
          <dd class="mt-1 flex items-end justify-between gap-3">
            <span class="text-2xl font-semibold tabular-nums">{{ tool.usage.calls.toLocaleString() }}</span>
            <UsageBars :series="tool.usage.series" class="w-28" />
          </dd>
        </div>
        <div class="border-b border-line p-5 lg:border-b-0 lg:border-r">
          <dt class="text-xs text-subtle">Success rate</dt>
          <dd class="mt-1 text-2xl font-semibold tabular-nums" :class="successTone">{{ tool.usage.success_rate === null ? "–" : `${Math.round(tool.usage.success_rate * 100)}%` }}</dd>
          <p class="text-xs text-subtle">{{ tool.usage.calls ? `${tool.usage.denied} denied · ${tool.usage.failed - tool.usage.denied} errors` : "No calls yet" }}</p>
        </div>
        <div class="border-r border-line p-5">
          <dt class="text-xs text-subtle">Response time</dt>
          <dd class="mt-1 text-2xl font-semibold tabular-nums">{{ tool.usage.avg_ms === null ? "–" : tool.usage.avg_ms }}<span v-if="tool.usage.avg_ms !== null" class="ml-0.5 text-sm font-normal text-subtle">ms</span></dd>
          <p class="text-xs text-subtle">{{ tool.usage.p95_ms === null ? "Average per call" : `average · p95 ${tool.usage.p95_ms} ms` }}</p>
        </div>
        <div class="p-5">
          <dt class="text-xs text-subtle">Last used</dt>
          <dd class="mt-1 text-2xl font-semibold">{{ tool.usage.last_used_at ? timeAgo(tool.usage.last_used_at) : "Never" }}</dd>
          <RouterLink :to="`/activity?search=${encodeURIComponent(tool.tool_key)}`" class="link text-xs">See its calls</RouterLink>
        </div>
      </dl>
    </section>

    <div class="grid gap-6 xl:grid-cols-5">
      <section class="card min-w-0 xl:col-span-3">
        <header class="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
          <h2 class="section-title">Test</h2>
          <div class="flex rounded-lg border border-line p-0.5" role="group" aria-label="Test data">
            <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium" :class="mode === 'sample' ? 'bg-brand-soft text-brand' : 'text-subtle'"
                    @click="mode = 'sample'">Sample data</button>
            <button type="button" class="rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-40"
                    :class="mode === 'live' ? 'bg-brand-soft text-brand' : 'text-subtle'" :disabled="isWrite" :title="liveBlocked"
                    @click="mode = 'live'">Live data</button>
          </div>
        </header>
        <div class="space-y-4 p-5">
          <p class="text-xs text-subtle">
            <template v-if="mode === 'sample'">Generated records shaped like the app's response run through the same checks as a real call. No request is sent.</template>
            <template v-else>Calls the app for real. User-scoped routes need a delegation token signed by the app; production apps allow live tests only for public aggregates.</template>
          </p>
          <SchemaForm v-model="args" :schema="tool.input_schema" />
          <label v-if="mode === 'live' && tool.requires_user_context" class="block"><span class="label">Delegation token from the app</span>
            <input v-model="delegation" class="input font-mono text-xs" type="password" autocomplete="off" /></label>
          <button class="btn-primary" type="button" :disabled="busy || !session.canWrite" @click="runTest"><AppIcon name="play" :size="16" /> Run test</button>

          <div v-if="result" class="space-y-4 border-t border-line pt-4">
            <div class="flex items-start gap-3 rounded-lg p-3" :class="result.passed ? 'bg-ok-soft' : 'bg-bad-soft'">
              <AppIcon :name="result.passed ? 'check' : 'alert'" :class="result.passed ? 'text-ok' : 'text-bad'" class="mt-0.5" />
              <div class="min-w-0 text-sm">
                <p class="font-medium text-ink">{{ result.passed ? "Test passed" : "Test failed" }} <span class="font-normal text-subtle">· {{ result.duration_ms }} ms</span></p>
                <p v-if="result.error_message" class="text-ink">{{ result.error_code }}: {{ result.error_message }}</p>
                <p class="font-mono text-xs text-subtle">trace {{ result.trace_id }}</p>
              </div>
            </div>
            <ul v-if="result.checks && Object.keys(result.checks).length" class="grid gap-1.5 sm:grid-cols-2">
              <li v-for="(passed, key) in result.checks" :key="key" class="flex items-center gap-2 text-xs">
                <AppIcon :name="passed ? 'check' : 'x'" :size="14" :class="passed ? 'text-ok' : 'text-bad'" /> {{ CHECKS[key] ?? key }}
              </li>
            </ul>
            <div v-if="result.request" class="rounded-lg border border-line p-3 text-xs">
              <p class="mb-1 font-medium">Request the Hub would send (dry run)</p>
              <p class="font-mono">{{ result.request.method }} {{ result.request.path }} <span class="text-subtle">fields: {{ result.request.fields.join(", ") || "none" }}</span></p>
            </div>
            <ResultView v-if="result.preview" :result="result.preview" />
          </div>
        </div>
      </section>

      <aside class="min-w-0 space-y-6 xl:col-span-2">
        <section class="card card-pad space-y-5">
          <div>
            <h2 class="section-title">What it takes</h2>
            <div v-if="parameters.length" class="mt-2 flex flex-wrap gap-2">
              <span v-for="param in parameters" :key="param.name" class="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs">
                <span class="font-mono font-medium">{{ param.name }}</span><span class="text-subtle">{{ param.detail }}</span>
                <span v-if="param.required" class="text-bad" title="Required">*</span></span>
            </div>
            <p v-else class="mt-1 text-sm text-subtle">No parameters: the AI just calls it.</p>
          </div>
          <div v-if="tool.template !== 'report'">
            <h2 class="section-title">What it returns</h2>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <span v-for="field in tool.allow_fields" :key="field" class="badge-neutral font-mono">{{ field }}</span>
              <span v-if="!tool.allow_fields.length" class="text-sm text-subtle">Nothing</span>
            </div>
          </div>
          <div v-else>
            <h2 class="section-title">Report</h2>
            <dl class="mt-2 grid grid-cols-[6rem_1fr] gap-y-1.5 text-xs">
              <dt class="text-subtle">Groups</dt><dd>{{ [...(tool.report?.group_by ?? []), tool.report?.time_bucket ? `${tool.report.time_bucket.field} by ${tool.report.time_bucket.interval}` : ""].filter(Boolean).join(", ") || "none" }}</dd>
              <dt class="text-subtle">Metrics</dt><dd>{{ (tool.report?.metrics ?? []).map((m) => m.fn === "count" ? "count" : `${m.fn}(${m.field})`).join(", ") || "count" }}</dd>
              <dt class="text-subtle">AI filters</dt><dd>{{ tool.report?.allow_filters === false ? "not allowed" : "allowed" }}</dd>
            </dl>
          </div>
          <dl class="grid grid-cols-[7rem_1fr] gap-y-2 border-t border-line pt-4 text-xs">
            <dt class="text-subtle">Route</dt><dd class="font-mono">{{ tool.method }} {{ tool.path_template }}</dd>
            <dt class="text-subtle">Signed-in user</dt><dd>{{ tool.requires_user_context ? "Required: only that user's data" : "Not needed (public totals)" }}</dd>
            <dt class="text-subtle">Timeout</dt><dd>{{ tool.timeout_ms }} ms</dd>
            <dt class="text-subtle">Version</dt><dd>v{{ tool.version }} · changed {{ timeAgo(tool.updated_at ?? tool.created_at) }}</dd>
          </dl>
        </section>
        <details class="card card-pad">
          <summary class="cursor-pointer section-title">How the AI sees this tool</summary>
          <p class="mb-3 mt-1 text-xs text-subtle">The exact definition clients receive from tools/list.</p>
          <CodeBlock :code="prettyJson(tool.mcp_tool)" max-height="20rem" />
        </details>
      </aside>
    </div>

    <ModalDialog v-if="editing" title="Edit tool" wide @close="editing = false">
      <div class="space-y-4">
        <p v-if="tool.status === 'published'" class="rounded-lg bg-warn-soft px-3 py-2 text-xs text-ink">
          Saving changes takes this live tool offline until it passes a test and is published again.</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <label><span class="label">Display title</span><input v-model="form.title" class="input" maxlength="120" /></label>
          <label><span class="label">Timeout (ms)</span><input v-model.number="form.timeout_ms" class="input" type="number" min="100" max="30000" /></label>
        </div>
        <label class="block"><span class="label">Description for the AI</span><textarea v-model="form.description" class="input" rows="2" maxlength="300" /></label>
        <template v-if="tool.template === 'report'">
          <ReportBuilder v-model="editReport" :fields="reportFields(source)" saved />
        </template>
        <template v-else-if="route_">
          <div>
            <p class="label">Parameters</p>
            <ParamEditor v-model="editSchema" :route="route_.input_schema" />
          </div>
          <div>
            <p class="label">Fields returned</p>
            <div class="flex flex-wrap gap-2">
              <button v-for="field in Object.keys(route_.output_schema.items?.properties ?? {})" :key="field" type="button" class="badge border"
                      :disabled="!isWrite && !visibleFieldNames(source).has(field)"
                      :class="editFields.includes(field) ? 'border-brand bg-brand-soft text-brand' : 'border-line text-subtle'"
                      @click="toggleField(field)">{{ field }}</button>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <button class="btn-secondary" type="button" @click="editing = false">Cancel</button>
        <button class="btn-primary" type="button" :disabled="busy" @click="saveEdit">Save</button>
      </template>
    </ModalDialog>

    <ModalDialog v-if="confirmDelete" title="Delete this tool?" @close="confirmDelete = false">
      <p class="text-sm text-subtle">The tool and its test history are removed. Audit records are kept.</p>
      <template #footer>
        <button class="btn-secondary" type="button" @click="confirmDelete = false">Cancel</button>
        <button class="btn-danger" type="button" :disabled="busy" @click="remove">Delete</button>
      </template>
    </ModalDialog>
  </template>
</template>
