import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Beaker,
  ChevronDown,
  ChevronRight,
  Clock,
  FlaskConical,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  Repeat,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CronJob } from "@/lib/api";
import type { AgentHubAgent, HeartbeatSurface } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Markdown } from "@/components/Markdown";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Heartbeat = a scheduled self-prompt (cortextOS-style).            */
/*  The realtor sets an interval + instructions; the agent wakes on    */
/*  that clock, runs the instructions in a fresh session, and reports  */
/*  back into this feed. Each heartbeat is a cron job tagged with      */
/*  origin.type === "heartbeat" so it stays out of the power cron page.*/
/* ------------------------------------------------------------------ */

const HEARTBEAT_ORIGIN = { type: "heartbeat", source: "desktop-heartbeat" };

interface IntervalPreset {
  key: string;
  label: string;
  schedule: string;
  minutes: number;
}

const INTERVAL_PRESETS: IntervalPreset[] = [
  { key: "15m", label: "15 min", schedule: "every 15m", minutes: 15 },
  { key: "30m", label: "30 min", schedule: "every 30m", minutes: 30 },
  { key: "1h", label: "Hourly", schedule: "every 1h", minutes: 60 },
  { key: "2h", label: "2 hours", schedule: "every 2h", minutes: 120 },
  { key: "4h", label: "4 hours", schedule: "every 4h", minutes: 240 },
  { key: "6h", label: "6 hours", schedule: "every 6h", minutes: 360 },
  { key: "12h", label: "12 hours", schedule: "every 12h", minutes: 720 },
];

const INSTRUCTIONS_PLACEHOLDER =
  "What should the agent check and report?\n\nExample: Check my new leads since the last run. List anyone hot and why. Remind me of today's showings and any follow-ups that are overdue. If nothing's changed, just say \"all quiet.\"";

interface FormValues {
  name: string;
  intervalKey: string; // preset key | "daily" | "custom"
  dailyTime: string; // "HH:MM"
  customSchedule: string;
  instructions: string;
  agent: string; // Agent Hub agent id that runs it ("" = default agent)
  deliver: string; // result routing: local | telegram | discord | slack | email
}

const EMPTY_FORM: FormValues = {
  name: "",
  intervalKey: "1h",
  dailyTime: "08:00",
  customSchedule: "",
  instructions: "",
  agent: "",
  deliver: "local",
};

const DELIVER_OPTIONS: { value: string; label: string }[] = [
  { value: "local", label: "In-app (this feed)" },
  { value: "telegram", label: "Telegram" },
  { value: "discord", label: "Discord" },
  { value: "slack", label: "Slack" },
  { value: "email", label: "Email" },
];

function isHeartbeat(job: CronJob): boolean {
  return !!job.origin && job.origin.type === "heartbeat";
}

function scheduleFromForm(v: FormValues): string {
  if (v.intervalKey === "custom") return v.customSchedule.trim();
  if (v.intervalKey === "daily") {
    const [h, m] = v.dailyTime.split(":");
    const hh = Math.max(0, Math.min(23, parseInt(h || "8", 10) || 0));
    const mm = Math.max(0, Math.min(59, parseInt(m || "0", 10) || 0));
    return `${mm} ${hh} * * *`;
  }
  const preset = INTERVAL_PRESETS.find((p) => p.key === v.intervalKey);
  return preset ? preset.schedule : "";
}

function formFromJob(job: CronJob): FormValues {
  const sched = job.schedule || ({} as CronJob["schedule"]);
  const display = job.schedule_display || sched.display || "";
  let intervalKey = "custom";
  let dailyTime = "08:00";
  let customSchedule = display;

  if (sched.kind === "interval" && typeof sched.minutes === "number") {
    const found = INTERVAL_PRESETS.find((p) => p.minutes === sched.minutes);
    if (found) {
      intervalKey = found.key;
    } else {
      intervalKey = "custom";
      customSchedule = `every ${sched.minutes}m`;
    }
  } else if (sched.kind === "cron" && sched.expr) {
    const m = /^(\d+)\s+(\d+)\s+\*\s+\*\s+\*$/.exec(sched.expr.trim());
    if (m) {
      intervalKey = "daily";
      dailyTime = `${m[2].padStart(2, "0")}:${m[1].padStart(2, "0")}`;
    } else {
      intervalKey = "custom";
      customSchedule = sched.expr;
    }
  }

  return {
    name: job.name || "",
    intervalKey,
    dailyTime,
    customSchedule,
    instructions: job.prompt || "",
    agent: job.agent || "",
    deliver: job.deliver || "local",
  };
}

function formatRelative(iso?: string | null): string {
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
  return `${days}d ago`;
}

function prettyInterval(m: number): string {
  if (m === 60) return "Hourly";
  if (m < 60) return `Every ${m} min`;
  if (m % 60 === 0) return `Every ${m / 60} hours`;
  return `Every ${Math.floor(m / 60)}h ${m % 60}m`;
}

function prettySchedule(job: CronJob): string {
  const sched = job.schedule || ({} as CronJob["schedule"]);
  if (sched.kind === "interval" && typeof sched.minutes === "number") {
    return prettyInterval(sched.minutes);
  }
  if (sched.kind === "cron" && sched.expr) {
    const m = /^(\d+)\s+(\d+)\s+\*\s+\*\s+\*$/.exec(sched.expr.trim());
    if (m) return `Daily at ${m[2].padStart(2, "0")}:${m[1].padStart(2, "0")}`;
  }
  return job.schedule_display || sched.display || "—";
}

function statusTone(status?: string | null): string {
  switch ((status || "").toLowerCase()) {
    case "error":
      return "text-destructive";
    case "success":
      return "text-success";
    case "running":
      return "text-foreground";
    default:
      return "text-muted-foreground";
  }
}

/* ------------------------------------------------------------------ */
/*  Surface heartbeats (per-account work + experiment loop per surface)*/
/* ------------------------------------------------------------------ */

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Best-effort human rendering of a 5-field cron cadence string. */
function prettyCron(expr?: string | null): string {
  const raw = (expr || "").trim();
  if (!raw) return "—";
  const parts = raw.split(/\s+/);
  if (parts.length !== 5) return raw;
  const [min, hr, dom, mon, dow] = parts;

  const times = (): string | null => {
    // Only render times when both minute and hour are concrete lists.
    if (/[*/-]/.test(hr)) return null;
    if (min !== "0" && /[*/-]/.test(min)) return null;
    const hours = hr.split(",");
    const mm = min === "0" || min === "*" ? "00" : min.padStart(2, "0");
    const fmt = hours
      .map((h) => `${h.padStart(2, "0")}:${mm}`)
      .join(", ");
    return fmt;
  };

  const t = times();
  if (dom === "*" && mon === "*" && dow === "*" && t) {
    return `Daily at ${t}`;
  }
  if (dom === "*" && mon === "*" && dow !== "*" && t) {
    const days = dow
      .split(",")
      .map((d) => DOW[Number(d) % 7] ?? d)
      .join(", ");
    return `${days} at ${t}`;
  }
  return raw;
}

function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function keepRateTone(rate: number, total: number): "outline" | "success" | "warning" {
  if (total === 0) return "outline";
  if (rate >= 60) return "success";
  if (rate <= 30) return "warning";
  return "outline";
}

function SurfaceCard({ surface }: { surface: HeartbeatSurface }) {
  const [showLearnings, setShowLearnings] = useState(false);
  const cfg = surface.config;
  const last = surface.lastRun;
  const exp = surface.experiments;
  const enabled = cfg?.enabled !== false;

  const lastSummary = (last?.summary || last?.found || "").trim();
  const lastRanAt = last?.ran_at || null;

  const learnings = (surface.learnings || "").trim();
  // Treat the seed placeholder as "no learnings yet" for the collapsed state.
  const hasLearnings =
    learnings.length > 0 && !/\(none yet/i.test(learnings);

  const recentExperiments = exp.history.slice(0, 3);

  return (
    <Card className={cn(!enabled && "opacity-70")}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <CardTitle>{titleCase(surface.surface)}</CardTitle>
              {!enabled && (
                <Badge variant="secondary">paused</Badge>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {prettyCron(cfg?.cadence)}
              </span>
              <span className="inline-flex items-center gap-1">
                <Repeat className="h-3 w-3" />
                {surface.runCount} {surface.runCount === 1 ? "run" : "runs"}
              </span>
              {cfg?.experiment?.every_n_runs ? (
                <span className="inline-flex items-center gap-1">
                  <FlaskConical className="h-3 w-3" />
                  experiment every {cfg.experiment.every_n_runs}
                </span>
              ) : null}
            </div>
          </div>
          <Badge variant={keepRateTone(exp.stats.keepRate, exp.stats.kept + exp.stats.discarded)}>
            {exp.stats.kept + exp.stats.discarded > 0
              ? `${exp.stats.keepRate}% kept`
              : "no experiments"}
          </Badge>
        </div>
        {cfg?.goal && (
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{cfg.goal}</p>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Last run */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
              Last run
            </span>
            <span className="text-[11px] text-muted-foreground">
              {formatRelative(lastRanAt)}
            </span>
          </div>
          {lastSummary ? (
            <p className="whitespace-pre-wrap text-xs leading-5 text-foreground/90">
              {lastSummary}
            </p>
          ) : (
            <p className="text-xs italic text-muted-foreground/70">
              No runs yet — fires on its cadence.
            </p>
          )}
        </div>

        {/* Active experiment */}
        {exp.active && (
          <div className="rounded-md border border-border bg-secondary/30 p-2.5">
            <div className="flex items-center gap-1.5">
              <Beaker className="h-3.5 w-3.5 text-foreground/70" />
              <span className="text-[11px] font-medium uppercase tracking-wide text-foreground/70">
                Running experiment
              </span>
            </div>
            {exp.active.hypothesis && (
              <p className="mt-1 text-xs leading-5 text-foreground/90">
                {exp.active.hypothesis}
              </p>
            )}
          </div>
        )}

        {/* Recent experiments */}
        {recentExperiments.length > 0 && (
          <div className="space-y-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
              Recent experiments
            </span>
            <ul className="space-y-1.5">
              {recentExperiments.map((e, i) => (
                <li
                  key={e.id || i}
                  className="flex items-start gap-2 rounded-md bg-secondary/30 p-2"
                >
                  <Badge
                    variant={
                      e.decision === "keep"
                        ? "success"
                        : e.decision === "discard"
                          ? "warning"
                          : "outline"
                    }
                    className="mt-0.5 shrink-0"
                  >
                    {e.decision || "open"}
                  </Badge>
                  <span className="min-w-0 text-xs leading-5 text-muted-foreground">
                    {e.learning || e.hypothesis || e.id || "experiment"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Learnings */}
        {hasLearnings && (
          <div className="space-y-1.5">
            <button
              type="button"
              onClick={() => setShowLearnings((v) => !v)}
              className="flex w-full items-center gap-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80 hover:text-foreground"
            >
              {showLearnings ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              Learnings
            </button>
            {showLearnings && (
              <div className="rounded-md border border-border bg-secondary/20 p-3">
                <Markdown content={learnings} />
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared form (create + inline edit)                                 */
/* ------------------------------------------------------------------ */

function HeartbeatForm({
  value,
  onChange,
  onSubmit,
  onCancel,
  submitLabel,
  busy,
  agents,
}: {
  value: FormValues;
  onChange: (next: FormValues) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  submitLabel: string;
  busy: boolean;
  agents: AgentHubAgent[];
}) {
  const set = (patch: Partial<FormValues>) => onChange({ ...value, ...patch });

  const intervalChips = [
    ...INTERVAL_PRESETS.map((p) => ({ key: p.key, label: p.label })),
    { key: "daily", label: "Daily" },
    { key: "custom", label: "Custom" },
  ];

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="hb-name">Name (optional)</Label>
        <Input
          id="hb-name"
          value={value.name}
          placeholder="Morning briefing"
          onChange={(e) => set({ name: e.target.value })}
        />
      </div>

      <div className="space-y-2">
        <Label>How often</Label>
        <div className="flex flex-wrap gap-1.5">
          {intervalChips.map((chip) => {
            const active = value.intervalKey === chip.key;
            return (
              <button
                key={chip.key}
                type="button"
                onClick={() => set({ intervalKey: chip.key })}
                className={cn(
                  "h-8 rounded-md border px-3 text-xs font-medium transition-colors",
                  active
                    ? "border-foreground/20 bg-secondary text-foreground"
                    : "border-border bg-card text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
                )}
              >
                {chip.label}
              </button>
            );
          })}
        </div>

        {value.intervalKey === "daily" && (
          <div className="flex items-center gap-2 pt-1">
            <span className="text-xs text-muted-foreground">at</span>
            <Input
              type="time"
              value={value.dailyTime}
              onChange={(e) => set({ dailyTime: e.target.value })}
              className="w-32"
            />
          </div>
        )}

        {value.intervalKey === "custom" && (
          <div className="space-y-1 pt-1">
            <Input
              value={value.customSchedule}
              placeholder='e.g. "every 90m" or "0 9 * * 1-5"'
              onChange={(e) => set({ customSchedule: e.target.value })}
            />
            <p className="text-[11px] text-muted-foreground">
              Plain interval like <code>every 90m</code> or a cron expression.
            </p>
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="hb-instructions">Instructions</Label>
        <textarea
          id="hb-instructions"
          value={value.instructions}
          placeholder={INSTRUCTIONS_PLACEHOLDER}
          onChange={(e) => set({ instructions: e.target.value })}
          rows={5}
          className="w-full resize-y rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
        />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="flex-1 space-y-1.5">
          <Label htmlFor="hb-agent">Run as agent</Label>
          <Select
            id="hb-agent"
            value={value.agent}
            onValueChange={(v) => set({ agent: v })}
          >
            <SelectOption value="">Default agent</SelectOption>
            {agents
              .filter((a) => a.enabled)
              .map((a) => (
                <SelectOption key={a.id} value={a.id}>
                  {a.name}
                </SelectOption>
              ))}
          </Select>
        </div>
        <div className="flex-1 space-y-1.5">
          <Label htmlFor="hb-deliver">Deliver to</Label>
          <Select
            id="hb-deliver"
            value={value.deliver}
            onValueChange={(v) => set({ deliver: v })}
          >
            {DELIVER_OPTIONS.map((d) => (
              <SelectOption key={d.value} value={d.value}>
                {d.label}
              </SelectOption>
            ))}
          </Select>
        </div>
      </div>
      {value.deliver !== "local" && (
        <p className="text-[11px] text-muted-foreground">
          {(() => {
            const a = agents.find((x) => x.id === value.agent);
            const who = a?.name || "the default agent";
            if (
              value.deliver === "telegram" &&
              a?.telegramLane &&
              !a.telegramLane.configured
            ) {
              return `${who} has no Telegram bot wired yet — set it up in Agent Hub, or it falls back to this feed.`;
            }
            return `The result is handed to ${who}, then sent to ${value.deliver}.`;
          })()}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={onSubmit} disabled={busy}>
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
          {submitLabel}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function HeartbeatPage() {
  const { toast, showToast } = useToast();
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [agents, setAgents] = useState<AgentHubAgent[]>([]);
  const [surfaces, setSurfaces] = useState<HeartbeatSurface[]>([]);
  const [surfacesLoaded, setSurfacesLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [createForm, setCreateForm] = useState<FormValues>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<FormValues>(EMPTY_FORM);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const all = await api.getCronJobs({ refresh: true });
      setJobs(all.filter(isHeartbeat));
    } catch (e) {
      // Surface only on first load; background polls fail silently.
      setJobs((prev) => prev);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 20000);
    return () => window.clearInterval(id);
  }, [refresh]);

  // Agent Hub agents power the "Run as agent" picker. Telegram delivery routes
  // to the chosen agent's own bot (per-agent ELEVATE_AGENT_<id>_TELEGRAM_*).
  useEffect(() => {
    api
      .getAgentHub({ lite: true })
      .then((snap) => setAgents(snap.agents || []))
      .catch(() => setAgents([]));
  }, []);

  // Surface heartbeats: per-account work+experiment loop per surface
  // (Admin, Leads). Read-only view of config/last-run/learnings/experiments.
  const refreshSurfaces = useCallback(async () => {
    try {
      const resp = await api.getHeartbeatSurfaces({ refresh: true });
      setSurfaces(resp.surfaces || []);
    } catch {
      // background poll — keep last good state
    } finally {
      setSurfacesLoaded(true);
    }
  }, []);

  useEffect(() => {
    refreshSurfaces();
    const id = window.setInterval(refreshSurfaces, 30000);
    return () => window.clearInterval(id);
  }, [refreshSurfaces]);

  const markBusy = (id: string, on: boolean) =>
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const softRefreshSoon = useCallback(() => {
    // Heartbeat runs are async; nudge a few refreshes so the result lands.
    [3000, 8000, 15000].forEach((ms) => {
      if (pollRef.current) window.clearTimeout(pollRef.current);
      pollRef.current = window.setTimeout(refresh, ms);
    });
  }, [refresh]);

  const handleCreate = async () => {
    const schedule = scheduleFromForm(createForm);
    if (!createForm.instructions.trim()) {
      showToast("Add instructions for the heartbeat", "error");
      return;
    }
    if (!schedule) {
      showToast("Pick an interval", "error");
      return;
    }
    setCreating(true);
    try {
      await api.createCronJob({
        prompt: createForm.instructions.trim(),
        schedule,
        name: createForm.name.trim() || createForm.instructions.trim().slice(0, 40),
        deliver: createForm.deliver || "local",
        agent: createForm.agent || undefined,
        origin: HEARTBEAT_ORIGIN,
      });
      showToast("Heartbeat created ✓", "success");
      setCreateForm(EMPTY_FORM);
      await refresh();
    } catch (e) {
      showToast(`Couldn't create heartbeat: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  const beginEdit = (job: CronJob) => {
    setEditingId(job.id);
    setEditForm(formFromJob(job));
  };

  const handleSaveEdit = async () => {
    if (!editingId) return;
    const schedule = scheduleFromForm(editForm);
    if (!editForm.instructions.trim()) {
      showToast("Instructions can't be empty", "error");
      return;
    }
    if (!schedule) {
      showToast("Pick an interval", "error");
      return;
    }
    markBusy(editingId, true);
    try {
      await api.updateCronJob(editingId, {
        name: editForm.name.trim() || editForm.instructions.trim().slice(0, 40),
        prompt: editForm.instructions.trim(),
        schedule,
        deliver: editForm.deliver || "local",
        agent: editForm.agent || null,
      });
      showToast("Saved ✓", "success");
      setEditingId(null);
      await refresh();
    } catch (e) {
      showToast(`Couldn't save: ${e}`, "error");
    } finally {
      markBusy(editingId, false);
    }
  };

  const handleToggle = async (job: CronJob) => {
    markBusy(job.id, true);
    try {
      if (job.enabled) await api.pauseCronJob(job.id);
      else await api.resumeCronJob(job.id);
      await refresh();
    } catch (e) {
      showToast(`Couldn't update: ${e}`, "error");
    } finally {
      markBusy(job.id, false);
    }
  };

  const handleRunNow = async (job: CronJob) => {
    markBusy(job.id, true);
    try {
      await api.triggerCronJob(job.id);
      showToast("Running now — result lands here shortly", "success");
      softRefreshSoon();
    } catch (e) {
      showToast(`Couldn't run: ${e}`, "error");
    } finally {
      markBusy(job.id, false);
    }
  };

  const handleDelete = async (job: CronJob) => {
    markBusy(job.id, true);
    try {
      await api.deleteCronJob(job.id);
      showToast("Deleted", "success");
      setJobs((prev) => prev.filter((j) => j.id !== job.id));
    } catch (e) {
      showToast(`Couldn't delete: ${e}`, "error");
    } finally {
      markBusy(job.id, false);
    }
  };

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const sorted = useMemo(
    () =>
      [...jobs].sort((a, b) => (a.name || a.prompt).localeCompare(b.name || b.prompt)),
    [jobs],
  );

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 pb-16">
      <Toast toast={toast} />

      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-foreground" />
          <h1 className="text-lg font-semibold text-foreground">Heartbeat</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          Scheduled check-ins. Set an interval and what to look at — your agent
          wakes on that clock, runs it, and reports back here.
        </p>
      </header>

      {/* Surface heartbeats — always-on, self-improving per surface */}
      {surfacesLoaded && surfaces.length > 0 && (
        <section className="space-y-3">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold text-foreground">Surfaces</h2>
            <p className="text-xs text-muted-foreground">
              Each surface runs its own work loop on a cadence and periodically
              experiments to do it better — compounding what it learns.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {surfaces.map((s) => (
              <SurfaceCard key={s.surface} surface={s} />
            ))}
          </div>
        </section>
      )}

      {/* Create */}
      <section className="rounded-lg border border-border bg-card/40 p-4">
        <h2 className="mb-3 text-sm font-semibold text-foreground">New heartbeat</h2>
        <HeartbeatForm
          value={createForm}
          onChange={setCreateForm}
          onSubmit={handleCreate}
          submitLabel="Create heartbeat"
          busy={creating}
          agents={agents}
        />
      </section>

      {/* List */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">
            Active heartbeats{sorted.length ? ` (${sorted.length})` : ""}
          </h2>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : sorted.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
            No heartbeats yet. Create one above.
          </div>
        ) : (
          sorted.map((job) => {
            const busy = busyIds.has(job.id);
            const isEditing = editingId === job.id;
            const isOpen = expanded.has(job.id);
            const summary = (job.last_summary || "").trim();
            return (
              <div
                key={job.id}
                className={cn(
                  "rounded-lg border border-border bg-card/40 p-4",
                  !job.enabled && "opacity-70",
                )}
              >
                {isEditing ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-foreground">
                        Edit heartbeat
                      </span>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    <HeartbeatForm
                      value={editForm}
                      onChange={setEditForm}
                      onSubmit={handleSaveEdit}
                      onCancel={() => setEditingId(null)}
                      submitLabel="Save"
                      busy={busy}
                      agents={agents}
                    />
                  </div>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-foreground">
                            {job.name || job.prompt.slice(0, 48)}
                          </span>
                          {!job.enabled && (
                            <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                              paused
                            </span>
                          )}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {prettySchedule(job)}
                          </span>
                          {job.deliver && job.deliver !== "local" && (
                            <span className="text-foreground/70">
                              → {job.deliver}
                              {job.agent
                                ? ` · ${agents.find((a) => a.id === job.agent)?.name || job.agent}`
                                : ""}
                            </span>
                          )}
                          <span>
                            last run{" "}
                            <span className={statusTone(job.last_status)}>
                              {formatRelative(job.last_run_at)}
                              {job.last_status ? ` · ${job.last_status}` : ""}
                            </span>
                          </span>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          title="Run now"
                          disabled={busy}
                          onClick={() => handleRunNow(job)}
                          className="rounded p-1.5 text-muted-foreground hover:bg-foreground/10 hover:text-foreground disabled:opacity-50"
                        >
                          {busy ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                        </button>
                        <button
                          type="button"
                          title={job.enabled ? "Pause" : "Resume"}
                          disabled={busy}
                          onClick={() => handleToggle(job)}
                          className="rounded p-1.5 text-muted-foreground hover:bg-foreground/10 hover:text-foreground disabled:opacity-50"
                        >
                          {job.enabled ? (
                            <Pause className="h-4 w-4" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                        </button>
                        <button
                          type="button"
                          title="Edit"
                          disabled={busy}
                          onClick={() => beginEdit(job)}
                          className="rounded p-1.5 text-muted-foreground hover:bg-foreground/10 hover:text-foreground disabled:opacity-50"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          title="Delete"
                          disabled={busy}
                          onClick={() => handleDelete(job)}
                          className="rounded p-1.5 text-muted-foreground hover:bg-destructive/15 hover:text-destructive disabled:opacity-50"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>

                    {/* Last result */}
                    {summary ? (
                      <button
                        type="button"
                        onClick={() => toggleExpanded(job.id)}
                        className="mt-3 flex w-full items-start gap-1.5 rounded-md bg-secondary/40 p-2.5 text-left"
                      >
                        {isOpen ? (
                          <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <span
                          className={cn(
                            "whitespace-pre-wrap text-xs text-muted-foreground",
                            !isOpen && "line-clamp-2",
                          )}
                        >
                          {summary}
                        </span>
                      </button>
                    ) : (
                      <p className="mt-3 text-xs italic text-muted-foreground/70">
                        No report yet — runs on schedule, or hit play to run now.
                      </p>
                    )}
                  </>
                )}
              </div>
            );
          })
        )}
      </section>
    </div>
  );
}
