<script setup lang="ts">
// Shows what an AI client receives: records as a table, reports as a summary,
// totals, a simple bar chart and the grouped rows. Raw JSON is one click away.
import { computed, ref } from "vue";

import { prettyJson } from "@/utils/format";

const props = defineProps<{ result: Record<string, any> }>();
const raw = ref(false);

const isReport = computed(() => typeof props.result.summary === "string" && props.result.data && !Array.isArray(props.result.data));
const rows = computed<Record<string, unknown>[]>(() =>
  isReport.value ? props.result.data.rows ?? [] : Array.isArray(props.result.data) ? props.result.data : []);
const columns = computed<string[]>(() => {
  if (isReport.value) return props.result.data.columns ?? [];
  const names = new Set<string>();
  rows.value.forEach((row) => Object.keys(row).forEach((key) => names.add(key)));
  return [...names];
});
const meta = computed(() => props.result.meta ?? {});
const chart = computed(() => {
  const hint = props.result.chart;
  if (!hint || !rows.value.length) return null;
  const metric = hint.y?.[0];
  const values = rows.value.map((row) => Number(row[metric] ?? 0)).filter((value) => Number.isFinite(value));
  const max = Math.max(...values, 0);
  if (!metric || max <= 0) return null;
  return { x: hint.x as string, metric, max, type: hint.type as string };
});

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  // Nested values (a source's fields, say) read as short text instead of "[object Object]".
  if (typeof value === "object") {
    const text = Array.isArray(value) ? value.map((item) => (typeof item === "object" && item !== null
      ? String((item as Record<string, unknown>).name ?? JSON.stringify(item)) : String(item))).join(", ") : JSON.stringify(value);
    return text.length > 160 ? `${text.slice(0, 160)}…` : text;
  }
  return String(value);
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <span v-if="meta.coverage" :class="meta.coverage === 'complete' ? 'badge-ok' : 'badge-warn'">Coverage: {{ meta.coverage }}</span>
      <span v-if="meta.records_read !== undefined" class="badge-neutral">{{ meta.records_read }} records read</span>
      <span v-if="meta.total_count !== undefined" class="badge-neutral">{{ meta.total_count }} total at source</span>
      <span v-if="meta.operation" class="badge-warn">{{ meta.operation }} request</span>
      <span v-if="meta.requires_confirmation" class="badge-brand">Needs user confirmation in the app</span>
      <span v-if="meta.as_of" class="badge-neutral">as of {{ new Date(meta.as_of).toLocaleString() }}</span>
      <button type="button" class="btn-ghost btn-sm ml-auto" @click="raw = !raw">{{ raw ? "Formatted view" : "Raw JSON" }}</button>
    </div>

    <pre v-if="raw" class="max-h-[28rem] overflow-auto rounded-lg border border-line bg-muted p-3 font-mono text-xs">{{ prettyJson(result) }}</pre>

    <template v-else>
      <p v-if="isReport" class="rounded-lg border border-brand/20 bg-brand-soft px-3 py-2.5 text-sm text-ink">{{ result.summary }}</p>

      <div v-if="isReport && result.data.totals && result.data.mode !== 'records'" class="flex flex-wrap gap-3">
        <div v-for="(value, key) in result.data.totals" :key="key" class="rounded-lg border border-line px-3 py-2">
          <p class="text-xs text-subtle">{{ key }}</p>
          <p class="font-mono text-lg">{{ cell(value) }}</p>
        </div>
      </div>

      <div v-if="chart" class="space-y-1.5 rounded-lg border border-line p-3">
        <p class="mb-2 text-xs text-subtle">{{ chart.metric }} by {{ chart.x }}</p>
        <div v-for="(row, index) in rows" :key="index" class="grid grid-cols-[minmax(5rem,10rem)_1fr_auto] items-center gap-2 text-xs">
          <span class="truncate text-subtle">{{ cell(row[chart.x]) }}</span>
          <span class="h-2.5 rounded-full bg-muted">
            <span class="block h-2.5 rounded-full bg-brand" :style="{ width: `${(Number(row[chart.metric] ?? 0) / chart.max) * 100}%` }" />
          </span>
          <span class="font-mono">{{ cell(row[chart.metric]) }}</span>
        </div>
      </div>

      <div v-if="rows.length" class="overflow-x-auto rounded-lg border border-line">
        <table class="tbl">
          <thead><tr><th v-for="column in columns" :key="column">{{ column }}</th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="index">
              <td v-for="column in columns" :key="column" class="font-mono text-xs">{{ cell(row[column]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="text-sm text-subtle">No records matched.</p>

      <ul v-if="result.notes?.length" class="list-disc space-y-1 pl-5 text-xs text-subtle">
        <li v-for="note in result.notes" :key="note">{{ note }}</li>
      </ul>
    </template>
  </div>
</template>
