import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const pagesRoot = path.resolve(testDir, "..");

function readPage(relativePath: string): string {
  return readFileSync(path.resolve(pagesRoot, relativePath), "utf8");
}

describe("large data page guards", () => {
  it("keeps logs bounded by the selected line-count contract", () => {
    const text = readPage("LogsPage.tsx");

    expect(text).toContain("const LINE_COUNTS = [50, 100, 200, 500] as const;");
    expect(text).toMatch(/api\s*\.\s*getLogs\(\{\s*file,\s*lines:\s*lineCount,\s*level,\s*component\s*\}\)/);
  });

  it("caps task rendering for large kanban and list datasets", () => {
    const text = readPage("TasksPage.tsx");

    expect(text).toContain("const TASK_COLUMN_RENDER_LIMIT = 80;");
    expect(text).toContain("const TASK_LIST_RENDER_LIMIT = 300;");
    expect(text).toContain("column.tasks.slice(0, TASK_COLUMN_RENDER_LIMIT)");
    expect(text).toContain("sorted.slice(0, TASK_LIST_RENDER_LIMIT)");
    expect(text).toContain("Showing first {TASK_COLUMN_RENDER_LIMIT} of {column.tasks.length}");
    expect(text).toContain("Showing first {TASK_LIST_RENDER_LIMIT} of {sorted.length}");
  });

  it("keeps real estate boards bounded on large local datasets", () => {
    const leadsQueue = readPage("real-estate-hub/leads/components/action-queue.tsx");
    const leadsProfiles = readPage("real-estate-hub/leads/components/profiles-list.tsx");
    const admin = readPage("real-estate-hub/admin/components/admin-board.tsx");
    const social = readPage("real-estate-hub/social/board.tsx");

    expect(leadsQueue).toContain("const PAGE = 5;");
    expect(leadsQueue).toContain("const visible = showAll ? activeList : activeList.slice(safePage * PAGE, safePage * PAGE + PAGE);");
    expect(leadsProfiles).toContain("const PROFILE_PAGE = 50;");
    expect(leadsProfiles).toContain("const visibleProfiles = showAll ? filtered : filtered.slice(safePage * PROFILE_PAGE, safePage * PROFILE_PAGE + PROFILE_PAGE);");
    expect(admin).toContain("const PAGE = 3;");
    expect(admin).toContain("const pinnedDeals = deals.filter(d => d.primary);");
    expect(admin).toContain("return [...pinnedDeals].sort((a, b) => score(b) - score(a)).slice(0, 25);");
    expect(admin).toContain("const visible = showAll ? filtered : filtered.slice(safePage * PAGE, safePage * PAGE + PAGE);");
    expect(social).toContain("const SOCIAL_POST_RENDER_LIMIT = 96;");
    expect(social).toContain("const rendered = useMemo(() => visible.slice(0, SOCIAL_POST_RENDER_LIMIT), [visible]);");
    expect(social).toContain("Showing first {SOCIAL_POST_RENDER_LIMIT} of {visible.length}");
  });
});
