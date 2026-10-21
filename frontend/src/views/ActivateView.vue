<script setup lang="ts">
import { ref } from "vue";
import { RouterLink } from "vue-router";

import { api } from "@/services/api";
import { errorMessage } from "@/utils/format";

const token = ref(window.location.hash.slice(1));
window.history.replaceState(null, "", window.location.pathname + window.location.search);
const email = ref("");
const code = ref("");
const challengeToken = ref("");
const proofToken = ref("");
const password = ref("");
const confirm = ref("");
const error = ref("");
const busy = ref(false);
const step = ref<"email" | "code" | "password" | "done">("email");

async function requestCode() {
  error.value = "";
  busy.value = true;
  try {
    const result = await api<{ challenge_token: string }>("/auth/activation-email", {
      method: "POST", body: JSON.stringify({ token: token.value, email: email.value }),
    });
    challengeToken.value = result.challenge_token;
    code.value = "";
    step.value = "code";
  } catch (exc) {
    error.value = errorMessage(exc, "Could not send the code");
  } finally {
    busy.value = false;
  }
}

async function verifyCode() {
  error.value = "";
  busy.value = true;
  try {
    const result = await api<{ proof_token: string }>("/auth/activation-code", {
      method: "POST", body: JSON.stringify({ token: token.value, challenge_token: challengeToken.value, code: code.value }),
    });
    proofToken.value = result.proof_token;
    code.value = "";
    step.value = "password";
  } catch (exc) {
    error.value = errorMessage(exc, "Code verification failed");
  } finally {
    busy.value = false;
  }
}

function changeEmail() {
  challengeToken.value = "";
  proofToken.value = "";
  code.value = "";
  step.value = "email";
  error.value = "";
}

async function activate() {
  error.value = "";
  if (password.value !== confirm.value) {
    error.value = "Passwords do not match.";
    return;
  }
  busy.value = true;
  try {
    await api("/auth/activate", { method: "POST", body: JSON.stringify({ token: token.value, proof_token: proofToken.value, password: password.value }) });
    token.value = "";
    proofToken.value = "";
    password.value = "";
    confirm.value = "";
    step.value = "done";
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
      <p v-if="step === 'done'" class="text-sm">Your account is ready. Sign in with your real email and new password, then enter the email code.</p>
      <p v-else-if="!token" class="text-sm text-subtle">This invitation link is missing or already used. Ask the root administrator to resend it.</p>
      <p v-else class="text-xs text-subtle">{{ step === "email" ? "Step 1 of 3: Verify your real email" : step === "code" ? "Step 2 of 3: Enter the email code" : "Step 3 of 3: Create a password" }}</p>
      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
      <form v-if="token && step === 'email'" class="space-y-4" @submit.prevent="requestCode">
        <p class="text-sm text-subtle">Enter the email address you will use to sign in. We will send a verification code there.</p>
        <label class="block"><span class="label">Your real email</span><input v-model="email" class="input" type="email" autocomplete="email" required /></label>
        <button class="btn-primary w-full" type="submit" :disabled="busy">Send verification code</button>
      </form>
      <form v-if="token && step === 'code'" class="space-y-4" @submit.prevent="verifyCode">
        <p class="text-sm text-subtle">Enter the six-digit code sent to {{ email }}. It expires in 10 minutes.</p>
        <label class="block"><span class="label">Email code</span><input v-model="code" class="input" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required /></label>
        <button class="btn-primary w-full" type="submit" :disabled="busy">Verify email</button>
        <button class="btn-ghost w-full" type="button" :disabled="busy" @click="changeEmail">Use another email</button>
      </form>
      <form v-if="token && step === 'password'" class="space-y-4" @submit.prevent="activate">
        <p class="text-sm text-subtle">Email verified for {{ email }}. Create your password to finish activation.</p>
        <label class="block"><span class="label">New password</span><input v-model="password" class="input" type="password" autocomplete="new-password" minlength="12" required /><span class="hint">At least 12 characters with upper and lower case letters and a number.</span></label>
        <label class="block"><span class="label">Confirm password</span><input v-model="confirm" class="input" type="password" autocomplete="new-password" minlength="12" required /></label>
        <button class="btn-primary w-full" type="submit" :disabled="busy">Activate account</button>
        <button class="btn-ghost w-full" type="button" :disabled="busy" @click="changeEmail">Start email verification again</button>
      </form>
      <RouterLink v-if="step === 'done' || !token" to="/login" class="btn-secondary inline-flex w-full justify-center">Go to sign in</RouterLink>
    </div>
  </main>
</template>
