<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import CodeBlock from "@/components/CodeBlock.vue";
import CustomApiPanel from "@/components/CustomApiPanel.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppDetail, type EmbedUser, type EmbedWidget, type ToolSwitchRow } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { dateTime, errorMessage, timeAgo } from "@/utils/format";

const props = defineProps<{ app: AppDetail; editable: boolean }>();
const emit = defineEmits<{ (event: "saved"): void }>();
const toast = useToast();

const widget = ref<EmbedWidget | null>(null);
const users = ref<EmbedUser[]>([]);
const form = ref({ enabled: false, title: "", accent: "#2563eb", position: "right" as "left" | "right", session_days: 30, origins: "" });
const pending = ref("");
const error = ref("");
// A second click confirms actions that cut users off.
const confirming = ref("");

// The tools the embedded chat may use. The chat is read-only, so tools that change data are never offered.
const toolRows = ref<ToolSwitchRow[]>([]);
const toolMode = ref<"all" | "some">("all");
const picked = ref<string[]>([]);
const editingEndpoints = ref(false);

function fill(value: EmbedWidget) {
  widget.value = value;
  form.value = { enabled: value.enabled, title: value.title, accent: value.accent, position: value.position,
                 session_days: value.session_days, origins: value.allowed_origins.join("\n") };
  toolMode.value = value.allowed_tools === null ? "all" : "some";
  picked.value = [...(value.allowed_tools ?? [])];
}

async function loadTools() {
  try {
    toolRows.value = (await hub.toolSwitches(props.app.id)).tools.filter((row) => !row.write && row.kind !== "memory");
  } catch {
    toolRows.value = [];
  }
}

async function load() {
  try {
    const [value] = await Promise.all([hub.embed(props.app.id), loadTools()]);
    fill(value);
    if (props.editable) users.value = await hub.embedUsers(props.app.id);
  } catch (exc) {
    error.value = errorMessage(exc);
  }
}
onMounted(load);

const appTools = computed(() => toolRows.value.filter((row) => row.kind === "app"));
const builtIn = computed(() => toolRows.value.filter((row) => row.kind !== "app"));
// Names picked earlier whose endpoint was removed since; they are dropped on the next save.
const known = computed(() => new Set(toolRows.value.map((row) => row.name)));
const toolsChanged = computed(() => {
  const saved = widget.value?.allowed_tools ?? null;
  if (toolMode.value === "all") return saved !== null;
  const now = [...new Set(picked.value.filter((name) => known.value.has(name)))].sort();
  return saved === null || JSON.stringify(now) !== JSON.stringify([...saved].filter((name) => known.value.has(name)).sort());
});

// Everything the embedded chat needs, in the order it is usually done.
const steps = computed(() => {
  const value = widget.value;
  if (!value) return [];
  return [
    { done: appTools.value.length > 0, text: "Register at least one endpoint (below, or in the Endpoints tab).", action: "endpoints" },
    { done: value.ready.user_sign_in, text: "Turn on user sign-in in the endpoint list, so each user sees only their own data.", action: "endpoints" },
    { done: value.ready.app_active, text: "Test the connection and activate the app (buttons at the top).", action: "" },
    { done: value.ready.chat_enabled, text: "Turn the chat on in the Chat tab (its model, instructions and welcome message are used here too).", action: "" },
    { done: value.allowed_origins.length > 0, text: "List the websites that may show it.", action: "" },
    { done: value.enabled, text: "Switch the embedded chat on and save.", action: "" },
  ];
});
const allDone = computed(() => steps.value.every((step) => step.done));
const blocking = computed(() => {
  const value = widget.value?.ready;
  return !!value && (!value.user_sign_in || !value.app_active || !value.chat_enabled);
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

async function saveTools() {
  if (toolMode.value === "some" && !picked.value.some((name) => known.value.has(name))) {
    toast.error("Pick at least one tool, or choose Every tool.");
    return;
  }
  pending.value = "tools";
  try {
    const allowed = toolMode.value === "all" ? null : picked.value.filter((name) => known.value.has(name));
    fill(await hub.updateEmbed(props.app.id, { allowed_tools: allowed }));
    toast.ok(allowed === null ? "The chat may use every tool" : `The chat may use ${allowed.length} tool${allowed.length === 1 ? "" : "s"}`);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

function toggle(name: string, on: boolean) {
  picked.value = on ? [...new Set([...picked.value, name])] : picked.value.filter((item) => item !== name);
}

async function endpointsSaved() {
  emit("saved");
  await load();
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
  <div class="space-y-6">
    <section class="grid gap-6 lg:grid-cols-3">
      <div class="space-y-6 lg:col-span-2">
        <div v-if="widget && !allDone" class="card card-pad space-y-3">
          <h2 class="section-title">Setup</h2>
          <ol class="space-y-2 text-sm">
            <li v-for="(step, index) in steps" :key="index" class="flex items-start gap-2">
              <span class="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs"
                    :class="step.done ? 'bg-ok-soft text-ok' : 'bg-muted text-subtle'">
                <AppIcon v-if="step.done" name="check" :size="12" /><template v-else>{{ index + 1 }}</template></span>
              <span :class="step.done ? 'text-subtle line-through' : ''">{{ step.text }}</span>
              <button v-if="!step.done && step.action === 'endpoints' && editable" type="button" class="btn-ghost btn-sm ml-auto"
                      @click="editingEndpoints = true">Open</button>
            </li>
          </ol>
        </div>

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

          <p v-if="blocking" class="rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">
            It can be switched on once the first steps of the setup above are done.</p>

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

        <div v-if="widget" class="card card-pad space-y-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="section-title">What the chat may use</h2>
              <p class="text-sm text-subtle">Each endpoint is a tool. Choose which ones this chat may call; the others stay
                available to your own AI clients.</p>
            </div>
            <button v-if="editable" type="button" class="btn-secondary btn-sm" @click="editingEndpoints = !editingEndpoints">
              <AppIcon :name="editingEndpoints ? 'x' : 'plus'" :size="14" />
              {{ editingEndpoints ? "Close endpoints" : "Register or edit endpoints" }}</button>
          </div>

          <fieldset :disabled="!editable || !!pending" class="space-y-3">
            <div class="flex flex-wrap gap-4 text-sm">
              <label class="flex items-center gap-2"><input v-model="toolMode" type="radio" value="all" /> Every tool, also endpoints added later</label>
              <label class="flex items-center gap-2"><input v-model="toolMode" type="radio" value="some" /> Only the ones I pick</label>
            </div>

            <p v-if="!toolRows.length" class="rounded-lg bg-muted p-3 text-sm text-subtle">
              No endpoints yet. Register one, test the connection and activate the app; its tools then appear here.</p>
            <ul v-else class="divide-y divide-line rounded-lg border border-line">
              <li v-for="row in [...appTools, ...builtIn]" :key="row.name" class="flex items-center gap-3 px-3 py-2">
                <input :id="`tool-${row.name}`" type="checkbox" class="h-4 w-4"
                       :checked="toolMode === 'all' || picked.includes(row.name)" :disabled="toolMode === 'all'"
                       @change="toggle(row.name, ($event.target as HTMLInputElement).checked)" />
                <label :for="`tool-${row.name}`" class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium">{{ row.title }}</span>
                  <span class="block truncate font-mono text-xs text-subtle">{{ row.name }}</span>
                </label>
                <span v-if="row.kind !== 'app'" class="badge-neutral">Built-in</span>
                <span v-if="!row.enabled" class="badge-neutral" title="Switched off in the Tools tab for every client">Off for the app</span>
                <span v-else-if="!row.live" class="badge-neutral" :title="row.note ?? ''">Not live</span>
              </li>
            </ul>
            <p v-if="toolMode === 'some'" class="hint">New endpoints are not added here by themselves; tick them after you register them.</p>
          </fieldset>
          <div v-if="editable" class="flex justify-end border-t border-line pt-4">
            <button type="button" class="btn-primary" :disabled="!!pending || !toolsChanged" @click="saveTools">
              <span v-if="pending === 'tools'" class="spinner" /> Save tool choice</button>
          </div>
        </div>

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

      <aside v-if="editable" class="card card-pad space-y-3 self-start">
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

    <CustomApiPanel v-if="editingEndpoints && editable" :app="app" :editable="editable" @saved="endpointsSaved" />
  </div>
</template>
