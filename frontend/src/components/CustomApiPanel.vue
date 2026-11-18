<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { hub, type AppDetail } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";

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

const text = ref("");
const error = ref("");
const saving = ref(false);

function fromApp() {
  text.value = JSON.stringify(props.app.custom_spec ?? EXAMPLE, null, 2);
}
fromApp();
watch(() => props.app.custom_spec, fromApp);

const saved = computed(() => !!props.app.custom_spec);
const dirty = computed(() => {
  try { return JSON.stringify(JSON.parse(text.value)) !== JSON.stringify(props.app.custom_spec ?? null); } catch { return true; }
});

async function save() {
  error.value = "";
  let body: unknown;
  try {
    body = JSON.parse(text.value);
  } catch {
    error.value = "This is not valid JSON. Check for a missing comma, quote or bracket.";
    return;
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
  <section class="grid gap-6 lg:grid-cols-3">
    <form class="card card-pad space-y-4 lg:col-span-2" @submit.prevent="save">
      <div>
        <h2 class="section-title">Endpoints of {{ app.base_url }}</h2>
        <p class="text-sm text-subtle">
          List the resources and read endpoints you want AI to use. Every endpoint becomes one tool
          named <span class="code">{{ app.app_key }}__resource__endpoint</span>.
          Only GET is supported for now.
        </p>
      </div>
      <textarea v-model="text" class="input min-h-[26rem] font-mono text-xs leading-relaxed" spellcheck="false"
                :disabled="!editable || saving" aria-label="Endpoint list as JSON" />
      <p v-if="error" role="alert" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>
      <div v-if="editable" class="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <button type="button" class="btn-ghost btn-sm" :disabled="saving" @click="text = JSON.stringify(EXAMPLE, null, 2)">Insert example</button>
        <div class="flex items-center gap-3">
          <span v-if="saved && !dirty" class="text-xs text-ok">Saved</span>
          <button class="btn-primary" type="submit" :disabled="saving">
            <span v-if="saving" class="spinner" /> {{ saving ? "Saving…" : "Save endpoints" }}</button>
        </div>
      </div>
    </form>

    <aside class="card card-pad space-y-3 text-sm">
      <h2 class="section-title">How to write it</h2>
      <dl class="space-y-2 text-subtle">
        <div><dt class="font-medium text-ink">fields</dt>
          <dd>The only fields AI may see, with a type: <span class="code">string</span>, <span class="code">integer</span>,
            <span class="code">number</span>, <span class="code">boolean</span>. Add <span class="code">?</span> to allow null.
            Use <span class="code">{"type":"string","maxLength":1000}</span> for long text.</dd></div>
        <div><dt class="font-medium text-ink">path</dt>
          <dd>Starts with <span class="code">/</span>. <span class="code">{id}</span> becomes a required argument.</dd></div>
        <div><dt class="font-medium text-ink">params / required</dt>
          <dd>Query arguments the tool accepts, and which of them must be given.</dd></div>
        <div><dt class="font-medium text-ink">result_path</dt>
          <dd>Where the records sit in the response, such as <span class="code">products</span> or
            <span class="code">data.items</span>. Leave it out when the response itself is the record.</dd></div>
        <div><dt class="font-medium text-ink">alias</dt>
          <dd>Everyday words for the resource, so AI and chat can match them.</dd></div>
      </dl>
      <p class="text-xs text-subtle">Treated as data anyone with this connection may read: there is no per-user filter.
        Saving applies right away; no redeploy.</p>
    </aside>
  </section>
</template>
