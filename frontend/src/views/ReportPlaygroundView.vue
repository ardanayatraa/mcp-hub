<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import CodeBlock from "@/components/CodeBlock.vue";
import PageHeader from "@/components/PageHeader.vue";
import ReportBuilder from "@/components/ReportBuilder.vue";
import ResultView from "@/components/ResultView.vue";
import { hub, type AppSummary, type DataSource, type ReportSpec, type TestResult } from "@/services/hub";
import { useToast } from "@/stores/toast";
import { errorMessage } from "@/utils/format";
import { reportFields } from "@/utils/sources";

const router = useRouter();
const toast = useToast();
const apps = ref<AppSummary[]>([]);
const sources = ref<DataSource[]>([]);
const connectorId = ref("");
const moduleKey = ref("");
const spec = ref<ReportSpec>({});
const mode = ref<"sample" | "live">("sample");
const delegation = ref("");
const result = ref<TestResult | null>(null);
const busy = ref(false);
const builderKey = ref(0);

onMounted(async () => {
  try {
    [apps.value, sources.value] = await Promise.all([hub.apps(), hub.sources()]);
    apps.value = apps.value.filter((app) => app.status !== "archived");
    if (apps.value.length === 1) connectorId.value = apps.value[0].id;
  } catch (exc) {
    toast.error(errorMessage(exc));
  }
});

const appSources = computed(() => sources.value.filter((source) => source.connector_id === connectorId.value && source.report_endpoint_effective));
const source = computed(() => appSources.value.find((item) => item.module_key === moduleKey.value));
const argumentsJson = computed(() => JSON.stringify({ source: moduleKey.value, ...spec.value }, null, 2));
watch(connectorId, () => { moduleKey.value = appSources.value[0]?.module_key ?? ""; });
watch(moduleKey, () => { builderKey.value += 1; result.value = null; });

async function run() {
  busy.value = true;
  result.value = null;
  try {
    result.value = await hub.testBuiltin("run_report", {
      connector_id: connectorId.value, mode: mode.value, arguments: { source: moduleKey.value, ...spec.value },
      ...(mode.value === "live" && delegation.value ? { delegation: delegation.value } : {}),
    });
  } catch (exc) {
    toast.error(errorMessage(exc));
  } finally {
    busy.value = false;
  }
}

function saveAsTool() {
  void router.push({ path: "/tools/new", query: { template: "report", connector: connectorId.value, module: moduleKey.value } });
}
</script>

<template>
  <PageHeader title="Report playground" back="/tools"
              subtitle="Try the built-in run_report tool the way an AI client would. Pick a data source, describe the report, and preview the answer." />

  <div class="grid gap-6 xl:grid-cols-5">
    <section class="card card-pad min-w-0 space-y-5 xl:col-span-2">
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
        <label><span class="label">App</span>
          <select v-model="connectorId" class="input"><option value="" disabled>Choose an app</option>
            <option v-for="app in apps" :key="app.id" :value="app.id">{{ app.name }} · {{ app.environment }}</option></select></label>
        <label><span class="label">Data source</span>
          <select v-model="moduleKey" class="input" :disabled="!connectorId">
            <option v-for="item in appSources" :key="item.id" :value="item.module_key">{{ item.name }}{{ item.enabled ? "" : " (off for AI)" }}</option></select></label>
      </div>
      <p v-if="connectorId && !appSources.length" class="text-sm text-subtle">This app has no data source with a list route.</p>
      <ReportBuilder v-if="source" :key="builderKey" v-model="spec" :fields="reportFields(source)" />
    </section>

    <section class="min-w-0 space-y-6 xl:col-span-3">
      <div class="card card-pad space-y-4">
        <div class="flex flex-wrap items-center gap-3">
          <div class="flex rounded-lg border border-line p-0.5" role="group" aria-label="Data">
            <button v-for="option in ['sample', 'live']" :key="option" type="button" class="rounded-md px-3 py-1.5 text-xs font-medium"
                    :class="mode === option ? 'bg-brand-soft text-brand' : 'text-subtle'" @click="mode = option as 'sample' | 'live'">
              {{ option === "sample" ? "Sample data" : "Live data" }}</button>
          </div>
          <button class="btn-primary" type="button" :disabled="busy || !source" @click="run"><AppIcon name="play" :size="16" /> Run report</button>
          <button class="btn-secondary ml-auto" type="button" :disabled="!source" @click="saveAsTool"><AppIcon name="plus" :size="16" /> Save as tool</button>
        </div>
        <label v-if="mode === 'live' && source?.endpoints.find((item) => item.key === source?.report_endpoint_effective)?.requires_user_context" class="block">
          <span class="label">Delegation token from the app</span>
          <input v-model="delegation" class="input font-mono text-xs" type="password" autocomplete="off" />
          <span class="hint">This data source is user-scoped. Live previews need a short-lived token the app signs for a user.</span>
        </label>
        <template v-if="result">
          <p v-if="!result.passed" class="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{{ result.error_code }}: {{ result.error_message }}</p>
          <ResultView v-if="result.preview" :result="result.preview" />
        </template>
        <p v-else class="text-sm text-subtle">Run the report to see the summary, totals and rows an AI client would receive.</p>
      </div>
      <div class="card card-pad">
        <h2 class="section-title mb-1">run_report arguments</h2>
        <p class="mb-3 text-xs text-subtle">What an AI client sends for this report. Useful for prompts and app gateways.</p>
        <CodeBlock :code="argumentsJson" max-height="16rem" />
      </div>
    </section>
  </div>
</template>
