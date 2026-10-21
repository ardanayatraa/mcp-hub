<script setup lang="ts">
import { ref } from "vue";
import { RouterLink } from "vue-router";

import { api } from "@/services/api";
import { errorMessage } from "@/utils/format";

const token = ref(window.location.hash.slice(1));
window.history.replaceState(null, "", window.location.pathname + window.location.search);
const password = ref("");
const confirm = ref("");
const error = ref("");
const busy = ref(false);
const done = ref(false);

async function activate() {
  error.value = "";
  if (password.value !== confirm.value) {
    error.value = "Passwords do not match.";
    return;
  }
  busy.value = true;
  try {
    await api("/auth/activate", { method: "POST", body: JSON.stringify({ token: token.value, password: password.value }) });
    token.value = "";
    password.value = "";
    confirm.value = "";
    done.value = true;
  } catch (exc) {
    error.value = errorMessage(exc, "Activation failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center px-4">
    <div class="card card-pad w-full max-w-sm space-y-4">
      <div class="flex items-center gap-2.5"><span class="grid h-9 w-9 place-items-center rounded-lg bg-brand text-brand-ink"><AppIcon name="bolt" :size="18" /></span><h1 class="text-lg font-semibold">Activate MCP Hub</h1></div>
      <p v-if="done" class="text-sm">Your account is ready. Sign in with your new password, then enter the code sent to your email.</p>
      <p v-else-if="!token" class="text-sm text-subtle">This invitation link is missing or already used. Ask the root administrator to resend it.</p>
      <form v-else class="space-y-4" @submit.prevent="activate">
        <p class="text-sm text-subtle">Set a password for your account. You will receive an email code each time you sign in.</p>
        <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
        <label class="block"><span class="label">New password</span><input v-model="password" class="input" type="password" autocomplete="new-password" minlength="12" required /><span class="hint">At least 12 characters with upper and lower case letters and a number.</span></label>
        <label class="block"><span class="label">Confirm password</span><input v-model="confirm" class="input" type="password" autocomplete="new-password" minlength="12" required /></label>
        <button class="btn-primary w-full" type="submit" :disabled="busy">Activate account</button>
      </form>
      <RouterLink v-if="done || !token" to="/login" class="btn-secondary inline-flex w-full justify-center">Go to sign in</RouterLink>
    </div>
  </main>
</template>
