<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import CodeBlock from "@/components/CodeBlock.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import { hub, type AppSummary, type ClientKey, type SystemInfo, type Tool } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage, timeAgo, untilLabel } from "@/utils/format";

// Client keys let AI clients call one app's tools. `scoped` shows only the keys of apps[0].
const props = withDefaults(defineProps<{ apps: AppSummary[]; scoped?: boolean }>(), { scoped: false });
const session = useSession();
const toast = useToast();
const keys = ref<ClientKey[]>([]);
const tools = ref<Tool[]>([]);
const system = ref<SystemInfo | null>(null);
const loaded = ref(false);
const busy = ref(false);
const showRevoked = ref(false);

const keyForm = ref({ open: false, editing: "" as string, name: "AI assistant", app_id: "", ttl_days: 90, write: false, limit: false, allowed: [] as string[] });
const created = ref<ClientKey | null>(null);
const revoking = ref<ClientKey | null>(null);

const scopedApp = computed(() => props.scoped ? props.apps[0] : undefined);

async function load() {
  try {
    [keys.value, tools.value, system.value] = await Promise.all([hub.keys(scopedApp.value?.app_id), hub.tools(), hub.system()]);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    loaded.value = true;
  }
}
onMounted(load);

const visibleKeys = computed(() => keys.value.filter((key) => showRevoked.value || key.status === "active"));
const activeApps = computed(() => props.apps.filter((app) => app.status !== "archived"));
const appTools = computed(() => {
  const app = props.apps.find((item) => item.id === keyForm.value.app_id);
  const own = tools.value.filter((tool) => tool.app_id === app?.app_id && tool.status !== "archived")
    .map((tool) => ({ name: tool.mcp_name, label: tool.display_title, write: ["create", "update", "delete"].includes(tool.template) }));
  return [{ name: "list_data_sources", label: "List data sources", write: false }, { name: "run_report", label: "Run report", write: false },
          { name: "recall_memory", label: "Recall memory (when memory is on)", write: false },
          { name: "save_memory", label: "Save memory (when memory is on)", write: false },
          { name: "forget_memory", label: "Forget memory (when memory is on)", write: false }, ...own];
});
const snippet = computed(() => JSON.stringify({
  mcpServers: { "mcp-hub": { type: "http", url: system.value?.mcp_url, headers: { Authorization: `Bearer ${created.value?.token ?? "<client key>"}` } } },
}, null, 2));

function newKey() {
  keyForm.value = { open: true, editing: "", name: "AI assistant", app_id: activeApps.value[0]?.id ?? "", ttl_days: 90, write: false, limit: false, allowed: [] };
}

function editKey(key: ClientKey) {
  const app = props.apps.find((item) => item.app_id === key.app_id);
  keyForm.value = { open: true, editing: key.id, name: key.name, app_id: app?.id ?? "", ttl_days: 90, write: key.write,
                    limit: key.allowed_tools !== null, allowed: [...(key.allowed_tools ?? [])] };
}

async function saveKey() {
  busy.value = true;
  const form = keyForm.value;
  try {
    const allowed_tools = form.limit ? form.allowed : null;
    if (form.editing) {
      await hub.updateKey(form.editing, { name: form.name, write: form.write, allowed_tools });
      toast.ok("Client key updated");
    } else {
      const app = props.apps.find((item) => item.id === form.app_id);
      created.value = await hub.createKey({ name: form.name, app_key: app?.app_key, environment: app?.environment,
                                            ttl_days: form.ttl_days, write: form.write, allowed_tools });
    }
    keyForm.value.open = false;
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function revoke() {
  if (!revoking.value) return;
  busy.value = true;
  try {
    await hub.revokeKey(revoking.value.id);
    toast.ok("Key revoked: calls using it are refused immediately");
    revoking.value = null;
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div v-if="scoped">
        <h2 class="section-title">Client keys</h2>
        <p class="text-xs text-subtle">Keys AI clients use to call {{ scopedApp?.name }}'s tools through the Hub. Each is shown once.</p>
      </div>
      <label class="flex items-center gap-2 text-xs text-subtle" :class="scoped ? 'ml-auto' : ''">
        <input v-model="showRevoked" type="checkbox" /> Show revoked and expired</label>
      <button v-if="session.canWrite" class="btn-primary" type="button" :disabled="!activeApps.length" @click="newKey">
        <AppIcon name="plus" :size="16" /> Create client key</button>
    </div>

    <LoadingSkeleton v-if="!loaded" label="Loading client keys" />
    <EmptyState v-else-if="!visibleKeys.length" icon="key" title="No client keys"
                :text="scoped && !activeApps.length ? 'Archived apps cannot issue client keys.'
                  : 'A client key lets an AI client (an MCP client or your app\'s AI gateway) call this app\'s tools. It is shown once.'">
      <button v-if="session.canWrite && activeApps.length" class="btn-primary" type="button" @click="newKey">Create client key</button>
    </EmptyState>
    <div v-else class="card overflow-x-auto">
      <table class="tbl">
        <thead><tr><th>Name</th><th v-if="!scoped">App</th><th>Permissions</th><th>Tools</th><th>Last used</th><th>Status</th><th /></tr></thead>
        <tbody>
          <tr v-for="key in visibleKeys" :key="key.id">
            <td class="font-medium">{{ key.name }}</td>
            <td v-if="!scoped" class="text-xs">{{ key.app_name }}<p class="text-subtle">{{ key.environment }}</p></td>
            <td><span :class="key.write ? 'badge-warn' : 'badge-neutral'">{{ key.write ? "Read & write" : "Read" }}</span></td>
            <td class="text-xs">{{ key.allowed_tools === null ? "All allowed tools" : `${key.allowed_tools.length} selected` }}</td>
            <td class="text-xs text-subtle">{{ timeAgo(key.last_used_at) }}</td>
            <td class="text-xs">
              <span :class="key.status === 'active' ? 'badge-ok' : 'badge-neutral'">{{ key.status }}</span>
              <p v-if="key.status === 'active'" class="mt-1 text-subtle">{{ untilLabel(key.expires_at) }}</p>
            </td>
            <td class="whitespace-nowrap text-right">
              <template v-if="session.canWrite && key.status === 'active'">
                <button class="btn-ghost btn-sm" type="button" @click="editKey(key)">Edit</button>
                <button class="btn-ghost btn-sm text-bad" type="button" @click="revoking = key">Revoke</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ModalDialog v-if="keyForm.open" :title="keyForm.editing ? 'Edit client key' : 'Create client key'" @close="keyForm.open = false">
      <form id="key-form" class="space-y-4" @submit.prevent="saveKey">
        <label class="block"><span class="label">Name</span><input v-model="keyForm.name" class="input" required maxlength="120" placeholder="Support assistant" /></label>
        <label v-if="!scoped" class="block"><span class="label">App</span>
          <select v-model="keyForm.app_id" class="input" :disabled="!!keyForm.editing" required>
            <option v-for="app in activeApps" :key="app.id" :value="app.id">{{ app.name }} · {{ app.environment }}</option>
          </select></label>
        <label v-if="!keyForm.editing" class="block"><span class="label">Expires after</span>
          <select v-model.number="keyForm.ttl_days" class="input"><option :value="30">30 days</option><option :value="90">90 days</option><option :value="180">180 days</option><option :value="365">1 year</option></select></label>
        <label class="flex items-start gap-3 rounded-lg border border-line p-3">
          <input v-model="keyForm.write" type="checkbox" class="mt-0.5" />
          <span><span class="font-medium">Allow write tools</span>
            <span class="block text-xs text-subtle">Lets this key call published create, update and delete tools. The app still checks the user and may require confirmation.</span></span>
        </label>
        <div class="rounded-lg border border-line p-3">
          <label class="flex items-center gap-3"><input v-model="keyForm.limit" type="checkbox" /> <span class="font-medium">Only selected tools</span></label>
          <div v-if="keyForm.limit" class="mt-3 max-h-48 space-y-1.5 overflow-y-auto">
            <label v-for="tool in appTools" :key="tool.name" class="flex items-center gap-2 text-sm" :class="tool.write && !keyForm.write ? 'opacity-50' : ''">
              <input v-model="keyForm.allowed" type="checkbox" :value="tool.name" /> {{ tool.label }} <span class="font-mono text-xs text-subtle">{{ tool.name }}</span>
            </label>
          </div>
        </div>
      </form>
      <template #footer>
        <button class="btn-secondary" type="button" @click="keyForm.open = false">Cancel</button>
        <button class="btn-primary" type="submit" form="key-form" :disabled="busy || !keyForm.app_id">
          <span v-if="busy" class="spinner" /> {{ keyForm.editing ? "Save" : "Create key" }}</button>
      </template>
    </ModalDialog>

    <ModalDialog v-if="created" title="Client key created" @close="created = null">
      <div class="space-y-4">
        <div class="rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">Copy the key now. For security it is stored as a hash and cannot be shown again.</div>
        <div class="flex items-center gap-2"><code class="code flex-1 break-all py-2">{{ created.token }}</code><CopyButton :text="created.token ?? ''" /></div>
        <div>
          <p class="label">MCP client configuration</p>
          <CodeBlock :code="snippet" max-height="12rem" />
          <p class="hint">Apps that act for a signed-in user also send an <span class="code">X-Hub-Delegation</span> header signed with the app's delegation secret.</p>
        </div>
      </div>
      <template #footer><button class="btn-primary" type="button" @click="created = null">Done</button></template>
    </ModalDialog>

    <ModalDialog v-if="revoking" :title="`Revoke ${revoking.name}?`" @close="revoking = null">
      <p class="text-sm text-subtle">Clients using this key lose access immediately. This cannot be undone; create a new key if needed.</p>
      <template #footer>
        <button class="btn-secondary" type="button" @click="revoking = null">Cancel</button>
        <button class="btn-danger" type="button" :disabled="busy" @click="revoke"><span v-if="busy" class="spinner" /> Revoke key</button>
      </template>
    </ModalDialog>
  </section>
</template>
