<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "#imports";

import PageHeader from "@/components/PageHeader.vue";
import ParamEditor from "@/components/ParamEditor.vue";
import ReportBuilder from "@/components/ReportBuilder.vue";
import { hub, type AppSummary, type DataSource, type JsonSchema, type ReportSpec } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";
import { endpointLabel, endpointsFor, reportFields, suggestName, visibleFieldNames } from "@/utils/sources";

definePageMeta({ write: true });

const route = useRoute();
const router = useRouter();
const toast = useToast();
const kind = ref<"" | "read" | "report" | "write">((["read", "report", "write"].includes(String(route.query.template)) ? route.query.template : "") as "");
const connectorId = ref(String(route.query.connector ?? ""));
const moduleKey = ref(String(route.query.module ?? ""));
const apps = ref<AppSummary[]>([]);
const sources = ref<DataSource[]>([]);
const endpointKey = ref("");
const name = ref("");
const title = ref("");
const description = ref("");
const inputSchema = ref<JsonSchema | null>(null);
const allowFields = ref<string[]>([]);
const report = ref<ReportSpec>({});
const busy = ref(false);
const error = ref("");

const KINDS = [
  { key: "read", icon: "table", title: "Read records", text: "List, look up or count records through one of the app's read routes.", badge: "" },
  { key: "report", icon: "chart", title: "Report", text: "A saved summary: filters, groups, totals and a short text answer.", badge: "Recommended" },
  { key: "write", icon: "pencil", title: "Change data", text: "Send a create, update or delete request. The app validates it and may ask the user to confirm.", badge: "Needs write permission" },
] as const;

onMounted(async () => {
  try {
    [apps.value, sources.value] = await Promise.all([hub.apps(), hub.sources()]);
    apps.value = apps.value.filter((app) => app.status !== "archived" && app.connector_type !== "source_managed");
  } catch (exc) {
    error.value = errorMessage(exc);
  }
});

const app = computed(() => apps.value.find((item) => item.id === connectorId.value));
const appSources = computed(() => sources.value.filter((source) => source.connector_id === connectorId.value));
const source = computed(() => appSources.value.find((item) => item.module_key === moduleKey.value));
const template = computed(() => (kind.value === "write" ? endpoint.value?.operation ?? "create" : kind.value));
const endpoints = computed(() => (kind.value === "write"
  ? (source.value?.endpoints ?? []).filter((item) => item.kind === "write")
  : endpointsFor(source.value, kind.value)));
const endpoint = computed(() => endpoints.value.find((item) => item.key === endpointKey.value));
const outputFields = computed(() => Object.keys(endpoint.value?.output_schema.items?.properties ?? {}));
const visible = computed(() => visibleFieldNames(source.value));
const operationOff = computed(() => {
  if (!source.value) return false;
  const needed = kind.value === "write" ? template.value : "read";
  return !source.value.enabled || !source.value.operations_enabled.includes(needed);
});

watch(connectorId, () => { if (!appSources.value.some((item) => item.module_key === moduleKey.value)) moduleKey.value = ""; });
watch([source, kind], () => {
  endpointKey.value = kind.value === "report" ? (source.value?.report_endpoint_effective ?? "") : (endpoints.value[0]?.key ?? "");
});
watch([endpoint, kind], () => {
  if (!source.value) return;
  name.value = suggestName(source.value, template.value, endpoint.value);
  inputSchema.value = null;
  allowFields.value = kind.value === "write" ? [...outputFields.value] : outputFields.value.filter((field) => visible.value.has(field));
}, { immediate: false });

function toggleField(field: string) {
  allowFields.value = allowFields.value.includes(field) ? allowFields.value.filter((item) => item !== field) : [...allowFields.value, field];
}

async function create() {
  if (!source.value || !app.value) return;
  busy.value = true;
  error.value = "";
  try {
    const body: Record<string, unknown> = {
      connector_id: connectorId.value, module_key: moduleKey.value, template: template.value, tool_key: name.value,
      title: title.value || null, description: description.value,
    };
    if (kind.value === "report") {
      body.report = report.value;
    } else if (endpoint.value) {
      Object.assign(body, { method: endpoint.value.method, path_template: endpoint.value.path_template,
                            input_schema: inputSchema.value ?? endpoint.value.input_schema, allow_fields: allowFields.value });
    }
    const created = await hub.createTool(body);
    toast.ok("Draft created. Test it, then publish.");
    await router.push(`/tools/${created.id}`);
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <PageHeader title="New tool" back="/tools" subtitle="Tools are built from your apps' reviewed routes. Nothing here runs code or reaches arbitrary URLs." />
  <p v-if="error" role="alert" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>

  <section class="mb-6">
    <h2 class="section-title mb-3">1. What should the tool do?</h2>
    <div class="grid gap-3 md:grid-cols-3">
      <button v-for="option in KINDS" :key="option.key" type="button"
              class="card card-pad text-left transition hover:border-brand/50"
              :class="kind === option.key ? 'border-brand ring-2 ring-brand/20' : ''" @click="kind = option.key">
        <span class="mb-3 flex items-center justify-between">
          <span class="grid h-9 w-9 place-items-center rounded-lg bg-brand-soft text-brand"><AppIcon :name="option.icon" /></span>
          <span v-if="option.badge" :class="option.key === 'write' ? 'badge-warn' : 'badge-brand'">{{ option.badge }}</span>
        </span>
        <p class="font-semibold">{{ option.title }}</p>
        <p class="mt-1 text-xs text-subtle">{{ option.text }}</p>
      </button>
    </div>
  </section>

  <section v-if="kind" class="mb-6">
    <h2 class="section-title mb-3">2. Which data?</h2>
    <div class="card card-pad grid gap-4 sm:grid-cols-2">
      <label><span class="label">App</span>
        <select v-model="connectorId" class="input">
          <option value="" disabled>Choose an app</option>
          <option v-for="item in apps" :key="item.id" :value="item.id">{{ item.name }} · {{ item.environment }}</option>
        </select></label>
      <label><span class="label">Data source</span>
        <select v-model="moduleKey" class="input" :disabled="!connectorId">
          <option value="" disabled>Choose a data source</option>
          <option v-for="item in appSources" :key="item.id" :value="item.module_key">{{ item.name }} ({{ item.module_key }})</option>
        </select></label>
      <p v-if="source && !endpoints.length" class="text-sm text-warn sm:col-span-2">
        {{ kind === "write" ? "This data source publishes no write routes." : kind === "report" ? "This data source has no list route to report on." : "This data source publishes no read routes." }}
      </p>
      <p v-else-if="operationOff" class="flex items-center gap-2 text-xs text-warn sm:col-span-2">
        <AppIcon name="info" :size="14" /> {{ kind === "write" ? `The ${template} operation` : "Read" }} is not enabled on this data source yet.
        You can create the draft now; enable it on the <RouterLink :to="`/apps/${connectorId}`" class="link">app page</RouterLink> before publishing.
      </p>
    </div>
  </section>

  <form v-if="kind && source && endpoints.length" class="space-y-6" @submit.prevent="create">
    <section>
      <h2 class="section-title mb-3">3. Configure</h2>
      <div class="card card-pad space-y-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <label><span class="label">Tool name</span>
            <span class="flex items-center overflow-hidden rounded-lg border border-line focus-within:ring-2 focus-within:ring-brand/25">
              <span class="bg-muted px-2.5 py-2 font-mono text-xs text-subtle">{{ app?.app_key }}.</span>
              <input v-model="name" class="w-full bg-surface px-2 py-2 font-mono text-sm outline-none" required pattern="[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}" />
            </span>
            <span class="hint">MCP name: <span class="font-mono">{{ `${app?.app_key}__${name.replaceAll(".", "__")}` }}</span></span></label>
          <label><span class="label">Display title (optional)</span><input v-model="title" class="input" maxlength="120" placeholder="Orders by status" /></label>
        </div>
        <label class="block"><span class="label">Description for the AI</span>
          <textarea v-model="description" class="input" rows="2" maxlength="300"
                    placeholder="When should the AI use this tool and what does it return? Leave empty for a sensible default." /></label>

        <template v-if="kind !== 'report'">
          <label v-if="endpoints.length > 1" class="block"><span class="label">{{ kind === "write" ? "Operation and route" : "Route" }}</span>
            <select v-model="endpointKey" class="input font-mono text-xs">
              <option v-for="item in endpoints" :key="item.key" :value="item.key">{{ kind === "write" ? `${item.operation}: ` : "" }}{{ endpointLabel(item) }}</option>
            </select></label>
          <p v-else-if="endpoint" class="text-xs text-subtle">Route: <span class="code">{{ endpointLabel(endpoint) }}</span></p>
        </template>
        <p v-else class="text-xs text-subtle">Reads every authorized record (page by page) from <span class="code">{{ source.report_endpoint_effective }}</span>.</p>
      </div>
    </section>

    <section v-if="kind !== 'report' && endpoint" class="grid gap-6 lg:grid-cols-2">
      <div>
        <h3 class="section-title mb-1">Parameters the AI may use</h3>
        <p class="mb-3 text-xs text-subtle">Hide parameters or narrow their limits. The app still validates every value.</p>
        <ParamEditor :key="endpoint.key" v-model="inputSchema" :route="endpoint.input_schema" />
      </div>
      <div>
        <h3 class="section-title mb-1">{{ kind === "write" ? "Receipt fields returned" : "Fields returned" }}</h3>
        <p class="mb-3 text-xs text-subtle">{{ kind === "write" ? "What the AI sees after the request." : "Only fields marked Visible to AI can be returned." }}</p>
        <div class="divide-y divide-line rounded-lg border border-line">
          <label v-for="field in outputFields" :key="field" class="flex items-center gap-3 px-3 py-2 text-sm"
                 :class="kind !== 'write' && !visible.has(field) ? 'opacity-50' : ''">
            <input type="checkbox" :checked="allowFields.includes(field)" :disabled="kind !== 'write' && !visible.has(field)" @change="toggleField(field)" />
            <span class="font-mono">{{ field }}</span>
            <span v-if="kind !== 'write' && !visible.has(field)" class="ml-auto flex items-center gap-1 text-xs text-subtle"><AppIcon name="lock" :size="12" /> not visible to AI</span>
          </label>
        </div>
      </div>
    </section>

    <section v-if="kind === 'report'" class="card card-pad">
      <h3 class="section-title mb-1">Report</h3>
      <p class="mb-4 text-xs text-subtle">Fixed parts of the report. The AI can still change the row limit, and add filters if you allow it.</p>
      <ReportBuilder v-model="report" :fields="reportFields(source)" saved />
    </section>

    <div class="flex justify-end gap-2">
      <RouterLink to="/tools" class="btn-secondary">Cancel</RouterLink>
      <button class="btn-primary" type="submit" :disabled="busy || !name || (kind !== 'report' && !allowFields.length)">Create draft</button>
    </div>
  </form>
</template>
