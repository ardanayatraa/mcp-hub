<script setup lang="ts">
import { computed } from "vue";

import type { GuideFile } from "@/docs/guide";
import { download } from "@/utils/download";

const props = defineProps<{ file: GuideFile; code: string }>();

const terminal = computed(() => props.file.path === "terminal");
const lines = computed(() => props.code.split("\n").map((text) => {
  const trimmed = text.trim();
  return { text, comment: /^(\/\/|#|\/\*\*?|\*)/.test(trimmed) };
}));
const fileName = computed(() => {
  const base = props.file.path.split("/").pop() ?? "snippet.txt";
  if (base === ".env") return "mcp-hub.env.example";
  return props.file.kind === "snippet" && !terminal.value ? base.replace(/(\.\w+)$/, ".snippet$1") : base;
});
</script>

<template>
  <figure class="overflow-hidden rounded-xl border border-line bg-surface shadow-card print:break-inside-avoid">
    <figcaption class="flex flex-wrap items-center gap-2 border-b border-line bg-muted/50 px-4 py-2">
      <AppIcon :name="terminal ? 'terminal' : 'file'" :size="15" class="text-subtle" />
      <span class="min-w-[12rem] flex-1 truncate font-mono text-xs font-medium">{{ terminal ? "Terminal" : file.path }}</span>
      <span class="badge-outline">{{ file.kind === "snippet" && !terminal ? "Add to existing file" : file.lang }}</span>
      <span class="flex gap-1.5 print:hidden">
        <CopyButton :text="code" />
        <button v-if="!terminal" type="button" class="btn-secondary btn-sm" :aria-label="`Download ${file.path}`" @click="download(fileName, code + '\n')">
          <AppIcon name="download" :size="14" /> Download
        </button>
      </span>
    </figcaption>
    <p v-if="file.caption" class="border-b border-line px-4 py-2 text-xs text-subtle">{{ file.caption }}</p>
    <pre class="code-lines max-h-[34rem] overflow-auto py-3 font-mono text-[12.5px] leading-relaxed print:max-h-none print:overflow-visible print:whitespace-pre-wrap"
         :class="{ 'no-numbers': terminal || lines.length < 4 }"><code><span v-for="(line, index) in lines" :key="index" class="code-line"
      :class="line.comment ? 'text-subtle' : 'text-ink'">{{ line.text || " " }}</span></code></pre>
  </figure>
</template>
