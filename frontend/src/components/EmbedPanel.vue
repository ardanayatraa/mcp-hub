<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import CodeBlock from "@/components/CodeBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppDetail, type EmbedUser, type EmbedWidget } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { dateTime, errorMessage, timeAgo } from "@/utils/format";

const props = defineProps<{ app: AppDetail; editable: boolean }>();
const toast = useToast();

const widget = ref<EmbedWidget | null>(null);
const users = ref<EmbedUser[]>([]);
const form = ref({ enabled: false, title: "", accent: "#2563eb", position: "right" as "left" | "right", session_days: 30, origins: "" });
const pending = ref("");
const error = ref("");
// A second click confirms actions that cut users off.
const confirming = ref("");

function fill(value: EmbedWidget) {
  widget.value = value;
  form.value = { enabled: value.enabled, title: value.title, accent: value.accent, position: value.position,
                 session_days: value.session_days, origins: value.allowed_origins.join("\n") };
}

async function load() {
  try {
    fill(await hub.embed(props.app.id));
    if (props.editable) users.value = await hub.embedUsers(props.app.id);
  } catch (exc) {
    error.value = errorMessage(exc);
  }
}
onMounted(load);

const ready = computed(() => widget.value?.ready);
const missing = computed(() => {
  const value = ready.value;
  if (!value) return [];
  return [
    !value.user_sign_in && "Add user_auth to the endpoint list (Endpoints tab), so each user signs in with their own account.",
    !value.app_active && "Activate the app.",
    !value.chat_enabled && "Turn the chat on in the Chat tab (model, instructions and welcome message are used here too).",
  ].filter(Boolean) as string[];
});

async function save() {
  error.value = "";
  pending.value = "save";
  try {
    const { origins, ...rest } = form.value;
    fill(await hub.updateEmbed(props.app.id, { ...rest, allowed_origins: origins.split(/\s+/).filter(Boolean) }));
    toast.ok("Embedded chat saved");
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    pending.value = "";
  }
}

async function act(key: string, task: () => Promise<unknown>, message: string) {
  if (confirming.value !== key) {
    confirming.value = key;
    return;
  }
  confirming.value = "";
  pending.value = key;
  try {
    await task();
    toast.ok(message);
    await load();
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}
const rotate = () => act("rotate", () => hub.rotateEmbed(props.app.id), "New id: update the snippet on your sites");
const revokeUser = (linkId: string) => act(`user:${linkId}`, () => hub.revokeEmbedUser(props.app.id, linkId), "Signed out");
const revokeAll = () => act("all", () => hub.revokeEmbedUsers(props.app.id), "Everyone was signed out");
</script>

<template>
  <section class="grid gap-6 lg:grid-cols-3">
    <div class="space-y-6 lg:col-span-2">
      <form class="card card-pad space-y-4" @submit.prevent="save">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="section-title">Embedded chat</h2>
            <p class="text-sm text-subtle">A chat button other websites can show. Users sign in with their {{ app.name }} account
              and the assistant reads only what {{ app.name }} lets them see. It never changes data.</p>
          </div>
          <RouterLink v-if="widget?.enabled" :to="{ path: '/chat-agent', query: { app: app.id } }" class="btn-secondary btn-sm">
            <AppIcon name="chat" :size="14" /> Try in Chat Agent</RouterLink>
        </div>

        <div v-if="missing.length" class="rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">
          <p class="font-medium">Before it can be turned on:</p>
          <ul class="ml-5 list-disc"><li v-for="item in missing" :key="item">{{ item }}</li></ul>
        </div>

        <fieldset :disabled="!editable || !!pending" class="grid gap-4 sm:grid-cols-2">
          <label class="flex items-center gap-3 sm:col-span-2"><ToggleSwitch v-model="form.enabled" label="Embedded chat on" />
            Embedded chat on</label>
          <label><span class="label">Title</span><input v-model="form.title" class="input" maxlength="80" /></label>
          <label><span class="label">Colour</span>
            <span class="flex gap-2"><input v-model="form.accent" type="color" class="h-10 w-12 rounded border border-line" aria-label="Colour picker" />
              <input v-model="form.accent" class="input font-mono" maxlength="7" /></span></label>
          <label><span class="label">Button side</span>
            <select v-model="form.position" class="input"><option value="right">Right</option><option value="left">Left</option></select></label>
          <label><span class="label">Stay signed in (days)</span>
            <input v-model.number="form.session_days" class="input" type="number" min="1" max="90" /></label>
          <label class="sm:col-span-2"><span class="label">Websites that may show it</span>
            <textarea v-model="form.origins" class="input font-mono text-xs" rows="3" placeholder="https://www.example.com" />
            <span class="hint">One per line, scheme and host only. Browsers refuse to show the chat on any other site.</span></label>
        </fieldset>
        <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
        <div v-if="editable" class="flex justify-end border-t border-line pt-4">
          <button class="btn-primary" type="submit" :disabled="!!pending"><span v-if="pending === 'save'" class="spinner" /> Save</button>
        </div>
      </form>

      <div v-if="widget" class="card card-pad space-y-3">
        <h2 class="section-title">Add it to a website</h2>
        <p class="text-sm text-subtle">Paste this before <code class="code">&lt;/body&gt;</code> on a site listed above. Nothing else is needed on that site.</p>
        <CodeBlock :code="widget.snippet" max-height="8rem" />
        <div v-if="editable" class="flex flex-wrap items-center justify-between gap-2 text-xs text-subtle">
          <span>Copied to a site you did not list? Browsers block it there, but you can also change its id.</span>
          <button type="button" class="btn-ghost btn-sm" :disabled="!!pending"
                  @click="rotate">
            {{ confirming === "rotate" ? "Click again: the old snippet stops working" : "Change id" }}</button>
        </div>
      </div>
    </div>

    <aside v-if="editable" class="card card-pad space-y-3">
      <div class="flex items-center justify-between gap-2">
        <h2 class="section-title">Signed-in users</h2>
        <span class="badge-neutral">{{ users.length }}</span>
      </div>
      <p class="text-xs text-subtle">Their {{ app.name }} access tokens are stored encrypted; passwords are never kept.</p>
      <ul v-if="users.length" class="divide-y divide-line text-sm">
        <li v-for="user in users" :key="user.id" class="flex items-center justify-between gap-2 py-2">
          <div class="min-w-0">
            <p class="truncate font-medium">{{ user.name || "Unnamed user" }}</p>
            <p class="text-xs text-subtle" :title="dateTime(user.expires_at)">
              {{ user.last_used_at ? `Used ${timeAgo(user.last_used_at)}` : `Signed in ${timeAgo(user.created_at)}` }}</p>
          </div>
          <button type="button" class="btn-ghost btn-sm text-bad" :disabled="!!pending"
                  @click="revokeUser(user.id)">
            {{ confirming === `user:${user.id}` ? "Confirm" : "Sign out" }}</button>
        </li>
      </ul>
      <p v-else class="text-sm text-subtle">Nobody has signed in yet.</p>
      <button v-if="users.length" type="button" class="btn-ghost btn-sm w-full text-bad" :disabled="!!pending"
              @click="revokeAll">
        {{ confirming === "all" ? "Click again to sign everyone out" : "Sign everyone out" }}</button>
    </aside>
  </section>
</template>
