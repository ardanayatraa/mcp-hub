<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import CustomApiEditor from "@/components/CustomApiEditor.vue";
import { hub, type AppDetail } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";
import { emptyResource, fromSpec, problems, toSpec, type Model } from "@/utils/customApiSpec";

const props = defineProps<{ app: AppDetail; editable: boolean }>();
const emit = defineEmits<{ (event: "saved"): void }>();
const toast = useToast();

const EXAMPLE = {
  resources: {
    product: {
      name: "Products",
      alias: ["produk", "menu"],
      fields: { id: "integer", title: "string", price: "number" },
      endpoints: [
        { name: "daftar_produk", path: "/products", result_path: "products" },
        { name: "cari_produk", path: "/products/search", params: { q: "string" }, required: ["q"], result_path: "products" },
        { name: "detail_produk", path: "/products/{id}" },
      ],
    },
  },
};

const mode = ref<"visual" | "json">("visual");
const model = reactive<Model>(fromSpec(props.app.custom_spec ?? null));
const text = ref("");
const error = ref("");
const saving = ref(false);

function load() {
  Object.assign(model, fromSpec(props.app.custom_spec ?? null));
  if (!model.resources.length) model.resources.push(emptyResource());
  text.value = JSON.stringify(props.app.custom_spec ?? EXAMPLE, null, 2);
  error.value = "";
}
load();
watch(() => props.app.custom_spec, load);

const saved = computed(() => !!props.app.custom_spec?.resources);
const issues = computed(() => (mode.value === "visual" ? problems(model) : []));

function switchTo(next: "visual" | "json") {
  error.value = "";
  if (next === mode.value) return;
  if (next === "json") {
    text.value = JSON.stringify(toSpec(model), null, 2);
  } else {
    try {
      Object.assign(model, fromSpec(JSON.parse(text.value)));
    } catch {
      error.value = "This is not valid JSON, so it cannot be shown visually yet.";
      return;
    }
  }
  mode.value = next;
}

async function save() {
  error.value = "";
  let body: unknown;
  if (mode.value === "visual") {
    if (issues.value.length) { error.value = issues.value[0]; return; }
    body = toSpec(model);
  } else {
    try {
      body = JSON.parse(text.value);
    } catch {
      error.value = "This is not valid JSON. Check for a missing comma, quote or bracket.";
      return;
    }
  }
  saving.value = true;
  try {
    await hub.saveCustomApi(props.app.id, body);
    toast.ok("Endpoints saved. Test the connection, then activate the app.");
    emit("saved");
  } catch (exc) {
    error.value = errorMessage(exc);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="grid gap-6 xl:grid-cols-3">
    <form class="card card-pad space-y-4 xl:col-span-2" @submit.prevent="save">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="section-title">API of {{ app.base_url }}</h2>
          <p class="text-sm text-subtle">
            Describe the requests AI may send, like in an API client. Each endpoint becomes a tool named
            <span class="code">{{ app.app_key }}__resource__endpoint</span>. Only reading (GET) is supported for now.
          </p>
        </div>
        <div class="inline-flex rounded-lg border border-line p-0.5 text-sm" role="tablist" aria-label="Editor mode">
          <button type="button" role="tab" :aria-selected="mode === 'visual'" :class="mode === 'visual' ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'" @click="switchTo('visual')">Visual</button>
          <button type="button" role="tab" :aria-selected="mode === 'json'" :class="mode === 'json' ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'" @click="switchTo('json')">JSON</button>
        </div>
      </div>

      <CustomApiEditor v-if="mode === 'visual'" :model="model" :connector-id="app.id" :editable="editable" />
      <textarea v-else v-model="text" class="input min-h-[26rem] font-mono text-xs leading-relaxed" spellcheck="false"
                :disabled="!editable || saving" aria-label="Endpoint list as JSON" />

      <ul v-if="issues.length" class="rounded-lg bg-warn-soft px-3 py-2 text-sm">
        <li v-for="item in issues.slice(0, 4)" :key="item">{{ item }}</li>
      </ul>
      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
      <div v-if="editable" class="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <button v-if="mode === 'json'" type="button" class="btn-ghost btn-sm" :disabled="saving" @click="text = JSON.stringify(EXAMPLE, null, 2)">Insert example</button>
        <span v-else />
        <div class="flex items-center gap-3">
          <span v-if="saved" class="text-xs text-ok">Saved</span>
          <button class="btn-primary" type="submit" :disabled="saving || (mode === 'visual' && issues.length > 0)">
            <span v-if="saving" class="spinner" /> {{ saving ? "Saving…" : "Save endpoints" }}</button>
        </div>
      </div>
    </form>

    <aside class="card card-pad space-y-3 self-start text-sm">
      <h2 class="section-title">How it works</h2>
      <dl class="space-y-2 text-subtle">
        <div><dt class="font-medium text-ink">Send</dt>
          <dd>Sends the request to the API with this connection's credentials and shows the answer. One click then fills in where the records are and which fields exist.</dd></div>
        <div><dt class="font-medium text-ink">Fields AI may see</dt>
          <dd>Only these reach AI, whatever else the API returns. Names such as email or password are always blocked.</dd></div>
        <div><dt class="font-medium text-ink">Parameters</dt>
          <dd>Query values the question can fill in. <span class="code">{id}</span> in the path becomes a required one. The test value is only for Send and is not saved.</dd></div>
        <div><dt class="font-medium text-ink">Headers</dt>
          <dd>Fixed, non-secret headers for one endpoint. The API key belongs to the connection (Connection tab), stored encrypted.</dd></div>
        <div><dt class="font-medium text-ink">Data per user</dt>
          <dd>Tick the box on top, and users sign in with their own account in the embedded chat. The API then decides what each one sees.</dd></div>
      </dl>
      <p class="text-xs text-subtle">Saving applies right away; nothing is redeployed.</p>
    </aside>
  </section>
</template>
