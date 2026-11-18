<script setup lang="ts">
import { ref } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import { hub } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

const emit = defineEmits<{ close: [] }>();
const toast = useToast();
const current = ref("");
const next = ref("");
const confirm = ref("");
const error = ref("");
const busy = ref(false);

async function save() {
  error.value = "";
  if (next.value !== confirm.value) {
    error.value = "The two new passwords are different.";
    return;
  }
  busy.value = true;
  try {
    await hub.changePassword(current.value, next.value);
    toast.ok("Password changed. Other devices were signed out.");
    emit("close");
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <ModalDialog title="Change password" @close="emit('close')">
    <form id="change-password" class="space-y-4" @submit.prevent="save">
      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
      <label class="block"><span class="label">Current password</span>
        <input v-model="current" class="input" type="password" autocomplete="current-password" required /></label>
      <label class="block"><span class="label">New password</span>
        <input v-model="next" class="input" type="password" autocomplete="new-password" minlength="12" required />
        <span class="hint">At least 12 characters with upper and lower case letters and a number. Other devices are signed out.</span></label>
      <label class="block"><span class="label">Confirm new password</span>
        <input v-model="confirm" class="input" type="password" autocomplete="new-password" minlength="12" required /></label>
    </form>
    <template #footer>
      <button class="btn-secondary" type="button" @click="emit('close')">Cancel</button>
      <button class="btn-primary" type="submit" form="change-password" :disabled="busy"><span v-if="busy" class="spinner" /> Change password</button>
    </template>
  </ModalDialog>
</template>
