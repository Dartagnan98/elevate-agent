import { describe, expect, it } from "vitest";
import fs from "node:fs";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("admin deal UI recovery wiring", () => {
  it("keeps fetch failures visible and preserves data during silent refreshes", () => {
    const hook = source("../use-admin-deals.ts");

    expect(hook).toContain('setError(errMsg(e, "Admin deals failed"))');
    expect(hook).toContain("if (!options?.keepData) setDeals([])");
    expect(hook).toContain("await load(undefined, { keepData: options?.silent })");
  });

  it("rolls back optimistic stage moves and surfaces move errors", () => {
    const hook = source("../use-admin-deals.ts");

    expect(hook).toContain("prevStage = d.currentStage");
    expect(hook).toContain("return { ...d, currentStage: toStage }");
    expect(hook).toContain("prevStage !== undefined ? { ...d, currentStage: prevStage } : d");
    expect(hook).toContain('setError(errMsg(e, "Move deal failed"))');
  });

  it("renders visible errors with a refresh path on the admin board", () => {
    const shell = source("../AdminDesignShell.tsx");
    const board = source("../components/admin-board.tsx");

    expect(shell).toContain("const visibleError = error ||");
    expect(shell).toContain("error={visibleError}");
    expect(shell).toContain("onRefresh={() => handleRefresh()}");
    expect(shell).toContain("onMoveDeal={moveDeal}");
    expect(board).toContain("{error ? (");
    expect(board).toContain('role="alert"');
    expect(board).toContain('aria-live="polite"');
    expect(board).toContain("{error}");
    expect(board).toContain('onClick={onRefresh}');
    expect(board).toContain('disabled={loading}');
    expect(board).toContain('loading ? "Retrying..." : "Retry"');
  });
});
