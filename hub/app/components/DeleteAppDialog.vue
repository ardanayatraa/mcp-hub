<script setup lang="ts">
import { computed, ref } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import { hub, type AppSummary } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

const props = defineProps<{ app: AppSummary }>();
const emit = defineEmits<{ close: []; deleted: []; changed: [] }>();
const toast = useToast();
const typed = ref("");
const step = ref<"" | "archiving" | "deleting">("");
// The Hub only deletes draft or archived apps, so a live app is archived first.
const needsArchive = computed(() => !["draft", "archived"].includes(props.app.status));

function close() {
  if (!step.value) emit("close");
}

async function remove() {
  let archived = false;
  try {
    if (needsArchive.value) {
      step.value = "archiving";
      await hub.appAction(props.app.id, "archive");
      archived = true;
    }
    step.value = "deleting";
    await hub.deleteApp(props.app.id);
    toast.ok(`${props.app.name} deleted`);
    emit("deleted");
  } catch (exc) {
    toast.error(errorMessage(exc));
    if (archived) emit("changed");
  } finally {
    step.value = "";
  }
}
</script>

<template>
  <ModalDialog :title="`Delete ${app.name}?`" @close="close">
    <div class="space-y-3 text-sm">
      <p class="text-subtle">
        The app, its data sources, tools and client keys are removed from the Hub. Audit history is kept and the app's own data is not touched.
      </p>
      <p v-if="needsArchive" class="rounded-lg border border-warn/40 bg-warn-soft p-3 text-xs">
        {{ app.name }} is {{ app.status }}. It is archived first: its tools stop immediately and its bearer token and client keys are revoked.
      </p>
      <label class="block"><span class="label">Type <span class="code">{{ app.app_key }}</span> to confirm</span>
        <input v-model="typed" class="input font-mono" autocomplete="off" spellcheck="false" :disabled="!!step" @keydown.enter.prevent="typed === app.app_key && remove()" /></label>
    </div>
    <template #footer>
      <button class="btn-secondary" type="button" :disabled="!!step" @click="close">Cancel</button>
      <button class="btn-danger" type="button" :disabled="typed !== app.app_key || !!step" @click="remove">
        <span v-if="step" class="spinner" />
        {{ step === "archiving" ? "Archiving…" : step === "deleting" ? "Deleting…" : "Delete app" }}
      </button>
    </template>
  </ModalDialog>
</template>
