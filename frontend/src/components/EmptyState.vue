<script setup lang="ts">
withDefaults(defineProps<{ icon?: string; title: string; text?: string }>(), { icon: "sparkles", text: "" });
</script>

<template>
  <div class="flex flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 py-12 text-center">
    <div class="mb-3 rounded-full bg-brand-soft p-3 text-brand"><AppIcon :name="icon" :size="22" /></div>
    <p class="font-medium text-ink">{{ title }}</p>
    <p v-if="text" class="mt-1 max-w-md text-sm text-subtle">{{ text }}</p>
    <div v-if="$slots.default" class="mt-4 flex gap-2"><slot /></div>
  </div>
</template>
