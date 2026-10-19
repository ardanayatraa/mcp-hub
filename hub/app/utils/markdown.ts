/** The small Markdown subset chat answers use, parsed into blocks that render without v-html. */
export type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "code"; text: string };

const cells = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
const isDivider = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
    } else if (line.trim().startsWith("```")) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) body.push(lines[index++]);
      index += 1;
      blocks.push({ kind: "code", text: body.join("\n") });
    } else if (line.trim().startsWith("|") && index + 1 < lines.length && isDivider(lines[index + 1])) {
      const head = cells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) rows.push(cells(lines[index++]));
      blocks.push({ kind: "table", head, rows });
    } else if (/^\s*#{1,4}\s/.test(line)) {
      blocks.push({ kind: "heading", text: line.replace(/^\s*#{1,4}\s+/, "") });
      index += 1;
    } else if (/^\s*([-*]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (index < lines.length && /^\s*([-*]|\d+[.)])\s+/.test(lines[index])) {
        items.push(lines[index++].replace(/^\s*([-*]|\d+[.)])\s+/, ""));
      }
      blocks.push({ kind: "list", ordered, items });
    } else {
      const text: string[] = [];
      while (index < lines.length && lines[index].trim() && !/^\s*([-*]|\d+[.)]|#{1,4})\s/.test(lines[index])
             && !lines[index].trim().startsWith("```") && !lines[index].trim().startsWith("|")) {
        text.push(lines[index++].trim());
      }
      if (!text.length) text.push(lines[index++].trim());
      blocks.push({ kind: "paragraph", text: text.join(" ") });
    }
  }
  return blocks;
}
