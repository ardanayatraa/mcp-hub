<script setup lang="ts">
import { computed } from "vue";

// Inline Markdown is rendered as text and Vue nodes, never injected as HTML.
const props = defineProps<{ text: string }>();
const parts = computed(() => props.text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|~~[^~\n]+~~|\[[^\]\n]+\]\([^)\s]+\))/g)
  .filter(Boolean).map((part) => {
    if (part.startsWith("`") && part.endsWith("`")) return { kind: "code", text: part.slice(1, -1) };
    if (part.startsWith("**") && part.endsWith("**")) return { kind: "bold", text: part.slice(2, -2) };
    if (part.startsWith("*") && part.endsWith("*")) return { kind: "italic", text: part.slice(1, -1) };
    if (part.startsWith("~~") && part.endsWith("~~")) return { kind: "strike", text: part.slice(2, -2) };
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link && /^https?:\/\//i.test(link[2])) return { kind: "link", text: link[1], href: link[2] };
    return { kind: "text", text: part };
  }));
</script>

<template>
  <template v-for="(part, index) in parts" :key="index"><code v-if="part.kind === 'code'" class="code">{{ part.text }}</code><strong
    v-else-if="part.kind === 'bold'" class="font-semibold text-ink">{{ part.text }}</strong><em
    v-else-if="part.kind === 'italic'">{{ part.text }}</em><s v-else-if="part.kind === 'strike'">{{ part.text }}</s><a
    v-else-if="part.kind === 'link'" :href="part.href" target="_blank" rel="noopener noreferrer" class="text-brand underline underline-offset-2">{{ part.text }}</a><template v-else>{{ part.text }}</template></template>
</template>
