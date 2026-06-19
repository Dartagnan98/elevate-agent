import { describe, expect, it } from "vitest";

import type { SourceInboxResponse } from "@/lib/api-types";
import { loadedListOrUndefined, sourceInboxDebugNote, sourceInboxProfileStatusForLabel } from "../LeadsDesignShell";
import { matchesLeadsSourceFilter } from "../components/leads-board";

type SourceInboxDebugCounts = NonNullable<SourceInboxResponse["debug"]>["counts"];

function inbox(counts: Partial<SourceInboxDebugCounts>, fallback = false): SourceInboxResponse {
  return {
    toolsRoot: "/tmp/tools",
    toolsRootSource: "test",
    toolsRootIo: "local",
    sourceRoot: "/tmp/source",
    limit: 10,
    recordCounts: {},
    hiddenCounts: {},
    sources: [],
    profiles: [],
    threads: [],
    drafts: [],
    debug: {
      readPath: fallback ? "jsonl" : "db",
      fallback,
      fallbackError: fallback ? "db offline" : undefined,
      counts: {
        sources: 0,
        profiles: 0,
        threads: 0,
        drafts: 0,
        skippedDrafts: 0,
        privateSearchBuyers: 0,
        recordCounts: {},
        hiddenCounts: {},
        ...counts,
      },
    },
  };
}

describe("source inbox debug note", () => {
  it("stays quiet for healthy non-empty reads", () => {
    expect(sourceInboxDebugNote(inbox({ threads: 1 }))).toBeNull();
  });

  it("surfaces the read path and empty counts", () => {
    expect(sourceInboxDebugNote(inbox({}))).toBe(
      "Source inbox read: db | 0 threads | 0 drafts | 0 profiles | 0 skipped | 0 private buyers",
    );
  });

  it("surfaces fallback errors even when fallback returns data", () => {
    expect(sourceInboxDebugNote(inbox({ threads: 1 }, true))).toBe(
      "Source inbox read: jsonl | 1 threads | 0 drafts | 0 profiles | 0 skipped | 0 private buyers | fallback: db offline",
    );
  });
});

describe("source inbox profile status labels", () => {
  it("maps profile menu labels to persisted source inbox statuses", () => {
    expect(sourceInboxProfileStatusForLabel("No status")).toBeNull();
    expect(sourceInboxProfileStatusForLabel("New Lead")).toBe("new_lead");
    expect(sourceInboxProfileStatusForLabel("Follow up")).toBe("follow_up");
    expect(sourceInboxProfileStatusForLabel("Closed Seller")).toBe("closed_seller");
    expect(sourceInboxProfileStatusForLabel("not a menu item")).toBeUndefined();
  });
});

describe("source inbox live data props", () => {
  it("passes loaded empty arrays through instead of falling back to demo rows", () => {
    expect(loadedListOrUndefined([])).toEqual([]);
    expect(loadedListOrUndefined(undefined)).toBeUndefined();
  });
});

describe("leads source filters", () => {
  it("matches live source ids before demo labels", () => {
    expect(matchesLeadsSourceFilter({ sourceId: "crm", source: "Real CRM" }, "crm")).toBe(true);
    expect(matchesLeadsSourceFilter({ sourceId: "apple-messages", source: "SMS" }, "crm")).toBe(false);
    expect(matchesLeadsSourceFilter({ source: "Lofty CRM" }, "lofty")).toBe(true);
    expect(matchesLeadsSourceFilter({ source: "Composio · instagram" }, "composio-insta")).toBe(true);
  });
});
