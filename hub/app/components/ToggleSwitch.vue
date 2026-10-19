<script setup lang="ts">
const model = defineModel<boolean>({ required: true });
withDefaults(defineProps<{ label?: string; disabled?: boolean }>(), { label: "", disabled: false });
</script>

<template>
  <button type="button" role="switch" :aria-checked="model" :aria-label="label" :disabled="disabled"
          class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50"
          :class="model ? 'bg-brand' : 'bg-line'" @click="model = !model">
    <span class="inline-block h-4 w-4 rounded-full shadow transition" :class="model ? 'translate-x-[18px] bg-brand-ink' : 'translate-x-0.5 bg-white'" />
  </button>
</template>
