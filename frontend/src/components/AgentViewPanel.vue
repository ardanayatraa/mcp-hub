<script setup lang="ts">
import { computed, ref, watch } from "vue";

import CodeBlock from "@/components/CodeBlock.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import { hub, type AgentView, type AppSummary, type ClientKey, type JsonSchema, type McpTool } from "@/services/hub";
import { byReadiness, errorMessage } from "@/utils/format";
import { useSlowFlag } from "@/utils/loading";

// Exactly what an AI client receives from tools/list and prompts/list for one app and key.
const props = defineProps<{ apps: AppSummary[]; appsLoaded: boolean; appsError: string }>();
const activeApps = computed(() => byReadiness(props.apps.filter((app) => app.status !== "archived")));
const appId = ref("");
const keyChoice = ref("read");
const keys = ref<ClientKey[]>([]);
const view = ref<AgentView | null>(null);
const loading = ref(false);
const slow = useSlowFlag(loading);
const error = ref("");
const showJson = ref(false);
const open = ref<Record<string, boolean>>({});

watch(activeApps, (apps) => {
  if (!apps.some((app) => app.id === appId.value)) appId.value = apps[0]?.id ?? "";
}, { immediate: true });

watch(appId, async (id) => {
  keyChoice.value = "read";
  keys.value = [];
  if (!id) return;
  const app = props.apps.find((item) => item.id === id);
  try {
    keys.value = (await hub.keys(app?.app_id)).filter((key) => key.status === "active");
  } catch {
    keys.value = [];
  }
}, { immediate: true });

// Switching app resets the key, so two requests can overlap; only the latest one may land.
let latest = 0;
watch([appId, keyChoice], async ([id, choice]) => {
  if (!id) {
    ++latest;
    view.value = null;
    loading.value = false;
    return;
  }
  const request = ++latest;
  loading.value = true;
  error.value = "";
  try {
    const next = await hub.agentView(id, choice === "read" || choice === "write" ? { write: choice === "write" } : { keyId: choice });
    if (request === latest) view.value = next;
  } catch (exc) {
    if (request !== latest) return;
    view.value = null;
    error.value = errorMessage(exc);
  } finally {
    if (request === latest) loading.value = false;
  }
}, { immediate: true });

const json = computed(() => JSON.stringify({ tools: view.value?.tools ?? [], prompts: view.value?.prompts ?? [] }, null, 2));

function kind(tool: McpTool): { label: string; tone: string } {
  if (tool.annotations?.readOnlyHint !== false) return { label: "Read-only", tone: "badge-neutral" };
  return tool.annotations?.destructiveHint ? { label: "Changes or deletes", tone: "badge-bad" } : { label: "Changes data", tone: "badge-warn" };
}

function inputs(schema: JsonSchema) {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, spec]) => ({
    name, required: required.has(name),
    type: spec.enum ? spec.enum.join(" | ") : Array.isArray(spec.type) ? spec.type.join(" | ") : spec.type ?? "any",
    description: spec.description ?? "",
  }));
}
</script>

<template>
  <section>
    <div class="mb-5 flex flex-wrap items-end gap-3">
      <label class="w-full sm:w-64"><span class="label">App</span>
        <select v-model="appId" class="input" :disabled="!activeApps.length">
          <option v-if="!activeApps.length" value="">{{ !appsLoaded ? "Loading apps…" : appsError ? "Apps unavailable" : "No apps connected" }}</option>
          <option v-for="app in activeApps" :key="app.id" :value="app.id">{{ app.name }} · {{ app.environment }}</option>
        </select></label>
      <label class="w-full sm:w-72"><span class="label">As seen by</span>
        <select v-model="keyChoice" class="input" :disabled="!activeApps.length">
          <option value="read">A new read-only key</option>
          <option value="write">A new key with write permission</option>
          <optgroup v-if="keys.length" label="Existing client keys">
            <option v-for="key in keys" :key="key.id" :value="key.id">{{ key.name }}{{ key.write ? " (read & write)" : "" }}</option>
          </optgroup>
        </select></label>
      <button v-if="view" type="button" class="btn-secondary sm:ml-auto" @click="showJson = !showJson">
        <AppIcon name="code" :size="16" /> {{ showJson ? "Hide JSON" : "Show JSON" }}</button>
    </div>

    <LoadingSkeleton v-if="!appsLoaded" label="Loading apps" />
    <p v-else-if="appsError && !activeApps.length" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad" role="alert">Could not load apps: {{ appsError }}</p>
    <EmptyState v-else-if="!activeApps.length" icon="apps" title="No apps connected" text="Connect an app to preview the tools and skills an AI client can use.">
      <RouterLink to="/apps" class="btn-secondary">View apps</RouterLink>
    </EmptyState>
    <template v-else-if="loading && !view">
      <LoadingSkeleton variant="rows" :count="4" label="Loading what the agent sees" />
      <p v-if="slow" class="mt-3 text-xs text-subtle">Asking the app for its current permissions…</p>
    </template>
    <p v-else-if="error" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>

    <div v-else-if="view" class="space-y-6 transition-opacity" :class="loading ? 'opacity-60' : ''">
      <p v-if="view.sync_error" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ view.sync_error.message }}</p>
      <p v-if="view.app.status !== 'active'" class="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm">
        {{ view.app.name }} is not active, so AI clients see no tools. Activate it on the app page.</p>

      <CodeBlock v-if="showJson" :code="json" max-height="28rem" />

      <div class="card card-pad">
        <h2 class="card-title">Server instructions</h2>
        <p class="mt-2 text-sm leading-6 text-subtle">{{ view.instructions }}</p>
        <p class="mt-3 text-xs text-subtle">Memory is <span :class="view.memory_enabled ? 'text-ok' : ''">{{ view.memory_enabled ? "on" : "off" }}</span> for this app.
          <RouterLink :to="`/apps/${view.app.connector_id}?tab=memory`" class="link">Change</RouterLink></p>
      </div>

      <div>
        <h2 class="mb-3 text-sm font-medium text-subtle">Tools ({{ view.tools.length }})</h2>
        <EmptyState v-if="!view.tools.length" icon="tools" title="No tools" text="This key sees nothing. Check that the app is active and the key's tool allowlist." />
        <ul v-else class="card divide-y divide-line">
          <li v-for="tool in view.tools" :key="tool.name" class="p-4">
            <div class="flex flex-wrap items-start gap-2">
              <div class="min-w-0 flex-1">
                <p class="font-medium">{{ tool.title || tool.name }}</p>
                <p class="font-mono text-xs text-subtle">{{ tool.name }}</p>
              </div>
              <span :class="kind(tool).tone">{{ kind(tool).label }}</span>
            </div>
            <p class="mt-2 text-sm text-subtle">{{ tool.description }}</p>
            <button v-if="inputs(tool.inputSchema).length" type="button" class="btn-ghost btn-sm mt-2 -ml-3" :aria-expanded="!!open[tool.name]"
                    @click="open[tool.name] = !open[tool.name]">
              <AppIcon :name="open[tool.name] ? 'chevron-down' : 'chevron-right'" :size="14" />
              {{ inputs(tool.inputSchema).length }} input{{ inputs(tool.inputSchema).length === 1 ? "" : "s" }}</button>
            <table v-if="open[tool.name]" class="tbl mt-1 rounded-lg border border-line">
              <thead><tr><th>Input</th><th>Type</th><th>Description</th></tr></thead>
              <tbody>
                <tr v-for="item in inputs(tool.inputSchema)" :key="item.name">
                  <td class="font-mono text-xs">{{ item.name }}<span v-if="item.required" class="text-bad">*</span></td>
                  <td class="text-xs text-subtle">{{ item.type }}</td>
                  <td class="text-xs text-subtle">{{ item.description }}</td>
                </tr>
              </tbody>
            </table>
          </li>
        </ul>
      </div>

      <div>
        <h2 class="mb-3 text-sm font-medium text-subtle">Skills ({{ view.prompts.length }})</h2>
        <p v-if="!view.prompts.length" class="text-sm text-subtle">No skills are offered to this key. <RouterLink to="/tools?tab=skills" class="link">Create one</RouterLink></p>
        <ul v-else class="card divide-y divide-line">
          <li v-for="prompt in view.prompts" :key="prompt.name" class="p-4">
            <p class="font-medium">{{ prompt.title || prompt.name }} <span class="font-mono text-xs font-normal text-subtle">/{{ prompt.name }}</span></p>
            <p class="mt-1 text-sm text-subtle">{{ prompt.description }}</p>
            <div v-if="prompt.arguments?.length" class="mt-2 flex flex-wrap gap-1">
              <span v-for="item in prompt.arguments" :key="item.name" class="badge-outline font-mono">{{ item.name }}{{ item.required ? "" : "?" }}</span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
