<script setup lang="ts">
withDefaults(defineProps<{ code: string; copy?: boolean; maxHeight?: string }>(), { copy: true, maxHeight: "24rem" });
</script>

<template>
  <div class="relative min-w-0 max-w-full rounded-lg border border-line bg-muted">
    <div v-if="copy" class="absolute right-2 top-2"><CopyButton :text="code" /></div>
    <pre class="overflow-auto p-3 pr-24 font-mono text-xs leading-relaxed text-ink" :style="{ maxHeight }">{{ code }}</pre>
  </div>
</template>
