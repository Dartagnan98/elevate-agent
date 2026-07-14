import type {
  AdminDeal,
  AdminDealsResponse,
  SourceInboxResponse,
  SourceInboxSentItem,
  SourceInboxSentResponse,
} from "@/lib/api-types";

export const REPORTING_PERIOD_DAYS = 30;
export const REPORTING_SEND_LIMIT = 500;
export const REPORTING_DEAL_LIMIT = 1000;

const DAY_MS = 24 * 60 * 60 * 1000;

export type ReportingMetricStatus = "available" | "partial" | "unavailable";

export interface ReportingMetric {
  id: "new-leads" | "calls" | "texts" | "emails" | "appointments" | "lead-client";
  label: string;
  value: number | null;
  displayValue: string;
  status: ReportingMetricStatus;
  note: string;
}

export interface ReportingBreakdownRow {
  id: string;
  label: string;
  value: number;
}

export interface ReportingTrendPoint {
  id: string;
  label: string;
  value: number;
}

export interface ReportingCoverage {
  status: "available" | "unavailable";
  profiles: number | null;
  conversations: number | null;
  sources: number | null;
}

export interface ReportingSnapshot {
  asOf: number;
  periodDays: number;
  periodStart: number;
  kpis: ReportingMetric[];
  coverage: ReportingCoverage;
  closedDealsBySource: ReportingBreakdownRow[] | null;
  closedDealsByMonth: ReportingTrendPoint[] | null;
  closedDealsPartial: boolean;
  undatedClosedDeals: number;
}

export interface ReportingSnapshotInput {
  inbox: SourceInboxResponse | null;
  sends: SourceInboxSentResponse | null;
  deals: AdminDeal[] | null;
}

export type ReportingFetchResults = readonly [
  PromiseSettledResult<SourceInboxResponse>,
  PromiseSettledResult<SourceInboxSentResponse>,
  PromiseSettledResult<AdminDealsResponse>,
];

export function reportingInputsFromFetchResults(results: ReportingFetchResults): {
  inputs: ReportingSnapshotInput;
  failures: string[];
  fulfilledCount: number;
} {
  const [inboxResult, sendsResult, dealsResult] = results;
  const failures: string[] = [];
  if (inboxResult.status === "rejected") failures.push("lead coverage");
  if (sendsResult.status === "rejected") failures.push("send history");
  if (dealsResult.status === "rejected") failures.push("closed deals");

  return {
    inputs: {
      inbox: inboxResult.status === "fulfilled" ? inboxResult.value : null,
      sends: sendsResult.status === "fulfilled" ? sendsResult.value : null,
      deals: dealsResult.status === "fulfilled" ? dealsResult.value.items : null,
    },
    failures,
    fulfilledCount: results.length - failures.length,
  };
}

function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isWithin(timestamp: number | null, start: number, end: number): boolean {
  return timestamp !== null && timestamp >= start && timestamp <= end;
}

function normalizeChannel(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_-]+/g, " ");
}

export function reportingChannelKind(channel: string): "text" | "email" | "other" {
  const normalized = normalizeChannel(channel);
  if (
    normalized === "sms" ||
    normalized === "text" ||
    normalized === "imessage" ||
    normalized === "apple messages"
  ) {
    return "text";
  }
  if (normalized === "email" || normalized === "gmail") return "email";
  return "other";
}

function sentWindowMayBeTruncated(
  response: SourceInboxSentResponse,
  periodStart: number,
): boolean {
  const effectiveLimit = Math.max(
    1,
    Math.min(Number(response.limit) || REPORTING_SEND_LIMIT, REPORTING_SEND_LIMIT),
  );
  if (response.items.length < effectiveLimit) return false;
  const timestamps = response.items
    .map((item) => parseTimestamp(item.updatedAt))
    .filter((value): value is number => value !== null);
  if (timestamps.length !== response.items.length) return true;
  return Math.min(...timestamps) >= periodStart;
}

function isSyntheticSend(item: SourceInboxSentItem): boolean {
  return item.providerMessageId?.trim().toLowerCase().startsWith("stub-") ?? false;
}

function countRecordedSends(
  items: SourceInboxSentItem[],
  kind: "text" | "email",
  periodStart: number,
  now: number,
): number {
  return items.filter(
    (item) =>
      item.status === "sent" &&
      !isSyntheticSend(item) &&
      reportingChannelKind(item.channel) === kind &&
      isWithin(parseTimestamp(item.updatedAt), periodStart, now),
  ).length;
}

function unavailableMetric(
  id: ReportingMetric["id"],
  label: string,
  note: string,
): ReportingMetric {
  return { id, label, value: null, displayValue: "—", status: "unavailable", note };
}

function sendMetric(
  id: "texts" | "emails",
  label: string,
  kind: "text" | "email",
  sends: SourceInboxSentResponse | null,
  periodStart: number,
  now: number,
): ReportingMetric {
  if (!sends) {
    return unavailableMetric(
      id,
      label,
      "Recorded send history was not available for this refresh.",
    );
  }
  const value = countRecordedSends(sends.items, kind, periodStart, now);
  const partial = sentWindowMayBeTruncated(sends, periodStart);
  return {
    id,
    label,
    value,
    displayValue: partial ? `${value.toLocaleString("en-CA")}+` : value.toLocaleString("en-CA"),
    status: partial ? "partial" : "available",
    note: partial
      ? `At least ${value.toLocaleString("en-CA")} non-synthetic rows were marked sent; the send log reached its ${REPORTING_SEND_LIMIT.toLocaleString("en-CA")}-row read limit within this period. Send status is not recipient-delivery proof.`
      : `Non-synthetic rows marked sent in the last ${REPORTING_PERIOD_DAYS} days. Send status is not recipient-delivery proof.`,
  };
}

function dealCloseTimestamp(deal: AdminDeal): number | null {
  return parseTimestamp(deal.closedAt) ?? parseTimestamp(deal.completedAt);
}

function isClosedDeal(deal: AdminDeal): boolean {
  return deal.status.trim().toLowerCase() === "closed";
}

function dealSource(deal: AdminDeal): string {
  const label = deal.sourceLabel?.trim();
  if (label) return label;
  const key = deal.sourceKey?.trim();
  return key || "Source not recorded";
}

function closedDealsBySource(deals: AdminDeal[], yearStart: number, now: number): ReportingBreakdownRow[] {
  const totals = new Map<string, number>();
  for (const deal of deals) {
    if (!isClosedDeal(deal)) continue;
    if (!isWithin(dealCloseTimestamp(deal), yearStart, now)) continue;
    const label = dealSource(deal);
    totals.set(label, (totals.get(label) ?? 0) + 1);
  }
  return Array.from(totals, ([label, value]) => ({
    id: label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "unknown",
    label,
    value,
  })).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
}

function monthStartUtc(now: Date, monthOffset: number): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + monthOffset, 1));
}

function monthKey(date: Date): string {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function closedDealsByMonth(deals: AdminDeal[], nowMs: number): ReportingTrendPoint[] {
  const now = new Date(nowMs);
  const months = Array.from({ length: 6 }, (_, index) => monthStartUtc(now, index - 5));
  const totals = new Map(months.map((month) => [monthKey(month), 0]));
  const rangeStart = months[0].getTime();

  for (const deal of deals) {
    if (!isClosedDeal(deal)) continue;
    const timestamp = dealCloseTimestamp(deal);
    if (!isWithin(timestamp, rangeStart, nowMs)) continue;
    const key = monthKey(new Date(timestamp as number));
    if (totals.has(key)) totals.set(key, (totals.get(key) ?? 0) + 1);
  }

  return months.map((month) => ({
    id: monthKey(month),
    label: new Intl.DateTimeFormat("en-CA", { month: "short", timeZone: "UTC" }).format(month),
    value: totals.get(monthKey(month)) ?? 0,
  }));
}

export function buildReportingSnapshot(
  input: ReportingSnapshotInput,
  now = Date.now(),
): ReportingSnapshot {
  const periodStart = now - REPORTING_PERIOD_DAYS * DAY_MS;
  const nowDate = new Date(now);
  const yearStart = Date.UTC(nowDate.getUTCFullYear(), 0, 1);
  const deals = input.deals;

  return {
    asOf: now,
    periodDays: REPORTING_PERIOD_DAYS,
    periodStart,
    kpis: [
      unavailableMetric(
        "new-leads",
        "New leads",
        "Lead profiles do not expose a created timestamp yet, so a period count cannot be proven.",
      ),
      unavailableMetric(
        "calls",
        "Calls made",
        "Calls are not stored as reportable activity events yet.",
      ),
      sendMetric("texts", "Texts recorded", "text", input.sends, periodStart, now),
      sendMetric("emails", "Emails recorded", "email", input.sends, periodStart, now),
      unavailableMetric(
        "appointments",
        "Appointments booked",
        "Appointments do not have a persisted reporting entity yet.",
      ),
      unavailableMetric(
        "lead-client",
        "Lead → client",
        "Lead profiles are not yet joined to a dated client-conversion event.",
      ),
    ],
    coverage: input.inbox
      ? {
          status: "available",
          profiles: input.inbox.profiles.length,
          conversations: input.inbox.threads.length,
          sources: input.inbox.sources.length,
        }
      : { status: "unavailable", profiles: null, conversations: null, sources: null },
    closedDealsBySource: deals ? closedDealsBySource(deals, yearStart, now) : null,
    closedDealsByMonth: deals ? closedDealsByMonth(deals, now) : null,
    closedDealsPartial: Boolean(deals && deals.length >= REPORTING_DEAL_LIMIT),
    undatedClosedDeals: deals
      ? deals.filter((deal) => isClosedDeal(deal) && dealCloseTimestamp(deal) === null).length
      : 0,
  };
}
