<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AgentViewPanel from "@/components/AgentViewPanel.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkillsPanel from "@/components/SkillsPanel.vue";
import TabBar from "@/components/TabBar.vue";
import ToolGenerator from "@/components/ToolGenerator.vue";
import { hub, type AppSummary, type BuiltinTool, type Tool } from "@/services/hub";
import { useSession } from "@/stores/session";
import { badgeClass, errorMessage, templateInfo, timeAgo, toolStatus } from "@/utils/format";
import { kindStyle, toolKind } from "@/utils/toolKinds";
import { useCatalogRefresh } from "@/utils/sources";

const route = useRoute();
const router = useRouter();
const session = useSession();
const tools = ref<Tool[]>([]);
const builtins = ref<BuiltinTool[]>([]);
const loaded = ref(false);
const error = ref("");
const search = ref("");
const app = ref("");
const status = ref("");
const TABS = ["catalog", "skills", "agent"];
const tab = ref(TABS.includes(String(route.query.tab)) ? String(route.query.tab) : "catalog");
const allApps = ref<AppSummary[]>([]);
const skillCount = ref<number | undefined>(undefined);
const generating = ref(false);

watch(tab, (value) => { void router.replace({ query: { ...route.query, tab: value === "catalog" ? undefined : value } }); });

// Apps load on their own: the generator, skills and agent view need them, the catalog does not.
onMounted(async () => {
  try {
    allApps.value = await hub.apps();
  } catch {
    allApps.value = [];
  }
});

async function loadTools(background = false) {
  try {
    tools.value = await hub.tools();
    if (!background) builtins.value = await hub.builtins();
    error.value = "";
  } catch (exc) {
    tools.value = [];
    error.value = errorMessage(exc);
  } finally {
    loaded.value = true;
  }
}
useCatalogRefresh(loadTools, () => tab.value === "catalog" && !generating.value);

const tabs = computed(() => [
  { key: "catalog", label: "Catalog", count: loaded.value ? tools.value.length + builtins.value.length : undefined },
  { key: "skills", label: "Skills", count: skillCount.value },
  { key: "agent", label: "What the agent sees" },
]);
const canGenerate = computed(() => allApps.value.some((app) => app.status !== "archived"));

const apps = computed(() => [...new Map(tools.value.map((tool) => [tool.app_id, tool.app_name])).entries()]);
const filtered = computed(() => tools.value.filter((tool) =>
  (!app.value || tool.app_id === app.value)
  && (!status.value || toolStatus(tool).label === status.value)
  && (!search.value || `${tool.display_title} ${tool.mcp_name} ${tool.description}`.toLowerCase().includes(search.value.toLowerCase()))));
</script>

<template>
  <PageHeader title="Tools" subtitle="What AI clients can call. Built-in tools work on every allowed data source; custom tools give common questions a clear name and fixed settings.">
    <template #actions>
      <button v-if="session.canWrite" type="button" class="btn-secondary" :disabled="!canGenerate" @click="generating = true">
        <AppIcon name="sparkles" :size="16" /> Generate tools</button>
      <RouterLink v-if="session.canWrite" to="/tools/report" class="btn-secondary"><AppIcon name="chart" :size="16" /> Report playground</RouterLink>
      <RouterLink v-if="session.canWrite" to="/tools/new" class="btn-primary"><AppIcon name="plus" :size="16" /> New tool</RouterLink>
    </template>
  </PageHeader>

  <TabBar v-model="tab" :tabs="tabs" />

  <SkillsPanel v-if="tab === 'skills'" :apps="allApps" @changed="(count: number) => (skillCount = count)" />
  <AgentViewPanel v-else-if="tab === 'agent'" :apps="allApps" />

  <template v-else>
  <p v-if="error" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>

  <h2 class="mb-3 text-sm font-medium text-subtle">Built-in</h2>
  <div class="mb-8 grid gap-4 md:grid-cols-2">
    <template v-if="!builtins.length && !error">
      <div v-for="n in 2" :key="n" class="card card-pad space-y-3" aria-hidden="true">
        <div class="flex items-center gap-2"><span class="skeleton h-8 w-8 rounded-lg" /><span class="skeleton h-4 w-32" /></div>
        <span class="skeleton h-3 w-full" /><span class="skeleton h-3 w-2/3" />
      </div>
    </template>
    <article v-for="tool in builtins" :key="tool.name" class="card card-pad">
      <div class="mb-2 flex items-center gap-2">
        <span class="grid h-8 w-8 place-items-center rounded-lg bg-brand-soft text-brand">
          <AppIcon :name="tool.name === 'run_report' ? 'chart' : tool.requires === 'memory' ? 'sparkles' : 'database'" :size="16" />
        </span>
        <div>
          <p class="font-semibold">{{ tool.title }}</p>
          <p class="font-mono text-xs text-subtle">{{ tool.name }}</p>
        </div>
        <span v-if="tool.requires === 'memory'" class="badge-outline ml-auto" title="Turn memory on for an app on its Memory tab">Per app, opt-in</span>
        <span v-else class="badge-ok ml-auto">Always on</span>
      </div>
      <p class="text-sm text-subtle">{{ tool.description }}</p>
      <RouterLink v-if="tool.name === 'run_report' && session.canWrite" to="/tools/report" class="link mt-3 inline-block text-xs">Try it in the playground →</RouterLink>
    </article>
  </div>

  <div class="mb-3 flex flex-wrap items-center gap-2">
    <h2 class="mr-auto text-sm font-medium text-subtle">Custom tools</h2>
    <div class="relative">
      <AppIcon name="search" :size="14" class="pointer-events-none absolute left-2.5 top-2.5 text-subtle" />
      <input v-model="search" class="input w-56 pl-8" placeholder="Search tools" aria-label="Search tools" />
    </div>
    <select v-model="app" class="input w-44"><option value="">All apps</option><option v-for="[key, name] in apps" :key="key" :value="key">{{ name }}</option></select>
    <select v-model="status" class="input w-40">
      <option value="">Any status</option><option>Live</option><option>Draft</option><option>Needs re-test</option><option>Disabled</option>
    </select>
  </div>

  <LoadingSkeleton v-if="!loaded" label="Loading tools" />
  <EmptyState v-else-if="!tools.length" icon="tools" title="No custom tools yet"
              text="Pick a template: read records, a saved report, or (with extra permission) a create, update or delete request.">
    <button v-if="session.canWrite && canGenerate" type="button" class="btn-primary" @click="generating = true">
      <AppIcon name="sparkles" :size="16" /> Generate from an app</button>
    <RouterLink v-if="session.canWrite" to="/tools/new" class="btn-secondary">Create one by hand</RouterLink>
  </EmptyState>

  <div v-else class="card overflow-x-auto">
    <table class="tbl">
      <thead><tr><th>Tool</th><th>Type</th><th>App · data source</th><th>Status</th><th>Last test</th></tr></thead>
      <tbody>
        <tr v-for="tool in filtered" :key="tool.id" class="row-link" @click="router.push(`/tools/${tool.id}`)">
          <td class="max-w-xs">
            <span class="flex min-w-0 items-center gap-2.5">
              <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md" :class="kindStyle(toolKind(tool.template, tool.tool_key)).tile">
                <AppIcon :name="kindStyle(toolKind(tool.template, tool.tool_key)).icon" :size="15" /></span>
              <span class="min-w-0"><span class="block truncate font-medium">{{ tool.display_title }}</span>
                <span class="block truncate font-mono text-xs text-subtle">{{ tool.mcp_name }}</span></span></span>
          </td>
          <td><span :class="badgeClass(templateInfo[tool.template]?.tone ?? 'neutral')">
            <AppIcon :name="templateInfo[tool.template]?.icon ?? 'tools'" :size="12" /> {{ templateInfo[tool.template]?.label ?? tool.template }}</span></td>
          <td class="text-xs"><p>{{ tool.app_name }}</p><p class="text-subtle">{{ tool.module_name }}</p></td>
          <td><span :class="badgeClass(toolStatus(tool).tone)">{{ toolStatus(tool).label }}</span></td>
          <td class="text-xs">
            <span v-if="tool.last_test" :class="tool.last_test.passed ? 'text-ok' : 'text-bad'">{{ tool.last_test.passed ? "Passed" : "Failed" }}</span>
            <span v-else class="text-subtle">{{ tool.source_managed ? "Managed by app" : "Not tested" }}</span>
            <span v-if="tool.last_test" class="text-subtle"> · {{ timeAgo(tool.last_test.created_at) }}</span>
          </td>
        </tr>
        <tr v-if="!filtered.length"><td colspan="5" class="py-8 text-center text-subtle">No tools match these filters.</td></tr>
      </tbody>
    </table>
  </div>
  </template>

  <ToolGenerator v-if="generating" :apps="allApps" @close="generating = false" @done="loadTools()" />
</template>
