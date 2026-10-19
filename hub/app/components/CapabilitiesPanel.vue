<script setup lang="ts">
import { computed } from "vue";

import CopyButton from "@/components/CopyButton.vue";
import type { Capabilities, CapabilityApp } from "@/services/hub";
import { appStatus, badgeClass } from "@/utils/format";
import { kindStyle } from "@/utils/toolKinds";

// Everything this MCP Hub can do right now, in plain words with the technical detail underneath.
const props = defineProps<{ data: Capabilities }>();

const OPERATORS: Record<string, string> = {
  eq: "equals", ne: "is not", in: "one of", gt: "greater than", gte: "at least", lt: "less than", lte: "at most",
  between: "between", contains: "contains", is_null: "is empty", not_null: "has a value",
};
const KINDS = ["list", "count", "get", "read", "report", "create", "update", "delete"];
const READS = ["list", "count", "get", "read"];
const WRITES = ["create", "update", "delete"];

const sum = (counts: Record<string, number>, kinds: string[]) => kinds.reduce((total, name) => total + (counts[name] ?? 0), 0);
const plural = (count: number, word: string) => `${count.toLocaleString()} ${word}${count === 1 ? "" : "s"}`;
const bytes = (value: number) => (value >= 1_048_576 ? `${+(value / 1_048_576).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`);

const totals = computed(() => {
  const s = props.data.summary;
  return { reads: sum(s.by_kind, READS), writes: sum(s.by_kind, WRITES), calls: Object.values(props.data.usage).reduce((a, b) => a + b, 0) };
});

const stats = computed(() => {
  const s = props.data.summary;
  return [
    { label: "Apps connected", icon: "apps", value: s.apps, hint: `${s.apps_active} active` },
    { label: "Live tools", icon: "tools", value: s.tools_live, suffix: `of ${s.tools_total}`, hint: s.switched_off ? `${s.switched_off} switched off` : "None switched off" },
    { label: "Data sources on", icon: "database", value: s.data_sources_on, hint: "Readable by AI clients" },
    { label: "Calls (7 days)", icon: "activity", value: totals.value.calls, hint: "Every tool, every app" },
    { label: "Skills", icon: "book", value: s.skills, hint: "Ready-made prompts" },
    { label: "Memory", icon: "sparkles", value: s.memory_apps, suffix: s.memory_apps === 1 ? "app" : "apps", hint: "Remembers each user" },
    { label: "AI chat", icon: "chat", value: s.chat_apps, suffix: s.chat_apps === 1 ? "app" : "apps", hint: "Chat built into the app" },
    { label: "Client keys", icon: "key", value: s.client_keys, hint: `${s.write_keys} may propose changes` },
  ];
});

const cards = computed(() => {
  const { summary: s, report: r, limits: l, protocol: p } = props.data;
  return [
    {
      icon: "table", tone: "bg-chart-1/10 text-chart-1", title: "Read data", status: plural(totals.value.reads, "live tool"),
      text: "Answers questions from app records: list with filters, sorting and pages, count, or look up one record.",
      points: [`Up to ${l.page_size} records per page`, "Runs as the signed-in user, so people only see their own data",
        "list_data_sources tells the AI which fields it may filter, group or total"],
    },
    {
      icon: "chart", tone: "bg-chart-2/10 text-chart-2", title: "Reports and analytics", status: "Always on",
      text: "run_report totals, averages and groups any allowed data source, with no custom tool needed.",
      points: [`Group by up to ${r.max_group_by} fields, ${r.max_metrics} totals and ${r.max_filters} filters per report`,
        `Returns up to ${r.max_rows} rows, reads up to ${r.max_records_read.toLocaleString()} records`, `Stops after ${r.timeout_seconds} seconds`],
      report: true,
    },
    {
      icon: "pencil", tone: "bg-warn/10 text-warn", title: "Create, update and delete", status: plural(totals.value.writes, "live tool"),
      text: "Nothing changes straight away. The app answers with a proposal, and the person confirms or cancels it in the app.",
      points: [`Needs a client key allowed to propose changes (${s.write_keys} of ${s.client_keys})`,
        "Each request carries an Idempotency-Key, so a retry never applies a change twice", "Every proposal and decision is in Activity"],
      kinds: WRITES,
    },
    {
      icon: "book", tone: "bg-chart-1/10 text-chart-1", title: "Skills", status: plural(s.skills, "skill"),
      text: "Saved instructions that AI clients load as MCP prompts, so a common job runs the same way every time.",
      points: ["Listed with prompts/list, loaded with prompts/get", "Can take arguments, such as a period or a customer"],
    },
    {
      icon: "sparkles", tone: "bg-chart-2/10 text-chart-2", title: "Memory", status: s.memory_apps ? `On in ${plural(s.memory_apps, "app")}` : "Off everywhere",
      text: "Opt-in per app. The AI can save, recall and forget short notes and preferences for each user.",
      points: ["Belongs to the signed-in user, never shared between users", "Encrypted, expires after the app's retention period",
        "Hidden from Hub administrators"],
    },
    {
      icon: "chat", tone: "bg-brand/10 text-brand", title: "AI chat", status: s.chat_apps ? `On in ${plural(s.chat_apps, "app")}` : "Off everywhere",
      text: "A chat apps build into their own screens. It streams answers, uses the same tools and asks before any change.",
      points: ["Claude or any OpenAI-compatible provider, models listed automatically", p.chat, `Up to ${l.chat_messages}`],
    },
    {
      icon: "power", tone: "bg-muted text-ink", title: "Tool switches", status: s.switched_off ? `${s.switched_off} switched off` : "All on",
      text: "Turn any tool off for one app without deleting it. AI clients stop seeing it on their next request.",
      points: ["Per app, from the app's Tools tab", "Switched-off tools keep their settings and history"],
    },
    {
      icon: "shield", tone: "bg-ok/10 text-ok", title: "Safety", status: "Always on",
      text: "Every call is checked before it reaches the app, and recorded after.",
      points: [`Rate limit: ${l.tool_calls}`, `Requests up to ${bytes(l.payload_bytes)}`, "Personal data is checked on the way in and out",
        `Signed user context: ${p.user_context}`],
    },
  ];
});

const protocol = computed(() => {
  const p = props.data.protocol;
  return [
    { label: "Transport", value: p.transport },
    { label: "Sign in", value: p.auth, mono: true },
    { label: "User context", value: p.user_context },
    { label: "Hub → app", value: p.app_auth },
    { label: "Chat API", value: p.chat },
    { label: "Built on", value: p.sdk },
    { label: "Hub version", value: props.data.version },
  ];
});

function reads(app: CapabilityApp) {
  return sum(app.kinds, READS);
}
</script>

<template>
  <div class="space-y-8">
    <section class="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <div v-for="stat in stats" :key="stat.label" class="card">
        <div class="flex items-center justify-between gap-2 p-4 pb-1 sm:p-5 sm:pb-1">
          <p class="truncate text-sm font-medium">{{ stat.label }}</p>
          <AppIcon :name="stat.icon" :size="18" class="text-subtle" />
        </div>
        <div class="px-4 pb-4 sm:px-5 sm:pb-5">
          <p class="text-2xl font-semibold tabular-nums">{{ stat.value.toLocaleString() }}<span v-if="stat.suffix" class="ml-1 text-sm font-normal text-subtle">{{ stat.suffix }}</span></p>
          <p class="mt-1 text-xs text-subtle">{{ stat.hint }}</p>
        </div>
      </div>
    </section>

    <section>
      <h2 class="mb-1 font-semibold">Live tools by kind</h2>
      <p class="mb-3 text-sm text-subtle">App tools that AI clients can call right now, not counting the Hub's own tools.</p>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <div v-for="name in KINDS" :key="name" class="card flex items-center gap-3 p-3">
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-md" :class="kindStyle(name).tile"><AppIcon :name="kindStyle(name).icon" :size="16" /></span>
          <span class="min-w-0"><span class="block text-lg font-semibold leading-tight tabular-nums">{{ data.summary.by_kind[name] ?? 0 }}</span>
            <span class="block truncate text-xs text-subtle">{{ kindStyle(name).label }}</span></span>
        </div>
      </div>
    </section>

    <section>
      <h2 class="mb-1 font-semibold">What this MCP can do</h2>
      <p class="mb-3 text-sm text-subtle">Each capability, what it means for people using it, and how it works.</p>
      <div class="grid gap-4 lg:grid-cols-2">
        <article v-for="card in cards" :key="card.title" class="card card-pad">
          <div class="mb-3 flex items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg" :class="card.tone"><AppIcon :name="card.icon" :size="18" /></span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 class="font-semibold">{{ card.title }}</h3>
                <span class="badge-outline">{{ card.status }}</span>
              </div>
              <p class="mt-1 text-sm text-subtle">{{ card.text }}</p>
            </div>
          </div>
          <ul class="space-y-1.5 text-sm">
            <li v-for="point in card.points" :key="point" class="flex gap-2"><AppIcon name="check" :size="14" class="mt-0.5 shrink-0 text-ok" />{{ point }}</li>
          </ul>
          <div v-if="card.kinds" class="mt-3 flex flex-wrap gap-2">
            <span v-for="name in card.kinds" :key="name" class="badge-neutral"><AppIcon :name="kindStyle(name).icon" :size="12" />
              {{ kindStyle(name).label }} · {{ data.summary.by_kind[name] ?? 0 }}</span>
          </div>
          <div v-if="card.report" class="mt-4 space-y-3 border-t border-line pt-4">
            <div>
              <p class="mb-1.5 text-xs font-medium text-subtle">Filters</p>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="op in data.report.filters" :key="op" class="badge-outline" :title="op"><code class="font-mono">{{ op }}</code>
                  <span class="font-normal text-subtle">{{ OPERATORS[op] ?? op }}</span></span>
              </div>
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <div><p class="mb-1.5 text-xs font-medium text-subtle">Totals</p>
                <div class="flex flex-wrap gap-1.5"><code v-for="metric in data.report.metrics" :key="metric" class="code">{{ metric }}</code></div></div>
              <div><p class="mb-1.5 text-xs font-medium text-subtle">Time buckets</p>
                <div class="flex flex-wrap gap-1.5"><code v-for="interval in data.report.intervals" :key="interval" class="code">{{ interval }}</code></div></div>
            </div>
            <RouterLink to="/tools/report" class="link inline-block text-xs">Try it in the report playground →</RouterLink>
          </div>
        </article>
      </div>
    </section>

    <section class="card">
      <div class="card-header pb-4">
        <h2 class="card-title">How AI clients connect</h2>
        <p class="card-description">Any MCP client (Claude, Cursor, your own agent) connects with these settings.</p>
      </div>
      <dl class="divide-y divide-line border-t border-line text-sm">
        <div class="grid gap-1 px-6 py-3 sm:grid-cols-[10rem_1fr] sm:items-center">
          <dt class="text-subtle">MCP endpoint</dt>
          <dd class="flex flex-wrap items-center gap-2"><code class="code break-all">{{ data.protocol.endpoint }}</code>
            <CopyButton :text="data.protocol.endpoint" /></dd>
        </div>
        <div class="grid gap-1 px-6 py-3 sm:grid-cols-[10rem_1fr] sm:items-center">
          <dt class="text-subtle">Methods</dt>
          <dd class="flex flex-wrap gap-1.5"><code v-for="method in data.protocol.methods" :key="method" class="code">{{ method }}</code></dd>
        </div>
        <div v-for="row in protocol" :key="row.label" class="grid gap-1 px-6 py-3 sm:grid-cols-[10rem_1fr] sm:items-center">
          <dt class="text-subtle">{{ row.label }}</dt>
          <dd><code v-if="row.mono" class="code">{{ row.value }}</code><template v-else>{{ row.value }}</template></dd>
        </div>
      </dl>
    </section>

    <section>
      <h2 class="mb-1 font-semibold">By app</h2>
      <p class="mb-3 text-sm text-subtle">What each app lets AI clients do. Numbers are live tools; switched-off and draft tools are left out.</p>
      <div class="card overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>App</th><th>Status</th><th class="text-right">Data sources</th><th class="text-right">Live tools</th>
              <th class="text-center">Read</th><th class="text-center">Report</th><th class="text-center">Create</th>
              <th class="text-center">Update</th><th class="text-center">Delete</th><th class="text-center">Skills</th>
              <th class="text-center">Memory</th><th>AI chat</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="app in data.apps" :key="app.connector_id">
              <td><RouterLink :to="`/apps/${app.connector_id}`" class="font-medium hover:underline">{{ app.name }}</RouterLink>
                <span class="block font-mono text-xs text-subtle">{{ app.app_key }}</span></td>
              <td><span :class="badgeClass(appStatus[app.status]?.tone ?? 'neutral')">{{ appStatus[app.status]?.label ?? app.status }}</span></td>
              <td class="text-right tabular-nums">{{ app.sources_on }}</td>
              <td class="text-right tabular-nums"><span class="font-medium">{{ app.tools_live }}</span><span class="text-subtle"> / {{ app.tools_total }}</span>
                <span v-if="app.switched_off" class="block text-xs text-subtle">{{ app.switched_off }} off</span></td>
              <td v-for="(count, index) in [reads(app), app.kinds.report, app.kinds.create, app.kinds.update, app.kinds.delete, app.skills]" :key="index"
                  class="text-center tabular-nums" :class="count ? '' : 'text-subtle/60'">{{ count || "—" }}</td>
              <td class="text-center"><AppIcon v-if="app.memory" name="check" :size="16" class="inline text-ok" aria-label="On" />
                <span v-else class="text-subtle/60" aria-label="Off">—</span></td>
              <td class="text-xs"><template v-if="app.chat"><span class="text-ok">On</span>
                <span class="block max-w-[12rem] truncate text-subtle" :title="app.chat_model ?? ''">{{ app.chat_model }}</span></template>
                <span v-else class="text-subtle/60">—</span></td>
            </tr>
            <tr v-if="!data.apps.length"><td colspan="12" class="py-10 text-center text-subtle">No apps connected yet.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
