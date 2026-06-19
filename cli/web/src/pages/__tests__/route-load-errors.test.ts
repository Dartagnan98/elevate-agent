import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(testDir, "../..");

function read(relativePath: string): string {
  return readFileSync(path.join(srcRoot, relativePath), "utf8");
}

describe("route load error states", () => {
  it("provides a shared visible route load error with retry support", () => {
    const source = read("components/route-skeletons.tsx");

    expect(source).toContain("export function RouteLoadError");
    expect(source).toContain('role="alert"');
    expect(source).toContain("onRetry");
    expect(source).toContain("RefreshCw");
  });

  it.each([
    ["pages/EnvPage.tsx", "varsError", "Could not load environment variables"],
    ["pages/SkillsPage.tsx", "skillsError", "Could not load skills"],
    ["pages/ProjectPage.tsx", "cacheError", "Could not load project"],
    ["pages/SessionsPage.tsx", "pageError", "Could not load sessions"],
    ["pages/HeartbeatPage.tsx", "heartbeatError", "Could not load heartbeats"],
  ])("%s keeps useCachedResource failures visible", (file, errorName, title) => {
    const source = read(file);

    expect(source).toContain("RouteLoadError");
    expect(source).toContain(`error: ${errorName}`);
    expect(source).toContain(title);
    expect(source).toContain("onRetry");
  });
});
