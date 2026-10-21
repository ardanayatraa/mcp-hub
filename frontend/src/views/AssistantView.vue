<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import ChatMarkdown from "@/components/ChatMarkdown.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import PageHeader from "@/components/PageHeader.vue";
import { hub, type AssistantOptions, type AssistantToolEvent, type ModelCatalog } from "@/services/hub";
import { postStream } from "@/services/stream";
import { errorMessage } from "@/utils/format";
import { useVisibleModelRefresh } from "@/utils/modelRefresh";

// The console assistant answers questions about this Hub from its own repository (README, docs, code).
// The model pick is remembered in this browser only.
const STORE = "hub-assistant-model";
const SUGGESTIONS = [
  "How does the Hub work, end to end?",
  "How do I connect a Laravel app?",
  "What does run_report do, and what are its limits?",
  "How are client keys and tool permissions checked?",
];
const VERBS: Record<string, { verb: string; icon: string }> = {
  read_file: { verb: "Read", icon: "file" },
  search_repo: { verb: "Searched", icon: "search" },
  list_files: { verb: "Listed", icon: "layers" },
};

const options = ref<AssistantOptions | null>(null);
const loadError = ref("");
const provider = ref("");
const model = ref("");
const catalog = ref<ModelCatalog | null>(null);
const catalogLoading = ref(false);
let catalogRequest = 0;
const markCatalogRequested = useVisibleModelRefresh(() => {
  if (provider.value && !catalogLoading.value && !streaming.value) void loadModels(provider.value);
});

interface Entry { role: "user" | "assistant"; text: string; tools: AssistantToolEvent[]; notices: string[]; error?: string; model?: string }
const entries = ref<Entry[]>([]);
const draft = ref("");
const streaming = ref(false);
const log = ref<HTMLElement | null>(null);
let controller: AbortController | null = null;
onBeforeUnmount(() => controller?.abort());

const providers = computed(() => (options.value?.providers ?? []).filter((item) => item.ready));
const models = computed(() => {
  const listed = catalog.value?.provider === provider.value ? catalog.value.models : [];
  return model.value && !listed.some((item) => item.id === model.value) ? [{ id: model.value, label: model.value }, ...listed] : listed;
});
const modelLabel = computed(() => `${providers.value.find((item) => item.id === provider.value)?.label ?? provider.value} · ${model.value}`);
const ready = computed(() => !!options.value?.available && !!provider.value && !!model.value && catalog.value?.provider === provider.value);

function remembered(): { provider: string; model: string } | null {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) ?? "null");
    return saved && typeof saved.provider === "string" && typeof saved.model === "string" ? saved : null;
  } catch {
    return null;
  }
}

onMounted(async () => {
  try {
    options.value = await hub.assistant();
    const saved = remembered();
    const pick = saved && providers.value.some((item) => item.id === saved.provider) ? saved : options.value.default;
    if (pick) {
      provider.value = pick.provider;
      model.value = pick.model;
    }
  } catch (exc) {
    loadError.value = errorMessage(exc);
  }
});

watch([provider, model], ([providerId, modelId]) => {
  try {
    if (providerId && modelId) localStorage.setItem(STORE, JSON.stringify({ provider: providerId, model: modelId }));
  } catch {
    // Storage blocked: the pick lasts for this page.
  }
});

// Model lists come from the providers themselves; switching provider starts from its default model.
async function loadModels(providerId: string) {
  markCatalogRequested();
  const request = ++catalogRequest;
  catalogLoading.value = true;
  try {
    const list = await hub.providerModels(providerId, true);
    if (request !== catalogRequest) return;
    catalog.value = list;
    if (!streaming.value && !list.error && list.models.length && !list.models.some((item) => item.id === model.value)) {
      model.value = list.models.some((item) => item.id === list.default_model) ? list.default_model : list.models[0].id;
    }
  } catch (exc) {
    if (request === catalogRequest) catalog.value = catalog.value?.provider === providerId
      ? { ...catalog.value, error: errorMessage(exc) }
      : { provider: providerId, models: [], source: "cache", fetched_at: null, default_model: "", error: errorMessage(exc) };
  } finally {
    if (request === catalogRequest) catalogLoading.value = false;
  }
}
watch(provider, (providerId, previous) => {
  if (previous && providerId !== previous) model.value = "";
  if (providerId) void loadModels(providerId);
});

async function scroll() {
  await nextTick();
  log.value?.scrollTo({ top: log.value.scrollHeight });
}

async function send(text = draft.value) {
  const message = text.trim();
  if (!message || streaming.value || !ready.value) return;
  const history = entries.value.filter((entry) => entry.text && !entry.error).map(({ role, text: body }) => ({ role, text: body }));
  entries.value.push({ role: "user", text: message, tools: [], notices: [] });
  entries.value.push({ role: "assistant", text: "", tools: [], notices: [], model: modelLabel.value });
  const live = entries.value[entries.value.length - 1];
  draft.value = "";
  streaming.value = true;
  controller = new AbortController();
  void scroll();
  try {
    await postStream("/assistant", { message, history, provider: provider.value, model: model.value }, (event, data) => {
      if (event === "text") live.text += String(data.delta ?? "");
      else if (event === "tool") {
        const tool = data as unknown as AssistantToolEvent;
        const index = live.tools.findIndex((item) => item.id === tool.id);
        if (index >= 0) live.tools[index] = tool;
        else live.tools.push(tool);
      } else if (event === "notice") live.notices.push(String(data.message ?? ""));
      else if (event === "error") live.error = String(data.message ?? "The assistant failed");
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
</script>

<template>
  <PageHeader title="Assistant" subtitle="Ask about MCP Hub features, setup, or code." />
  <p v-if="loadError" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ loadError }}</p>
  <LoadingSkeleton v-else-if="!options" variant="panel" :count="4" label="Loading the assistant" />
  <section v-else class="card flex h-[calc(100vh-14rem)] min-h-[520px] flex-col">
    <header class="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
      <p class="text-xs text-subtle">Answers use the MCP Hub documentation and code.</p>
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="provider" class="input w-40" aria-label="Provider" :disabled="streaming || !providers.length">
          <option v-for="item in providers" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <select v-model="model" class="input w-56" aria-label="Model" :disabled="streaming || catalogLoading || !providers.length">
          <option v-for="item in models" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <button v-if="entries.length" type="button" class="btn-ghost text-xs" :disabled="streaming" @click="entries = []">Clear</button>
      </div>
    </header>
    <p v-if="catalog?.error && catalog.provider === provider" class="border-b border-warn/40 bg-warn-soft px-5 py-2 text-xs text-warn" role="status">
      Could not refresh models: {{ catalog.error }}
    </p>

    <div ref="log" class="flex-1 space-y-6 overflow-y-auto p-5" aria-live="polite">
      <div v-if="!entries.length" class="mx-auto max-w-xl space-y-4 pt-8 text-center">
        <span class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-brand-soft text-brand"><AppIcon name="chat" :size="22" /></span>
        <p v-if="!options.available" class="text-sm text-bad">The Hub cannot find its repository. Set ASSISTANT_REPO_PATH on the server.</p>
        <p v-else-if="!providers.length" class="text-sm text-subtle">Add a model under
          <RouterLink to="/providers" class="font-medium underline">AI providers</RouterLink> to ask questions.</p>
        <template v-else>
          <p class="text-sm">What would you like to know about this Hub?</p>
          <div class="flex flex-wrap justify-center gap-2">
            <button v-for="text in SUGGESTIONS" :key="text" type="button" class="badge-outline cursor-pointer hover:bg-muted" @click="send(text)">
              {{ text }}</button>
          </div>
        </template>
      </div>

      <div v-for="(entry, index) in entries" :key="index" :class="entry.role === 'user' ? 'flex justify-end' : 'space-y-3'">
        <p v-if="entry.role === 'user'" class="max-w-[75%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-brand px-4 py-2 text-sm text-brand-ink">{{ entry.text }}</p>
        <template v-else>
          <ol v-if="entry.tools.length" class="flex flex-wrap gap-1.5" aria-label="Research activity">
            <li v-for="tool in entry.tools" :key="tool.id" :title="tool.detail"
                class="inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] leading-4"
                :class="tool.status === 'error' ? 'border-bad/30 bg-bad-soft text-bad' : tool.status === 'running' ? 'border-warn/30 bg-warn-soft text-warn' : 'border-line bg-surface text-subtle'">
              <span v-if="tool.status === 'running'" class="spinner h-3 w-3" />
              <AppIcon v-else :name="tool.status === 'error' ? 'alert' : VERBS[tool.name]?.icon ?? 'check'" :size="12" />
              <span class="shrink-0 font-medium">{{ VERBS[tool.name]?.verb ?? tool.title }}</span>
              <code class="max-w-44 min-w-0 truncate text-[11px]">{{ tool.detail }}</code>
              <span v-if="tool.status === 'error'" class="shrink-0 font-medium">failed</span>
            </li>
          </ol>
          <ChatMarkdown v-if="entry.text" :text="entry.text" />
          <p v-else-if="streaming && index === entries.length - 1 && !entry.error" class="flex items-center gap-2 text-sm text-subtle">
            <span class="spinner" /> Reading the repository…</p>
          <p v-for="note in entry.notices" :key="note" class="rounded-md bg-warn-soft px-3 py-1.5 text-xs">{{ note }}</p>
          <p v-if="entry.error" class="rounded-md bg-bad-soft px-3 py-1.5 text-xs text-bad">{{ entry.error }}</p>
          <p v-if="entry.model && (entry.text || entry.error)" class="text-[11px] text-subtle">{{ entry.model }}</p>
        </template>
      </div>
    </div>

    <form class="flex items-end gap-2 border-t border-line p-3" @submit.prevent="send()">
      <textarea v-model="draft" rows="1" class="input max-h-32 min-h-[40px] flex-1 resize-none" :disabled="!ready"
                placeholder="Ask about the Hub: its workflow, setup, features or code" aria-label="Message" @keydown.enter.exact.prevent="send()" />
      <button v-if="streaming" type="button" class="btn-secondary" @click="stop"><AppIcon name="pause" :size="16" /> Stop</button>
      <button v-else type="submit" class="btn-primary" :disabled="!ready || !draft.trim()" aria-label="Send"><AppIcon name="send" :size="16" /></button>
    </form>
  </section>
</template>
