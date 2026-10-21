<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { hub, type ChatSettings, type GatewayModel } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

// Which Hub models the app may call through /gateway, its monthly token budget and this month's usage.
const props = defineProps<{ appId: string; appName: string; settings: ChatSettings; editable: boolean }>();
const emit = defineEmits<{ saved: [view: ChatSettings] }>();
const toast = useToast();

const allowed = ref<string[]>([]);
const budget = ref(0);
watch(() => props.settings, (view) => {
  allowed.value = [...view.gateway_models];
  budget.value = view.monthly_token_limit;
}, { immediate: true });

const models = ref<GatewayModel[] | null>(null);
const loading = ref(false);
const filter = ref("");
async function loadModels() {
  loading.value = true;
  try {
    models.value = (await hub.gatewayModels(props.appId)).models;
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    loading.value = false;
  }
}

const providers = computed(() => [...new Set((models.value ?? []).map((model) => model.provider))]);
const shown = computed(() => {
  const words = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
  return (models.value ?? []).filter((model) => words.every((word) => `${model.id} ${model.name}`.toLowerCase().includes(word))).slice(0, 200);
});
function toggle(id: string) {
  allowed.value = allowed.value.includes(id) ? allowed.value.filter((item) => item !== id) : [...allowed.value, id];
}

const dirty = computed(() => JSON.stringify(allowed.value) !== JSON.stringify(props.settings.gateway_models)
  || budget.value !== props.settings.monthly_token_limit);
const saving = ref(false);
async function save() {
  saving.value = true;
  try {
    emit("saved", await hub.updateChat(props.appId, { gateway_models: allowed.value, monthly_token_limit: budget.value || 0 }));
    toast.ok("Model access saved");
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    saving.value = false;
  }
}

const usage = computed(() => props.settings.gateway_usage);
const used = computed(() => usage.value.prompt_tokens + usage.value.completion_tokens);
const share = computed(() => (props.settings.monthly_token_limit ? Math.min(100, Math.round((used.value / props.settings.monthly_token_limit) * 100)) : 0));
const number = (value: number) => value.toLocaleString();
</script>

<template>
  <section class="card card-pad space-y-5">
    <div>
      <h2 class="card-title">Model gateway access</h2>
      <p class="card-description mt-1.5">The models {{ appName }} may call through <code class="code">/gateway</code> for its own chat,
        and how many tokens it may use each month. Calls with any other model are refused.
        <template v-if="!editable">Only a super admin can change these.</template></p>
    </div>

    <div class="grid gap-3 sm:grid-cols-3">
      <div class="rounded-lg bg-muted p-3"><span class="text-xs text-subtle">Calls in {{ usage.period }}</span>
        <p class="text-lg font-semibold">{{ number(usage.calls) }}</p>
        <span v-if="usage.errors" class="text-xs text-warn">{{ number(usage.errors) }} failed</span></div>
      <div class="rounded-lg bg-muted p-3"><span class="text-xs text-subtle">Tokens used</span>
        <p class="text-lg font-semibold">{{ number(used) }}</p>
        <span class="text-xs text-subtle">{{ number(usage.prompt_tokens) }} in · {{ number(usage.completion_tokens) }} out</span></div>
      <div class="rounded-lg bg-muted p-3"><span class="text-xs text-subtle">Monthly budget</span>
        <p class="text-lg font-semibold">{{ settings.monthly_token_limit ? number(settings.monthly_token_limit) : "No budget" }}</p>
        <p v-if="settings.monthly_token_limit" class="text-xs" :class="share >= 90 ? 'text-bad' : 'text-subtle'">{{ share }}% used</p></div>
    </div>
    <ul v-if="usage.models.length" class="space-y-1 text-xs text-subtle">
      <li v-for="row in usage.models.slice(0, 5)" :key="row.model" class="flex justify-between gap-3">
        <span class="truncate font-mono">{{ row.model }}</span><span class="shrink-0">{{ number(row.calls) }} calls · {{ number(row.tokens) }} tokens</span></li>
    </ul>

    <fieldset :disabled="!editable || saving" class="space-y-4">
      <div>
        <span class="label">Allowed models</span>
        <div v-if="!allowed.length" class="mb-2 flex items-start gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">
          <AppIcon name="alert" class="mt-0.5 shrink-0 text-warn" />
          <p>Every model under AI providers is open to {{ appName }}, including the most expensive ones. Pick the ones it needs.</p>
        </div>
        <ul v-else class="mb-2 flex flex-wrap gap-1.5">
          <li v-for="id in allowed" :key="id" class="flex items-center gap-1 rounded-md bg-muted px-2 py-1 font-mono text-xs">
            {{ id }}
            <button type="button" class="text-subtle hover:text-bad" :aria-label="`Remove ${id}`" @click="toggle(id)"><AppIcon name="x" :size="12" /></button>
          </li>
        </ul>
        <button v-if="!models" type="button" class="btn-secondary" :disabled="loading" @click="loadModels">
          <span v-if="loading" class="spinner" /> Choose models</button>
        <div v-else class="space-y-2">
          <div class="flex flex-wrap gap-2">
            <input v-model="filter" class="input max-w-sm" placeholder="Filter models" aria-label="Filter models" />
            <button v-for="name in providers" :key="name" type="button" class="btn-ghost h-9 px-2 text-xs"
                    :aria-pressed="allowed.includes(`${name}/*`)" @click="toggle(`${name}/*`)">
              {{ allowed.includes(`${name}/*`) ? "✓ " : "" }}All of {{ name }}</button>
          </div>
          <div class="max-h-64 overflow-y-auto rounded-lg border border-line">
            <label v-for="model in shown" :key="model.id" class="flex cursor-pointer items-center gap-2 border-b border-line px-3 py-1.5 text-sm last:border-0">
              <input type="checkbox" :checked="allowed.includes(model.id)" @change="toggle(model.id)" />
              <span class="truncate">{{ model.name }}</span>
            </label>
            <p v-if="!shown.length" class="p-3 text-sm text-subtle">No model matches.</p>
          </div>
          <span class="hint">{{ models.length }} models on the Hub<template v-if="shown.length === 200">; the first 200 matches are shown</template>.</span>
        </div>
      </div>
      <label class="block max-w-xs"><span class="label">Tokens per month</span>
        <input v-model.number="budget" class="input" type="number" min="0" :max="settings.options.monthly_token_limit[1]" step="100000" />
        <span class="hint">Input plus output tokens, all models together. 0 means no budget.</span></label>
    </fieldset>
    <div v-if="editable" class="flex items-center justify-end gap-3 border-t border-line pt-4">
      <span v-if="dirty" class="text-xs text-subtle">Unsaved changes</span>
      <button class="btn-primary" type="button" :disabled="!dirty || saving" @click="save"><span v-if="saving" class="spinner" /> Save model access</button>
    </div>
  </section>
</template>
