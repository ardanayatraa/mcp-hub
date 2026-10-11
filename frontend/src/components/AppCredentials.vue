<script setup lang="ts">
import { computed, ref } from "vue";

import SecretInput from "@/components/SecretInput.vue";
import { hub, type AppSummary, type Health } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { dateTime, errorMessage, timeAgo } from "@/utils/format";
import { useSlowFlag } from "@/utils/loading";

// The credential the app issued for the Hub. Write-only: it can be replaced and tested, never read back.
const props = defineProps<{ app: AppSummary }>();
const emit = defineEmits<{ changed: [] }>();
const session = useSession();
const toast = useToast();
const form = ref({ secret: "", delegation_secret: "" });
// verifying: testing a value just saved; testing: testing the stored value on request.
const step = ref<"" | "saving" | "verifying" | "testing">("");
const result = ref<(Health & { after_save: boolean }) | null>(null);
const checking = computed(() => step.value === "verifying" || step.value === "testing");
const slow = useSlowFlag(checking);

const editable = computed(() => session.canWrite && props.app.status !== "archived");
const keyLabel = computed(() => props.app.auth_type === "api_key" ? "API key" : "Bearer token");
// Mid-sentence form: "API key" keeps its capitals, "bearer token" does not.
const keyNoun = computed(() => props.app.auth_type === "api_key" ? "API key" : "bearer token");
const sentAs = computed(() => props.app.auth_type === "api_key" ? "X-API-Key header" : "Authorization: Bearer header");
const valid = computed(() => {
  const { secret, delegation_secret: delegation } = form.value;
  return Boolean(secret || delegation) && (!secret || secret.length >= 8) && (!delegation || delegation.length >= 8);
});

function generate() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  form.value.delegation_secret = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function check(afterSave: boolean) {
  step.value = afterSave ? "verifying" : "testing";
  result.value = null;
  const health = await hub.testApp(props.app.id);
  result.value = { ...health, after_save: afterSave };
}

async function save() {
  const body: { secret?: string; delegation_secret?: string } = {};
  if (form.value.secret) body.secret = form.value.secret;
  if (form.value.delegation_secret) body.delegation_secret = form.value.delegation_secret;
  let saved = false;
  step.value = "saving";
  result.value = null;
  try {
    await hub.rotateSecret(props.app.id, body);
    saved = true;
    form.value = { secret: "", delegation_secret: "" };
    toast.ok(body.secret ? `${keyLabel.value} saved` : "Delegation secret saved");
    if (body.secret) await check(true);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    step.value = "";
    if (saved) emit("changed");
  }
}

async function testSaved() {
  try {
    await check(false);
    emit("changed");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    step.value = "";
  }
}
</script>

<template>
  <section class="card">
    <header class="flex flex-wrap items-start justify-between gap-3 border-b border-line p-5">
      <div class="min-w-0">
        <h2 class="section-title">{{ app.name }} {{ keyLabel }}</h2>
        <p class="mt-1 max-w-2xl text-xs text-subtle">
          The credential {{ app.name }} issued for the Hub. It is stored encrypted, sent only to {{ app.name }}, and never shown again or given to AI clients.
        </p>
      </div>
      <span :class="app.secret_configured ? 'badge-ok' : 'badge-bad'">
        <AppIcon :name="app.secret_configured ? 'lock' : 'alert'" :size="12" /> {{ app.secret_configured ? "Stored" : "Revoked" }}
      </span>
    </header>

    <dl class="grid gap-4 border-b border-line p-5 sm:grid-cols-3">
      <div><dt class="text-xs text-subtle">Saved {{ keyNoun }}</dt>
        <dd class="mt-1 font-mono text-sm tracking-widest text-subtle">{{ app.secret_configured ? "••••••••••••" : "—" }}</dd></div>
      <div><dt class="text-xs text-subtle">Sent as</dt><dd class="mt-1 font-mono text-xs">{{ sentAs }}</dd></div>
      <div><dt class="text-xs text-subtle">Last updated</dt>
        <dd class="mt-1 text-sm" :title="dateTime(app.secret_updated_at)">{{ app.secret_updated_at ? timeAgo(app.secret_updated_at) : "—" }}</dd></div>
    </dl>

    <form v-if="editable" class="space-y-4 p-5" @submit.prevent="save">
      <div>
        <label class="label" for="app-secret">New {{ keyNoun }}</label>
        <SecretInput id="app-secret" v-model="form.secret" minlength="8" maxlength="500" :disabled="!!step"
                     :placeholder="`Paste the ${keyNoun} issued by ${app.name}`" />
        <p class="hint">Change it in {{ app.name }} first, then save it here. Saving tests the connection with the new value.</p>
      </div>
      <div>
        <label class="label" for="app-delegation">New user delegation secret <span class="font-normal text-subtle">(optional)</span></label>
        <div class="flex flex-wrap gap-2">
          <SecretInput id="app-delegation" v-model="form.delegation_secret" class="flex-1 basis-56" minlength="8" maxlength="500"
                       :disabled="!!step" placeholder="Leave blank to keep the current one" />
          <button type="button" class="btn-secondary" :disabled="!!step" @click="generate"><AppIcon name="sparkles" :size="16" /> Generate</button>
          <CopyButton v-if="form.delegation_secret" :text="form.delegation_secret" />
        </div>
        <p class="hint">{{ app.name }} uses it to sign which user is asking. Copy a generated value into {{ app.name }} before saving; it is not shown again.</p>
      </div>

      <div v-if="checking" role="status" class="flex items-start gap-3 rounded-lg border border-line p-3 text-sm">
        <span class="spinner mt-0.5 text-brand" />
        <div>
          <p>Testing the connection to {{ app.name }}…</p>
          <p v-if="slow" class="text-xs text-subtle">Still waiting. {{ app.name }} has up to {{ Math.round(app.timeout_ms / 1000) }} s to answer.</p>
        </div>
      </div>
      <div v-else-if="result" role="status" class="flex items-start gap-3 rounded-lg border p-3 text-sm"
           :class="result.status === 'ok' ? 'border-ok/40 bg-ok-soft' : 'border-bad/40 bg-bad-soft'">
        <AppIcon :name="result.status === 'ok' ? 'check' : 'alert'" :class="result.status === 'ok' ? 'text-ok' : 'text-bad'" />
        <p v-if="result.status === 'ok'">{{ app.name }} accepted the {{ result.after_save ? "new" : "saved" }} {{ keyNoun }} ({{ result.latency_ms }} ms).</p>
        <p v-else class="text-bad">{{ result.hint || `Connection failed (${result.error_category})` }}</p>
      </div>

      <div class="flex flex-wrap justify-end gap-2 border-t border-line pt-4">
        <button type="button" class="btn-secondary" :disabled="!!step || !app.secret_configured" @click="testSaved">
          <span v-if="step === 'testing'" class="spinner" /><AppIcon v-else name="plug" :size="16" /> Test saved key
        </button>
        <button type="submit" class="btn-primary" :disabled="!!step || !valid">
          <span v-if="step === 'saving' || step === 'verifying'" class="spinner" /><AppIcon v-else name="key" :size="16" />
          {{ step === "saving" ? "Saving…" : step === "verifying" ? "Testing…" : form.secret ? "Save and test" : "Save" }}
        </button>
      </div>
    </form>
    <p v-else class="p-5 text-xs text-subtle">
      {{ app.status === "archived" ? "Archived apps keep no usable credential." : "Only app admins can replace the credential." }}
    </p>
  </section>
</template>
