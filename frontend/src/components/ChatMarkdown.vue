<script setup lang="ts">
import { computed } from "vue";

import InlineText from "@/components/InlineText.vue";
import { parseMarkdown } from "@/utils/markdown";

const props = defineProps<{ text: string }>();
const blocks = computed(() => parseMarkdown(props.text));
</script>

<template>
  <div class="min-w-0 space-y-3 break-words text-sm leading-relaxed">
    <template v-for="(block, index) in blocks" :key="index">
      <p v-if="block.kind === 'heading'" class="font-semibold text-ink"
         :class="block.level === 1 ? 'text-base' : 'text-sm'"><InlineText :text="block.text" /></p>
      <p v-else-if="block.kind === 'paragraph'"><InlineText :text="block.text" /></p>
      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.kind === 'list'"
                 class="space-y-1.5 pl-5" :class="block.ordered ? 'list-decimal' : 'list-disc'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex"><InlineText :text="item" /></li>
      </component>
      <div v-else-if="block.kind === 'table'" class="max-h-[28rem] max-w-full overflow-auto rounded-lg border border-line">
        <table class="min-w-full border-collapse text-left text-xs">
          <thead class="sticky top-0 z-10 bg-muted text-ink"><tr><th v-for="(cell, cellIndex) in block.head" :key="cellIndex" class="whitespace-nowrap border-b border-line px-3 py-2 font-semibold">
            <InlineText :text="cell" /></th></tr></thead>
          <tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex" class="border-b border-line last:border-0 even:bg-muted/40">
            <td v-for="(cell, cellIndex) in row" :key="cellIndex" class="max-w-[24rem] px-3 py-2 align-top tabular-nums"><InlineText :text="cell" /></td></tr></tbody>
        </table>
      </div>
      <blockquote v-else-if="block.kind === 'quote'" class="border-l-2 border-line pl-3 text-subtle"><InlineText :text="block.text" /></blockquote>
      <hr v-else-if="block.kind === 'rule'" class="border-line" />
      <pre v-else class="max-w-full overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs"><code>{{ block.text }}</code></pre>
    </template>
  </div>
</template>
