<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import ModalDialog from "@/components/ModalDialog.vue";
import PaginationBar from "@/components/PaginationBar.vue";
import type { BuiltinTool, Tool } from "@/services/hub";
import { badgeClass, timeAgo, toolStatus } from "@/utils/format";
import { TOOL_KINDS, kindStyle, toolKind } from "@/utils/toolKinds";

// Every tool AI clients could get, Hub tools and app tools together, in one sortable, paginated table.
const props = defineProps<{ tools: Tool[]; builtins: BuiltinTool[]; usage: Record<string, number> }>();
const router = useRouter();

interface Row {
  key: string;
  title: string;
  name: string;
  description: string;
  kind: string;
  app: string;
  source: string;
  status: { label: string; tone: string };
  calls: number;
  check: { text: string; tone: string; when: string | null };
  link: string | null;
  builtin: BuiltinTool | null;
}

const rows = computed<Row[]>(() => [
  ...props.builtins.map((tool) => ({
    key: tool.name, title: tool.title, name: tool.name, description: tool.description,
    kind: tool.requires === "memory" ? "memory" : tool.name === "run_report" ? "report" : "hub",
    app: "Hub", source: tool.requires === "memory" ? "Apps with memory on" : "Every allowed data source",
    status: tool.requires === "memory" ? { label: "Opt-in per app", tone: "neutral" } : { label: "Always on", tone: "ok" },
    calls: props.usage[tool.name] ?? 0, check: { text: "Built in", tone: "text-subtle", when: null }, link: null, builtin: tool,
  })),
  ...props.tools.map((tool) => ({
    key: tool.id, title: tool.display_title, name: tool.mcp_name, description: tool.description,
    kind: toolKind(tool.template, tool.tool_key), app: tool.app_name ?? "", source: tool.module_name ?? "",
    status: toolStatus(tool), calls: props.usage[tool.tool_key] ?? 0,
    check: tool.last_test
      ? { text: tool.last_test.passed ? "Passed" : "Failed", tone: tool.last_test.passed ? "text-ok" : "text-bad", when: tool.last_test.created_at }
      : { text: tool.source_managed ? "Managed by app" : "Not tested", tone: "text-subtle", when: null },
    link: `/tools/${tool.id}`, builtin: null,
  })),
]);

const search = ref("");
const app = ref("");
const kind = ref("");
const status = ref("");
const sortBy = ref<"title" | "app" | "kind" | "status" | "calls">("title");
const descending = ref(false);
const page = ref(1);
const size = ref(25);
const opened = ref<Row | null>(null);

const appOptions = computed(() => [...new Set(rows.value.map((row) => row.app))].sort((a, b) => (a === "Hub" ? -1 : b === "Hub" ? 1 : a.localeCompare(b))));
const statusOptions = computed(() => [...new Set(rows.value.map((row) => row.status.label))].sort());
const kindOptions = computed(() => Object.entries(TOOL_KINDS).filter(([key]) => rows.value.some((row) => row.kind === key)));

const filtered = computed(() => {
  const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
  const list = rows.value.filter((row) => (!app.value || row.app === app.value) && (!kind.value || row.kind === kind.value)
    && (!status.value || row.status.label === status.value)
    && words.every((word) => `${row.title} ${row.name} ${row.app} ${row.source} ${row.description}`.toLowerCase().includes(word)));
  const value = (row: Row) => sortBy.value === "calls" ? row.calls
    : sortBy.value === "kind" ? kindStyle(row.kind).label : sortBy.value === "status" ? row.status.label : row[sortBy.value];
  return [...list].sort((a, b) => {
    const left = value(a);
    const right = value(b);
    const order = typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right));
    return (descending.value ? -order : order) || a.title.localeCompare(b.title);
  });
});
const shown = computed(() => filtered.value.slice((page.value - 1) * size.value, page.value * size.value));

watch([search, app, kind, status], () => { page.value = 1; });
watch(() => filtered.value.length, (count) => { page.value = Math.min(page.value, Math.max(1, Math.ceil(count / size.value))); });

function sort(column: typeof sortBy.value) {
  if (sortBy.value === column) descending.value = !descending.value;
  else {
    sortBy.value = column;
    descending.value = column === "calls";
  }
}

function ariaSort(column: string) {
  return sortBy.value === column ? (descending.value ? "descending" : "ascending") : "none";
}

function open(row: Row) {
  if (row.link) void router.push(row.link);
  else opened.value = row;
}

// Parameters as people read them: "status: open | done", "limit: 1–200".
function parameters(tool: BuiltinTool) {
  const required = new Set(tool.inputSchema.required ?? []);
  return Object.entries(tool.inputSchema.properties ?? {}).map(([name, raw]) => {
    const prop = raw as { type?: string | string[]; enum?: unknown[]; description?: string };
    const type = Array.isArray(prop.type) ? prop.type.join(" | ") : prop.type ?? "value";
    return { name, detail: prop.enum ? prop.enum.join(" | ") : type, description: prop.description ?? "", required: required.has(name) };
  });
}

function clear() {
  search.value = "";
  app.value = "";
  kind.value = "";
  status.value = "";
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <div class="relative min-w-[14rem] flex-1">
        <AppIcon name="search" :size="14" class="pointer-events-none absolute left-2.5 top-2.5 text-subtle" />
        <input v-model="search" class="input pl-8" placeholder="Search name, app, data source or description" aria-label="Search tools" />
      </div>
      <select v-model="app" class="input w-44" aria-label="App"><option value="">All apps</option>
        <option v-for="name in appOptions" :key="name" :value="name">{{ name === "Hub" ? "Hub tools" : name }}</option></select>
      <select v-model="kind" class="input w-40" aria-label="Kind"><option value="">Any kind</option>
        <option v-for="[key, style] in kindOptions" :key="key" :value="key">{{ style.label }}</option></select>
      <select v-model="status" class="input w-40" aria-label="Status"><option value="">Any status</option>
        <option v-for="label in statusOptions" :key="label">{{ label }}</option></select>
      <button v-if="search || app || kind || status" type="button" class="btn-ghost text-xs" @click="clear">Clear filters</button>
    </div>

    <div class="card overflow-x-auto">
      <table class="tbl">
        <thead>
          <tr>
            <th v-for="column in ([['title', 'Tool'], ['kind', 'Kind'], ['app', 'App · data source'], ['status', 'Status'], ['calls', 'Calls (7 days)']] as const)"
                :key="column[0]" :aria-sort="ariaSort(column[0])" :class="column[0] === 'calls' ? 'text-right' : ''">
              <button type="button" class="inline-flex items-center gap-1 font-medium hover:text-ink" @click="sort(column[0])">
                {{ column[1] }}
                <AppIcon :name="sortBy === column[0] ? (descending ? 'chevron-down' : 'chevron-up') : 'chevrons-up-down'" :size="12"
                         :class="sortBy === column[0] ? 'text-ink' : 'text-subtle/60'" />
              </button>
            </th>
            <th>Last test</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in shown" :key="row.key" class="row-link" @click="open(row)">
            <td class="max-w-xs">
              <span class="flex min-w-0 items-center gap-2.5">
                <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md" :class="kindStyle(row.kind).tile">
                  <AppIcon :name="kindStyle(row.kind).icon" :size="15" /></span>
                <span class="min-w-0"><span class="block truncate font-medium">{{ row.title }}</span>
                  <span class="block truncate font-mono text-xs text-subtle">{{ row.name }}</span></span>
              </span>
            </td>
            <td class="whitespace-nowrap text-xs">{{ kindStyle(row.kind).label }}</td>
            <td class="text-xs"><p>{{ row.app === "Hub" ? "Hub tool" : row.app }}</p><p class="text-subtle">{{ row.source }}</p></td>
            <td><span :class="badgeClass(row.status.tone as never)">{{ row.status.label }}</span></td>
            <td class="text-right tabular-nums" :class="row.calls ? 'font-medium' : 'text-subtle'">{{ row.calls.toLocaleString() }}</td>
            <td class="whitespace-nowrap text-xs"><span :class="row.check.tone">{{ row.check.text }}</span>
              <span v-if="row.check.when" class="text-subtle"> · {{ timeAgo(row.check.when) }}</span></td>
          </tr>
          <tr v-if="!shown.length"><td colspan="6" class="py-10 text-center text-subtle">No tools match these filters.</td></tr>
        </tbody>
      </table>
    </div>
    <PaginationBar v-model:page="page" v-model:size="size" :total="filtered.length" label="tools" />

    <ModalDialog v-if="opened?.builtin" :title="opened.title" wide @close="opened = null">
      <div class="space-y-4">
        <div class="flex flex-wrap items-center gap-2">
          <span :class="badgeClass(opened.status.tone as never)">{{ opened.status.label }}</span>
          <code class="code">{{ opened.name }}</code>
          <span class="text-xs text-subtle">{{ opened.source }}</span>
        </div>
        <p class="text-sm">{{ opened.description }}</p>
        <div>
          <p class="label">What it takes</p>
          <ul v-if="parameters(opened.builtin).length" class="space-y-1.5">
            <li v-for="param in parameters(opened.builtin)" :key="param.name" class="text-sm">
              <span class="font-mono font-medium">{{ param.name }}</span><span v-if="param.required" class="text-bad">*</span>
              <span class="ml-1 text-xs text-subtle">{{ param.detail }}</span>
              <span v-if="param.description" class="block text-xs text-subtle">{{ param.description }}</span>
            </li>
          </ul>
          <p v-else class="text-sm text-subtle">No parameters.</p>
        </div>
        <p class="text-xs text-subtle">{{ opened.calls ? `Called ${opened.calls === 1 ? "once" : `${opened.calls.toLocaleString()} times`} in the last 7 days.` : "Not called in the last 7 days." }}</p>
      </div>
      <template #footer>
        <RouterLink v-if="opened.name === 'run_report'" to="/tools/report" class="btn-secondary">
          <AppIcon name="chart" :size="16" /> Try it in the playground</RouterLink>
        <button type="button" class="btn-primary" @click="opened = null">Done</button>
      </template>
    </ModalDialog>
  </section>
</template>
