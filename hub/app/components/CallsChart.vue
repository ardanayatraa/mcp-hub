<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import type { CallPoint } from "@/services/hub";

// Tool calls over time: all calls as a washed area, unsuccessful calls as a dashed line (form, not only color, separates them).
const props = withDefaults(defineProps<{ points?: CallPoint[]; table?: boolean }>(), { points: () => [], table: false });

const HEIGHT = 240;
const M = { top: 12, right: 12, bottom: 28, left: 40 };
const root = ref<HTMLElement | null>(null);
const width = ref(640);
const hover = ref<number | null>(null);
let observer: ResizeObserver | undefined;

// The chart element comes and goes with the table view, so follow it rather than measuring once.
watch(root, (element) => {
  observer?.disconnect();
  if (!element) return;
  width.value = Math.max(280, element.clientWidth || 640);
  observer = new ResizeObserver(([entry]) => { width.value = Math.max(280, entry.contentRect.width); });
  observer.observe(element);
});
onBeforeUnmount(() => observer?.disconnect());

const n = computed(() => props.points.length);
const innerW = computed(() => width.value - M.left - M.right);
const innerH = HEIGHT - M.top - M.bottom;
const stepMs = computed(() => n.value > 1 ? Date.parse(props.points[1].start) - Date.parse(props.points[0].start) : 3_600_000);
const empty = computed(() => props.points.every((point) => point.calls === 0));

// Four clean intervals: 0 / 5 / 10 / 15 / 20, never a fractional call count.
const yMax = computed(() => {
  const peak = Math.max(0, ...props.points.map((point) => point.calls));
  const raw = Math.max(1, peak / 4);
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((factor) => factor * power).find((value) => value >= raw) ?? 10 * power;
  return Math.max(1, Math.ceil(step)) * 4;
});
const yTicks = computed(() => [0, 1, 2, 3, 4].map((index) => (yMax.value / 4) * index));

const x = (index: number) => M.left + (n.value <= 1 ? innerW.value / 2 : (index * innerW.value) / (n.value - 1));
const y = (value: number) => M.top + innerH - (value / yMax.value) * innerH;

function line(key: "calls" | "failed") {
  return props.points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point[key]).toFixed(1)}`).join("");
}
const callsLine = computed(() => line("calls"));
const failedLine = computed(() => line("failed"));
const callsArea = computed(() => n.value
  ? `${callsLine.value}L${x(n.value - 1).toFixed(1)},${y(0)}L${x(0).toFixed(1)},${y(0)}Z` : "");

const xTicks = computed(() => {
  const count = Math.min(n.value, Math.max(2, Math.floor(innerW.value / 96)));
  if (count <= 1) return n.value ? [0] : [];
  return [...new Set(Array.from({ length: count }, (_, index) => Math.round((index * (n.value - 1)) / (count - 1))))];
});

function compact(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K` : String(Math.round(value));
}

function axisLabel(iso: string) {
  const date = new Date(iso);
  return stepMs.value < 3 * 3_600_000
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function fullLabel(iso: string) {
  const date = new Date(iso);
  const day = date.toLocaleDateString([], { month: "short", day: "numeric" });
  return stepMs.value < 86_400_000 ? `${day}, ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : day;
}

function onPointer(event: PointerEvent) {
  if (!n.value) return;
  const box = (event.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
  if (!box) return;
  const ratio = n.value <= 1 ? 0 : (event.clientX - box.left - M.left) / (innerW.value / (n.value - 1));
  hover.value = Math.min(n.value - 1, Math.max(0, Math.round(ratio)));
}

function onKey(event: KeyboardEvent) {
  if (!n.value || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const current = hover.value ?? n.value - 1;
  hover.value = event.key === "Home" ? 0 : event.key === "End" ? n.value - 1
    : Math.min(n.value - 1, Math.max(0, current + (event.key === "ArrowRight" ? 1 : -1)));
}

const tip = computed(() => {
  if (hover.value === null || !props.points[hover.value]) return null;
  const left = x(hover.value);
  return { point: props.points[hover.value], left, flip: left > width.value - 180 };
});
const summary = computed(() => {
  const total = props.points.reduce((sum, point) => sum + point.calls, 0);
  const failed = props.points.reduce((sum, point) => sum + point.failed, 0);
  return `${total} tool calls, ${failed} unsuccessful, over ${n.value} intervals. Use the arrow keys to read each interval.`;
});
</script>

<template>
  <div v-if="table" class="max-h-72 overflow-auto rounded-lg border border-line">
    <table class="tbl">
      <thead class="sticky top-0 bg-surface"><tr><th>Interval starting</th><th class="text-right">Calls</th><th class="text-right">Unsuccessful</th></tr></thead>
      <tbody>
        <tr v-for="point in [...points].reverse()" :key="point.start">
          <td class="text-xs">{{ fullLabel(point.start) }}</td>
          <td class="text-right tabular-nums">{{ point.calls }}</td>
          <td class="text-right tabular-nums">{{ point.failed }}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div v-else ref="root" class="relative w-full">
    <svg :width="width" :height="HEIGHT" class="block max-w-full overflow-visible outline-none" role="img" :aria-label="summary" tabindex="0"
         @keydown="onKey" @focus="hover = hover ?? n - 1" @blur="hover = null">
      <g>
        <template v-for="tick in yTicks" :key="tick">
          <line :x1="M.left" :x2="width - M.right" :y1="y(tick)" :y2="y(tick)" stroke="rgb(var(--line))" stroke-width="1" shape-rendering="crispEdges" />
          <text :x="M.left - 8" :y="y(tick)" dy="0.32em" text-anchor="end" class="fill-subtle text-[11px] tabular-nums">{{ compact(tick) }}</text>
        </template>
        <text v-for="(index, position) in xTicks" :key="index" :x="x(index)" :y="HEIGHT - 8" class="fill-subtle text-[11px]"
              :text-anchor="xTicks.length > 1 && position === 0 ? 'start' : position === xTicks.length - 1 && xTicks.length > 1 ? 'end' : 'middle'">
          {{ axisLabel(points[index].start) }}</text>
      </g>

      <path :d="callsArea" fill="rgb(var(--chart-1))" fill-opacity="0.1" />
      <path :d="callsLine" fill="none" stroke="rgb(var(--chart-1))" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      <path :d="failedLine" fill="none" stroke="rgb(var(--chart-2))" stroke-width="2" stroke-dasharray="4 4" stroke-linejoin="round" stroke-linecap="round" />

      <g v-if="tip" pointer-events="none">
        <line :x1="tip.left" :x2="tip.left" :y1="M.top" :y2="M.top + innerH" stroke="rgb(var(--subtle))" stroke-opacity="0.5" stroke-width="1" />
        <circle :cx="tip.left" :cy="y(tip.point.calls)" r="4" fill="rgb(var(--chart-1))" stroke="rgb(var(--surface))" stroke-width="2" />
        <circle :cx="tip.left" :cy="y(tip.point.failed)" r="4" fill="rgb(var(--chart-2))" stroke="rgb(var(--surface))" stroke-width="2" />
      </g>
      <rect :x="M.left - 6" :y="M.top" :width="innerW + 12" :height="innerH" fill="transparent" @pointermove="onPointer" @pointerleave="hover = null" />
    </svg>

    <p v-if="empty" class="pointer-events-none absolute inset-x-0 top-[40%] text-center text-sm text-subtle">No tool calls in this period</p>

    <div v-if="tip" class="pointer-events-none absolute top-2 z-10 min-w-[10rem] rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop"
         :style="tip.flip ? { right: `${width - tip.left + 12}px` } : { left: `${tip.left + 12}px` }">
      <p class="mb-1.5 font-medium text-ink">{{ fullLabel(tip.point.start) }}</p>
      <p class="flex items-center justify-between gap-4 text-subtle">
        <span class="flex items-center gap-1.5"><span class="h-0.5 w-3 rounded bg-chart-1" />Calls</span>
        <span class="font-mono font-medium tabular-nums text-ink">{{ tip.point.calls }}</span></p>
      <p class="mt-1 flex items-center justify-between gap-4 text-subtle">
        <span class="flex items-center gap-1.5"><span class="w-3 border-t-2 border-dashed border-chart-2" />Unsuccessful</span>
        <span class="font-mono font-medium tabular-nums text-ink">{{ tip.point.failed }}</span></p>
    </div>

    <div class="mt-3 flex items-center justify-center gap-5 text-xs text-subtle">
      <span class="flex items-center gap-1.5"><span class="h-0.5 w-4 rounded bg-chart-1" /> Calls</span>
      <span class="flex items-center gap-1.5"><span class="w-4 border-t-2 border-dashed border-chart-2" /> Unsuccessful (errors and denials)</span>
    </div>
  </div>
</template>
