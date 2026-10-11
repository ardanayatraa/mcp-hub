<script setup lang="ts">
// Choose which source parameters the AI may use, describe them, and tighten their limits.
// The source route is the upper bound: parameters can be hidden or narrowed, never widened.
import { computed, reactive, watch } from "vue";

import type { JsonSchema } from "@/services/hub";

const props = defineProps<{ route: JsonSchema; modelValue: JsonSchema | null }>();
const emit = defineEmits<{ "update:modelValue": [value: JsonSchema] }>();

interface Row {
  name: string;
  spec: JsonSchema;
  expose: boolean;
  forced: boolean;
  required: boolean;
  description: string;
  values: string[];
  minimum: number | "";
  maximum: number | "";
}

const rows = reactive<Row[]>([]);
const routeRequired = computed(() => new Set(props.route.required ?? []));

watch(() => props.route, () => {
  const current = props.modelValue?.properties;
  const required = new Set(props.modelValue?.required ?? []);
  rows.splice(0, rows.length, ...Object.entries(props.route.properties ?? {}).map(([name, spec]) => {
    const chosen = current?.[name];
    return {
      name, spec,
      expose: current ? Boolean(chosen) : true,
      forced: routeRequired.value.has(name),
      required: routeRequired.value.has(name) || required.has(name),
      description: chosen?.description ?? spec.description ?? "",
      values: chosen?.enum ?? spec.enum ?? [],
      minimum: (chosen?.minimum ?? spec.minimum ?? "") as number | "",
      maximum: (chosen?.maximum ?? spec.maximum ?? "") as number | "",
    };
  }));
}, { immediate: true });

function clamp(value: number | "", low?: number, high?: number): number | undefined {
  if (value === "" || Number.isNaN(Number(value))) return undefined;
  let number = Math.round(Number(value));
  if (low !== undefined) number = Math.max(number, low);
  if (high !== undefined) number = Math.min(number, high);
  return number;
}

watch(rows, () => {
  const properties: Record<string, JsonSchema> = {};
  const required: string[] = [];
  for (const row of rows) {
    if (!row.expose && !row.forced) continue;
    const spec: JsonSchema = { ...row.spec };
    if (row.description.trim()) spec.description = row.description.trim().slice(0, 300);
    if (row.spec.enum) spec.enum = row.spec.enum.filter((value) => row.values.includes(value));
    if (row.spec.type === "integer" || row.spec.type === "number") {
      const minimum = clamp(row.minimum, row.spec.minimum, row.spec.maximum);
      const maximum = clamp(row.maximum, row.spec.minimum, row.spec.maximum);
      if (minimum !== undefined) spec.minimum = minimum;
      if (maximum !== undefined) spec.maximum = maximum;
    }
    properties[row.name] = spec;
    if (row.required || row.forced) required.push(row.name);
  }
  emit("update:modelValue", { type: "object", additionalProperties: false, properties, ...(required.length ? { required } : {}) });
}, { deep: true, immediate: true });

function toggleValue(row: Row, value: string) {
  row.values = row.values.includes(value) ? row.values.filter((item) => item !== value) : [...row.values, value];
}
</script>

<template>
  <div v-if="rows.length" class="divide-y divide-line rounded-lg border border-line">
    <div v-for="row in rows" :key="row.name" class="space-y-2 p-3" :class="!row.expose && !row.forced ? 'opacity-60' : ''">
      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 font-mono text-sm">
          <input v-model="row.expose" type="checkbox" :disabled="row.forced" /> {{ row.name }}
        </label>
        <span class="badge-neutral">{{ row.spec.type }}</span>
        <span v-if="row.forced" class="badge-brand">required by the app</span>
        <label v-else-if="row.expose" class="flex items-center gap-1.5 text-xs text-subtle">
          <input v-model="row.required" type="checkbox" /> required
        </label>
      </div>
      <template v-if="row.expose || row.forced">
        <input v-model="row.description" class="input" placeholder="Describe this parameter for the AI (optional)" />
        <div v-if="row.spec.enum" class="flex flex-wrap gap-1.5">
          <span class="text-xs text-subtle">Allowed values:</span>
          <button v-for="value in row.spec.enum" :key="value" type="button" class="badge border"
                  :class="row.values.includes(value) ? 'border-brand bg-brand-soft text-brand' : 'border-line text-subtle line-through'"
                  @click="toggleValue(row, value)">{{ value }}</button>
        </div>
        <div v-if="row.spec.type === 'integer' || row.spec.type === 'number'" class="grid max-w-xs grid-cols-2 gap-2">
          <label><span class="label">Min</span><input v-model.number="row.minimum" class="input" type="number" :min="row.spec.minimum" :max="row.spec.maximum" /></label>
          <label><span class="label">Max</span><input v-model.number="row.maximum" class="input" type="number" :min="row.spec.minimum" :max="row.spec.maximum" /></label>
        </div>
      </template>
    </div>
  </div>
  <p v-else class="text-sm text-subtle">This endpoint takes no parameters.</p>
</template>
