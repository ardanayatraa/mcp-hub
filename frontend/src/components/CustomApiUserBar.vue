<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";

import SecretInput from "@/components/SecretInput.vue";
import { hub, type EmbedUser } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { toSpec, type UserAuth } from "@/utils/customApiSpec";
import { errorMessage, timeAgo } from "@/utils/format";

const props = defineProps<{ connectorId: string; userAuth: UserAuth; editable: boolean }>();
const linkId = defineModel<string>({ default: "" });
const signingIn = defineModel<boolean>("signingIn", { default: false });

const toast = useToast();
const users = ref<EmbedUser[]>([]);
const busy = ref(false);
const error = ref("");
const method = ref<"form" | "token">(props.userAuth.enabled && props.userAuth.mode === "form" ? "form" : "token");
const fields = reactive<Record<string, string>>({});
const token = ref("");
const label = ref("");

const canForm = computed(() => props.userAuth.enabled && props.userAuth.mode === "form");
const fieldNames = computed(() => {
  const list = props.userAuth.fields.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
  return list.length ? list : ["email", "password"];
});

watch(canForm, (allowed) => { method.value = allowed ? "form" : "token"; });

function fieldType(name: string) {
  const lower = name.toLowerCase();
  if (/password|pin|secret|passcode/.test(lower)) return "password";
  if (lower.includes("email")) return "email";
  return "text";
}

function fieldLabel(name: string) {
  const text = name.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

async function loadUsers() {
  if (!props.editable) return;
  try {
    users.value = await hub.embedUsers(props.connectorId);
    if (props.userAuth.enabled && users.value.length && !users.value.some((user) => user.id === linkId.value)) {
      linkId.value = users.value[0].id;
    }
  } catch {
    users.value = [];
  }
}
onMounted(loadUsers);

function openForm() {
  error.value = "";
  method.value = canForm.value ? "form" : "token";
  signingIn.value = true;
}

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    const authConfig = props.userAuth.enabled ? toSpec({ userAuth: props.userAuth, resources: [], authHeader: null }).user_auth : undefined;
    const body = method.value === "form"
      ? { mode: "form", fields: Object.fromEntries(fieldNames.value.map((name) => [name, fields[name] ?? ""])), user_auth: authConfig }
      : { mode: "token", token: token.value.trim(), label: label.value.trim() || undefined, user_auth: authConfig };
    const created = await hub.signInCustomApi(props.connectorId, body);
    users.value = [created, ...users.value.filter((item) => item.id !== created.id)];
    linkId.value = created.id;
    for (const key of Object.keys(fields)) fields[key] = "";
    token.value = "";
    label.value = "";
    signingIn.value = false;
    toast.ok(`Signed in as ${created.name || "test user"}`);
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    busy.value = false;
  }
}

async function signOutSelected() {
  const id = linkId.value;
  if (!id) return;
  busy.value = true;
  try {
    await hub.revokeEmbedUser(props.connectorId, id);
    users.value = users.value.filter((item) => item.id !== id);
    linkId.value = props.userAuth.enabled && users.value.length ? users.value[0].id : "";
    toast.ok("Test user signed out");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section v-if="editable && (userAuth.enabled || users.length || signingIn)" class="space-y-3 rounded-lg border border-line bg-muted/40 p-3">
    <div class="flex flex-wrap items-center gap-2">
      <AppIcon name="users" :size="16" class="text-subtle" />
      <label class="text-xs font-medium text-subtle" for="probe-as-user">Test endpoints as</label>
      <select id="probe-as-user" v-model="linkId" class="input h-8 w-auto min-w-[13rem] py-1 text-sm" :disabled="busy">
        <option value="">{{ userAuth.enabled ? "No signed-in user" : "Connection default" }}</option>
        <option v-for="user in users" :key="user.id" :value="user.id">
          {{ user.name || "Unnamed user" }}{{ user.last_used_at ? ` · used ${timeAgo(user.last_used_at)}` : "" }}
        </option>
      </select>
      <button type="button" class="btn-secondary btn-sm" :disabled="busy" @click="signingIn ? (signingIn = false) : openForm()">
        {{ signingIn ? "Cancel" : "+ Sign in as user" }}
      </button>
      <button v-if="linkId" type="button" class="btn-ghost btn-sm text-bad" :disabled="busy" @click="signOutSelected">
        <AppIcon name="logout" :size="14" /> Sign out
      </button>
    </div>

    <p v-if="!users.length && userAuth.enabled && !signingIn" class="text-xs text-subtle">
      No signed-in user yet. Sign in as a test user so <span class="font-medium">Send</span> can test user-protected endpoints.
    </p>

    <div v-if="signingIn" class="space-y-3 border-t border-line pt-3"
         @keydown.enter="($event.target as HTMLElement)?.tagName === 'INPUT' && ($event.preventDefault(), submit())">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-xs font-medium text-ink">
          {{ method === "form" ? "Sign in via login endpoint" : "Sign in with a user token" }}
        </span>
        <button v-if="canForm" type="button" class="btn-ghost btn-sm text-xs"
                @click="method = method === 'form' ? 'token' : 'form'; error = ''">
          {{ method === "form" ? "Paste a user token instead" : "Use the login form instead" }}
        </button>
      </div>

      <div v-if="method === 'form'" class="grid gap-2 sm:grid-cols-2">
        <label v-for="name in fieldNames" :key="name">
          <span class="label">{{ fieldLabel(name) }}</span>
          <input v-model="fields[name]" :type="fieldType(name)" class="input" :disabled="busy" :placeholder="name" />
        </label>
      </div>
      <div v-else class="grid gap-2 sm:grid-cols-[1fr_13rem]">
        <label>
          <span class="label">User bearer token</span>
          <SecretInput v-model="token" :disabled="busy" placeholder="Paste the user's access token from the app" />
        </label>
        <label>
          <span class="label">Name <span class="font-normal text-subtle">(optional)</span></span>
          <input v-model="label" class="input" :disabled="busy" placeholder="e.g. Andi (test user)" />
        </label>
      </div>

      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-xs text-bad">{{ error }}</p>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-xs text-subtle">
          {{ method === "form"
            ? "Posts to the login path and keeps the returned token encrypted; the password is never saved."
            : "Stored encrypted for testing and previewing as this user." }}
        </span>
        <button type="button" class="btn-primary btn-sm" :disabled="busy" @click="submit">
          <span v-if="busy" class="spinner" /> {{ method === "form" ? "Sign in & select" : "Use token & select" }}
        </button>
      </div>
    </div>
  </section>

  <div v-else-if="editable" class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed border-line px-3 py-2 text-xs text-subtle">
    <span>Need a user login to test an endpoint with <span class="font-medium">Send</span>?</span>
    <button type="button" class="btn-ghost btn-sm" @click="openForm">+ Sign in as user</button>
  </div>
</template>
