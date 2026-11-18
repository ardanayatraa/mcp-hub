<script setup lang="ts">
import { ref } from "vue";
import { RouterLink } from "vue-router";

import { hub } from "@/services/hub";
import { errorMessage } from "@/utils/format";

// The token travels in the link's fragment, never in a request line; drop it from the address bar at once.
const token = ref(window.location.hash.slice(1));
window.history.replaceState(null, "", window.location.pathname + window.location.search);
const password = ref("");
const confirm = ref("");
const error = ref("");
const busy = ref(false);
const done = ref(false);

async function submit() {
  error.value = "";
  if (password.value !== confirm.value) {
    error.value = "The two passwords are different.";
    return;
  }
  busy.value = true;
  try {
    await hub.completePasswordReset(token.value, password.value);
    done.value = true;
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center px-4">
    <div class="card card-pad w-full max-w-sm space-y-4">
      <div class="flex items-center gap-2.5"><span class="grid h-9 w-9 place-items-center rounded-lg bg-brand text-brand-ink"><AppIcon name="bolt" :size="18" /></span><h1 class="text-lg font-semibold">Set a new password</h1></div>
      <p v-if="done" class="text-sm">Your password is changed and you were signed out everywhere. Sign in with the new password.</p>
      <p v-else-if="!token" class="text-sm text-subtle">This reset link is missing or already used. Ask the root administrator for a new one.</p>
      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
      <form v-if="token && !done" class="space-y-4" @submit.prevent="submit">
        <label class="block"><span class="label">New password</span><input v-model="password" class="input" type="password" autocomplete="new-password" minlength="12" required /><span class="hint">At least 12 characters with upper and lower case letters and a number.</span></label>
        <label class="block"><span class="label">Confirm password</span><input v-model="confirm" class="input" type="password" autocomplete="new-password" minlength="12" required /></label>
        <button class="btn-primary w-full" type="submit" :disabled="busy"><span v-if="busy" class="spinner" /> Save new password</button>
      </form>
      <RouterLink v-if="done || !token" to="/login" class="btn-secondary inline-flex w-full justify-center">Go to sign in</RouterLink>
    </div>
  </main>
</template>
