<script setup lang="ts">
import { computed } from "vue";

// "Showing 11–20 of 57", a page size choice and page buttons with gaps for long lists.
const props = withDefaults(defineProps<{ total: number; sizes?: number[]; label?: string }>(), { sizes: () => [10, 25, 50, 100], label: "items" });
const page = defineModel<number>("page", { required: true });
const size = defineModel<number>("size", { required: true });
const pages = computed(() => Math.max(1, Math.ceil(props.total / size.value)));
const first = computed(() => (props.total ? (page.value - 1) * size.value + 1 : 0));
const last = computed(() => Math.min(props.total, page.value * size.value));
const numbers = computed(() => {
  const count = pages.value;
  const shown = new Set([1, count, page.value - 1, page.value, page.value + 1].filter((n) => n >= 1 && n <= count));
  const sorted = [...shown].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((n, index) => {
    if (index && n - sorted[index - 1] > 1) out.push("gap");
    out.push(n);
  });
  return out;
});

function go(target: number) {
  page.value = Math.min(pages.value, Math.max(1, target));
}

function resize(value: number) {
  size.value = value;
  page.value = 1;
}
</script>

<template>
  <nav class="flex flex-wrap items-center justify-between gap-3 text-sm" :aria-label="`Pages of ${label}`">
    <p class="text-xs text-subtle">
      <template v-if="total">Showing <span class="font-medium text-ink tabular-nums">{{ first }}–{{ last }}</span> of
        <span class="font-medium text-ink tabular-nums">{{ total }}</span> {{ label }}</template>
      <template v-else>No {{ label }}</template>
    </p>
    <div class="flex flex-wrap items-center gap-3">
      <label class="flex items-center gap-2 text-xs text-subtle">Rows per page
        <select class="input h-8 w-20 py-0 text-xs" :value="size" aria-label="Rows per page"
                @change="resize(Number(($event.target as HTMLSelectElement).value))">
          <option v-for="option in sizes" :key="option" :value="option">{{ option }}</option>
        </select></label>
      <div class="flex items-center gap-1">
        <button type="button" class="btn-ghost btn-icon h-8 w-8" :disabled="page <= 1" aria-label="Previous page" @click="go(page - 1)">
          <AppIcon name="chevron-left" :size="16" /></button>
        <template v-for="(item, index) in numbers" :key="index">
          <span v-if="item === 'gap'" class="px-1 text-subtle" aria-hidden="true">…</span>
          <button v-else type="button" class="h-8 min-w-8 rounded-md px-2 text-xs font-medium tabular-nums transition"
                  :class="item === page ? 'bg-brand text-brand-ink' : 'text-subtle hover:bg-muted hover:text-ink'"
                  :aria-current="item === page ? 'page' : undefined" :aria-label="`Page ${item}`" @click="go(item)">{{ item }}</button>
        </template>
        <button type="button" class="btn-ghost btn-icon h-8 w-8" :disabled="page >= pages" aria-label="Next page" @click="go(page + 1)">
          <AppIcon name="chevron-right" :size="16" /></button>
      </div>
    </div>
  </nav>
</template>
