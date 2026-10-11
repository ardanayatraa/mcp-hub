<script setup lang="ts">
import { onMounted, ref } from "vue";

import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ModalDialog from "@/components/ModalDialog.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppSummary, type MemorySettings } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

// Opt-in memory per app. Administrators see settings and counts, never what users saved.
const props = defineProps<{ app: AppSummary }>();
const session = useSession();
const toast = useToast();
const settings = ref<MemorySettings | null>(null);
const form = ref({ retention_days: 90, max_notes: 50 });
const pending = ref<"" | "toggle" | "save" | "purge">("");
const confirmPurge = ref(false);
const error = ref("");

async function load() {
  try {
    settings.value = await hub.memory(props.app.id);
    form.value = { retention_days: settings.value.retention_days, max_notes: settings.value.max_notes };
    error.value = "";
  } catch (exc) {
    error.value = errorMessage(exc);
  }
}
onMounted(load);

const editable = () => session.canWrite && props.app.status !== "archived";

async function update(body: Parameters<typeof hub.updateMemory>[1], action: "toggle" | "save", message: string) {
  pending.value = action;
  try {
    settings.value = await hub.updateMemory(props.app.id, body);
    form.value = { retention_days: settings.value.retention_days, max_notes: settings.value.max_notes };
    toast.ok(message);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

async function purge() {
  pending.value = "purge";
  try {
    const { removed } = await hub.purgeMemory(props.app.id);
    toast.ok(`${removed} memories deleted`);
    confirmPurge.value = false;
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}
</script>

<template>
  <p v-if="error" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
  <LoadingSkeleton v-else-if="!settings" variant="panel" :count="5" label="Loading memory settings" />
  <div v-else class="grid gap-6 lg:grid-cols-3">
    <section class="card lg:col-span-2">
      <div class="flex items-start justify-between gap-4 p-6">
        <div>
          <h2 class="card-title">User memory</h2>
          <p class="card-description mt-1.5 max-w-xl">
            Lets AI clients remember preferences and short notes for each signed-in user of {{ app.name }}, such as their
            language, currency or usual report period, and use them in later conversations.
          </p>
        </div>
        <span class="flex items-center gap-2">
          <span v-if="pending === 'toggle'" class="spinner text-subtle" />
          <ToggleSwitch :model-value="settings.enabled" label="Memory" :disabled="!editable() || pending !== ''"
                        @update:model-value="(on: boolean) => update({ enabled: on }, 'toggle', on ? 'Memory turned on' : 'Memory turned off')" />
        </span>
      </div>
      <ul class="space-y-2 border-t border-line px-6 py-5 text-sm">
        <li v-for="line in [
          'Memory belongs to the user named by the app\'s signed X-Hub-Delegation header, never to a value the AI supplies.',
          'Each user sees only their own memory. It is encrypted in the Hub and expires after the retention period.',
          'Emails, phone numbers, ID numbers and credentials are refused. Administrators see counts, never content.',
          'The model does not learn or retrain: it reads the saved notes at the start of a conversation.',
        ]" :key="line" class="flex gap-2.5"><AppIcon name="check" :size="16" class="mt-0.5 text-subtle" /><span class="text-subtle">{{ line }}</span></li>
      </ul>
      <form class="grid gap-4 border-t border-line p-6 sm:grid-cols-3" @submit.prevent="update(form, 'save', 'Memory settings saved')">
        <label><span class="label">Keep memories for</span>
          <select v-model.number="form.retention_days" class="input" :disabled="!editable()">
            <option v-for="days in settings.retention_choices" :key="days" :value="days">{{ days }} days</option>
          </select></label>
        <label><span class="label">Notes per user</span>
          <input v-model.number="form.max_notes" class="input" type="number" min="5" max="200" :disabled="!editable()" />
          <span class="hint">Oldest notes make room. Up to {{ settings.max_profile_keys }} preferences.</span></label>
        <div class="flex items-start pt-6">
          <button v-if="editable()" class="btn-secondary w-full" type="submit"
                  :disabled="pending !== '' || (form.retention_days === settings.retention_days && form.max_notes === settings.max_notes)">
            <span v-if="pending === 'save'" class="spinner" /> Save settings</button>
        </div>
      </form>
    </section>

    <div class="space-y-6">
      <section class="card card-pad">
        <h2 class="card-title">Stored now</h2>
        <dl class="mt-4 grid grid-cols-3 gap-3 text-center">
          <div class="rounded-lg bg-muted p-3"><dt class="text-xs text-subtle">Users</dt><dd class="text-xl font-semibold tabular-nums">{{ settings.users }}</dd></div>
          <div class="rounded-lg bg-muted p-3"><dt class="text-xs text-subtle">Notes</dt><dd class="text-xl font-semibold tabular-nums">{{ settings.notes }}</dd></div>
          <div class="rounded-lg bg-muted p-3"><dt class="text-xs text-subtle">Preferences</dt><dd class="text-xl font-semibold tabular-nums">{{ settings.profile_entries }}</dd></div>
        </dl>
        <p class="mt-4 text-xs text-subtle">Tools AI clients get when memory is on:</p>
        <div class="mt-2 flex flex-wrap gap-1"><span v-for="name in settings.tools" :key="name" class="badge-neutral font-mono">{{ name }}</span></div>
        <p class="mt-2 text-xs text-subtle">Client keys with a tool allowlist need these added to it.</p>
      </section>
      <section v-if="editable()" class="card card-pad space-y-3 border-bad/30">
        <h2 class="card-title text-bad">Delete memories</h2>
        <p class="text-xs text-subtle">Removes everything every user of {{ app.name }} saved. Settings stay as they are.</p>
        <button class="btn-danger w-full" type="button" :disabled="pending !== '' || !(settings.notes + settings.profile_entries)"
                @click="confirmPurge = true"><AppIcon name="trash" :size="16" /> Delete all memories</button>
      </section>
    </div>

    <ModalDialog v-if="confirmPurge" title="Delete all memories?" @close="pending || (confirmPurge = false)">
      <p class="text-sm text-subtle">{{ settings.notes + settings.profile_entries }} saved items of {{ settings.users }} users are deleted permanently.</p>
      <template #footer>
        <button class="btn-secondary" type="button" :disabled="pending !== ''" @click="confirmPurge = false">Cancel</button>
        <button class="btn-danger" type="button" :disabled="pending !== ''" @click="purge"><span v-if="pending === 'purge'" class="spinner" /> Delete</button>
      </template>
    </ModalDialog>
  </div>
</template>
