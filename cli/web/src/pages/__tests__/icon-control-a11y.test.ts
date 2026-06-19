import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
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

function read(relativePath: string): string {
  return readFileSync(path.join(srcRoot, relativePath), "utf8");
}

function lineNumber(source: string, index: number): number {
  return source.slice(0, index).split("\n").length;
}

function relative(file: string): string {
  return path.relative(srcRoot, file);
}

function windowAround(source: string, marker: string): string {
  const index = source.indexOf(marker);
  expect(index).toBeGreaterThanOrEqual(0);
  return source.slice(Math.max(0, index - 220), index + 420);
}

describe("icon-only control accessibility", () => {
  it.each([
    ["components/ui/modal.tsx", 'aria-label="Close modal"', "Close modal"],
    ["pages/ExperimentsPage.tsx", 'aria-label="Close dialog"', "Close dialog"],
    ["pages/real-estate-hub/admin-task-drawer.tsx", 'aria-label="Close task drawer"', "Close task drawer"],
    ["pages/real-estate-hub/thread-drawer.tsx", 'aria-label="Close thread drawer"', "Close thread drawer"],
    ["pages/real-estate-hub/leads/onboarding.tsx", 'aria-label="Cancel template edit"', "Cancel template edit"],
  ])("%s names critical icon-only close controls", (file, marker, label) => {
    const source = read(file);
    const block = windowAround(source, marker);

    expect(block).toContain(`aria-label="${label}"`);
    expect(block).toContain('aria-hidden="true"');
  });

  it.each([
    ["pages/real-estate-hub/admin/components/sidebar.tsx", 'aria-label="Collapse sidebar"'],
    ["pages/real-estate-hub/admin/components/sidebar.tsx", 'aria-label="Search"'],
    ["pages/ExperimentsPage.tsx", 'aria-label="Remove cycle"'],
    ["pages/real-estate-hub/social/board.tsx", 'aria-label="Refresh queue"'],
    ["pages/ChatPage.tsx", 'aria-label="Edit message"'],
    ["pages/ChatPage.tsx", 'aria-label={pinned ? "Unpin message" : "Pin message"}'],
    ["pages/ChatPage.tsx", 'aria-label="Open message actions"'],
    ["pages/CronPage.tsx", 'aria-label="Clear cron search"'],
    ["pages/SessionsPage.tsx", 'aria-label="Clear session search"'],
    ["pages/SkillsPage.tsx", 'aria-label="Clear skill search"'],
    ["pages/ExperimentsPage.tsx", "aria-label={`Remove goal ${i + 1}`}"],
    ["pages/HeartbeatPage.tsx", 'aria-label="Close heartbeat editor"'],
  ])("%s names additional icon-only controls", (file, marker) => {
    const source = read(file);
    const block = windowAround(source, marker);

    expect(block).toContain(marker);
    expect(block).toContain('aria-hidden="true"');
  });

  it("names both message copy icon buttons", () => {
    const source = read("pages/ChatPage.tsx");

    expect(source.match(/aria-label=\{copied \? "Copied message" : "Copy message"\}/g)).toHaveLength(2);
  });

  it("does not nest the OAuth provider docs link inside a button", () => {
    const source = read("components/OAuthProvidersCard.tsx");
    const docsLink = windowAround(source, "p.docs_url");

    expect(docsLink).toContain("aria-label={`Open ${p.name} docs`}");
    expect(docsLink).not.toMatch(/<a[\\s\\S]*<Button/);
  });

  it("keeps shared modal dialog semantics and focus recovery wired", () => {
    const source = read("components/ui/modal.tsx");

    expect(source).toContain('role="dialog"');
    expect(source).toContain('aria-modal="true"');
    expect(source).toContain("aria-labelledby={titleId}");
    expect(source).toContain("closeRef.current?.focus()");
    expect(source).toContain("prevActive?.focus?.()");
    expect(source).toContain("document.body.style.overflow = \"hidden\"");
  });

  it("keeps dialog surfaces named with explicit modal state", () => {
    const failures: string[] = [];
    const dialogTag = /<[A-Za-z][^>]*role="dialog"[^>]*>/g;

    for (const file of scanRoots.flatMap(walkTsx)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(dialogTag)) {
        const tag = match[0];
        const hasName = /aria-label\s*=|aria-labelledby\s*=/.test(tag);
        const hasModalState = /aria-modal\s*=/.test(tag);
        if (!hasName || !hasModalState) {
          failures.push(`${relative(file)}:${lineNumber(source, match.index ?? 0)}`);
        }
      }
    }

    expect(failures).toEqual([]);
  });

  it("keeps shared Switch controls explicitly named", () => {
    const failures: string[] = [];

    for (const file of scanRoots.flatMap(walkTsx)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/<Switch\b[\s\S]*?\/>/g)) {
        const block = match[0];
        if (!/aria-label\s*=|aria-labelledby\s*=|title\s*=/.test(block)) {
          failures.push(`${relative(file)}:${lineNumber(source, match.index ?? 0)}`);
        }
      }
    }

    expect(failures).toEqual([]);
  });
});
