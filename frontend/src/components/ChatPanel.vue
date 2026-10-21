<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import CodeBlock from "@/components/CodeBlock.vue";
import GatewayPanel from "@/components/GatewayPanel.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type AppSummary, type ChatSettings, type ChatSettingsUpdate, type ModelCatalog } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { errorMessage, timeAgo } from "@/utils/format";
import { useVisibleModelRefresh } from "@/utils/modelRefresh";

// The Hub-hosted chat: the Hub is the kitchen (model, tools, rules); the app brings the user and the data.
const props = defineProps<{ app: AppSummary }>();
const emit = defineEmits<{ try: [] }>();
const session = useSession();
const toast = useToast();
const settings = ref<ChatSettings | null>(null);
const error = ref("");
const pending = ref<"" | "toggle" | "save">("");
const form = ref<Required<Omit<ChatSettingsUpdate, "enabled" | "gateway_models" | "monthly_token_limit">>>({
  provider: "anthropic", model: "claude-opus-5-5", effort: "medium", instructions: "", welcome_message: "",
  suggestions: [], max_steps: 6, daily_limit: 200,
});
const editable = computed(() => session.canWrite && props.app.status !== "archived");

function fill(view: ChatSettings) {
  settings.value = view;
  const { provider, model, effort, instructions, welcome_message, suggestions, max_steps, daily_limit } = view;
  form.value = { provider, model, effort, instructions, welcome_message, suggestions: [...suggestions], max_steps, daily_limit };
}

const hubUrl = ref("https://your-hub.example.com");

async function load() {
  try {
    fill(await hub.chat(props.app.id));
    error.value = "";
    void loadModels(true);
    hub.system().then((info) => { hubUrl.value = info.mcp_url.replace(/\/mcp\/?$/, ""); }).catch(() => undefined);
  } catch (exc) {
    error.value = errorMessage(exc);
  }
}
onMounted(load);

const dirty = computed(() => {
  const view = settings.value;
  if (!view) return false;
  return JSON.stringify(form.value) !== JSON.stringify({
    provider: view.provider, model: view.model, effort: view.effort, instructions: view.instructions,
    welcome_message: view.welcome_message, suggestions: view.suggestions, max_steps: view.max_steps, daily_limit: view.daily_limit,
  });
});
const provider = computed(() => settings.value?.options.providers.find((item) => item.id === form.value.provider));
const claude = computed(() => form.value.provider === "anthropic");
const fallbackModel = computed(() => claude.value && ["claude-opus-5-5", "claude-sonnet-5-5"].includes(form.value.model));

// Model lists come from the providers themselves, so nobody types model names.
const catalog = ref<ModelCatalog | null>(null);
const catalogLoading = ref(false);
const modelFilter = ref("");
const typeModel = ref(false);
let catalogRequest = 0;
const recommendedIds = computed(() => new Set(settings.value?.options.models.map((model) => model.id) ?? []));
const otherClaude = computed(() => (catalog.value?.models ?? []).filter((model) => !recommendedIds.value.has(model.id)));
const listedModels = computed(() => {
  const words = modelFilter.value.toLowerCase().split(/\s+/).filter(Boolean);
  const models = catalog.value?.models ?? [];
  const shown = models.filter((model) => words.every((word) => `${model.id} ${model.label}`.toLowerCase().includes(word)));
  // Keep the saved model visible even when a filter or refreshed list leaves it out.
  return form.value.model && !shown.some((model) => model.id === form.value.model)
    ? [{ id: form.value.model, label: selectedModelMissing.value ? `${form.value.model} (no longer listed)` : form.value.model }, ...shown] : shown;
});

function pickDefault(list: ModelCatalog) {
  if (list.provider === "anthropic" || !list.models.length || list.error) return;
  if (!form.value.model || form.value.model.startsWith("claude-") || !list.models.some((model) => model.id === form.value.model)) {
    // Start from the provider's default model, or its first listed one.
    form.value.model = list.models.some((model) => model.id === list.default_model) ? list.default_model : list.models[0].id;
  }
}

const markCatalogRequested = useVisibleModelRefresh(() => {
  if (form.value.provider && !catalogLoading.value) void loadModels(true);
});
const selectedModelMissing = computed(() => !!catalog.value && !catalog.value.error && !!form.value.model
  && !catalog.value.models.some((item) => item.id === form.value.model));

async function loadModels(refresh = false, resetMissing = false) {
  const request = ++catalogRequest;
  const providerId = form.value.provider;
  markCatalogRequested();
  catalogLoading.value = true;
  try {
    const list = await hub.providerModels(providerId, refresh);
    if (request !== catalogRequest) return;
    const firstList = catalog.value?.provider !== providerId;
    catalog.value = list;
    if (resetMissing || firstList) typeModel.value = !list.models.length && providerId !== "anthropic";
    if (resetMissing) pickDefault(list);
  } catch (exc) {
    if (request !== catalogRequest) return;
    catalog.value = catalog.value?.provider === providerId
      ? { ...catalog.value, error: errorMessage(exc) }
      : { provider: providerId, models: [], source: "cache", fetched_at: null, default_model: "", error: errorMessage(exc) };
    typeModel.value = !catalog.value.models.length && providerId !== "anthropic";
  } finally {
    if (request === catalogRequest) catalogLoading.value = false;
  }
}

function chooseProvider(id: string) {
  form.value.provider = id;
  modelFilter.value = "";
  if (id === "anthropic" && !form.value.model.startsWith("claude-")) form.value.model = "claude-opus-5-5";
  else if (id !== "anthropic") form.value.model = "";
  catalog.value = null;
  void loadModels(true, true);
}

async function save(body: ChatSettingsUpdate, action: "toggle" | "save", message: string) {
  pending.value = action;
  try {
    const keep = action === "toggle" && dirty.value ? { ...form.value } : null;
    fill(await hub.updateChat(props.app.id, body));
    if (keep) form.value = keep;  // turning chat on or off keeps unsaved edits
    toast.ok(message);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    pending.value = "";
  }
}

// Saving model access keeps any unsaved edits in the chat form.
function gatewaySaved(view: ChatSettings) {
  if (settings.value) settings.value = { ...settings.value, gateway_models: view.gateway_models,
    monthly_token_limit: view.monthly_token_limit, gateway_usage: view.gateway_usage };
}

const newSuggestion = ref("");
function addSuggestion() {
  const text = newSuggestion.value.trim();
  if (text && form.value.suggestions.length < 6) form.value.suggestions.push(text);
  newSuggestion.value = "";
}

const request = computed(() => `POST ${hubUrl.value}/chat/v1/turn
Authorization: Bearer <a client key from the API keys tab>
X-Hub-Delegation: <the signed-in user, signed with this app's delegation secret>
Content-Type: application/json

{"message": "How many orders are pending?", "history": [], "locale": "id"}`);
</script>

<template>
  <p v-if="error" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
  <LoadingSkeleton v-else-if="!settings" variant="panel" :count="5" label="Loading chat settings" />
  <div v-else class="max-w-4xl">
    <div class="space-y-6">
      <section class="card">
        <div class="flex items-start justify-between gap-4 p-6">
          <div>
            <h2 class="card-title">AI chat for {{ app.name }}</h2>
            <p class="card-description mt-1.5 max-w-xl">
              A chat window your users open inside {{ app.name }}. The Hub runs the model with this app's tools and rules;
              {{ app.name }} only passes the signed-in user and shows the answer. Conversations are never stored in the Hub.
            </p>
            <p class="card-description mt-1.5 max-w-xl">
              While this is on, {{ app.name }} may also run its own chat on the Hub's models: it lists the models allowed
              under Model gateway access and calls the one its users pick through <code class="code">/gateway</code>, with the keys kept here.
            </p>
          </div>
          <span class="flex items-center gap-3">
            <button v-if="settings.enabled" type="button" class="btn-secondary btn-sm" @click="emit('try')">
              <AppIcon name="sparkles" :size="14" /> Try it</button>
            <span v-if="pending === 'toggle'" class="spinner text-subtle" />
            <ToggleSwitch :model-value="settings.enabled" label="Chat" :disabled="!editable || pending !== ''"
                          @update:model-value="(on: boolean) => save({ enabled: on }, 'toggle', on ? 'Chat turned on' : 'Chat turned off')" />
          </span>
        </div>
        <div v-if="provider && !provider.ready" class="mx-6 mb-5 flex items-start gap-3 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">
          <AppIcon name="alert" class="mt-0.5 shrink-0 text-warn" />
          <p v-if="form.provider === 'openai_compatible'">The Hub has no address for {{ provider.label }} yet. Add
            <code class="code">CHAT_OPENAI_BASE_URL</code> to the Hub's environment and restart it, or add the gateway under
            <RouterLink to="/providers" class="font-medium underline">AI providers</RouterLink>. Chat answers fail until then.</p>
          <p v-else-if="form.provider === 'anthropic'">The Hub has no key for {{ provider.label }} yet. A super admin can paste it under
            <RouterLink to="/providers" class="font-medium underline">AI providers</RouterLink>. Chat answers fail until then.</p>
          <p v-else>{{ provider.label }} has no API key or is turned off. A super admin can fix it under
            <RouterLink to="/providers" class="font-medium underline">AI providers</RouterLink>. Chat answers fail until then.</p>
        </div>

        <form class="space-y-5 border-t border-line p-6" @submit.prevent="save(form, 'save', 'Chat settings saved')">
          <fieldset :disabled="!editable || pending !== ''" class="space-y-5">
            <div>
              <span class="label">Model provider</span>
              <div class="flex flex-wrap items-center gap-2">
                <select :value="form.provider" class="input max-w-sm" aria-label="Model provider"
                        @change="chooseProvider(($event.target as HTMLSelectElement).value)">
                  <option v-for="item in settings.options.providers" :key="item.id" :value="item.id">
                    {{ item.label }}{{ item.ready ? "" : " (not ready)" }}</option>
                </select>
                <RouterLink to="/providers" class="btn-ghost text-xs"><AppIcon name="plus" :size="14" /> Add a provider</RouterLink>
              </div>
              <span class="hint">Claude, or any OpenAI-compatible provider added under AI providers (OpenAI, OpenRouter, Groq, Gemini, a gateway, Ollama…).</span>
            </div>
            <div v-if="claude" class="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Model">
              <label v-for="model in settings.options.models" :key="model.id"
                     class="flex cursor-pointer flex-col gap-1 rounded-lg border p-3 text-sm transition"
                     :class="form.model === model.id ? 'border-brand ring-1 ring-brand' : 'border-line hover:bg-muted/60'">
                <span class="flex items-center gap-2 font-medium">
                  <input v-model="form.model" type="radio" class="accent-current" :value="model.id" /> {{ model.label }}</span>
                <span class="text-xs text-subtle">{{ model.hint }}</span>
              </label>
            </div>
            <label v-if="claude && otherClaude.length" class="block"><span class="label">Other Claude models</span>
              <select class="input max-w-md" :value="recommendedIds.has(form.model) ? '' : form.model" aria-label="Other Claude models"
                      @change="form.model = ($event.target as HTMLSelectElement).value || form.model">
                <option value="">Choose another Claude model…</option>
                <option v-for="model in otherClaude" :key="model.id" :value="model.id">{{ model.label }} ({{ model.id }})</option>
              </select></label>
            <div v-if="!claude">
              <div class="flex items-center justify-between gap-2">
                <span class="label">Model</span>
                <button v-if="!typeModel" type="button" class="btn-ghost text-xs" @click="typeModel = true">Type a name instead</button>
                <button v-else-if="catalog?.models.length" type="button" class="btn-ghost text-xs" @click="typeModel = false">Pick from the list</button>
              </div>
              <input v-if="typeModel" v-model.trim="form.model" class="input font-mono" required aria-label="Model name"
                     placeholder="The model name exactly as the provider spells it" />
              <template v-else>
                <input v-if="(catalog?.models.length ?? 0) > 15" v-model="modelFilter" class="input mb-2" aria-label="Search models"
                       :placeholder="`Search ${catalog?.models.length} models`" />
                <select v-model="form.model" class="input font-mono" aria-label="Model" required :disabled="catalogLoading && !catalog">
                  <option v-if="catalogLoading && !catalog" value="">Loading models…</option>
                  <option v-for="model in listedModels" :key="model.id" :value="model.id">{{ model.label }}</option>
                </select>
              </template>
            </div>
            <p class="-mt-2 flex flex-wrap items-center gap-2 text-xs text-subtle">
              <span v-if="catalogLoading" class="spinner h-3 w-3" />
              <template v-if="catalogLoading">Loading models from {{ provider?.label }}…</template>
              <template v-else-if="catalog?.error"><span class="text-warn">{{ catalog.error }}</span></template>
              <template v-else-if="catalog">{{ catalog.models.length }} models from {{ provider?.label }}<template v-if="catalog.fetched_at">
                · updated {{ timeAgo(catalog.fetched_at) }}</template><template v-if="!claude">. Pick one that supports tool calling.</template></template>
              <button type="button" class="btn-ghost h-6 px-2 text-xs" :disabled="catalogLoading" @click="loadModels(true)">
                <AppIcon name="refresh" :size="12" /> Refresh list</button>
            </p>
            <p v-if="selectedModelMissing" class="-mt-2 text-xs text-warn">{{ form.model }} is not in the latest provider list. Check the name or choose another model.</p>
            <p v-if="fallbackModel" class="flex items-start gap-2 text-xs text-subtle">
              <AppIcon name="shield" :size="14" class="mt-0.5 shrink-0" />
              Server-side fallback is on: if Claude declines a request, Anthropic retries it on a fallback model within the same answer.
            </p>
            <div v-if="claude"><span class="label">Effort</span>
              <div class="segmented" role="tablist" aria-label="Effort">
                <button v-for="level in settings.options.efforts" :key="level" type="button" class="segmented-item capitalize" role="tab"
                        :aria-selected="form.effort === level" @click="form.effort = level">{{ level }}</button>
              </div>
              <span class="hint block">Higher effort thinks longer and costs more. Medium suits most chats.</span>
            </div>
            <div class="grid gap-4 sm:grid-cols-2">
              <label><span class="label">Tool steps per answer</span>
                <input v-model.number="form.max_steps" class="input" type="number" :min="settings.options.max_steps[0]" :max="settings.options.max_steps[1]" />
                <span class="hint">Rounds of tool calls before it must answer.</span></label>
              <label><span class="label">Messages per user per day</span>
                <input v-model.number="form.daily_limit" class="input" type="number" :min="settings.options.daily_limit[0]" :max="settings.options.daily_limit[1]" />
                <span class="hint">0 means no limit.</span></label>
            </div>
            <label class="block"><span class="label">Instructions for the assistant</span>
              <textarea v-model="form.instructions" class="input min-h-28" maxlength="4000"
                        placeholder="For example: Our users call projects 'campaigns'. Amounts are in IDR. Keep answers under 120 words." />
              <span class="hint">Added to the Hub's built-in safety rules, which always apply. No personal data.</span></label>
            <label class="block"><span class="label">Welcome message</span>
              <input v-model="form.welcome_message" class="input" maxlength="300" placeholder="Hi! Ask me about your campaigns, invoices or customers." /></label>
            <div>
              <span class="label">Suggested questions</span>
              <ul v-if="form.suggestions.length" class="mb-2 space-y-1.5">
                <li v-for="(text, index) in form.suggestions" :key="index" class="flex items-center gap-2 rounded-md bg-muted px-3 py-1.5 text-sm">
                  <span class="flex-1">{{ text }}</span>
                  <button type="button" class="text-subtle hover:text-bad" :aria-label="`Remove ${text}`" @click="form.suggestions.splice(index, 1)">
                    <AppIcon name="x" :size="14" /></button>
                </li>
              </ul>
              <div v-if="form.suggestions.length < 6" class="flex gap-2">
                <input v-model="newSuggestion" class="input" maxlength="120" placeholder="How many campaigns ran this month?"
                       @keydown.enter.prevent="addSuggestion" />
                <button type="button" class="btn-secondary" :disabled="!newSuggestion.trim()" @click="addSuggestion"><AppIcon name="plus" :size="16" /> Add</button>
              </div>
              <span class="hint">Shown as one-tap chips when a user opens the chat. Up to 6.</span>
            </div>
          </fieldset>
          <div v-if="editable" class="flex items-center justify-end gap-3 border-t border-line pt-4">
            <span v-if="dirty" class="text-xs text-subtle">Unsaved changes</span>
            <button class="btn-primary" type="submit" :disabled="!dirty || pending !== ''"><span v-if="pending === 'save'" class="spinner" /> Save settings</button>
          </div>
        </form>
      </section>

      <GatewayPanel :app-id="app.id" :app-name="app.name" :settings="settings" :editable="editable && session.isHubAdmin" @saved="gatewaySaved" />

      <section class="card card-pad space-y-4">
        <div>
          <h2 class="card-title">Build the chat into {{ app.name }}</h2>
          <p class="card-description mt-1.5">{{ app.name }} designs its own chat window. Its server sends each message to the Hub with the
            client key and the signed-in user, then streams the answer to the page. The key never reaches the browser, and the Hub keeps
            no conversation: send the visible history with every message.</p>
        </div>
        <CodeBlock :code="request" />
        <p class="text-xs text-subtle">The answer streams back as events: <code class="code">text</code> (the answer, in Markdown),
          <code class="code">tool</code> (progress), <code class="code">proposal</code> (a change to confirm in {{ app.name }}),
          <code class="code">notice</code>, <code class="code">error</code> and <code class="code">done</code>.
          <code class="code">GET /chat/v1/config</code> returns the welcome message, suggestions and skills.</p>
        <RouterLink to="/docs/laravel#chat" class="btn-secondary"><AppIcon name="book" :size="16" /> Laravel route and browser helper</RouterLink>
      </section>
    </div>
  </div>
</template>
