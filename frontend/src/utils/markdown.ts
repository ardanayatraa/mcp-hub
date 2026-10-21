/** Markdown blocks used by chat. Rendered as Vue nodes, never as model-supplied HTML. */
export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "code"; text: string }
  | { kind: "quote"; text: string }
  | { kind: "rule" };

function cells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "");
  return trimmed.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function tableColumns(line: string, next: string | undefined): number {
  if (!next || !/(?<!\\)\|/.test(line)) return 0;
  const head = cells(line);
  const rule = cells(next);
  return head.length >= 2 && head.length === rule.length && rule.every((cell) => /^:?-{3,}:?$/.test(cell))
    ? head.length : 0;
}

const listLine = /^\s*(?:[-*+]\s+|\d+[.)]\s+)/;
const headingLine = /^\s*#{1,4}\s+/;
const fenceLine = /^\s*(`{3,}|~{3,})/;

function startsBlock(lines: string[], index: number): boolean {
  const line = lines[index];
  return headingLine.test(line) || listLine.test(line) || fenceLine.test(line)
    || /^\s*>/.test(line) || /^\s*(?:-{3,}|\*{3,})\s*$/.test(line)
    || tableColumns(line, lines[index + 1]) > 0;
}

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
    } else if (fenceLine.test(line)) {
      const fence = line.match(fenceLine)?.[1] ?? "```";
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith(fence)) body.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push({ kind: "code", text: body.join("\n") });
    } else if (tableColumns(line, lines[index + 1])) {
      const head = cells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim() && /(?<!\\)\|/.test(lines[index])) {
        const row = cells(lines[index++]);
        rows.push(head.map((_, column) => column === head.length - 1
          ? row.slice(column).join(" | ") : (row[column] ?? "")));
      }
      blocks.push({ kind: "table", head, rows });
    } else if (headingLine.test(line)) {
      const match = line.match(/^\s*(#{1,4})\s+(.*)$/);
      blocks.push({ kind: "heading", level: match?.[1].length ?? 1, text: match?.[2].trim() ?? line.trim() });
      index += 1;
    } else if (/^\s*(?:-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push({ kind: "rule" });
      index += 1;
    } else if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) body.push(lines[index++].replace(/^\s*>\s?/, ""));
      blocks.push({ kind: "quote", text: body.join(" ") });
    } else if (listLine.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (index < lines.length && listLine.test(lines[index]) && /^\s*\d/.test(lines[index]) === ordered) {
        items.push(lines[index++].replace(listLine, "").trim());
      }
      blocks.push({ kind: "list", ordered, items });
    } else {
      const body: string[] = [];
      while (index < lines.length && lines[index].trim() && (index === 0 || !startsBlock(lines, index))) {
        body.push(lines[index++].trim());
      }
      if (!body.length) body.push(lines[index++].trim());
      blocks.push({ kind: "paragraph", text: body.join(" ") });
    }
  }
  return blocks;
}
