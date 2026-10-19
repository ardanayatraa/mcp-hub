<script setup lang="ts">
const model = defineModel<string>({ required: true });
defineProps<{ tabs: { key: string; label: string; count?: number }[] }>();
</script>

<template>
  <div class="mb-6 max-w-full overflow-x-auto">
    <nav class="segmented" role="tablist">
      <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" class="segmented-item" :aria-selected="model === tab.key"
              @click="model = tab.key">
        {{ tab.label }}
        <span v-if="tab.count !== undefined" class="text-xs tabular-nums text-subtle">{{ tab.count }}</span>
      </button>
    </nav>
  </div>
</template>
