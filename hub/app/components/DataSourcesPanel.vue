<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "#imports";

import EmptyState from "@/components/EmptyState.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { hub, type DataSource } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { classification, errorMessage, timeAgo } from "@/utils/format";
import { endpointLabel } from "@/utils/sources";

// A list beside a detail panel, so apps with a hundred data sources stay easy to scan and edit.
const props = defineProps<{ sources: DataSource[]; appName: string; editable: boolean; managed: boolean }>();
const emit = defineEmits<{ updated: [DataSource] }>();
const route = useRoute();
const router = useRouter();
const toast = useToast();

type Draft = { operations: string[]; fields: Record<string, string>; report_endpoint: string };
type Filter = "all" | "on" | "off" | "write" | "changed";

const RANK: Record<string, number> = { blocked: 0, secure_form_only: 0, aggregate_only: 1, allowed_for_ai: 2, allowed: 2 };
const CHOICES = [["allowed_for_ai", "Visible to AI"], ["aggregate_only", "Totals only"], ["blocked", "Hidden"]] as const;
const OPS = ["read", "create", "update", "delete"];
const FIELD_FILTERS = [["all", "All"], ["visible", "Visible"], ["aggregate", "Totals only"], ["hidden", "Hidden"]] as const;

const drafts = reactive<Record<string, Draft>>({});
const search = ref("");
const filter = ref<Filter>("all");
const selectedId = ref("");
const checked = ref<Set<string>>(new Set());
const fieldSearch = ref("");
const fieldFilter = ref<(typeof FIELD_FILTERS)[number][0]>("all");
const showDetailOnMobile = ref(false);
const busy = ref<{ label: string; done: number; total: number } | null>(null);

function freshDraft(source: DataSource): Draft {
  return {
    operations: source.enabled ? [...source.operations_enabled] : [],
    fields: Object.fromEntries(source.fields.map((field) => [field.field_path, field.classification])),
    report_endpoint: source.report_endpoint ?? "",
  };
}

function dirty(source: DataSource): boolean {
  const draft = drafts[source.id];
  if (!draft) return false;
  const operations = source.enabled ? source.operations_enabled : [];
  return draft.operations.slice().sort().join() !== operations.slice().sort().join()
    || source.fields.some((field) => draft.fields[field.field_path] !== field.classification)
    || draft.report_endpoint !== (source.report_endpoint ?? "");
}

// Number-aware, so "Branch 2" sorts before "Branch 10".
const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
const sorted = computed(() => [...props.sources].sort((a, b) => natural(a.name, b.name)));

// A refreshed list keeps unsaved edits; everything else follows the server.
watch(() => props.sources, (list) => {
  for (const source of list) {
    if (!drafts[source.id] || !dirty(source)) drafts[source.id] = freshDraft(source);
  }
  const wanted = String(route.query.source ?? "");
  const match = list.find((source) => source.module_key === wanted) ?? list.find((source) => source.id === selectedId.value);
  selectedId.value = (match ?? sorted.value[0])?.id ?? "";
  checked.value = new Set([...checked.value].filter((id) => list.some((source) => source.id === id)));
}, { immediate: true });

const writeOps = (source: DataSource) => (drafts[source.id]?.operations ?? []).filter((op) => op !== "read");
const isOn = (source: DataSource) => (drafts[source.id]?.operations.length ?? 0) > 0;
const matchers: Record<Filter, (source: DataSource) => boolean> = {
  all: () => true, on: isOn, off: (source) => !isOn(source), write: (source) => writeOps(source).length > 0, changed: dirty,
};
const counts = computed(() => Object.fromEntries((Object.keys(matchers) as Filter[])
  .map((key) => [key, props.sources.filter(matchers[key]).length])) as Record<Filter, number>);
const visible = computed(() => {
  const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
  return sorted.value.filter((source) => matchers[filter.value](source) && words.every((word) =>
    `${source.name} ${source.module_key} ${source.description} ${source.fields.map((field) => field.field_path).join(" ")}`
      .toLowerCase().includes(word)));
});
const selected = computed(() => props.sources.find((source) => source.id === selectedId.value) ?? null);
const allChecked = computed(() => visible.value.length > 0 && visible.value.every((source) => checked.value.has(source.id)));
const changed = computed(() => props.sources.filter(dirty));

// A link that names a source opens with that row in view.
onMounted(async () => {
  await nextTick();
  document.querySelector('[aria-label="Data sources"] [aria-current="true"]')?.scrollIntoView({ block: "nearest" });
});

function select(source: DataSource) {
  selectedId.value = source.id;
  fieldSearch.value = "";
  fieldFilter.value = "all";
  showDetailOnMobile.value = true;
  void router.replace({ query: { ...route.query, source: source.module_key } });
}

function toggleChecked(id: string, on: boolean) {
  const next = new Set(checked.value);
  if (on) next.add(id); else next.delete(id);
  checked.value = next;
}

function toggleAll(on: boolean) {
  checked.value = on ? new Set([...checked.value, ...visible.value.map((source) => source.id)]) : new Set();
}

function toggleOperation(source: DataSource, operation: string, on: boolean) {
  const draft = drafts[source.id];
  draft.operations = on ? [...new Set([...draft.operations, operation, ...(operation !== "read" ? ["read"] : [])])]
    : draft.operations.filter((item) => item !== operation && (operation !== "read"));
}

function summary(source: DataSource) {
  const fields = Object.values(drafts[source.id]?.fields ?? {});
  return {
    visible: fields.filter((value) => RANK[value] === 2).length,
    totals: fields.filter((value) => value === "aggregate_only").length,
    hidden: fields.filter((value) => RANK[value] === 0).length,
  };
}

const fieldRows = computed(() => {
  const source = selected.value;
  if (!source) return [];
  const word = fieldSearch.value.toLowerCase().trim();
  return [...source.fields].sort((a, b) => natural(a.field_path, b.field_path)).filter((field) => {
    const value = drafts[source.id]?.fields[field.field_path] ?? field.classification;
    const bucket = RANK[value] === 2 ? "visible" : value === "aggregate_only" ? "aggregate" : "hidden";
    return (fieldFilter.value === "all" || fieldFilter.value === bucket) && (!word || field.field_path.toLowerCase().includes(word));
  });
});

function payload(source: DataSource, draft: Draft) {
  const fields = source.fields.filter((field) => draft.fields[field.field_path] !== field.classification)
    .map((field) => ({ field_path: field.field_path, classification: draft.fields[field.field_path] }));
  return { enabled: draft.operations.length > 0, operations: draft.operations, fields, report_endpoint: draft.report_endpoint || null };
}

// One request per data source, in order; a failure stops the run and keeps the rest as they were.
async function run(label: string, items: { source: DataSource; draft: Draft }[]) {
  if (!items.length) return;
  busy.value = { label, done: 0, total: items.length };
  try {
    for (const { source, draft } of items) {
      const updated = await hub.updateSource(source.id, payload(source, draft));
      drafts[source.id] = freshDraft(updated);
      emit("updated", updated);
      if (busy.value) busy.value.done += 1;
    }
    toast.ok(items.length === 1 ? `${items[0].source.name} saved` : `${items.length} data sources saved`);
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = null;
  }
}

function save(source: DataSource) {
  return run("Saving", [{ source, draft: drafts[source.id] }]);
}

function saveAll() {
  return run("Saving changes", changed.value.map((source) => ({ source, draft: drafts[source.id] })));
}

async function bulk(action: "read" | "off") {
  const targets = sorted.value.filter((source) => checked.value.has(source.id));
  const items = targets.flatMap((source) => {
    const draft = { ...drafts[source.id] };
    if (action === "read") {
      if (!source.enableable_operations.includes("read") || draft.operations.includes("read")) return [];
      draft.operations = [...draft.operations, "read"];
    } else {
      if (!draft.operations.length) return [];
      draft.operations = [];
    }
    return [{ source, draft }];
  });
  if (!items.length) {
    toast.ok(action === "read" ? "The selected data sources are already readable" : "The selected data sources are already off");
    return;
  }
  await run(action === "read" ? "Allowing reading" : "Turning off", items);
  checked.value = new Set();
}

function discard(source: DataSource) {
  drafts[source.id] = freshDraft(source);
}
</script>

<template>
  <EmptyState v-if="!sources.length" icon="database" :title="managed ? 'No models allowed' : 'No data sources yet'"
              :text="managed ? 'Allow a model in the application to make its tools available.' : 'Sync the contract to discover what this app publishes.'" />

  <div v-else class="grid gap-5 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
    <!-- List -->
    <section class="card flex min-w-0 flex-col self-start lg:sticky lg:top-0 lg:max-h-[calc(100dvh-9rem)]" :class="showDetailOnMobile ? 'hidden lg:flex' : 'flex'"
             aria-label="Data sources">
      <div class="space-y-3 border-b border-line p-3">
        <div class="relative">
          <AppIcon name="search" :size="14" class="pointer-events-none absolute left-2.5 top-2.5 text-subtle" />
          <input v-model="search" class="input pl-8" placeholder="Search name, key or field" aria-label="Search data sources" />
        </div>
        <div class="flex flex-wrap gap-1" role="group" aria-label="Filter">
          <button v-for="[key, label] in ([['all', 'All'], ['on', 'Allowed'], ['off', 'Off'], ['write', 'Write'], ['changed', 'Unsaved']] as const)"
                  :key="key" type="button" class="rounded-md px-2 py-1 text-xs font-medium transition"
                  :class="filter === key ? 'bg-brand text-brand-ink' : 'bg-muted text-subtle hover:text-ink'"
                  :aria-pressed="filter === key" @click="filter = key">
            {{ label }} <span class="tabular-nums opacity-70">{{ counts[key] }}</span>
          </button>
        </div>
        <div v-if="editable && !managed" class="flex items-center gap-2 text-xs">
          <label class="flex items-center gap-2 text-subtle"><input type="checkbox" :checked="allChecked" :disabled="!visible.length"
                 @change="toggleAll(($event.target as HTMLInputElement).checked)" /> Select shown</label>
          <span v-if="checked.size" class="ml-auto flex gap-1">
            <button type="button" class="btn-secondary btn-sm h-7 px-2" :disabled="!!busy" @click="bulk('read')">Allow read ({{ checked.size }})</button>
            <button type="button" class="btn-ghost btn-sm h-7 px-2" :disabled="!!busy" @click="bulk('off')">Turn off</button>
          </span>
        </div>
      </div>

      <ul class="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        <li v-for="source in visible" :key="source.id" class="flex items-start gap-2 px-3 py-2.5 transition-colors"
            :class="source.id === selectedId ? 'bg-muted' : 'hover:bg-muted/50'">
          <input v-if="editable && !managed" type="checkbox" class="mt-1" :checked="checked.has(source.id)" :aria-label="`Select ${source.name}`"
                 @change="toggleChecked(source.id, ($event.target as HTMLInputElement).checked)" />
          <button type="button" class="min-w-0 flex-1 text-left" :aria-current="source.id === selectedId ? 'true' : undefined" @click="select(source)">
            <span class="flex items-center gap-2">
              <span class="h-2 w-2 shrink-0 rounded-full" :class="isOn(source) ? 'bg-ok' : 'bg-line'" :title="isOn(source) ? 'Allowed' : 'Off'" />
              <span class="truncate text-sm font-medium">{{ source.name }}</span>
              <span v-if="dirty(source)" class="badge-warn ml-auto shrink-0 px-1.5 py-0 text-[11px]">unsaved</span>
              <span v-else-if="writeOps(source).length" class="badge-neutral ml-auto shrink-0 px-1.5 py-0 text-[11px]">+{{ writeOps(source).join(", ") }}</span>
            </span>
            <span class="mt-0.5 block truncate pl-4 text-xs text-subtle">
              <span class="font-mono">{{ source.module_key }}</span> · {{ plural(source.fields.length, "field") }} · {{ plural(source.endpoints.length, "route") }}
            </span>
          </button>
        </li>
        <li v-if="!visible.length" class="px-3 py-8 text-center text-sm text-subtle">No data sources match.</li>
      </ul>

      <footer v-if="busy || changed.length > 1" class="flex items-center gap-2 border-t border-line px-3 py-2 text-xs">
        <template v-if="busy"><span class="spinner h-3.5 w-3.5 text-brand" /> {{ busy.label }} {{ busy.done }} of {{ busy.total }}…</template>
        <template v-else>
          <span class="text-warn">{{ changed.length }} unsaved</span>
          <button type="button" class="btn-primary btn-sm ml-auto h-7" @click="saveAll">Save all</button>
        </template>
      </footer>
    </section>

    <!-- Detail -->
    <section v-if="selected" class="card min-w-0" :class="showDetailOnMobile ? '' : 'hidden lg:block'" :aria-label="selected.name">
      <header class="flex flex-wrap items-start justify-between gap-3 border-b border-line p-5">
        <div class="min-w-0">
          <button type="button" class="btn-ghost btn-sm -ml-3 mb-1 lg:hidden" @click="showDetailOnMobile = false">
            <AppIcon name="chevron-left" :size="14" /> All data sources</button>
          <h3 class="text-lg font-semibold">{{ selected.name }} <span class="font-mono text-xs font-normal text-subtle">{{ selected.module_key }}</span></h3>
          <p class="text-xs text-subtle">{{ selected.description || "No description" }} · synced {{ timeAgo(selected.last_synced_at) }}</p>
        </div>
        <span :class="isOn(selected) ? 'badge-ok' : 'badge-neutral'">{{ isOn(selected) ? "Allowed" : "Off" }}</span>
      </header>

      <div class="border-b border-line p-5">
        <p class="mb-3 text-xs font-medium text-subtle">What AI clients may do</p>
        <div class="flex flex-wrap gap-x-6 gap-y-3">
          <label v-for="operation in OPS.filter((op) => selected!.supported_operations.includes(op))" :key="operation" class="flex items-center gap-2 text-sm"
                 :title="selected.enableable_operations.includes(operation) ? '' : 'The app has not published a reviewed route for this operation'">
            <ToggleSwitch :model-value="drafts[selected.id]?.operations.includes(operation) ?? false" :label="`${operation} ${selected.name}`"
                          :disabled="managed || !editable || !selected.enableable_operations.includes(operation)"
                          @update:model-value="(on: boolean) => toggleOperation(selected!, operation, on)" />
            <span :class="operation === 'read' ? '' : 'text-warn'">{{ operation.charAt(0).toUpperCase() + operation.slice(1) }}</span>
          </label>
        </div>
        <p v-if="writeOps(selected).length" class="mt-3 text-xs text-warn">Write operations work only through published write tools and client keys with write permission.</p>
        <p v-if="managed" class="mt-3 text-xs text-subtle">Managed by {{ appName }}: change models, fields and operations in the application.</p>
      </div>

      <div class="border-b border-line p-5">
        <div class="mb-3 flex flex-wrap items-center gap-2">
          <p class="mr-auto text-xs font-medium text-subtle">Field visibility
            <span class="font-normal">· {{ summary(selected).visible }} visible, {{ summary(selected).totals }} totals only, {{ summary(selected).hidden }} hidden</span></p>
          <template v-if="selected.fields.length > 8">
            <input v-model="fieldSearch" class="input h-8 w-40 text-xs" placeholder="Find a field" aria-label="Find a field" />
            <select v-model="fieldFilter" class="input h-8 w-32 text-xs" aria-label="Show fields">
              <option v-for="[value, label] in FIELD_FILTERS" :key="value" :value="value">{{ label }}</option>
            </select>
          </template>
        </div>
        <div class="max-h-[26rem] overflow-auto rounded-lg border border-line">
          <table class="tbl [&_td]:py-1.5">
            <thead class="sticky top-0 z-[1] bg-surface"><tr><th>Field</th><th class="hidden sm:table-cell">Type</th><th>AI may see</th></tr></thead>
            <tbody>
              <tr v-for="field in fieldRows" :key="field.field_path">
                <td class="font-mono text-xs">{{ field.field_path }}</td>
                <td class="hidden text-xs text-subtle sm:table-cell">{{ field.type ?? "—" }}</td>
                <td>
                  <span v-if="field.locked || managed" class="flex items-center gap-1.5 text-xs text-subtle" title="Managed by the app or the Hub's privacy rules">
                    <AppIcon name="lock" :size="14" /> {{ classification[drafts[selected.id]?.fields[field.field_path] ?? field.classification]?.label ?? field.classification }}
                  </span>
                  <select v-else v-model="drafts[selected.id].fields[field.field_path]" class="input h-8 py-0 text-xs" :disabled="!editable"
                          :aria-label="`Visibility of ${field.field_path}`">
                    <option v-for="[value, label] in CHOICES" :key="value" :value="value" :disabled="RANK[value] > RANK[field.baseline]">{{ label }}</option>
                  </select>
                </td>
              </tr>
              <tr v-if="!fieldRows.length"><td colspan="3" class="py-6 text-center text-xs text-subtle">No fields match.</td></tr>
            </tbody>
          </table>
        </div>
        <p v-if="!managed" class="hint">"Totals only" fields can be summed or averaged over 3+ records but never shown. Options above the app's own limit are disabled.</p>
      </div>

      <div class="grid gap-5 p-5 md:grid-cols-2">
        <div class="min-w-0">
          <p class="mb-2 text-xs font-medium text-subtle">Published routes ({{ selected.endpoints.length }})</p>
          <ul class="max-h-48 space-y-1.5 overflow-y-auto">
            <li v-for="endpoint in selected.endpoints" :key="endpoint.key" class="flex items-center gap-2 text-xs">
              <span :class="endpoint.kind === 'write' ? 'badge-warn' : 'badge-neutral'">{{ endpoint.kind === "write" ? endpoint.operation : "read" }}</span>
              <span class="truncate font-mono" :title="endpointLabel(endpoint)">{{ endpointLabel(endpoint) }}</span>
              <AppIcon v-if="endpoint.requires_user_context" name="users" :size="14" class="shrink-0 text-subtle" />
            </li>
          </ul>
          <p class="hint flex items-center gap-1"><AppIcon name="users" :size="12" /> needs the signed-in user's context from the app</p>
        </div>
        <div class="min-w-0">
          <label v-if="selected.endpoints.filter((endpoint) => endpoint.dataset).length > 1" class="block">
            <span class="label">Reports read from</span>
            <select v-model="drafts[selected.id].report_endpoint" class="input text-xs" :disabled="managed || !editable">
              <option value="">Automatic ({{ selected.report_endpoint_auto }})</option>
              <option v-for="endpoint in selected.endpoints.filter((item) => item.dataset)" :key="endpoint.key" :value="endpoint.key">{{ endpoint.key }}</option>
            </select>
          </label>
          <p v-else-if="selected.report_endpoint_effective" class="text-xs text-subtle">Reports read from <span class="code">{{ selected.report_endpoint_effective }}</span></p>
          <p v-else class="text-xs text-subtle">This source has no list route, so run_report cannot use it.</p>
        </div>
      </div>

      <footer v-if="!managed && editable && dirty(selected)" class="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 rounded-b-xl border-t border-line bg-surface/95 px-5 py-3 backdrop-blur">
        <span class="mr-auto text-xs text-warn">Unsaved changes to {{ selected.name }}</span>
        <button class="btn-ghost" type="button" :disabled="!!busy" @click="discard(selected)">Discard</button>
        <button class="btn-primary" type="button" :disabled="!!busy" @click="save(selected)">
          <span v-if="busy" class="spinner" /> Save changes</button>
      </footer>
    </section>
  </div>
</template>
