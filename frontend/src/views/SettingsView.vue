<script setup lang="ts">
import { onMounted, ref } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import { hub, type SystemInfo } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

const toast = useToast();
const session = useSession();
const system = ref<SystemInfo | null>(null);
const busy = ref(false);
const pending = ref<unknown>(null);
const fileName = ref("");

onMounted(async () => {
  try {
    system.value = await hub.system();
  } catch (exc) {
    toast.error(errorMessage(exc));
  }
});

const POSTURE: [string, string, boolean][] = [
  ["mfa_required", "Two-step sign-in required", true],
  ["email_delivery_ready", "Activation email codes ready", true],
  ["secure_cookies", "Secure (HTTPS-only) session cookies", true],
  ["egress_allowlist", "Outbound calls limited to approved hosts", true],
  ["insecure_http_allowed", "Plain HTTP to apps allowed", false],
  ["private_egress_allowed", "Calls to private or local networks allowed", false],
];
const LIMITS: Record<string, string> = {
  records_per_call: "Records per source page / read call",
  report_max_records: "Records a report may read",
  report_timeout_seconds: "Report time budget (s)",
  tool_rate_limit: "Calls per key and tool per window",
  tool_rate_window_seconds: "Rate window (s)",
  audit_retention_days: "Activity retention (days)",
};

async function download() {
  busy.value = true;
  try {
    const document = await hub.exportBackup();
    const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }));
    const link = window.document.createElement("a");
    link.href = url;
    link.download = `mcp-hub-config-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast.ok("Configuration exported (secrets stay encrypted)");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function choose(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (file.size > 1_048_576) {
    toast.error("Backup files are limited to 1 MB; restore larger backups from a database dump.");
    return;
  }
  try {
    pending.value = JSON.parse(await file.text());
    fileName.value = file.name;
  } catch {
    toast.error("That file is not valid JSON.");
  }
}

async function restore() {
  busy.value = true;
  try {
    const counts = await hub.importBackup(pending.value);
    toast.ok(`Restored ${Object.values(counts).reduce((sum, count) => sum + count, 0)} records`);
    pending.value = null;
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

async function purge() {
  busy.value = true;
  try {
    const result = await hub.purge();
    toast.ok(`Removed ${Object.values(result.removed).reduce((sum, count) => sum + count, 0)} expired records`);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <PageHeader title="Settings" subtitle="How this Hub is configured. Runtime settings come from environment variables; see the README to change them." />

  <div v-if="system" class="grid gap-6 lg:grid-cols-2">
    <section class="card card-pad space-y-3">
      <h2 class="section-title">This Hub</h2>
      <dl class="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
        <dt class="text-subtle">Version</dt><dd>{{ system.version }}</dd>
        <dt class="text-subtle">Environment</dt><dd>{{ system.environment }}</dd>
        <dt class="text-subtle">MCP endpoint</dt><dd class="flex items-center gap-2"><span class="code truncate">{{ system.mcp_url }}</span><CopyButton :text="system.mcp_url" /></dd>
      </dl>
    </section>

    <section class="card card-pad space-y-3">
      <h2 class="section-title">Security posture</h2>
      <ul class="space-y-2 text-sm">
        <li v-for="[key, label, good] in POSTURE" :key="key" class="flex items-center gap-2">
          <AppIcon :name="system.security[key] === good ? 'check' : 'alert'" :size="16" :class="system.security[key] === good ? 'text-ok' : 'text-warn'" />
          <span>{{ label }}: <span class="font-medium">{{ system.security[key] ? "yes" : "no" }}</span></span>
        </li>
      </ul>
      <p class="text-xs text-subtle">Production refuses to start unless secure cookies, HTTPS, PostgreSQL and an egress allowlist are configured. Two-step sign-in is recommended.</p>
    </section>

    <section class="card card-pad space-y-3">
      <h2 class="section-title">Limits</h2>
      <dl class="grid grid-cols-[1fr_auto] gap-y-2 text-sm">
        <template v-for="(label, key) in LIMITS" :key="key"><dt class="text-subtle">{{ label }}</dt><dd class="font-mono">{{ system.limits[key] }}</dd></template>
      </dl>
    </section>

    <section class="card card-pad space-y-4">
      <h2 class="section-title">Backup and maintenance</h2>
      <div class="flex flex-wrap gap-2">
        <button class="btn-secondary" type="button" :disabled="busy" @click="download"><AppIcon name="download" :size="16" /> Export configuration</button>
        <label v-if="session.isRoot" class="btn-secondary cursor-pointer"><AppIcon name="upload" :size="16" /> Restore from file
          <input class="hidden" type="file" accept="application/json" @change="choose" /></label>
        <button class="btn-secondary" type="button" :disabled="busy" @click="purge"><AppIcon name="trash" :size="16" /> Purge expired records</button>
      </div>
      <p class="text-xs text-subtle">Exports contain apps, data sources, tools, tests and client key hashes. Secrets stay encrypted and need the same SECRET_ENCRYPTION_KEY. Purge removes activity and test history older than the retention period. Schedule database dumps for full recovery.</p>
    </section>
  </div>

  <ModalDialog v-if="pending" title="Restore configuration?" @close="pending = null">
    <p class="text-sm text-subtle">Replace the current apps, tools and keys with <span class="code">{{ fileName }}</span>. Take an export first if you may need the current state. Admin users and activity history are not changed.</p>
    <template #footer>
      <button class="btn-secondary" type="button" @click="pending = null">Cancel</button>
      <button class="btn-danger" type="button" :disabled="busy" @click="restore">Restore</button>
    </template>
  </ModalDialog>
</template>
