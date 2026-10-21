<script setup lang="ts">
import { encode } from "uqr";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import ThemeSwitch from "@/components/ThemeSwitch.vue";
import { useSession } from "@/stores/session";
import { errorMessage } from "@/utils/format";

const session = useSession();
const route = useRoute();
const router = useRouter();
const email = ref("");
const password = ref("");
const code = ref("");
const mfaToken = ref("");
const otpauth = ref("");
const error = ref("");
const busy = ref(false);

// The setup link as a QR code for authenticator apps: one SVG path over the dark modules.
const qr = computed(() => {
  if (!otpauth.value) return null;
  const { size, data } = encode(otpauth.value, { border: 4 });
  let path = "";
  data.forEach((row, y) => row.forEach((dark, x) => { if (dark) path += `M${x} ${y}h1v1h-1z`; }));
  return { size, path };
});
// For typing in by hand ("Enter a setup key"): the secret alone, shown in groups of four.
const setupKey = computed(() => /[?&]secret=([A-Z2-7]+)/.exec(otpauth.value)?.[1] ?? "");
const setupKeyGroups = computed(() => setupKey.value.replace(/(.{4})(?=.)/g, "$1 "));

async function finish() {
  const next = typeof route.query.next === "string" && route.query.next.startsWith("/") ? route.query.next : "/";
  await router.push(next);
}

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    if (mfaToken.value) {
      await session.confirmMfa(mfaToken.value, code.value);
      await finish();
      return;
    }
    const data = await session.login(email.value, password.value);
    if (data.user) {
      await finish();
      return;
    }
    mfaToken.value = data.mfa_token || "";
    otpauth.value = data.otpauth_uri || "";
  } catch (exc) {
    error.value = errorMessage(exc, "Sign-in failed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="relative flex min-h-screen items-center justify-center px-4">
    <div class="absolute right-4 top-4"><ThemeSwitch variant="toggle" /></div>
    <div class="w-full max-w-sm">
      <div class="mb-6 flex items-center gap-3">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-brand text-brand-ink"><AppIcon name="bolt" :size="22" /></span>
        <div>
          <p class="text-lg font-semibold">MCP Hub</p>
          <p class="text-sm text-subtle">Connect your apps to AI, safely.</p>
        </div>
      </div>
      <form class="card card-pad space-y-4" @submit.prevent="submit">
        <h1 class="text-base">{{ mfaToken ? "Two-step verification" : "Sign in" }}</h1>
        <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
        <template v-if="!mfaToken">
          <label class="block"><span class="label">Email</span>
            <input v-model="email" class="input" autocomplete="username" type="email" required /></label>
          <label class="block"><span class="label">Password</span>
            <input v-model="password" class="input" autocomplete="current-password" type="password" required /></label>
        </template>
        <template v-else>
          <div v-if="otpauth" class="space-y-3 rounded-lg bg-muted p-3 text-xs">
            <p class="text-ink">Scan this code with your authenticator app (for example Google Authenticator or 1Password), then enter the 6-digit code.</p>
            <svg v-if="qr" :viewBox="`0 0 ${qr.size} ${qr.size}`" class="mx-auto h-48 w-48 rounded" shape-rendering="crispEdges"
                 role="img" aria-label="Authenticator setup QR code">
              <rect :width="qr.size" :height="qr.size" fill="#fff" />
              <path :d="qr.path" fill="#000" />
            </svg>
            <p class="text-subtle">Can't scan it? Choose "Enter a setup key", pick time-based and type this key:</p>
            <p class="break-all font-mono text-sm text-ink">{{ setupKeyGroups }}</p>
            <CopyButton :text="setupKey" label="Copy key" />
          </div>
          <p v-else class="text-sm text-subtle">Enter the 6-digit code from your authenticator app.</p>
          <label class="block"><span class="label">Code</span>
            <input v-model="code" class="input text-center font-mono text-lg tracking-[0.4em]" inputmode="numeric"
                   autocomplete="one-time-code" maxlength="6" required /></label>
        </template>
        <button class="btn-primary w-full" type="submit" :disabled="busy">{{ mfaToken ? "Verify" : "Sign in" }}</button>
      </form>
    </div>
  </main>
</template>
