// How each kind of tool looks: an icon, a colour and a short label.
export interface KindStyle { icon: string; tile: string; label: string }

export const TOOL_KINDS: Record<string, KindStyle> = {
  list: { icon: "table", tile: "bg-chart-1/10 text-chart-1", label: "List" },
  count: { icon: "chart", tile: "bg-chart-1/10 text-chart-1", label: "Count" },
  get: { icon: "search", tile: "bg-chart-1/10 text-chart-1", label: "Look up" },
  read: { icon: "eye", tile: "bg-chart-1/10 text-chart-1", label: "Read" },
  report: { icon: "layers", tile: "bg-chart-2/10 text-chart-2", label: "Report" },
  create: { icon: "plus", tile: "bg-ok/10 text-ok", label: "Create" },
  update: { icon: "pencil", tile: "bg-warn/10 text-warn", label: "Update" },
  delete: { icon: "trash", tile: "bg-bad/10 text-bad", label: "Delete" },
  hub: { icon: "bolt", tile: "bg-brand/10 text-brand", label: "Hub tool" },
  memory: { icon: "sparkles", tile: "bg-chart-2/10 text-chart-2", label: "Memory" },
};

export function kindStyle(kind: string | null | undefined): KindStyle {
  return TOOL_KINDS[kind ?? ""] ?? TOOL_KINDS.read;
}

/** The kind of a tool from its template and key, for pages that have the tool itself. */
export function toolKind(template: string, toolKey: string): string {
  if (template === "report") return "report";
  if (["create", "update", "delete"].includes(template)) return template;
  const action = toolKey.split(".").pop() ?? "";
  return ["list", "count", "get"].includes(action) ? action : "read";
}
