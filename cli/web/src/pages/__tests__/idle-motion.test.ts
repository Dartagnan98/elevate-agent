import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(testDir, "..");

function readSource(relativePath: string): string {
  return readFileSync(path.resolve(srcRoot, relativePath), "utf8");
}

describe("production idle motion budget", () => {
  it("keeps the memory graph edge flow static when idle", () => {
    const css = readSource("real-estate-hub/memory/memory.css");

    expect(css).toContain(".memory-constellation-edge-flow { stroke-dasharray: 20 8; }");
    expect(css).toContain(".memory-constellation-edge-flow.memory-constellation-edge-active");
    expect(css).not.toMatch(/\.memory-constellation-edge-flow\s*\{[^}]*animation:[^}]*infinite/);
  });

  it("does not run decorative real-estate pulse loops forever", () => {
    const cssFiles = [
      "real-estate-hub/admin/admin.css",
      "real-estate-hub/leads/leads.css",
      "real-estate-hub/social/social.css",
      "real-estate-hub/today/today.css",
    ];

    for (const file of cssFiles) {
      expect(readSource(file), file).not.toMatch(/animation:\s*ab-pulse[^;]*infinite/);
    }
  });

  it("lets first-run onboarding settle when idle", () => {
    const css = readSource("../index.css");

    expect(css).toContain(".onboarding-aurora-bg");
    expect(css).not.toMatch(/\.onboarding-aurora-bg\s*\{[^}]*animation:[^;]*infinite/);
  });
});
