import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  FlaskConical,
  Loader2,
  Play,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  HeartbeatExperiment,
  HeartbeatExperimentCycle,
  HeartbeatExperimentSurface,
  HeartbeatExperimentsResponse,
} from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Experiments = the autoresearch view of surface heartbeats.         */
/*  Each surface runs a research cycle every Nth heartbeat: it proposes */
/*  an experiment, runs it for a window, then decides keep/discard and  */
/*  compounds the learning into its own playbook. This page is a        */
/*  read-only window onto that loop (mirrors CTRL Flow /ai/experiments).*/
/* ------------------------------------------------------------------ */

/* ----------------------------- helpers ---------------------------- */

function timeAgo(iso?: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";
  const diff = Date.now() - then;
  if (diff < 0) return "just now";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

type StatusVariant = "default" | "secondary" | "outline" | "success" | "warning";

function statusVariant(status?: string | null): StatusVariant {
  switch ((status || "").toLowerCase()) {
    case "completed":
      return "default";
    case "running":
      return "secondary";
    case "proposed":
      return "outline";
    default:
      return "outline";
  }
}

function decisionVariant(decision?: string | null): StatusVariant {
  switch ((decision || "").toLowerCase()) {
    case "keep":
      return "success";
    case "discard":
      return "warning";
    default:
      return "outline";
  }
}

/** Keep-rate tone band: ≥70 sage, ≥40 amber, else coral. */
function keepRateTone(rate: number, decided: number): "success" | "warning" | "destructive" | "muted" {
  if (decided === 0) return "muted";
  if (rate >= 70) return "success";
  if (rate >= 40) return "warning";
  return "destructive";
}

const TONE_TEXT: Record<string, string> = {
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
  muted: "text-muted-foreground",
};

/** Render a baseline/result value compactly — numbers, strings, or JSON. */
function fmtValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/* --------------------------- stat tiles --------------------------- */

function StatTile({
  label,
  value,
  valueClass,
  dot,
  subtitle,
}: {
  label: string;
  value: string | number;
  valueClass?: string;
  dot?: boolean;
  subtitle?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card/40 p-3">
      <div className="flex items-center gap-1.5">
        {dot && <span className="inline-block h-2 w-2 rounded-full bg-warning" />}
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          {label}
        </span>
      </div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums text-foreground", valueClass)}>
        {value}
      </div>
      {subtitle && (
        <p className="mt-0.5 text-[11px] text-muted-foreground">{subtitle}</p>
      )}
    </div>
  );
}

/* --------------------------- experiment row ----------------------- */

function ExperimentRow({ exp }: { exp: HeartbeatExperiment }) {
  const shortId = (exp.id || "").slice(0, 8) || "exp";
  const hasResult = exp.result != null;
  return (
    <li className="space-y-1.5 rounded-md border border-border bg-secondary/30 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={statusVariant(exp.status)} className="shrink-0">
          {exp.status || "open"}
        </Badge>
        {exp.decision && (
          <Badge variant={decisionVariant(exp.decision)} className="shrink-0">
            {exp.decision}
          </Badge>
        )}
        <span className="font-mono-ui text-[11px] text-muted-foreground/70">{shortId}</span>
      </div>

      {exp.hypothesis && (
        <p className="text-xs leading-5 text-foreground/90">{exp.hypothesis}</p>
      )}
      {exp.changes_description && (
        <p className="text-[11px] leading-5 text-muted-foreground">
          {exp.changes_description}
        </p>
      )}

      {hasResult && (
        <p className="font-mono-ui text-[11px] text-muted-foreground">
          {fmtValue(exp.baseline)} <span className="text-muted-foreground/60">→</span>{" "}
          <span className="text-foreground/90">{fmtValue(exp.result)}</span>
          {exp.metric ? <span className="text-muted-foreground/60"> · {exp.metric}</span> : null}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground/80">
        <span>started {timeAgo(exp.created_at)}</span>
        {exp.completed_at && <span>done {timeAgo(exp.completed_at)}</span>}
      </div>

      {exp.learning && (
        <div className="rounded-md border border-warning/40 bg-warning/10 p-2">
          <span className="text-[10px] font-medium uppercase tracking-wide text-warning">
            Learning
          </span>
          <p className="mt-0.5 text-[11px] leading-5 text-foreground/90">{exp.learning}</p>
        </div>
      )}
    </li>
  );
}

/* ---------------------------- cycle row --------------------------- */

function CycleRow({ cycle }: { cycle: HeartbeatExperimentCycle }) {
  const up = (cycle.direction || "").toLowerCase() === "higher";
  return (
    <li className="flex items-center justify-between gap-3 rounded-md bg-secondary/30 p-2">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          {up ? (
            <TrendingUp className="h-3.5 w-3.5 text-success" />
          ) : (
            <TrendingDown className="h-3.5 w-3.5 text-warning" />
          )}
          <span className="truncate text-xs font-medium text-foreground/90">{cycle.name}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
          {cycle.metric && <span>{cycle.metric}</span>}
          <span>
            {cycle.window} · {cycle.loop_interval}
          </span>
        </div>
      </div>
      <Badge variant={cycle.enabled ? "success" : "secondary"} className="shrink-0">
        {cycle.enabled ? "on" : "off"}
      </Badge>
    </li>
  );
}

/* -------------------------- split bar ----------------------------- */

function KeepDiscardBar({ kept, discarded }: { kept: number; discarded: number }) {
  const total = kept + discarded;
  if (total === 0) return null;
  const keepPct = Math.round((kept / total) * 100);
  return (
    <div className="space-y-1">
      <div className="flex h-2 overflow-hidden rounded-full bg-secondary">
        <div className="bg-success" style={{ width: `${keepPct}%` }} />
        <div className="bg-destructive" style={{ width: `${100 - keepPct}%` }} />
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span className="text-success">{kept} kept</span>
        <span className="text-destructive">{discarded} discarded</span>
      </div>
    </div>
  );
}

/* ------------------------- surface card --------------------------- */

function SurfaceCard({ surface }: { surface: HeartbeatExperimentSurface }) {
  const [open, setOpen] = useState(false);
  const stats = surface.stats;
  const decided = stats.kept + stats.discarded;
  const tone = keepRateTone(stats.keepRate, decided);

  return (
    <Card>
      <CardHeader>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-start justify-between gap-3 text-left"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {open ? (
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              )}
              <CardTitle>{titleCase(surface.surface)}</CardTitle>
              {stats.running > 0 && (
                <Badge variant="secondary" className="shrink-0">
                  {stats.running} running
                </Badge>
              )}
            </div>
            <div className="mt-1.5 ml-6 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{stats.total} total</span>
              <span className={TONE_TEXT[tone]}>
                {decided > 0 ? `${stats.keepRate}% kept` : "no decisions"}
              </span>
              <span className="inline-flex items-center gap-1">
                <FlaskConical className="h-3 w-3" />
                {surface.cycles.length} {surface.cycles.length === 1 ? "cycle" : "cycles"}
              </span>
            </div>
          </div>
        </button>
      </CardHeader>

      {open && (
        <CardContent className="space-y-4">
          {decided > 0 && <KeepDiscardBar kept={stats.kept} discarded={stats.discarded} />}

          {surface.cycles.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                Research Cycles
              </span>
              <ul className="space-y-1.5">
                {surface.cycles.map((c, i) => (
                  <CycleRow key={c.name || i} cycle={c} />
                ))}
              </ul>
            </div>
          )}

          {surface.experiments.length > 0 ? (
            <div className="space-y-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                Experiments
              </span>
              <ul className="space-y-1.5">
                {surface.experiments.map((e, i) => (
                  <ExperimentRow key={e.id || i} exp={e} />
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs italic text-muted-foreground/70">
              No experiments yet on this surface.
            </p>
          )}
        </CardContent>
      )}
    </Card>
  );
}

/* --------------------------- timeline ----------------------------- */

function TimelineRow({ exp }: { exp: HeartbeatExperiment }) {
  const glyph =
    exp.decision === "keep" ? (
      <Check className="h-4 w-4 text-success" />
    ) : exp.decision === "discard" ? (
      <X className="h-4 w-4 text-destructive" />
    ) : exp.status === "running" ? (
      <Play className="h-4 w-4 text-foreground/70" />
    ) : (
      <Clock className="h-4 w-4 text-muted-foreground" />
    );
  const when = exp.completed_at || exp.created_at;
  return (
    <li className="flex items-start gap-3 rounded-md border border-border bg-card/40 p-2.5">
      <div className="mt-0.5 shrink-0">{glyph}</div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-medium text-foreground">{titleCase(exp.surface)}</span>
          {exp.metric && (
            <span className="text-[11px] text-muted-foreground">· {exp.metric}</span>
          )}
          <Badge variant={statusVariant(exp.status)} className="shrink-0">
            {exp.status || "open"}
          </Badge>
          {exp.decision && (
            <Badge variant={decisionVariant(exp.decision)} className="shrink-0">
              {exp.decision}
            </Badge>
          )}
        </div>
        {exp.hypothesis && (
          <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{exp.hypothesis}</p>
        )}
      </div>
      <span className="shrink-0 text-[11px] text-muted-foreground/80">{timeAgo(when)}</span>
    </li>
  );
}

/* ----------------------------- page ------------------------------- */

type Tab = "surfaces" | "timeline" | "learnings";

const TABS: { key: Tab; label: string }[] = [
  { key: "surfaces", label: "By Surface" },
  { key: "timeline", label: "Timeline" },
  { key: "learnings", label: "Learnings" },
];

export default function ExperimentsPage() {
  const [data, setData] = useState<HeartbeatExperimentsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("surfaces");

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const resp = await api.getHeartbeatExperiments({ refresh });
      setData(resp);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
    const id = window.setInterval(() => load(true), 30000);
    return () => window.clearInterval(id);
  }, [load]);

  const surfaces = data?.surfaces || [];
  const summary = data?.summary;

  // Flatten every experiment across surfaces for the timeline, newest first.
  const timeline = useMemo(() => {
    const all = surfaces.flatMap((s) => s.experiments);
    return [...all].sort((a, b) => {
      const ta = new Date(a.completed_at || a.created_at || 0).getTime();
      const tb = new Date(b.completed_at || b.created_at || 0).getTime();
      return tb - ta;
    });
  }, [surfaces]);

  const keepTone = summary
    ? keepRateTone(summary.keepRate, summary.kept + summary.discarded)
    : "muted";

  const empty = surfaces.length === 0;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-foreground" />
            <h1 className="text-lg font-semibold text-foreground">Experiments</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Autoresearch — each surface improves its own playbook.
          </p>
        </div>
        <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Refresh
        </Button>
      </header>

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load experiments: {error}
        </div>
      ) : (
        <>
          {/* Stat tiles */}
          {summary && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatTile label="Cycles" value={summary.cycles} />
              <StatTile label="Running" value={summary.running} dot={summary.running > 0} />
              <StatTile label="Completed" value={summary.completed} />
              <StatTile
                label="Keep Rate"
                value={`${summary.keepRate}%`}
                valueClass={TONE_TEXT[keepTone]}
                subtitle={`${summary.kept} kept · ${summary.discarded} discarded`}
              />
              <StatTile label="Total Runs" value={summary.total} />
            </div>
          )}

          {/* Tabs */}
          <div className="flex flex-wrap gap-1.5 border-b border-border pb-2">
            {TABS.map((tb) => {
              const active = tab === tb.key;
              return (
                <button
                  key={tb.key}
                  type="button"
                  onClick={() => setTab(tb.key)}
                  className={cn(
                    "h-8 rounded-md border px-3 text-xs font-medium transition-colors",
                    active
                      ? "border-foreground/20 bg-secondary text-foreground"
                      : "border-border bg-card text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
                  )}
                >
                  {tb.label}
                </button>
              );
            })}
          </div>

          {empty ? (
            <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
              No experiments yet — each surface runs its improvement loop every Nth
              heartbeat.
            </div>
          ) : tab === "surfaces" ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {surfaces.map((s) => (
                <SurfaceCard key={s.surface} surface={s} />
              ))}
            </div>
          ) : tab === "timeline" ? (
            timeline.length > 0 ? (
              <ul className="space-y-2">
                {timeline.map((e, i) => (
                  <TimelineRow key={e.id || i} exp={e} />
                ))}
              </ul>
            ) : (
              <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
                No experiments yet — each surface runs its improvement loop every Nth
                heartbeat.
              </div>
            )
          ) : (
            <div className="space-y-3">
              {surfaces.map((s) => {
                const learnings = (s.learnings || "").trim();
                return (
                  <Card key={s.surface}>
                    <CardHeader>
                      <CardTitle>{titleCase(s.surface)}</CardTitle>
                    </CardHeader>
                    <CardContent>
                      {learnings ? (
                        <pre className="whitespace-pre-wrap break-words font-mono-ui text-xs leading-5 text-foreground/90">
                          {learnings}
                        </pre>
                      ) : (
                        <p className="text-xs italic text-muted-foreground/70">
                          No learnings recorded yet.
                        </p>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
