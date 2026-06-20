import { describe, expect, it } from "vitest";

import type {
  SourceInboxProfile,
  SourceInboxResponse,
  SourceInboxSentItem,
  SourceInboxThread,
} from "@/lib/api-types";
import { sourceInboxDebugNote, sourceInboxProfileStatusForLabel } from "../LeadsDesignShell";
import { matchesLeadsSourceFilter, nextDraftQueueSelection } from "../components/action-queue-helpers";
import { mapLeadsPipeline, mapLeadsSent } from "../compute-leads-data";

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

describe("leads source filters", () => {
  it("matches live source ids before demo labels", () => {
    expect(matchesLeadsSourceFilter({ sourceId: "crm", source: "Real CRM" }, "crm")).toBe(true);
    expect(matchesLeadsSourceFilter({ sourceId: "apple-messages", source: "SMS" }, "crm")).toBe(false);
    expect(matchesLeadsSourceFilter({ source: "Lofty CRM" }, "lofty")).toBe(true);
    expect(matchesLeadsSourceFilter({ source: "Composio · instagram" }, "composio-insta")).toBe(true);
  });
});

describe("leads approve queue selection", () => {
  it("selects every filtered draft instead of only the visible page", () => {
    const drafts = Array.from({ length: 25 }, (_, i) => ({ id: `draft-${i}` }));
    const next = nextDraftQueueSelection(new Set<string>(), drafts);

    expect(next.size).toBe(25);
    expect(next.has("draft-0")).toBe(true);
    expect(next.has("draft-24")).toBe(true);
  });

  it("toggles only the active filtered draft set", () => {
    const current = new Set(["draft-0", "draft-1", "other"]);
    const next = nextDraftQueueSelection(current, [{ id: "draft-0" }, { id: "draft-1" }]);

    expect(Array.from(next).sort()).toEqual(["other"]);
  });
});

describe("leads sent messages", () => {
  it("uses updatedAt for the visible approved/sent age", () => {
    const updatedAt = new Date(Date.now() + 1000).toISOString();
    const rows: SourceInboxSentItem[] = [{
      id: "send-1",
      idempotencyKey: "idem-1",
      sourceId: "email",
      threadId: "thread-1",
      taskId: "task-1",
      channel: "sms",
      status: "sent",
      attempts: 1,
      createdAt: "2000-01-01T00:00:00+00:00",
      updatedAt,
      payload: { draft_text: "Hi", recipient: { person_name: "Ava" } },
    }];

    expect(mapLeadsSent(rows)[0].when).toBe("now");
  });
});

describe("leads pipeline sections", () => {
  it("keeps all skipped drafts for the skipped tab show-all control", () => {
    const skipped = Array.from({ length: 25 }, (_, i) => ({
      id: `skipped-${i}`,
      sourceId: "email",
      sourceLabel: "Email",
      taskId: `task-${i}`,
      threadId: `thread-${i}`,
      personName: `Lead ${i}`,
      channel: "sms",
      latestAt: "2026-06-19T10:00:00+00:00",
      latestText: "",
      draftText: "",
      context: "",
      title: "",
      status: "skipped",
    }));

    expect(mapLeadsPipeline([], skipped, []).skipped).toHaveLength(25);
  });

  it("sorts skipped drafts newest-first using skippedAt before falling back to latestAt", () => {
    const skipped = [
      {
        id: "older",
        sourceId: "email",
        sourceLabel: "Email",
        taskId: "task-older",
        threadId: "thread-older",
        personName: "Older Lead",
        channel: "sms",
        latestAt: "2026-06-19T10:00:00+00:00",
        skippedAt: "2026-06-19T10:00:00+00:00",
        latestText: "",
        draftText: "",
        context: "",
        title: "",
        status: "skipped",
      },
      {
        id: "newest",
        sourceId: "email",
        sourceLabel: "Email",
        taskId: "task-newest",
        threadId: "thread-newest",
        personName: "Newest Lead",
        channel: "sms",
        latestAt: "2026-06-19T09:00:00+00:00",
        skippedAt: "2026-06-20T10:00:00+00:00",
        latestText: "",
        draftText: "",
        context: "",
        title: "",
        status: "skipped",
      },
      {
        id: "middle-fallback",
        sourceId: "email",
        sourceLabel: "Email",
        taskId: "task-middle",
        threadId: "thread-middle",
        personName: "Middle Lead",
        channel: "sms",
        latestAt: "2026-06-20T09:00:00+00:00",
        latestText: "",
        draftText: "",
        context: "",
        title: "",
        status: "skipped",
      },
    ];

    expect(mapLeadsPipeline([], skipped, []).skipped.map((entry) => entry.id)).toEqual([
      "newest",
      "middle-fallback",
      "older",
    ]);
  });

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
