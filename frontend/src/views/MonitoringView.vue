<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import MonitorBoard from "@/components/MonitorBoard.vue";
import { ApiError } from "@/services/api";
import { hub, type MonitoringBoard } from "@/services/hub";
import { errorMessage } from "@/utils/format";

const POLL_MS = 4000;
const WINDOWS = ["5m", "1h", "24h"] as const;

const board = ref<MonitoringBoard | null>(null);
const windowKey = ref("5m");
const paused = ref(false);
const error = ref("");
const stopped = ref(false);
const loading = ref(false);
let pending = false;
let poll: ReturnType<typeof setInterval> | undefined;

async function load(background = true) {
  if (pending || stopped.value || (background && (paused.value || document.hidden))) return;
  pending = true;
  if (!background) loading.value = true;
  try {
    board.value = await hub.monitoring(windowKey.value);
    error.value = "";
  } catch (exc) {
    error.value = errorMessage(exc);
    // A finished session will not come back by itself: stop asking until the page is opened again.
    if (exc instanceof ApiError && exc.status === 401) stopped.value = true;
  } finally {
    pending = false;
    loading.value = false;
  }
}
const resume = () => { void load(); };
onMounted(() => {
  void load(false);
  poll = setInterval(resume, POLL_MS);
  document.addEventListener("visibilitychange", resume);
});
onBeforeUnmount(() => {
  clearInterval(poll);
  document.removeEventListener("visibilitychange", resume);
});
watch(windowKey, () => { void load(false); });
watch(paused, (value) => { if (!value) void load(); });

const status = computed(() => {
  if (stopped.value) return { text: "Stopped", dot: "bg-bad" };
  if (error.value) return { text: "Reconnecting…", dot: "bg-warn" };
  if (paused.value) return { text: "Paused", dot: "bg-subtle" };
  return { text: "Live", dot: "bg-ok" };
});
</script>

<template>
  <h1 class="mb-4 text-2xl font-semibold tracking-tight text-ink">Monitoring</h1>

  <p v-if="error" role="alert" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">
    {{ error }}<template v-if="stopped"> Sign in again to resume live updates.</template>
  </p>

  <LoadingSkeleton v-if="!board && !error" variant="panel" :count="8" label="Loading the board" />
  <section v-if="board" class="card overflow-hidden transition-opacity" :class="loading ? 'opacity-60' : ''" :aria-busy="loading">
    <MonitorBoard :board="board">
      <template #corner>
        <div class="absolute left-3 top-3 flex items-center gap-1 rounded-lg border border-line bg-surface/95 p-1 shadow-card backdrop-blur"
             @pointerdown.stop>
          <span class="inline-flex items-center gap-2 px-2 text-xs text-subtle" role="status" aria-live="polite">
            <span class="relative flex h-2.5 w-2.5">
              <span v-if="status.text === 'Live'" class="absolute inline-flex h-full w-full rounded-full bg-ok opacity-60 motion-safe:animate-ping" />
              <span class="relative inline-flex h-2.5 w-2.5 rounded-full" :class="status.dot" />
            </span>
            {{ status.text }}
          </span>
          <button type="button" class="btn-ghost btn-icon h-8 w-8" :disabled="stopped" :title="paused ? 'Resume' : 'Pause'"
                  :aria-label="paused ? 'Resume' : 'Pause'" @click="paused = !paused">
            <AppIcon :name="paused ? 'play' : 'pause'" :size="14" />
          </button>
          <span class="mx-0.5 h-5 w-px bg-line" aria-hidden="true" />
          <div class="flex items-center gap-0.5" role="group" aria-label="Time window">
            <button v-for="value in WINDOWS" :key="value" type="button" class="h-8 rounded-md px-2.5 text-xs font-medium"
                    :class="windowKey === value ? 'bg-muted text-ink' : 'text-subtle hover:text-ink'" :aria-pressed="windowKey === value"
                    @click="windowKey = value">{{ value }}</button>
          </div>
        </div>
      </template>
    </MonitorBoard>
  </section>
</template>
