<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "#imports";

import PageHeader from "@/components/PageHeader.vue";
import ToolName from "@/components/ToolName.vue";
import { hub, type AppSummary, type AuditRow } from "@/services/hub";
import { useSession } from "@/stores/session";
import { useToast } from "@/stores/toast";
import { actionLabel, badgeClass, dateTime, errorMessage, resultTone, timeAgo } from "@/utils/format";

const route = useRoute();
const session = useSession();
const toast = useToast();
const rows = ref<AuditRow[]>([]);
const apps = ref<AppSummary[]>([]);
// The log stores ids only; names are resolved here for people allowed to see them.
const names = ref<Record<string, string>>({});

function actor(ref_: string): { kind: string; name: string } {
  const [kind, id] = ref_.split(":", 2);
  const label = { admin: "Admin", service: "Client key", anonymous: "Anonymous", system: "System" }[kind] ?? kind;
  return { kind: label, name: names.value[ref_] ?? (id ? `${id.slice(0, 8)}…` : "") };
}
const filters = ref({ kind: "", app_key: "", result: "", period: "7d", search: String(route.query.trace_id ?? route.query.search ?? "") });
const more = ref(false);
const loading = ref(false);
const PAGE = 50;

function query(before?: string) {
  const params = new URLSearchParams({ limit: String(PAGE) });
  const { kind, app_key, result, period, search } = filters.value;
  if (kind) params.set("kind", kind);
  if (app_key) params.set("app_key", app_key);
  if (result) params.set("result", result);
  if (period) params.set("period", period);
  if (search.startsWith("tr_")) params.set("trace_id", search.trim());
  else if (search) params.set("tool_key", search.trim());
  if (before) params.set("before", before);
  return params;
}

async function load(append = false) {
  loading.value = true;
  try {
    const page = await hub.activity(query(append ? rows.value[rows.value.length - 1]?.created_at : undefined));
    rows.value = append ? [...rows.value, ...page] : page;
    more.value = page.length === PAGE;
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  void load();
  try {
    apps.value = await hub.apps();
    const keys = await hub.keys();
    const users = session.isSuper ? await hub.users() : [];
    names.value = Object.fromEntries([
      ...keys.map((key) => [`service:${key.id}`, key.name]),
      ...users.map((user) => [`admin:${user.id}`, user.email]),
      ...(session.user ? [[`admin:${session.user.id}`, session.user.email]] : []),
    ]);
  } catch { /* filters and names are a convenience */ }
});
watch(() => [filters.value.kind, filters.value.app_key, filters.value.result, filters.value.period], () => load());
</script>

<template>
  <PageHeader title="Activity" subtitle="Every tool call and admin change, with outcome and timing. Request bodies, results and secrets are never stored." />

  <form class="card card-pad mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5" @submit.prevent="load()">
    <label class="lg:col-span-2"><span class="label">Search</span>
      <span class="relative block"><AppIcon name="search" :size="14" class="pointer-events-none absolute left-2.5 top-2.5 text-subtle" />
        <input v-model="filters.search" class="input pl-8" placeholder="Tool name or trace id (tr_…)" /></span></label>
    <label><span class="label">Type</span>
      <select v-model="filters.kind" class="input"><option value="">Everything</option><option value="calls">Tool calls</option><option value="admin">Admin changes</option></select></label>
    <label><span class="label">App</span>
      <select v-model="filters.app_key" class="input"><option value="">All apps</option>
        <option v-for="app in apps" :key="app.id" :value="app.app_key">{{ app.name }}</option></select></label>
    <label><span class="label">Result · period</span>
      <span class="flex gap-2">
        <select v-model="filters.result" class="input"><option value="">Any</option><option value="success">Success</option><option value="denied">Denied</option><option value="error">Error</option></select>
        <select v-model="filters.period" class="input w-24"><option value="24h">24h</option><option value="7d">7d</option><option value="30d">30d</option></select>
      </span></label>
  </form>

  <div class="card overflow-x-auto">
    <table class="tbl">
      <thead><tr><th>When</th><th>Event</th><th>App</th><th>Actor</th><th>Result</th><th>Time</th><th>Trace</th></tr></thead>
      <tbody>
        <tr v-for="row in rows" :key="row.trace_id + row.created_at + row.action">
          <td class="whitespace-nowrap text-xs" :title="dateTime(row.created_at)">{{ timeAgo(row.created_at) }}</td>
          <td class="max-w-[22rem]">
            <template v-if="row.tool"><p class="mb-1 text-xs text-subtle">{{ actionLabel(row.action) }}</p><ToolName :card="row.tool" size="sm" /></template>
            <template v-else><p class="text-sm">{{ actionLabel(row.action) }}</p><p v-if="row.tool_key" class="font-mono text-xs text-subtle">{{ row.tool_key }}</p></template>
          </td>
          <td class="text-xs">{{ row.app_key ?? "—" }}</td>
          <td class="max-w-[12rem] text-xs" :title="row.actor_ref">
            <p class="truncate">{{ actor(row.actor_ref).name }}</p><p class="text-subtle">{{ actor(row.actor_ref).kind }}</p></td>
          <td><span :class="badgeClass(resultTone(row.result))">{{ row.result }}</span>
            <p v-if="row.error_code" class="mt-1 text-xs text-subtle">{{ row.error_code }}</p></td>
          <td class="whitespace-nowrap text-xs text-subtle">{{ row.duration_ms ?? 0 }} ms<template v-if="row.retry_count"> · {{ row.retry_count }} retry</template></td>
          <td class="font-mono text-xs"><span class="inline-flex items-center gap-1">{{ row.trace_id.slice(0, 12) }}…
            <button type="button" class="text-subtle hover:text-ink" title="Show only this trace" @click="filters.search = row.trace_id; load()"><AppIcon name="search" :size="12" /></button></span></td>
        </tr>
        <tr v-if="!rows.length && !loading"><td colspan="7" class="py-10 text-center text-subtle">No activity for these filters.</td></tr>
      </tbody>
    </table>
  </div>
  <div v-if="more" class="mt-4 text-center"><button class="btn-secondary" type="button" :disabled="loading" @click="load(true)">Load more</button></div>
</template>
