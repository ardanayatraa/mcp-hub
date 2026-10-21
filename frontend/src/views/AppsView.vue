<script setup lang="ts">
import { computed, ref } from "vue";

import DeleteAppDialog from "@/components/DeleteAppDialog.vue";
import EmptyState from "@/components/EmptyState.vue";
import LoadingSkeleton from "@/components/LoadingSkeleton.vue";
import PageHeader from "@/components/PageHeader.vue";
import { hub, type AppSummary } from "@/services/hub";
import { useSession } from "@/stores/session";
import { appStatus, badgeClass, errorMessage, timeAgo } from "@/utils/format";
import { useSlowFlag } from "@/utils/loading";
import { useCatalogRefresh } from "@/utils/sources";

const session = useSession();
const apps = ref<AppSummary[]>([]);
const loaded = ref(false);
const error = ref("");
const showArchived = ref(false);
const deleting = ref<AppSummary | null>(null);
const visible = computed(() => apps.value.filter((app) => showArchived.value || app.status !== "archived"));
const archivedCount = computed(() => apps.value.filter((app) => app.status === "archived").length);
// The list asks apps that manage their own permissions for their current catalog, which can be slow.
const slow = useSlowFlag(computed(() => !loaded.value));

async function load() {
  try {
    apps.value = await hub.apps();
    error.value = "";
  } catch (exc) {
    apps.value = [];
    error.value = errorMessage(exc);
  } finally {
    loaded.value = true;
  }
}
useCatalogRefresh(load, () => !deleting.value);

function removed() {
  const id = deleting.value?.id;
  apps.value = apps.value.filter((item) => item.id !== id);
  deleting.value = null;
}

function health(app: AppSummary) {
  if (app.circuit_open) return { tone: "bad", text: "Failing repeatedly" };
  if (!app.health) return { tone: "neutral", text: "Not tested" };
  return app.health.status === "ok"
    ? { tone: "ok", text: `Healthy · ${app.health.latency_ms ?? "?"} ms` }
    : { tone: "bad", text: `Check failed (${app.health.error_category})` };
}
</script>

<template>
  <PageHeader title="Apps" subtitle="Applications connected through the connector contract. Each app owns its data; the Hub only calls routes the app published.">
    <template #actions>
      <RouterLink v-if="session.canWrite" to="/apps/new" class="btn-primary"><AppIcon name="plus" :size="16" /> Connect app</RouterLink>
    </template>
  </PageHeader>

  <p v-if="error" class="mb-4 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ error }}</p>

  <template v-if="!loaded">
    <LoadingSkeleton variant="cards" label="Loading apps" />
    <p v-if="slow" class="mt-4 flex items-center gap-2 text-xs text-subtle">
      <span class="spinner h-3 w-3 text-brand" /> Checking connected apps for their current permissions. A slow app can take a few seconds.
    </p>
  </template>

  <div v-else-if="error" class="text-sm text-subtle">
    The app list is unavailable. <button type="button" class="link" @click="load">Try again</button>
  </div>
  <EmptyState v-else-if="!visible.length" icon="plug" title="No apps connected yet"
              text="Connect an application using its base URL and the bearer token it issued for the Hub.">
    <RouterLink v-if="session.canWrite" to="/apps/new" class="btn-primary">Connect your first app</RouterLink>
  </EmptyState>

  <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
    <article v-for="app in visible" :key="app.id" class="card flex flex-col transition hover:border-brand/40 hover:shadow-pop">
      <RouterLink :to="`/apps/${app.id}`" class="card-pad flex flex-1 flex-col gap-4 rounded-t-xl">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate font-semibold">{{ app.name }}</p>
            <p class="truncate font-mono text-xs text-subtle">{{ app.app_key }} · {{ app.environment }}</p>
          </div>
          <span :class="badgeClass(appStatus[app.status]?.tone ?? 'neutral')">{{ appStatus[app.status]?.label ?? app.status }}</span>
        </div>
        <p class="flex items-center gap-2 text-xs">
          <span class="h-2 w-2 rounded-full" :class="{ ok: 'bg-ok', bad: 'bg-bad', neutral: 'bg-line' }[health(app).tone]" />
          <span class="text-subtle">{{ health(app).text }}</span>
          <span v-if="app.health?.checked_at" class="text-subtle">· {{ timeAgo(app.health.checked_at) }}</span>
        </p>
        <dl class="grid grid-cols-2 gap-2 border-t border-line pt-3 text-xs">
          <div><dt class="text-subtle">Data sources on</dt><dd class="text-base font-semibold">{{ app.source_sync_error ? "—" : app.sources_enabled }}<span v-if="!app.source_sync_error" class="text-xs font-normal text-subtle"> / {{ app.sources_total }}</span></dd></div>
          <div><dt class="text-subtle">Live tools</dt><dd class="text-base font-semibold">{{ app.source_sync_error ? "—" : app.tools_published }}<span v-if="!app.source_sync_error" class="text-xs font-normal text-subtle"> / {{ app.tools_total }}</span></dd></div>
        </dl>
        <p v-if="app.source_sync_error" class="text-xs text-bad">Permissions unavailable. Check connection.</p>
      </RouterLink>
      <footer class="flex items-center gap-1 border-t border-line px-3 py-2">
        <RouterLink :to="`/apps/${app.id}?tab=keys`" class="btn-ghost btn-sm"><AppIcon name="key" :size="14" /> API keys</RouterLink>
        <RouterLink v-if="session.canWrite && app.status !== 'archived'" :to="`/apps/${app.id}?tab=connection`" class="btn-ghost btn-sm">
          <AppIcon name="pencil" :size="14" /> Edit</RouterLink>
        <button v-if="session.canWrite" type="button" class="btn-ghost btn-sm ml-auto text-bad hover:bg-bad-soft hover:text-bad"
                :aria-label="`Delete ${app.name}`" @click="deleting = app"><AppIcon name="trash" :size="14" /> Delete</button>
      </footer>
    </article>
  </div>

  <button v-if="archivedCount" type="button" class="btn-ghost btn-sm mt-4" @click="showArchived = !showArchived">
    {{ showArchived ? "Hide" : "Show" }} {{ archivedCount }} archived
  </button>

  <DeleteAppDialog v-if="deleting" :app="deleting" @close="deleting = null" @deleted="removed" @changed="load" />
</template>
