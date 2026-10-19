<script setup lang="ts">
// Inputs generated from a tool's JSON Schema. Scalars get proper controls;
// lists and objects (for example report filters) use a small JSON field.
import { computed, reactive, watch } from "vue";

import type { JsonSchema } from "@/services/hub";

const props = defineProps<{ schema: JsonSchema; modelValue: Record<string, unknown> }>();
const emit = defineEmits<{ "update:modelValue": [value: Record<string, unknown>] }>();

const properties = computed(() => Object.entries(props.schema.properties ?? {}));
const required = computed(() => new Set(props.schema.required ?? []));
const drafts = reactive<Record<string, string>>({});
const errors = reactive<Record<string, string>>({});

function kind(spec: JsonSchema): string {
  const type = Array.isArray(spec.type) ? spec.type.find((item) => item !== "null") : spec.type;
  if (spec.enum) return "enum";
  if (type === "integer" || type === "number") return "number";
  if (type === "boolean") return "boolean";
  if (type === "string") return "string";
  return "json";
}

watch(() => props.schema, () => {
  for (const [name, spec] of properties.value) {
    const current = props.modelValue[name];
    drafts[name] = current === undefined ? "" : kind(spec) === "json" ? JSON.stringify(current) : String(current);
  }
}, { immediate: true });

function update(name: string, spec: JsonSchema, raw: string | boolean) {
  const next = { ...props.modelValue };
  delete errors[name];
  if (typeof raw === "boolean") {
    next[name] = raw;
  } else {
    drafts[name] = raw;
    if (raw.trim() === "") {
      delete next[name];
    } else if (kind(spec) === "number") {
      const value = Number(raw);
      if (Number.isNaN(value)) errors[name] = "Enter a number";
      else next[name] = value;
    } else if (kind(spec) === "json") {
      try { next[name] = JSON.parse(raw); } catch { errors[name] = "Enter valid JSON"; }
    } else {
      next[name] = raw;
    }
  }
  emit("update:modelValue", next);
}

function hint(spec: JsonSchema): string {
  const parts = [];
  if (spec.minimum !== undefined || spec.maximum !== undefined) parts.push(`${spec.minimum ?? "…"}–${spec.maximum ?? "…"}`);
  if (spec.maxLength) parts.push(`max ${spec.maxLength} chars`);
  return [spec.description, parts.join(", ")].filter(Boolean).join(" · ");
}
</script>

<template>
  <div v-if="properties.length" class="grid gap-3 sm:grid-cols-2">
    <label v-for="[name, spec] in properties" :key="name" :class="kind(spec) === 'json' ? 'sm:col-span-2' : ''">
      <span class="label">{{ name }}<span v-if="required.has(name)" class="text-bad"> *</span></span>
      <select v-if="kind(spec) === 'enum'" class="input" :value="drafts[name]" @change="update(name, spec, ($event.target as HTMLSelectElement).value)">
        <option value="">(any)</option>
        <option v-for="option in spec.enum" :key="option" :value="option">{{ option }}</option>
      </select>
      <span v-else-if="kind(spec) === 'boolean'" class="flex items-center gap-2 py-2">
        <input type="checkbox" :checked="modelValue[name] === true" @change="update(name, spec, ($event.target as HTMLInputElement).checked)" />
        <span class="text-subtle">true</span>
      </span>
      <textarea v-else-if="kind(spec) === 'json'" class="input font-mono text-xs" rows="3" :value="drafts[name]" placeholder='[{"field": "status", "op": "eq", "value": "active"}]'
                @input="update(name, spec, ($event.target as HTMLTextAreaElement).value)" />
      <input v-else class="input" :type="kind(spec) === 'number' ? 'number' : 'text'" :value="drafts[name]"
             @input="update(name, spec, ($event.target as HTMLInputElement).value)" />
      <span v-if="errors[name]" class="hint text-bad">{{ errors[name] }}</span>
      <span v-else-if="hint(spec)" class="hint">{{ hint(spec) }}</span>
    </label>
  </div>
  <p v-else class="text-sm text-subtle">This tool takes no arguments.</p>
</template>
