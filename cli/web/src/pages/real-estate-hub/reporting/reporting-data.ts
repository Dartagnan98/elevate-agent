import type {
  AccountGoals,
  AdminDeal,
  AdminDealsResponse,
  SourceInboxProfile,
  SourceInboxResponse,
  SourceInboxSentItem,
  SourceInboxSentResponse,
} from "@/lib/api-types";

export const REPORTING_PERIOD_DAYS = 30;
/** Selectable report windows (days). Every snapshot number derives from the chosen one. */
export const REPORTING_RANGE_OPTIONS = [30, 90] as const;
export type ReportingRangeDays = (typeof REPORTING_RANGE_OPTIONS)[number];
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

// ---------------------------------------------------------------------------
// Pipeline-status groupings (migration 0035 stages + legacy statuses).
// ---------------------------------------------------------------------------

/** Statuses that mean "this profile became a client" (includes closed). */
export const CLIENT_STATUSES: ReadonlySet<string> = new Set([
  "client",
  "pending_deal",
  "closed",
  "closed_seller",
  "closed_buyer",
]);

/** Statuses that mean "this profile's deal closed". */
export const CLOSED_STATUSES: ReadonlySet<string> = new Set([
  "closed",
  "closed_seller",
  "closed_buyer",
]);

/** Statuses excluded from the lead universe (not sales leads). */
export const NON_LEAD_STATUSES: ReadonlySet<string> = new Set([
  "realtor_contact",
  "trash",
]);

function isLeadProfile(profile: SourceInboxProfile): boolean {
  return !NON_LEAD_STATUSES.has(profile.status ?? "");
}

function isClientProfile(profile: SourceInboxProfile): boolean {
  return CLIENT_STATUSES.has(profile.status ?? "");
}

// ---------------------------------------------------------------------------
// Funnel (snapshot of current pipeline statuses, not a dated cohort).
// ---------------------------------------------------------------------------

export type ReportingFunnelStageId =
  | "leads"
  | "conversations"
  | "appointments"
  | "clients"
  | "under-contract"
  | "closed";

export interface ReportingFunnelStage {
  id: ReportingFunnelStageId;
  label: string;
  /** null = no data source exists for this stage yet. */
  value: number | null;
  /** Percent kept from the nearest previous stage with a measured value. */
  keptPct: number | null;
  note?: string;
}

export function buildFunnelStages(profiles: SourceInboxProfile[]): ReportingFunnelStage[] {
  const leads = profiles.filter(isLeadProfile);
  const conversations = leads.filter((profile) => profile.hasConversation).length;
  const clients = leads.filter(isClientProfile).length;
  const underContract = leads.filter((profile) => profile.status === "pending_deal").length;
  const closed = leads.filter((profile) => CLOSED_STATUSES.has(profile.status ?? "")).length;

  const stages: ReportingFunnelStage[] = [
    { id: "leads", label: "Leads", value: leads.length, keptPct: null },
    { id: "conversations", label: "Conversations", value: conversations, keptPct: null },
    {
      id: "appointments",
      label: "Appointments",
      value: null,
      keptPct: null,
      note: "No appointment tracking yet",
    },
    { id: "clients", label: "Clients", value: clients, keptPct: null },
    { id: "under-contract", label: "Under contract", value: underContract, keptPct: null },
    { id: "closed", label: "Closed", value: closed, keptPct: null },
  ];

  let previousMeasured: number | null = null;
  for (const stage of stages) {
    if (stage.value === null) continue;
    if (previousMeasured !== null && previousMeasured > 0) {
      stage.keptPct = Math.round((stage.value / previousMeasured) * 100);
    }
    previousMeasured = stage.value;
  }
  return stages;
}

// ---------------------------------------------------------------------------
// Conversion by lead source (share of each source's leads now in a client stage).
// ---------------------------------------------------------------------------

export interface SourceConversionRow {
  id: string;
  label: string;
  leads: number;
  clients: number;
  pct: number;
}

export function conversionByLeadSource(
  profiles: SourceInboxProfile[],
  limit = 10,
): SourceConversionRow[] {
  const groups = new Map<string, { label: string; leads: number; clients: number }>();
  for (const profile of profiles) {
    if (!isLeadProfile(profile)) continue;
    const label = profile.leadSource?.trim();
    if (!label) continue;
    const key = label.toLowerCase();
    const group = groups.get(key) ?? { label, leads: 0, clients: 0 };
    group.leads += 1;
    if (isClientProfile(profile)) group.clients += 1;
    groups.set(key, group);
  }
  return Array.from(groups.entries(), ([key, group]) => ({
    id: key.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "unknown",
    label: group.label,
    leads: group.leads,
    clients: group.clients,
    pct: Math.round((group.clients / group.leads) * 100),
  }))
    .sort((a, b) => b.pct - a.pct || b.leads - a.leads || a.label.localeCompare(b.label))
    .slice(0, limit);
}

// ---------------------------------------------------------------------------
// Reverse activity calculator ("what it takes to hit your goal").
// ---------------------------------------------------------------------------

/**
 * Published fallback conversion rates, used ONLY when a step cannot be measured
 * from real pipeline data. Rendered in the UI with an explicit
 * "industry default" caption whenever any of them is in play.
 */
export const REPORTING_DEFAULT_RATES = {
  leadToConversation: 0.52,
  conversationToAppointment: 0.33,
  appointmentToClient: 0.42,
  clientToClose: 0.22,
} as const;

export type ReportingRateId = keyof typeof REPORTING_DEFAULT_RATES;

export interface ReportingRate {
  rate: number;
  source: "measured" | "default";
}

export type ReportingRates = Record<ReportingRateId, ReportingRate>;

function resolveRate(
  numerator: number | null | undefined,
  denominator: number | null | undefined,
  fallback: number,
): ReportingRate {
  if (
    typeof numerator === "number" &&
    typeof denominator === "number" &&
    denominator > 0 &&
    numerator > 0
  ) {
    return { rate: numerator / denominator, source: "measured" };
  }
  return { rate: fallback, source: "default" };
}

export function resolveFunnelRates(funnel: ReportingFunnelStage[] | null): ReportingRates {
  const value = (id: ReportingFunnelStageId): number | null =>
    funnel?.find((stage) => stage.id === id)?.value ?? null;
  return {
    leadToConversation: resolveRate(
      value("conversations"),
      value("leads"),
      REPORTING_DEFAULT_RATES.leadToConversation,
    ),
    conversationToAppointment: resolveRate(
      value("appointments"),
      value("conversations"),
      REPORTING_DEFAULT_RATES.conversationToAppointment,
    ),
    appointmentToClient: resolveRate(
      value("clients"),
      value("appointments"),
      REPORTING_DEFAULT_RATES.appointmentToClient,
    ),
    clientToClose: resolveRate(
      value("closed"),
      value("clients"),
      REPORTING_DEFAULT_RATES.clientToClose,
    ),
  };
}

export interface ActivityMath {
  closingsGoal: number;
  /** Whole-number requirements, funnel order. */
  leads: number;
  conversations: number;
  appointments: number;
  clients: number;
  conversationsPerSale: number;
  perWeek: number;
  perDay: number;
  usesDefaults: boolean;
  defaultRateIds: ReportingRateId[];
}

export function buildActivityMath(
  closingsGoal: number | null | undefined,
  rates: ReportingRates,
): ActivityMath | null {
  if (typeof closingsGoal !== "number" || !Number.isFinite(closingsGoal) || closingsGoal <= 0) {
    return null;
  }
  const clients = closingsGoal / rates.clientToClose.rate;
  const appointments = clients / rates.appointmentToClient.rate;
  const conversations = appointments / rates.conversationToAppointment.rate;
  const leads = conversations / rates.leadToConversation.rate;
  const defaultRateIds = (Object.keys(rates) as ReportingRateId[]).filter(
    (id) => rates[id].source === "default",
  );
  return {
    closingsGoal,
    leads: Math.ceil(leads),
    conversations: Math.ceil(conversations),
    appointments: Math.ceil(appointments),
    clients: Math.ceil(clients),
    conversationsPerSale: Math.max(1, Math.round(conversations / closingsGoal)),
    perWeek: Math.max(1, Math.round(conversations / 4.3)),
    perDay: Math.max(1, Math.round(conversations / 21)),
    usesDefaults: defaultRateIds.length > 0,
    defaultRateIds,
  };
}

// ---------------------------------------------------------------------------
// Goal progress.
// ---------------------------------------------------------------------------

export type GoalTone = "good" | "neutral" | "warn";

export function goalTone(pct: number): GoalTone {
  if (pct >= 80) return "good";
  if (pct >= 50) return "neutral";
  return "warn";
}

export interface GoalProgressRow {
  id: "leads" | "appointments" | "closings" | "gci";
  label: string;
  current: number | null;
  goal: number | null;
  /** 0-100, capped; null when either side is unknown. */
  pct: number | null;
  tone: GoalTone | null;
  currentDisplay: string;
  goalDisplay: string;
  note?: string;
}

export interface GoalCurrents {
  newLeads: number | null;
  appointments: number | null;
  closingsThisMonth: number | null;
  gciThisYear: number | null;
}

function formatGciShort(value: number): string {
  return `$${Math.round(value / 1000).toLocaleString("en-CA")}k`;
}

function goalRow(
  id: GoalProgressRow["id"],
  label: string,
  current: number | null,
  goal: number | null,
  fmt: (value: number) => string,
  note?: string,
): GoalProgressRow {
  const pct =
    current !== null && goal !== null && goal > 0
      ? Math.min(100, Math.round((current / goal) * 100))
      : null;
  return {
    id,
    label,
    current,
    goal,
    pct,
    tone: pct === null ? null : goalTone(pct),
    currentDisplay: current === null ? "—" : fmt(current),
    goalDisplay: goal === null ? "not set" : fmt(goal),
    note,
  };
}

export function buildGoalProgress(
  goals: AccountGoals | null,
  currents: GoalCurrents,
  periodDays: number = REPORTING_PERIOD_DAYS,
): GoalProgressRow[] {
  const plain = (value: number) => value.toLocaleString("en-CA");
  return [
    goalRow("leads", `New leads (${periodDays}d)`, currents.newLeads, goals?.leadsGoal ?? null, plain),
    goalRow(
      "appointments",
      "Appointments",
      currents.appointments,
      goals?.apptsGoal ?? null,
      plain,
      "No appointment tracking yet",
    ),
    goalRow("closings", "Closings (mo)", currents.closingsThisMonth, goals?.closingsGoal ?? null, plain),
    goalRow("gci", "GCI (year)", currents.gciThisYear, goals?.gciGoal ?? null, formatGciShort),
  ];
}

// ---------------------------------------------------------------------------
// Snapshot plumbing.
// ---------------------------------------------------------------------------

export interface ReportingSnapshot {
  asOf: number;
  periodDays: number;
  periodStart: number;
  kpis: ReportingMetric[];
  coverage: ReportingCoverage;
  goals: AccountGoals | null;
  goalProgress: GoalProgressRow[];
  funnel: ReportingFunnelStage[] | null;
  conversionBySource: SourceConversionRow[] | null;
  rates: ReportingRates;
  activityMath: ActivityMath | null;
  closedDealsBySource: ReportingBreakdownRow[] | null;
  closedDealsByMonth: ReportingTrendPoint[] | null;
  salesByYear: ReportingBreakdownRow[] | null;
  gciThisYear: { total: number; dealsWithGci: number; dealsMissingGci: number } | null;
  closedDealsPartial: boolean;
  undatedClosedDeals: number;
  /**
   * True when the newest-first send read hit its row limit without leaving the
   * selected window — send-derived totals are lower bounds for this range.
   */
  sendWindowTruncated: boolean;
}

export interface ReportingSnapshotInput {
  inbox: SourceInboxResponse | null;
  sends: SourceInboxSentResponse | null;
  deals: AdminDeal[] | null;
  goals: AccountGoals | null;
}

export type ReportingFetchResults = readonly [
  PromiseSettledResult<SourceInboxResponse>,
  PromiseSettledResult<SourceInboxSentResponse>,
  PromiseSettledResult<AdminDealsResponse>,
  PromiseSettledResult<AccountGoals>,
];

export function reportingInputsFromFetchResults(results: ReportingFetchResults): {
  inputs: ReportingSnapshotInput;
  failures: string[];
  fulfilledCount: number;
} {
  const [inboxResult, sendsResult, dealsResult, goalsResult] = results;
  const failures: string[] = [];
  if (inboxResult.status === "rejected") failures.push("lead coverage");
  if (sendsResult.status === "rejected") failures.push("send history");
  if (dealsResult.status === "rejected") failures.push("closed deals");
  if (goalsResult.status === "rejected") failures.push("goals");

  return {
    inputs: {
      inbox: inboxResult.status === "fulfilled" ? inboxResult.value : null,
      sends: sendsResult.status === "fulfilled" ? sendsResult.value : null,
      deals: dealsResult.status === "fulfilled" ? dealsResult.value.items : null,
      goals: goalsResult.status === "fulfilled" ? goalsResult.value : null,
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
  periodDays: number,
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
      ? `At least ${value.toLocaleString("en-CA")} non-synthetic rows were marked sent; the send log reached its ${REPORTING_SEND_LIMIT.toLocaleString("en-CA")}-row read limit within this ${periodDays}-day period. Send status is not recipient-delivery proof.`
      : `Non-synthetic rows marked sent in the last ${periodDays} days. Send status is not recipient-delivery proof.`,
  };
}

/** Profiles marked "New lead" inside the window (status-change date). */
export function countMarkedNewLeads(
  profiles: SourceInboxProfile[],
  periodStart: number,
  now: number,
): number {
  return profiles.filter(
    (profile) =>
      profile.status === "new_lead" &&
      isWithin(parseTimestamp(profile.statusUpdatedAt), periodStart, now),
  ).length;
}

export function leadToClientRate(profiles: SourceInboxProfile[]): {
  clients: number;
  base: number;
  pct: number | null;
} {
  const leads = profiles.filter(isLeadProfile);
  const clients = leads.filter(isClientProfile).length;
  return {
    clients,
    base: leads.length,
    pct: leads.length > 0 ? (clients / leads.length) * 100 : null,
  };
}

function newLeadsMetric(
  inbox: SourceInboxResponse | null,
  periodStart: number,
  now: number,
  periodDays: number,
): ReportingMetric {
  if (!inbox) {
    return unavailableMetric(
      "new-leads",
      "New leads",
      "Lead coverage was not available for this refresh.",
    );
  }
  const value = countMarkedNewLeads(inbox.profiles, periodStart, now);
  return {
    id: "new-leads",
    label: "New leads",
    value,
    displayValue: value.toLocaleString("en-CA"),
    status: "available",
    note: `Profiles marked New lead in the last ${periodDays} days (status-change date; contact creation dates are not recorded yet).`,
  };
}

function leadToClientMetric(inbox: SourceInboxResponse | null): ReportingMetric {
  if (!inbox) {
    return unavailableMetric(
      "lead-client",
      "Lead → client",
      "Lead coverage was not available for this refresh.",
    );
  }
  const { clients, base, pct } = leadToClientRate(inbox.profiles);
  if (pct === null) {
    return unavailableMetric(
      "lead-client",
      "Lead → client",
      "No lead profiles in the source window yet.",
    );
  }
  return {
    id: "lead-client",
    label: "Lead → client",
    value: pct,
    displayValue: `${pct.toFixed(1)}%`,
    status: "available",
    note: `${clients.toLocaleString("en-CA")} of ${base.toLocaleString("en-CA")} profiles in the source window are in a client or closed pipeline stage.`,
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

/** Closed deals with a close timestamp inside the current UTC calendar month. */
export function closedDealsInMonth(deals: AdminDeal[], nowMs: number): number {
  const now = new Date(nowMs);
  const monthStart = monthStartUtc(now, 0).getTime();
  return deals.filter(
    (deal) => isClosedDeal(deal) && isWithin(dealCloseTimestamp(deal), monthStart, nowMs),
  ).length;
}

/** Sum of recorded GCI on deals closed this calendar year. */
export function gciClosedThisYear(
  deals: AdminDeal[],
  yearStart: number,
  now: number,
): { total: number; dealsWithGci: number; dealsMissingGci: number } {
  let total = 0;
  let dealsWithGci = 0;
  let dealsMissingGci = 0;
  for (const deal of deals) {
    if (!isClosedDeal(deal)) continue;
    if (!isWithin(dealCloseTimestamp(deal), yearStart, now)) continue;
    if (typeof deal.gci === "number" && Number.isFinite(deal.gci)) {
      total += deal.gci;
      dealsWithGci += 1;
    } else {
      dealsMissingGci += 1;
    }
  }
  return { total, dealsWithGci, dealsMissingGci };
}

/** Closed deals grouped by close year, oldest first; current year labelled YTD. */
export function salesByYear(deals: AdminDeal[], nowMs: number): ReportingBreakdownRow[] {
  const currentYear = new Date(nowMs).getUTCFullYear();
  const totals = new Map<number, number>();
  for (const deal of deals) {
    if (!isClosedDeal(deal)) continue;
    const timestamp = dealCloseTimestamp(deal);
    if (timestamp === null || timestamp > nowMs) continue;
    const year = new Date(timestamp).getUTCFullYear();
    totals.set(year, (totals.get(year) ?? 0) + 1);
  }
  return Array.from(totals.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([year, value]) => ({
      id: String(year),
      label: year === currentYear ? `${year} · YTD` : String(year),
      value,
    }));
}

export function buildReportingSnapshot(
  input: ReportingSnapshotInput,
  now = Date.now(),
  periodDays: number = REPORTING_PERIOD_DAYS,
): ReportingSnapshot {
  const periodStart = now - periodDays * DAY_MS;
  const nowDate = new Date(now);
  const yearStart = Date.UTC(nowDate.getUTCFullYear(), 0, 1);
  const deals = input.deals;
  const profiles = input.inbox?.profiles ?? null;

  const funnel = profiles ? buildFunnelStages(profiles) : null;
  const rates = resolveFunnelRates(funnel);
  const gciThisYear = deals ? gciClosedThisYear(deals, yearStart, now) : null;

  return {
    asOf: now,
    periodDays,
    periodStart,
    kpis: [
      newLeadsMetric(input.inbox, periodStart, now, periodDays),
      unavailableMetric(
        "calls",
        "Calls made",
        "No call tracking yet — calls are not stored as reportable activity events.",
      ),
      sendMetric("texts", "Texts sent", "text", input.sends, periodStart, now, periodDays),
      sendMetric("emails", "Emails sent", "email", input.sends, periodStart, now, periodDays),
      unavailableMetric(
        "appointments",
        "Appointments booked",
        "No appointment tracking yet — appointments do not have a persisted reporting entity.",
      ),
      leadToClientMetric(input.inbox),
    ],
    coverage: input.inbox
      ? {
          status: "available",
          profiles: input.inbox.profiles.length,
          conversations: input.inbox.threads.length,
          sources: input.inbox.sources.length,
        }
      : { status: "unavailable", profiles: null, conversations: null, sources: null },
    goals: input.goals,
    goalProgress: buildGoalProgress(input.goals, {
      newLeads: profiles ? countMarkedNewLeads(profiles, periodStart, now) : null,
      appointments: null,
      closingsThisMonth: deals ? closedDealsInMonth(deals, now) : null,
      gciThisYear: gciThisYear ? gciThisYear.total : null,
    }, periodDays),
    funnel,
    conversionBySource: profiles ? conversionByLeadSource(profiles) : null,
    rates,
    activityMath: buildActivityMath(input.goals?.closingsGoal ?? null, rates),
    closedDealsBySource: deals ? closedDealsBySource(deals, yearStart, now) : null,
    closedDealsByMonth: deals ? closedDealsByMonth(deals, now) : null,
    salesByYear: deals ? salesByYear(deals, now) : null,
    gciThisYear,
    closedDealsPartial: Boolean(deals && deals.length >= REPORTING_DEAL_LIMIT),
    undatedClosedDeals: deals
      ? deals.filter((deal) => isClosedDeal(deal) && dealCloseTimestamp(deal) === null).length
      : 0,
    sendWindowTruncated: Boolean(input.sends && sentWindowMayBeTruncated(input.sends, periodStart)),
  };
}
