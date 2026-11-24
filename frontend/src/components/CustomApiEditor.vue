<script setup lang="ts">
import { reactive, ref } from "vue";

import { hub, type CustomApiProbe } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";
import { emptyEndpoint, emptyResource, FIELD_TYPES, slug, type Endpoint, type Field, type Model, type Resource } from "@/utils/customApiSpec";

const props = defineProps<{ model: Model; connectorId: string; editable: boolean; linkId?: string }>();
const emit = defineEmits<{ (event: "signIn"): void }>();
const toast = useToast();

// One test result per endpoint, kept only while this page is open.
const results = reactive<Record<string, CustomApiProbe & { error?: string; busy?: boolean }>>({});
const open = ref<Record<string, boolean>>({});
const slot = (resource: Resource, endpoint: Endpoint) => `${resource.key}/${endpoint.name}/${props.model.resources.indexOf(resource)}`;

function addResource() {
  const resource = emptyResource();
  props.model.resources.push(resource);
}
function removeResource(index: number) { props.model.resources.splice(index, 1); }
function addEndpoint(resource: Resource) { resource.endpoints.push(emptyEndpoint()); }
function removeEndpoint(resource: Resource, index: number) { resource.endpoints.splice(index, 1); }
function addField(resource: Resource) { resource.fields.push({ name: "", type: "string", nullable: false, maxLength: null }); }
function nameResource(resource: Resource) { if (!resource.key || resource.key === slug(resource.name.slice(0, -1))) resource.key = slug(resource.name); }

async function send(resource: Resource, endpoint: Endpoint) {
  const key = slot(resource, endpoint);
  results[key] = { status: 0, elapsed_ms: 0, json: false, busy: true } as never;
  try {
    const params: Record<string, string> = {};
    for (const param of endpoint.params.filter((item) => item.name.trim() && item.test !== "")) params[param.name.trim()] = param.test;
    const headers: Record<string, string> = {};
    for (const header of endpoint.headers.filter((item) => item.name.trim() && item.value)) headers[header.name.trim()] = header.value;
    // Placeholders in the path take their value from the matching test value.
    for (const match of endpoint.path.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)) {
      if (!(match[1] in params)) throw new Error(`Give a test value for {${match[1]}} under Parameters.`);
    }
    results[key] = {
      ...(await hub.probeCustomApi(props.connectorId, {
        path: endpoint.path.trim(), params, headers, ...(props.linkId ? { link_id: props.linkId } : {}),
      })),
      busy: false,
    };
  } catch (exc) {
    results[key] = { status: 0, elapsed_ms: 0, json: false, busy: false, error: errorMessage(exc) } as never;
  }
}

function useDetected(resource: Resource, endpoint: Endpoint) {
  const found = results[slot(resource, endpoint)];
  if (!found?.fields) return;
  endpoint.result_path = found.result_path ?? "";
  const keep = new Map(resource.fields.map((field) => [field.name, field]));
  const next: Field[] = [];
  for (const [name, raw] of Object.entries(found.fields)) {
    if (found.sensitive?.includes(name)) continue;
    const type = raw.replace(/\?$/, "") as Field["type"];
    next.push(keep.get(name) ?? { name, type: FIELD_TYPES.includes(type) ? type : "string", nullable: raw.endsWith("?"), maxLength: null });
  }
  if (next.length) resource.fields = next;
  toast.ok("Result path and fields filled in from the response");
}

const statusTone = (status: number) => (status >= 200 && status < 300 ? "text-ok" : status === 0 ? "text-subtle" : "text-bad");
</script>

<template>
  <div class="space-y-5">
    <section class="rounded-lg border border-line p-4 space-y-3">
      <label class="flex items-center gap-3 text-sm font-medium">
        <input v-model="model.userAuth.enabled" type="checkbox" :disabled="!editable" />
        Each user signs in with their own account (data per user)
      </label>
      <div v-if="model.userAuth.enabled" class="grid gap-3 sm:grid-cols-2">
        <label class="sm:col-span-2"><span class="label">How the chat learns who the user is</span>
          <select v-model="model.userAuth.mode" class="input" :disabled="!editable">
            <option value="token">The page hands over the token its user already has (no login API needed)</option>
            <option value="form">The chat asks for email and password and posts them to a login API</option>
          </select>
          <span class="hint">{{ model.userAuth.mode === "token"
            ? "Add data-token to the snippet on the signed-in page. The API only needs to accept that token."
            : "The API must return a token from a login request." }}</span></label>
        <template v-if="model.userAuth.mode === 'form'">
          <label><span class="label">Login path</span><input v-model="model.userAuth.login_path" class="input font-mono" :disabled="!editable" /></label>
          <label><span class="label">Login fields</span><input v-model="model.userAuth.fields" class="input font-mono" placeholder="email, password" :disabled="!editable" />
            <span class="hint">The form the user fills in, posted as JSON.</span></label>
          <label><span class="label">Token in the answer</span><input v-model="model.userAuth.token_path" class="input font-mono" :disabled="!editable" />
            <span class="hint">Where the token sits, such as token or data.access_token.</span></label>
        </template>
        <label><span class="label">Who am I path (optional)</span><input v-model="model.userAuth.me_path" class="input font-mono" :disabled="!editable" />
          <span class="hint">Only gives the user's name, and checks the token early.</span></label>
        <label v-if="model.userAuth.me_path"><span class="label">Name in that answer</span><input v-model="model.userAuth.name_path" class="input font-mono" :disabled="!editable" /></label>
      </div>
      <p v-if="model.authHeader" class="text-xs text-subtle">The connection sends its API key in the <span class="code">{{ model.authHeader }}</span> header.</p>
    </section>

    <section v-for="(resource, index) in model.resources" :key="index" class="rounded-lg border border-line">
      <header class="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-muted/40 px-4 py-3">
        <h3 class="text-sm font-semibold">{{ resource.name || resource.key || "New resource" }}</h3>
        <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" @click="removeResource(index)">Remove resource</button>
      </header>
      <div class="space-y-5 p-4">
        <div class="grid gap-3 sm:grid-cols-3">
          <label><span class="label">Name</span><input v-model="resource.name" class="input" placeholder="Products" :disabled="!editable" @input="nameResource(resource)" /></label>
          <label><span class="label">Key</span><input v-model="resource.key" class="input font-mono" placeholder="products" :disabled="!editable" />
            <span class="hint">Part of each tool's name.</span></label>
          <label><span class="label">Also called</span><input v-model="resource.alias" class="input" placeholder="produk, barang" :disabled="!editable" />
            <span class="hint">Everyday words, comma separated.</span></label>
        </div>

        <div>
          <div class="mb-2 flex items-center justify-between">
            <h4 class="text-xs font-semibold uppercase tracking-wide text-subtle">Fields AI may see</h4>
            <button v-if="editable" type="button" class="btn-ghost btn-sm" @click="addField(resource)">+ Field</button>
          </div>
          <div class="space-y-2">
            <div v-for="(field, n) in resource.fields" :key="n" class="grid grid-cols-[1fr_7rem_auto_5.5rem_auto] items-center gap-2">
              <input v-model="field.name" class="input font-mono" placeholder="field name" :disabled="!editable" aria-label="Field name" />
              <select v-model="field.type" class="input" :disabled="!editable" aria-label="Field type"><option v-for="t in FIELD_TYPES" :key="t">{{ t }}</option></select>
              <label class="flex items-center gap-1 text-xs"><input v-model="field.nullable" type="checkbox" :disabled="!editable" /> may be empty</label>
              <input v-if="field.type === 'string'" v-model.number="field.maxLength" class="input" type="number" min="1" max="2000" placeholder="max length" :disabled="!editable" aria-label="Maximum length" />
              <span v-else />
              <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove field" @click="resource.fields.splice(n, 1)">✕</button>
            </div>
          </div>
        </div>

        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <h4 class="text-xs font-semibold uppercase tracking-wide text-subtle">Endpoints</h4>
            <button v-if="editable" type="button" class="btn-secondary btn-sm" @click="addEndpoint(resource)">+ Endpoint</button>
          </div>

          <article v-for="(endpoint, e) in resource.endpoints" :key="e" class="space-y-3 rounded-lg border border-line p-3">
            <div class="flex flex-wrap items-center gap-2">
              <span class="badge-neutral font-mono">GET</span>
              <input v-model="endpoint.path" class="input min-w-[14rem] flex-1 font-mono" placeholder="/products/search" :disabled="!editable" aria-label="Path" />
              <button type="button" class="btn-primary btn-sm" :disabled="results[slot(resource, endpoint)]?.busy" @click="send(resource, endpoint)">
                <span v-if="results[slot(resource, endpoint)]?.busy" class="spinner" /> Send</button>
              <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove endpoint" @click="removeEndpoint(resource, e)">✕</button>
            </div>
            <div class="grid gap-3 sm:grid-cols-3">
              <label><span class="label">Name</span><input v-model="endpoint.name" class="input font-mono" placeholder="search" :disabled="!editable" /></label>
              <label><span class="label">Records are at</span><input v-model="endpoint.result_path" class="input font-mono" placeholder="products (empty = the body)" :disabled="!editable" /></label>
              <label><span class="label">What it returns</span><input v-model="endpoint.description" class="input" placeholder="Search the catalogue" :disabled="!editable" /></label>
            </div>

            <div class="grid gap-4 lg:grid-cols-2">
              <div>
                <div class="mb-1 flex items-center justify-between">
                  <span class="label mb-0">Parameters</span>
                  <button v-if="editable" type="button" class="btn-ghost btn-sm" @click="endpoint.params.push({ name: '', type: 'string', required: false, test: '' })">+ Parameter</button>
                </div>
                <p v-if="!endpoint.params.length" class="text-xs text-subtle">None. Use <span class="code">{id}</span> in the path for a value taken from the question.</p>
                <div v-for="(param, n) in endpoint.params" :key="n" class="mb-2 grid grid-cols-[1fr_6.5rem_auto_1fr_auto] items-center gap-2">
                  <input v-model="param.name" class="input font-mono" placeholder="q" :disabled="!editable" aria-label="Parameter name" />
                  <select v-model="param.type" class="input" :disabled="!editable" aria-label="Parameter type"><option v-for="t in FIELD_TYPES" :key="t">{{ t }}</option></select>
                  <label class="flex items-center gap-1 text-xs"><input v-model="param.required" type="checkbox" :disabled="!editable" /> required</label>
                  <input v-model="param.test" class="input" placeholder="test value" aria-label="Test value (not saved)" />
                  <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove parameter" @click="endpoint.params.splice(n, 1)">✕</button>
                </div>
              </div>
              <div>
                <div class="mb-1 flex items-center justify-between">
                  <span class="label mb-0">Headers</span>
                  <button v-if="editable" type="button" class="btn-ghost btn-sm" @click="endpoint.headers.push({ name: '', value: '' })">+ Header</button>
                </div>
                <p v-if="!endpoint.headers.length" class="text-xs text-subtle">None. Fixed, non-secret headers only; the API key belongs to the connection.</p>
                <div v-for="(header, n) in endpoint.headers" :key="n" class="mb-2 grid grid-cols-[1fr_1fr_auto] items-center gap-2">
                  <input v-model="header.name" class="input font-mono" placeholder="Accept-Language" :disabled="!editable" aria-label="Header name" />
                  <input v-model="header.value" class="input font-mono" placeholder="id" :disabled="!editable" aria-label="Header value" />
                  <button v-if="editable" type="button" class="btn-ghost btn-sm text-bad" aria-label="Remove header" @click="endpoint.headers.splice(n, 1)">✕</button>
                </div>
              </div>
            </div>

            <div v-if="results[slot(resource, endpoint)] && !results[slot(resource, endpoint)].busy" class="space-y-2 rounded-lg bg-muted/60 p-3 text-sm">
              <p v-if="results[slot(resource, endpoint)].error" class="text-bad">{{ results[slot(resource, endpoint)].error }}</p>
              <template v-else>
                <p>
                  <span class="font-mono font-semibold" :class="statusTone(results[slot(resource, endpoint)].status)">{{ results[slot(resource, endpoint)].status }}</span>
                  <span class="text-subtle"> · {{ results[slot(resource, endpoint)].elapsed_ms }} ms</span>
                  <span v-if="results[slot(resource, endpoint)].user_rejected" class="text-subtle">
                    · this user's sign-in was refused.
                    <button v-if="editable" type="button" class="font-medium underline" @click="emit('signIn')">Sign in again</button>
                  </span>
                  <span v-else-if="results[slot(resource, endpoint)].needs_user_sign_in || ([401, 403].includes(results[slot(resource, endpoint)].status) && !linkId)" class="text-subtle">
                    · this API wants a signed-in user.
                    <button v-if="editable" type="button" class="font-medium underline" @click="emit('signIn')">Sign in as user</button>
                  </span>
                  <span v-else-if="!results[slot(resource, endpoint)].json" class="text-subtle"> · the answer is not JSON</span>
                </p>
                <template v-if="results[slot(resource, endpoint)].fields">
                  <p class="text-xs text-subtle">
                    Records at <span class="code">{{ results[slot(resource, endpoint)].result_path || "(the body)" }}</span>,
                    {{ results[slot(resource, endpoint)].count }} found.
                    Fields: <span class="font-mono">{{ Object.entries(results[slot(resource, endpoint)].fields ?? {}).map(([k, v]) => `${k}: ${v}`).join(", ") }}</span>
                  </p>
                  <p v-if="results[slot(resource, endpoint)].sensitive?.length" class="text-xs text-warn">
                    Blocked from AI as sensitive: {{ results[slot(resource, endpoint)].sensitive?.join(", ") }}</p>
                  <pre class="max-h-40 overflow-auto rounded bg-surface p-2 font-mono text-xs">{{ JSON.stringify(results[slot(resource, endpoint)].sample, null, 2) }}</pre>
                  <button v-if="editable" type="button" class="btn-secondary btn-sm" @click="useDetected(resource, endpoint)">Use this result path and these fields</button>
                </template>
              </template>
            </div>
          </article>
        </div>
      </div>
    </section>

    <button v-if="editable" type="button" class="btn-secondary" @click="addResource">+ Resource</button>
  </div>
</template>
