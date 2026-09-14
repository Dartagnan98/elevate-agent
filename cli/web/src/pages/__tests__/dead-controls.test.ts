import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as ts from "typescript";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(testDir, "../..");
const scanRoots = ["pages", "components"].map((dir) => path.join(srcRoot, dir));

function walkTsx(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (full.includes(`${path.sep}__tests__${path.sep}`)) return [];
    const st = statSync(full);
    if (st.isDirectory()) return walkTsx(full);
    return full.endsWith(".tsx") ? [full] : [];
  });
}

function lineNumber(source: string, index: number): number {
  return source.slice(0, index).split("\n").length;
}

function relative(file: string): string {
  return path.relative(srcRoot, file);
}

function jsxAttributes(node: ts.JsxOpeningElement): Map<string, string | true> {
  const attrs = new Map<string, string | true>();
  for (const prop of node.attributes.properties) {
    if (ts.isJsxAttribute(prop)) {
      attrs.set(prop.name.getText(), prop.initializer?.getText() ?? true);
    }
  }
  return attrs;
}

function tagName(node: ts.JsxOpeningElement | ts.JsxSelfClosingElement, ast: ts.SourceFile): string {
  return node.tagName.getText(ast);
}

function isButtonLikeTag(name: string): boolean {
  return name === "button" || name === "Button";
}

function isStringLiteralText(value: string | true, text: string): boolean {
  return value === `"${text}"` || value === `'${text}'`;
}

describe("dead control sweep", () => {
  const files = scanRoots.flatMap(walkTsx);

  it("does not ship obvious placeholder links or no-op click handlers", () => {
    const forbidden = [
      { name: "hash href", pattern: /href\s*=\s*["']#["']/g },
      { name: "javascript href", pattern: /href\s*=\s*["']javascript:/gi },
      { name: "empty click handler", pattern: /onClick\s*=\s*\{\s*\(\s*\)\s*=>\s*\{\s*\}\s*\}/g },
      { name: "forced enabled disabled prop", pattern: /disabled\s*=\s*\{\s*false\s*\}/g },
      { name: "blocking browser alert", pattern: /\b(?:window\.)?alert\s*\(/g },
      { name: "blocking browser confirm", pattern: /\b(?:window\.)?confirm\s*\(/g },
      { name: "blocking browser prompt", pattern: /\b(?:window\.)?prompt\s*\(/g },
    ];
    const failures: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      for (const check of forbidden) {
        for (const match of source.matchAll(check.pattern)) {
          failures.push(
            `${relative(file)}:${lineNumber(source, match.index ?? 0)} ${check.name}`,
          );
        }
      }
    }

    expect(failures).toEqual([]);
  });

  it("keeps custom role=button controls keyboard reachable", () => {
    const failures: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      const lines = source.split("\n");
      lines.forEach((line, idx) => {
        if (!line.includes('role="button"')) return;
        const start = Math.max(0, idx - 25);
        const end = Math.min(lines.length, idx + 26);
        const window = lines.slice(start, end).join("\n");
        if (!/onClick\s*=/.test(window)) {
          failures.push(`${relative(file)}:${idx + 1} missing onClick`);
        }
        if (!/onKeyDown\s*=/.test(window)) {
          failures.push(`${relative(file)}:${idx + 1} missing onKeyDown`);
        }
        if (!/tabIndex\s*=\s*\{?0\}?/.test(window)) {
          failures.push(`${relative(file)}:${idx + 1} missing tabIndex=0`);
        }
      });
    }

    expect(failures).toEqual([]);
  });

  it("does not nest button controls inside other button controls", () => {
    const failures: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

      const findNested = (root: ts.JsxElement, parentTag: string) => {
        const visitDescendant = (node: ts.Node) => {
          if (node === root) {
            ts.forEachChild(node, visitDescendant);
            return;
          }
          if (ts.isJsxElement(node) && isButtonLikeTag(tagName(node.openingElement, ast))) {
            failures.push(
              `${relative(file)}:${lineNumber(source, node.getStart(ast))} ${parentTag} contains ${tagName(node.openingElement, ast)}`,
            );
            return;
          }
          if (ts.isJsxSelfClosingElement(node) && isButtonLikeTag(tagName(node, ast))) {
            failures.push(
              `${relative(file)}:${lineNumber(source, node.getStart(ast))} ${parentTag} contains ${tagName(node, ast)}`,
            );
            return;
          }
          ts.forEachChild(node, visitDescendant);
        };
        visitDescendant(root);
      };

      const visit = (node: ts.Node) => {
        if (ts.isJsxElement(node)) {
          const parentTag = tagName(node.openingElement, ast);
          if (isButtonLikeTag(parentTag)) {
            findNested(node, parentTag);
          }
        }
        ts.forEachChild(node, visit);
      };

      visit(ast);
    }

    expect(failures).toEqual([]);
  });

  it("keeps native buttons actionable, disabled, or explicit submit controls", () => {
    const failures: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

      const visit = (node: ts.Node) => {
        if (ts.isJsxElement(node) && node.openingElement.tagName.getText(ast) === "button") {
          const attrs = jsxAttributes(node.openingElement);
          const hasAction = [...attrs.keys()].some((name) =>
            /^on(Click|MouseDown|PointerDown|KeyDown|Submit)$/.test(name),
          );
          const isSubmit = attrs.get("type") === '"submit"' || attrs.get("type") === "'submit'";
          if (!hasAction && !attrs.has("disabled") && !isSubmit) {
            failures.push(`${relative(file)}:${lineNumber(source, node.getStart(ast))}`);
          }
        }
        ts.forEachChild(node, visit);
      };

      visit(ast);
    }

    expect(failures).toEqual([]);
  });

  it("keeps new tabs isolated from the opener", () => {
    const failures: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, "utf8");
      const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

      const visit = (node: ts.Node) => {
        if (ts.isCallExpression(node) && node.expression.getText(ast) === "window.open") {
          const featureArg = node.arguments[2]?.getText(ast) ?? "";
          if (node.arguments.length < 3 || !featureArg.includes("noopener")) {
            failures.push(`${relative(file)}:${lineNumber(source, node.getStart(ast))} window.open`);
          }
        }

        if (ts.isJsxElement(node) && node.openingElement.tagName.getText(ast) === "a") {
          const attrs = jsxAttributes(node.openingElement);
          const target = attrs.get("target");
          const rel = attrs.get("rel");
          if (target && isStringLiteralText(target, "_blank")) {
            const relText = typeof rel === "string" ? rel : "";
            if (!relText.includes("noopener") && !relText.includes("noreferrer")) {
              failures.push(`${relative(file)}:${lineNumber(source, node.getStart(ast))} target=_blank`);
            }
          }
        }

        ts.forEachChild(node, visit);
      };

      visit(ast);
    }

    expect(failures).toEqual([]);
  });

  it("keeps disabled Agent Hub gateway controls explained", () => {
    const source = readFileSync(path.join(srcRoot, "pages/AgentHubPage.tsx"), "utf8");

    expect(source).toContain('title={snapshot.gateway.running ? "Gateway is already online." : busyAction !== null ? "Gateway action in progress." : undefined}');
    expect(source).toContain('title={busyAction !== null ? "Gateway action in progress." : undefined}');
  });
});
