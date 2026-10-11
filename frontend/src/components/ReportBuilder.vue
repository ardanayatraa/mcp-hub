<script setup lang="ts">
// Point-and-click report spec: groups, a time trend, metrics, filters, sort and columns.
// Field rules mirror the Hub: "totals only" fields can only be summed or averaged.
import { computed, reactive, watch } from "vue";

import type { ReportSpec } from "@/services/hub";
import type { ReportField } from "@/utils/sources";

const props = withDefaults(defineProps<{ fields: ReportField[]; modelValue: ReportSpec; saved?: boolean }>(), { saved: false });
const emit = defineEmits<{ "update:modelValue": [value: ReportSpec] }>();

const OPS = [
  ["eq", "equals"], ["ne", "is not"], ["in", "is one of"], ["contains", "contains"], ["gt", ">"], ["gte", "≥"],
  ["lt", "<"], ["lte", "≤"], ["between", "between"], ["is_null", "is empty"], ["not_null", "is not empty"],
] as const;
const FUNCTIONS = ["count", "sum", "avg", "min", "max"];

const visible = computed(() => props.fields.filter((field) => field.usage === "visible"));
const numeric = (field: ReportField) => field.type === "integer" || field.type === "number";

function text(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return value === undefined || value === null ? "" : String(value);
}

const initial = props.modelValue;
const state = reactive({
  group1: initial.group_by?.[0] ?? "",
  group2: initial.group_by?.[1] ?? "",
  trendField: initial.time_bucket?.field ?? "",
  trendInterval: initial.time_bucket?.interval ?? "month",
  metrics: (initial.metrics ?? []).map((metric) => ({ fn: metric.fn, field: metric.field ?? "" })),
  filters: (initial.filters ?? []).map((item) => ({ field: item.field, op: item.op, value: text(item.value) })),
  sortBy: initial.sort?.by ?? "",
  sortDir: initial.sort?.direction ?? "desc",
  limit: initial.limit ?? 50,
  columns: [...(initial.columns ?? [])],
  allowFilters: initial.allow_filters ?? true,
});

const grouped = computed(() => Boolean(state.group1 || state.trendField));
const metricOptions = (fn: string) => props.fields.filter((field) =>
  fn === "sum" || fn === "avg" ? numeric(field) || field.usage === "aggregate" : field.usage === "visible");
const aliases = computed(() => (state.metrics.length ? state.metrics : [{ fn: "count", field: "" }])
  .map((metric) => (metric.fn === "count" ? "count" : `${metric.fn}_${metric.field}`)));
const sortOptions = computed(() => grouped.value
  ? [...[state.group1, state.group2].filter(Boolean), ...(state.trendField ? ["period"] : []), ...aliases.value]
  : visible.value.map((field) => field.name));

function typed(fieldName: string, raw: string): unknown {
  const field = props.fields.find((item) => item.name === fieldName);
  const value = raw.trim();
  if (field && numeric(field) && value !== "" && !Number.isNaN(Number(value))) return Number(value);
  if (field?.type === "boolean") return value === "true";
  return value;
}

function build(): ReportSpec {
  const spec: ReportSpec = { limit: Number(state.limit) || 50 };
  const groups = [state.group1, state.group2].filter(Boolean);
  if (groups.length) spec.group_by = groups;
  if (state.trendField) spec.time_bucket = { field: state.trendField, interval: state.trendInterval };
  const metrics = state.metrics.filter((metric) => metric.fn === "count" || metric.field)
    .map((metric) => (metric.fn === "count" ? { fn: "count" } : { fn: metric.fn, field: metric.field }));
  if (metrics.length) spec.metrics = metrics;
  const filters = state.filters.filter((item) => item.field).map((item) => {
    if (item.op === "is_null" || item.op === "not_null") return { field: item.field, op: item.op };
    if (item.op === "in" || item.op === "between") {
      return { field: item.field, op: item.op, value: item.value.split(",").map((part) => typed(item.field, part)).filter((part) => part !== "") };
    }
    return { field: item.field, op: item.op, value: typed(item.field, item.value) };
  });
  if (filters.length) spec.filters = filters;
  if (state.sortBy && sortOptions.value.includes(state.sortBy)) spec.sort = { by: state.sortBy, direction: state.sortDir };
  if (!grouped.value && !spec.metrics && state.columns.length) spec.columns = [...state.columns];
  if (props.saved) spec.allow_filters = state.allowFilters;
  return spec;
}

watch(state, () => emit("update:modelValue", build()), { deep: true, immediate: true });

function toggleColumn(name: string) {
  state.columns = state.columns.includes(name) ? state.columns.filter((item) => item !== name) : [...state.columns, name];
}
</script>

<template>
  <div class="space-y-5">
    <div class="grid gap-3 sm:grid-cols-2">
      <label>
        <span class="label">Group by</span>
        <select v-model="state.group1" class="input">
          <option value="">(no grouping)</option>
          <option v-for="field in visible" :key="field.name" :value="field.name">{{ field.name }}</option>
        </select>
      </label>
      <label>
        <span class="label">Then by</span>
        <select v-model="state.group2" class="input" :disabled="!state.group1">
          <option value="">(none)</option>
          <option v-for="field in visible.filter((item) => item.name !== state.group1)" :key="field.name" :value="field.name">{{ field.name }}</option>
        </select>
      </label>
      <label class="sm:col-span-2">
        <span class="label">Trend over time</span>
        <span class="flex gap-2">
          <select v-model="state.trendField" class="input min-w-0 flex-1">
            <option value="">(none)</option>
            <option v-for="field in visible.filter((item) => item.type === 'string')" :key="field.name" :value="field.name">{{ field.name }}</option>
          </select>
          <select v-model="state.trendInterval" class="input w-28" :disabled="!state.trendField">
            <option v-for="interval in ['day', 'week', 'month', 'year']" :key="interval">{{ interval }}</option>
          </select>
        </span>
      </label>
    </div>

    <div>
      <div class="mb-2 flex items-center justify-between">
        <span class="label mb-0">Metrics <span class="font-normal text-subtle">(groups count records by default)</span></span>
        <button type="button" class="btn-ghost btn-sm" :disabled="state.metrics.length >= 6"
                @click="state.metrics.push({ fn: state.metrics.length ? 'sum' : 'count', field: '' })">
          <AppIcon name="plus" :size="14" /> Add metric
        </button>
      </div>
      <p v-if="!state.metrics.length" class="text-xs text-subtle">
        {{ grouped ? "Each group shows its number of records." : "No metrics: the report lists records." }}
      </p>
      <div class="space-y-2">
        <div v-for="(metric, index) in state.metrics" :key="index" class="flex gap-2">
          <select v-model="metric.fn" class="input w-32">
            <option v-for="fn in FUNCTIONS" :key="fn">{{ fn }}</option>
          </select>
          <select v-if="metric.fn !== 'count'" v-model="metric.field" class="input">
            <option value="" disabled>Choose a field</option>
            <option v-for="field in metricOptions(metric.fn)" :key="field.name" :value="field.name">
              {{ field.name }}{{ field.usage === "aggregate" ? " (totals only)" : "" }}
            </option>
          </select>
          <span v-else class="input flex items-center text-subtle">number of records</span>
          <button type="button" class="btn-ghost btn-sm" aria-label="Remove metric" @click="state.metrics.splice(index, 1)"><AppIcon name="x" :size="14" /></button>
        </div>
      </div>
    </div>

    <div>
      <div class="mb-2 flex items-center justify-between">
        <span class="label mb-0">Filters <span class="font-normal text-subtle">(records must match all)</span></span>
        <button type="button" class="btn-ghost btn-sm" :disabled="state.filters.length >= 10" @click="state.filters.push({ field: visible[0]?.name ?? '', op: 'eq', value: '' })">
          <AppIcon name="plus" :size="14" /> Add filter
        </button>
      </div>
      <p v-if="!state.filters.length" class="text-xs text-subtle">No filters: every authorized record is included.</p>
      <div class="space-y-2">
        <div v-for="(item, index) in state.filters" :key="index" class="grid grid-cols-[1fr_9rem_1fr_auto] gap-2">
          <select v-model="item.field" class="input">
            <option v-for="field in visible" :key="field.name" :value="field.name">{{ field.name }}</option>
          </select>
          <select v-model="item.op" class="input">
            <option v-for="[op, label] in OPS" :key="op" :value="op">{{ label }}</option>
          </select>
          <input v-if="item.op !== 'is_null' && item.op !== 'not_null'" v-model="item.value" class="input"
                 :list="`values-${index}`" :placeholder="item.op === 'in' || item.op === 'between' ? 'a, b' : 'value or 2026-10-01'" />
          <span v-else />
          <datalist :id="`values-${index}`">
            <option v-for="value in fields.find((field) => field.name === item.field)?.values ?? []" :key="value" :value="value" />
          </datalist>
          <button type="button" class="btn-ghost btn-sm" aria-label="Remove filter" @click="state.filters.splice(index, 1)"><AppIcon name="x" :size="14" /></button>
        </div>
      </div>
      <label v-if="saved" class="mt-3 flex items-center gap-2 text-sm">
        <input v-model="state.allowFilters" type="checkbox" /> Let the AI add its own filters when calling this report
      </label>
    </div>

    <div class="grid gap-3 sm:grid-cols-3">
      <label>
        <span class="label">Sort by</span>
        <select v-model="state.sortBy" class="input">
          <option value="">(default)</option>
          <option v-for="option in sortOptions" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label>
        <span class="label">Direction</span>
        <select v-model="state.sortDir" class="input"><option value="desc">Highest first</option><option value="asc">Lowest first</option></select>
      </label>
      <label>
        <span class="label">Max rows</span>
        <input v-model.number="state.limit" class="input" type="number" min="1" max="200" />
      </label>
    </div>

    <div v-if="!grouped && !state.metrics.length">
      <span class="label">Columns to show <span class="font-normal text-subtle">(record lists only; empty means all visible)</span></span>
      <div class="flex flex-wrap gap-2">
        <button v-for="field in visible" :key="field.name" type="button" class="badge border"
                :class="state.columns.includes(field.name) ? 'border-brand bg-brand-soft text-brand' : 'border-line bg-surface text-subtle'"
                @click="toggleColumn(field.name)">{{ field.name }}</button>
      </div>
    </div>
  </div>
</template>
