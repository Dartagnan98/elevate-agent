import { describe, expect, it } from "vitest";

import type { SourceInboxProfile, SourceInboxResponse, SourceInboxThread } from "@/lib/api-types";
import { loadedListOrUndefined, sourceInboxDebugNote, sourceInboxProfileStatusForLabel } from "../LeadsDesignShell";
import { matchesLeadsSourceFilter } from "../components/leads-board";
import { mapLeadsPipeline } from "../compute-leads-data";

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

describe("leads pipeline sections", () => {
  it("uses backend leadSections when hot/follow-up rows are not draft-backed", () => {
    const pipeline = mapLeadsPipeline(
      [],
      [],
      [],
      {
        hot: {
          id: "hot",
          label: "Hot leads",
          source: "test",
          count: 1,
          contactIds: ["contact-1"],
          threadIds: [],
          profileIds: ["profile-1"],
          draftIds: [],
          buyerIds: [],
        },
        follow_up: {
          id: "follow_up",
          label: "Needs follow-up",
          source: "test",
          count: 1,
          contactIds: [],
          threadIds: ["email:thread-2"],
          profileIds: [],
          draftIds: [],
          buyerIds: [],
        },
        buyer_search: {
          id: "buyer_search",
          label: "Buyer searches",
          source: "test",
          count: 3,
          contactIds: [],
          threadIds: [],
          profileIds: [],
          draftIds: [],
          buyerIds: [],
        },
      },
      [
        {
          id: "profile-1",
          displayName: "Ava Buyer",
          contactIds: ["contact-1"],
          threadIds: ["email:thread-1"],
          sourceIds: ["email"],
          latestText: "Back on the saved search",
          latestAt: "2099-01-01T00:00:00+00:00",
        } as SourceInboxProfile,
      ],
      [
        {
          id: "email:thread-2",
          sourceId: "email",
          threadId: "thread-2",
          contactId: "contact-2",
          personName: "Noah Seller",
          latestText: "Can we talk next week?",
          latestAt: "2099-01-01T00:00:00+00:00",
        } as SourceInboxThread,
      ],
    );

    expect(pipeline.hot).toMatchObject([
      { id: "profile:profile-1", name: "Ava Buyer", sourceId: "email", threadId: "thread-1" },
    ]);
    expect(pipeline.followups).toMatchObject([
      { id: "thread:email:thread-2", name: "Noah Seller", sourceId: "email", threadId: "thread-2" },
    ]);
    expect(pipeline.buyers).toBe(3);
  });
});
