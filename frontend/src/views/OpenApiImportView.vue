<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import { hub, type AppSummary, type OpenApiImport, type OpenApiPreview, type OpenApiSource } from "@/services/hub";
import { errorMessage } from "@/utils/format";

const apps = ref<AppSummary[]>([]);
const appId = ref("");
const mode = ref("document");
const format = ref<"json" | "yaml">("json");
const document = ref("");
const sourceUrl = ref("");
const preview = ref<OpenApiPreview | null>(null);
const result = ref<OpenApiImport | null>(null);
const selected = ref<string[]>([]);
const busy = ref(false);
const loaded = ref(false);
const error = ref("");
const confirming = ref(false);
const manualApps = computed(() => apps.value.filter(app => app.status !== "archived" && app.connector_type === "http_contract"));
const writeCount = computed(() => preview.value?.candidates.filter(item => selected.value.includes(item.id) && item.template !== "read").length ?? 0);
watch([appId, mode, format, document, sourceUrl], () => { preview.value = null; selected.value = []; result.value = null; });

onMounted(async () => {
  try { apps.value = await hub.apps(); appId.value = manualApps.value[0]?.id ?? ""; }
  catch (exc) { error.value = errorMessage(exc); }
  finally { loaded.value = true; }
});

function input(): OpenApiSource {
  return { connector_id: appId.value, format: format.value,
    ...(mode.value === "document" ? { document: document.value } : { source_url: sourceUrl.value }) };
}

async function chooseFile(event: Event) {
  const field = event.target as HTMLInputElement;
  const file = field.files?.[0];
  if (!file) return;
  if (file.size > 524288 || !/\.(json|ya?ml)$/i.test(file.name)) {
    error.value = "Choose a JSON or YAML file no larger than 512 KiB."; field.value = ""; return;
  }
  try {
    document.value = await file.text();
    format.value = /\.ya?ml$/i.test(file.name) ? "yaml" : "json";
    error.value = "";
  } catch { error.value = "The file could not be read."; }
}

async function inspect() {
  busy.value = true; error.value = ""; result.value = null; preview.value = null; selected.value = [];
  try { preview.value = await hub.previewOpenApi(input()); }
  catch (exc) { error.value = errorMessage(exc); }
  finally { busy.value = false; }
}

async function create() {
  if (!preview.value || !selected.value.length) return;
  busy.value = true; error.value = "";
  try {
    result.value = await hub.importOpenApi({ ...input(), fingerprint: preview.value.fingerprint, selected: selected.value });
    preview.value = null; selected.value = []; confirming.value = false;
  } catch (exc) { error.value = errorMessage(exc); }
  finally { busy.value = false; }
}
</script>

<template>
  <PageHeader title="Import OpenAPI" subtitle="Review operations from an API description, then create draft tools within the application's existing permissions.">
    <template #actions><RouterLink to="/tools" class="btn-secondary">View tools</RouterLink></template>
  </PageHeader>
  <p v-if="error" role="alert" class="mb-4 rounded-lg bg-bad-soft p-3 text-sm text-bad">{{ error }}</p>
  <p v-if="loaded && !manualApps.length" class="card card-pad text-sm text-subtle">No manually reviewed HTTP connection is available. Source-managed applications define their tools in the application itself.</p>
  <form v-if="manualApps.length" class="card card-pad space-y-4" @submit.prevent="inspect">
    <div class="grid gap-4 md:grid-cols-3">
      <label><span class="label">App</span><select v-model="appId" class="input" :disabled="busy" required><option v-for="app in manualApps" :key="app.id" :value="app.id">{{ app.name }} · {{ app.environment }}</option></select></label>
      <label><span class="label">Document source</span><select v-model="mode" class="input" :disabled="busy"><option value="document">Paste or upload file</option><option value="url">Approved HTTPS URL</option></select></label>
      <label><span class="label">Format</span><select v-model="format" class="input" :disabled="busy"><option value="json">JSON</option><option value="yaml">YAML</option></select></label>
    </div>
    <template v-if="mode === 'document'">
      <label class="block"><span class="label">JSON or YAML file</span><input type="file" accept=".json,.yaml,.yml" :disabled="busy" @change="chooseFile" /></label>
      <label class="block"><span class="label">API description</span><textarea v-model="document" class="input min-h-64 font-mono text-xs" :disabled="busy" required maxlength="524288" spellcheck="false" /></label>
    </template>
    <label v-else class="block"><span class="label">Document URL</span><input v-model="sourceUrl" type="url" pattern="https://.*" class="input" :disabled="busy" required maxlength="2048" placeholder="https://app.example.com/openapi.json" /><span class="hint">The host must be approved by the Hub's network policy. Application credentials are not sent.</span></label>
    <p class="text-xs text-subtle">OpenAPI 3.0–3.2, up to 512 KiB. Only approved routes and safe scalar fields are eligible. Imported tools remain drafts.</p>
    <div class="flex justify-end"><button class="btn-primary" type="submit" :disabled="busy || !appId">Preview operations</button></div>
  </form>
  <section v-if="preview" class="mt-6 space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3"><h2 class="section-title">Review operations</h2><span class="text-sm text-subtle">{{ selected.length }} selected · maximum 20</span></div>
    <p v-if="!preview.candidates.length" class="text-sm text-subtle">This document has no supported operation candidates.</p>
    <div v-for="candidate in preview.candidates" :key="candidate.id" class="card card-pad space-y-3">
      <label class="flex items-start gap-3"><input v-model="selected" type="checkbox" :value="candidate.id" :disabled="busy || !candidate.eligible || (selected.length >= 20 && !selected.includes(candidate.id))" class="mt-1" />
        <span class="min-w-0 flex-1"><span class="font-mono text-sm break-all">{{ candidate.method }} {{ candidate.path }}</span>
          <span class="ml-2" :class="!candidate.eligible ? 'badge-neutral' : candidate.template === 'read' ? 'badge-ok' : 'badge-warn'">{{ !candidate.eligible ? 'Ineligible' : candidate.template === 'read' ? 'Read' : 'Write draft' }}</span></span></label>
      <p v-if="candidate.reason" class="text-sm text-subtle">{{ candidate.reason }}</p>
      <template v-if="candidate.eligible">
        <dl class="grid gap-2 text-xs sm:grid-cols-2"><div><dt class="text-subtle">Data source</dt><dd>{{ candidate.module_key }}</dd></div>
          <div><dt class="text-subtle">Source authorization</dt><dd>{{ candidate.requires_user_context ? 'Signed-in user required' : 'Reviewed service access' }}</dd></div>
          <div><dt class="text-subtle">Reviewed inputs</dt><dd>{{ candidate.input_fields?.join(', ') || 'None' }}</dd></div>
          <div><dt class="text-subtle">AI-visible output</dt><dd>{{ candidate.output_fields?.join(', ') }}</dd></div>
          <div v-if="candidate.auth_requirements?.length"><dt class="text-subtle">Documented authentication</dt><dd>{{ candidate.auth_requirements.join(', ') }}</dd></div></dl>
        <p v-if="candidate.excluded_output_fields" class="text-xs text-subtle">{{ candidate.excluded_output_fields }} documented output fields excluded by the source contract or privacy policy.</p>
      </template>
    </div>
    <div class="flex justify-end"><button class="btn-primary" type="button" :disabled="busy || !selected.length" @click="confirming = true">Create selected drafts</button></div>
  </section>
  <section v-if="result" class="card card-pad mt-6 space-y-3"><h2 class="section-title">Drafts created</h2><p class="text-sm text-subtle">Review and test each tool before publishing. No module or operation was enabled by this import.</p>
    <ul class="space-y-2 text-sm"><li v-for="tool in result.created" :key="tool.id"><RouterLink :to="'/tools/' + tool.id" class="link">{{ tool.tool_key }}</RouterLink> <span class="badge-neutral">{{ tool.status }}</span></li></ul></section>
  <ModalDialog v-if="confirming" title="Create these draft tools?" @close="!busy && (confirming = false)">
    <p class="text-sm">Create {{ selected.length }} drafts using the current reviewed source constraints. {{ writeCount ? `${writeCount} are write operations and stay unavailable until separately tested and published.` : 'All selected operations are reads.' }}</p>
    <p class="mt-2 text-sm text-subtle">Existing tools are preserved. If any selection cannot be created, the entire import is rejected.</p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-bad">{{ error }}</p>
    <template #footer><button class="btn-secondary" type="button" :disabled="busy" @click="confirming = false">Cancel</button><button class="btn-primary" type="button" :disabled="busy" @click="create">Create drafts</button></template>
  </ModalDialog>
</template>
