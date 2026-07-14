import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const page = readFileSync(new URL("../index.tsx", import.meta.url), "utf8");

describe("reporting interaction truth", () => {
  it("keeps refresh live and the unsupported goals control explicitly disabled", () => {
    expect(page).toContain("onRefresh: refreshAll");
    expect(page).toContain('onClick={() => void refreshAll()}');
    expect(page).toContain("await refreshReporting()");
    expect(page).not.toContain("refreshHub");
    expect(page).not.toContain("Promise.all([refreshReporting()");
    expect(page).toContain('<button type="button" disabled aria-describedby="report-goals-reason">');
    expect(page.match(/<button\b/g)).toHaveLength(2);
  });

  it("does not ship the handoff's fake reporting totals or a dead range control", () => {
    for (const mockValue of [">34<", ">48<", ">512<", ">256<", ">8.4%<", "value: 1240"]) {
      expect(page).not.toContain(mockValue);
    }
    expect(page).not.toContain('className="range"');
    expect(page).toContain("Sample values from the design handoff are intentionally excluded");
  });

  it("describes send rows without claiming recipient delivery", () => {
    expect(page).toContain("recorded send rows");
    expect(page).toContain("Recorded source data only");
    expect(page).not.toMatch(/\bconfirmed\b/i);
    expect(page).not.toMatch(/\bdelivered\b/i);
  });
});
