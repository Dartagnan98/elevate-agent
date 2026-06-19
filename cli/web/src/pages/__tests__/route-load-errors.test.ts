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

  it("keeps manual log fetch failures visible with retry support", () => {
    const source = read("pages/LogsPage.tsx");

    expect(source).toContain("RouteLoadError");
    expect(source).toContain("Could not load logs");
    expect(source).toContain("onRetry={fetchLogs}");
  });

  it.each([
    ["pages/ActivityPage.tsx", "cacheError", "Could not load activity"],
    ["pages/AnalyticsPage.tsx", "cacheError", "Could not load analytics"],
    ["pages/ApprovalsPage.tsx", "cacheError", "Could not load approvals"],
    ["pages/CommsPage.tsx", "cacheError", "Could not load comms"],
    ["pages/EnvPage.tsx", "varsError", "Could not load environment variables"],
    ["pages/ExperimentsPage.tsx", "cacheError", "Could not load experiments"],
    ["pages/OverviewPage.tsx", "cacheError", "Could not load overview"],
    ["pages/SkillsPage.tsx", "skillsError", "Could not load skills"],
    ["pages/ProjectPage.tsx", "cacheError", "Could not load project"],
    ["pages/SessionsPage.tsx", "pageError", "Could not load sessions"],
    ["pages/HeartbeatPage.tsx", "heartbeatError", "Could not load heartbeats"],
    ["pages/TasksPage.tsx", "cacheError", "Could not load tasks"],
  ])("%s keeps useCachedResource failures visible", (file, errorName, title) => {
    const source = read(file);

    expect(source).toContain("RouteLoadError");
    expect(source).toContain(`error: ${errorName}`);
    expect(source).toContain(title);
    expect(source).toContain("onRetry");
  });
});
