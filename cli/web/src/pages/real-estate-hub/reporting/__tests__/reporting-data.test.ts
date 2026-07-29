import { describe, expect, it } from "vitest";
import type {
  AdminDeal,
  SourceInboxProfile,
  SourceInboxResponse,
  SourceInboxSentItem,
  SourceInboxSentResponse,
} from "@/lib/api-types";
import {
  buildActivityMath,
  buildFunnelStages,
  buildGoalProgress,
  buildReportingSnapshot,
  closedDealsInMonth,
  conversionByLeadSource,
  countMarkedNewLeads,
  gciClosedThisYear,
  goalTone,
  reportingChannelKind,
  reportingInputsFromFetchResults,
  resolveFunnelRates,
  salesByYear,
  REPORTING_DEFAULT_RATES,
  REPORTING_SEND_LIMIT,
} from "../reporting-data";
import type { ReportingFetchResults } from "../reporting-data";

const NOW = Date.parse("2026-07-13T12:00:00Z");
const PERIOD_START = NOW - 30 * 24 * 60 * 60 * 1000;

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

function profile(overrides: Partial<SourceInboxProfile>): SourceInboxProfile {
  return {
    id: `profile-${Math.random().toString(36).slice(2, 8)}`,
    displayName: "Person",
    sources: ["crm"],
    sourceIds: ["crm"],
    channels: ["sms"],
    contactIds: [],
    conversationIds: [],
    verifiers: [],
    phones: [],
    emails: [],
    threadIds: [],
    threadCount: 0,
    latestText: "",
    latestAt: "2026-07-10T00:00:00Z",
    heatScore: 0,
    heatLabel: "normal",
    hasCrm: true,
    hasConversation: false,
    isPotentialLead: true,
    crmStage: null,
    leadSource: null,
    tags: [],
    status: null,
    statusUpdatedAt: null,
    ...overrides,
  };
}

function inbox(profiles: SourceInboxProfile[] = []): SourceInboxResponse {
  return {
    toolsRoot: "/tmp/tools",
    toolsRootSource: "test",
    toolsRootIo: "local",
    sourceRoot: "/tmp/source",
    limit: 500,
    recordCounts: {},
    hiddenCounts: {},
    sources: [{ id: "crm" }, { id: "messages" }] as SourceInboxResponse["sources"],
    profiles,
    threads: [{ id: "thread-1" }] as SourceInboxResponse["threads"],
    drafts: [],
  };
}

/** 10 leads: conv 6, clients 2 (pending_deal + closed_buyer), under contract 1, closed 1. */
function funnelProfiles(): SourceInboxProfile[] {
  return [
    profile({ status: "new_lead", hasConversation: true, statusUpdatedAt: "2026-07-01T00:00:00Z", leadSource: "Referral" }),
    profile({ status: "new_lead", statusUpdatedAt: "2026-07-05T00:00:00Z", leadSource: "Referral" }),
    profile({ status: "new_lead", statusUpdatedAt: "2026-05-01T00:00:00Z" }),
    profile({ status: "new_lead" }),
    profile({ status: "attempted_contact", hasConversation: true, leadSource: "Website" }),
    profile({ status: "attempted_contact", hasConversation: true, leadSource: "website " }),
    profile({ status: "prospect", hasConversation: true }),
    profile({ status: "prospect" }),
    profile({ status: "pending_deal", hasConversation: true, leadSource: "Referral" }),
    profile({ status: "closed_buyer", hasConversation: true }),
    // Excluded from the lead universe entirely:
    profile({ status: "realtor_contact", hasConversation: true }),
    profile({ status: "trash" }),
  ];
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

describe("pipeline funnel from profile statuses", () => {
  it("builds funnel stages with kept-% against the nearest measured stage", () => {
    const stages = buildFunnelStages(funnelProfiles());

    expect(stages.map((stage) => [stage.id, stage.value, stage.keptPct])).toEqual([
      ["leads", 10, null],
      ["conversations", 6, 60],
      ["appointments", null, null],
      ["clients", 2, 33],
      ["under-contract", 1, 50],
      ["closed", 1, 100],
    ]);
    expect(stages.find((stage) => stage.id === "appointments")?.note).toBe(
      "No appointment tracking yet",
    );
  });

  it("computes conversion by recorded lead source, case-insensitively", () => {
    const rows = conversionByLeadSource(funnelProfiles());

    expect(rows).toEqual([
      { id: "referral", label: "Referral", leads: 3, clients: 1, pct: 33 },
      { id: "website", label: "Website", leads: 2, clients: 0, pct: 0 },
    ]);
  });

  it("ignores realtor contacts and trash for source conversion", () => {
    const rows = conversionByLeadSource([
      profile({ status: "realtor_contact", leadSource: "Referral" }),
      profile({ status: "trash", leadSource: "Referral" }),
    ]);
    expect(rows).toEqual([]);
  });
});

describe("reverse activity calculator", () => {
  it("uses published defaults when no funnel history exists, and says so", () => {
    const rates = resolveFunnelRates(null);
    for (const rate of Object.values(rates)) expect(rate.source).toBe("default");

    const math = buildActivityMath(3, rates);
    expect(math).toMatchObject({
      closingsGoal: 3,
      clients: 14, // ceil(3 / 0.22)
      appointments: 33, // ceil(13.64 / 0.42)
      conversations: 99, // ceil(32.47 / 0.33)
      leads: 190, // ceil(98.39 / 0.52)
      conversationsPerSale: 33,
      perWeek: 23,
      perDay: 5,
      usesDefaults: true,
    });
    expect(math?.defaultRateIds).toEqual([
      "leadToConversation",
      "conversationToAppointment",
      "appointmentToClient",
      "clientToClose",
    ]);
  });

  it("prefers measured funnel rates and only defaults the untracked steps", () => {
    const rates = resolveFunnelRates(buildFunnelStages(funnelProfiles()));

    expect(rates.leadToConversation).toEqual({ rate: 0.6, source: "measured" });
    expect(rates.clientToClose).toEqual({ rate: 0.5, source: "measured" });
    expect(rates.conversationToAppointment).toEqual({
      rate: REPORTING_DEFAULT_RATES.conversationToAppointment,
      source: "default",
    });
    expect(rates.appointmentToClient).toEqual({
      rate: REPORTING_DEFAULT_RATES.appointmentToClient,
      source: "default",
    });

    const math = buildActivityMath(2, rates);
    expect(math).toMatchObject({
      clients: 4, // ceil(2 / 0.5)
      appointments: 10, // ceil(4 / 0.42)
      conversations: 29, // ceil(9.52 / 0.33)
      leads: 49, // ceil(28.86 / 0.6)
      usesDefaults: true,
    });
    expect(math?.defaultRateIds).toEqual(["conversationToAppointment", "appointmentToClient"]);
  });

  it("returns null without a positive closings goal instead of inventing one", () => {
    const rates = resolveFunnelRates(null);
    expect(buildActivityMath(null, rates)).toBeNull();
    expect(buildActivityMath(0, rates)).toBeNull();
    expect(buildActivityMath(-2, rates)).toBeNull();
  });
});

describe("goal progress", () => {
  it("maps percent thresholds onto good / neutral / warn tones", () => {
    expect(goalTone(100)).toBe("good");
    expect(goalTone(80)).toBe("good");
    expect(goalTone(79)).toBe("neutral");
    expect(goalTone(50)).toBe("neutral");
    expect(goalTone(49)).toBe("warn");
    expect(goalTone(0)).toBe("warn");
  });

  it("builds progress rows from saved goals and real current values", () => {
    const rows = buildGoalProgress(
      { leadsGoal: 40, apptsGoal: 25, closingsGoal: 3, gciGoal: 250000, updatedAt: null },
      { newLeads: 34, appointments: null, closingsThisMonth: 2, gciThisYear: 142000 },
    );

    expect(rows.map((row) => [row.id, row.pct, row.tone])).toEqual([
      ["leads", 85, "good"],
      ["appointments", null, null],
      ["closings", 67, "neutral"],
      ["gci", 57, "neutral"],
    ]);
    expect(rows[3].currentDisplay).toBe("$142k");
    expect(rows[3].goalDisplay).toBe("$250k");
    expect(rows[1].note).toBe("No appointment tracking yet");
  });

  it("leaves progress blank when goals are unset instead of assuming targets", () => {
    const rows = buildGoalProgress(null, {
      newLeads: 12,
      appointments: null,
      closingsThisMonth: 1,
      gciThisYear: 5000,
    });
    for (const row of rows) {
      expect(row.pct).toBeNull();
      expect(row.goalDisplay).toBe("not set");
    }
  });
});

describe("deal-derived metrics", () => {
  it("counts closings only inside the current UTC month", () => {
    const deals = [
      deal({ id: "in", closedAt: "2026-07-01T00:00:00Z" }),
      deal({ id: "boundary-out", closedAt: "2026-06-30T23:59:59Z" }),
      deal({ id: "future", closedAt: "2026-07-14T00:00:00Z" }),
      deal({ id: "open", status: "active", closedAt: "2026-07-02T00:00:00Z" }),
    ];
    expect(closedDealsInMonth(deals, NOW)).toBe(1);
  });

  it("sums recorded GCI this year and reports deals missing a GCI figure", () => {
    const yearStart = Date.UTC(2026, 0, 1);
    const deals = [
      deal({ id: "a", gci: 10000 }),
      deal({ id: "b", gci: 5000, closedAt: "2026-02-01T00:00:00Z" }),
      deal({ id: "missing", gci: null }),
      deal({ id: "last-year", gci: 99999, closedAt: "2025-11-01T00:00:00Z" }),
    ];
    expect(gciClosedThisYear(deals, yearStart, NOW)).toEqual({
      total: 15000,
      dealsWithGci: 2,
      dealsMissingGci: 1,
    });
  });

  it("groups sales by close year with the current year marked YTD", () => {
    const deals = [
      deal({ id: "a", closedAt: "2025-03-01T00:00:00Z" }),
      deal({ id: "b", closedAt: "2025-09-01T00:00:00Z" }),
      deal({ id: "c", closedAt: "2026-05-01T00:00:00Z" }),
      deal({ id: "undated", closedAt: null, completedAt: null }),
    ];
    expect(salesByYear(deals, NOW)).toEqual([
      { id: "2025", label: "2025", value: 2 },
      { id: "2026", label: "2026 · YTD", value: 1 },
    ]);
  });

  it("counts profiles marked New lead only inside the window", () => {
    expect(countMarkedNewLeads(funnelProfiles(), PERIOD_START, NOW)).toBe(2);
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

    const snapshot = buildReportingSnapshot(
      { inbox: inbox(funnelProfiles()), sends, deals: [], goals: null },
      NOW,
    );
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));

    expect(metrics.get("texts")).toMatchObject({ value: 3, displayValue: "3", status: "available" });
    expect(metrics.get("emails")).toMatchObject({ value: 1, displayValue: "1", status: "available" });
    // Calls and appointments have no data source; they must stay honest dashes.
    for (const id of ["calls", "appointments"] as const) {
      expect(metrics.get(id)).toMatchObject({ value: null, displayValue: "—", status: "unavailable" });
    }
    // New leads counts status-change dates inside the window (2 of the 4 new_lead rows).
    expect(metrics.get("new-leads")).toMatchObject({ value: 2, displayValue: "2", status: "available" });
    // Lead → client: 2 client-stage profiles of 10 leads.
    expect(metrics.get("lead-client")).toMatchObject({ displayValue: "20.0%", status: "available" });
    expect(snapshot.coverage).toMatchObject({ profiles: 12, conversations: 1, sources: 2 });
    expect(snapshot.funnel?.[0]).toMatchObject({ id: "leads", value: 10 });
    expect(snapshot.conversionBySource?.[0]).toMatchObject({ id: "referral", pct: 33 });
  });

  it("keeps lead-derived KPIs unavailable when lead coverage fails to load", () => {
    const snapshot = buildReportingSnapshot(
      { inbox: null, sends: null, deals: null, goals: null },
      NOW,
    );
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));
    for (const id of ["new-leads", "lead-client"] as const) {
      expect(metrics.get(id)).toMatchObject({ value: null, displayValue: "—", status: "unavailable" });
    }
    expect(snapshot.funnel).toBeNull();
    expect(snapshot.conversionBySource).toBeNull();
    expect(snapshot.salesByYear).toBeNull();
    expect(snapshot.gciThisYear).toBeNull();
    expect(snapshot.activityMath).toBeNull();
  });

  it("excludes synthetic provider rows without treating a sent row as delivery proof", () => {
    const sends = sentResponse([
      sent("provider", "sms"),
      sent("no-provider-id", "sms", "2026-07-12T12:00:00Z", "sent", null),
      sent("synthetic-upper", "sms", "2026-07-12T12:00:00Z", "sent", " Stub-LOCAL "),
    ]);

    const snapshot = buildReportingSnapshot(
      { inbox: null, sends, deals: null, goals: null },
      NOW,
    );
    const textMetric = snapshot.kpis.find((metric) => metric.id === "texts");

    expect(textMetric).toMatchObject({
      label: "Texts sent",
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
      { inbox: null, sends: sentResponse(items), deals: null, goals: null },
      NOW,
    );
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));

    expect(metrics.get("texts")).toMatchObject({ value: 250, displayValue: "250+", status: "partial" });
    expect(metrics.get("emails")).toMatchObject({ value: 250, displayValue: "250+", status: "partial" });
    expect(snapshot.sendWindowTruncated).toBe(true);
  });

  it("keeps the truncation flag off when the send read did not hit its limit", () => {
    const snapshot = buildReportingSnapshot(
      { inbox: null, sends: sentResponse([sent("only", "sms")]), deals: null, goals: null },
      NOW,
    );
    expect(snapshot.sendWindowTruncated).toBe(false);
    expect(
      buildReportingSnapshot({ inbox: null, sends: null, deals: null, goals: null }, NOW)
        .sendWindowTruncated,
    ).toBe(false);
  });

  it("recomputes every windowed number from the selected period instead of a hardcoded 30 days", () => {
    const inWiderWindow = "2026-05-20T12:00:00Z"; // ~54 days before NOW
    const sends = sentResponse([
      sent("recent", "sms"),
      sent("older", "sms", inWiderWindow),
      sent("older-email", "email", inWiderWindow),
    ]);
    const profiles = [
      ...funnelProfiles(), // includes a new_lead marked 2026-05-01 (outside 30d, inside 90d)
    ];

    const thirty = buildReportingSnapshot({ inbox: inbox(profiles), sends, deals: [], goals: null }, NOW, 30);
    const ninety = buildReportingSnapshot({ inbox: inbox(profiles), sends, deals: [], goals: null }, NOW, 90);

    expect(thirty.periodDays).toBe(30);
    expect(ninety.periodDays).toBe(90);
    expect(ninety.periodStart).toBe(NOW - 90 * 24 * 60 * 60 * 1000);

    const thirtyMetrics = new Map(thirty.kpis.map((metric) => [metric.id, metric]));
    const ninetyMetrics = new Map(ninety.kpis.map((metric) => [metric.id, metric]));

    expect(thirtyMetrics.get("texts")).toMatchObject({ value: 1 });
    expect(ninetyMetrics.get("texts")).toMatchObject({ value: 2 });
    expect(ninetyMetrics.get("emails")).toMatchObject({ value: 1 });
    expect(thirtyMetrics.get("new-leads")).toMatchObject({ value: 2 });
    expect(ninetyMetrics.get("new-leads")).toMatchObject({ value: 3 });

    // Captions and goal labels name the selected window.
    expect(ninetyMetrics.get("texts")?.note).toContain("last 90 days");
    expect(ninetyMetrics.get("new-leads")?.note).toContain("last 90 days");
    expect(ninety.goalProgress.find((row) => row.id === "leads")?.label).toBe("New leads (90d)");
    expect(thirty.goalProgress.find((row) => row.id === "leads")?.label).toBe("New leads (30d)");
    // The wider window counts more marked leads toward the same goal input.
    expect(ninety.goalProgress.find((row) => row.id === "leads")?.current).toBe(3);
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

    const snapshot = buildReportingSnapshot(
      { inbox: null, sends: null, deals, goals: null },
      NOW,
    );

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

  it("wires saved goals into progress rows and the reverse calculator", () => {
    const snapshot = buildReportingSnapshot(
      {
        inbox: inbox(funnelProfiles()),
        sends: null,
        deals: [deal({ id: "closed-july", gci: 12000 })],
        goals: { leadsGoal: 4, apptsGoal: 25, closingsGoal: 2, gciGoal: 250000, updatedAt: null },
      },
      NOW,
    );

    const leadsRow = snapshot.goalProgress.find((row) => row.id === "leads");
    expect(leadsRow).toMatchObject({ current: 2, goal: 4, pct: 50, tone: "neutral" });
    const closingsRow = snapshot.goalProgress.find((row) => row.id === "closings");
    expect(closingsRow).toMatchObject({ current: 1, goal: 2, pct: 50 });
    const gciRow = snapshot.goalProgress.find((row) => row.id === "gci");
    expect(gciRow).toMatchObject({ current: 12000, pct: 5, tone: "warn" });
    expect(snapshot.activityMath).toMatchObject({ closingsGoal: 2, usesDefaults: true });
  });

  it("distinguishes unavailable deal data from a loaded empty deal list", () => {
    expect(
      buildReportingSnapshot({ inbox: null, sends: null, deals: null, goals: null }, NOW)
        .closedDealsBySource,
    ).toBeNull();
    expect(
      buildReportingSnapshot({ inbox: null, sends: null, deals: [], goals: null }, NOW)
        .closedDealsBySource,
    ).toEqual([]);
  });

  it("clears a failed source during a partial refresh instead of presenting stale success", () => {
    const results: ReportingFetchResults = [
      { status: "fulfilled", value: inbox() },
      { status: "rejected", reason: new Error("send source offline") },
      { status: "fulfilled", value: { items: [], count: 0 } },
      { status: "rejected", reason: new Error("goals offline") },
    ];

    const refreshed = reportingInputsFromFetchResults(results);
    const snapshot = buildReportingSnapshot(refreshed.inputs, NOW);
    const metrics = new Map(snapshot.kpis.map((metric) => [metric.id, metric]));

    expect(refreshed.failures).toEqual(["send history", "goals"]);
    expect(refreshed.fulfilledCount).toBe(2);
    expect(refreshed.inputs.sends).toBeNull();
    expect(refreshed.inputs.goals).toBeNull();
    expect(metrics.get("texts")?.status).toBe("unavailable");
    expect(metrics.get("emails")?.status).toBe("unavailable");
    expect(snapshot.closedDealsBySource).toEqual([]);
    expect(snapshot.goals).toBeNull();
    expect(snapshot.activityMath).toBeNull();
  });
});

describe("funnel read window", () => {
  // The funnel, lead→client, and conversion-by-source all read `inbox.profiles`,
  // which the page fetches capped at REPORTING_SOURCE_LIMIT. On a real book
  // (3,885 contacts) that made "Conversations 500 / Leads 500 = 100%" true by
  // construction — both hit the same cap. Deals and sends already flagged their
  // truncation; profiles didn't.
  it("flags the window when profiles are a sample of the book", () => {
    const partial = inbox(funnelProfiles());
    partial.recordCounts = { contacts: 3885, conversations: 4395 };

    const snapshot = buildReportingSnapshot(
      { inbox: partial, sends: null, deals: [], goals: null },
      NOW,
    );

    expect(snapshot.coverage.truncated).toBe(true);
    expect(snapshot.coverage.totalContacts).toBe(3885);
    expect(snapshot.coverage.profiles).toBe(funnelProfiles().length);
  });

  it("does not flag a window that holds the whole book", () => {
    const whole = inbox(funnelProfiles());
    whole.recordCounts = { contacts: funnelProfiles().length };

    const snapshot = buildReportingSnapshot(
      { inbox: whole, sends: null, deals: [], goals: null },
      NOW,
    );

    expect(snapshot.coverage.truncated).toBe(false);
  });

  it("stays quiet when the response carries no record counts", () => {
    const snapshot = buildReportingSnapshot(
      { inbox: inbox(funnelProfiles()), sends: null, deals: [], goals: null },
      NOW,
    );

    expect(snapshot.coverage.truncated).toBe(false);
    expect(snapshot.coverage.totalContacts).toBeNull();
  });
});
