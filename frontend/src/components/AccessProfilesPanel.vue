<script setup lang="ts">
import { computed, ref, watch } from "vue";

import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import { hub, type AppSummary, type DataSource, type McpAccessProfile, type Tool } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

const props = withDefaults(defineProps<{ apps: AppSummary[]; scoped?: boolean }>(), { scoped: false });
const emit = defineEmits<{ changed: [] }>();
const session = useSession();
const toast = useToast();
const appId = ref("");
const profiles = ref<McpAccessProfile[]>([]);
const sources = ref<DataSource[]>([]);
const tools = ref<Tool[]>([]);
const loaded = ref(false);
const loadError = ref("");
const busy = ref(false);
let loadRequest = 0;
const form = ref({ open: false, id: "", revision: 1, name: "Access profile", enabled: false,
                   modules: [] as string[], tools: [] as string[] });
const activeApps = computed(() => props.apps.filter((app) => app.status !== "archived"));
const selectedApp = computed(() => activeApps.value.find((app) => app.app_id === appId.value));
watch(activeApps, (apps) => {
  if (!apps.some((app) => app.app_id === appId.value)) appId.value = apps[0]?.app_id ?? "";
}, { immediate: true });

async function load() {
  const request = ++loadRequest;
  const app = selectedApp.value;
  profiles.value = []; sources.value = []; tools.value = [];
  loaded.value = false; loadError.value = "";
  if (!app) { loaded.value = true; return; }
  try {
    const [rows, modules, definitions] = await Promise.all([hub.profiles(app.app_id), hub.sources(app.id), hub.tools()]);
    if (request !== loadRequest) return;
    profiles.value = rows; sources.value = modules; tools.value = definitions.filter((tool) => tool.app_id === app.app_id);
  } catch (exc) {
    if (request === loadRequest) loadError.value = errorMessage(exc);
  } finally { if (request === loadRequest) loaded.value = true; }
}
watch(appId, () => { form.value.open = false; void load(); }, { immediate: true });
const choices = computed(() => [
  { name: "list_data_sources", title: "List data sources" }, { name: "run_report", title: "Run report" },
  { name: "recall_memory", title: "Recall memory" }, { name: "save_memory", title: "Save memory" },
  { name: "forget_memory", title: "Forget memory" },
  ...tools.value.filter((tool) => tool.status !== "archived").map((tool) => ({ name: tool.mcp_name, title: tool.display_title })),
]);

function edit(profile?: McpAccessProfile) {
  form.value = { open: true, id: profile?.id ?? "", revision: profile?.revision ?? 1, name: profile?.name ?? "Access profile",
    enabled: profile?.enabled ?? false, modules: [...(profile?.modules ?? [])], tools: [...(profile?.tools ?? [])] };
}

async function save() {
  if (!selectedApp.value) return;
  busy.value = true;
  const { id, revision, name, enabled, modules, tools: names } = form.value;
  try {
    const values = { name, enabled, modules, tools: names };
    if (id) await hub.updateProfile(id, { revision, ...values });
    else await hub.createProfile({ app_id: appId.value, ...values });
    form.value.open = false;
    toast.ok("Access profile saved");
    await load(); emit("changed");
  } catch (exc) { toast.error(errorMessage(exc)); }
  finally { busy.value = false; }
}
</script>

<template>
  <section class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div><h2 class="section-title">Access profiles</h2>
        <p class="text-xs text-subtle">Limit a client key to selected modules and tools. App permissions and user access still apply.</p></div>
      <button v-if="session.canWrite && selectedApp" class="btn-secondary" type="button"
              :disabled="!loaded || !!loadError" @click="edit()">Create profile</button>
    </div>
    <label v-if="!scoped && activeApps.length" class="block max-w-sm"><span class="label">App</span>
      <select v-model="appId" class="input"><option v-for="app in activeApps" :key="app.app_id" :value="app.app_id">{{ app.name }} · {{ app.environment }}</option></select></label>
    <LoadingSkeleton v-if="!loaded" label="Loading access profiles" />
    <div v-else-if="loadError" class="text-sm text-bad">{{ loadError }} <button class="btn-ghost btn-sm" type="button" @click="load">Retry</button></div>
    <p v-else-if="!profiles.length" class="text-sm text-subtle">{{ selectedApp ? 'No access profiles. Existing keys use their app permissions.' : 'Connect an app to create an access profile.' }}</p>
    <div v-else class="card overflow-x-auto">
      <table class="tbl"><thead><tr><th>Name</th><th>Modules</th><th>Tools</th><th>Keys</th><th>Status</th><th /></tr></thead>
        <tbody><tr v-for="profile in profiles" :key="profile.id">
          <td class="font-medium">{{ profile.name }}</td><td>{{ profile.modules.length }} selected</td><td>{{ profile.tools.length }} selected</td>
          <td>{{ profile.bound_keys }}</td><td><span :class="profile.enabled ? 'badge-ok' : 'badge-neutral'">{{ profile.enabled ? 'Enabled' : 'Disabled' }}</span></td>
          <td class="text-right"><button v-if="session.canWrite" class="btn-ghost btn-sm" type="button" @click="edit(profile)">Edit</button></td>
        </tr></tbody></table>
    </div>
    <ModalDialog v-if="form.open" :title="form.id ? 'Edit access profile' : 'Create access profile'" @close="form.open = false">
      <form id="profile-form" class="space-y-4" @submit.prevent="save">
        <label class="block"><span class="label">Name</span><input v-model="form.name" class="input" required maxlength="120" /></label>
        <label class="flex items-center gap-2 text-sm"><input v-model="form.enabled" type="checkbox" /> Profile enabled</label>
        <p v-if="!form.enabled" class="text-xs text-subtle">Keys bound to this profile cannot connect while it is disabled.</p>
        <fieldset><legend class="label">Modules</legend>
          <p class="mb-2 text-xs text-subtle">An empty selection allows no modules. Selecting a module keeps its existing permissions.</p>
          <div class="max-h-40 space-y-2 overflow-y-auto">
            <label v-for="source in sources" :key="source.module_key" class="flex items-center gap-2 text-sm">
              <input v-model="form.modules" type="checkbox" :value="source.module_key" /> {{ source.name }}</label>
          </div></fieldset>
        <fieldset><legend class="label">Tools</legend>
          <p class="mb-2 text-xs text-subtle">Only selected tools can be called. Write tools still require a write-enabled key and app approval.</p>
          <div class="max-h-56 space-y-2 overflow-y-auto">
            <label v-for="tool in choices" :key="tool.name" class="flex items-start gap-2 text-sm">
              <input v-model="form.tools" type="checkbox" :value="tool.name" class="mt-1" />
              <span>{{ tool.title }}<span class="block font-mono text-xs text-subtle">{{ tool.name }}</span></span></label>
          </div></fieldset>
        <p class="text-xs text-subtle">Changes affect every key bound to this profile on its next request.</p>
      </form>
      <template #footer><button class="btn-secondary" type="button" @click="form.open = false">Cancel</button>
        <button class="btn-primary" type="submit" form="profile-form" :disabled="busy">Save profile</button></template>
    </ModalDialog>
  </section>
</template>
