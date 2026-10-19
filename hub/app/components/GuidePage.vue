<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "#imports";

import CodeFile from "@/components/CodeFile.vue";
import HubFlowFigure from "@/components/HubFlowFigure.vue";
import InlineText from "@/components/InlineText.vue";
import { guideMarkdown, withMcpUrl, type GuideMeta, type GuideSection } from "@/docs/guide";
import { hub } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { download, zipFiles } from "@/utils/download";

// A long-form guide: sections with a table of contents, copyable code, Markdown download and print.
const props = defineProps<{
  guide: GuideMeta;
  sections: GuideSection[];
  markdownName: string;
  kit?: { fileName: string; title: string; description: string; files: (mcpUrl: string) => { path: string; content: string }[] };
}>();
const route = useRoute();
const toast = useToast();
const mcpUrl = ref("");
const activeId = ref(props.sections[0]?.id ?? "");
const kitCount = computed(() => props.kit?.files(mcpUrl.value).length ?? 0);
let scroller: HTMLElement | null = null;

// The page scrolls inside the shell's <main>, so the table of contents follows that element.
function onScroll() {
  let current = props.sections[0]?.id ?? "";
  for (const section of props.sections) {
    const top = document.getElementById(section.id)?.getBoundingClientRect().top;
    if (top !== undefined && top <= 160) current = section.id;
  }
  activeId.value = current;
}

function jump(id: string, smooth = true) {
  const motion = smooth && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.getElementById(id)?.scrollIntoView({ behavior: motion ? "smooth" : "auto", block: "start" });
}

onMounted(async () => {
  scroller = document.querySelector("main");
  scroller?.addEventListener("scroll", onScroll, { passive: true });
  // Links such as /docs/guide#clients open at that section.
  if (route.hash) {
    await nextTick();
    jump(route.hash.slice(1), false);
  }
  onScroll();
  try {
    mcpUrl.value = (await hub.system()).mcp_url;
  } catch {
    mcpUrl.value = "";
  }
});
onBeforeUnmount(() => scroller?.removeEventListener("scroll", onScroll));

function downloadKit() {
  if (!props.kit) return;
  download(props.kit.fileName, zipFiles(props.kit.files(mcpUrl.value)));
  toast.ok(`${props.kit.title} downloaded`);
}

function downloadGuide() {
  download(props.markdownName, guideMarkdown(props.guide, props.sections, mcpUrl.value), "text/markdown");
}

function printPage() {
  window.print();
}
</script>

<template>
  <div class="lg:grid lg:grid-cols-[minmax(0,1fr)_13rem] lg:gap-12">
    <article class="min-w-0">
      <header class="mb-10 border-b border-line pb-8">
        <span class="badge-outline mb-4"><AppIcon name="book" :size="12" /> {{ guide.badge }}</span>
        <h1 class="text-3xl font-semibold tracking-tight">{{ guide.title }}</h1>
        <p class="mt-3 max-w-2xl text-base leading-7 text-subtle">{{ guide.summary }}</p>
        <ul class="mt-4 flex flex-wrap gap-2">
          <li v-for="item in guide.meta" :key="item" class="badge-neutral">{{ item }}</li>
        </ul>
        <div class="mt-6 flex flex-wrap gap-2 print:hidden">
          <button v-if="kit" type="button" class="btn-primary" @click="downloadKit"><AppIcon name="download" :size="16" /> Download {{ kit.title.toLowerCase() }} (.zip)</button>
          <button type="button" :class="kit ? 'btn-secondary' : 'btn-primary'" @click="downloadGuide"><AppIcon name="file" :size="16" /> Download guide (.md)</button>
          <button type="button" class="btn-ghost" @click="printPage">Print or save as PDF</button>
        </div>
        <p v-if="kit" class="hint print:hidden">
          The kit holds {{ kitCount }} files. {{ kit.description }}<template v-if="mcpUrl"> Examples already use this Hub's MCP endpoint.</template>
        </p>
        <p v-else-if="mcpUrl" class="hint print:hidden">Examples on this page already use this Hub's MCP endpoint, <span class="code">{{ mcpUrl }}</span>.</p>

        <details class="card mt-6 p-4 lg:hidden print:hidden">
          <summary class="cursor-pointer text-sm font-medium">On this page</summary>
          <ul class="mt-3 space-y-1.5 text-sm">
            <li v-for="section in sections" :key="section.id">
              <button type="button" class="text-left text-subtle hover:text-ink" @click="jump(section.id)">
                {{ section.step ? `${section.step}. ` : "" }}{{ section.title }}</button>
            </li>
          </ul>
        </details>
      </header>

      <section v-for="section in sections" :id="section.id" :key="section.id" class="mb-14 scroll-mt-6">
        <h2 class="flex items-center gap-3 text-xl font-semibold tracking-tight">
          <span v-if="section.step" class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand text-xs font-semibold text-brand-ink">{{ section.step }}</span>
          {{ section.title }}
        </h2>

        <p v-for="paragraph in section.body" :key="paragraph" class="mt-3 max-w-3xl leading-7"><InlineText :text="paragraph" /></p>

        <HubFlowFigure v-if="section.figure === 'hub-flow'">{{ section.figureText }}</HubFlowFigure>

        <ol v-if="section.steps" class="mt-4 max-w-3xl space-y-3">
          <li v-for="(item, index) in section.steps" :key="item" class="flex gap-3 leading-7">
            <span class="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold">{{ index + 1 }}</span>
            <span><InlineText :text="item" /></span>
          </li>
        </ol>

        <div v-if="section.table" class="card mt-4 overflow-x-auto">
          <table class="tbl">
            <thead><tr><th v-for="cell in section.table.head" :key="cell">{{ cell }}</th></tr></thead>
            <tbody>
              <tr v-for="row in section.table.rows" :key="row[0]">
                <td v-for="(cell, index) in row" :key="index" class="align-top text-sm" :class="index === 0 ? 'font-medium' : 'text-subtle'">
                  <InlineText :text="cell" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        <ul v-if="section.list" class="mt-4 max-w-3xl space-y-2.5">
          <li v-for="item in section.list" :key="item" class="flex gap-3 leading-7">
            <AppIcon name="check" :size="16" class="mt-1.5 text-subtle" /><span><InlineText :text="item" /></span>
          </li>
        </ul>

        <div v-if="section.files" class="mt-5 space-y-4">
          <CodeFile v-for="file in section.files" :key="file.path + file.code.length" :file="file" :code="withMcpUrl(file.code, mcpUrl)" />
        </div>

        <div v-for="note in section.after ?? []" :key="note" class="mt-4 flex max-w-3xl gap-3 rounded-lg border border-line bg-muted/40 p-4 text-sm leading-6">
          <AppIcon name="info" :size="16" class="mt-0.5 text-subtle" /><p><InlineText :text="note" /></p>
        </div>
      </section>

      <div class="print:hidden"><slot name="footer" /></div>
    </article>

    <aside class="hidden lg:block print:hidden">
      <nav class="sticky top-0 pt-1 text-sm" aria-label="On this page">
        <p class="mb-3 font-medium">On this page</p>
        <ul class="border-l border-line">
          <li v-for="section in sections" :key="section.id">
            <button type="button" class="-ml-px block w-full border-l-2 py-1.5 pl-3 text-left transition-colors"
                    :class="activeId === section.id ? 'border-ink font-medium text-ink' : 'border-transparent text-subtle hover:text-ink'"
                    :aria-current="activeId === section.id ? 'location' : undefined" @click="jump(section.id)">
              {{ section.step ? `${section.step}. ` : "" }}{{ section.title }}
            </button>
          </li>
        </ul>
        <div v-if="kit" class="card mt-6 p-4">
          <p class="text-sm font-medium">{{ kit.title }}</p>
          <p class="mt-1 text-xs text-subtle">Every file on this page, ready to copy into your project.</p>
          <button type="button" class="btn-secondary btn-sm mt-3 w-full" @click="downloadKit"><AppIcon name="download" :size="14" /> Download .zip</button>
        </div>
        <slot name="aside" />
      </nav>
    </aside>
  </div>
</template>
