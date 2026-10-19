<script setup lang="ts">
import { computed } from "vue";

// Prose with `inline code` and **bold** (UI labels), rendered without v-html.
const props = defineProps<{ text: string }>();
const parts = computed(() => props.text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean).map((part) => {
  if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) return { kind: "code", text: part.slice(1, -1) };
  if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) return { kind: "bold", text: part.slice(2, -2) };
  return { kind: "text", text: part };
}));
</script>

<template>
  <template v-for="(part, index) in parts" :key="index"><code v-if="part.kind === 'code'" class="code">{{ part.text }}</code><strong
    v-else-if="part.kind === 'bold'" class="font-semibold text-ink">{{ part.text }}</strong><template v-else>{{ part.text }}</template></template>
</template>
