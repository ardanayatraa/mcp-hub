<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import PageHeader from "@/components/PageHeader.vue";
import SecretInput from "@/components/SecretInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppSummary, type DataSource, type Health } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage, slugify } from "@/utils/format";
import { useSlowFlag } from "@/utils/loading";

const router = useRouter();
const toast = useToast();
const step = ref(1);
const busy = ref(false);
const error = ref("");
const advanced = ref(false);
const keyEdited = ref(false);
const form = ref({
  name: "", app_key: "", environment: "dev", base_url: "", auth_type: "api_key", secret: "", delegation_secret: "",
  manifest_path: "/api/ai/v1/capabilities", health_path: "/api/ai/v1/health", timeout_ms: 5000, tls_verify: true,
  connector_type: "http_contract",
});
const app = ref<AppSummary | null>(null);
const delegation = ref("");
const check = ref<{ health: Health | null; syncing: boolean; sources: number; syncError: string }>({ health: null, syncing: false, sources: 0, syncError: "" });
// Set while the Hub is waiting on the app, so a slow answer shows a notice instead of a frozen screen.
const waiting = ref(false);
const slow = useSlowFlag(waiting);
const sources = ref<(DataSource & { allow: boolean })[]>([]);

watch(() => form.value.name, (name) => { if (!keyEdited.value) form.value.app_key = slugify(name); });

const sourceManaged = computed(() => form.value.connector_type === "source_managed");
const steps = computed(() => sourceManaged.value ? ["App details", "Check connection"] : ["App details", "Check connection", "Choose data"]);
const canNext = computed(() => form.value.name && form.value.app_key && form.value.base_url && form.value.secret.length >= 8);

async function runChecks() {
  if (!app.value) return;
  busy.value = true;
  waiting.value = true;
  check.value = { health: null, syncing: false, sources: 0, syncError: "" };
  try {
    check.value.health = await hub.testApp(app.value.id);
    if (check.value.health.status === "ok") {
      check.value.syncing = true;
      try {
        const synced = await hub.syncApp(app.value.id);
        check.value.sources = synced.modules.length;
      } catch (exc) {
        check.value.syncError = errorMessage(exc);
      } finally {
        check.value.syncing = false;
      }
    }
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
    waiting.value = false;
  }
}

async function save() {
  error.value = "";
  busy.value = true;
  try {
    if (!app.value) {
      const created = await hub.createApp({ ...form.value, delegation_secret: form.value.delegation_secret || "" });
      delegation.value = created.delegation_secret ?? "";
      app.value = created;
    } else {
      const { name, base_url, manifest_path, health_path, timeout_ms, tls_verify, connector_type } = form.value;
      await hub.updateApp(app.value.id, { name, base_url, manifest_path, health_path, timeout_ms, tls_verify, connector_type });
      if (form.value.secret) await hub.rotateSecret(app.value.id, { secret: form.value.secret });
    }
    step.value = 2;
    busy.value = false;
    await runChecks();
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}

async function toSources() {
  if (!app.value) return;
  busy.value = true;
  try {
    sources.value = (await hub.sources(app.value.id)).map((source) => ({ ...source, allow: true }));
    step.value = 3;
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}

async function finish() {
  if (!app.value) return;
  busy.value = true;
  error.value = "";
  try {
    for (const source of sources.value.filter((item) => !sourceManaged.value && item.allow && item.enableable_operations.includes("read"))) {
      await hub.updateSource(source.id, { enabled: true, operations: ["read"] });
    }
    await hub.appAction(app.value.id, "activate");
    toast.ok(`${form.value.name} is connected`);
    step.value = 4;
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <PageHeader title="Connect an app" back="/apps"
              subtitle="The app must implement the connector contract: an authenticated health check, a capability manifest and the reviewed routes it lists." />

  <ol v-if="step < 4" class="mb-6 flex flex-wrap gap-2">
    <li v-for="(label, index) in steps" :key="label" class="flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium"
        :class="step === index + 1 ? 'bg-brand-soft text-brand' : step > index + 1 ? 'bg-ok-soft text-ok' : 'bg-muted text-subtle'">
      <AppIcon v-if="step > index + 1" name="check" :size="14" /><span v-else>{{ index + 1 }}</span> {{ label }}
    </li>
  </ol>

  <p v-if="error" role="alert" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>

  <form v-if="step === 1" class="card card-pad max-w-3xl space-y-5" @submit.prevent="save">
    <div class="grid gap-4 sm:grid-cols-2">
      <label><span class="label">App name</span><input v-model="form.name" class="input" placeholder="Telixmart" required /></label>
      <label><span class="label">App key</span>
        <input v-model="form.app_key" class="input font-mono" pattern="[a-z][a-z0-9_]*" required :disabled="!!app" @input="keyEdited = true" />
        <span class="hint">Lowercase id. Must match <span class="code">application</span> in the app's manifest.</span></label>
      <label class="sm:col-span-2"><span class="label">Base URL</span>
        <input v-model="form.base_url" class="input" placeholder="https://telixmart.example.com" required />
        <span class="hint">The Hub only calls routes under this address that the app lists in its manifest.</span></label>
      <label><span class="label">Environment</span>
        <select v-model="form.environment" class="input" :disabled="!!app">
          <option value="dev">Development</option><option value="test">Test</option><option value="staging">Staging</option><option value="production">Production</option>
        </select></label>
      <div>
        <span class="label">Authentication</span>
        <div class="flex rounded-lg border border-line p-0.5">
          <button v-for="[value, label] in [['api_key', 'API key header'], ['bearer', 'Bearer token']]" :key="value" type="button"
                  class="flex-1 rounded-md px-3 py-1.5 text-xs font-medium" :class="form.auth_type === value ? 'bg-brand-soft text-brand' : 'text-subtle'"
                  :disabled="!!app" @click="form.auth_type = value">{{ label }}</button>
        </div>
      </div>
      <label class="sm:col-span-2"><span class="label">{{ form.auth_type === "api_key" ? "API key" : "Bearer token" }}</span>
        <SecretInput v-model="form.secret" :required="!app" minlength="8" maxlength="500"
                     :placeholder="app ? 'Leave blank to keep the saved secret' : 'Issued by the app for the Hub'" />
        <span class="hint">Stored encrypted. It is never shown again or sent to AI clients.</span></label>
      <label class="sm:col-span-2"><span class="label">Permission management</span>
        <select v-model="form.connector_type" class="input" :disabled="!!app">
          <option value="http_contract">Set up in Hub</option>
          <option value="source_managed">Follow application permissions automatically</option>
        </select>
      </label>
    </div>

    <button type="button" class="btn-ghost btn-sm" @click="advanced = !advanced">
      <AppIcon :name="advanced ? 'chevron-down' : 'chevron-right'" :size="14" /> Advanced settings
    </button>
    <div v-if="advanced" class="grid gap-4 rounded-lg bg-muted/60 p-4 sm:grid-cols-2">
      <label><span class="label">Manifest path</span><input v-model="form.manifest_path" class="input font-mono" /></label>
      <label><span class="label">Health path</span><input v-model="form.health_path" class="input font-mono" /></label>
      <label><span class="label">Timeout (ms)</span><input v-model.number="form.timeout_ms" class="input" type="number" min="100" max="30000" /></label>
      <label class="flex items-center gap-3 pt-6"><ToggleSwitch v-model="form.tls_verify" label="Verify TLS" /> Verify TLS certificate</label>
      <label v-if="!app" class="sm:col-span-2"><span class="label">User delegation secret (optional)</span>
        <SecretInput v-model="form.delegation_secret" />
        <span class="hint">Shared with the app to sign which user is asking. Leave blank and the Hub generates one and shows it once.</span></label>
    </div>

    <div class="flex justify-end gap-2 border-t border-line pt-4">
      <RouterLink to="/apps" class="btn-secondary">Cancel</RouterLink>
      <button class="btn-primary" type="submit" :disabled="busy || !canNext">
        <template v-if="busy"><span class="spinner" /> Saving…</template>
        <template v-else>Save and check <AppIcon name="chevron-right" :size="16" /></template>
      </button>
    </div>
  </form>

  <section v-else-if="step === 2" class="card card-pad max-w-3xl space-y-4">
    <div class="flex items-start gap-3 rounded-lg border border-line p-4">
      <span v-if="!check.health" class="spinner mt-0.5 h-5 w-5 text-brand" />
      <AppIcon v-else :name="check.health.status === 'ok' ? 'check' : 'alert'" :size="20"
               :class="check.health.status === 'ok' ? 'text-ok' : 'text-bad'" />
      <div class="min-w-0 flex-1">
        <p class="font-medium">Connection</p>
        <template v-if="!check.health">
          <p class="truncate text-sm text-subtle">Calling {{ form.base_url }}{{ form.health_path }}…</p>
          <span class="skeleton mt-2 h-2 w-2/3" aria-hidden="true" />
        </template>
        <p v-else-if="check.health.status === 'ok'" class="text-sm text-subtle">The app answered in {{ check.health.latency_ms }} ms and accepted the credential.</p>
        <p v-else class="text-sm text-bad">{{ check.health.hint || `Check failed (${check.health.error_category})` }}</p>
      </div>
    </div>
    <div v-if="check.health?.status === 'ok'" class="flex items-start gap-3 rounded-lg border border-line p-4">
      <span v-if="check.syncing" class="spinner mt-0.5 h-5 w-5 text-brand" />
      <AppIcon v-else :name="check.syncError ? 'alert' : 'database'" :size="20" :class="check.syncError ? 'text-bad' : 'text-ok'" />
      <div class="min-w-0 flex-1">
        <p class="font-medium">Contract</p>
        <template v-if="check.syncing">
          <p class="truncate text-sm text-subtle">Reading the manifest at {{ form.manifest_path }}…</p>
          <span class="skeleton mt-2 h-2 w-1/2" aria-hidden="true" />
        </template>
        <p v-else-if="check.syncError" class="text-sm text-bad">{{ check.syncError }}</p>
        <p v-else class="text-sm text-subtle">Found {{ check.sources }} data source{{ check.sources === 1 ? "" : "s" }}. {{ sourceManaged ? "Tools follow the application's saved permissions automatically." : "New ones stay off until you allow them." }}</p>
      </div>
    </div>
    <p v-if="slow" role="status" class="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-xs text-subtle">
      <AppIcon name="info" :size="14" /> Still waiting for {{ form.name || "the app" }}. The Hub gives each request up to {{ Math.round(form.timeout_ms / 1000) }} s; slow apps can take a moment.
    </p>
    <div v-if="delegation" class="rounded-lg border border-warn/40 bg-warn-soft p-4">
      <p class="font-medium text-ink">Save the user delegation secret now</p>
      <p class="mb-2 text-xs text-subtle">Configure it in the app so it can sign which user is asking. It is shown only once.</p>
      <div class="flex items-center gap-2"><code class="code flex-1 truncate py-1.5">{{ delegation }}</code><CopyButton :text="delegation" /></div>
    </div>
    <div class="flex justify-between gap-2 border-t border-line pt-4">
      <button type="button" class="btn-secondary" @click="step = 1">Edit details</button>
      <div class="flex gap-2">
        <button type="button" class="btn-secondary" :disabled="busy" @click="runChecks"><AppIcon name="refresh" :size="16" /> Retry</button>
        <button type="button" class="btn-primary" :disabled="busy || check.health?.status !== 'ok' || !!check.syncError || (!sourceManaged && !check.sources)" @click="sourceManaged ? finish() : toSources()">
          <span v-if="busy && check.health?.status === 'ok' && !check.syncing" class="spinner" />
          {{ sourceManaged ? "Activate app" : "Continue" }} <AppIcon name="chevron-right" :size="16" />
        </button>
      </div>
    </div>
  </section>

  <section v-else-if="step === 3" class="card card-pad max-w-3xl space-y-4">
    <div>
      <h2 class="section-title">Which data may AI clients read?</h2>
      <p class="text-xs text-subtle">Read access lets clients use run_report and the tools you publish for that data source. Field visibility and write operations can be set later on the app page.</p>
    </div>
    <ul class="divide-y divide-line rounded-lg border border-line">
      <li v-for="source in sources" :key="source.id" class="flex items-center justify-between gap-4 p-4">
        <div class="min-w-0">
          <p class="font-medium">{{ source.name }} <span class="font-mono text-xs text-subtle">{{ source.module_key }}</span></p>
          <p class="truncate text-xs text-subtle">{{ source.description || "No description" }}</p>
          <p class="mt-1 text-xs text-subtle">{{ source.fields.filter((field) => field.classification.startsWith("allowed")).length }} visible fields ·
            {{ source.fields.filter((field) => !field.classification.startsWith("allowed")).length }} hidden or totals-only</p>
        </div>
        <ToggleSwitch v-model="source.allow" :label="`Allow reading ${source.name}`" :disabled="!source.enableable_operations.includes('read')" />
      </li>
    </ul>
    <div class="flex justify-between gap-2 border-t border-line pt-4">
      <button type="button" class="btn-secondary" @click="step = 2">Back</button>
      <button type="button" class="btn-primary" :disabled="busy" @click="finish"><span v-if="busy" class="spinner" /> Activate app</button>
    </div>
  </section>

  <section v-else class="card card-pad max-w-2xl text-center">
    <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-ok-soft text-ok"><AppIcon name="check" :size="24" /></div>
    <h2 class="text-lg">{{ form.name }} is connected</h2>
    <p v-if="sourceManaged" class="mx-auto mt-1 max-w-md text-sm text-subtle">Models, permissions and tools follow the application automatically.</p>
    <p v-else class="mx-auto mt-1 max-w-md text-sm text-subtle">AI clients with a key for this app can already use <span class="code">list_data_sources</span> and <span class="code">run_report</span>. Publish named tools for the questions you expect most.</p>
    <div class="mt-5 flex flex-wrap justify-center gap-2">
      <RouterLink :to="`/apps/${app?.id}`" class="btn-secondary">Review fields</RouterLink>
      <RouterLink v-if="!sourceManaged" :to="`/tools/new?connector=${app?.id}`" class="btn-secondary">Create a tool</RouterLink>
      <button type="button" class="btn-primary" @click="router.push('/access')">Create a client key</button>
    </div>
  </section>
</template>
