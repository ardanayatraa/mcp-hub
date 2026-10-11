<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import CallsChart from "@/components/CallsChart.vue";
import CodeBlock from "@/components/CodeBlock.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import PageHeader from "@/components/PageHeader.vue";
import ToolName from "@/components/ToolName.vue";
import { hub, type AppSummary, type Overview, type SystemInfo } from "@/services/hub";
import { useSession } from "@/stores/session";
import { actionLabel, appStatus, badgeClass, errorMessage, resultTone, timeAgo } from "@/utils/format";
import { kindStyle } from "@/utils/toolKinds";

const session = useSession();
const period = ref("24h");
const data = ref<Overview | null>(null);
const system = ref<SystemInfo | null>(null);
const apps = ref<AppSummary[]>([]);
const appsLoaded = ref(false);
const loading = ref(false);
const showTable = ref(false);
const error = ref("");

const PERIODS = [["24h", "24 hours"], ["7d", "7 days"], ["30d", "30 days"]] as const;
const SERIES_TEXT: Record<string, string> = {
  "24h": "per hour over the last 24 hours", "7d": "every 6 hours over the last 7 days", "30d": "per day over the last 30 days",
};

async function load() {
  error.value = "";
  loading.value = true;
  try {
    [data.value, system.value] = await Promise.all([hub.overview(period.value), system.value ? Promise.resolve(system.value) : hub.system()]);
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    loading.value = false;
  }
}

// Apps are fetched on their own: the list asks connected apps for current permissions and can be slower.
async function loadApps() {
  try {
    apps.value = await hub.apps();
  } catch {
    apps.value = [];
  } finally {
    appsLoaded.value = true;
  }
}
onMounted(() => { void load(); void loadApps(); });
watch(period, load);

const steps = computed(() => {
  const done = data.value?.checklist;
  return [
    { done: done?.app_connected, title: "Connect an app", text: "Add the app's base URL and API key, then test it.", to: "/apps/new", action: "Connect app" },
    { done: done?.source_enabled, title: "Allow a data source", text: "Choose which data the AI may read and which fields stay hidden.", to: "/apps", action: "Open apps" },
    { done: done?.key_created, title: "Create a client key", text: "Give your AI client a key. It can use run_report right away.", to: "/access", action: "Create key" },
    { done: done?.tool_published, title: "Publish a custom tool (optional)", text: "Turn a list, lookup or saved report into a named tool.", to: "/tools/new", action: "New tool" },
  ];
});
const allDone = computed(() => steps.value.every((step) => step.done));
const stats = computed(() => {
  const value = data.value;
  if (!value) return [];
  const rate = value.success_rate == null ? "—" : `${Math.round(value.success_rate * 100)}%`;
  return [
    { label: "Active apps", icon: "apps", to: "/apps", value: String(value.connectors_active), suffix: `/ ${value.apps_total}`,
      hint: value.connectors_failing ? `${value.connectors_failing} need attention` : "All healthy", alert: value.connectors_failing > 0 },
    { label: "Live tools", icon: "tools", to: "/tools", value: String(value.tools_published), suffix: "",
      hint: `${value.tools_draft} draft · ${value.modules_enabled} data sources on`, alert: false },
    { label: `Tool calls (${period.value})`, icon: "activity", to: "/activity", value: value.executions.toLocaleString(), suffix: "",
      hint: `${rate} success · ${value.denied} denied`, alert: false },
    { label: "Response time (p95)", icon: "clock", to: "/activity", value: String(value.latency_p95_ms), suffix: "ms",
      hint: `${value.keys_active} active client keys`, alert: false },
  ];
});
const topApps = computed(() => apps.value.filter((app) => app.status !== "archived").slice(0, 5));
const topToolMax = computed(() => Math.max(1, ...(data.value?.top_tools ?? []).map((item) => item.calls)));
const clientConfig = computed(() => JSON.stringify({
  mcpServers: { "mcp-hub": { type: "http", url: system.value?.mcp_url ?? "https://hub.example.com/mcp", headers: { Authorization: "Bearer <client key>" } } },
}, null, 2));

function share(app: AppSummary) {
  return app.sources_total ? Math.round((app.sources_enabled / app.sources_total) * 100) : 0;
}
function health(app: AppSummary) {
  if (app.circuit_open) return "failing repeatedly";
  if (!app.health) return "not tested";
  return app.health.status === "ok" ? `healthy · ${app.health.latency_ms ?? "?"} ms` : `check failed (${app.health.error_category})`;
}
function actorIcon(ref_: string) {
  return { admin: "users", service: "key", system: "bolt" }[ref_.split(":")[0]] ?? "activity";
}
</script>

<template>
  <PageHeader title="Overview" subtitle="Health of your connected apps and how AI clients use them.">
    <template #actions>
      <div class="segmented" role="group" aria-label="Period">
        <button v-for="[value, label] in PERIODS" :key="value" type="button" class="segmented-item" :aria-pressed="period === value"
                :title="label" @click="period = value">{{ value }}</button>
      </div>
    </template>
  </PageHeader>

  <p v-if="error" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>

  <section v-if="data && !allDone && session.canWrite" class="card mb-6">
    <div class="card-header">
      <h2 class="card-title">Get started</h2>
      <p class="card-description">Four steps from a connected app to an AI client that can answer questions about your data.</p>
    </div>
    <ol class="grid gap-3 px-6 pb-6 md:grid-cols-2 xl:grid-cols-4">
      <li v-for="(step, index) in steps" :key="step.title" class="flex flex-col rounded-lg border border-line p-4" :class="step.done ? 'bg-muted/50' : ''">
        <span class="mb-3 grid h-6 w-6 place-items-center rounded-full text-xs font-semibold"
              :class="step.done ? 'bg-ok text-white' : 'bg-muted text-subtle'">
          <AppIcon v-if="step.done" name="check" :size="14" /><template v-else>{{ index + 1 }}</template>
        </span>
        <p class="font-medium">{{ step.title }}</p>
        <p class="mt-1 flex-1 text-xs text-subtle">{{ step.text }}</p>
        <RouterLink v-if="!step.done" :to="step.to" class="btn-secondary btn-sm mt-3 self-start">{{ step.action }}</RouterLink>
      </li>
    </ol>
  </section>

  <template v-if="!data && !error">
    <LoadingSkeleton variant="stats" :count="4" label="Loading overview" class="mb-6" />
    <LoadingSkeleton variant="panel" :count="7" label="Loading tool calls" class="mb-6" />
  </template>

  <template v-if="data">
    <section class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <RouterLink v-for="stat in stats" :key="stat.label" :to="stat.to" class="card block transition-colors hover:bg-muted/40">
        <div class="flex items-center justify-between gap-2 p-6 pb-2">
          <p class="truncate text-sm font-medium">{{ stat.label }}</p>
          <AppIcon :name="stat.icon" :size="18" class="text-subtle" />
        </div>
        <div class="px-6 pb-6">
          <p class="text-2xl font-semibold tabular-nums">{{ stat.value }}<span v-if="stat.suffix" class="ml-1 text-sm font-normal text-subtle">{{ stat.suffix }}</span></p>
          <p class="mt-1 flex items-center gap-1 text-xs" :class="stat.alert ? 'text-bad' : 'text-subtle'">
            <AppIcon v-if="stat.alert" name="alert" :size="12" />{{ stat.hint }}</p>
        </div>
      </RouterLink>
    </section>

    <section class="card mb-6 transition-opacity" :class="loading ? 'opacity-60' : ''" :aria-busy="loading">
      <div class="flex flex-wrap items-start justify-between gap-3 p-6 pb-4">
        <div class="min-w-0">
          <h2 class="card-title">Tool calls</h2>
          <p class="card-description mt-1.5">All calls and unsuccessful calls {{ SERIES_TEXT[period] }}</p>
        </div>
        <div class="segmented" role="group" aria-label="View">
          <button type="button" class="segmented-item" :aria-pressed="!showTable" @click="showTable = false">Chart</button>
          <button type="button" class="segmented-item" :aria-pressed="showTable" @click="showTable = true">Table</button>
        </div>
      </div>
      <div class="px-6 pb-6">
        <CallsChart v-if="data.series" :points="data.series" :table="showTable" />
        <p v-else class="rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-subtle">
          Call history needs a newer Hub API. Restart the Hub server to load it.</p>
      </div>
    </section>

    <div class="mb-6 grid gap-6 lg:grid-cols-2">
      <section class="card min-w-0">
        <div class="flex items-start justify-between gap-3 p-6 pb-4">
          <div>
            <h2 class="card-title">Connected apps</h2>
            <p class="card-description mt-1.5">Data sources AI clients may read, per app</p>
          </div>
          <RouterLink to="/apps" class="link text-xs">View all</RouterLink>
        </div>
        <div class="px-6 pb-6">
          <div v-if="!appsLoaded" class="space-y-5" aria-label="Loading apps" role="status">
            <div v-for="n in 3" :key="n" class="space-y-2" aria-hidden="true">
              <div class="flex justify-between"><span class="skeleton h-4 w-32" /><span class="skeleton h-5 w-14" /></div>
              <span class="skeleton h-3 w-48" /><span class="skeleton h-2 w-full rounded-full" />
            </div>
          </div>
          <p v-else-if="!topApps.length" class="py-6 text-center text-sm text-subtle">
            No apps connected yet. <RouterLink v-if="session.canWrite" to="/apps/new" class="link">Connect one</RouterLink>
          </p>
          <ul v-else class="-mx-2 flex flex-col gap-1">
            <li v-for="app in topApps" :key="app.id">
              <RouterLink :to="`/apps/${app.id}`" class="flex flex-col gap-2 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50">
                <div class="flex items-center justify-between gap-2">
                  <h3 class="truncate text-sm font-medium">{{ app.name }}</h3>
                  <span :class="badgeClass(appStatus[app.status]?.tone ?? 'neutral')">{{ appStatus[app.status]?.label ?? app.status }}</span>
                </div>
                <p class="truncate text-xs text-subtle"><span class="font-mono">{{ app.app_key }}</span> · {{ app.environment }} · {{ health(app) }}</p>
                <div class="flex items-center gap-3">
                  <div class="progress" role="progressbar" :aria-valuenow="share(app)" aria-valuemin="0" aria-valuemax="100"
                       :aria-label="`${app.name}: data sources allowed`"><span :style="{ width: `${share(app)}%` }" /></div>
                  <span class="shrink-0 text-xs tabular-nums text-subtle">
                    {{ app.source_sync_error ? "—" : `${app.sources_enabled}/${app.sources_total}` }} sources</span>
                </div>
                <p class="flex justify-between gap-2 text-xs text-subtle">
                  <span>{{ app.tools_published }} live tool{{ app.tools_published === 1 ? "" : "s" }}</span>
                  <span v-if="app.health?.checked_at">checked {{ timeAgo(app.health.checked_at) }}</span>
                </p>
              </RouterLink>
            </li>
          </ul>
        </div>
      </section>

      <section class="card min-w-0">
        <div class="flex items-start justify-between gap-3 p-6 pb-4">
          <div>
            <h2 class="card-title">Recent activity</h2>
            <p class="card-description mt-1.5">Latest calls and configuration changes</p>
          </div>
          <RouterLink to="/activity" class="link text-xs">View all</RouterLink>
        </div>
        <ol v-if="data.recent.length" class="flex flex-col gap-4 px-6 pb-6">
          <li v-for="event in data.recent" :key="event.trace_id + event.created_at" class="flex items-start gap-3">
            <span v-if="event.tool" class="grid h-8 w-8 shrink-0 place-items-center rounded-md" :class="kindStyle(event.tool.kind).tile">
              <AppIcon :name="kindStyle(event.tool.kind).icon" :size="15" /></span>
            <span v-else class="avatar text-subtle"><AppIcon :name="actorIcon(event.actor_ref)" :size="15" /></span>
            <div class="min-w-0 flex-1">
              <p v-if="event.tool" class="truncate text-sm leading-snug">
                <RouterLink v-if="event.tool.tool_id" :to="`/tools/${event.tool.tool_id}`" class="font-medium hover:underline">{{ event.tool.title }}</RouterLink>
                <span v-else class="font-medium">{{ event.tool.title }}</span>
              </p>
              <p v-else class="truncate text-sm leading-snug">
                <span class="font-medium">{{ actionLabel(event.action) }}</span>
                <span v-if="event.tool_key" class="ml-1 font-mono text-xs text-subtle">{{ event.tool_key }}</span>
              </p>
              <p class="truncate text-xs text-subtle">
                <template v-if="event.tool">{{ actionLabel(event.action) }} · {{ [event.tool.app_name, event.tool.module_name].filter(Boolean).join(" · ") || "Hub" }}</template>
                <template v-else>{{ event.app_key ?? "hub" }}</template>
                · {{ timeAgo(event.created_at) }}<template v-if="event.error_code"> · {{ event.error_code }}</template></p>
            </div>
            <span :class="badgeClass(resultTone(event.result))">{{ event.result }}</span>
          </li>
        </ol>
        <p v-else class="px-6 pb-10 pt-4 text-center text-sm text-subtle">Nothing yet.</p>
      </section>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <section class="card min-w-0">
        <div class="card-header">
          <h2 class="card-title">Connect an AI client</h2>
          <p class="card-description">Point any MCP client (Claude, Cursor, your app's AI gateway) at this endpoint with a client key.</p>
        </div>
        <div class="space-y-3 px-6 pb-6">
          <div class="flex items-center gap-2">
            <code class="code flex-1 truncate py-1.5">{{ system?.mcp_url }}</code>
            <CopyButton v-if="system" :text="system.mcp_url" />
          </div>
          <CodeBlock :code="clientConfig" max-height="12rem" />
          <div class="flex flex-wrap gap-2">
            <RouterLink to="/access" class="btn-secondary btn-sm">Create a client key</RouterLink>
            <RouterLink to="/docs/guide#clients" class="btn-ghost btn-sm"><AppIcon name="book" :size="14" /> How to connect a client</RouterLink>
          </div>
        </div>
      </section>

      <section class="card min-w-0">
        <div class="card-header">
          <h2 class="card-title">Most used tools</h2>
          <p class="card-description">Calls in the last {{ PERIODS.find(([value]) => value === period)?.[1] }}</p>
        </div>
        <ul v-if="data.top_tools.length" class="space-y-4 px-6 pb-6">
          <li v-for="item in data.top_tools" :key="item.tool_key">
            <div class="flex items-center justify-between gap-3">
              <ToolName :card="item.tool" :fallback="item.tool_key" />
              <span class="shrink-0 text-right"><span class="block text-sm font-semibold tabular-nums">{{ item.calls.toLocaleString() }}</span>
                <span class="block text-xs text-subtle">calls</span></span>
            </div>
            <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <span class="block h-full rounded-full bg-chart-1" :style="{ width: `${(item.calls / topToolMax) * 100}%` }" />
            </div>
          </li>
        </ul>
        <p v-else class="px-6 pb-10 pt-4 text-center text-sm text-subtle">No tool calls in this period.</p>
      </section>
    </div>
  </template>
</template>
