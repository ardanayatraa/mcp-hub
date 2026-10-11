<script setup lang="ts">
import { computed, ref } from "vue";

import ModalDialog from "@/components/ModalDialog.vue";
import SecretInput from "@/components/SecretInput.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type ModelProvider, type ProviderDraft, type ProviderPreset } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

// Add or edit one OpenAI-compatible provider. A new one starts from a preset.
const props = defineProps<{ provider?: ModelProvider; presets: ProviderPreset[]; taken: string[] }>();
const emit = defineEmits<{ close: []; saved: [provider: ModelProvider, created: boolean] }>();
const toast = useToast();
const editing = computed(() => !!props.provider);
const picked = ref<ProviderPreset | null>(null);
const saving = ref(false);
const form = ref({
  key: props.provider?.key ?? "", name: props.provider?.name ?? "", base_url: props.provider?.base_url ?? "",
  auth_style: props.provider?.auth_style ?? "bearer", auth_header: props.provider?.auth_header ?? "", api_key: "",
  clear_api_key: false, default_model: props.provider?.default_model ?? "", token_param: props.provider?.token_param ?? "max_tokens",
  tool_schema: props.provider?.tool_schema ?? "full", streaming: props.provider?.streaming ?? true,
});
const headers = ref<{ name: string; value: string }[]>(Object.entries(props.provider?.headers ?? {}).map(([name, value]) => ({ name, value })));
const keyTouched = ref(editing.value);

function slug(text: string) {
  return text.toLowerCase().replace(/\(.*?\)/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
}

function uniqueKey(base: string) {
  let key = base.length >= 2 ? base : `${base}ai`;
  for (let n = 2; props.taken.includes(key); n += 1) key = `${base.slice(0, 29)}-${n}`;
  return key;
}

function choose(preset: ProviderPreset) {
  picked.value = preset;
  form.value = { ...form.value, name: preset.key === "custom" ? "" : preset.name, base_url: preset.base_url,
    key: preset.key === "custom" ? "" : uniqueKey(preset.key), auth_style: preset.auth_style ?? "bearer",
    auth_header: preset.auth_header ?? "", token_param: preset.token_param ?? "max_tokens", tool_schema: preset.tool_schema ?? "full" };
  headers.value = Object.entries(preset.headers ?? {}).map(([name, value]) => ({ name, value }));
  keyTouched.value = preset.key !== "custom";
}

function onName() {
  if (!keyTouched.value) form.value.key = uniqueKey(slug(form.value.name));
}

const showForm = computed(() => editing.value || picked.value !== null);
const needsKey = computed(() => form.value.auth_style !== "none");

async function save() {
  saving.value = true;
  const body: ProviderDraft = {
    name: form.value.name, base_url: form.value.base_url, auth_style: form.value.auth_style,
    auth_header: form.value.auth_style === "header" ? form.value.auth_header : "", default_model: form.value.default_model.trim(),
    token_param: form.value.token_param, tool_schema: form.value.tool_schema, streaming: form.value.streaming,
    headers: Object.fromEntries(headers.value.filter((row) => row.name.trim()).map((row) => [row.name.trim(), row.value])),
  };
  if (form.value.api_key) body.api_key = form.value.api_key;
  if (editing.value && form.value.clear_api_key) body.clear_api_key = true;
  try {
    const saved = props.provider ? await hub.updateProvider(props.provider.id, body) : await hub.createProvider({ ...body, key: form.value.key });
    emit("saved", saved, !props.provider);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <ModalDialog :title="editing ? `Edit ${provider?.name}` : picked ? `Add ${picked.key === 'custom' ? 'a provider' : picked.name}` : 'Add an AI provider'"
               wide @close="saving || emit('close')">
    <div v-if="!showForm">
      <p class="mb-4 text-sm text-subtle">Any service that speaks the OpenAI Chat Completions API works. Pick one to fill in its address.</p>
      <div class="grid gap-2 sm:grid-cols-2">
        <button v-for="preset in presets" :key="preset.key" type="button"
                class="rounded-lg border border-line p-3 text-left transition hover:border-brand hover:bg-muted/50" @click="choose(preset)">
          <span class="block text-sm font-medium">{{ preset.name }}</span>
          <span class="mt-0.5 block text-xs text-subtle">{{ preset.hint }}</span>
        </button>
      </div>
    </div>

    <form v-else id="provider-form" class="space-y-4" @submit.prevent="save">
      <p v-if="picked?.hint" class="rounded-lg bg-muted px-3 py-2 text-xs text-subtle">{{ picked.hint }}</p>
      <div class="grid gap-4 sm:grid-cols-2">
        <label><span class="label">Name</span><input v-model="form.name" class="input" maxlength="80" required @input="onName" /></label>
        <label><span class="label">Key</span>
          <input v-model="form.key" class="input font-mono" :disabled="editing" required pattern="[a-z][a-z0-9_\-]{1,31}" maxlength="32"
                 @input="keyTouched = true" />
          <span class="hint">{{ editing ? "Apps refer to the provider by this key; it cannot change." : "Lowercase, for example groq or company-gateway." }}</span></label>
      </div>
      <label class="block"><span class="label">Base URL</span>
        <input v-model.trim="form.base_url" class="input font-mono" required placeholder="https://api.example.com/v1" />
        <span class="hint">The address before <code class="code">/chat/completions</code>.</span></label>
      <div>
        <span class="label">Authentication</span>
        <div class="segmented" role="tablist" aria-label="Authentication">
          <button v-for="[value, label] in [['bearer', 'API key'], ['header', 'Key in a named header'], ['none', 'No key']]" :key="value"
                  type="button" class="segmented-item" role="tab" :aria-selected="form.auth_style === value"
                  @click="form.auth_style = value as typeof form.auth_style">{{ label }}</button>
        </div>
      </div>
      <div v-if="needsKey" class="grid gap-4 sm:grid-cols-2">
        <label v-if="form.auth_style === 'header'"><span class="label">Header name</span>
          <input v-model.trim="form.auth_header" class="input font-mono" placeholder="api-key" required /></label>
        <label :class="form.auth_style === 'header' ? '' : 'sm:col-span-2'"><span class="label">API key</span>
          <SecretInput v-model="form.api_key" :placeholder="provider?.api_key_set ? `Saved${provider.api_key_hint ? ` (…${provider.api_key_hint})` : ''}. Leave empty to keep it.` : 'Paste the key'"
                       :required="!provider?.api_key_set" />
          <span class="hint">Stored encrypted. Never shown again, never sent to apps or browsers.</span></label>
      </div>
      <label v-if="editing && provider?.api_key_set" class="flex items-center gap-2 text-sm">
        <input v-model="form.clear_api_key" type="checkbox" /> Remove the saved key</label>
      <label class="block"><span class="label">Default model <span class="font-normal text-subtle">(optional)</span></span>
        <select v-if="provider?.models.length" v-model="form.default_model" class="input font-mono">
          <option value="">No default: apps start from the first model</option>
          <option v-if="form.default_model && !provider.models.includes(form.default_model)" :value="form.default_model">{{ form.default_model }}</option>
          <option v-for="model in provider.models" :key="model" :value="model">{{ model }}</option>
        </select>
        <input v-else v-model="form.default_model" class="input font-mono" placeholder="Filled in for apps that choose this provider" />
        <span class="hint">{{ provider?.models.length ? `${provider.models.length} models loaded from the provider.`
          : "The model list loads by itself when the provider is added; you can pick a default afterwards." }}</span></label>
      <details class="rounded-lg border border-line p-3">
        <summary class="cursor-pointer text-sm font-medium">Advanced</summary>
        <div class="mt-3 space-y-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <label><span class="label">Answer length parameter</span>
              <select v-model="form.token_param" class="input">
                <option value="max_tokens">max_tokens (most providers)</option>
                <option value="max_completion_tokens">max_completion_tokens (newer OpenAI models)</option>
                <option value="none">Do not send</option>
              </select></label>
            <label><span class="label">Tool schemas</span>
              <select v-model="form.tool_schema" class="input">
                <option value="full">Full (most providers)</option>
                <option value="basic">Basic (strict providers such as Gemini)</option>
              </select></label>
          </div>
          <label class="flex items-center gap-3 text-sm"><ToggleSwitch v-model="form.streaming" label="Stream answers" />
            Stream answers as they are written (turn off if the provider breaks on streamed tool calls)</label>
          <div>
            <span class="label">Extra headers</span>
            <div v-for="(row, index) in headers" :key="index" class="mb-2 flex gap-2">
              <input v-model="row.name" class="input w-40 font-mono" placeholder="X-Title" aria-label="Header name" />
              <input v-model="row.value" class="input flex-1" placeholder="Value" aria-label="Header value" />
              <button type="button" class="btn-ghost" aria-label="Remove header" @click="headers.splice(index, 1)"><AppIcon name="x" :size="16" /></button>
            </div>
            <button v-if="headers.length < 10" type="button" class="btn-ghost text-xs" @click="headers.push({ name: '', value: '' })">
              <AppIcon name="plus" :size="14" /> Add header</button>
            <span class="hint">Not secret, for example OpenRouter's X-Title. Put keys in the API key field.</span>
          </div>
        </div>
      </details>
    </form>

    <template #footer>
      <button v-if="picked && !editing" class="btn-ghost mr-auto" type="button" :disabled="saving" @click="picked = null">Back</button>
      <button class="btn-secondary" type="button" :disabled="saving" @click="emit('close')">Cancel</button>
      <button v-if="showForm" class="btn-primary" type="submit" form="provider-form" :disabled="saving">
        <span v-if="saving" class="spinner" /> {{ editing ? "Save" : "Add and test" }}</button>
    </template>
  </ModalDialog>
</template>
