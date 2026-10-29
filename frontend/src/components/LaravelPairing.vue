<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import CodeBlock from "@/components/CodeBlock.vue";
import CopyButton from "@/components/CopyButton.vue";
import { hub, type ConnectorEnrollment } from "@/services/hub";
import { errorMessage, slugify } from "@/utils/format";
import { pairingCommand } from "@/utils/pairing";

const form = ref({ name: "", app_key: "", environment: "dev", base_url: "" });
const enrollment = ref<ConnectorEnrollment | null>(null);
const hubUrl = ref("");
const busy = ref(false);
const error = ref("");
const editedKey = ref(false);
let stopped = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let codeExpiry: ReturnType<typeof setTimeout> | undefined;
let checking = false;
watch(() => form.value.name, name => { if (!editedKey.value) form.value.app_key = slugify(name); });
const command = computed(() => hubUrl.value ? pairingCommand(hubUrl.value) : "");
const labels: Record<string, string> = {
  pending: "Waiting for the Laravel application", claimed: "Credentials received by the application",
  verifying: "Checking the source connection", failed: "Source checks need attention",
  active: "Application connected", expired: "Pairing expired", revoked: "Pairing revoked",
};

async function refresh() {
  if (!enrollment.value || stopped || checking) return;
  if (timer) clearTimeout(timer);
  checking = true;
  try {
    const next = await hub.enrollment(enrollment.value.id);
    if (stopped) return;
    enrollment.value = { ...next, code: next.status === "pending" ? enrollment.value.code : undefined };
    error.value = "";
    if (!["active", "expired", "revoked"].includes(next.status)) timer = setTimeout(refresh, 3000);
  } catch (exc) {
    if (!stopped) error.value = errorMessage(exc);
  } finally {
    checking = false;
  }
}

async function create() {
  busy.value = true;
  error.value = "";
  try {
    const system = await hub.system();
    const url = new URL(system.mcp_url);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || /[^A-Za-z0-9._~%:/\[\]-]/.test(url.href)) {
      throw new Error("The Hub connection URL is invalid.");
    }
    hubUrl.value = url.href.replace(/\/$/, "");
    enrollment.value = await hub.createEnrollment(form.value);
    const delay = Date.parse(enrollment.value.expires_at) - Date.now();
    if (codeExpiry) clearTimeout(codeExpiry);
    if (Number.isFinite(delay) && delay > 0) codeExpiry = setTimeout(() => {
      if (enrollment.value) enrollment.value = { ...enrollment.value, code: undefined };
    }, Math.min(delay, 2147483647));
    else enrollment.value = { ...enrollment.value, code: undefined };
    timer = setTimeout(refresh, 3000);
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}

async function revoke() {
  if (!enrollment.value) return;
  busy.value = true;
  error.value = "";
  try {
    const next = await hub.revokeEnrollment(enrollment.value.id);
    enrollment.value = next;
    if (timer) clearTimeout(timer);
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}

onBeforeUnmount(() => {
  stopped = true;
  if (timer) clearTimeout(timer);
  if (codeExpiry) clearTimeout(codeExpiry);
  enrollment.value = null;
});
</script>

<template>
  <section class="card card-pad max-w-3xl space-y-5">
    <div>
      <h2 class="section-title">Connect the Laravel package</h2>
      <p class="mt-1 text-sm text-subtle">Create a one-use code, then enter it in the application's terminal.
        The Hub checks its health and permissions before activating the connection.</p>
    </div>
    <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
    <form v-if="!enrollment" class="space-y-5" @submit.prevent="create">
      <div class="grid gap-4 sm:grid-cols-2">
        <label><span class="label">App name</span><input v-model="form.name" class="input" maxlength="200" required placeholder="Your App" /></label>
        <label><span class="label">App key</span><input v-model="form.app_key" @input="editedKey = true" class="input font-mono"
          maxlength="64" pattern="[a-z][a-z0-9_]*" required /></label>
        <label class="sm:col-span-2"><span class="label">Application URL</span><input v-model="form.base_url" type="url" class="input"
          maxlength="500" required placeholder="https://app.example.com" /><span class="hint">Use the application's configured public URL.
          Its host must already be permitted by the Hub's network policy.</span></label>
        <label><span class="label">Environment</span><select v-model="form.environment" class="input">
          <option value="dev">Development</option><option value="test">Test</option>
          <option value="staging">Staging</option><option value="production">Production</option>
        </select></label>
      </div>
      <div class="flex justify-end">
        <button class="btn-primary" type="submit" :disabled="busy"><span v-if="busy" class="spinner" /> Create pairing code</button>
      </div>
    </form>
    <template v-else>
      <div class="rounded-lg border border-line p-4" role="status">
        <p class="font-medium">{{ labels[enrollment.status] || enrollment.status }}</p>
        <p class="mt-1 text-xs text-subtle">{{ enrollment.source_url }} · Code expires {{ new Date(enrollment.expires_at).toLocaleString() }}</p>
      </div>
      <template v-if="enrollment.code">
        <p class="text-sm text-subtle">With the package installed, run this in the Laravel project:</p>
        <CodeBlock :code="command" />
        <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line p-4">
          <span class="text-sm">Paste the code into the hidden terminal prompt.</span>
          <CopyButton :text="enrollment.code" label="Copy one-use code" />
        </div>
        <p class="text-xs text-subtle">The code is shown on this page only and is cleared after it is claimed.</p>
      </template>
      <p v-if="enrollment.status === 'failed'" class="text-sm text-subtle">
        Check the package's configuration and run <code class="code">php artisan mcp-hub:connect --resume</code>.
      </p>
      <p v-if="enrollment.status === 'active'" class="text-sm text-subtle">
        Data access follows the application's reviewed resources and permissions.
        Chat, allowed models and budgets can be configured on the app page.
      </p>
      <div class="flex flex-wrap gap-2">
        <RouterLink :to="'/apps/' + enrollment.connector_id" class="btn-primary">Open application</RouterLink>
        <button v-if="!['active','expired','revoked'].includes(enrollment.status)" type="button" class="btn-secondary" :disabled="busy" @click="refresh">Refresh status</button>
        <button v-if="['pending','claimed','failed'].includes(enrollment.status)" type="button" class="btn-secondary" :disabled="busy" @click="revoke">Revoke pending pairing</button>
      </div>
    </template>
  </section>
</template>
