import { useCallback, useEffect, useMemo, useState } from "react";
import { Target } from "lucide-react";

import { api } from "@/lib/api";
import type {
  ReportingSummary,
  ReportingGoals,
  ReportingFunnelStep,
  ReportingSourceCount,
  ReportingMonthlyPoint,
} from "@/lib/api-types";
import {
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";
import { resolvePipelineStage } from "../leads/pipeline-stages";
import "./reporting.css";

// ── formatting helpers ────────────────────────────────────────────────────
const nf = (n: number) => n.toLocaleString();
const money = (n: number) => "$" + Math.round(n).toLocaleString();
const moneyK = (n: number) => "$" + Math.round(n / 1000) + "k";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
function monthLabel(ym: string): string {
  const parts = ym.split("-");
  const m = Number(parts[1]);
  return m >= 1 && m <= 12 ? MONTHS[m - 1] : ym;
}

function titleize(s: string): string {
  const clean = s.replace(/_/g, " ").trim();
  if (!clean) return "Unknown";
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

// Bucket a source distribution: fold "Unknown"/blank and the long tail into a
// single "Other" bar so the chart stays readable. Never fabricates a value.
function bucketSources(
  rows: ReportingSourceCount[],
  keep = 9,
): { label: string; value: number }[] {
  const named = rows.filter(
    (r) => r.source && r.source.toLowerCase() !== "unknown",
  );
  const unknown = rows
    .filter((r) => !r.source || r.source.toLowerCase() === "unknown")
    .reduce((a, r) => a + r.count, 0);
  const sorted = [...named].sort((a, b) => b.count - a.count);
  const head = sorted.slice(0, keep);
  const tail = sorted.slice(keep).reduce((a, r) => a + r.count, 0);
  const out = head.map((r) => ({ label: titleize(r.source), value: r.count }));
  const other = tail + unknown;
  if (other > 0) out.push({ label: "Other", value: other });
  return out;
}

// ── delta chip ─────────────────────────────────────────────────────────────
function DeltaChip({ delta }: { delta: number | null }) {
  if (delta === null || delta === undefined) return null;
  if (delta === 0) return <span className="d flat">even</span>;
  const up = delta > 0;
  return (
    <span className={"d " + (up ? "up" : "down")}>
      {up ? "▲" : "▼"} {Math.abs(delta)}%
    </span>
  );
}

// ── horizontal bar chart (mirrors the mockup's hbars) ──────────────────────
type Bar = { label: string; value: number; accent?: boolean };
function HBars({
  data,
  padL = 120,
  padR = 54,
  rowH = 34,
  gap = 8,
  showPct = false,
  fmt,
  ariaLabel,
}: {
  data: Bar[];
  padL?: number;
  padR?: number;
  rowH?: number;
  gap?: number;
  showPct?: boolean;
  fmt?: (v: number) => string;
  ariaLabel: string;
}) {
  const W = 560;
  const top = 6;
  const max = Math.max(1, ...data.map((d) => d.value));
  const barW = W - padL - padR;
  const height = top + data.length * (rowH + gap);
  const format = fmt ?? ((v: number) => nf(v));
  return (
    <svg
      className="rx-chart"
      viewBox={`0 0 ${W} ${height}`}
      role="img"
      aria-label={ariaLabel}
    >
      {data.map((d, i) => {
        const y = top + i * (rowH + gap);
        const w = Math.max(3, barW * (d.value / max));
        const prev = i > 0 ? data[i - 1].value : 0;
        const pct = showPct && i > 0 && prev > 0 ? Math.round((d.value / prev) * 100) : null;
        return (
          <g key={d.label + i}>
            <rect x={padL} y={y} width={barW} height={rowH} rx={7} fill="var(--line-2)" />
            <rect
              x={padL}
              y={y}
              width={w}
              height={rowH}
              rx={7}
              fill={d.accent ? "var(--c-accent)" : "var(--c-data)"}
            >
              <title>{`${d.label} · ${format(d.value)}`}</title>
            </rect>
            <text x={padL - 12} y={y + rowH / 2 + 4} textAnchor="end" fontSize={13} className="lbl">
              {d.label}
            </text>
            <text x={padL + w + 8} y={y + rowH / 2 + 4} fontSize={13} className="val">
              {format(d.value)}
            </text>
            {pct !== null && (
              <text x={W - 2} y={y + rowH / 2 + 4} textAnchor="end" fontSize={11} className="axl">
                {pct}%
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── combo: leads area+line with closings overlaid (mirrors mockup) ─────────
function Combo({ points }: { points: ReportingMonthlyPoint[] }) {
  const W = 1120;
  const H = 300;
  const padL = 46;
  const padR = 30;
  const padT = 40;
  const padB = 34;
  const iw = W - padL - padR;
  const ih = H - padT - padB;
  const n = points.length;
  const leads = points.map((p) => p.leads);
  const sales = points.map((p) => p.sales);
  const max1 = Math.max(1, ...leads) * 1.2;
  const x = (i: number) => padL + iw * (n > 1 ? i / (n - 1) : 0.5);
  const y1 = (v: number) => padT + ih * (1 - v / max1);
  const smin = Math.min(...sales);
  const smax = Math.max(...sales);
  const y2 = (v: number) => {
    const t = (v - smin) / ((smax - smin) || 1);
    return padT + ih - (0.14 * ih + t * 0.5 * ih);
  };
  const gid = "rx-ag";

  let d1 = `M ${x(0)} ${y1(leads[0])}`;
  for (let i = 1; i < n; i++) d1 += ` L ${x(i)} ${y1(leads[i])}`;
  let d2 = `M ${x(0)} ${y2(sales[0])}`;
  for (let j = 1; j < n; j++) d2 += ` L ${x(j)} ${y2(sales[j])}`;

  const grid = [0, 1, 2, 3];
  return (
    <svg className="rx-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="New leads and closings by month">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--c-soft)" />
          <stop offset="100%" stopColor="var(--c-soft-2)" />
        </linearGradient>
      </defs>
      {grid.map((g) => {
        const gy = padT + (ih * g) / 3;
        return (
          <g key={g}>
            <line x1={padL} y1={gy} x2={W - padR} y2={gy} stroke="var(--grid)" strokeWidth={1} />
            <text x={padL - 8} y={gy + 4} textAnchor="end" fontSize={11} className="axl">
              {Math.round(max1 * (1 - g / 3))}
            </text>
          </g>
        );
      })}
      <path d={`${d1} L ${x(n - 1)} ${padT + ih} L ${x(0)} ${padT + ih} Z`} fill={`url(#${gid})`} />
      <path d={d1} fill="none" stroke="var(--c-data)" strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" />
      <path d={d2} fill="none" stroke="var(--c-accent)" strokeWidth={2.2} strokeDasharray="6 4" strokeLinejoin="round" strokeLinecap="round" />
      {points.map((pt, i) => (
        <g key={pt.month}>
          <circle cx={x(i)} cy={y1(pt.leads)} r={3.5} fill="var(--c-data)" stroke="var(--card)" strokeWidth={2} />
          <circle cx={x(i)} cy={y2(pt.sales)} r={3.5} fill="var(--c-accent)" stroke="var(--card)" strokeWidth={2} />
          <text x={x(i)} y={y2(pt.sales) - 9} textAnchor="middle" fontSize={11} className="val" fill="var(--c-accent)">
            {pt.sales}
          </text>
          <text x={x(i)} y={H - 12} textAnchor="middle" fontSize={11} className="axl">
            {monthLabel(pt.month)}
          </text>
          <rect x={x(i) - 16} y={padT} width={32} height={ih} fill="transparent">
            <title>{`${monthLabel(pt.month)} · ${pt.leads} leads · ${pt.sales} closings`}</title>
          </rect>
        </g>
      ))}
      <line x1={padL} y1={16} x2={padL + 22} y2={16} stroke="var(--c-data)" strokeWidth={2.4} />
      <text x={padL + 28} y={20} className="legt">New leads</text>
      <line x1={padL + 120} y1={16} x2={padL + 142} y2={16} stroke="var(--c-accent)" strokeWidth={2.2} strokeDasharray="6 4" />
      <text x={padL + 148} y={20} className="legt">Closings</text>
    </svg>
  );
}

// ── goal progress ──────────────────────────────────────────────────────────
type GoalRow = { key: string; label: string; cur: number; goal: number; fmt: (v: number) => string };

function GoalProgress({ rows }: { rows: GoalRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="goals-empty">
        No goals set yet. Use <b>Set goals</b> to add monthly lead, appointment,
        and closing targets plus a GCI target. Progress will show here against
        your real pipeline.
      </div>
    );
  }
  return (
    <div className="goals">
      {rows.map((g) => {
        const pct = g.goal > 0 ? Math.min(100, Math.round((g.cur / g.goal) * 100)) : 0;
        const color = pct >= 80 ? "var(--c-good)" : pct >= 50 ? "var(--c-data)" : "var(--c-warn)";
        const pctcol = pct >= 80 ? "var(--c-good)" : pct >= 50 ? "var(--sub)" : "var(--c-warn)";
        return (
          <div className="goal" key={g.key}>
            <div className="gtop">
              <span className="glab">{g.label}</span>
              <span className="gnum">
                {g.fmt(g.cur)} <span className="goalv">/ {g.fmt(g.goal)}</span>
              </span>
            </div>
            <div className="gbar">
              <span style={{ width: pct + "%", background: color }} />
            </div>
            <div className="gpct" style={{ color: pctcol }}>
              {pct}% to goal
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── activity math (reverse funnel from closings goal) ──────────────────────
function ActivityMath({
  funnel,
  closingsGoal,
}: {
  funnel: ReportingFunnelStep[];
  closingsGoal: number | null;
}) {
  const by = useMemo(() => {
    const m: Record<string, number> = {};
    funnel.forEach((f) => (m[f.stage] = f.count));
    return m;
  }, [funnel]);

  const leadsN = by.leads ?? 0;
  const convN = by.conversations ?? 0;
  const apptN = by.appointments ?? 0;
  const clientN = by.under_contract ?? 0;
  const closedN = by.closed ?? 0;

  const rLc = leadsN > 0 ? convN / leadsN : 0;
  const rCa = convN > 0 ? apptN / convN : 0;
  const rAc = apptN > 0 ? clientN / apptN : 0;
  const rCc = clientN > 0 ? closedN / clientN : 0;

  const goal = closingsGoal ?? 0;
  const ratesOk = rLc > 0 && rCa > 0 && rAc > 0 && rCc > 0;
  const convPerSale = closedN > 0 ? Math.round(convN / closedN) : null;

  if (!goal || !ratesOk) {
    return (
      <div className="mathcard">
        <div className="mathhd">
          <div>
            <h3>What it takes to hit your goal</h3>
            <p className="cap">
              Worked backward from your funnel's real conversion rates so you know
              your daily number.
            </p>
          </div>
          {convPerSale !== null && (
            <div className="bigratio">
              <span className="br-n">{convPerSale}</span>
              <span className="br-l">conversations per sale</span>
            </div>
          )}
        </div>
        <div className="math-note">
          {goal
            ? "Not enough closed-deal history yet to work the funnel backward. Once a few leads move through conversation, appointment, and close, this will show the daily activity it takes to hit your goal."
            : "Set a monthly closings goal to see the leads, conversations, and appointments it takes to get there."}
        </div>
      </div>
    );
  }

  const clients = goal / rCc;
  const appts = clients / rAc;
  const convs = appts / rCa;
  const leads = convs / rLc;
  const steps = [
    { n: Math.ceil(leads), l: "leads" },
    { n: Math.ceil(convs), l: "conversations" },
    { n: Math.ceil(appts), l: "appointments" },
    { n: Math.ceil(clients), l: "client meetings" },
    { n: goal, l: goal === 1 ? "closing" : "closings", goal: true },
  ];
  const perWeek = Math.round(convs / 4.3);
  const perDay = Math.max(1, Math.round(convs / 21));

  return (
    <div className="mathcard">
      <div className="mathhd">
        <div>
          <h3>What it takes to hit your goal</h3>
          <p className="cap">
            Worked backward from your funnel's real conversion rates so you know
            your daily number.
          </p>
        </div>
        {convPerSale !== null && (
          <div className="bigratio">
            <span className="br-n">{convPerSale}</span>
            <span className="br-l">conversations per sale</span>
          </div>
        )}
      </div>
      <div className="mathrow">
        {steps.map((s, i) => (
          <div key={s.l} style={{ display: "contents" }}>
            <div className={"mstep" + (s.goal ? " goal" : "")}>
              <div className="mn">{nf(s.n)}</div>
              <div className="ml">{s.l}</div>
            </div>
            {i < steps.length - 1 && <div className="marrow">→</div>}
          </div>
        ))}
      </div>
      <div className="mathcadence">
        To hit <b>{goal}</b> closing{goal === 1 ? "" : "s"} a month, that is about{" "}
        <b>{Math.ceil(convs)}</b> conversations a month, roughly <b>{perWeek}</b> a
        week, or <b>{perDay}</b> a day.
      </div>
    </div>
  );
}

// ── goals modal ────────────────────────────────────────────────────────────
function GoalsModal({
  goals,
  onClose,
  onSaved,
}: {
  goals: ReportingGoals;
  onClose: () => void;
  onSaved: (g: ReportingGoals) => void;
}) {
  const [leads, setLeads] = useState(goals.leadsGoal?.toString() ?? "");
  const [appts, setAppts] = useState(goals.apptsGoal?.toString() ?? "");
  const [close, setClose] = useState(goals.closingsGoal?.toString() ?? "");
  const [gci, setGci] = useState(goals.gciGoal?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const num = (s: string): number | null => {
    const t = s.trim();
    if (t === "") return null;
    const v = Number(t);
    return Number.isFinite(v) && v >= 0 ? Math.round(v) : null;
  };

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const saved = await api.saveReportingGoals({
        leadsGoal: num(leads),
        apptsGoal: num(appts),
        closingsGoal: num(close),
        gciGoal: num(gci),
      });
      onSaved(saved);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save goals");
      setSaving(false);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="gm-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="gm-card" role="dialog" aria-modal="true" aria-labelledby="gm-goals-title">
        <h3 id="gm-goals-title">Set your goals</h3>
        <div className="gm-sub">
          Targets for this period. Leave a field blank to clear that goal.
        </div>
        <div className="gm-field">
          <label>New leads (per month)</label>
          <input type="number" value={leads} onChange={(e) => setLeads(e.target.value)} />
        </div>
        <div className="gm-field">
          <label>Appointments booked (per month)</label>
          <input type="number" value={appts} onChange={(e) => setAppts(e.target.value)} />
        </div>
        <div className="gm-field">
          <label>Closings (per month)</label>
          <input type="number" value={close} onChange={(e) => setClose(e.target.value)} />
        </div>
        <div className="gm-field">
          <label>GCI target (year, $)</label>
          <input type="number" value={gci} onChange={(e) => setGci(e.target.value)} />
        </div>
        {err && <div className="gm-sub" style={{ color: "var(--c-accent)" }}>{err}</div>}
        <div className="gm-foot">
          <button className="gm-cancel" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="gm-save" onClick={() => void save()} disabled={saving}>
            {saving ? "Saving…" : "Save goals"}
          </button>
        </div>
      </div>
    </div>
  );
}

const WINDOWS = [7, 30, 90];

// ── page ───────────────────────────────────────────────────────────────────
export function RealEstateReportingPage() {
  const hub = useRealEstateHubData();
  const [windowDays, setWindowDays] = useState(30);
  const [summary, setSummary] = useState<ReportingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [goalsOpen, setGoalsOpen] = useState(false);
  const [trendTab, setTrendTab] = useState<"monthly" | "yoy">("monthly");

  const load = useCallback(async (win: number) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getReportingSummary(win);
      setSummary(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load reporting");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(windowDays);
  }, [load, windowDays]);

  useHubHeader("Reporting", hub, {
    onRefresh: () => load(windowDays),
    refreshing: loading,
  });

  const goalRows = useMemo<GoalRow[]>(() => {
    if (!summary) return [];
    const g = summary.goals;
    const rows: GoalRow[] = [];
    const monthly = summary.trend.monthly;
    const curClosings = monthly.length ? monthly[monthly.length - 1].sales : 0;
    if (g.leadsGoal != null)
      rows.push({ key: "leads", label: "New leads", cur: summary.kpis.newLeads.value, goal: g.leadsGoal, fmt: nf });
    if (g.apptsGoal != null)
      rows.push({ key: "appts", label: "Appointments", cur: summary.kpis.apptsBooked.value, goal: g.apptsGoal, fmt: nf });
    if (g.closingsGoal != null)
      rows.push({ key: "close", label: "Closings (mo)", cur: curClosings, goal: g.closingsGoal, fmt: nf });
    if (g.gciGoal != null)
      rows.push({ key: "gci", label: "GCI to date", cur: summary.gci, goal: g.gciGoal, fmt: moneyK });
    return rows;
  }, [summary]);

  if (loading && !summary) {
    return (
      <div className="reportx">
        <div className="rx-loading">Loading reporting…</div>
      </div>
    );
  }
  if (error && !summary) {
    return (
      <div className="reportx">
        <div className="rx-error">
          Could not load reporting: {error}{" "}
          <button className="range" onClick={() => void load(windowDays)} style={{ marginLeft: 8 }}>
            Retry
          </button>
        </div>
      </div>
    );
  }
  if (!summary) return null;

  const k = summary.kpis;
  const leadSourceBars = bucketSources(summary.leadsBySource);
  // Map raw pipeline_status slugs into Skyleigh's operator vocabulary and
  // aggregate slugs that fold into the same stage (follow_up + ghosting ->
  // Attempted, closed_seller + closed_buyer -> Closed).
  const stageAgg = new Map<string, number>();
  for (const s of summary.leadsByStage) {
    const label = resolvePipelineStage(s.stage).label;
    stageAgg.set(label, (stageAgg.get(label) ?? 0) + s.count);
  }
  const stageBars: Bar[] = Array.from(stageAgg.entries()).map(([label, value]) => ({
    label,
    value,
    accent: label === "Closed",
  }));
  const tempOrder = ["hot", "warm", "watch", "normal"];
  const tempBars: Bar[] = [...summary.leadsByTemperature]
    .sort((a, b) => tempOrder.indexOf(a.label) - tempOrder.indexOf(b.label))
    .map((t) => ({ label: titleize(t.label), value: t.count, accent: t.label === "hot" }));
  const funnelBars: Bar[] = summary.funnel.map((f) => ({ label: f.label, value: f.count }));
  const funnelAllZero = summary.funnel.every((f) => f.count === 0);
  const closedBars: Bar[] = bucketSources(summary.closedBySource, 8).map((b) => ({
    label: b.label,
    value: b.value,
    accent: false,
  }));
  const monthly = summary.trend.monthly;
  const monthlyEmpty = monthly.every((p) => p.leads === 0 && p.sales === 0);
  const yoy = summary.trend.yoy;

  return (
    <div className="reportx">
      <div className="rx-page">
        <div className="rx-toolbar">
          <button className="goalbtn" onClick={() => setGoalsOpen(true)}>
            <Target size={14} /> Set goals
          </button>
          <div className="rx-spacer" />
          <select
            className="range"
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            aria-label="Reporting window"
          >
            {WINDOWS.map((w) => (
              <option key={w} value={w}>
                Last {w} days
              </option>
            ))}
          </select>
        </div>

        <div className="goalcard">
          <div className="gc-hd">
            <b>Goal progress</b>
            <button className="edit" onClick={() => setGoalsOpen(true)}>
              Edit goals
            </button>
          </div>
          <GoalProgress rows={goalRows} />
        </div>

        <div className="kpis">
          <div className="kpi">
            <div className="n">{nf(k.newLeads.value)}</div>
            <div className="l">New leads</div>
            <div>
              <DeltaChip delta={k.newLeads.delta} />
            </div>
          </div>
          <div className="kpi">
            <div className="n">{nf(k.calls.value)}</div>
            <div className="l">Calls made</div>
            <div className="note">voice not tracked yet</div>
          </div>
          <div className="kpi">
            <div className="n">{nf(k.texts.value)}</div>
            <div className="l">Texts sent</div>
            <div>
              <DeltaChip delta={k.texts.delta} />
            </div>
          </div>
          <div className="kpi">
            <div className="n">{nf(k.emails.value)}</div>
            <div className="l">Emails sent</div>
            <div>
              <DeltaChip delta={k.emails.delta} />
            </div>
          </div>
          <div className="kpi">
            <div className="n">{nf(k.apptsBooked.value)}</div>
            <div className="l">Deal appointments</div>
            <div>
              <DeltaChip delta={k.apptsBooked.delta} />
            </div>
          </div>
          <div className="kpi">
            <div className="n">{k.leadToClient.value}%</div>
            <div className="l">Lead → client</div>
          </div>
        </div>

        <ActivityMath funnel={summary.funnel} closingsGoal={summary.goals.closingsGoal} />

        <div className="charts">
          <div className="cardc">
            <h3>Lead-to-close funnel</h3>
            <p className="cap">
              Leads and conversations from the contacts system; appointments,
              under-contract, and closed from your deals. Right column = kept from
              the stage above.
            </p>
            {funnelAllZero ? (
              <div className="empty">
                <b>No pipeline yet</b>
                Leads, conversations, and deals will fill this funnel as they come in.
              </div>
            ) : (
              <HBars data={funnelBars} showPct padR={96} padL={120} ariaLabel="Lead to close funnel" />
            )}
          </div>

          <div className="cardc">
            <h3>Leads by source</h3>
            <p className="cap">Where your contacts came from. Small and unknown sources roll into Other.</p>
            {leadSourceBars.length === 0 ? (
              <div className="empty">
                <b>No lead sources yet</b>
                Source shows once contacts carry a lead source.
              </div>
            ) : (
              <HBars data={leadSourceBars} padL={118} ariaLabel="Leads by source" />
            )}
          </div>

          <div className="cardc">
            <h3>Leads by pipeline stage</h3>
            <p className="cap">How your contacts are split across pipeline status.</p>
            {stageBars.length === 0 ? (
              <div className="empty">
                <b>No contacts yet</b>
                Pipeline stages will populate as leads are worked.
              </div>
            ) : (
              <HBars data={stageBars} padL={118} ariaLabel="Leads by pipeline stage" />
            )}
          </div>

          <div className="cardc">
            <h3>Leads by temperature</h3>
            <p className="cap">Hot, warm, watch, and normal from lead scoring.</p>
            {tempBars.length === 0 ? (
              <div className="empty">
                <b>No contacts yet</b>
                Temperature shows once contacts are scored.
              </div>
            ) : (
              <HBars data={tempBars} padL={100} ariaLabel="Leads by temperature" />
            )}
          </div>

          <div className="cardc">
            <h3>Where closed deals came from</h3>
            <p className="cap">
              Origin of the deals you actually closed.
              {summary.gci > 0 && <> Total GCI closed: <strong>{money(summary.gci)}</strong>.</>}
            </p>
            {closedBars.length === 0 ? (
              <div className="empty">
                <b>No closed deals yet</b>
                This fills in as deals reach closed status.
              </div>
            ) : (
              <HBars
                data={closedBars}
                padL={120}
                ariaLabel="Closed deals by source"
                fmt={(v) => `${v} ${v === 1 ? "deal" : "deals"}`}
              />
            )}
          </div>

          <div className="cardc">
            <h3>Marketing spend</h3>
            <p className="cap">Dollars into each channel this year.</p>
            <div className="empty">
              <b>No ad-spend connected yet</b>
              Connect an ad-spend source to see cost per lead and cost per closed deal.
            </div>
          </div>

          <div className="cardc span">
            <div className="trend-hd">
              <div>
                <h3>Leads &amp; sales over time</h3>
                <p className="cap">
                  Leads on the axis; closings overlaid (dashed). Point labels are the
                  actual number of sales.
                </p>
              </div>
              <div className="tabs2">
                <button className={trendTab === "monthly" ? "on" : ""} onClick={() => setTrendTab("monthly")}>
                  Monthly
                </button>
                <button className={trendTab === "yoy" ? "on" : ""} onClick={() => setTrendTab("yoy")}>
                  Year over year
                </button>
              </div>
            </div>
            {trendTab === "monthly" ? (
              monthlyEmpty ? (
                <div className="empty">
                  <b>No monthly activity yet</b>
                  Leads and closings will chart here month over month.
                </div>
              ) : (
                <Combo points={monthly} />
              )
            ) : yoy.length === 0 ? (
              <div className="empty">
                <b>No yearly history yet</b>
                Year-over-year needs at least one year of leads or sales.
              </div>
            ) : (
              <div className="yoy2">
                <div>
                  <div className="tlabel">Leads by year</div>
                  <HBars
                    data={yoy.map((r) => ({ label: r.ytd ? `${r.year} · YTD` : r.year, value: r.leads, accent: r.ytd }))}
                    padL={88}
                    padR={60}
                    rowH={32}
                    ariaLabel="Leads by year"
                  />
                </div>
                <div>
                  <div className="tlabel">Sales by year</div>
                  <HBars
                    data={yoy.map((r) => ({ label: r.ytd ? `${r.year} · YTD` : r.year, value: r.sales, accent: r.ytd }))}
                    padL={88}
                    padR={60}
                    rowH={32}
                    ariaLabel="Sales by year"
                    fmt={(v) => `${v} ${v === 1 ? "sale" : "sales"}`}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="footnote">
          Window: last {summary.window} days · leads, conversion, and outreach.
          Pipeline value and closed-deal detail live on the admin page.
        </div>
      </div>

      {goalsOpen && (
        <GoalsModal
          goals={summary.goals}
          onClose={() => setGoalsOpen(false)}
          onSaved={(g) => {
            setSummary((prev) => (prev ? { ...prev, goals: g } : prev));
            setGoalsOpen(false);
          }}
        />
      )}
    </div>
  );
}

export default RealEstateReportingPage;
