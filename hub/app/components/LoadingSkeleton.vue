<script setup lang="ts">
// Placeholder shaped like the content that is loading, so the page does not jump when it arrives.
withDefaults(defineProps<{ variant?: "cards" | "rows" | "panel" | "stats"; count?: number; label?: string }>(),
  { variant: "rows", count: 3, label: "Loading" });
</script>

<template>
  <div role="status" aria-live="polite" :aria-busy="true">
    <span class="sr-only">{{ label }}…</span>

    <div v-if="variant === 'cards'" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
      <div v-for="n in count" :key="n" class="card card-pad flex flex-col gap-4">
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1 space-y-2"><span class="skeleton h-4 w-32" /><span class="skeleton h-3 w-24" /></div>
          <span class="skeleton h-5 w-14 rounded-full" />
        </div>
        <span class="skeleton h-3 w-40" />
        <div class="grid grid-cols-2 gap-2 border-t border-line pt-3">
          <div class="space-y-2"><span class="skeleton h-3 w-20" /><span class="skeleton h-5 w-10" /></div>
          <div class="space-y-2"><span class="skeleton h-3 w-16" /><span class="skeleton h-5 w-10" /></div>
        </div>
      </div>
    </div>

    <div v-else-if="variant === 'stats'" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
      <div v-for="n in count" :key="n" class="card card-pad space-y-3">
        <span class="skeleton h-3 w-20" /><span class="skeleton h-7 w-24" /><span class="skeleton h-3 w-28" />
      </div>
    </div>

    <div v-else-if="variant === 'panel'" class="card card-pad space-y-4" aria-hidden="true">
      <span class="skeleton h-4 w-40" />
      <span v-for="n in count" :key="n" class="skeleton h-3" :class="n % 3 === 0 ? 'w-1/2' : n % 2 === 0 ? 'w-3/4' : 'w-full'" />
    </div>

    <div v-else class="card divide-y divide-line" aria-hidden="true">
      <div class="flex gap-6 px-4 py-3"><span class="skeleton h-3 w-24" /><span class="skeleton h-3 w-16" /><span class="skeleton h-3 w-20" /></div>
      <div v-for="n in count" :key="n" class="flex items-center gap-4 px-4 py-3.5">
        <div class="flex-1 space-y-2"><span class="skeleton h-4 w-48 max-w-full" /><span class="skeleton h-3 w-32" /></div>
        <span class="skeleton hidden h-3 w-24 sm:block" />
        <span class="skeleton h-5 w-16 rounded-full" />
      </div>
    </div>
  </div>
</template>
