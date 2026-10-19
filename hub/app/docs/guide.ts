// Shared shape of the in-app guides: one source for the page, its Markdown download and any file kit.
// Inline `code` in prose is rendered as code. Code blocks use String.raw so backslashes survive.

export interface GuideFile {
  path: string;
  lang: string;
  /** "file" is a complete file (kits keep its path); "snippet" is added to an existing file or run once. */
  kind: "file" | "snippet";
  caption?: string;
  code: string;
}

export interface GuideSection {
  id: string;
  title: string;
  step?: number;
  body: string[];
  /** Ordered steps, shown numbered. */
  steps?: string[];
  list?: string[];
  table?: { head: string[]; rows: string[][] };
  /** A drawn figure rendered by the page; `figureText` stands in for it in Markdown and for screen readers. */
  figure?: "hub-flow";
  figureText?: string;
  files?: GuideFile[];
  after?: string[];
}

export interface GuideMeta {
  badge: string;
  title: string;
  summary: string;
  meta: string[];
}

export const MCP_URL_PLACEHOLDER = "https://hub.example.com/mcp";

export function withMcpUrl(code: string, mcpUrl: string): string {
  return mcpUrl ? code.split(MCP_URL_PLACEHOLDER).join(mcpUrl) : code;
}

export function guideMarkdown(guide: GuideMeta, sections: GuideSection[], mcpUrl: string): string {
  const lines = [`# ${guide.title}`, "", guide.summary, "", `_${guide.meta.join(" · ")}_`, ""];
  for (const section of sections) {
    lines.push(`## ${section.step ? `${section.step}. ` : ""}${section.title}`, "");
    for (const paragraph of section.body) lines.push(paragraph, "");
    if (section.figureText) lines.push(`> ${section.figureText}`, "");
    section.steps?.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
    if (section.steps) lines.push("");
    if (section.table) {
      lines.push(`| ${section.table.head.join(" | ")} |`, `|${section.table.head.map(() => "---").join("|")}|`);
      for (const row of section.table.rows) lines.push(`| ${row.map((cell) => cell.replace(/\|/g, "\\|")).join(" | ")} |`);
      lines.push("");
    }
    for (const item of section.list ?? []) lines.push(`- ${item}`);
    if (section.list) lines.push("");
    for (const file of section.files ?? []) {
      lines.push(`**${file.path === "terminal" ? "Terminal" : `\`${file.path}\``}**${file.caption ? `: ${file.caption}` : ""}`, "");
      lines.push("```" + file.lang, withMcpUrl(file.code, mcpUrl), "```", "");
    }
    for (const paragraph of section.after ?? []) lines.push(paragraph, "");
  }
  return lines.join("\n");
}
