import { useCallback, useMemo, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";

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
  onOpenPath,
}: {
  content: string;
  highlightTerms?: string[];
  streaming?: boolean;
  /** Click handler for local file paths detected in the text (Claude-style). */
  onOpenPath?: (path: string) => void;
}) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  const caret = streaming ? <StreamingCaret /> : null;

  // Delegated click — paths render as <span data-md-path> so we don't thread a
  // callback through the whole inline render tree.
  const handleClick = onOpenPath
    ? (e: React.MouseEvent<HTMLDivElement>) => {
        const el = (e.target as HTMLElement).closest("[data-md-path]");
        const path = el?.getAttribute("data-md-path");
        if (path) {
          e.preventDefault();
          onOpenPath(path);
        }
      }
    : undefined;

  return (
    <div
      className="text-sm text-foreground leading-relaxed space-y-2"
      onClick={handleClick}
    >
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

/* ------------------------------------------------------------------ */
/*  Copyable code box                                                  */
/* ------------------------------------------------------------------ */

function copyToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
    return;
  }
  fallbackCopy(text);
}

function fallbackCopy(text: string) {
  if (typeof document === "undefined") return;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "true");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
  } catch {
    /* ignore */
  }
  document.body.removeChild(ta);
}

/**
 * A code box with a hover copy button. `inline` renders a compact box that can
 * sit inside a line (used for collapsed/inline multi-backtick spans); the
 * default is a full-width fenced block.
 */
function CodeBlock({
  content,
  lang,
  caret,
  inline,
}: {
  content: string;
  lang?: string;
  caret?: ReactNode;
  inline?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(() => {
    copyToClipboard(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }, [content]);

  return (
    <div
      className={`group relative ${inline ? "my-0.5 inline-block max-w-full align-top" : "my-1 block"}`}
    >
      <pre
        className={`overflow-x-auto rounded-md border border-[var(--chat-border)] bg-[var(--chat-surface-strong)] py-2.5 pl-3 pr-9 text-xs font-mono leading-relaxed text-[var(--chat-text)] selection:bg-[#5d5d5d] selection:text-white [&_*]:selection:bg-[#5d5d5d] [&_*]:selection:text-white ${inline ? "whitespace-pre-wrap" : ""}`}
      >
        {lang ? (
          <span className="mb-1 block select-none text-[10px] uppercase tracking-wide text-foreground/40">
            {lang}
          </span>
        ) : null}
        <code className="text-foreground">
          {content}
          {caret}
        </code>
      </pre>
      <button
        type="button"
        onClick={onCopy}
        aria-label={copied ? "Copied" : "Copy code"}
        title={copied ? "Copied" : "Copy"}
        className="absolute right-1.5 top-1.5 inline-flex h-6 w-6 items-center justify-center rounded-md border border-border bg-background/60 text-foreground/55 opacity-0 transition-opacity hover:bg-foreground/[0.08] hover:text-foreground group-hover:opacity-100 focus:opacity-100"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-success" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}

/**
 * A compact copyable code box that is valid inside a paragraph (<span>-based,
 * never <div>/<pre>, so it doesn't break <p> nesting). Used for inline commands
 * and collapsed fenced snippets.
 */
function InlineCodeBox({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(() => {
    copyToClipboard(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }, [content]);

  return (
    <span className="my-0.5 inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-foreground/[0.06] py-0.5 pl-2 pr-1 align-middle">
      <span className="overflow-x-auto whitespace-pre font-mono text-[0.85em] text-foreground">
        {content}
      </span>
      <button
        type="button"
        onClick={onCopy}
        aria-label={copied ? "Copied" : "Copy"}
        title={copied ? "Copied" : "Copy"}
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-foreground/50 transition-colors hover:bg-foreground/[0.1] hover:text-foreground"
      >
        {copied ? (
          <Check className="h-3 w-3 text-success" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </button>
    </span>
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

    // Fenced code block — allow leading whitespace so list-nested fences work.
    const fenceMatch = line.match(/^\s*```(\w*)\s*$/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || "";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
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
        <CodeBlock content={block.content} lang={block.lang} caret={caret} />
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
        // overflow-x-auto + a content-sized table (w-max) means columns size to
        // their content instead of squeezing into the chat width and stacking.
        // When the table is wider than the chat column it scrolls left/right;
        // when it's narrower it still fills the width (min-w-full).
        <div className="my-1 max-w-full overflow-x-auto rounded-md border border-border">
          <table className="w-max min-w-full border-collapse">
            <thead>
              <tr className="bg-foreground/[0.04]">
                {Array.from({ length: cols }, (_, c) => (
                  <th
                    key={c}
                    className="whitespace-nowrap border-b border-border px-2.5 py-1.5 text-left font-semibold"
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
                      // Cap each cell so one long value (a pitch, an address)
                      // wraps within a sane column instead of forcing a giant
                      // single line — the whole table still scrolls if needed.
                      className="max-w-[26rem] border-r border-border/40 px-2.5 py-1.5 align-top last:border-r-0"
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
  | { type: "codebox"; content: string }
  | { type: "bold"; content: string }
  | { type: "italic"; content: string }
  | { type: "link"; text: string; href: string }
  | { type: "path"; path: string }
  | { type: "br" };

// A token looks like a local file/dir path (not a date/fraction): has a letter
// and isn't pure digits/slashes/dots.
function looksLikePath(s: string): boolean {
  return /[a-zA-Z]/.test(s) && !/^[\d/.]+$/.test(s);
}

// Language tokens that can prefix a collapsed fenced block (e.g. a
// ```text\nCODE``` whose newline got eaten becomes "```text CODE```").
const KNOWN_LANGS = new Set([
  "text", "plaintext", "txt", "bash", "sh", "shell", "zsh", "console",
  "json", "js", "javascript", "ts", "typescript", "tsx", "jsx", "python",
  "py", "html", "css", "yaml", "yml", "sql", "md", "markdown", "go", "rust",
  "java", "c", "cpp", "diff", "xml", "http", "env", "ini", "toml",
]);

// A `code` span counts as a copyable "command box" when it reads like a shell
// command / multi-token snippet (has whitespace) rather than a bare identifier.
function looksLikeCommand(content: string): boolean {
  return /\s/.test(content.trim()) && content.trim().length >= 4;
}

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  // Pattern priority: fenced/multi-backtick code box > inline code > link >
  // bold > italic > bare URL > line break. The first group greedily captures
  // any run of 1+ backticks so collapsed ```fences``` (whose newlines were
  // eaten) still render as a box instead of leaking stray backticks.
  const pattern =
    /(```+[^`]*?```+|``[^`]+?``|`[^`]+?`)|(\[([^\]]+)\]\(([^)]+)\))|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(\bhttps?:\/\/[^\s<>)\]]+)|((?:\/|~\/|\.{1,2}\/)[\w.@-]+(?:\/[\w.@-]+)*\/?|[\w@.-]+(?:\/[\w@.-]+){2,}\/?|[\w@.-]+\/[\w@.-]*\.[a-zA-Z0-9]{1,8})|(\n)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }

    if (match[1]) {
      const raw = match[1];
      const fence = (raw.match(/^`+/)?.[0].length) ?? 1;
      let inner = raw.slice(fence, raw.length - fence);
      if (fence >= 2) {
        // Collapsed/multi-backtick fence — render as a copyable box. Strip a
        // leading language token if one survived the newline collapse.
        inner = inner.trim();
        const lead = inner.match(/^([a-zA-Z][\w+-]*)\s+([\s\S]+)$/);
        if (lead && KNOWN_LANGS.has(lead[1].toLowerCase())) inner = lead[2];
        nodes.push({ type: "codebox", content: inner });
      } else if (looksLikeCommand(inner)) {
        // Single-backtick command/snippet — give it a copy box too.
        nodes.push({ type: "codebox", content: inner });
      } else {
        nodes.push({ type: "code", content: inner });
      }
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
      // Local file/dir path — clickable when it really looks like a path.
      const p = match[10];
      if (looksLikePath(p)) nodes.push({ type: "path", path: p });
      else nodes.push({ type: "text", content: p });
    } else if (match[11]) {
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
          case "codebox":
            return <InlineCodeBox key={i} content={node.content} />;
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
          case "path":
            return (
              <span
                key={i}
                data-md-path={node.path}
                role="button"
                tabIndex={0}
                title={`Open ${node.path}`}
                className="cursor-pointer rounded bg-primary/5 px-1 font-mono-ui text-[0.92em] text-primary underline decoration-primary/30 underline-offset-2 hover:decoration-primary/70"
              >
                {node.path}
              </span>
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
