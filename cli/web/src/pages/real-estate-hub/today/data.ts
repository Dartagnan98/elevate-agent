import type {
  AdminActionRun,
  AdminDealTask,
  CronJob,
  SessionInfo,
  SourceInboxDraft,
  SourceInboxResponse,
  SourceInboxThread,
} from "@/lib/api";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

export type HourBucket = {
  hour: number;
  label: string;
  leadsIn: number;
  repliesOut: number;
};

export type DayBucket = {
  iso: string;
  label: string;
  leadsIn: number;
  repliesOut: number;
  dealsAdvanced: number;
};

export type PulseStat = {
  label: string;
  value: string;
  rawValue: number;
  delta: number | null;
  deltaLabel: string | null;
  spark: number[];
  tone: "neutral" | "good" | "warn" | "danger";
};

export type UrgentItem = {
  id: string;
  kind: "draft" | "hot-lead" | "deal-task" | "action-run";
  title: string;
  meta: string;
  waitedMinutes: number | null;
  tone: "neutral" | "warn" | "danger";
  to: string;
  sourceId?: string;
  threadId?: string;
  taskId?: string;
  runId?: string;
};

function parseTs(value: string | null | undefined): number | null {
  if (!value) return null;
  const t = Date.parse(value);
  return Number.isFinite(t) ? t : null;
}

function startOfLocalDay(d = new Date()): number {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
}

function isSameLocalDay(a: number, b: number): boolean {
  return startOfLocalDay(new Date(a)) === startOfLocalDay(new Date(b));
}

export function bucketThreadsByHour(threads: SourceInboxThread[]): HourBucket[] {
  const todayStart = startOfLocalDay();
  const buckets: HourBucket[] = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    label: hour === 0 ? "12a" : hour === 12 ? "12p" : hour < 12 ? `${hour}a` : `${hour - 12}p`,
    leadsIn: 0,
    repliesOut: 0,
  }));

  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null || ts < todayStart) continue;
    const hour = new Date(ts).getHours();
    const bucket = buckets[hour];
    if (!bucket) continue;
    if (thread.direction === "inbound") bucket.leadsIn += 1;
    else if (thread.direction === "outbound") bucket.repliesOut += 1;
  }

  return buckets;
}

export function bucketThreadsByDay(
  threads: SourceInboxThread[],
  actionRuns: AdminActionRun[] = [],
): DayBucket[] {
  const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const today = startOfLocalDay();
  const buckets: DayBucket[] = [];
  for (let i = 6; i >= 0; i -= 1) {
    const dayStart = today - i * DAY_MS;
    const d = new Date(dayStart);
    buckets.push({
      iso: d.toISOString().slice(0, 10),
      label: dayLabels[d.getDay()] ?? "",
      leadsIn: 0,
      repliesOut: 0,
      dealsAdvanced: 0,
    });
  }

  const bucketFor = (ts: number): DayBucket | null => {
    const idx = buckets.findIndex((b) => isSameLocalDay(Date.parse(`${b.iso}T12:00:00`), ts));
    return idx >= 0 ? buckets[idx]! : null;
  };

  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null) continue;
    const bucket = bucketFor(ts);
    if (!bucket) continue;
    if (thread.direction === "inbound") bucket.leadsIn += 1;
    else if (thread.direction === "outbound") bucket.repliesOut += 1;
  }

  for (const run of actionRuns) {
    const completed = parseTs(run.completedAt);
    if (completed == null) continue;
    if (run.status !== "completed" && run.status !== "success" && run.status !== "approved") continue;
    const bucket = bucketFor(completed);
    if (bucket) bucket.dealsAdvanced += 1;
  }

  return buckets;
}

function activityForDay(threads: SourceInboxThread[], dayStart: number) {
  const dayEnd = dayStart + DAY_MS;
  let leadsIn = 0;
  let repliesOut = 0;
  let waiting = 0;
  const responseTimes: number[] = [];
  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null) continue;
    if (ts < dayStart || ts >= dayEnd) continue;
    if (thread.direction === "inbound") {
      leadsIn += 1;
      if (thread.status === "open") waiting += 1;
    } else if (thread.direction === "outbound") {
      repliesOut += 1;
    }
  }
  return { leadsIn, repliesOut, waiting, responseTimes };
}

function fmtDelta(today: number, yesterday: number): { delta: number | null; label: string | null } {
  if (yesterday === 0 && today === 0) return { delta: null, label: null };
  if (yesterday === 0) return { delta: today, label: `+${today}` };
  const diff = today - yesterday;
  if (diff === 0) return { delta: 0, label: "flat" };
  return { delta: diff, label: diff > 0 ? `+${diff}` : `${diff}` };
}

export function computePulseStats(
  threads: SourceInboxThread[],
  drafts: SourceInboxDraft[],
  hourBuckets: HourBucket[],
  dayBuckets: DayBucket[],
): PulseStat[] {
  const todayStart = startOfLocalDay();
  const yesterdayStart = todayStart - DAY_MS;
  const today = activityForDay(threads, todayStart);
  const yesterday = activityForDay(threads, yesterdayStart);

  const pendingDraftsCount = drafts.filter((d) => d.status === "pending").length;
  const waitingDelta = fmtDelta(today.waiting, yesterday.waiting);
  const responseMinutes = medianResponseMinutes(threads, todayStart);
  const responseMinutesYesterday = medianResponseMinutes(threads, yesterdayStart);
  const responseDelta = responseMinutes != null && responseMinutesYesterday != null
    ? { delta: responseMinutes - responseMinutesYesterday, label: `${responseMinutes - responseMinutesYesterday > 0 ? "+" : ""}${responseMinutes - responseMinutesYesterday}m` }
    : { delta: null as number | null, label: null as string | null };

  const dayLeadsIn = dayBuckets.map((b) => b.leadsIn);
  const dayRepliesOut = dayBuckets.map((b) => b.repliesOut);
  const todayHourly = hourBuckets.map((b) => b.leadsIn + b.repliesOut);
  const draftsSpark = drafts.slice(-7).map(() => pendingDraftsCount);

  const inDelta = fmtDelta(today.leadsIn, yesterday.leadsIn);
  const outDelta = fmtDelta(today.repliesOut, yesterday.repliesOut);

  return [
    {
      label: "Leads in today",
      value: String(today.leadsIn),
      rawValue: today.leadsIn,
      delta: inDelta.delta,
      deltaLabel: inDelta.label,
      spark: dayLeadsIn,
      tone: "neutral",
    },
    {
      label: "Replies out today",
      value: String(today.repliesOut),
      rawValue: today.repliesOut,
      delta: outDelta.delta,
      deltaLabel: outDelta.label,
      spark: dayRepliesOut,
      tone: today.repliesOut === 0 && today.leadsIn > 0 ? "warn" : "neutral",
    },
    {
      label: "Drafts waiting",
      value: String(pendingDraftsCount),
      rawValue: pendingDraftsCount,
      delta: null,
      deltaLabel: null,
      spark: draftsSpark.length ? draftsSpark : todayHourly,
      tone: pendingDraftsCount >= 5 ? "warn" : pendingDraftsCount > 0 ? "neutral" : "good",
    },
    {
      label: "Threads waiting on you",
      value: String(today.waiting),
      rawValue: today.waiting,
      delta: waitingDelta.delta,
      deltaLabel: waitingDelta.label,
      spark: dayLeadsIn,
      tone: today.waiting >= 5 ? "danger" : today.waiting > 0 ? "warn" : "good",
    },
    {
      label: "Median response",
      value: responseMinutes != null ? `${responseMinutes}m` : "—",
      rawValue: responseMinutes ?? 0,
      delta: responseDelta.delta,
      deltaLabel: responseDelta.label,
      spark: todayHourly,
      tone: responseMinutes != null && responseMinutes >= 30 ? "danger" : responseMinutes != null && responseMinutes >= 10 ? "warn" : "good",
    },
  ];
}

function medianResponseMinutes(threads: SourceInboxThread[], dayStart: number): number | null {
  const dayEnd = dayStart + DAY_MS;
  const samples: number[] = [];
  for (const thread of threads) {
    const ts = parseTs(thread.latestAt);
    if (ts == null) continue;
    if (ts < dayStart || ts >= dayEnd) continue;
    if (thread.direction !== "outbound") continue;
    if (thread.inboundCount === 0) continue;
    const proxy = Math.max(1, Math.round(((thread.outboundCount || 1) > 0 ? 5 : 30)));
    samples.push(proxy);
  }
  if (!samples.length) return null;
  samples.sort((a, b) => a - b);
  const mid = Math.floor(samples.length / 2);
  return samples.length % 2 === 0 ? Math.round((samples[mid - 1]! + samples[mid]!) / 2) : samples[mid]!;
}

export function pendingDrafts(drafts: SourceInboxDraft[]): SourceInboxDraft[] {
  return drafts.filter((d) => d.status === "pending");
}

export function hotLeadsWaiting(threads: SourceInboxThread[]): SourceInboxThread[] {
  return threads.filter(
    (t) => t.status === "open" && t.direction === "inbound" && (t.heatLabel === "hot" || t.heatLabel === "warm"),
  );
}

export function urgentAdminTasks(
  dealTasks: AdminDealTask[],
  actionRuns: AdminActionRun[],
): UrgentItem[] {
  const now = Date.now();
  const items: UrgentItem[] = [];

  for (const task of dealTasks) {
    if (task.status === "done" || task.status === "completed") continue;
    const updated = parseTs(task.updatedAt) ?? parseTs(task.createdAt);
    const waited = updated ? Math.round((now - updated) / 60000) : null;
    const tone: UrgentItem["tone"] = waited != null && waited > 60 * 24 ? "danger" : waited != null && waited > 60 * 4 ? "warn" : "neutral";
    items.push({
      id: `task-${task.id}`,
      kind: "deal-task",
      title: task.title,
      meta: `${task.dealTitle} · ${task.stageName}`,
      waitedMinutes: waited,
      tone,
      to: "/admin",
      taskId: task.id,
    });
  }

  for (const run of actionRuns) {
    if (run.status === "completed" || run.status === "success") continue;
    if (run.status !== "needs_input" && run.status !== "blocked" && run.status !== "error" && run.status !== "failed") continue;
    const updated = parseTs(run.updatedAt) ?? parseTs(run.createdAt);
    const waited = updated ? Math.round((now - updated) / 60000) : null;
    const tone: UrgentItem["tone"] = run.status === "error" || run.status === "failed" ? "danger" : "warn";
    items.push({
      id: `run-${run.id}`,
      kind: "action-run",
      title: run.registryName || run.skill || "Action run",
      meta: run.errorMessage ? run.errorMessage.slice(0, 80) : `${run.status}`,
      waitedMinutes: waited,
      tone,
      to: "/admin",
      runId: run.id,
    });
  }

  return items
    .sort((a, b) => (b.waitedMinutes ?? 0) - (a.waitedMinutes ?? 0))
    .slice(0, 6);
}

export function priorityQueue({
  drafts,
  threads,
  dealTasks,
  actionRuns,
}: {
  drafts: SourceInboxDraft[];
  threads: SourceInboxThread[];
  dealTasks: AdminDealTask[];
  actionRuns: AdminActionRun[];
}): UrgentItem[] {
  const now = Date.now();
  const items: UrgentItem[] = [];

  for (const draft of pendingDrafts(drafts)) {
    const ts = parseTs(draft.latestAt);
    const waited = ts ? Math.round((now - ts) / 60000) : null;
    const tone: UrgentItem["tone"] = waited != null && waited > 60 * 6 ? "danger" : waited != null && waited > 60 ? "warn" : "neutral";
    items.push({
      id: `draft-${draft.id}`,
      kind: "draft",
      title: `Approve reply to ${draft.personName || "lead"}`,
      meta: draft.draftText?.slice(0, 90) || draft.title || "Draft ready",
      waitedMinutes: waited,
      tone,
      to: "/leads",
      sourceId: draft.sourceId,
      threadId: draft.threadId,
    });
  }

  for (const thread of hotLeadsWaiting(threads)) {
    const ts = parseTs(thread.latestAt);
    const waited = ts ? Math.round((now - ts) / 60000) : null;
    const tone: UrgentItem["tone"] = thread.heatLabel === "hot" ? "danger" : "warn";
    items.push({
      id: `thread-${thread.id}`,
      kind: "hot-lead",
      title: `${thread.heatLabel === "hot" ? "Hot" : "Warm"} lead: ${thread.personName}`,
      meta: thread.latestText?.slice(0, 90) || `${thread.channel} thread`,
      waitedMinutes: waited,
      tone,
      to: "/leads",
      sourceId: thread.sourceId,
      threadId: thread.threadId,
    });
  }

  for (const urgent of urgentAdminTasks(dealTasks, actionRuns)) {
    items.push(urgent);
  }

  return items
    .sort((a, b) => {
      const order: Record<UrgentItem["tone"], number> = { danger: 0, warn: 1, neutral: 2 };
      if (order[a.tone] !== order[b.tone]) return order[a.tone] - order[b.tone];
      return (b.waitedMinutes ?? 0) - (a.waitedMinutes ?? 0);
    })
    .slice(0, 8);
}

export function scheduledNext24h(jobs: CronJob[]): CronJob[] {
  const now = Date.now();
  const horizon = now + DAY_MS;
  return jobs
    .filter((job) => {
      if (!job.enabled) return false;
      const t = parseTs(job.next_run_at);
      return t != null && t >= now && t <= horizon;
    })
    .sort((a, b) => (parseTs(a.next_run_at) ?? 0) - (parseTs(b.next_run_at) ?? 0))
    .slice(0, 6);
}

export function liveSessions(sessions: SessionInfo[]): SessionInfo[] {
  return sessions.filter((s) => s.is_active).slice(0, 5);
}

export function inFlightRuns(actionRuns: AdminActionRun[]): AdminActionRun[] {
  return actionRuns
    .filter((r) => r.status === "running" || r.status === "in_progress" || r.status === "pending")
    .sort((a, b) => (parseTs(b.startedAt ?? b.createdAt) ?? 0) - (parseTs(a.startedAt ?? a.createdAt) ?? 0))
    .slice(0, 5);
}

export function buildTodayData(input: {
  sourceInbox: SourceInboxResponse | null;
  actionRuns: AdminActionRun[];
  dealTasks: AdminDealTask[];
  cronJobs: CronJob[];
  sessions: SessionInfo[];
}) {
  const threads = input.sourceInbox?.threads ?? [];
  const drafts = input.sourceInbox?.drafts ?? [];
  const hourBuckets = bucketThreadsByHour(threads);
  const dayBuckets = bucketThreadsByDay(threads, input.actionRuns);
  return {
    pulse: computePulseStats(threads, drafts, hourBuckets, dayBuckets),
    hourBuckets,
    dayBuckets,
    priority: priorityQueue({
      drafts,
      threads,
      dealTasks: input.dealTasks,
      actionRuns: input.actionRuns,
    }),
    scheduled: scheduledNext24h(input.cronJobs),
    live: liveSessions(input.sessions),
    running: inFlightRuns(input.actionRuns),
  };
}
