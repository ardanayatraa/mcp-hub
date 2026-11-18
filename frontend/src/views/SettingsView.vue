<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import PageHeader from "@/components/PageHeader.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type HubSettings, type SealedBackup, type SmtpDraft, type SystemInfo } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { dateTime, errorMessage } from "@/utils/format";

const toast = useToast();
const session = useSession();
const system = ref<SystemInfo | null>(null);
const settings = ref<HubSettings | null>(null);
const busy = ref(false);
const saving = ref("");
const pending = ref<unknown>(null);
const fileName = ref("");
// Only the root administrator changes settings; other hub admins read them.
const editable = computed(() => session.isRoot);

// What a chosen file says about itself before it is restored. Only sealed backups carry these labels.
const sealedInfo = computed(() => {
  const file = pending.value as Partial<SealedBackup> | null;
  if (!file || file.format !== "mcp-hub-backup-v2") return null;
  return { created: file.created_at ?? "", version: file.hub_version ?? "", fingerprint: file.key_fingerprint ?? "",
           matches: !!system.value?.backup_key_fingerprint && file.key_fingerprint === system.value.backup_key_fingerprint };
});
const plainFile = computed(() => (pending.value as { format?: string } | null)?.format === "mcp-hub-metadata-v1");

const LIMITS: Record<string, string> = {
  max_records: "Records per source page / read call",
  report_max_records: "Records a report may read",
  report_timeout_seconds: "Report time budget (s)",
  tool_rate_limit: "Calls per key and tool per window",
  tool_rate_window_seconds: "Rate window (s)",
  audit_retention_days: "Activity retention (days)",
};
// Set when the Hub is deployed, in .env: from the UI they could lock everyone out or reach internal networks.
const ENVIRONMENT_ONLY: [string, string, boolean][] = [
  ["secure_cookies", "Secure (HTTPS-only) session cookies", true],
  ["insecure_http_allowed", "Plain HTTP to apps allowed", false],
  ["private_egress_allowed", "Calls to private or local networks allowed", false],
];
const limitDraft = ref<Record<string, number>>({});
const mfaDraft = ref(false);
const hosts = ref<string[]>([]);
const newHost = ref("");
const smtp = ref<SmtpDraft>({ host: "", port: 587, username: "", password: "", from: "", tls_mode: "starttls" });

function adopt(value: HubSettings) {
  settings.value = value;
  limitDraft.value = Object.fromEntries(Object.entries(value.limits).map(([key, limit]) => [key, limit.value]));
  mfaDraft.value = value.mfa_required.value;
  hosts.value = [...value.egress_allowed_hosts.value];
  smtp.value = { host: value.smtp.host, port: value.smtp.port || 587, username: value.smtp.username, password: "",
                 from: value.smtp.from, tls_mode: value.smtp.tls_mode || "starttls" };
}

async function load() {
  try {
    const [info, values] = await Promise.all([hub.system(), session.isHubAdmin ? hub.hubSettings() : Promise.resolve(null)]);
    system.value = info;
    if (values) adopt(values);
  } catch (exc) {
    toast.error(errorMessage(exc));
  }
}
onMounted(load);

const limitsChanged = computed(() => !!settings.value
  && Object.entries(limitDraft.value).some(([key, value]) => value !== settings.value!.limits[key]?.value));
const hostsChanged = computed(() => !!settings.value
  && JSON.stringify(hosts.value) !== JSON.stringify(settings.value.egress_allowed_hosts.value));

async function save(section: string, body: Record<string, unknown>, done: string) {
  saving.value = section;
  try {
    adopt(await hub.updateHubSettings(body));
    system.value = await hub.system();
    toast.ok(done);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    saving.value = "";
  }
}
function saveLimits() {
  const changed = Object.fromEntries(Object.entries(limitDraft.value).filter(([key, value]) => value !== settings.value?.limits[key]?.value));
  void save("limits", changed, "Limits saved. They apply now.");
}
function resetLimit(key: string) {
  void save("limits", { [key]: null }, "Back to the .env value");
}
function addHost() {
  const value = newHost.value.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/[/:].*$/, "");
  if (value && !hosts.value.includes(value)) hosts.value = [...hosts.value, value];
  newHost.value = "";
}
function saveSmtp() {
  const { password, ...rest } = smtp.value;
  void save("smtp", { smtp: { ...rest, password: password || null } }, "Email settings saved");
}
async function testEmail() {
  saving.value = "test";
  try {
    const sent = await hub.testEmail();
    toast.ok(`Test email sent to ${sent.sent_to}`);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    saving.value = "";
  }
}

async function download() {
  busy.value = true;
  try {
    const document = await hub.exportBackup();
    const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }));
    const link = window.document.createElement("a");
    link.href = url;
    link.download = `mcp-hub-backup-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast.ok("Backup downloaded, encrypted with this Hub's key");
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
    await load();
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
  <PageHeader title="Settings" subtitle="Changes here apply at once, without editing .env or restarting. A value set here wins over .env until you reset it." />

  <div v-if="system" class="grid gap-6 lg:grid-cols-2">
    <section class="card card-pad space-y-3">
      <h2 class="section-title">This Hub</h2>
      <dl class="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
        <dt class="text-subtle">Version</dt><dd>{{ system.version }}</dd>
        <dt class="text-subtle">Environment</dt><dd>{{ system.environment }}</dd>
        <dt class="text-subtle">MCP endpoint</dt><dd class="flex items-center gap-2"><span class="code truncate">{{ system.mcp_url }}</span><CopyButton :text="system.mcp_url" /></dd>
      </dl>
      <p v-if="settings && !editable" class="rounded-lg bg-muted px-3 py-2 text-xs text-subtle">Only the root administrator can change settings.</p>
    </section>

    <!-- Sign-in -->
    <section v-if="settings" class="card card-pad space-y-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="section-title">Sign-in</h2>
          <p class="mt-1 text-xs text-subtle">Two-step sign-in with an authenticator app for every administrator. Admins who have not set it up
            get a window to do so at their next sign-in.</p>
        </div>
        <span :class="settings.mfa_required.source === 'hub' ? 'badge-brand' : 'badge-outline'">{{ settings.mfa_required.source === "hub" ? "Set here" : "From .env" }}</span>
      </div>
      <label class="flex items-center justify-between gap-3 rounded-lg border border-line p-3">
        <span class="text-sm font-medium">Require two-step sign-in</span>
        <ToggleSwitch v-model="mfaDraft" label="Require two-step sign-in" :disabled="!editable || saving === 'mfa'"
                      @update:model-value="(value: boolean) => save('mfa', { mfa_required: value }, value ? 'Two-step sign-in is now required' : 'Two-step sign-in is now optional')" />
      </label>
      <button v-if="editable && settings.mfa_required.source === 'hub'" type="button" class="link text-xs"
              @click="save('mfa', { mfa_required: null }, 'Back to the .env value')">Use the .env value ({{ settings.mfa_required.environment ? "on" : "off" }})</button>

      <div class="border-t border-line pt-4">
        <h3 class="text-sm font-semibold">Set in .env only</h3>
        <ul class="mt-2 space-y-2 text-sm">
          <li v-for="[key, label, good] in ENVIRONMENT_ONLY" :key="key" class="flex items-center gap-2">
            <AppIcon :name="system.security[key] === good ? 'check' : 'alert'" :size="16" :class="system.security[key] === good ? 'text-ok' : 'text-warn'" />
            <span>{{ label }}: <span class="font-medium">{{ system.security[key] ? "yes" : "no" }}</span></span>
            <AppIcon name="lock" :size="13" class="text-subtle" />
          </li>
        </ul>
        <p class="mt-2 text-xs text-subtle">Changed only on the server, because a wrong value could lock every administrator out or let the Hub
          reach internal networks. Production always enforces the safe value.</p>
      </div>
    </section>

    <!-- Limits -->
    <section v-if="settings" class="card card-pad space-y-3">
      <h2 class="section-title">Limits</h2>
      <ul class="divide-y divide-line">
        <li v-for="(label, key) in LIMITS" :key="key" class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
          <span class="min-w-0 flex-1 text-sm">{{ label }}
            <span v-if="settings.limits[key].source === 'hub'" class="ml-1 badge-brand">Set here</span></span>
          <input v-if="editable" v-model.number="limitDraft[key]" type="number" class="input h-8 w-28 text-right font-mono"
                 :min="settings.limits[key].min" :max="settings.limits[key].max" :aria-label="label" />
          <span v-else class="font-mono text-sm">{{ settings.limits[key].value }}</span>
          <span class="w-full text-xs text-subtle sm:w-auto">{{ settings.limits[key].min }}–{{ settings.limits[key].max }}
            <template v-if="settings.limits[key].source === 'hub'"> · .env {{ settings.limits[key].environment }}
              <button v-if="editable" type="button" class="link" @click="resetLimit(key)">reset</button></template>
          </span>
        </li>
      </ul>
      <div v-if="editable" class="flex justify-end">
        <button type="button" class="btn-primary btn-sm" :disabled="!limitsChanged || saving === 'limits'" @click="saveLimits">
          <span v-if="saving === 'limits'" class="spinner" /> Save limits</button>
      </div>
    </section>

    <!-- Approved app hosts -->
    <section v-if="settings" class="card card-pad space-y-3">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="section-title">Approved app hosts</h2>
          <p class="mt-1 text-xs text-subtle">The Hub calls connected apps only on these hosts. Add an app's host before you connect it. A host
            that points at a private or local address stays blocked.</p>
        </div>
        <span :class="settings.egress_allowed_hosts.source === 'hub' ? 'badge-brand' : 'badge-outline'">{{ settings.egress_allowed_hosts.source === "hub" ? "Set here" : "From .env" }}</span>
      </div>
      <ul v-if="hosts.length" class="flex flex-wrap gap-2">
        <li v-for="host in hosts" :key="host" class="badge-neutral gap-1.5 py-1 font-mono">
          {{ host }}
          <button v-if="editable" type="button" class="text-subtle hover:text-ink" :aria-label="`Remove ${host}`"
                  @click="hosts = hosts.filter((item) => item !== host)"><AppIcon name="x" :size="12" /></button>
        </li>
      </ul>
      <p v-else class="rounded-lg border border-dashed border-line px-3 py-3 text-xs text-subtle">
        {{ settings.production ? "No hosts approved." : "No list: in development the Hub may call any public host." }}</p>
      <p v-if="settings.egress_allowed_hosts.cidrs.length" class="text-xs text-subtle">Also allowed in .env:
        <span class="font-mono">{{ settings.egress_allowed_hosts.cidrs.join(", ") }}</span></p>
      <form v-if="editable" class="flex gap-2" @submit.prevent="addHost">
        <input v-model="newHost" class="input font-mono" placeholder="app.example.com" aria-label="Host to approve" maxlength="253" />
        <button type="submit" class="btn-secondary" :disabled="!newHost.trim()"><AppIcon name="plus" :size="15" /> Add</button>
      </form>
      <div v-if="editable" class="flex flex-wrap justify-end gap-2">
        <button v-if="settings.egress_allowed_hosts.source === 'hub'" type="button" class="btn-ghost btn-sm"
                @click="save('hosts', { egress_allowed_hosts: null }, 'Back to the .env list')">Use the .env list</button>
        <button type="button" class="btn-primary btn-sm" :disabled="!hostsChanged || saving === 'hosts'"
                @click="save('hosts', { egress_allowed_hosts: hosts }, 'Approved hosts saved')">
          <span v-if="saving === 'hosts'" class="spinner" /> Save hosts</button>
      </div>
    </section>

    <!-- Email -->
    <section v-if="settings" class="card card-pad space-y-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="section-title">Email for invitations</h2>
          <p class="mt-1 text-xs text-subtle">Sends activation codes to invited administrators. The password is stored encrypted and never shown again.</p>
        </div>
        <span :class="settings.smtp.ready ? 'badge-ok' : 'badge-warn'">{{ settings.smtp.ready ? "Ready" : "Not set up" }}</span>
      </div>
      <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="saveSmtp">
        <label class="sm:col-span-2"><span class="label">Mail server</span>
          <input v-model="smtp.host" class="input font-mono" placeholder="smtp.example.com" :disabled="!editable" required maxlength="253" /></label>
        <label><span class="label">Port</span>
          <select v-model.number="smtp.port" class="input" :disabled="!editable">
            <option v-for="port in [587, 465, 2525, 25]" :key="port" :value="port">{{ port }}</option>
          </select></label>
        <label><span class="label">Encryption</span>
          <select v-model="smtp.tls_mode" class="input" :disabled="!editable">
            <option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option>
          </select></label>
        <label><span class="label">User name</span>
          <input v-model="smtp.username" class="input" autocomplete="off" :disabled="!editable" required maxlength="200" /></label>
        <label><span class="label">Password</span>
          <input v-model="smtp.password" type="password" class="input" autocomplete="new-password" :disabled="!editable" maxlength="500"
                 :placeholder="settings.smtp.password_set ? 'Saved; leave empty to keep it' : ''" :required="!settings.smtp.password_set" /></label>
        <label class="sm:col-span-2"><span class="label">Sender address</span>
          <input v-model="smtp.from" type="email" class="input" placeholder="hub@example.com" :disabled="!editable" required maxlength="200" /></label>
        <div v-if="editable" class="flex flex-wrap justify-end gap-2 sm:col-span-2">
          <button v-if="settings.smtp.source === 'hub'" type="button" class="btn-ghost btn-sm"
                  @click="save('smtp', { smtp: null }, 'Back to the .env email settings')">Use .env</button>
          <button type="button" class="btn-secondary btn-sm" :disabled="!settings.smtp.ready || saving === 'test'" @click="testEmail">
            <span v-if="saving === 'test'" class="spinner" /><AppIcon v-else name="send" :size="14" /> Send test email</button>
          <button type="submit" class="btn-primary btn-sm" :disabled="saving === 'smtp'">
            <span v-if="saving === 'smtp'" class="spinner" /> Save email settings</button>
        </div>
      </form>
    </section>

    <!-- Backup -->
    <section class="card card-pad space-y-4">
      <h2 class="section-title">Backup and maintenance</h2>
      <div class="flex flex-wrap gap-2">
        <button class="btn-secondary" type="button" :disabled="busy" @click="download"><AppIcon name="download" :size="16" /> Export configuration</button>
        <label v-if="session.isRoot" class="btn-secondary cursor-pointer"><AppIcon name="upload" :size="16" /> Restore from file
          <input class="hidden" type="file" accept="application/json" @change="choose" /></label>
        <button class="btn-secondary" type="button" :disabled="busy" @click="purge"><AppIcon name="trash" :size="16" /> Purge expired records</button>
      </div>
      <p class="text-xs text-subtle">The backup holds apps, data sources, tools, skills, client key hashes and the settings on this page, and the whole
        file is encrypted with this Hub's <span class="code">SECRET_ENCRYPTION_KEY</span>: without that key it cannot be read or restored. Keep a copy of
        the key somewhere safe, such as a password manager. Purge removes activity and test history older than the retention period.</p>
      <p v-if="system.backup_key_fingerprint" class="flex flex-wrap items-center gap-2 text-xs text-subtle">
        <AppIcon name="key" :size="14" /> Key fingerprint <span class="code">{{ system.backup_key_fingerprint }}</span>
        <span>· backups show the same label</span>
      </p>
    </section>
  </div>

  <ModalDialog v-if="pending" title="Restore configuration?" @close="pending = null">
    <p class="text-sm text-subtle">Replace the current apps, tools, keys and settings with <span class="code">{{ fileName }}</span>. Take an export first if you may need the current state. Admin users and activity history are not changed.</p>
    <dl v-if="sealedInfo" class="mt-4 grid grid-cols-[8rem_1fr] gap-y-1.5 rounded-lg border border-line p-3 text-sm">
      <dt class="text-subtle">Made</dt><dd>{{ dateTime(sealedInfo.created) }}</dd>
      <dt class="text-subtle">Hub version</dt><dd>{{ sealedInfo.version }}</dd>
      <dt class="text-subtle">Key</dt>
      <dd class="flex flex-wrap items-center gap-2"><span class="code">{{ sealedInfo.fingerprint }}</span>
        <span :class="sealedInfo.matches ? 'badge-ok' : 'badge-warn'">{{ sealedInfo.matches ? "This Hub's key" : "Another key" }}</span></dd>
    </dl>
    <p v-if="sealedInfo && !sealedInfo.matches" class="mt-3 text-xs text-warn">This backup was made with another key. It restores only if that key is
      set as <span class="code">SECRET_ENCRYPTION_KEY_PREVIOUS</span> on this Hub.</p>
    <p v-if="plainFile" class="mt-3 text-xs text-subtle">This is an unencrypted backup from an earlier version. It can still be restored.</p>
    <template #footer>
      <button class="btn-secondary" type="button" @click="pending = null">Cancel</button>
      <button class="btn-danger" type="button" :disabled="busy" @click="restore">Restore</button>
    </template>
  </ModalDialog>
</template>
