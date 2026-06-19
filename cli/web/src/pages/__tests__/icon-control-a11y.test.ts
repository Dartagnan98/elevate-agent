import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(testDir, "../..");

function read(relativePath: string): string {
  return readFileSync(path.join(srcRoot, relativePath), "utf8");
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

  it("does not nest the OAuth provider docs link inside a button", () => {
    const source = read("components/OAuthProvidersCard.tsx");
    const docsLink = windowAround(source, "p.docs_url");

    expect(docsLink).toContain("aria-label={`Open ${p.name} docs`}");
    expect(docsLink).not.toMatch(/<a[\\s\\S]*<Button/);
  });
});
