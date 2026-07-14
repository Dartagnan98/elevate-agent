import { describe, expect, it } from "vitest";
import type {
  AdminDeal,
  SourceInboxResponse,
  SourceInboxSentItem,
  SourceInboxSentResponse,
} from "@/lib/api-types";
import {
  buildReportingSnapshot,
  reportingChannelKind,
  reportingInputsFromFetchResults,
  REPORTING_SEND_LIMIT,
} from "../reporting-data";
import type { ReportingFetchResults } from "../reporting-data";

const NOW = Date.parse("2026-07-13T12:00:00Z");

function sent(
  id: string,
  channel: string,
  updatedAt = "2026-07-12T12:00:00Z",
  status = "sent",
  providerMessageId: string | null = `provider-${id}`,
): SourceInboxSentItem {
  return {
    id,
    idempotencyKey: `idem-${id}`,
    sourceId: "source",
    threadId: `thread-${id}`,
    taskId: `task-${id}`,
    channel,
    status,
    providerMessageId,
    attempts: 1,
    createdAt: updatedAt,
    updatedAt,
    payload: {},
  };
}

function sentResponse(items: SourceInboxSentItem[], limit = REPORTING_SEND_LIMIT): SourceInboxSentResponse {
  return { items, limit, includePending: false };
}

function deal(overrides: Partial<AdminDeal>): AdminDeal {
  return {
    id: "deal",
    title: "Deal",
    side: "listing",
    currentStage: 8,
    status: "closed",
    province: "BC",
    primaryContactId: null,
    loftyContactId: null,
    listingAddress: null,
    extraToggles: {},
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    stageEnteredAt: "2026-01-01T00:00:00Z",
    closedAt: "2026-07-01T00:00:00Z",
    signingAuthority: null,
    fintracFormType: null,
    listingTrack: null,
    propertySubtype: null,
    estateStatus: null,
    transactionType: null,
    listingType: null,
    pep: null,
    tenanted: null,
    poaSigning: null,
    corporate: null,
    hasSuite: null,
    multipleOffers: null,
    familyMember: null,
    dualRep: null,
    unrepresentedOtherSide: null,
    lockbox: null,
    delayedOffer: null,
    saleOfBuyersProperty: null,
    ...overrides,
  };
}

function inbox(): SourceInboxResponse {
  return {
    toolsRoot: "/tmp/tools",
    toolsRootSource: "test",
    toolsRootIo: "local",
    sourceRoot: "/tmp/source",
    limit: 500,
    recordCounts: {},
    hiddenCounts: {},
    sources: [{ id: "crm" }, { id: "messages" }] as SourceInboxResponse["sources"],
    profiles: [{ id: "profile-1" }, { id: "profile-2" }] as SourceInboxResponse["profiles"],
    threads: [{ id: "thread-1" }] as SourceInboxResponse["threads"],
    drafts: [],
  };
}

describe("reporting channel classification", () => {
  it("counts only explicit text and email send channels", () => {
    expect(reportingChannelKind("SMS")).toBe("text");
    expect(reportingChannelKind("Apple_Messages")).toBe("text");
    expect(reportingChannelKind("gmail")).toBe("email");
    expect(reportingChannelKind("instagram")).toBe("other");
    expect(reportingChannelKind("whatsapp")).toBe("other");
  });
});

describe("truthful reporting snapshot", () => {
  it("uses recorded send timestamps and leaves untracked KPIs unavailable", () => {
    const sends = sentResponse([
      sent("text-1", "sms"),
      sent("text-2", "imessage"),
      sent("email-1", "email"),
      sent("failed", "sms", "2026-07-12T12:00:00Z", "failed"),
      sent("old", "sms", "2026-05-01T12:00:00Z"),
      sent("boundary", "sms", "2026-06-13T12:00:00Z"),
      sent("future", "sms", "2026-07-14T12:00:00Z"),
      sent("social", "instagram"),
      sent("synthetic", "sms", "2026-07-12T12:00:00Z", "sent", "stub-local-test"),
    ]);

    const snapshot = buildReportingSnapshot({ inbox: inbox(), sends, deals: [] }, NOW);
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));

    expect(metrics.get("texts")).toMatchObject({ value: 3, displayValue: "3", status: "available" });
    expect(metrics.get("emails")).toMatchObject({ value: 1, displayValue: "1", status: "available" });
    for (const id of ["new-leads", "calls", "appointments", "lead-client"] as const) {
      expect(metrics.get(id)).toMatchObject({ value: null, displayValue: "—", status: "unavailable" });
    }
    expect(snapshot.coverage).toMatchObject({ profiles: 2, conversations: 1, sources: 2 });
  });

  it("excludes synthetic provider rows without treating a sent row as delivery proof", () => {
    const sends = sentResponse([
      sent("provider", "sms"),
      sent("no-provider-id", "sms", "2026-07-12T12:00:00Z", "sent", null),
      sent("synthetic-upper", "sms", "2026-07-12T12:00:00Z", "sent", " Stub-LOCAL "),
    ]);

    const snapshot = buildReportingSnapshot({ inbox: null, sends, deals: null }, NOW);
    const textMetric = snapshot.kpis.find((metric) => metric.id === "texts");

    expect(textMetric).toMatchObject({
      label: "Texts recorded",
      value: 2,
      displayValue: "2",
      status: "available",
    });
    expect(textMetric?.note).toContain("not recipient-delivery proof");
  });

  it("marks recorded send totals as lower bounds when the newest-first read is exhausted inside the period", () => {
    const items = Array.from({ length: REPORTING_SEND_LIMIT }, (_, index) =>
      sent(`send-${index}`, index % 2 === 0 ? "sms" : "email"),
    );
    const snapshot = buildReportingSnapshot(
      { inbox: null, sends: sentResponse(items), deals: null },
      NOW,
    );
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));

    expect(metrics.get("texts")).toMatchObject({ value: 250, displayValue: "250+", status: "partial" });
    expect(metrics.get("emails")).toMatchObject({ value: 250, displayValue: "250+", status: "partial" });
  });

  it("uses dated closed deals for source attribution and excludes undated claims", () => {
    const deals = [
      deal({ id: "r1", sourceLabel: "Referral", closedAt: "2026-07-01T00:00:00Z" }),
      deal({ id: "r2", sourceLabel: "Referral", closedAt: "2026-06-01T00:00:00Z" }),
      deal({ id: "web", sourceKey: "Website", closedAt: "2026-02-01T00:00:00Z" }),
      deal({ id: "unknown", sourceLabel: null, sourceKey: null, closedAt: "2026-04-01T00:00:00Z" }),
      deal({ id: "old", sourceLabel: "Old", closedAt: "2025-12-20T00:00:00Z" }),
      deal({ id: "undated", sourceLabel: "Referral", closedAt: null, completedAt: null }),
      deal({
        id: "active",
        status: "active",
        sourceLabel: "Referral",
        closedAt: null,
        completedAt: "2026-07-02T00:00:00Z",
      }),
    ];

    const snapshot = buildReportingSnapshot({ inbox: null, sends: null, deals }, NOW);

    expect(snapshot.closedDealsBySource).toEqual([
      { id: "referral", label: "Referral", value: 2 },
      { id: "source-not-recorded", label: "Source not recorded", value: 1 },
      { id: "website", label: "Website", value: 1 },
    ]);
    expect(snapshot.undatedClosedDeals).toBe(1);
    expect(snapshot.closedDealsByMonth?.map((point) => [point.id, point.value])).toEqual([
      ["2026-02", 1],
      ["2026-03", 0],
      ["2026-04", 1],
      ["2026-05", 0],
      ["2026-06", 1],
      ["2026-07", 1],
    ]);
  });

  it("distinguishes unavailable deal data from a loaded empty deal list", () => {
    expect(buildReportingSnapshot({ inbox: null, sends: null, deals: null }, NOW).closedDealsBySource)
      .toBeNull();
    expect(buildReportingSnapshot({ inbox: null, sends: null, deals: [] }, NOW).closedDealsBySource)
      .toEqual([]);
  });

  it("clears a failed source during a partial refresh instead of presenting stale success", () => {
    const results: ReportingFetchResults = [
      { status: "fulfilled", value: inbox() },
      { status: "rejected", reason: new Error("send source offline") },
      { status: "fulfilled", value: { items: [], count: 0 } },
    ];

    const refreshed = reportingInputsFromFetchResults(results);
    const snapshot = buildReportingSnapshot(refreshed.inputs, NOW);
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));

    expect(refreshed.failures).toEqual(["send history"]);
    expect(refreshed.fulfilledCount).toBe(2);
    expect(refreshed.inputs.sends).toBeNull();
    expect(metrics.get("texts")?.status).toBe("unavailable");
    expect(metrics.get("emails")?.status).toBe("unavailable");
    expect(snapshot.closedDealsBySource).toEqual([]);
  });
});
