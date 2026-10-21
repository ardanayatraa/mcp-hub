<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import ProviderDialog from "@/components/ProviderDialog.vue";
import SecretInput from "@/components/SecretInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type BuiltinProvider, type ModelProvider, type ProviderPreset } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage, timeAgo } from "@/utils/format";

// Models the Hub chat can use. Claude comes from the Hub's environment; super admins add the rest here.
const session = useSession();
const toast = useToast();
const builtin = ref<BuiltinProvider[]>([]);
const rows = ref<ModelProvider[]>([]);
const presets = ref<ProviderPreset[]>([]);
const loaded = ref(false);
const error = ref("");
const dialog = ref<{ provider?: ModelProvider } | null>(null);
const removing = ref<ModelProvider | null>(null);
const busy = ref("");
const canEdit = computed(() => session.isHubAdmin);
const claudeKey = ref("");

async function load() {
  try {
    const [listing, presetList] = await Promise.all([hub.providers(), hub.providerPresets()]);
    builtin.value = listing.builtin;
    rows.value = listing.providers;
    presets.value = presetList;
    error.value = "";
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    loaded.value = true;
  }
}
onMounted(load);

function replace(updated: ModelProvider) {
  const index = rows.value.findIndex((row) => row.id === updated.id);
  if (index >= 0) rows.value[index] = updated;
  else rows.value = [...rows.value, updated].sort((a, b) => a.name.localeCompare(b.name));
}

async function test(row: ModelProvider) {
  busy.value = `test:${row.id}`;
  try {
    const tested = await hub.testProvider(row.id);
    replace(tested);
    if (tested.status === "ok") toast.ok(tested.status_message);
    else toast.error(tested.status_message || "The provider did not answer");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

const keySource = (item: BuiltinProvider) => item.key_source === "hub"
  ? `Key saved in the Hub${item.api_key_hint ? ` (…${item.api_key_hint})` : ""}.`
  : item.key_source === "environment" ? `Key from ${item.configured_by} in the Hub's environment.` : "No key yet.";

function replaceBuiltin(updated: BuiltinProvider) {
  builtin.value = builtin.value.map((item) => (item.key === updated.key ? updated : item));
}

async function saveClaude() {
  busy.value = "claude:save";
  try {
    replaceBuiltin(await hub.saveClaudeKey(claudeKey.value.trim()));
    claudeKey.value = "";
    // Loading the model list checks the new key with Anthropic.
    const catalog = await hub.providerModels("anthropic", true);
    if (catalog.error) toast.error(`Key saved, but ${catalog.error}`);
    else toast.ok(`Claude key saved · ${catalog.models.length} models available`);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

async function clearClaude() {
  busy.value = "claude:clear";
  try {
    replaceBuiltin(await hub.clearClaudeKey());
    toast.ok("Saved Claude key removed");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

async function saved(provider: ModelProvider, created: boolean) {
  dialog.value = null;
  replace(provider);
  toast.ok(created ? `${provider.name} added` : `${provider.name} saved`);
  if (created || provider.status === "untested") await test(provider);
}

async function setEnabled(row: ModelProvider, enabled: boolean) {
  busy.value = `toggle:${row.id}`;
  try {
    replace(await hub.updateProvider(row.id, { enabled }));
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

async function remove() {
  const row = removing.value;
  if (!row) return;
  busy.value = `delete:${row.id}`;
  try {
    await hub.deleteProvider(row.id);
    rows.value = rows.value.filter((item) => item.id !== row.id);
    toast.ok(`${row.name} removed`);
    removing.value = null;
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = "";
  }
}

const statusInfo = (row: ModelProvider) => !row.enabled ? { label: "Off", tone: "badge-neutral" }
  : row.status === "ok" ? { label: "Connected", tone: "badge-ok" }
    : row.status === "error" ? { label: "Error", tone: "badge-bad" } : { label: "Not tested", tone: "badge-neutral" };
</script>

<template>
  <PageHeader title="AI providers" subtitle="The models an app's chat can use. Each app picks one on its Chat tab.">
    <template #actions>
      <button v-if="canEdit" class="btn-primary" type="button" @click="dialog = {}"><AppIcon name="plus" :size="16" /> Add provider</button>
    </template>
  </PageHeader>

  <p v-if="error" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
  <LoadingSkeleton v-else-if="!loaded" variant="rows" :count="4" label="Loading AI providers" />
  <div v-else class="space-y-6">
    <section class="grid gap-4 md:grid-cols-2">
      <div v-for="item in builtin" :key="item.key" class="card card-pad flex items-start gap-4">
        <div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted"><AppIcon name="sparkles" :size="18" /></div>
        <div class="min-w-0 flex-1">
          <p class="flex flex-wrap items-center gap-2 font-medium">{{ item.name }}
            <span :class="item.ready ? 'badge-ok' : 'badge-warn'">{{ item.ready ? "Ready" : "No key" }}</span></p>
          <template v-if="item.key === 'anthropic'">
            <p class="mt-1 text-xs text-subtle">{{ keySource(item) }}</p>
            <form v-if="canEdit" class="mt-3 flex flex-wrap items-center gap-2" @submit.prevent="saveClaude">
              <SecretInput v-model="claudeKey" class="min-w-0 flex-1" aria-label="Claude API key" maxlength="1000"
                           :placeholder="item.ready ? 'Paste a new key to replace it' : 'Paste the API key (sk-ant-…)'" />
              <button class="btn-primary" type="submit" :disabled="!claudeKey.trim() || busy !== ''">
                <span v-if="busy === 'claude:save'" class="spinner" /> Save</button>
              <button v-if="item.key_source === 'hub'" class="btn-ghost text-bad" type="button" :disabled="busy !== ''"
                      :title="`Remove the saved key; ${item.configured_by} applies again when set`" @click="clearClaude">
                <span v-if="busy === 'claude:clear'" class="spinner" /> Remove</button>
            </form>
          </template>
          <p v-else class="mt-1 text-xs text-subtle">Set by <code class="code">{{ item.configured_by }}</code> in the Hub's environment.
            {{ item.ready ? "" : "Add it and restart the Hub to use it." }} To manage its key here, add it as a provider instead.</p>
          <p v-if="item.used_by.length" class="mt-1 text-xs text-subtle">Used by {{ item.used_by.join(", ") }}</p>
        </div>
      </div>
    </section>

    <EmptyState v-if="!rows.length" icon="sparkles" title="No OpenAI-compatible providers yet"
                :text="canEdit ? 'Add OpenAI, OpenRouter, Groq, DeepSeek, Gemini, a company gateway or a local Ollama server.' : 'A super admin can add them.'" />
    <section v-else class="card divide-y divide-line">
      <article v-for="row in rows" :key="row.id" class="flex flex-wrap items-start gap-4 p-5">
        <div class="min-w-0 flex-1">
          <p class="flex flex-wrap items-center gap-2 font-medium">{{ row.name }} <span class="badge-outline font-mono">{{ row.key }}</span>
            <span :class="statusInfo(row).tone">{{ statusInfo(row).label }}</span></p>
          <p class="mt-1 truncate font-mono text-xs text-subtle">{{ row.base_url }}</p>
          <p class="mt-1.5 text-xs text-subtle">
            {{ row.auth_style === "none" ? "No key" : row.api_key_set ? `Key saved${row.api_key_hint ? ` (…${row.api_key_hint})` : ""}` : "No key yet" }}
            · {{ row.models.length ? `${row.models.length} models` : "Model list not loaded" }}
            <template v-if="row.default_model"> · default <span class="font-mono">{{ row.default_model }}</span></template>
            <template v-if="row.checked_at"> · tested {{ timeAgo(row.checked_at) }}</template>
          </p>
          <p v-if="row.status_message" class="mt-1 text-xs" :class="row.status === 'error' ? 'text-bad' : 'text-subtle'">{{ row.status_message }}</p>
          <p v-if="row.used_by.length" class="mt-1 text-xs text-subtle">Used by {{ row.used_by.join(", ") }}</p>
        </div>
        <div class="flex items-center gap-2">
          <ToggleSwitch :model-value="row.enabled" :label="`${row.name} on or off`" :disabled="!canEdit || busy !== ''"
                        @update:model-value="(on: boolean) => setEnabled(row, on)" />
          <template v-if="canEdit">
            <button class="btn-secondary" type="button" :disabled="busy !== ''" @click="test(row)">
              <span v-if="busy === `test:${row.id}`" class="spinner" /><AppIcon v-else name="plug" :size="16" /> Test</button>
            <button class="btn-ghost" type="button" :disabled="busy !== ''" @click="dialog = { provider: row }"><AppIcon name="pencil" :size="16" /> Edit</button>
            <button class="btn-ghost text-bad" type="button" :disabled="busy !== ''" :aria-label="`Remove ${row.name}`" @click="removing = row">
              <AppIcon name="trash" :size="16" /></button>
          </template>
        </div>
      </article>
    </section>

    <p class="text-xs text-subtle">Provider addresses follow the Hub's egress rules: private and loopback addresses (such as a local Ollama)
      only when <code class="code">EGRESS_ALLOW_PRIVATE</code> / <code class="code">EGRESS_ALLOW_LOOPBACK</code> allow them, and plain HTTP only when
      <code class="code">ALLOW_INSECURE_HTTP</code> is on.</p>
  </div>

  <ProviderDialog v-if="dialog" :provider="dialog.provider" :presets="presets" :taken="rows.map((row) => row.key)"
                  @close="dialog = null" @saved="saved" />
  <ModalDialog v-if="removing" :title="`Remove ${removing.name}?`" @close="busy || (removing = null)">
    <p class="text-sm text-subtle">{{ removing.used_by.length ? `It is used by ${removing.used_by.join(", ")}. Choose another provider on their Chat tab first.`
      : "The saved key is deleted. Apps can no longer choose this provider." }}</p>
    <template #footer>
      <button class="btn-secondary" type="button" :disabled="busy !== ''" @click="removing = null">Cancel</button>
      <button class="btn-danger" type="button" :disabled="busy !== '' || removing.used_by.length > 0" @click="remove">
        <span v-if="busy.startsWith('delete')" class="spinner" /> Remove</button>
    </template>
  </ModalDialog>
</template>
