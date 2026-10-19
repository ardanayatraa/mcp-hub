<script setup lang="ts">
import { computed, ref } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppSummary, type GeneratedTools } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { appStatus, badgeClass, byReadiness, errorMessage, templateInfo } from "@/utils/format";
import { useSlowFlag } from "@/utils/loading";

const props = defineProps<{ apps: AppSummary[]; connectorId?: string }>();
const emit = defineEmits<{ close: []; done: [] }>();
const toast = useToast();
const eligible = computed(() => byReadiness(props.apps.filter((app) => app.status !== "archived")));
const appId = ref(props.connectorId ?? eligible.value[0]?.id ?? "");
const publish = ref(true);
const running = ref(false);
const slow = useSlowFlag(running);
const outcome = ref<GeneratedTools | null>(null);
const chosen = computed(() => eligible.value.find((app) => app.id === appId.value));
// Apps that manage their own permissions decide their tools; the Hub can only re-read them.
const managed = computed(() => chosen.value?.connector_type === "source_managed");
const listed = computed(() => outcome.value ? [
  ...outcome.value.created.map((item) => ({ ...item, kind: "New" })),
  ...outcome.value.repaired.map((item) => ({ ...item, kind: "Fixed" })),
] : []);

async function run() {
  running.value = true;
  try {
    outcome.value = await hub.generateTools({ connector_id: appId.value, publish: publish.value });
    const changed = outcome.value.created.length + outcome.value.repaired.length;
    toast.ok(changed ? `${changed} tools created or fixed` : "Tools are already up to date");
    emit("done");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    running.value = false;
  }
}

function close() {
  if (!running.value) emit("close");
}
</script>

<template>
  <ModalDialog :title="managed ? 'Refresh tools' : 'Generate tools'" wide @close="close">
    <template v-if="!outcome">
      <p class="text-sm text-subtle">
        Brings the app's tools up to date with the routes it published: a tool for every new route (list and lookup tools, a
        summary report, and create, update or delete requests), and a fix for tools left as drafts or needing a re-test.
      </p>
      <div class="mt-4 space-y-4">
        <label class="block"><span class="label">App</span>
          <select v-model="appId" class="input" :disabled="running">
            <option v-for="app in eligible" :key="app.id" :value="app.id">{{ app.name }} · {{ app.environment }}</option>
          </select>
          <span v-if="!eligible.length" class="hint">Connect an app first.</span>
          <span v-else-if="managed" class="hint">{{ chosen?.name }} decides its own tools. This re-reads its current permissions and updates the tools to match.</span>
          <span v-else-if="chosen" class="hint" :class="chosen.sources_enabled ? '' : 'text-warn'">
            {{ appStatus[chosen.status]?.label ?? chosen.status }} · {{ chosen.sources_enabled }} of {{ chosen.sources_total }} data sources allowed{{
              chosen.sources_enabled ? "" : ". Allow a data source on the app page first." }}</span>
        </label>
        <label v-if="!managed" class="flex items-start gap-3 rounded-lg border border-line p-3">
          <ToggleSwitch v-model="publish" label="Publish tools that pass" :disabled="running" />
          <span><span class="text-sm font-medium">Publish read and report tools that pass their test</span>
            <span class="block text-xs text-subtle">Each one is tested with synthetic data first. Write tools always stay drafts for you to review.</span></span>
        </label>
      </div>
      <div v-if="running" role="status" class="mt-4 flex items-center gap-3 rounded-lg bg-muted px-3 py-2.5 text-sm text-subtle">
        <span class="spinner text-brand" />
        <span>{{ managed ? `Reading ${chosen?.name}'s permissions…` : slow ? "Still testing each tool with sample data. Large apps take a few seconds." : "Creating and testing tools…" }}</span>
      </div>
    </template>

    <div v-else class="space-y-4">
      <div class="grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
        <div class="rounded-lg bg-muted p-3"><p class="text-xl font-semibold tabular-nums">{{ outcome.created.length }}</p><p class="text-xs text-subtle">new</p></div>
        <div class="rounded-lg bg-muted p-3"><p class="text-xl font-semibold tabular-nums">{{ outcome.repaired.length }}</p><p class="text-xs text-subtle">fixed</p></div>
        <div class="rounded-lg bg-muted p-3"><p class="text-xl font-semibold tabular-nums">{{ outcome.unchanged }}</p><p class="text-xs text-subtle">already live</p></div>
        <div class="rounded-lg bg-muted p-3"><p class="text-xl font-semibold tabular-nums">{{ outcome.skipped.length }}</p><p class="text-xs text-subtle">need you</p></div>
      </div>
      <p v-if="!listed.length" class="rounded-lg bg-muted px-3 py-2.5 text-sm text-subtle">
        Nothing to create or fix. {{ outcome.skipped.length ? "What needs you is listed below." : "Every published route already has a live tool." }}</p>
      <ul v-else class="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
        <li v-for="item in listed" :key="item.id" class="flex items-start gap-3 p-3">
          <span :class="badgeClass(templateInfo[item.template]?.tone ?? 'neutral')">{{ templateInfo[item.template]?.label ?? item.template }}</span>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium">{{ item.title }} <span class="badge-outline ml-1">{{ item.kind }}</span></p>
            <p class="truncate font-mono text-xs text-subtle">{{ item.mcp_name }}</p>
            <p v-if="item.note" class="mt-0.5 text-xs text-subtle">{{ item.note }}</p>
          </div>
          <span :class="item.status === 'published' ? 'badge-ok' : 'badge-neutral'">{{ item.status === "published" ? "Live" : "Draft" }}</span>
        </li>
      </ul>
      <details v-if="outcome.skipped.length" class="rounded-lg border border-line p-3 text-sm" :open="!listed.length">
        <summary class="cursor-pointer font-medium">Need you ({{ outcome.skipped.length }})</summary>
        <ul class="mt-2 max-h-56 space-y-1 overflow-y-auto text-xs">
          <li v-for="item in outcome.skipped" :key="item.tool_key + item.reason"><span class="font-mono">{{ item.tool_key }}</span> · <span class="text-subtle">{{ item.reason }}</span></li>
        </ul>
      </details>
    </div>

    <template #footer>
      <template v-if="!outcome">
        <button class="btn-secondary" type="button" :disabled="running" @click="close">Cancel</button>
        <button class="btn-primary" type="button" :disabled="running || !appId" @click="run">
          <span v-if="running" class="spinner" /><AppIcon v-else :name="managed ? 'refresh' : 'sparkles'" :size="16" />
          {{ running ? (managed ? "Refreshing…" : "Generating…") : managed ? "Refresh tools" : "Generate tools" }}
        </button>
      </template>
      <button v-else class="btn-primary" type="button" @click="emit('close')">Done</button>
    </template>
  </ModalDialog>
</template>
