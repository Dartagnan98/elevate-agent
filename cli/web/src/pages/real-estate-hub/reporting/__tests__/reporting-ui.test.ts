import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const page = readFileSync(new URL("../index.tsx", import.meta.url), "utf8");
const modal = readFileSync(new URL("../goals-modal.tsx", import.meta.url), "utf8");

describe("reporting interaction truth", () => {
  it("keeps refresh live and wires the goals dialog to the real API", () => {
    expect(page).toContain("onRefresh: refreshAll");
    expect(page).toContain('onClick={() => void refreshAll()}');
    expect(page).toContain("await refreshReporting()");
    expect(page).not.toContain("refreshHub");
    expect(page).not.toContain("Promise.all([refreshReporting()");
    // Goals save goes through the real endpoint and then refetches.
    expect(modal).toContain("api.putCrmGoals");
    expect(page).toContain("onSaved={refreshAll}");
    // Numeric goal inputs cannot go negative.
    expect(modal).toContain('type="number"');
    expect(modal).toContain("min={0}");
  });

  it("ships the date range as a live labelled select wired into the snapshot window", () => {
    // A named <select> whose value drives the reporting hook's window.
    expect(page).toContain('aria-label="Reporting date range"');
    expect(page).toContain("REPORTING_RANGE_OPTIONS.map((days)");
    expect(page).toContain("Last {days} days");
    expect(page).toContain("useReportingData(rangeDays)");
    expect(page).toContain("setRangeDays(");
    // The select is enabled and window text is derived, never hardcoded.
    expect(page).not.toMatch(/className="report-range"\s+disabled/);
    expect(page).not.toContain("Last 30 days");
    // Hitting the send read limit inside the window is called out honestly.
    expect(page).toContain("snapshot.sendWindowTruncated");
    expect(page).toContain("window may be truncated");
    // No fake dropdown affordance and no dead handlers.
    expect(page).not.toContain("window.open");
    expect(page).not.toMatch(/onClick=\{\(\)\s*=>\s*\{\s*\}\}/);
  });

  it("does not ship the handoff's fake reporting totals", () => {
    for (const mockValue of [">34<", ">48<", ">512<", ">256<", ">8.4%<", "value: 1240", "value:1240"]) {
      expect(page).not.toContain(mockValue);
    }
    expect(page).toContain("Sample values from the design handoff are intentionally excluded");
    // Sections without a data source must say so instead of charting samples.
    expect(page).toContain("No spend ledger yet");
    expect(page).toContain("Lead-created timestamps are not recorded yet");
  });

  it("labels default calculator rates instead of passing them off as measured", () => {
    expect(page).toContain("Using industry default rates for");
    expect(page).toContain("math.usesDefaults");
  });

  it("describes send rows without claiming recipient delivery", () => {
    expect(page).toContain("recorded send rows");
    expect(page).toContain("Recorded source data only");
    expect(page).not.toMatch(/\bconfirmed\b/i);
    expect(page).not.toMatch(/\bdelivered\b/i);
  });
});
