<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import PageHeader from "@/components/PageHeader.vue";
import { hub, type EmbedListed, type EmbedUser } from "@/services/hub";
import { useSession } from "@/stores/session";
import { errorMessage, timeAgo } from "@/utils/format";

const route = useRoute();
const router = useRouter();
const session = useSession();

const widgets = ref<EmbedListed[]>([]);
const loaded = ref(false);
const error = ref("");
const chosen = ref(String(route.query.app || ""));
const users = ref<EmbedUser[]>([]);
// "" = a new visitor who signs in themselves; otherwise the id of a signed-in user to preview as.
const viewAs = ref("");
const device = ref<"widget" | "phone">("widget");
const frameUrl = ref("");
const frameKey = ref(0);
const pending = ref(false);

const widget = computed(() => widgets.value.find((item) => item.connector_id === chosen.value));
const usable = computed(() => widgets.value.filter((item) => item.enabled));
const asUser = computed(() => users.value.find((user) => user.id === viewAs.value));
// Same origin as this console, so the page's frame-ancestors 'self' lets it show here.
const pagePath = computed(() => (widget.value ? `/api/embed/v1/w/${widget.value.public_id}` : ""));

onMounted(async () => {
  try {
    widgets.value = await hub.embedWidgets();
    const start = widget.value?.enabled ? chosen.value : usable.value[0]?.connector_id ?? "";
    if (start === chosen.value) await selectApp(start);
    else chosen.value = start;
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    loaded.value = true;
  }
});

async function selectApp(value: string) {
  void router.replace({ query: { ...route.query, app: value || undefined } });
  users.value = [];
  if (value && session.canWrite) {
    try { users.value = await hub.embedUsers(value); } catch { users.value = []; }
  }
  if (viewAs.value) viewAs.value = "";  // reopens through the watcher below
  else await open();
}

watch(chosen, (value) => void selectApp(value));
watch(viewAs, () => void open());

async function open() {
  error.value = "";
  if (!widget.value) { frameUrl.value = ""; return; }
  if (!viewAs.value) {
    frameUrl.value = pagePath.value;
    frameKey.value++;
    return;
  }
  pending.value = true;
  try {
    // A short read-only token, recorded in Activity as you. It travels in the fragment, never to a server log.
    const { token } = await hub.embedPreview(widget.value.connector_id, viewAs.value);
    frameUrl.value = `${pagePath.value}#preview=${encodeURIComponent(token)}`;
    frameKey.value++;
  } catch (exc) {
    error.value = errorMessage(exc);
    frameUrl.value = "";
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <PageHeader title="Chat Agent" subtitle="See an app's embedded chat exactly as its users see it." />

  <LoadingSkeleton v-if="!loaded" variant="panel" :count="2" label="Loading embedded chats" />

  <EmptyState v-else-if="!usable.length" icon="chat" title="No embedded chat is on yet"
              text="Open an app connected as a Custom API with user sign-in, then turn the chat on in its Embed tab.">
    <RouterLink to="/apps" class="btn-primary">Go to Apps</RouterLink>
  </EmptyState>

  <div v-else class="grid gap-6 lg:grid-cols-[20rem_1fr]">
    <aside class="card card-pad space-y-4 self-start">
      <label><span class="label">Application</span>
        <select v-model="chosen" class="input">
          <option v-for="item in usable" :key="item.connector_id" :value="item.connector_id">
            {{ item.app_name }} · {{ item.environment }}</option>
        </select></label>

      <label><span class="label">View as</span>
        <select v-model="viewAs" class="input" :disabled="pending">
          <option value="">A new visitor (sign in yourself)</option>
          <option v-for="user in users" :key="user.id" :value="user.id">
            {{ user.name || "Unnamed user" }}{{ user.last_used_at ? ` · used ${timeAgo(user.last_used_at)}` : "" }}</option>
        </select>
        <span class="hint">
          <template v-if="!session.canWrite">Only admins who can change the app may preview as its users.</template>
          <template v-else-if="!users.length">Nobody has signed in yet. Sign in as a visitor with a test account first.</template>
          <template v-else>Previewing as a user is read-only, lasts 30 minutes and is recorded in Activity as you.</template>
        </span></label>

      <div><span class="label">Size</span>
        <div class="flex gap-2">
          <button type="button" :class="device === 'widget' ? 'btn-primary btn-sm' : 'btn-secondary btn-sm'" @click="device = 'widget'">Chat window</button>
          <button type="button" :class="device === 'phone' ? 'btn-primary btn-sm' : 'btn-secondary btn-sm'" @click="device = 'phone'">Phone</button>
        </div></div>

      <button type="button" class="btn-secondary w-full" :disabled="pending" @click="open">
        <span v-if="pending" class="spinner" /><AppIcon v-else name="refresh" :size="16" /> Reload</button>

      <div v-if="widget" class="space-y-1 border-t border-line pt-3 text-xs text-subtle">
        <p>Allowed sites: <span class="font-mono">{{ widget.allowed_origins.join(", ") || "none yet" }}</span></p>
        <RouterLink :to="{ path: `/apps/${widget.connector_id}`, query: { tab: 'embed' } }" class="font-medium underline">
          Embed settings</RouterLink>
      </div>
    </aside>

    <section class="space-y-3">
      <div v-if="asUser" class="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">
        <AppIcon name="alert" class="mt-0.5 text-warn" />
        <p>You are seeing {{ asUser.name || "this user" }}'s data as they would. Nothing can be changed from here.</p>
      </div>
      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
      <div class="flex justify-center rounded-xl border border-line bg-muted/60 p-6">
        <div :class="device === 'phone' ? 'h-[667px] w-[375px] rounded-[2rem] border-8 border-ink/80' : 'h-[600px] w-[380px] rounded-2xl'"
             class="overflow-hidden bg-white shadow-xl">
          <iframe v-if="frameUrl" :key="frameKey" :src="frameUrl" title="Embedded chat preview" class="h-full w-full border-0" />
        </div>
      </div>
    </section>
  </div>
</template>
