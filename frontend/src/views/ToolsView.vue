<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AgentViewPanel from "@/components/AgentViewPanel.vue";
import CapabilitiesPanel from "@/components/CapabilitiesPanel.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import PageHeader from "@/components/PageHeader.vue";
import SkillsPanel from "@/components/SkillsPanel.vue";
import TabBar from "@/components/TabBar.vue";
import ToolGenerator from "@/components/ToolGenerator.vue";
import ToolsTable from "@/components/ToolsTable.vue";
import { hub, type AppSummary, type BuiltinTool, type Capabilities, type Tool } from "@/services/hub";
import { useSession } from "@/stores/session";
import { errorMessage } from "@/utils/format";
import { useCatalogRefresh } from "@/utils/sources";

const route = useRoute();
const router = useRouter();
const session = useSession();
const tools = ref<Tool[]>([]);
const builtins = ref<BuiltinTool[]>([]);
const capabilities = ref<Capabilities | null>(null);
const capabilitiesError = ref("");
const loaded = ref(false);
const error = ref("");
const TABS = ["tools", "capabilities", "skills", "agent"];
// "catalog" was this tab's name before 1.0.1; old links still land on the table.
const requested = route.query.tab === "catalog" ? "tools" : String(route.query.tab);
const tab = ref(TABS.includes(requested) ? requested : "tools");
const allApps = ref<AppSummary[]>([]);
const appsLoaded = ref(false);
const appsError = ref("");
const skillCount = ref<number | undefined>(undefined);
const generating = ref(false);

watch(tab, (value) => { void router.replace({ query: { ...route.query, tab: value === "tools" ? undefined : value } }); });

// Apps load on their own: the generator, skills and agent view need them, the table does not.
async function loadApps() {
  try {
    allApps.value = await hub.apps();
    appsError.value = "";
  } catch (exc) {
    appsError.value = errorMessage(exc);
  } finally {
    appsLoaded.value = true;
  }
}
onMounted(loadApps);

async function loadCapabilities() {
  try {
    capabilities.value = await hub.capabilities();
    capabilitiesError.value = "";
  } catch (exc) {
    capabilitiesError.value = errorMessage(exc);
  }
}

async function loadTools(background = false) {
  const extras = loadCapabilities();
  try {
    tools.value = await hub.tools();
    if (!background) builtins.value = await hub.builtins();
    error.value = "";
  } catch (exc) {
    tools.value = [];
    error.value = errorMessage(exc);
  } finally {
    await extras;
    loaded.value = true;
  }
}
useCatalogRefresh(loadTools, () => ["tools", "capabilities"].includes(tab.value) && !generating.value);

const tabs = computed(() => [
  { key: "tools", label: "All tools", count: loaded.value ? tools.value.length + builtins.value.length : undefined },
  { key: "capabilities", label: "Capabilities" },
  { key: "skills", label: "Skills", count: skillCount.value },
  { key: "agent", label: "What the agent sees" },
]);
const canGenerate = computed(() => allApps.value.some((app) => app.status !== "archived"));
</script>

<template>
  <PageHeader title="Tools" subtitle="What AI clients can call and what this MCP can do. Hub tools work on every allowed data source; app tools give common questions a clear name and fixed settings.">
    <template #actions>
      <RouterLink v-if="session.canWrite" to="/tools/import" class="btn-secondary">Import OpenAPI</RouterLink>
      <button v-if="session.canWrite" type="button" class="btn-secondary" :disabled="!canGenerate" @click="generating = true">
        <AppIcon name="sparkles" :size="16" /> Generate tools</button>
      <RouterLink v-if="session.canWrite" to="/tools/report" class="btn-secondary"><AppIcon name="chart" :size="16" /> Report playground</RouterLink>
      <RouterLink v-if="session.canWrite" to="/tools/new" class="btn-primary"><AppIcon name="plus" :size="16" /> New tool</RouterLink>
    </template>
  </PageHeader>

  <TabBar v-model="tab" :tabs="tabs" />

  <div v-if="appsError" class="mb-5 flex flex-wrap items-center gap-3 rounded-lg bg-bad-soft px-4 py-3 text-sm text-bad" role="alert">
    <span class="mr-auto">Could not load apps: {{ appsError }}</span>
    <button type="button" class="btn-secondary btn-sm" @click="loadApps">Try again</button>
  </div>
  <div v-else-if="appsLoaded && !canGenerate" class="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-sm">
    <span class="mr-auto">No app is connected to this Hub yet. Connect one to generate tools and preview what AI clients can use.</span>
    <RouterLink v-if="session.canWrite" to="/apps/new" class="btn-primary btn-sm">Connect app</RouterLink>
  </div>

  <SkillsPanel v-if="tab === 'skills'" :apps="allApps" @changed="(count: number) => (skillCount = count)" />
  <AgentViewPanel v-else-if="tab === 'agent'" :apps="allApps" :apps-loaded="appsLoaded" :apps-error="appsError" />

  <template v-else>
    <p v-if="error" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
    <LoadingSkeleton v-if="!loaded" label="Loading tools" />
    <template v-else-if="tab === 'capabilities'">
      <CapabilitiesPanel v-if="capabilities" :data="capabilities" />
      <p v-else-if="capabilitiesError" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ capabilitiesError }}</p>
    </template>
    <template v-else>
      <ToolsTable :tools="tools" :builtins="builtins" :usage="capabilities?.usage ?? {}" />
      <EmptyState v-if="!tools.length && !error" icon="tools" title="No app tools yet" class="mt-6"
                  text="The Hub tools in the table already work on every allowed data source. Generate tools from an app to give common questions a clear name.">
        <button v-if="session.canWrite && canGenerate" type="button" class="btn-primary" @click="generating = true">
          <AppIcon name="sparkles" :size="16" /> Generate from an app</button>
        <RouterLink v-if="session.canWrite" to="/tools/new" class="btn-secondary">Create one by hand</RouterLink>
      </EmptyState>
    </template>
  </template>

  <ToolGenerator v-if="generating" :apps="allApps" @close="generating = false" @done="loadTools()" />
</template>
