<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppCredentials from "@/components/AppCredentials.vue";
import AppSkillsPanel from "@/components/AppSkillsPanel.vue";
import ChatPanel from "@/components/ChatPanel.vue";
import DataSourcesPanel from "@/components/DataSourcesPanel.vue";
import ClientKeysPanel from "@/components/ClientKeysPanel.vue";
import DeleteAppDialog from "@/components/DeleteAppDialog.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import MemoryPanel from "@/components/MemoryPanel.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import TabBar from "@/components/TabBar.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import ToolGenerator from "@/components/ToolGenerator.vue";
import TryItPanel from "@/components/TryItPanel.vue";
import { hub, type AppDetail, type DataSource, type Tool, type ToolSwitches } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { appStatus, badgeClass, dateTime, errorMessage, timeAgo, toolStatus } from "@/utils/format";
import { kindStyle, TOOL_KINDS, toolKind } from "@/utils/toolKinds";
import { useSlowFlag } from "@/utils/loading";
import { useCatalogRefresh } from "@/utils/sources";

const route = useRoute();
const router = useRouter();
const session = useSession();
const toast = useToast();
const id = String(route.params.id);
const TABS = ["sources", "tools", "skills", "chat", "try", "keys", "memory", "connection", "history"];
// Skills that are on, reported by the Skills tab once it has loaded.
const skillsOn = ref<number | undefined>(undefined);
const tab = ref(TABS.includes(String(route.query.tab)) ? String(route.query.tab) : "sources");
const app = ref<AppDetail | null>(null);
const loadError = ref("");
const sources = ref<DataSource[]>([]);
const tools = ref<Tool[]>([]);
const catalogLoaded = ref(false);
// Which action is running, so only its button shows a spinner while the others wait.
const pending = ref("");
const busy = computed(() => pending.value !== "");
const slow = useSlowFlag(computed(() => pending.value === "test" || pending.value === "sync"));
const catalogError = ref("");
const edit = ref({ name: "", base_url: "", manifest_path: "", health_path: "", timeout_ms: 5000, tls_verify: true, connector_type: "http_contract" });
const confirm = ref<"" | "archive">("");
const deleting = ref(false);
const generating = ref(false);
// On/off per tool for this app. Null when the server predates switches.
const switches = ref<ToolSwitches | null>(null);
const switchFor = computed(() => new Map((switches.value?.tools ?? []).map((row) => [row.name, row])));
const hubTools = computed(() => (switches.value?.tools ?? []).filter((row) => row.kind !== "app"));


async function load(background = false) {
  if (background && busy.value) return;
  try {
    const nextApp = await hub.app(id);
    if (background && busy.value) return;
    app.value = nextApp;
    loadError.value = "";
    if (!background) {
      const { name, base_url, manifest_path, health_path, timeout_ms, tls_verify, connector_type } = nextApp;
      edit.value = { name, base_url, manifest_path, health_path, timeout_ms, tls_verify, connector_type };
    }
    if (nextApp.source_sync_error) throw new Error(nextApp.source_sync_error.message);
    const [nextSources, nextTools, nextSwitches] = await Promise.all([
      hub.sources(id), hub.tools(), hub.toolSwitches(id).catch(() => null)]);
    if (background && busy.value) return;
    switches.value = nextSwitches;
    const managed = nextApp.connector_type === "source_managed";
    sources.value = nextSources.filter((source) => !managed || source.enabled);
    tools.value = nextTools.filter((tool) => tool.connector_id === id && (!managed || tool.status === "published"));
    catalogError.value = "";
  } catch (exc) {
    if (!app.value) {
      loadError.value = errorMessage(exc);
      return;
    }
    sources.value = [];
    tools.value = [];
    catalogError.value = errorMessage(exc);
    if (!background) toast.error(catalogError.value);
  } finally {
    if (app.value) catalogLoaded.value = true;
  }
}
useCatalogRefresh(load, () => sourceManaged.value && !busy.value && !confirm.value && !deleting.value);

function retry() {
  loadError.value = "";
  void load();
}

watch(tab, (value) => {
  void router.replace({ query: { ...route.query, tab: value === "sources" ? undefined : value } });
});

function sourceSaved(updated: DataSource) {
  sources.value = sources.value.map((source) => (source.id === updated.id ? updated : source));
}

// One card per data source (plus one for the Hub's built-in tools); a card opens its tools in a modal.
const BUILT_IN = "__built_in";
const KIND_ORDER = Object.keys(TOOL_KINDS);
const toolGroups = computed(() => {
  // Every data source gets a card, also one whose tools do not exist yet.
  const groups = new Map<string, { key: string; name: string; source?: DataSource; tools: Tool[] }>(
    sources.value.map((source) => [source.module_key, { key: source.module_key, name: source.name, source, tools: [] }]));
  for (const tool of tools.value) {
    if (!groups.has(tool.module_key)) groups.set(tool.module_key, { key: tool.module_key, name: tool.module_name, tools: [] });
    groups.get(tool.module_key)?.tools.push(tool);
  }
  const order = (tool: Tool) => KIND_ORDER.indexOf(toolKind(tool.template, tool.tool_key));
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name))
    .map((group) => ({ ...group, tools: group.tools.sort((a, b) => order(a) - order(b) || a.display_title.localeCompare(b.display_title)) }));
});
const isOn = (name: string) => switchFor.value.get(name)?.enabled ?? true;
const groupKinds = (group: { tools: Tool[] }) => [...new Set(group.tools.map((tool) => toolKind(tool.template, tool.tool_key)))]
  .sort((a, b) => KIND_ORDER.indexOf(a) - KIND_ORDER.indexOf(b));
// Tools that are not live, by status: "Needs re-test: 5 · Draft: 1".
function statusNote(group: { tools: Tool[] }) {
  const counts = new Map<string, number>();
  for (const label of group.tools.map((tool) => toolStatus(tool).label).filter((label) => label !== "Live")) {
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts].map(([label, count]) => `${label}: ${count}`).join(" · ");
}
const openGroup = ref("");
const openSource = computed(() => toolGroups.value.find((group) => group.key === openGroup.value));
const emptyHint = computed(() => {
  if (sourceManaged.value) return `${app.value?.name} has no tools for it yet. They appear here by themselves once it publishes them.`;
  if (openSource.value?.source && !openSource.value.source.enabled) return "AI may not read it yet. Allow it on the Data sources tab, then generate its tools.";
  return "Generate its tools so AI clients can use it by name. run_report can already read it.";
});

async function showSource(key: string) {
  openGroup.value = "";
  await router.replace({ query: { ...route.query, source: key, tab: undefined } });
  tab.value = "sources";
}
const modalTitle = computed(() => openGroup.value === BUILT_IN ? "Built-in tools"
  : toolGroups.value.find((group) => group.key === openGroup.value)?.name ?? "");
const modalRows = computed<{ name: string; title: string; detail: string; kind: string; status: ReturnType<typeof toolStatus>;
  toolId?: string }[]>(() => {
  if (openGroup.value === BUILT_IN) {
    return hubTools.value.map((row) => ({ name: row.name, title: row.title, detail: row.live ? "" : row.note ?? "",
      kind: row.kind, status: row.live ? toolStatus({ status: "published", stale: false }) : { label: "Not live", tone: "neutral" } }));
  }
  return (toolGroups.value.find((group) => group.key === openGroup.value)?.tools ?? []).map((tool) => ({
    name: tool.mcp_name, title: tool.display_title, detail: tool.description, kind: toolKind(tool.template, tool.tool_key),
    status: toolStatus(tool), toolId: tool.id }));
});

async function run(action: string, task: () => Promise<unknown>, message: string) {
  pending.value = action;
  try {
    await task();
    toast.ok(message);
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

async function setSwitches(changes: Record<string, boolean>, message: string) {
  if (!Object.keys(changes).length) return;
  pending.value = "switch";
  try {
    switches.value = await hub.updateToolSwitches(id, changes);
    toast.ok(message);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

function switchGroup(on: boolean) {
  const changes = Object.fromEntries(modalRows.value.filter((row) => isOn(row.name) !== on).map((row) => [row.name, on]));
  const count = Object.keys(changes).length;
  void setSwitches(changes, `${count} tool${count === 1 ? "" : "s"} switched ${on ? "on" : "off"}`);
}

function setActive(on: boolean) {
  return run("status", () => hub.appAction(id, on ? "activate" : "pause"), on ? "App active" : "App paused: all its tools are blocked");
}

async function testConnection() {
  pending.value = "test";
  try {
    const result = await hub.testApp(id);
    if (result.status === "ok") toast.ok(`Connection OK (${result.latency_ms} ms)`);
    else toast.error(result.hint || `Connection failed: ${result.error_category}`);
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

async function sync() {
  pending.value = "sync";
  try {
    const result = await hub.syncApp(id);
    const changed = result.modules.filter((module) => module.change !== "unchanged");
    toast.ok(changed.length ? `Contract synced: ${changed.map((module) => `${module.name} ${module.change}`).join(", ")}` : "Contract synced, no changes");
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

async function saveConnection() {
  await run("save", () => hub.updateApp(id, edit.value), "Connection settings saved");
}

async function archive() {
  confirm.value = "";
  await run("archive", () => hub.appAction(id, "archive"), "App archived and its keys revoked");
}

const tabs = computed(() => [
  { key: "sources", label: "Data sources", count: catalogLoaded.value ? sources.value.length : undefined },
  { key: "tools", label: "Tools", count: catalogLoaded.value ? tools.value.length : undefined },
  { key: "skills", label: "Skills", count: skillsOn.value },
  { key: "chat", label: "Chat" },
  { key: "try", label: "Try it" },
  { key: "keys", label: "API keys" },
  { key: "memory", label: "Memory" },
  { key: "connection", label: "Connection" },
  { key: "history", label: "History" },
]);
const archived = computed(() => app.value?.status === "archived");
const sourceManaged = computed(() => app.value?.connector_type === "source_managed");
</script>

<template>
  <template v-if="app">
    <PageHeader :title="app.name" back="/apps">
      <template #subtitle>
        <span class="font-mono">{{ app.app_key }}</span> · {{ app.environment }} · {{ app.base_url }}
      </template>
      <template #actions>
        <span :class="badgeClass(appStatus[app.status]?.tone ?? 'neutral')">{{ appStatus[app.status]?.label ?? app.status }}</span>
        <template v-if="session.canWrite && !archived">
          <button class="btn-secondary" type="button" :disabled="busy" @click="testConnection">
            <span v-if="pending === 'test'" class="spinner" /><AppIcon v-else name="plug" :size="16" /> {{ pending === "test" ? "Testing…" : "Test" }}</button>
          <button class="btn-secondary" type="button" :disabled="busy" @click="sync">
            <span v-if="pending === 'sync'" class="spinner" /><AppIcon v-else name="refresh" :size="16" />
            {{ pending === "sync" ? "Syncing…" : sourceManaged ? "Refresh" : "Sync contract" }}</button>
          <button v-if="app.status === 'active'" class="btn-secondary" type="button" :disabled="busy" @click="setActive(false)">
            <span v-if="pending === 'status'" class="spinner" /><AppIcon v-else name="pause" :size="16" /> Pause</button>
          <button v-else class="btn-primary" type="button" :disabled="busy" @click="setActive(true)">
            <span v-if="pending === 'status'" class="spinner" /><AppIcon v-else name="play" :size="16" /> Activate</button>
        </template>
      </template>
    </PageHeader>

    <div v-if="app.status === 'draft'" class="mb-5 flex items-start gap-3 rounded-lg border border-warn/40 bg-warn-soft p-4 text-sm">
      <AppIcon name="alert" class="mt-0.5 text-warn" />
      <p>This app is not active yet. Test the connection and sync its contract, then activate it. Tools of inactive apps are never callable.</p>
    </div>
    <div v-if="app.circuit_open" class="mb-5 flex items-start gap-3 rounded-lg border border-bad/40 bg-bad-soft p-4 text-sm">
      <AppIcon name="alert" class="mt-0.5 text-bad" />
      <p>Calls are briefly suspended because the app failed {{ app.failure_count }} times in a row. They resume automatically.</p>
    </div>

    <div v-if="slow" role="status" class="mb-5 flex items-center gap-3 rounded-lg border border-line bg-surface p-3 text-sm text-subtle">
      <span class="spinner text-brand" />
      <p>Still waiting for {{ app.name }} to answer. Each request may take up to {{ Math.round(app.timeout_ms / 1000) }} s before the Hub gives up.</p>
    </div>
    <p v-if="catalogError" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ catalogError }}</p>
    <TabBar v-model="tab" :tabs="tabs" />
    <p v-if="sourceManaged && (tab === 'sources' || tab === 'tools')" class="mb-4 text-sm text-subtle">
      Models with Enabled and Read follow {{ app.name }} automatically.
    </p>

    <LoadingSkeleton v-if="!catalogLoaded && (tab === 'sources' || tab === 'tools')" :variant="tab === 'sources' ? 'panel' : 'rows'"
                     :count="tab === 'sources' ? 6 : 3" :label="tab === 'sources' ? 'Loading data sources' : 'Loading tools'" />

    <DataSourcesPanel v-else-if="tab === 'sources'" :sources="sources" :app-name="app.name"
                      :editable="session.canWrite && !archived" :managed="sourceManaged" @updated="sourceSaved" />

    <section v-else-if="tab === 'tools'" class="space-y-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="section-title">What the AI may use</h2>
          <p v-if="switches" class="text-xs text-subtle">{{ switches.reaching_ai }} tools reach AI clients and the chat now<template v-if="switches.off">
            · {{ switches.off }} switched off</template>. Open a card to switch its tools on or off.</p>
        </div>
        <span class="flex flex-wrap gap-2">
          <button v-if="session.canWrite && !archived" type="button" class="btn-secondary" @click="generating = true">
            <AppIcon :name="sourceManaged ? 'refresh' : 'sparkles'" :size="16" /> {{ sourceManaged ? "Refresh tools" : "Generate tools" }}</button>
          <RouterLink v-if="!sourceManaged && session.canWrite && !archived" :to="`/tools/new?connector=${id}`" class="btn-primary"><AppIcon name="plus" :size="16" /> New tool</RouterLink>
        </span>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <button v-for="group in toolGroups" :key="group.key" type="button"
                class="card card-pad flex flex-col text-left transition hover:border-brand/50" @click="openGroup = group.key">
          <span class="flex items-center justify-between gap-2">
            <span class="truncate font-medium">{{ group.name }}</span>
            <span v-if="!group.tools.length" class="badge-neutral">No tools</span>
            <span v-else :class="group.tools.some((tool) => isOn(tool.mcp_name)) ? 'badge-ok' : 'badge-neutral'">
              {{ group.tools.filter((tool) => isOn(tool.mcp_name)).length }}/{{ group.tools.length }} on</span>
          </span>
          <span v-if="group.tools.length" class="mt-3 flex flex-wrap gap-1.5">
            <span v-for="kind in groupKinds(group)" :key="kind" class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium"
                  :class="kindStyle(kind).tile"><AppIcon :name="kindStyle(kind).icon" :size="12" /> {{ kindStyle(kind).label }}</span>
          </span>
          <span v-if="!group.tools.length" class="mt-3 block text-xs text-subtle">
            {{ group.source && !group.source.enabled && !sourceManaged ? "Not allowed for AI yet" : "No tools yet" }}</span>
          <span v-else-if="statusNote(group)" class="mt-2 block text-xs text-subtle">{{ statusNote(group) }}</span>
        </button>
        <button v-if="hubTools.length" type="button" class="card card-pad flex flex-col text-left transition hover:border-brand/50"
                @click="openGroup = BUILT_IN">
          <span class="flex items-center justify-between gap-2">
            <span class="truncate font-medium">Built-in tools</span>
            <span :class="hubTools.some((row) => row.enabled) ? 'badge-ok' : 'badge-neutral'">
              {{ hubTools.filter((row) => row.enabled).length }}/{{ hubTools.length }} on</span>
          </span>
          <span class="mt-3 flex flex-wrap gap-1.5">
            <span v-for="row in hubTools" :key="row.name" class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium"
                  :class="kindStyle(row.kind).tile"><AppIcon :name="kindStyle(row.kind).icon" :size="12" /> {{ row.title }}</span>
          </span>
        </button>
      </div>
      <EmptyState v-if="!tools.length" icon="tools" :title="sourceManaged ? 'No models allowed' : 'No custom tools yet'"
                  :text="sourceManaged ? 'Allow a model in the application to make its tools available.' : 'AI clients can already use run_report on allowed data sources. Generate named tools for every published route, or add one by hand.'" />

      <ModalDialog v-if="openGroup" :title="modalTitle" @close="openGroup = ''">
        <div v-if="!modalRows.length" class="rounded-lg bg-muted p-4">
          <p class="text-sm font-medium">No tools for {{ modalTitle }} yet</p>
          <p class="mt-1 text-xs text-subtle">{{ emptyHint }}</p>
        </div>
        <p v-else class="mb-2 text-xs text-subtle">A switched-off tool is hidden and refused for every key of {{ app.name }} and its chat.</p>
        <ul v-if="modalRows.length" class="divide-y divide-line">
          <li v-for="row in modalRows" :key="row.name" class="flex items-center gap-3 py-3">
            <ToggleSwitch v-if="switches" :model-value="isOn(row.name)" :label="`${row.title} on or off`" :disabled="!session.canWrite || archived || busy"
                          @update:model-value="(on: boolean) => setSwitches({ [row.name]: on }, `${row.title} switched ${on ? 'on' : 'off'}`)" />
            <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md" :class="kindStyle(row.kind).tile"><AppIcon :name="kindStyle(row.kind).icon" :size="15" /></span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium">{{ row.title }}</span>
              <span v-if="row.detail" class="block truncate text-xs text-subtle">{{ row.detail }}</span>
            </span>
            <span v-if="!isOn(row.name)" class="badge-neutral">Off</span>
            <span v-else :class="badgeClass(row.status.tone)">{{ row.status.label }}</span>
            <RouterLink v-if="row.toolId" :to="`/tools/${row.toolId}`" class="btn-ghost btn-sm" :aria-label="`Open ${row.title}`">
              <AppIcon name="chevron-right" :size="16" /></RouterLink>
          </li>
        </ul>
        <template #footer>
          <template v-if="!modalRows.length && !sourceManaged && session.canWrite && !archived">
            <button v-if="openSource?.source && !openSource.source.enabled" type="button" class="btn-secondary" @click="showSource(openGroup)">
              Open in Data sources</button>
            <button v-else type="button" class="btn-secondary" @click="openGroup = ''; generating = true">
              <AppIcon name="sparkles" :size="16" /> Generate tools</button>
          </template>
          <template v-if="modalRows.length && switches && session.canWrite && !archived">
            <button type="button" class="btn-ghost" :disabled="busy" @click="switchGroup(false)">All off</button>
            <button type="button" class="btn-ghost" :disabled="busy" @click="switchGroup(true)"><AppIcon name="power" :size="16" /> All on</button>
          </template>
          <button type="button" class="btn-primary" @click="openGroup = ''">Done</button>
        </template>
      </ModalDialog>
    </section>

    <AppSkillsPanel v-else-if="tab === 'skills'" :app="app" :editable="session.canWrite && !archived" @changed="(count: number) => (skillsOn = count)" />

    <ChatPanel v-else-if="tab === 'chat'" :app="app" @try="tab = 'try'" />

    <TryItPanel v-else-if="tab === 'try'" :app="app" @settings="tab = 'chat'" />

    <section v-else-if="tab === 'keys'" class="space-y-8">
      <AppCredentials :app="app" @changed="load()" />
      <ClientKeysPanel :apps="[app]" scoped />
    </section>

    <MemoryPanel v-else-if="tab === 'memory'" :app="app" />

    <section v-else-if="tab === 'connection'" class="grid gap-6 lg:grid-cols-3">
      <form class="card card-pad space-y-4 lg:col-span-2" @submit.prevent="saveConnection">
        <h2 class="section-title">Connection settings</h2>
        <fieldset :disabled="!session.canWrite || archived || busy" class="grid gap-4 sm:grid-cols-2">
          <label><span class="label">Name</span><input v-model="edit.name" class="input" required /></label>
          <label><span class="label">Timeout (ms)</span><input v-model.number="edit.timeout_ms" class="input" type="number" min="100" max="30000" /></label>
          <label class="sm:col-span-2"><span class="label">Permission management</span>
            <select v-model="edit.connector_type" class="input">
              <option value="http_contract">Set up in Hub</option>
              <option value="source_managed">Follow application permissions automatically</option>
            </select>
          </label>
          <label class="sm:col-span-2"><span class="label">Base URL</span><input v-model="edit.base_url" class="input" required />
            <span class="hint">Changing the address or manifest path returns the app to setup: test, sync and review again.</span></label>
          <label><span class="label">Manifest path</span><input v-model="edit.manifest_path" class="input font-mono" /></label>
          <label><span class="label">Health path</span><input v-model="edit.health_path" class="input font-mono" /></label>
          <label class="flex items-center gap-3"><ToggleSwitch v-model="edit.tls_verify" label="Verify TLS" /> Verify TLS certificate</label>
        </fieldset>
        <div v-if="session.canWrite && !archived" class="flex justify-end border-t border-line pt-4">
          <button class="btn-primary" type="submit" :disabled="busy"><span v-if="pending === 'save'" class="spinner" /> Save settings</button>
        </div>
      </form>
      <div class="space-y-6">
        <div class="card card-pad space-y-3">
          <h2 class="section-title">Credential</h2>
          <p class="text-xs text-subtle">Bearer token ·
            <span :class="app.secret_configured ? 'text-ok' : 'text-bad'">{{ app.secret_configured ? "stored" : "revoked" }}</span>
            <template v-if="app.secret_updated_at"> · updated {{ timeAgo(app.secret_updated_at) }}</template></p>
          <button class="btn-secondary w-full" type="button" @click="tab = 'keys'"><AppIcon name="key" :size="16" /> Manage API keys</button>
        </div>
        <div v-if="session.canWrite" class="card card-pad space-y-3 border-bad/30">
          <h2 class="section-title text-bad">Danger zone</h2>
          <p class="text-xs text-subtle">Archiving revokes the credential and this app's client keys, and retires its tools. Deleting also removes the app's configuration from the Hub; audit history is kept.</p>
          <button v-if="!archived" class="btn-secondary w-full" type="button" :disabled="busy" @click="confirm = 'archive'">
            <span v-if="pending === 'archive'" class="spinner" /><AppIcon v-else name="archive" :size="16" /> Archive app</button>
          <button class="btn-danger w-full" type="button" :disabled="busy" @click="deleting = true"><AppIcon name="trash" :size="16" /> Delete app</button>
        </div>
      </div>
    </section>

    <section v-else class="grid gap-6 lg:grid-cols-2">
      <div class="card card-pad">
        <h2 class="section-title mb-3">Connection checks</h2>
        <ul v-if="app.health_history.length" class="divide-y divide-line">
          <li v-for="row in app.health_history" :key="row.created_at" class="flex items-center gap-3 py-2 text-xs">
            <span :class="row.status === 'ok' ? 'badge-ok' : 'badge-bad'">{{ row.status }}</span>
            <span class="flex-1 text-subtle">{{ row.status === "ok" ? `${row.latency_ms} ms` : row.hint || row.error_category }}</span>
            <span class="text-subtle">{{ dateTime(row.created_at) }}</span>
          </li>
        </ul>
        <p v-else class="text-sm text-subtle">No checks yet.</p>
      </div>
      <div class="card card-pad">
        <h2 class="section-title mb-3">Contract versions</h2>
        <ul v-if="app.contracts.length" class="divide-y divide-line">
          <li v-for="row in app.contracts" :key="row.hash" class="py-2 text-xs">
            <p><span class="font-medium">{{ row.version }}</span> <span class="text-subtle">· {{ dateTime(row.created_at) }}</span></p>
            <p class="text-subtle">{{ row.modules.join(", ") }}</p>
          </li>
        </ul>
        <p v-else class="text-sm text-subtle">Sync the contract to record its first version.</p>
      </div>
    </section>

    <ModalDialog v-if="confirm" :title="`Archive ${app.name}?`" @close="confirm = ''">
      <p class="text-sm text-subtle">All tools of this app stop immediately, its credential and client keys are revoked. This cannot be undone.</p>
      <template #footer>
        <button class="btn-secondary" type="button" @click="confirm = ''">Cancel</button>
        <button class="btn-danger" type="button" :disabled="busy" @click="archive">Archive</button>
      </template>
    </ModalDialog>

    <ToolGenerator v-if="generating" :apps="[app]" :connector-id="id" @close="generating = false" @done="load()" />

    <DeleteAppDialog v-if="deleting" :app="app" @close="deleting = false" @deleted="router.push('/apps')"
                     @changed="deleting = false; load()" />
  </template>

  <div v-else-if="loadError" class="card card-pad mx-auto max-w-lg text-center">
    <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-bad-soft text-bad"><AppIcon name="alert" :size="22" /></div>
    <h2 class="text-base">This app could not be loaded</h2>
    <p class="mt-1 text-sm text-subtle">{{ loadError }}</p>
    <div class="mt-4 flex justify-center gap-2">
      <RouterLink to="/apps" class="btn-secondary">Back to apps</RouterLink>
      <button class="btn-primary" type="button" @click="retry"><AppIcon name="refresh" :size="16" /> Try again</button>
    </div>
  </div>

  <div v-else aria-label="Loading app">
    <div class="mb-6 space-y-3" aria-hidden="true">
      <span class="skeleton h-3 w-12" />
      <span class="skeleton h-6 w-56" />
      <span class="skeleton h-4 w-80 max-w-full" />
    </div>
    <div class="mb-5 flex gap-4 border-b border-line pb-3" aria-hidden="true">
      <span v-for="n in 5" :key="n" class="skeleton h-4 w-20" />
    </div>
    <LoadingSkeleton variant="panel" :count="6" label="Loading app" />
  </div>
</template>
