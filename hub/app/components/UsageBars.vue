<script setup lang="ts">
import { computed } from "vue";

// A tiny daily bar chart: successful calls in brand, unsuccessful ones stacked on top in red.
const props = defineProps<{ series: { day: string; calls: number; failed: number }[] }>();
const max = computed(() => Math.max(1, ...props.series.map((point) => point.calls)));
const days = computed(() => props.series.map((point) => ({
  ...point,
  ok: ((point.calls - point.failed) / max.value) * 100,
  bad: (point.failed / max.value) * 100,
  label: new Date(`${point.day}T00:00:00`).toLocaleDateString(undefined, { weekday: "short" }),
})));
</script>

<template>
  <div class="flex h-12 items-end gap-1" role="img"
       :aria-label="`Calls per day: ${days.map((point) => `${point.label} ${point.calls}`).join(', ')}`">
    <div v-for="point in days" :key="point.day" class="flex h-full flex-1 flex-col justify-end gap-px"
         :title="`${point.label}: ${point.calls} calls${point.failed ? `, ${point.failed} unsuccessful` : ''}`">
      <span v-if="point.bad" class="block rounded-t-sm bg-bad" :style="{ height: `${point.bad}%` }" />
      <span class="block bg-chart-1" :class="point.bad ? '' : 'rounded-t-sm'" :style="{ height: `${Math.max(point.ok, point.calls ? 0 : 4)}%`, opacity: point.calls ? 1 : 0.25 }" />
    </div>
  </div>
</template>
