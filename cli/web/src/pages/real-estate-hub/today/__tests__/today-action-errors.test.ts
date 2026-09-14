import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const shell = readFileSync(resolve(here, "../TodayDesignShell.tsx"), "utf8");
const board = readFileSync(resolve(here, "../components/today-board.tsx"), "utf8");

describe("today draft action failures", () => {
  it("surfaces failed quick approvals and keeps failed drafts retryable", () => {
    expect(shell).toContain("todayActionError");
    expect(shell).toContain("Could not ${verb} draft");
    expect(shell).toContain("throw err instanceof Error ? err : new Error(detail)");
    expect(shell).toContain("error={todayActionError || todayError}");

    expect(board).toContain('role="alert"');
    expect(board).toContain("Parent surfaces the action error; keep the draft visible for retry.");
    expect(board).toContain("if (action === \"skip\") setSkipped");
  });
});
