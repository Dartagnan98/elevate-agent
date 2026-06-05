import { useMemo, type ReactNode } from "react";

/**
 * Lightweight markdown renderer for LLM output.
 * Handles: code blocks, inline code, bold, italic, headers, links, lists, horizontal rules.
 * NOT a full CommonMark parser — optimized for typical assistant message patterns.
 *
 * `streaming` renders a blinking caret at the tail of the last block so it
 * appears to hug the final character instead of wrapping onto a new line
 * after a block element (paragraph/list/code/…).
 */
export function Markdown({
  content,
  highlightTerms,
  streaming,
}: {
  content: string;
  highlightTerms?: string[];
  streaming?: boolean;
}) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  const caret = streaming ? <StreamingCaret /> : null;

  return (
    <div className="text-sm text-foreground leading-relaxed space-y-2">
      {blocks.map((block, i) => (
        <Block
          key={i}
          block={block}
          highlightTerms={highlightTerms}
          caret={caret && i === blocks.length - 1 ? caret : null}
        />
      ))}
      {blocks.length === 0 && caret}
    </div>
  );
}

function StreamingCaret() {
  return (
    <span
      aria-hidden
      className="inline-block w-[0.5em] h-[1em] ml-0.5 align-[-0.15em] bg-foreground/50 animate-pulse"
    />
  );
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type BlockNode =
  | { type: "code"; lang: string; content: string }
  | { type: "heading"; level: number; content: string }
  | { type: "hr" }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "paragraph"; content: string };

/** A GFM table delimiter row, e.g. `| --- | :--: |` or `---|---`. */
function isTableDelimiter(line: string): boolean {
  const t = line.trim();
  if (!t.includes("-") || !t.includes("|")) return false;
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$/.test(t);
}

/** Split a `| a | b |` table row into trimmed cells (outer pipes dropped). */
function splitTableRow(line: string): string[] {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => c.trim());
}

/* ------------------------------------------------------------------ */
/*  Block parser                                                       */
/* ------------------------------------------------------------------ */

function parseBlocks(text: string): BlockNode[] {
  const lines = text.split("\n");
  const blocks: BlockNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fenceMatch = line.match(/^```(\w*)/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || "";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", lang, content: codeLines.join("\n") });
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,4})\s+(.+)/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        content: headingMatch[2],
      });
      i++;
      continue;
    }

    // GFM table — a header row of pipe-separated cells followed by a
    // delimiter row. Renders as a real <table> grid instead of literal pipes.
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      isTableDelimiter(lines[i + 1])
    ) {
      const headers = splitTableRow(line);
      i += 2; // consume header + delimiter
      const rows: string[][] = [];
      while (
        i < lines.length &&
        lines[i].includes("|") &&
        lines[i].trim() !== "" &&
        !isTableDelimiter(lines[i])
      ) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Horizontal rule
    if (/^[-*_]{3,}\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: false, items });
      continue;
    }

    // Ordered list
    if (/^\d+[.)]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+[.)]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+[.)]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: true, items });
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph — collect consecutive non-empty, non-special lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].match(/^```/) &&
      !lines[i].match(/^#{1,4}\s/) &&
      !lines[i].match(/^[-*+]\s/) &&
      !lines[i].match(/^\d+[.)]\s/) &&
      !lines[i].match(/^[-*_]{3,}\s*$/)
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", content: paraLines.join("\n") });
    }
  }

  return blocks;
}

/* ------------------------------------------------------------------ */
/*  Block renderer                                                     */
/* ------------------------------------------------------------------ */

function Block({
  block,
  highlightTerms,
  caret,
}: {
  block: BlockNode;
  highlightTerms?: string[];
  caret?: ReactNode;
}) {
  switch (block.type) {
    case "code":
      return (
        <pre className="rounded-md bg-foreground/[0.06] border border-border px-3 py-2.5 text-xs font-mono leading-relaxed overflow-x-auto text-foreground">
          <code className="text-foreground">
            {block.content}
            {caret}
          </code>
        </pre>
      );

    case "heading": {
      const Tag = `h${Math.min(block.level, 4)}` as "h1" | "h2" | "h3" | "h4";
      const sizes: Record<string, string> = {
        h1: "text-base font-bold",
        h2: "text-sm font-bold",
        h3: "text-sm font-semibold",
        h4: "text-sm font-medium",
      };
      return (
        <Tag className={sizes[Tag]}>
          <InlineContent text={block.content} highlightTerms={highlightTerms} />
          {caret}
        </Tag>
      );
    }

    case "hr":
      return (
        <>
          <hr className="border-border" />
          {caret}
        </>
      );

    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      const last = block.items.length - 1;
      return (
        <Tag
          className={`space-y-0.5 ${block.ordered ? "list-decimal" : "list-disc"} pl-5 text-sm`}
        >
          {block.items.map((item, i) => (
            <li key={i}>
              <InlineContent text={item} highlightTerms={highlightTerms} />
              {i === last ? caret : null}
            </li>
          ))}
        </Tag>
      );
    }

    case "table": {
      const cols = Math.max(
        block.headers.length,
        ...block.rows.map((r) => r.length),
      );
      return (
        <div className="my-1 overflow-x-auto rounded-md border border-border">
          <table className="w-full border-collapse text-[0.85em]">
            <thead>
              <tr className="bg-foreground/[0.04]">
                {Array.from({ length: cols }, (_, c) => (
                  <th
                    key={c}
                    className="border-b border-border px-2.5 py-1.5 text-left font-semibold whitespace-nowrap"
                  >
                    <InlineContent
                      text={block.headers[c] ?? ""}
                      highlightTerms={highlightTerms}
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r} className="border-t border-border/60">
                  {Array.from({ length: cols }, (_, c) => (
                    <td
                      key={c}
                      className="px-2.5 py-1.5 align-top border-r border-border/40 last:border-r-0"
                    >
                      <InlineContent
                        text={row[c] ?? ""}
                        highlightTerms={highlightTerms}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {caret}
        </div>
      );
    }

    case "paragraph":
      return (
        <p>
          <InlineContent text={block.content} highlightTerms={highlightTerms} />
          {caret}
        </p>
      );
  }
}

/* ------------------------------------------------------------------ */
/*  Inline parser + renderer                                           */
/* ------------------------------------------------------------------ */

type InlineNode =
  | { type: "text"; content: string }
  | { type: "code"; content: string }
  | { type: "bold"; content: string }
  | { type: "italic"; content: string }
  | { type: "link"; text: string; href: string }
  | { type: "br" };

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  // Pattern priority: code > link > bold > italic > bare URL > line break
  const pattern =
    /(`[^`]+`)|(\[([^\]]+)\]\(([^)]+)\))|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(\bhttps?:\/\/[^\s<>)\]]+)|(\n)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }

    if (match[1]) {
      // Inline code
      nodes.push({ type: "code", content: match[1].slice(1, -1) });
    } else if (match[2]) {
      // [text](url) link
      nodes.push({ type: "link", text: match[3], href: match[4] });
    } else if (match[5]) {
      // **bold**
      nodes.push({ type: "bold", content: match[6] });
    } else if (match[7]) {
      // *italic*
      nodes.push({ type: "italic", content: match[8] });
    } else if (match[9]) {
      // Bare URL
      nodes.push({ type: "link", text: match[9], href: match[9] });
    } else if (match[10]) {
      // Line break within paragraph
      nodes.push({ type: "br" });
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push({ type: "text", content: text.slice(lastIndex) });
  }

  return nodes;
}

function InlineContent({
  text,
  highlightTerms,
}: {
  text: string;
  highlightTerms?: string[];
}) {
  const nodes = useMemo(() => parseInline(text), [text]);

  return (
    <>
      {nodes.map((node, i) => {
        switch (node.type) {
          case "text":
            return (
              <HighlightedText
                key={i}
                text={node.content}
                terms={highlightTerms}
              />
            );
          case "code":
            return (
              <code
                key={i}
                className="rounded-sm bg-foreground/[0.08] px-1.5 py-0.5 text-[0.85em] font-mono text-foreground"
              >
                {node.content}
              </code>
            );
          case "bold":
            return (
              <strong key={i} className="font-semibold">
                <HighlightedText text={node.content} terms={highlightTerms} />
              </strong>
            );
          case "italic":
            return (
              <em key={i}>
                <HighlightedText text={node.content} terms={highlightTerms} />
              </em>
            );
          case "link":
            return (
              <a
                key={i}
                href={node.href}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline underline-offset-2 decoration-primary/30 hover:decoration-primary/60 transition-colors"
              >
                {node.text}
              </a>
            );
          case "br":
            return <br key={i} />;
        }
      })}
    </>
  );
}

/** Highlight search terms within a plain text string. */
function HighlightedText({ text, terms }: { text: string; terms?: string[] }) {
  if (!terms || terms.length === 0) return <>{text}</>;

  // Build a regex that matches any of the search terms (case-insensitive)
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const regex = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(regex);

  return (
    <>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-transparent text-warning underline decoration-warning decoration-2 underline-offset-2 px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
