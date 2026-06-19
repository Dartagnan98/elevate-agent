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
});
