<script setup lang="ts">
import { computed, reactive } from "vue";

import { hub, type CustomApiProbe } from "@/services/hub";
import { errorMessage } from "@/utils/format";
import { emptyEndpoint, FIELD_TYPES, slug, type Field, type Model, type Resource } from "@/utils/customApiSpec";

const props = defineProps<{ model: Model; connectorId: string; editable: boolean }>();
const emit = defineEmits<{ (event: "advanced"): void }>();

type Probe = CustomApiProbe & { error?: string; busy?: boolean };
// Per card, kept while the page is open: the last answer and every field it contained.
const probes = reactive<Record<number, Probe>>({});
const seen = reactive<Record<number, Record<string, string>>>({});
const more = reactive<Record<number, boolean>>({});
const draft = reactive<Record<number, { name: string; type: Field["type"] }>>({});

const single = (resource: Resource) => resource.endpoints.length === 1;
const several = computed(() => props.model.resources.filter((resource) => !single(resource)));
const indexOf = (resource: Resource) => props.model.resources.indexOf(resource);

function add() {
  const endpoint = emptyEndpoint();
  endpoint.name = "get";
  props.model.resources.push({ key: "", name: "", description: "", alias: "", fields: [], endpoints: [endpoint] });
}

function rename(resource: Resource) {
  // The key follows the name until it has been set by hand.
  if (!resource.key || resource.key === slug(resource.name.slice(0, -1)) || resource.key === slug(resource.name.slice(0, -2))) {
    resource.key = slug(resource.name);
  }
}

async function send(resource: Resource) {
  const at = indexOf(resource);
  const endpoint = resource.endpoints[0];
  probes[at] = { status: 0, elapsed_ms: 0, json: false, needs_user_sign_in: false, busy: true };
  try {
    const params: Record<string, string> = {};
    for (const param of endpoint.params.filter((item) => item.name.trim() && item.test !== "")) params[param.name.trim()] = param.test;
    const headers: Record<string, string> = {};
    for (const header of endpoint.headers.filter((item) => item.name.trim() && item.value)) headers[header.name.trim()] = header.value;
    for (const match of endpoint.path.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)) {
      if (!(match[1] in params)) {
        more[at] = true;
        throw new Error(`Give a test value for {${match[1]}} under More options.`);
      }
    }
    const found = await hub.probeCustomApi(props.connectorId, { path: endpoint.path.trim(), params, headers });
    probes[at] = { ...found, busy: false };
    if (found.fields && Object.keys(found.fields).length) {
      // Fill the card straight away: where the records are, and every field that is safe to show.
      endpoint.result_path = found.result_path ?? "";
      seen[at] = found.fields;
      const kept = new Map(resource.fields.map((field) => [field.name, field]));
      const next: Field[] = [];
      for (const [name, raw] of Object.entries(found.fields)) {
        if (found.sensitive?.includes(name)) continue;
        const type = raw.replace(/\?$/, "") as Field["type"];
        next.push(kept.get(name) ?? { name, type: FIELD_TYPES.includes(type) ? type : "string", nullable: raw.endsWith("?"), maxLength: null });
      }
      resource.fields = next;
    }
  } catch (exc) {
    probes[at] = { status: 0, elapsed_ms: 0, json: false, needs_user_sign_in: false, busy: false, error: errorMessage(exc) };
  }
}

const candidates = (resource: Resource): string[] => {
  const names = Object.keys(seen[indexOf(resource)] ?? {});
  for (const field of resource.fields) if (!names.includes(field.name)) names.push(field.name);
  return names;
};
const on = (resource: Resource, name: string) => resource.fields.some((field) => field.name === name);
const locked = (resource: Resource, name: string) => !!probes[indexOf(resource)]?.sensitive?.includes(name);

function addField(resource: Resource) {
  const at = indexOf(resource);
  const item = draft[at];
  const name = item?.name.trim();
  if (!name || on(resource, name)) return;
  resource.fields.push({ name, type: item.type, nullable: false, maxLength: null });
  draft[at] = { name: "", type: "string" };
}

function toggle(resource: Resource, name: string) {
  if (on(resource, name)) {
    resource.fields = resource.fields.filter((field) => field.name !== name);
    return;
  }
  const raw = seen[indexOf(resource)]?.[name] ?? "string";
  const type = raw.replace(/\?$/, "") as Field["type"];
  resource.fields.push({ name, type: FIELD_TYPES.includes(type) ? type : "string", nullable: raw.endsWith("?"), maxLength: null });
}

const tone = (status: number) => (status >= 200 && status < 300 ? "text-ok" : "text-bad");
</script>

<template>
  <div class="space-y-4">
    <p v-if="!model.resources.length" class="rounded-lg border border-dashed border-line p-6 text-center text-sm text-subtle">
      No endpoints yet. Add one: give it a name and an address, then click Send.
    </p>

    <template v-for="resource in model.resources" :key="indexOf(resource)">
      <article v-if="single(resource)" class="space-y-3 rounded-lg border border-line p-4">
        <div class="flex flex-wrap items-center gap-2">
          <input v-model="resource.name" class="input w-44 font-medium" placeholder="Name, e.g. My orders" :disabled="!editable"
                 aria-label="Endpoint name" @input="rename(resource)" />
          <span class="badge-neutral font-mono">GET</span>
          <input v-model="resource.endpoints[0].path" class="input min-w-[12rem] flex-1 font-mono" placeholder="/api/pesanan" :disabled="!editable" aria-label="Address" />
          <button type="button" class="btn-primary btn-sm" :disabled="probes[indexOf(resource)]?.busy || !resource.endpoints[0].path.startsWith('/')" @click="send(resource)">
            <span v-if="probes[indexOf(resource)]?.busy" class="spinner" /> Send</button>
          <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove endpoint" @click="model.resources.splice(indexOf(resource), 1)">✕</button>
        </div>

        <input v-model="resource.endpoints[0].description" class="input" placeholder="What does it return? e.g. The signed-in user's orders" :disabled="!editable" aria-label="Description" />

        <template v-if="probes[indexOf(resource)] && !probes[indexOf(resource)].busy">
          <p v-if="probes[indexOf(resource)].error" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ probes[indexOf(resource)].error }}</p>
          <p v-else class="text-sm">
            <span class="font-mono font-semibold" :class="tone(probes[indexOf(resource)].status)">{{ probes[indexOf(resource)].status }}</span>
            <span class="text-subtle"> · {{ probes[indexOf(resource)].elapsed_ms }} ms</span>
            <span v-if="probes[indexOf(resource)].needs_user_sign_in" class="text-subtle"> · this API wants a signed-in user, so it cannot be tried from here. Add the fields below by hand.</span>
            <span v-else-if="!probes[indexOf(resource)].json" class="text-subtle"> · the answer is not JSON</span>
            <span v-else-if="probes[indexOf(resource)].count !== undefined" class="text-subtle"> · {{ probes[indexOf(resource)].count }} records found</span>
          </p>
        </template>

        <div>
          <span class="label">Fields AI may see</span>
          <div class="flex flex-wrap gap-2">
            <label v-for="name in candidates(resource)" :key="name"
                   class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
                   :class="locked(resource, name) ? 'border-line text-subtle opacity-60' : on(resource, name) ? 'border-brand bg-brand-soft text-ink' : 'border-line text-subtle'">
              <input type="checkbox" :checked="on(resource, name)" :disabled="!editable || locked(resource, name)" @change="toggle(resource, name)" />
              <span class="font-mono">{{ name }}</span>
              <span v-if="locked(resource, name)" title="Looks sensitive: always blocked from AI">🔒</span>
            </label>
          </div>
          <form v-if="editable" class="mt-2 flex items-center gap-2" @submit.prevent="addField(resource)">
            <input :value="draft[indexOf(resource)]?.name ?? ''" class="input w-44 font-mono" placeholder="add a field by hand"
                   aria-label="New field name" @input="draft[indexOf(resource)] = { name: ($event.target as HTMLInputElement).value, type: draft[indexOf(resource)]?.type ?? 'string' }" />
            <select :value="draft[indexOf(resource)]?.type ?? 'string'" class="input w-32" aria-label="New field type"
                    @change="draft[indexOf(resource)] = { name: draft[indexOf(resource)]?.name ?? '', type: ($event.target as HTMLSelectElement).value as Field['type'] }">
              <option v-for="t in FIELD_TYPES" :key="t">{{ t }}</option></select>
            <button type="submit" class="btn-ghost btn-sm">Add</button>
          </form>
        </div>

        <details :open="more[indexOf(resource)]" @toggle="more[indexOf(resource)] = ($event.target as HTMLDetailsElement).open">
          <summary class="cursor-pointer text-sm font-medium text-subtle">More options: parameters, headers, where the data is</summary>
          <div class="mt-3 space-y-4">
            <label class="block"><span class="label">Records are at</span>
              <input v-model="resource.endpoints[0].result_path" class="input font-mono" placeholder="products (empty = the whole answer)" :disabled="!editable" /></label>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="label mb-0">Parameters</span>
                <button v-if="editable" type="button" class="btn-ghost btn-sm" @click="resource.endpoints[0].params.push({ name: '', type: 'string', required: false, test: '' })">+ Parameter</button>
              </div>
              <p v-if="!resource.endpoints[0].params.length" class="text-xs text-subtle">None. Use <span class="code">{id}</span> in the address for a value taken from the question.</p>
              <div v-for="(param, n) in resource.endpoints[0].params" :key="n" class="mb-2 grid grid-cols-[1fr_6.5rem_auto_1fr_auto] items-center gap-2">
                <input v-model="param.name" class="input font-mono" placeholder="q" :disabled="!editable" aria-label="Parameter name" />
                <select v-model="param.type" class="input" :disabled="!editable" aria-label="Parameter type"><option v-for="t in FIELD_TYPES" :key="t">{{ t }}</option></select>
                <label class="flex items-center gap-1 text-xs"><input v-model="param.required" type="checkbox" :disabled="!editable" /> required</label>
                <input v-model="param.test" class="input" placeholder="test value (not saved)" aria-label="Test value" />
                <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove parameter" @click="resource.endpoints[0].params.splice(n, 1)">✕</button>
              </div>
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="label mb-0">Headers</span>
                <button v-if="editable" type="button" class="btn-ghost btn-sm" @click="resource.endpoints[0].headers.push({ name: '', value: '' })">+ Header</button>
              </div>
              <p v-if="!resource.endpoints[0].headers.length" class="text-xs text-subtle">None. Fixed, non-secret headers only; the API key belongs to the connection.</p>
              <div v-for="(header, n) in resource.endpoints[0].headers" :key="n" class="mb-2 grid grid-cols-[1fr_1fr_auto] items-center gap-2">
                <input v-model="header.name" class="input font-mono" placeholder="Accept-Language" :disabled="!editable" aria-label="Header name" />
                <input v-model="header.value" class="input font-mono" placeholder="id" :disabled="!editable" aria-label="Header value" />
                <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove header" @click="resource.endpoints[0].headers.splice(n, 1)">✕</button>
              </div>
            </div>
          </div>
        </details>
      </article>
    </template>

    <p v-if="several.length" class="rounded-lg bg-muted/60 px-3 py-2 text-sm text-subtle">
      {{ several.map((item) => item.name || item.key).join(", ") }} groups several endpoints and can only be edited in
      <button type="button" class="font-medium underline" @click="emit('advanced')">Advanced</button> mode.
    </p>

    <button v-if="editable" type="button" class="btn-secondary" @click="add">+ Endpoint</button>
  </div>
</template>
