<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import ChatMarkdown from "@/components/ChatMarkdown.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ResultView from "@/components/ResultView.vue";
import { hub, type AppSummary, type ChatSettings, type ChatToolEvent, type ModelCatalog } from "@/services/hub";
import { postStream } from "@/services/stream";
import { errorMessage } from "@/utils/format";

// Try it: ask as an admin, read-only and with no signed-in app user, on any model the Hub has, and see
// what each tool returned. Nothing is saved; the model picked here applies to this page only.
const props = defineProps<{ app: AppSummary }>();
const emit = defineEmits<{ settings: [] }>();
const settings = ref<ChatSettings | null>(null);
const loadError = ref("");
const provider = ref("");
const model = ref("");
const catalog = ref<ModelCatalog | null>(null);
const catalogLoading = ref(false);
let catalogRequest = 0;

interface Entry { role: "user" | "assistant"; text: string; tools: ChatToolEvent[]; notices: string[]; error?: string; model?: string }
const entries = ref<Entry[]>([]);
const draft = ref("");
const streaming = ref(false);
// The tool call whose answer is open under the message.
const open = ref("");
const log = ref<HTMLElement | null>(null);
let controller: AbortController | null = null;
onBeforeUnmount(() => controller?.abort());

const providers = computed(() => (settings.value?.options.providers ?? [])
  .filter((item) => item.ready || item.id === settings.value?.provider));
const models = computed(() => {
  const listed = catalog.value?.provider === provider.value ? catalog.value.models : [];
  return model.value && !listed.some((item) => item.id === model.value) ? [{ id: model.value, label: model.value }, ...listed] : listed;
});
const saved = computed(() => provider.value === settings.value?.provider && model.value === settings.value?.model);
const modelLabel = computed(() => `${providers.value.find((item) => item.id === provider.value)?.label ?? provider.value} · ${model.value}`);

onMounted(async () => {
  try {
    const view = await hub.chat(props.app.id);
    settings.value = view;
    provider.value = view.provider;
    model.value = view.model;
  } catch (exc) {
    loadError.value = errorMessage(exc);
  }
});

// Model lists come from the providers themselves; switching provider starts from its default model.
watch(provider, async (providerId) => {
  if (!providerId) return;
  const request = ++catalogRequest;
  catalogLoading.value = true;
  try {
    const list = await hub.providerModels(providerId);
    if (request !== catalogRequest) return;
    catalog.value = list;
    if (!list.models.some((item) => item.id === model.value)) {
      model.value = providerId === settings.value?.provider ? settings.value.model
        : list.models.some((item) => item.id === list.default_model) ? list.default_model : list.models[0]?.id ?? "";
    }
  } catch {
    if (request === catalogRequest) catalog.value = null;
  } finally {
    if (request === catalogRequest) catalogLoading.value = false;
  }
});

async function scroll() {
  await nextTick();
  log.value?.scrollTo({ top: log.value.scrollHeight });
}

async function send(text = draft.value) {
  const message = text.trim();
  if (!message || streaming.value || !model.value) return;
  const history = entries.value.filter((entry) => entry.text && !entry.error).map(({ role, text: body }) => ({ role, text: body }));
  entries.value.push({ role: "user", text: message, tools: [], notices: [] });
  entries.value.push({ role: "assistant", text: "", tools: [], notices: [], model: modelLabel.value });
  const live = entries.value[entries.value.length - 1];
  draft.value = "";
  streaming.value = true;
  controller = new AbortController();
  void scroll();
  try {
    await postStream(`/connectors/${props.app.id}/chat/try`, { message, history, provider: provider.value, model: model.value },
      (event, data) => {
        if (event === "text") live.text += String(data.delta ?? "");
        else if (event === "tool") {
          const tool = data as unknown as ChatToolEvent;
          const index = live.tools.findIndex((item) => item.id === tool.id);
          if (index >= 0) live.tools[index] = tool;
          else live.tools.push(tool);
          // Show the newest data straight away; the chips switch between answers.
          if (tool.result) open.value = tool.id;
        } else if (event === "notice") live.notices.push(String(data.message ?? ""));
        else if (event === "error") live.error = String(data.message ?? "The chat failed");
        void scroll();
      }, controller.signal);
  } catch (exc) {
    if ((exc as Error).name !== "AbortError") live.error = errorMessage(exc);
  } finally {
    streaming.value = false;
    controller = null;
    void scroll();
  }
}

function stop() {
  controller?.abort();
}

function clear() {
  entries.value = [];
  open.value = "";
}
</script>

<template>
  <p v-if="loadError" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ loadError }}</p>
  <LoadingSkeleton v-else-if="!settings" variant="panel" :count="4" label="Loading chat settings" />
  <section v-else class="card flex h-[calc(100vh-16rem)] min-h-[540px] flex-col">
    <header class="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
      <div class="min-w-0">
        <h2 class="card-title">Try it</h2>
        <p class="text-xs text-subtle">Read-only, as you, with no signed-in {{ app.name }} user. The model you pick here is not saved.</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span v-if="!saved" class="badge-warn" title="The app's chat still uses the model saved on the Chat tab">Trying another model</span>
        <select v-model="provider" class="input w-40" aria-label="Provider" :disabled="streaming">
          <option v-for="item in providers" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <select v-model="model" class="input w-56" aria-label="Model" :disabled="streaming || catalogLoading">
          <option v-for="item in models" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <button v-if="entries.length" type="button" class="btn-ghost text-xs" :disabled="streaming" @click="clear">Clear</button>
      </div>
    </header>

    <div ref="log" class="flex-1 space-y-6 overflow-y-auto p-5" aria-live="polite">
      <div v-if="!entries.length" class="mx-auto max-w-xl space-y-4 pt-6 text-center">
        <span class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-brand-soft text-brand"><AppIcon name="sparkles" :size="22" /></span>
        <template v-if="!settings.enabled">
          <p class="text-sm text-subtle">The chat is off for {{ app.name }}. Turn it on to try it.</p>
          <button type="button" class="btn-secondary" @click="emit('settings')">Open the Chat tab</button>
        </template>
        <template v-else>
          <p class="text-sm">{{ settings.welcome_message || `Ask a question about ${app.name}'s data.` }}</p>
          <div v-if="settings.suggestions.length" class="flex flex-wrap justify-center gap-2">
            <button v-for="text in settings.suggestions" :key="text" type="button" class="badge-outline cursor-pointer hover:bg-muted"
                    @click="send(text)">{{ text }}</button>
          </div>
          <p class="text-xs text-subtle">Each tool's answer opens under the reply: tables, totals and charts. Data that only a signed-in
            {{ app.name }} user may read answers inside {{ app.name }} only.</p>
        </template>
      </div>

      <div v-for="(entry, index) in entries" :key="index" :class="entry.role === 'user' ? 'flex justify-end' : 'space-y-3'">
        <p v-if="entry.role === 'user'" class="max-w-[75%] rounded-2xl rounded-br-sm bg-brand px-4 py-2 text-sm text-brand-ink">{{ entry.text }}</p>
        <template v-else>
          <div v-if="entry.tools.length" class="flex flex-wrap gap-1.5">
            <button v-for="tool in entry.tools" :key="tool.id" type="button"
                    class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition"
                    :class="[tool.status === 'error' ? 'border-bad/40 text-bad' : 'border-line text-subtle',
                             open === tool.id ? 'bg-muted text-ink' : 'hover:bg-muted']"
                    :disabled="tool.status === 'running'" @click="open = open === tool.id ? '' : tool.id">
              <span v-if="tool.status === 'running'" class="spinner h-3 w-3" />
              <AppIcon v-else :name="tool.status === 'error' ? 'alert' : 'check'" :size="12" />{{ tool.title }}
              <AppIcon v-if="tool.status !== 'running'" :name="open === tool.id ? 'chevron-down' : 'chevron-right'" :size="12" />
            </button>
          </div>
          <template v-for="tool in entry.tools" :key="`${tool.id}-answer`">
            <div v-if="open === tool.id" class="rounded-lg border border-line p-4">
              <p class="mb-3 text-xs font-medium text-subtle">{{ tool.title }} answered</p>
              <p v-if="tool.error" class="text-sm text-bad">{{ tool.error.message }}</p>
              <p v-else-if="!tool.result || tool.result.too_large" class="text-sm text-subtle">This answer is too large to show here.</p>
              <ResultView v-else :result="tool.result" />
              <p v-if="tool.result?.truncated" class="mt-2 text-xs text-subtle">Showing the first 50 rows.</p>
            </div>
          </template>
          <ChatMarkdown v-if="entry.text" :text="entry.text" />
          <p v-else-if="streaming && index === entries.length - 1 && !entry.error" class="flex items-center gap-2 text-sm text-subtle">
            <span class="spinner" /> Thinking…</p>
          <p v-for="note in entry.notices" :key="note" class="rounded-md bg-warn-soft px-3 py-1.5 text-xs">{{ note }}</p>
          <p v-if="entry.error" class="rounded-md bg-bad-soft px-3 py-1.5 text-xs text-bad">{{ entry.error }}</p>
          <p v-if="entry.model && (entry.text || entry.error)" class="text-[11px] text-subtle">{{ entry.model }}</p>
        </template>
      </div>
    </div>

    <form class="flex items-end gap-2 border-t border-line p-3" @submit.prevent="send()">
      <textarea v-model="draft" rows="1" class="input max-h-32 min-h-[40px] flex-1 resize-none" :disabled="!settings.enabled"
                :placeholder="`Ask about ${app.name}'s data`" aria-label="Message" @keydown.enter.exact.prevent="send()" />
      <button v-if="streaming" type="button" class="btn-secondary" @click="stop"><AppIcon name="pause" :size="16" /> Stop</button>
      <button v-else type="submit" class="btn-primary" :disabled="!settings.enabled || !draft.trim() || !model" aria-label="Send">
        <AppIcon name="send" :size="16" /></button>
    </form>
  </section>
</template>
