import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import DealDetailModal, { type Deal as AdminModalDeal } from "../../admin/components/deal-modal";
import { ADMIN_PIPELINE, ADMIN_BUYER_PIPELINE } from "../../admin/admin-data";
import type { AdminDeal } from "@/lib/api-types";

// Build the Admin DealDetailModal `Deal` from a raw AdminDeal. `currentStage`
// is 0-based; the modal does pipeline.find(p => p.id === deal.phase), so phase
// MUST be a real pipeline id, not a display label, or it always opens stage 1.
function adminDealToModalDeal(d: AdminDeal): AdminModalDeal {
  const isBuyer = d.side === "buyer";
  const pipeline = isBuyer ? ADMIN_BUYER_PIPELINE : ADMIN_PIPELINE;
  const idx = Math.max(0, Math.min(pipeline.length - 1, d.currentStage ?? 0));
  const phase = pipeline[idx]?.id || pipeline[0].id;
  const addr = d.listingAddress || d.title || "Untitled deal";
  return {
    id: d.id,
    phase,
    addr,
    line2: d.listingAddress && d.title && d.listingAddress !== d.title ? d.title : (d.province || ""),
    badge: pipeline[idx]?.name || "Stage",
    next: pipeline[idx]?.next || "",
    side: d.side, // "listing" | "buyer" — modal only branches on === "buyer"
  };
}

// Fallback when a TodayDeal has no matching AdminDeal: build a minimal modal
// Deal from the TodayDeal fields, defaulting to the first pipeline phase.
function todayDealToModalDeal(d: TodayDeal): AdminModalDeal {
  const modalSide = d.side === "seller" ? "listing" : "buyer";
  const pipeline = modalSide === "buyer" ? ADMIN_BUYER_PIPELINE : ADMIN_PIPELINE;
  return {
    id: d.id,
    phase: pipeline[0].id,
    addr: d.address,
    line2: d.client,
    badge: d.phase,
    next: d.next,
    side: modalSide,
  };
}

export type TodayPulseStat = {
  id: string;
  label: string;
  value: string | number;
  delta?: number | null;
  deltaLabel?: string;
  tone?: "good" | "warn" | "danger" | "neutral";
  spark: number[];
  sub?: string;
};

export type TodayPriorityItem = {
  id: string;
  kind: "draft" | "hot-lead" | "deal-task" | "action-run";
  title: string;
  meta: string;
  tone?: "good" | "warn" | "danger" | "neutral";
  waitedMinutes?: number | null;
  heat?: number | null;
};

export type TodayHourBucket = { hour: number; leadsIn: number; repliesOut: number };
export type TodayDayBucket = { label: string; leadsIn: number; repliesOut: number; deals: number };

export type TodayScheduledJob = { id: string; name: string; fires: string; schedule: string; meta: string };
export type TodayLiveItem = { id: string; kind: string; title: string; meta: string; tone?: string };

export type TodayPipelineStage = {
  id: string;
  label: string;
  value: number;
  delta: string;
  deltaTone: string;
  tone: string;
};

export type TodayDraft = {
  id: string;
  to: string;
  handle: string;
  channel: string;
  preview: string;
  age: string;
  confidence: number | null;
  intent: string;
  heat: number | null;
};

export type TodayCalendarEvent = {
  id: string;
  time: string;
  duration: string;
  kind: "showing" | "meeting" | "cma" | "callback";
  title: string;
  sub: string;
  status: string;
};

export type TodaySourceItem = {
  id: string;
  name: string;
  status: "live" | "error" | "blocked" | string;
  detail: string;
  kind?: string;
};
export type TodaySources = { channels: TodaySourceItem[]; schedules: TodaySourceItem[] };

export type TodayAgentRun = {
  id: string;
  title: string;
  age: string;
  kind: string;
  messages: number;
  tools: number;
  tone?: "ok" | "warn" | "error";
};

export type TodayDeal = {
  id: string;
  side: "buyer" | "seller";
  address: string;
  client: string;
  phase: string;
  phaseIdx: number;
  phaseTotal: number;
  next: string;
  nextWhen: string;
  progress: number;
  tone?: "good" | "warn" | "ok" | "muted";
};

export type TodayWin = { id: string; icon: "calendar" | "check" | "arrow" | "spark"; title: string; sub: string; value: number };

export type TodaySourceBreakdown = {
  total: number;
  channels: { id: string; label: string; count: number; share: number }[];
};

export type TodayBoardProps = {
  greeting?: string;
  greetingName?: string;
  greetingSub?: string;
  pulse: TodayPulseStat[];
  priority: TodayPriorityItem[];
  hourBuckets: TodayHourBucket[];
  dayBuckets: TodayDayBucket[];
  scheduled: TodayScheduledJob[];
  live: TodayLiveItem[];
  pipeline: TodayPipelineStage[];
  drafts: TodayDraft[];
  calendar: TodayCalendarEvent[];
  sources: TodaySources;
  runs: TodayAgentRun[];
  deals: TodayDeal[];
  adminDealsById?: Map<string, AdminDeal>;
  wins: TodayWin[];
  sourceBreakdown: TodaySourceBreakdown;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  onDraftAction?: (action: "approve" | "skip", draftId: string) => void | Promise<void>;
  themeControl?: ReactNode;
};

function greetingForNow(): string {
  const h = new Date().getHours();
  if (h < 5) return "Late night";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  if (h < 21) return "Good evening";
  return "Late night";
}

function fmtTodayDate(): string {
  const d = new Date();
  const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()];
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
  return `${dow}, ${mon} ${d.getDate()}`;
}

function fmtWait(mins: number | null | undefined): string {
  if (mins == null) return "";
  if (mins < 1) return "now";
  if (mins < 60) return mins + "m";
  const h = Math.floor(mins / 60);
  if (h < 24) return h + "h";
  return Math.floor(h / 24) + "d";
}

const PRIORITY_LABEL: Record<TodayPriorityItem["kind"], string> = {
  draft: "Draft",
  "hot-lead": "Lead",
  "deal-task": "Admin",
  "action-run": "Action",
};

function PriorityIcon({ kind }: { kind: TodayPriorityItem["kind"] }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, width: 13, height: 13 };
  if (kind === "hot-lead") {
    return (
      <svg {...common}>
        <path d="M12 2c0 4-4 5-4 9a4 4 0 0 0 8 0c0-2-1-3-1-5" />
        <path d="M12 22a6 6 0 0 0 6-6c0-3-3-4-3-7" />
      </svg>
    );
  }
  if (kind === "deal-task") {
    return (
      <svg {...common}>
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    );
  }
  if (kind === "action-run") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M9 14l2 2 4-4" />
    </svg>
  );
}

function Sparkline({ values, tone }: { values: number[]; tone?: TodayPulseStat["tone"] }) {
  const w = 80, h = 22;
  const safe = values && values.length > 0 ? values : [0];
  const max = Math.max(1, ...safe);
  const stepX = safe.length > 1 ? w / (safe.length - 1) : w;
  const points = safe
    .map((v, i) => {
      const x = safe.length === 1 ? w / 2 : i * stepX;
      const y = h - (v / max) * (h - 3) - 1.5;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const area = `0,${h} ${points} ${w},${h}`;
  const colorMap: Record<string, string> = {
    danger: "var(--status-error)",
    warn: "var(--status-warn)",
    good: "var(--status-done)",
    neutral: "var(--fg-muted)",
  };
  const color = colorMap[tone || "neutral"] || colorMap.neutral;
  return (
    <svg className="td-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polygon fill={color} opacity="0.14" points={area} />
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" points={points} />
    </svg>
  );
}

function TodayPulse({ stats, greeting, name, sub, themeControl }: { stats: TodayPulseStat[]; greeting: string; name: string; sub: string; themeControl?: ReactNode }) {
  return (
    <section className="td-pulse" aria-label="Today pulse">
      <header className="td-pulse-head">
        <div>
          <h2 className="td-pulse-greet">{greeting}, {name}</h2>
          <p className="td-pulse-sub">{sub}</p>
        </div>
        {themeControl}
      </header>
      <div className="td-pulse-grid">
        {stats.map((s) => (
          <PulseCard key={s.id} stat={s} />
        ))}
      </div>
    </section>
  );
}

function PulseCard({ stat }: { stat: TodayPulseStat }) {
  const deltaCls = stat.delta == null
    ? "neutral"
    : stat.delta > 0
      ? "up"
      : stat.delta < 0 && stat.tone === "warn"
        ? "warn"
        : stat.delta < 0
          ? "down"
          : "neutral";
  return (
    <div className={"td-pulse-card td-tone-" + (stat.tone || "neutral")}>
      <div className="td-pulse-card-top">
        <span className="td-pulse-card-label mono">{stat.label}</span>
        {stat.deltaLabel && (
          <span className={"td-pulse-card-delta mono " + deltaCls}>{stat.deltaLabel}</span>
        )}
      </div>
      <div className="td-pulse-card-mid">
        <span className="td-pulse-card-value">{stat.value}</span>
        <Sparkline values={stat.spark} tone={stat.tone} />
      </div>
      {stat.sub && <div className="td-pulse-card-sub">{stat.sub}</div>}
    </div>
  );
}

function PriorityQueue({ items }: { items: TodayPriorityItem[] }) {
  return (
    <section className="td-card td-priority" aria-label="Needs you now">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Needs you now</h3>
          <p className="td-card-sub">{items.length === 0 ? "Inbox is clear" : items.length + " waiting"}</p>
        </div>
        <Link to="/leads" className="td-card-link mono">
          Open leads
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      {items.length === 0 ? (
        <div className="td-priority-empty">Nothing waiting on you. Drafts auto-approve when nothing is flagged.</div>
      ) : (
        <ul className="td-priority-list">
          {items.map((it) => (
            <li key={it.id} className={"td-priority-row td-tone-" + (it.tone || "neutral")}>
              <span className="td-priority-icon" aria-hidden="true"><PriorityIcon kind={it.kind} /></span>
              <div className="td-priority-body">
                <div className="td-priority-title-row">
                  <span className="td-priority-title">{it.title}</span>
                  <span className="td-priority-kind mono">{PRIORITY_LABEL[it.kind]}</span>
                </div>
                <div className="td-priority-meta-row">
                  <span className="td-priority-meta">{it.meta}</span>
                  {it.waitedMinutes != null && (
                    <span className="td-priority-wait mono">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="10" height="10"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
                      {fmtWait(it.waitedMinutes)}
                    </span>
                  )}
                  {it.heat != null && (
                    <span className={"td-priority-heat mono " + (it.heat >= 80 ? "hot" : it.heat >= 50 ? "warm" : "cool")}>
                      {it.heat}
                    </span>
                  )}
                </div>
              </div>
              <span className="td-priority-chev" aria-hidden="true">›</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function HourlyChart({ buckets }: { buckets: TodayHourBucket[] }) {
  const totalIn = buckets.reduce((s, b) => s + b.leadsIn, 0);
  const totalOut = buckets.reduce((s, b) => s + b.repliesOut, 0);
  const max = Math.max(1, ...buckets.flatMap((b) => [b.leadsIn, b.repliesOut]));
  const w = 720, h = 200;
  const pad = { l: 24, r: 14, t: 16, b: 28 };
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const stepX = innerW / 23;
  const linePts = (key: "leadsIn" | "repliesOut") =>
    buckets.map((b, i) => {
      const x = pad.l + i * stepX;
      const y = pad.t + innerH - (b[key] / max) * innerH;
      return [x, y] as const;
    });
  const inPts = linePts("leadsIn");
  const outPts = linePts("repliesOut");
  const polyStr = (pts: readonly (readonly [number, number])[]) =>
    pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const areaStr = (pts: readonly (readonly [number, number])[]) =>
    `${pad.l},${pad.t + innerH} ${polyStr(pts)} ${pad.l + innerW},${pad.t + innerH}`;
  const hourLabels = [0, 6, 12, 18, 23];
  return (
    <div className="td-card td-hourly">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Today, hour by hour</h3>
          <p className="td-card-sub">Inbound vs outbound</p>
        </div>
        <div className="td-hourly-legend mono">
          <span className="td-hourly-legend-item"><i className="td-swatch in" />{totalIn} in</span>
          <span className="td-hourly-legend-item"><i className="td-swatch out" />{totalOut} out</span>
        </div>
      </header>
      <div className="td-hourly-chart-wrap">
        <svg className="td-hourly-svg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
          {[0.25, 0.5, 0.75].map((p) => (
            <line key={p} x1={pad.l} x2={pad.l + innerW} y1={pad.t + innerH * p} y2={pad.t + innerH * p}
              stroke="color-mix(in srgb, var(--fg) 6%, transparent)" strokeDasharray="2 4" />
          ))}
          <line x1={pad.l} x2={pad.l + innerW} y1={pad.t + innerH} y2={pad.t + innerH} stroke="color-mix(in srgb, var(--fg) 12%, transparent)" />
          <polygon fill="var(--status-info)" fillOpacity="0.14" points={areaStr(inPts)} />
          <polyline fill="none" stroke="var(--status-info)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" points={polyStr(inPts)} />
          <polygon fill="var(--fg-muted)" fillOpacity="0.08" points={areaStr(outPts)} />
          <polyline fill="none" stroke="var(--fg-muted)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" points={polyStr(outPts)} strokeDasharray="3 3" />
          {(() => {
            const peakIdx = buckets.reduce(
              (bestI, b, i, arr) => (arr[bestI].leadsIn + arr[bestI].repliesOut) >= (b.leadsIn + b.repliesOut) ? bestI : i,
              0,
            );
            const [x, y] = inPts[peakIdx];
            return <circle cx={x} cy={y} r="3" fill="var(--status-info)" stroke="var(--bg)" strokeWidth="1.5" />;
          })()}
          {hourLabels.map((hr) => {
            const x = pad.l + hr * stepX;
            return (
              <text key={hr} x={x} y={200 - 8} fontSize="9" fontFamily="Geist Mono, monospace" fill="var(--fg-faint)" textAnchor="middle" letterSpacing="0.06em">
                {hr === 0 ? "12A" : hr === 12 ? "12P" : hr === 23 ? "11P" : hr < 12 ? hr + "A" : hr - 12 + "P"}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function WeeklyChart({ buckets }: { buckets: TodayDayBucket[] }) {
  const max = Math.max(1, ...buckets.flatMap((b) => [b.leadsIn, b.repliesOut]));
  return (
    <div className="td-card td-weekly">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Last 7 days</h3>
          <p className="td-card-sub">Leads · replies · deals advanced</p>
        </div>
        <div className="td-hourly-legend mono">
          <span className="td-hourly-legend-item"><i className="td-swatch in" />In</span>
          <span className="td-hourly-legend-item"><i className="td-swatch out" />Out</span>
          <span className="td-hourly-legend-item"><i className="td-swatch deal" />Deals</span>
        </div>
      </header>
      <div className="td-weekly-grid">
        {buckets.map((b, i) => {
          const isToday = i === buckets.length - 1;
          return (
            <div key={b.label + i} className={"td-weekly-col" + (isToday ? " today" : "")}>
              <div className="td-weekly-bars">
                <div className="td-weekly-bar in" style={{ height: (b.leadsIn / max) * 100 + "%" }} />
                <div className="td-weekly-bar out" style={{ height: (b.repliesOut / max) * 100 + "%" }} />
                <div className="td-weekly-bar deal" style={{ height: (b.deals / max) * 100 + "%" }} />
              </div>
              <div className="td-weekly-label mono">{b.label}</div>
              <div className="td-weekly-num mono">{b.leadsIn}<span className="td-weekly-num-sep">/</span>{b.repliesOut}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DayShape({ hourBuckets, dayBuckets }: { hourBuckets: TodayHourBucket[]; dayBuckets: TodayDayBucket[] }) {
  return (
    <section className="td-dayshape" aria-label="Day shape">
      <HourlyChart buckets={hourBuckets} />
      <WeeklyChart buckets={dayBuckets} />
    </section>
  );
}

function ScheduledCard({ jobs }: { jobs: TodayScheduledJob[] }) {
  return (
    <div className="td-card">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="13" height="13" style={{ verticalAlign: "-2px", marginRight: 6 }}><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>
            Scheduled · next 24h
          </h3>
          <p className="td-card-sub">{jobs.length} upcoming</p>
        </div>
        <Link to="/admin" className="td-card-link mono">Open</Link>
      </header>
      <ul className="td-running-list">
        {jobs.map((j) => (
          <li key={j.id} className="td-running-row">
            <span className="td-running-dot" />
            <div className="td-running-body">
              <div className="td-running-title">{j.name}</div>
              <div className="td-running-meta mono">{j.fires} · {j.meta}</div>
            </div>
            <code className="td-running-cron mono">{j.schedule}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

function InFlightCard({ live }: { live: TodayLiveItem[] }) {
  const total = live.length;
  return (
    <div className="td-card">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" width="13" height="13" style={{ verticalAlign: "-2px", marginRight: 6 }}><path d="M22 12h-4l-3 8-6-16-3 8H2" /></svg>
            In flight
          </h3>
          <p className="td-card-sub">{total === 0 ? "Idle" : total + " running"}</p>
        </div>
        <Link to="/admin" className="td-card-link mono">Open</Link>
      </header>
      {total === 0 ? (
        <div className="td-priority-empty">No live sessions or running actions.</div>
      ) : (
        <ul className="td-running-list">
          {live.map((l) => (
            <li key={l.id} className="td-running-row">
              <span className={"td-running-dot " + (l.tone || "")} />
              <div className="td-running-body">
                <div className="td-running-title">{l.title}</div>
                <div className="td-running-meta mono">{l.meta}</div>
              </div>
              <span className="td-running-kind mono">{l.kind}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RunningStrip({ scheduled, live }: { scheduled: TodayScheduledJob[]; live: TodayLiveItem[] }) {
  return (
    <section className="td-running" aria-label="What's running">
      <ScheduledCard jobs={scheduled} />
      <InFlightCard live={live} />
    </section>
  );
}

function PipelineVelocity({ stages }: { stages: TodayPipelineStage[] }) {
  return (
    <section className="td-card td-pipeline" aria-label="Pipeline velocity today">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Pipeline velocity · today</h3>
          <p className="td-card-sub">Movement through each stage in the last 24h</p>
        </div>
        <Link to="/admin" className="td-card-link mono">7-day trend
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      <div className="td-pipeline-track">
        {stages.map((s, i) => {
          const prev = i > 0 ? stages[i - 1].value : null;
          const conv = prev != null && prev > 0 ? Math.round((s.value / prev) * 100) : null;
          const convTone = conv == null ? "" : conv >= 65 ? "good" : conv >= 30 ? "ok" : "low";
          return (
            <Fragment key={s.id}>
              {i > 0 && (
                <div className="td-pipeline-conv" aria-hidden="true">
                  <span className={"td-pipeline-conv-pct mono " + convTone}>{conv}%</span>
                  <svg viewBox="0 0 80 12" className="td-pipeline-conv-line" preserveAspectRatio="none">
                    <line x1="0" y1="6" x2="80" y2="6" stroke="currentColor" strokeWidth="1" strokeDasharray="2 3" />
                    <path d="M70 2l6 4-6 4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              )}
              <div className={"td-pipeline-stage td-tone-" + s.tone}>
                <div className="td-pipeline-stage-label mono">{s.label}</div>
                <div className="td-pipeline-stage-val">{s.value}</div>
                <div className={"td-pipeline-stage-delta mono " + s.deltaTone}>
                  {s.delta === "—" ? <span className="td-pipeline-stage-delta-neutral">no change</span> : s.delta + " vs yesterday"}
                </div>
              </div>
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}

function QuickApprovals({ drafts, onDraftAction }: { drafts: TodayDraft[]; onDraftAction?: TodayBoardProps["onDraftAction"] }) {
  const [skipped, setSkipped] = useState<Set<string>>(() => new Set());
  const [approved, setApproved] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const visible = drafts.filter((d) => !skipped.has(d.id) && !approved.has(d.id));

  const handle = async (action: "approve" | "skip", id: string) => {
    setBusy((s) => new Set(s).add(id));
    try {
      if (onDraftAction) await onDraftAction(action, id);
      if (action === "skip") setSkipped((s) => new Set(s).add(id));
      else setApproved((s) => new Set(s).add(id));
    } catch {
      // Parent surfaces the action error; keep the draft visible for retry.
    } finally {
      setBusy((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  };

  return (
    <section className="td-card td-approvals" aria-label="Quick approvals">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Quick approvals</h3>
          <p className="td-card-sub">
            {visible.length === 0
              ? "Inbox is clear — nothing else queued."
              : visible.length + " draft" + (visible.length === 1 ? "" : "s") + " ready · auto-send paused"}
          </p>
        </div>
        <div className="td-card-link-group">
          <button
            type="button"
            className="td-card-link mono"
            disabled={visible.length === 0 || busy.size > 0}
            onClick={() => { for (const d of visible) void handle("approve", d.id); }}
          >
            Approve all
          </button>
          <Link to="/leads" className="td-card-link mono">Open queue
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
          </Link>
        </div>
      </header>
      {visible.length === 0 ? (
        <div className="td-priority-empty">Nothing to approve. Drafts will appear here as the agent prepares them.</div>
      ) : (
        <ul className="td-approvals-list">
          {visible.map((d) => (
            <li key={d.id} className="td-approval-row">
              <div className="td-approval-meta">
                <div className="td-approval-to">
                  <span className="td-approval-name">{d.to}</span>
                  {d.heat != null && (
                    <span className={"td-priority-heat mono " + (d.heat >= 80 ? "hot" : d.heat >= 50 ? "warm" : "cool")}>{d.heat}</span>
                  )}
                </div>
                <div className="td-approval-meta-line mono">
                  <span>{d.channel}</span>
                  <span className="td-approval-meta-dot">·</span>
                  <span>{d.intent}</span>
                  <span className="td-approval-meta-dot">·</span>
                  <span>{d.handle}</span>
                </div>
              </div>
              <div className="td-approval-preview">{d.preview}</div>
              <div className="td-approval-foot">
                <span className="td-approval-conf mono">
                  {d.confidence != null && (
                    <>
                      <span className="td-approval-conf-bar"><span style={{ width: d.confidence + "%" }} /></span>
                      {d.confidence}% confident ·{" "}
                    </>
                  )}
                  drafted {d.age} ago
                </span>
                <div className="td-approval-actions">
                  <button type="button" className="td-btn ghost" disabled={busy.has(d.id)} onClick={() => handle("skip", d.id)}>
                    {busy.has(d.id) ? "…" : "Skip"}
                  </button>
                  <Link to="/leads" className="td-btn ghost">Edit</Link>
                  <button type="button" className="td-btn primary" disabled={busy.has(d.id)} onClick={() => handle("approve", d.id)}>
                    {busy.has(d.id) ? "…" : "Approve & send"}
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CalendarIcon({ kind }: { kind: TodayCalendarEvent["kind"] }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, width: 13, height: 13 };
  if (kind === "meeting") return <svg {...common}><rect x="2" y="6" width="14" height="12" rx="2" /><path d="M22 8l-6 4 6 4z" /></svg>;
  if (kind === "cma") return <svg {...common}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></svg>;
  if (kind === "callback") return <svg {...common}><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.94.36 1.85.67 2.73a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.35-1.35a2 2 0 0 1 2.11-.45c.88.31 1.79.54 2.73.67A2 2 0 0 1 22 16.92z" /></svg>;
  return <svg {...common}><path d="M3 12l9-9 9 9" /><path d="M5 10v10h14V10" /></svg>;
}

function TodayCalendar({ events }: { events: TodayCalendarEvent[] }) {
  const last = events[events.length - 1];
  return (
    <section className="td-card td-calendar" aria-label="Today's schedule">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Today's schedule</h3>
          <p className="td-card-sub">{events.length} events{last ? ` · ends ${last.time}` : ""}</p>
        </div>
        <Link to="/admin" className="td-card-link mono">Full calendar
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      <ul className="td-cal-list">
        {events.map((e) => (
          <li key={e.id} className="td-cal-row">
            <div className="td-cal-time">
              <div className="td-cal-time-h mono">{e.time}</div>
              <div className="td-cal-time-d mono">{e.duration}</div>
            </div>
            <div className={"td-cal-icon td-cal-icon-" + e.kind}><CalendarIcon kind={e.kind} /></div>
            <div className="td-cal-body">
              <div className="td-cal-title">{e.title}</div>
              <div className="td-cal-sub mono">{e.sub}</div>
            </div>
            <span className={"td-cal-status mono " + e.status}>{e.status}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SourcesGroup({ label, items }: { label: string; items: TodaySourceItem[] }) {
  return (
    <div className="td-sources-group">
      <div className="td-sources-group-label mono">{label}</div>
      {items.map((it) => (
        <div key={it.id} className={"td-source-row " + it.status}>
          <span className={"td-source-dot " + it.status} aria-hidden="true" />
          <div className="td-source-body">
            <div className="td-source-name">{it.name}</div>
            <div className="td-source-detail mono">{it.detail}</div>
          </div>
          <span className={"td-source-tag mono " + it.status}>
            {it.status === "live" ? "Live" : it.status === "error" ? "Error" : it.status === "blocked" ? "Blocked" : it.status}
          </span>
        </div>
      ))}
    </div>
  );
}

function SourcesHealth({ sources }: { sources: TodaySources }) {
  const errored = [...sources.channels, ...sources.schedules].filter((s) => s.status === "error" || s.status === "blocked");
  const total = sources.channels.length + sources.schedules.length;
  return (
    <section className="td-card td-sources" aria-label="Sources health">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Sources & schedules</h3>
          <p className="td-card-sub">
            {errored.length === 0 ? "All channels live" : `${errored.length} need attention · ${total - errored.length} live`}
          </p>
        </div>
        <Link to="/config#connectors" className="td-card-link mono">Settings
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      <div className="td-sources-body">
        <SourcesGroup label="Channels" items={sources.channels} />
        <SourcesGroup label="Schedules" items={sources.schedules} />
      </div>
    </section>
  );
}

function AgentRuns({ runs }: { runs: TodayAgentRun[] }) {
  return (
    <section className="td-card td-runs" aria-label="Recent agent runs">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Recent agent activity</h3>
          <p className="td-card-sub">{runs.length} runs in last 24h</p>
        </div>
        <Link to="/admin" className="td-card-link mono">View all
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      <ul className="td-runs-list">
        {runs.map((r) => (
          <li key={r.id} className="td-run-row">
            <span className={"td-run-dot " + (r.tone || "ok")} />
            <div className="td-run-body">
              <div className="td-run-title">{r.title}</div>
              <div className="td-run-meta mono">{r.kind} · {r.messages} messages · {r.tools} tools</div>
            </div>
            <div className="td-run-age mono">{r.age}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DealCard({ deal, onOpen }: { deal: TodayDeal; onOpen?: (deal: TodayDeal) => void }) {
  return (
    <article
      className={"td-deal td-tone-" + (deal.tone || "muted")}
      role="button"
      tabIndex={0}
      onClick={() => onOpen?.(deal)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen?.(deal);
        }
      }}
    >
      <header className="td-deal-head">
        <span className={"td-deal-side mono " + deal.side}>{deal.side}</span>
        <span className="td-deal-phase mono">{deal.phaseIdx}/{deal.phaseTotal}</span>
      </header>
      <div className="td-deal-body">
        <div className="td-deal-addr">{deal.address}</div>
        <div className="td-deal-client mono">{deal.client}</div>
      </div>
      <div className="td-deal-progress">
        <div className="td-deal-progress-bar">
          <span style={{ width: (deal.progress * 100).toFixed(0) + "%" }} />
        </div>
        <div className="td-deal-progress-label mono">{deal.phase}</div>
      </div>
      <footer className="td-deal-foot">
        <div className="td-deal-next-label mono">Next</div>
        <div className="td-deal-next-row">
          <span className="td-deal-next-text">{deal.next}</span>
          <span className="td-deal-next-when mono">{deal.nextWhen}</span>
        </div>
      </footer>
    </article>
  );
}

function ActiveDeals({ deals, adminDealsById }: { deals: TodayDeal[]; adminDealsById?: Map<string, AdminDeal> }) {
  const [active, setActive] = useState<AdminModalDeal | null>(null);

  const openDeal = (d: TodayDeal) => {
    const adminDeal = adminDealsById?.get(d.id);
    setActive(adminDeal ? adminDealToModalDeal(adminDeal) : todayDealToModalDeal(d));
  };

  return (
    <section className="td-card td-deals" aria-label="Active deals">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Active deals</h3>
          <p className="td-card-sub">{deals.length} in flight · phase progress + next step</p>
        </div>
        <Link to="/admin" className="td-card-link mono">Open admin
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      <div className="td-deals-track">
        {deals.map((d) => <DealCard key={d.id} deal={d} onOpen={openDeal} />)}
      </div>
      {active && <DealDetailModal deal={active} onClose={() => setActive(null)} />}
    </section>
  );
}

function WinIcon({ kind }: { kind: TodayWin["icon"] }) {
  const common = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, width: 14, height: 14 };
  if (kind === "calendar") return <svg {...common}><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>;
  if (kind === "arrow") return <svg {...common} strokeWidth="1.8"><path d="M5 12h14M13 5l7 7-7 7" /></svg>;
  if (kind === "spark") return <svg {...common}><path d="M12 3l1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5z" /></svg>;
  return <svg {...common} strokeWidth="1.8"><path d="M20 6L9 17l-5-5" /></svg>;
}

function DailyWins({ wins }: { wins: TodayWin[] }) {
  const total = wins.reduce((s, w) => s + w.value, 0);
  return (
    <section className="td-card td-wins" aria-label="Daily wins">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Today's wins</h3>
          <p className="td-card-sub">{total} positive actions logged · keep going</p>
        </div>
      </header>
      <ul className="td-wins-list">
        {wins.map((w) => (
          <li key={w.id} className="td-win-row">
            <span className="td-win-icon" aria-hidden="true"><WinIcon kind={w.icon} /></span>
            <div className="td-win-body">
              <div className="td-win-title">{w.title}</div>
              <div className="td-win-sub mono">{w.sub}</div>
            </div>
            <div className="td-win-num">{w.value}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function LeadSourceBreakdown({ data }: { data: TodaySourceBreakdown }) {
  const R = 56, r = 38, cx = 64, cy = 64;
  const total = data.total || 1;
  let acc = 0;
  const tones = ["fg", "fg-muted", "fg-dim", "fg-faint"];
  const segs = data.channels.map((c, i) => {
    const startAng = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += c.count;
    const endAng = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const large = endAng - startAng > Math.PI ? 1 : 0;
    const p = (a: number, rad: number): [number, number] => [cx + Math.cos(a) * rad, cy + Math.sin(a) * rad];
    const [x1, y1] = p(startAng, R);
    const [x2, y2] = p(endAng, R);
    const [x3, y3] = p(endAng, r);
    const [x4, y4] = p(startAng, r);
    const d = [
      `M ${x1} ${y1}`,
      `A ${R} ${R} 0 ${large} 1 ${x2} ${y2}`,
      `L ${x3} ${y3}`,
      `A ${r} ${r} 0 ${large} 0 ${x4} ${y4}`,
      "Z",
    ].join(" ");
    return { ...c, d, tone: tones[i] || "fg-faint" };
  });
  return (
    <section className="td-card td-sources-mix" aria-label="Lead source breakdown">
      <header className="td-card-head">
        <div>
          <h3 className="td-card-title">Where leads came from</h3>
          <p className="td-card-sub">{data.total} new leads today</p>
        </div>
        <Link to="/leads" className="td-card-link mono">All sources
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="11" height="11"><path d="M7 17L17 7M9 7h8v8" /></svg>
        </Link>
      </header>
      <div className="td-mix-body">
        <div className="td-mix-donut">
          <svg viewBox="0 0 128 128" width="128" height="128" aria-hidden="true">
            {segs.map((s, i) => (
              <path key={s.id} d={s.d} fill={`var(--${s.tone})`} opacity={i === 0 ? 1 : 0.78 - i * 0.14} />
            ))}
            <text x="64" y="62" textAnchor="middle" fontFamily="Anthropic Sans Display, Geist" fontSize="22" fontWeight="600" fill="var(--fg)">{data.total}</text>
            <text x="64" y="78" textAnchor="middle" fontFamily="Geist Mono, monospace" fontSize="9" fill="var(--fg-faint)" letterSpacing="0.1em">LEADS</text>
          </svg>
        </div>
        <ul className="td-mix-legend">
          {segs.map((s, i) => (
            <li key={s.id} className="td-mix-row">
              <span className="td-mix-swatch" style={{ background: `var(--${s.tone})`, opacity: i === 0 ? 1 : 0.78 - i * 0.14 }} />
              <span className="td-mix-label">{s.label}</span>
              <span className="td-mix-pct mono">{Math.round(s.share * 100)}%</span>
              <span className="td-mix-count mono">{s.count}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function TodayBoard(props: TodayBoardProps) {
  const greeting = useMemo(() => props.greeting ?? greetingForNow(), [props.greeting]);
  const sub = props.greetingSub ?? `Today at a glance · ${fmtTodayDate()}`;
  return (
    <main className="admin-board td-board" data-screen-label="01 Today">
      {/* No in-page hero — the title "Today" lives in the app breadcrumb
          header (like Memory and the other pages), no icon/eyebrow/status. */}
      <div className="td-board-body">
        {props.error ? (
          <div className="td-board-alert" role="alert">
            <span className="td-board-alert-title">Today needs attention</span>
            <span>{props.error}</span>
          </div>
        ) : null}
        <TodayPulse stats={props.pulse} greeting={greeting} name={props.greetingName ?? "there"} sub={sub} themeControl={props.themeControl} />
        <PipelineVelocity stages={props.pipeline} />
        <ActiveDeals deals={props.deals} adminDealsById={props.adminDealsById} />
        <div className="td-two">
          <PriorityQueue items={props.priority} />
          <QuickApprovals drafts={props.drafts} onDraftAction={props.onDraftAction} />
        </div>
        <DayShape hourBuckets={props.hourBuckets} dayBuckets={props.dayBuckets} />
        <div className="td-two">
          <TodayCalendar events={props.calendar} />
          <SourcesHealth sources={props.sources} />
        </div>
        <div className="td-two">
          <DailyWins wins={props.wins} />
          <LeadSourceBreakdown data={props.sourceBreakdown} />
        </div>
        <RunningStrip scheduled={props.scheduled} live={props.live} />
        <AgentRuns runs={props.runs} />
      </div>
    </main>
  );
}

export default TodayBoard;
