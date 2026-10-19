<script setup lang="ts">
defineProps<{ title: string; subtitle?: string; back?: string }>();
</script>

<template>
  <header class="mb-8 flex flex-wrap items-end justify-between gap-4">
    <div class="min-w-0">
      <RouterLink v-if="back" :to="back" class="mb-3 inline-flex items-center gap-1 text-xs font-medium text-subtle hover:text-ink">
        <AppIcon name="chevron-left" :size="14" /> Back
      </RouterLink>
      <h1 class="text-2xl font-semibold tracking-tight text-ink">
        <slot name="title">{{ title }}</slot>
      </h1>
      <p v-if="subtitle || $slots.subtitle" class="mt-1.5 max-w-3xl text-sm text-subtle">
        <slot name="subtitle">{{ subtitle }}</slot>
      </p>
    </div>
    <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
