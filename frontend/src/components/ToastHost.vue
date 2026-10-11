<script setup lang="ts">
import { useToast } from "@/stores/toast";

const toast = useToast();
const tone = { ok: "border-ok/30 bg-ok-soft text-ok", bad: "border-bad/30 bg-bad-soft text-bad", info: "border-brand/30 bg-brand-soft text-brand" };
const icon = { ok: "check", bad: "alert", info: "info" };
</script>

<template>
  <div class="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
    <div v-for="item in toast.items" :key="item.id" role="status"
         class="pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-pop" :class="tone[item.tone]">
      <AppIcon :name="icon[item.tone]" :size="16" class="mt-0.5" />
      <span class="flex-1 text-ink">{{ item.message }}</span>
      <button type="button" class="text-subtle hover:text-ink" aria-label="Dismiss" @click="toast.dismiss(item.id)">
        <AppIcon name="x" :size="14" />
      </button>
    </div>
  </div>
</template>
