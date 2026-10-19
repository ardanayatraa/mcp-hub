<script setup lang="ts">
import { computed } from "vue";

import InlineText from "@/components/InlineText.vue";
import { parseMarkdown } from "@/utils/markdown";

const props = defineProps<{ text: string }>();
const blocks = computed(() => parseMarkdown(props.text));
</script>

<template>
  <div class="space-y-2 text-sm leading-relaxed">
    <template v-for="(block, index) in blocks" :key="index">
      <p v-if="block.kind === 'heading'" class="font-semibold text-ink"><InlineText :text="block.text" /></p>
      <p v-else-if="block.kind === 'paragraph'"><InlineText :text="block.text" /></p>
      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.kind === 'list'"
                 class="space-y-1 pl-5" :class="block.ordered ? 'list-decimal' : 'list-disc'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex"><InlineText :text="item" /></li>
      </component>
      <div v-else-if="block.kind === 'table'" class="overflow-x-auto rounded-md border border-line">
        <table class="w-full text-xs">
          <thead class="bg-muted"><tr><th v-for="(cell, cellIndex) in block.head" :key="cellIndex" class="px-2 py-1.5 text-left font-medium">
            <InlineText :text="cell" /></th></tr></thead>
          <tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex" class="border-t border-line">
            <td v-for="(cell, cellIndex) in row" :key="cellIndex" class="px-2 py-1.5 tabular-nums"><InlineText :text="cell" /></td></tr></tbody>
        </table>
      </div>
      <pre v-else class="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">{{ block.text }}</pre>
    </template>
  </div>
</template>
