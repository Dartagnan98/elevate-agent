import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  AdminDeal,
  AdminUpcomingEvent,
  CronJob,
  SessionInfo,
  SourceInboxDraft,
  SourceInboxThread,
  TodayDashboardResponse,
} from "@/lib/api-types";
import { useRealEstateHubData } from "@/pages/real-estate-hub/_shared";
import { TodayBoard } from "./components/today-board";
import type {
  TodayAgentRun,
  TodayBoardProps,
  TodayCalendarEvent,
  TodayDayBucket,
  TodayDeal,
  TodayDraft,
  TodayHourBucket,
  TodayLiveItem,
  TodayPipelineStage,
  TodayPriorityItem,
  TodayPulseStat,
  TodayScheduledJob,
  TodaySourceBreakdown,
  TodaySourceItem,
  TodaySources,
  TodayWin,
} from "./components/today-board";
import "../leads/leads.css";
import "./today.css";

const DAY_MS = 24 * 60 * 60 * 1000;

const STAGE_LABELS = [
  ["Pre-CMA", "Intake"],
  ["CMA", "Search Setup"],
  ["Listing Intake", "Tours"],
  ["SkySlope Prep", "Follow-Up"],
  ["Marketing Go", "Offer Prep"],
  ["MLS Entry", "Accepted"],
  ["Live", "Conditions"],
  ["Accepted Offer", "Conditions Removed"],
  ["Conditions", "Closing"],
  ["Closing", "Possession"],
];

const STAGE_TOTAL = 10;

function ageShort(input: string | number | null | undefined): string {
  if (input == null) return "";
  const t = typeof input === "number" ? input : Date.parse(input);
  if (!Number.isFinite(t) || t <= 0) return "";
  const diff = Date.now() - t;
  if (diff < 60_000) return "now";
  const m = Math.floor(diff / 60_000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function startOfLocalDay(d = new Date()): number {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
}

function formatEventTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  let hours = d.getHours();
  const minutes = d.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  if (hours === 0) hours = 12;
  const mm = minutes < 10 ? `0${minutes}` : String(minutes);
  return `${hours}:${mm} ${ampm}`;
}

function eventDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return "";
  const s = Date.parse(startIso);
  const e = Date.parse(endIso);
  if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return "";
  const mins = Math.round((e - s) / 60_000);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem === 0 ? `${h}h` : `${h}h ${rem}m`;
}

function eventKind(kind: string | null | undefined): TodayCalendarEvent["kind"] {
  const k = (kind || "").toLowerCase();
  if (k.includes("show")) return "showing";
  if (k.includes("cma") || k.includes("close") || k.includes("possession")) return "cma";
  if (k.includes("call")) return "callback";
  return "meeting";
}

function formatCronFires(job: CronJob): string {
  if (job.next_run_at) {
    const t = Date.parse(job.next_run_at);
    if (Number.isFinite(t)) {
      const start = startOfLocalDay();
      const d = new Date(t);
      const isToday = t >= start && t < start + DAY_MS;
      const isTomorrow = t >= start + DAY_MS && t < start + 2 * DAY_MS;
      const time = formatEventTime(d.toISOString());
      if (isToday) return `Today ${time}`;
      if (isTomorrow) return `Tomorrow ${time}`;
      const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()];
      return `${dow} ${time}`;
    }
  }
  return job.schedule_display || "scheduled";
}

function cronScheduleExpr(job: CronJob): string {
  return job.schedule?.expr || job.schedule_display || "—";
}

function cronMeta(job: CronJob): string {
  const parts: string[] = [];
  if (job.skill) parts.push(job.skill);
  if (job.tier) parts.push(job.tier);
  if (!parts.length && job.schedule?.kind) parts.push(job.schedule.kind);
  return parts.join(" · ") || "scheduled";
}

function mapPulse(stats: TodayDashboardResponse["pulse"] | undefined): TodayPulseStat[] {
  if (!stats || stats.length === 0) return [];
  return stats.map((s, i) => ({
    id: s.label ? `pulse-${i}-${s.label.toLowerCase().replace(/\s+/g, "-")}` : `pulse-${i}`,
    label: s.label,
    value: s.value,
    delta: s.delta,
    deltaLabel: s.deltaLabel ?? undefined,
    spark: s.spark || [],
    tone: s.tone,
  }));
}

function heatScore(d: SourceInboxDraft): number | null {
  if (typeof d.score === "number") return Math.round(d.score * 100);
  if (d.leadLabel === "hot") return 95;
  if (d.leadLabel === "warm") return 75;
  return null;
}

function threadHeat(t: SourceInboxThread): number | null {
  if (typeof t.heatScore === "number") return Math.round(t.heatScore * 100);
  if (t.heatLabel === "hot") return 95;
  if (t.heatLabel === "warm") return 75;
  return null;
}

function mapPriority(
  priority: TodayDashboardResponse["priority"] | undefined,
  drafts: SourceInboxDraft[],
  threads: SourceInboxThread[],
): TodayPriorityItem[] {
  if (!priority) return [];
  const draftById = new Map(drafts.map((d) => [d.id, d]));
  const threadById = new Map(threads.map((t) => [t.threadId, t]));
  return priority.map((p) => {
    let heat: number | null = null;
    if (p.kind === "draft" && p.sourceId) {
      const draft = drafts.find((d) => d.threadId === p.threadId) || draftById.get(p.id.replace(/^draft-/, ""));
      if (draft) heat = heatScore(draft);
    } else if (p.kind === "hot-lead" && p.threadId) {
      const thread = threadById.get(p.threadId);
      if (thread) heat = threadHeat(thread);
    }
    return {
      id: p.id,
      kind: p.kind,
      title: p.title,
      meta: p.meta,
      waitedMinutes: p.waitedMinutes,
      tone: p.tone,
      heat,
    };
  });
}

function mapHourBuckets(buckets: TodayDashboardResponse["hourBuckets"] | undefined): TodayHourBucket[] {
  if (!buckets || buckets.length === 0) {
    return Array.from({ length: 24 }, (_, hour) => ({ hour, leadsIn: 0, repliesOut: 0 }));
  }
  return buckets.map((b) => ({ hour: b.hour, leadsIn: b.leadsIn, repliesOut: b.repliesOut }));
}

function mapDayBuckets(buckets: TodayDashboardResponse["dayBuckets"] | undefined): TodayDayBucket[] {
  if (!buckets || buckets.length === 0) return [];
  return buckets.map((b) => ({
    label: b.label,
    leadsIn: b.leadsIn,
    repliesOut: b.repliesOut,
    deals: b.dealsAdvanced,
  }));
}

function mapScheduled(jobs: CronJob[] | undefined): TodayScheduledJob[] {
  if (!jobs || jobs.length === 0) return [];
  return jobs.slice(0, 6).map((j) => ({
    id: j.id,
    name: j.name || j.prompt.slice(0, 60),
    fires: formatCronFires(j),
    schedule: cronScheduleExpr(j),
    meta: cronMeta(j),
  }));
}

function mapLive(
  sessions: SessionInfo[] | undefined,
  running: TodayDashboardResponse["running"] | undefined,
): TodayLiveItem[] {
  const items: TodayLiveItem[] = [];
  if (sessions) {
    for (const s of sessions.slice(0, 4)) {
      items.push({
        id: `session-${s.id}`,
        kind: "session",
        title: s.title || s.preview?.slice(0, 60) || "Active session",
        meta: `${ageShort(s.last_active * 1000)} ago · ${s.message_count} msg`,
        tone: "ok",
      });
    }
  }
  if (running) {
    for (const r of running.slice(0, 4)) {
      items.push({
        id: `run-${r.id}`,
        kind: "action",
        title: r.registryName || r.skill || "Action run",
        meta: `${r.status} · ${ageShort(r.startedAt ?? r.createdAt)}`,
        tone: r.status === "error" || r.status === "failed" ? "error" : "work",
      });
    }
  }
  return items;
}

function computePipeline(
  pulse: TodayPulseStat[],
  drafts: SourceInboxDraft[],
  deals: AdminDeal[],
  events: AdminUpcomingEvent[],
): TodayPipelineStage[] {
  const leadsIn = pulse.find((p) => /leads in/i.test(p.label))?.value;
  const repliesOut = pulse.find((p) => /replies/i.test(p.label))?.value;
  const todayStart = startOfLocalDay();
  const todayEnd = todayStart + DAY_MS;
  const showingsToday = events.filter((e) => {
    if (!e.startAt) return false;
    const t = Date.parse(e.startAt);
    return Number.isFinite(t) && t >= todayStart && t < todayEnd && eventKind(e.kind) === "showing";
  }).length;
  const offers = deals.filter((d) => (d.currentStage ?? 0) >= 4 && (d.currentStage ?? 0) <= 7 && d.status === "active").length;
  const closes = deals.filter((d) => d.closedAt && Date.parse(d.closedAt) >= todayStart).length;
  const pendingDrafts = drafts.filter((d) => d.status === "pending").length;

  return [
    {
      id: "leads",
      label: "Leads in",
      value: Number(leadsIn ?? 0) || 0,
      delta: "—",
      deltaTone: "flat",
      tone: "info",
    },
    {
      id: "replies",
      label: "Replies sent",
      value: Number(repliesOut ?? 0) || 0,
      delta: pendingDrafts > 0 ? `${pendingDrafts} queued` : "—",
      deltaTone: pendingDrafts > 0 ? "flat" : "flat",
      tone: "buyer",
    },
    {
      id: "showings",
      label: "Showings set",
      value: showingsToday,
      delta: "—",
      deltaTone: "flat",
      tone: "active",
    },
    {
      id: "offers",
      label: "Offers in flight",
      value: offers,
      delta: "—",
      deltaTone: "flat",
      tone: "warn",
    },
    {
      id: "closes",
      label: "Closes today",
      value: closes,
      delta: "—",
      deltaTone: "flat",
      tone: closes > 0 ? "good" : "muted",
    },
  ];
}

function mapDrafts(drafts: SourceInboxDraft[]): TodayDraft[] {
  return drafts
    .filter((d) => d.status === "pending")
    .slice(0, 6)
    .map((d) => ({
      id: d.id,
      to: d.personName || "Unknown",
      handle: d.contactId || d.threadId || d.taskId,
      channel: d.sourceLabel || d.channel || d.sourceId,
      preview: (d.draftText || "").slice(0, 220),
      age: ageShort(d.latestAt) || "—",
      confidence: typeof d.score === "number" ? Math.round(d.score * 100) : null,
      intent: d.scoreReason || d.title || "Reply ready",
      heat: heatScore(d),
    }));
}

function mapCalendar(events: AdminUpcomingEvent[]): TodayCalendarEvent[] {
  const todayStart = startOfLocalDay();
  const todayEnd = todayStart + DAY_MS;
  return events
    .filter((e) => {
      if (!e.startAt) return false;
      const t = Date.parse(e.startAt);
      return Number.isFinite(t) && t >= todayStart && t < todayEnd;
    })
    .sort((a, b) => Date.parse(a.startAt!) - Date.parse(b.startAt!))
    .slice(0, 6)
    .map((e) => ({
      id: e.id,
      time: formatEventTime(e.startAt),
      duration: eventDuration(e.startAt, e.endAt) || "—",
      kind: eventKind(e.kind),
      title: e.title,
      sub: e.location || e.address || (e.source === "gcal" ? "Calendar event" : "Deal event"),
      status: e.kind === "appointment" ? "confirmed" : e.kind || "scheduled",
    }));
}

function mapSources(
  inbox: ReturnType<typeof useRealEstateHubData>["sourceInbox"],
  jobs: CronJob[],
): TodaySources {
  const channels: TodaySourceItem[] = (inbox?.sources ?? []).slice(0, 6).map((s) => {
    let status: TodaySourceItem["status"] = "live";
    if (s.blocked) status = "blocked";
    else if (s.state === "error" || s.lastError) status = "error";
    const detail = s.lastError ? s.lastError.slice(0, 80) : s.state === "connected" ? "Connected" : s.state || "—";
    return {
      id: s.id,
      name: s.label || s.id,
      kind: s.id,
      status,
      detail,
    };
  });

  const schedules: TodaySourceItem[] = jobs
    .filter((j) => j.skill === "outreach" || /outreach|watch|follow|private/i.test(j.name || j.prompt))
    .slice(0, 4)
    .map((j) => {
      let status: TodaySourceItem["status"] = "live";
      if (!j.enabled || j.state === "paused") status = "blocked";
      else if (j.state === "error" || j.alignment_status === "blocked") status = "error";
      const detail = j.last_run_at
        ? `Last run ${ageShort(j.last_run_at)} ago`
        : j.schedule_display || j.state;
      return {
        id: j.id,
        name: j.name || j.prompt.slice(0, 40),
        status,
        detail,
      };
    });

  return { channels, schedules };
}

function mapAgentRuns(running: TodayDashboardResponse["running"] | undefined): TodayAgentRun[] {
  if (!running) return [];
  return running.slice(0, 8).map((r) => {
    let tone: TodayAgentRun["tone"] = "ok";
    if (r.status === "error" || r.status === "failed") tone = "error";
    else if (r.status === "waiting_human" || r.status === "blocked" || r.status === "needs_input") tone = "warn";
    return {
      id: r.id,
      title: r.registryName || r.skill || "Action run",
      age: `${ageShort(r.completedAt ?? r.updatedAt ?? r.startedAt ?? r.createdAt)} ago`,
      kind: r.skill || r.status,
      messages: 0,
      tools: 0,
      tone,
    };
  });
}

function mapDeals(deals: AdminDeal[]): TodayDeal[] {
  return deals
    .filter((d) => d.status === "active")
    .slice(0, 6)
    .map((d) => {
      const stage = d.currentStage ?? 0;
      const sideKey: "listing" | "buyer" = d.side === "listing" ? "listing" : "buyer";
      const phaseLabel = STAGE_LABELS[Math.max(0, Math.min(STAGE_LABELS.length - 1, stage))]?.[sideKey === "listing" ? 0 : 1] || "Stage";
      let tone: TodayDeal["tone"] = "ok";
      if (stage <= 1) tone = "muted";
      else if (stage >= 8) tone = "good";
      else if (stage >= 4) tone = "warn";
      return {
        id: d.id,
        side: sideKey === "listing" ? "seller" : "buyer",
        address: d.listingAddress || d.title || "Untitled",
        client: d.title || "—",
        phase: phaseLabel,
        phaseIdx: stage + 1,
        phaseTotal: STAGE_TOTAL,
        next: phaseLabel,
        nextWhen: d.stageEnteredAt ? ageShort(d.stageEnteredAt) : "—",
        progress: (stage + 1) / STAGE_TOTAL,
        tone,
      };
    });
}

function mapWins(
  pulse: TodayPulseStat[],
  drafts: SourceInboxDraft[],
  events: AdminUpcomingEvent[],
  deals: AdminDeal[],
): TodayWin[] {
  const todayStart = startOfLocalDay();
  const todayEnd = todayStart + DAY_MS;

  const showingsBooked = events.filter((e) => {
    if (!e.startAt) return false;
    const t = Date.parse(e.startAt);
    return Number.isFinite(t) && t >= todayStart && t < todayEnd && eventKind(e.kind) === "showing";
  }).length;

  const approvedDrafts = drafts.filter((d) => d.status === "approved").length;
  const repliesOut = Number(pulse.find((p) => /replies/i.test(p.label))?.value ?? 0);
  const dealsAdvanced = deals.filter((d) => {
    if (!d.stageEnteredAt) return false;
    const t = Date.parse(d.stageEnteredAt);
    return Number.isFinite(t) && t >= todayStart;
  }).length;

  return [
    { id: "w1", icon: "calendar", title: "Showings booked", value: showingsBooked, sub: "Today's calendar" },
    { id: "w2", icon: "check", title: "Drafts approved", value: approvedDrafts, sub: "Outreach lanes" },
    { id: "w3", icon: "arrow", title: "Deals advanced", value: dealsAdvanced, sub: "Stage progression" },
    { id: "w4", icon: "spark", title: "Replies sent", value: repliesOut, sub: "Multi-channel" },
  ];
}

function mapSourceBreakdown(threads: SourceInboxThread[]): TodaySourceBreakdown {
  const todayStart = startOfLocalDay();
  const counts = new Map<string, { label: string; count: number }>();
  let total = 0;
  for (const t of threads) {
    if (t.direction !== "inbound") continue;
    if (!t.latestAt) continue;
    const ts = Date.parse(t.latestAt);
    if (!Number.isFinite(ts) || ts < todayStart) continue;
    total += 1;
    const key = t.sourceId || "unknown";
    const label = t.sourceLabel || t.sourceId || "Unknown";
    const entry = counts.get(key) || { label, count: 0 };
    entry.count += 1;
    counts.set(key, entry);
  }
  const channels = Array.from(counts.entries())
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 6)
    .map(([id, v]) => ({ id, label: v.label, count: v.count, share: total > 0 ? v.count / total : 0 }));
  return { total, channels };
}

function greetingFromEmail(email: string | null | undefined): string {
  if (!email) return "there";
  const local = email.split("@")[0] || "";
  const first = local.split(/[._-]/)[0] || "";
  if (!first) return "there";
  return first.charAt(0).toUpperCase() + first.slice(1).toLowerCase();
}

export function TodayDesignShell() {
  const data = useRealEstateHubData();
  const [today, setToday] = useState<TodayDashboardResponse | null>(null);
  const [todayLoading, setTodayLoading] = useState(false);
  const [todayError, setTodayError] = useState<string | null>(null);
  const [deals, setDeals] = useState<AdminDeal[]>([]);
  const [events, setEvents] = useState<AdminUpcomingEvent[]>([]);
  const [greetingName, setGreetingName] = useState<string>("there");

  const loadToday = useCallback(async () => {
    setTodayLoading(true);
    setTodayError(null);
    try {
      const next = await api.getToday();
      setToday(next);
    } catch (err) {
      setTodayError(err instanceof Error ? err.message : "Today summary failed");
    } finally {
      setTodayLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadToday();
    api.getAdminDeals({ status: "active", limit: 50 })
      .then((res) => { if (!cancelled) setDeals(res.items ?? []); })
      .catch(() => { if (!cancelled) setDeals([]); });
    api.getAdminUpcomingEvents(7)
      .then((res) => { if (!cancelled) setEvents(res.items ?? []); })
      .catch(() => { if (!cancelled) setEvents([]); });
    api.getLicenseStatus()
      .then((res) => { if (!cancelled) setGreetingName(greetingFromEmail(res.email)); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [loadToday]);

  const threads = data.sourceInbox?.threads ?? [];
  const drafts = data.sourceInbox?.drafts ?? [];

  const pulse = useMemo(() => mapPulse(today?.pulse), [today?.pulse]);
  const priority = useMemo(() => mapPriority(today?.priority, drafts, threads), [today?.priority, drafts, threads]);
  const hourBuckets = useMemo(() => mapHourBuckets(today?.hourBuckets), [today?.hourBuckets]);
  const dayBuckets = useMemo(() => mapDayBuckets(today?.dayBuckets), [today?.dayBuckets]);
  const scheduled = useMemo(() => mapScheduled(today?.scheduled ?? data.cronJobs), [today?.scheduled, data.cronJobs]);
  const live = useMemo(() => mapLive(today?.live ?? data.sessions, today?.running), [today?.live, today?.running, data.sessions]);
  const pipeline = useMemo(() => computePipeline(pulse, drafts, deals, events), [pulse, drafts, deals, events]);
  const draftCards = useMemo(() => mapDrafts(drafts), [drafts]);
  const calendar = useMemo(() => mapCalendar(events), [events]);
  const sources = useMemo(() => mapSources(data.sourceInbox, data.cronJobs), [data.sourceInbox, data.cronJobs]);
  const runs = useMemo(() => mapAgentRuns(today?.running ?? data.actionRuns), [today?.running, data.actionRuns]);
  const dealCards = useMemo(() => mapDeals(deals), [deals]);
  const wins = useMemo(() => mapWins(pulse, drafts, events, deals), [pulse, drafts, events, deals]);
  const sourceBreakdown = useMemo(() => mapSourceBreakdown(threads), [threads]);

  const handleRefresh = useCallback(async () => {
    await Promise.all([
      data.refresh({ force: true }),
      loadToday(),
      api.getAdminDeals({ status: "active", limit: 50 })
        .then((res) => setDeals(res.items ?? []))
        .catch(() => {}),
      api.getAdminUpcomingEvents(7)
        .then((res) => setEvents(res.items ?? []))
        .catch(() => {}),
    ]);
  }, [data, loadToday]);

  const handleDraftAction = useCallback<NonNullable<TodayBoardProps["onDraftAction"]>>(
    async (action, draftId) => {
      const draft = drafts.find((d) => d.id === draftId);
      if (!draft) return;
      try {
        const res = await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, action);
        data.setSourceInbox(res);
      } catch (err) {
        console.error("today draft action failed", err);
      }
    },
    [drafts, data],
  );

  const rootAttrs = {
    "data-accent": "graphite" as const,
    "data-density": "compact" as const,
    "data-dots": "smart" as const,
    "data-active-row": "fill" as const,
    "data-sections": "micro" as const,
    "data-artifacts": "hidden" as const,
  };

  return (
    <div className="app today-design-embedded" {...rootAttrs}>
      <TodayBoard
        greetingName={greetingName}
        pulse={pulse}
        priority={priority}
        hourBuckets={hourBuckets}
        dayBuckets={dayBuckets}
        scheduled={scheduled}
        live={live}
        pipeline={pipeline}
        drafts={draftCards}
        calendar={calendar}
        sources={sources}
        runs={runs}
        deals={dealCards}
        wins={wins}
        sourceBreakdown={sourceBreakdown}
        loading={todayLoading || data.loading}
        error={todayError}
        onRefresh={handleRefresh}
        onDraftAction={handleDraftAction}
      />
    </div>
  );
}

export default TodayDesignShell;
