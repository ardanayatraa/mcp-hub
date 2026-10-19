import { onMounted, onUnmounted } from "vue";

import type { DataSource, Endpoint } from "@/services/hub";

export interface ReportField { name: string; type: string; usage: "visible" | "aggregate"; values: string[] }

const VISIBLE = new Set(["allowed", "allowed_for_ai"]);

/** Keep open catalog pages current without overlapping requests or hidden-tab polling. */
export function useCatalogRefresh(load: (background: boolean) => Promise<void>, enabled = () => true) {
  let pending = false;
  let timer: ReturnType<typeof setInterval> | undefined;
  async function refresh(background = true) {
    if (pending || (background && (document.hidden || !enabled()))) return;
    pending = true;
    try { await load(background); } finally { pending = false; }
  }
  const resume = () => { void refresh(); };
  onMounted(() => {
    void refresh(false);
    timer = setInterval(resume, 10_000);
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
  });
  onUnmounted(() => {
    clearInterval(timer);
    window.removeEventListener("focus", resume);
    document.removeEventListener("visibilitychange", resume);
  });
}

/** Fields a report may use: the report endpoint's outputs that policy shows or totals. */
export function reportFields(source: DataSource | undefined): ReportField[] {
  if (!source) return [];
  const endpoint = source.endpoints.find((item) => item.key === source.report_endpoint_effective);
  const properties = endpoint?.output_schema.items?.properties ?? {};
  return source.fields
    .filter((field) => properties[field.field_path] && (VISIBLE.has(field.classification) || field.classification === "aggregate_only"))
    .map((field) => ({
      name: field.field_path,
      type: field.type ?? "string",
      usage: field.classification === "aggregate_only" ? "aggregate" : "visible",
      values: properties[field.field_path]?.enum ?? [],
    }));
}

export function visibleFieldNames(source: DataSource | undefined): Set<string> {
  return new Set((source?.fields ?? []).filter((field) => VISIBLE.has(field.classification)).map((field) => field.field_path));
}

export function endpointLabel(endpoint: Endpoint): string {
  const params = Object.keys(endpoint.input_schema.properties ?? {});
  return `${endpoint.method} ${endpoint.path_template}` + (params.length ? `  ·  ${params.join(", ")}` : "");
}

export function endpointsFor(source: DataSource | undefined, template: string): Endpoint[] {
  if (!source) return [];
  if (template === "report") return source.endpoints.filter((endpoint) => endpoint.dataset);
  if (template === "read") return source.endpoints.filter((endpoint) => endpoint.kind === "read");
  return source.endpoints.filter((endpoint) => endpoint.kind === "write" && endpoint.operation === template);
}

export function suggestName(source: DataSource, template: string, endpoint?: Endpoint): string {
  if (template === "report") return `${source.module_key}.summary`;
  if (template !== "read") return `${source.module_key}.${template}`;
  const last = endpoint?.path_template.split("/").filter((part) => part && !part.startsWith("{")).pop() ?? "list";
  const action = last === source.module_key ? "list" : last.replace(/[^a-z0-9_]/gi, "_").toLowerCase();
  return `${source.module_key}.${action}`;
}
