<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import CodeBlock from "@/components/CodeBlock.vue";
import CopyButton from "@/components/CopyButton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import { hub, type AppSummary, type ConnectorEnrollment } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { dateTime, errorMessage } from "@/utils/format";
import { pairingCommand } from "@/utils/pairing";

const props = defineProps<{ app: AppSummary }>();
const emit = defineEmits<{ changed: []; state: [value: "paired" | "manual" | "error"] }>();
const session = useSession();
const toast = useToast();
const rows = ref<ConnectorEnrollment[]>([]);
const loaded = ref(false);
const error = ref("");
const busy = ref(false);
const confirm = ref<"" | "renew" | "replace" | "revoke">("");
const oneTime = ref<{ id: string; code: string } | null>(null);
const command = ref("");
const current = computed(() => rows.value.find(row => !row.replacement_id));
let stopped = false;
let sequence = 0;
let poll: ReturnType<typeof setTimeout> | undefined;
let expiry: ReturnType<typeof setTimeout> | undefined;

function clearCode() {
  oneTime.value = null;
  if (expiry) clearTimeout(expiry);
}

async function load() {
  if (stopped) return;
  const request = ++sequence;
  if (poll) clearTimeout(poll);
  try {
    const next = await hub.enrollments(props.app.id);
    if (stopped || request !== sequence) return;
    rows.value = next;
    emit("state", next.length ? "paired" : "manual");
    const issued = next.find(row => row.id === oneTime.value?.id);
    if (!issued || issued.status !== "pending") clearCode();
    error.value = "";
    if (current.value && ["pending", "claimed", "verifying", "failed"].includes(current.value.status)) {
      poll = setTimeout(load, 5000);
    }
  } catch (exc) {
    if (!stopped && request === sequence) { error.value = errorMessage(exc); emit("state", "error"); }
  } finally { if (!stopped && request === sequence) loaded.value = true; }
}
watch(() => props.app.id, () => { clearCode(); rows.value = []; loaded.value = false; void load(); }, { immediate: true });

async function act() {
  const row = current.value;
  const action = confirm.value;
  if (!row || !action) return;
  busy.value = true; error.value = ""; ++sequence;
  if (poll) clearTimeout(poll);
  try {
    if (action === "replace") {
      command.value = pairingCommand((await hub.system()).mcp_url, true);
      const next = await hub.replaceEnrollment(row.id);
      if (stopped) return;
      clearCode();
      const { code, ...metadata } = next;
      rows.value = [metadata, ...rows.value.filter(item => item.id !== next.id).map(item => item.id === row.id ? { ...item, replacement_id: next.id, status: "revoked" as const } : item)];
      const delay = Date.parse(next.expires_at) - Date.now();
      if (code && Number.isFinite(delay) && delay > 0) {
        oneTime.value = { id: next.id, code };
        expiry = setTimeout(clearCode, Math.min(delay, 2147483647));
      }
      toast.ok("Replacement pairing code ready");
    } else if (action === "renew") {
      await hub.renewEnrollment(row.id);
      toast.ok("Connection extended for 90 days; credentials preserved");
    } else {
      await hub.revokeEnrollment(row.id);
      clearCode();
      toast.ok("Pairing credentials revoked");
    }
    confirm.value = "";
    await load(); emit("changed");
  } catch (exc) { if (!stopped) error.value = errorMessage(exc); }
  finally { if (!stopped) busy.value = false; }
}

onBeforeUnmount(() => {
  stopped = true; ++sequence; clearCode();
  if (poll) clearTimeout(poll);
});
</script>

<template>
  <section v-if="!loaded || error || current" class="card card-pad space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div><h2 class="section-title">Laravel connection</h2><p class="text-xs text-subtle">Recover pairing or extend the existing connection without changing its access limits.</p></div>
      <button class="btn-ghost btn-sm" type="button" :disabled="busy" @click="load">Refresh pairing</button>
    </div>
    <p v-if="error" role="alert" class="rounded-lg bg-bad-soft p-3 text-sm text-bad">{{ error }}</p>
    <p v-if="!loaded" class="text-sm text-subtle">Loading pairing status…</p>
    <template v-if="current">
      <dl class="grid gap-3 text-sm sm:grid-cols-2">
        <div><dt class="text-xs text-subtle">Pairing status</dt><dd>{{ current.status.replaceAll('_', ' ') }}</dd></div>
        <div><dt class="text-xs text-subtle">{{ current.status === 'active' ? 'Access expires' : 'Pairing code expires' }}</dt><dd>{{ dateTime(current.status === 'active' ? current.management_expires_at : current.expires_at) }}</dd></div>
        <div class="sm:col-span-2"><dt class="text-xs text-subtle">Application URL</dt><dd class="break-all">{{ current.source_url }}</dd></div>
      </dl>
      <div v-if="oneTime?.id === current.id" class="space-y-3 rounded-lg border border-line p-4">
        <p class="text-sm">Run this in the existing Laravel installation, then paste the code into its hidden prompt:</p>
        <CodeBlock :code="command" />
        <CopyButton :text="oneTime.code" label="Copy replacement code" />
        <p class="text-xs text-subtle">Shown once on this page. Expires {{ dateTime(current.expires_at) }}. For a fresh installation, omit <code>--replace</code>.</p>
      </div>
      <p v-else-if="['pending', 'claimed', 'verifying', 'failed'].includes(current.status)" class="text-sm text-subtle">
        Run <code class="code">php artisan mcp-hub:connect --resume</code> in the paired installation. If its saved connection or code was lost, create a replacement.
      </p>
      <div v-if="session.canWrite && app.status !== 'archived'" class="flex flex-wrap gap-2">
        <button v-if="current.status === 'active'" class="btn-secondary" type="button" :disabled="busy" @click="confirm = 'renew'">Extend access</button>
        <button class="btn-secondary" type="button" :disabled="busy" @click="confirm = 'replace'">Replace pairing</button>
        <button v-if="current.status !== 'revoked'" class="btn-ghost text-bad" type="button" :disabled="busy" @click="confirm = 'revoke'">Revoke pairing</button>
      </div>
    </template>
    <ModalDialog v-if="confirm" :title="confirm === 'replace' ? 'Replace this connection?' : confirm === 'renew' ? 'Extend this connection?' : 'Revoke this connection?'" @close="!busy && (confirm = '')">
      <p v-if="confirm === 'replace'" class="text-sm">The current credentials will stop working. A new one-use code pairs the same application again and preserves its profile and tool restrictions. The old credentials cannot be recovered.</p>
      <p v-else-if="confirm === 'renew'" class="text-sm">Extend access for 90 days from now. The existing credentials, access profile, tool limits and model budgets are preserved.</p>
      <p v-else class="text-sm">Clients using this pairing will lose access. Other client keys remain unchanged. Reconnecting requires a replacement pairing.</p>
      <p v-if="error" role="alert" class="mt-3 text-sm text-bad">{{ error }}</p>
      <template #footer><button class="btn-secondary" type="button" :disabled="busy" @click="confirm = ''">Cancel</button>
        <button :class="confirm === 'renew' ? 'btn-primary' : 'btn-danger'" type="button" :disabled="busy" @click="act">{{ confirm === 'replace' ? 'Create replacement' : confirm === 'renew' ? 'Extend for 90 days' : 'Revoke credentials' }}</button></template>
    </ModalDialog>
  </section>
</template>
