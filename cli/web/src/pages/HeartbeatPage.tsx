import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
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
import { ListSkeleton } from "@/components/ui/skeleton";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Heartbeat = a scheduled self-prompt (cortextOS-style).            */
/*  The realtor sets an interval + instructions; the agent wakes on    */
/*  that clock, runs the instructions in a fresh session, and reports  */
/*  back into this feed. Each heartbeat is a cron job tagged as one of */
/*  Elevate's native heartbeat origins so it stays out of page clutter.*/
/* ------------------------------------------------------------------ */

interface IntervalPreset {
  key: string;
  label: string;
  schedule: string;
  minutes: number;
}

type ReportMode = "quiet" | "notify";

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
  agent: string; // Agent Hub agent id that owns/runs it
  deliver: string; // result routing: local | telegram | discord | slack | email
  reportMode: ReportMode;
}

const EMPTY_FORM: FormValues = {
  name: "",
  intervalKey: "1h",
  dailyTime: "08:00",
  customSchedule: "",
  instructions: "",
  agent: "",
  deliver: "local",
  reportMode: "quiet",
};

const DELIVER_OPTIONS: { value: string; label: string }[] = [
  { value: "local", label: "In-app (this feed)" },
  { value: "telegram", label: "Telegram" },
  { value: "discord", label: "Discord" },
  { value: "slack", label: "Slack" },
  { value: "email", label: "Email" },
];

const REPORT_MODE_OPTIONS: { value: ReportMode; label: string }[] = [
  { value: "quiet", label: "Only important changes" },
  { value: "notify", label: "Every run" },
];

function preferredAgentId(agents: AgentHubAgent[]): string {
  const enabled = agents.filter((agent) => agent.enabled);
  return (
    enabled.find((agent) => agent.role === "orchestrator")?.id ||
    enabled.find((agent) => agent.id === "executive-assistant")?.id ||
    enabled[0]?.id ||
    ""
  );
}

function isHeartbeat(job: CronJob): boolean {
  const type = String(job.origin?.type || "");
  return type === "heartbeat" || type === "surface-heartbeat" || type === "cortext-native-loop";
}

function heartbeatSurfaceKey(job: CronJob): string {
  const origin = job.origin || {};
  const surface = origin.surface;
  return typeof surface === "string" ? surface : "";
}

function heartbeatAgentId(job: CronJob, surface?: HeartbeatSurface | null): string {
  if (job.agent) return job.agent;
  const cfgAgent = surface?.config?.agent;
  if (typeof cfgAgent === "string" && cfgAgent) return cfgAgent;
  const originAgent = job.origin?.agent;
  return typeof originAgent === "string" ? originAgent : "";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normalizeReportMode(value: unknown): ReportMode | null {
  const raw = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (["notify", "notifying", "always", "always-notify", "every-run", "report"].includes(raw)) {
    return "notify";
  }
  if (["quiet", "silent", "changes", "change-only", "important", "important-only"].includes(raw)) {
    return "quiet";
  }
  return null;
}

function heartbeatReportMode(job: CronJob, surface?: HeartbeatSurface | null): ReportMode {
  const metadata = asRecord(job.metadata);
  const origin = asRecord(job.origin);
  const config = asRecord(surface?.config);
  return (
    normalizeReportMode(metadata.heartbeat_report_mode) ||
    normalizeReportMode(metadata.report_mode) ||
    normalizeReportMode(metadata.notification_mode) ||
    normalizeReportMode(origin.heartbeat_report_mode) ||
    normalizeReportMode(origin.report_mode) ||
    normalizeReportMode(origin.notification_mode) ||
    normalizeReportMode(config.heartbeat_report_mode) ||
    normalizeReportMode(config.report_mode) ||
    normalizeReportMode(config.notification_mode) ||
    "quiet"
  );
}

function reportModeLabel(mode: ReportMode): string {
  return mode === "notify" ? "Every run" : "Only important changes";
}

function withHeartbeatReportMode(
  metadata: Record<string, unknown> | undefined,
  mode: ReportMode,
): Record<string, unknown> {
  return { ...(metadata || {}), heartbeat_report_mode: mode };
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

function formScheduleParts(schedule?: CronJob["schedule"], display = "") {
  const sched = schedule || ({} as CronJob["schedule"]);
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

  return { intervalKey, dailyTime, customSchedule };
}

function formFromJob(job: CronJob, surface?: HeartbeatSurface | null): FormValues {
  if (surface?.config) {
    const cfg = surface.config;
    const scheduleParts = formScheduleParts(job.schedule, cfg.cadence || job.schedule_display);
    return {
      name: job.name || "",
      ...scheduleParts,
      instructions: cfg.goal || job.prompt || "",
      agent: heartbeatAgentId(job, surface),
      deliver: job.deliver || cfg.deliver || "local",
      reportMode: heartbeatReportMode(job, surface),
    };
  }

  const sched = job.schedule || ({} as CronJob["schedule"]);
  const display = job.schedule_display || sched.display || "";
  const scheduleParts = formScheduleParts(sched, display);

  return {
    name: job.name || "",
    ...scheduleParts,
    instructions: job.prompt || "",
    agent: heartbeatAgentId(job),
    deliver: job.deliver || "local",
    reportMode: heartbeatReportMode(job),
  };
}

function surfaceLastSummary(surface?: HeartbeatSurface | null): string {
  const last = surface?.lastRun;
  return String(last?.summary || last?.found || "").trim();
}

function surfaceLastRunAt(surface?: HeartbeatSurface | null): string | null {
  return surface?.lastRun?.ran_at || null;
}

function surfaceLearnings(surface?: HeartbeatSurface | null): string {
  const learnings = String(surface?.learnings || "").trim();
  return learnings && !/\(none yet/i.test(learnings) ? learnings : "";
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
  deliverOptions = DELIVER_OPTIONS,
  showActions = true,
}: {
  value: FormValues;
  onChange: (next: FormValues) => void;
  onSubmit: () => void;
  onCancel?: () => void;
  submitLabel: string;
  busy: boolean;
  agents: AgentHubAgent[];
  deliverOptions?: { value: string; label: string }[];
  showActions?: boolean;
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

      <div className="flex flex-col gap-3 lg:flex-row">
        <div className="flex-1 space-y-1.5">
          <Label htmlFor="hb-agent">Which agent is this for?</Label>
          <Select
            id="hb-agent"
            value={value.agent}
            onValueChange={(v) => set({ agent: v })}
          >
            <SelectOption value="">Choose agent</SelectOption>
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
          <Label htmlFor="hb-report-mode">Report mode</Label>
          <Select
            id="hb-report-mode"
            value={value.reportMode}
            onValueChange={(v) => set({ reportMode: normalizeReportMode(v) || "quiet" })}
          >
            {REPORT_MODE_OPTIONS.map((mode) => (
              <SelectOption key={mode.value} value={mode.value}>
                {mode.label}
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
            {deliverOptions.map((d) => (
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
            const who = a?.name || "the selected agent";
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

      {showActions && (
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
      )}
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
  const [surfaceByKey, setSurfaceByKey] = useState<Record<string, HeartbeatSurface>>({});
  const [searchParams, setSearchParams] = useSearchParams();
  const agentParam = searchParams.get("agent") ?? "";
  const [agentFilter, setAgentFilter] = useState(agentParam);
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
      const [all, surfaceResp] = await Promise.all([
        api.getCronJobs({ refresh: true }),
        api.getHeartbeatSurfaces({ refresh: true }).catch(() => ({ surfaces: [] })),
      ]);
      setJobs(all.filter(isHeartbeat));
      const nextSurfaceByKey: Record<string, HeartbeatSurface> = {};
      for (const surface of surfaceResp.surfaces || []) {
        nextSurfaceByKey[surface.surface] = surface;
      }
      setSurfaceByKey(nextSurfaceByKey);
    } catch (e) {
      // Toast only on direct actions; background polls fail silently.
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
  useRefreshOnAgentTurn(() => void refresh());

  useEffect(() => {
    setAgentFilter(agentParam);
  }, [agentParam]);

  // Agent Hub agents power the heartbeat owner picker. Telegram delivery routes
  // to the chosen agent's own bot (per-agent ELEVATE_AGENT_<id>_TELEGRAM_*).
  useEffect(() => {
    api
      .getAgentHub({ lite: true })
      .then((snap) => setAgents(snap.agents || []))
      .catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    setCreateForm((prev) => {
      if (prev.agent || !agents.length) return prev;
      const agent = preferredAgentId(agents);
      return agent ? { ...prev, agent } : prev;
    });
  }, [agents]);

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
    const title =
      createForm.name.trim() || createForm.instructions.trim().split(/\s+/).slice(0, 4).join(" ");
    if (!createForm.instructions.trim()) {
      showToast("Add instructions for the heartbeat", "error");
      return;
    }
    if (!schedule) {
      showToast("Pick an interval", "error");
      return;
    }
    if (agents.length && !createForm.agent.trim()) {
      showToast("Pick the agent that runs this heartbeat", "error");
      return;
    }
    setCreating(true);
    try {
      await api.createCronJob({
        prompt: createForm.instructions.trim(),
        schedule,
        name: title,
        deliver: createForm.deliver || "local",
        agent: createForm.agent || "",
        metadata: withHeartbeatReportMode(undefined, createForm.reportMode),
        origin: { type: "heartbeat", source: "heartbeat-page" },
      });
      showToast("Heartbeat created", "success");
      const defaultAgent = preferredAgentId(agents);
      setCreateForm(defaultAgent ? { ...EMPTY_FORM, agent: defaultAgent } : EMPTY_FORM);
      await refresh();
    } catch (e) {
      showToast(`Couldn't create heartbeat: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  const beginEdit = (job: CronJob) => {
    setEditingId(job.id);
    setEditForm(formFromJob(job, surfaceByKey[heartbeatSurfaceKey(job)]));
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
      const job = jobs.find((candidate) => candidate.id === editingId);
      const surfaceKey = job ? heartbeatSurfaceKey(job) : "";
      if (surfaceKey) {
        await api.patchHeartbeatSurfaceConfig(surfaceKey, {
          goal: editForm.instructions.trim(),
          cadence: schedule,
          agent: editForm.agent || "",
          heartbeat_report_mode: editForm.reportMode,
        });
        await api.setHeartbeatSurfaceRoute(surfaceKey, editForm.deliver || "local");
        const metadata = withHeartbeatReportMode(asRecord(job?.metadata), editForm.reportMode);
        await api.updateCronJob(editingId, {
          name: editForm.name.trim() || editForm.instructions.trim().slice(0, 40),
          metadata,
        });
      } else {
        const metadata = withHeartbeatReportMode(asRecord(job?.metadata), editForm.reportMode);
        await api.updateCronJob(editingId, {
          name: editForm.name.trim() || editForm.instructions.trim().slice(0, 40),
          prompt: editForm.instructions.trim(),
          schedule,
          deliver: editForm.deliver || "local",
          agent: editForm.agent || null,
          metadata,
        });
      }
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
    const name = job.name || "this heartbeat";
    if (!window.confirm(`Delete "${name}"? This removes the heartbeat schedule only.`)) {
      return;
    }
    markBusy(job.id, true);
    try {
      await api.deleteCronJob(job.id);
      showToast("Deleted", "success");
      setJobs((prev) => prev.filter((j) => j.id !== job.id));
      if (editingId === job.id) setEditingId(null);
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

  const updateAgentFilter = useCallback(
    (nextAgent: string) => {
      setAgentFilter(nextAgent);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (nextAgent) next.set("agent", nextAgent);
          else next.delete("agent");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const filteredJobs = useMemo(
    () =>
      jobs.filter((job) => {
        const surface = surfaceByKey[heartbeatSurfaceKey(job)];
        return !agentFilter || heartbeatAgentId(job, surface) === agentFilter;
      }),
    [agentFilter, jobs, surfaceByKey],
  );

  const sorted = useMemo(
    () =>
      [...filteredJobs].sort((a, b) => (a.name || a.prompt).localeCompare(b.name || b.prompt)),
    [filteredJobs],
  );

  const heartbeatCount = sorted.length;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 pb-16">
      <Toast toast={toast} />

      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-foreground" />
          <h1 className="text-lg font-semibold text-foreground">Heartbeat</h1>
        </div>
      </header>

      <section className="rounded-lg border border-border bg-card/40 p-4">
        <h2 className="mb-3 text-sm font-semibold text-foreground">Create heartbeat</h2>
        <HeartbeatForm
          value={createForm}
          onChange={setCreateForm}
          onSubmit={handleCreate}
          submitLabel="Create heartbeat"
          busy={creating}
          agents={agents}
        />
      </section>

      <section className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold text-foreground">
              Heartbeats{heartbeatCount ? ` (${heartbeatCount})` : ""}
            </h2>
          </div>
          <div className="w-full sm:w-44">
            <Select value={agentFilter} onValueChange={updateAgentFilter}>
              <SelectOption value="">All agents</SelectOption>
              {agents.map((agent) => (
                <SelectOption key={agent.id} value={agent.id}>
                  {agent.name}
                </SelectOption>
              ))}
            </Select>
          </div>
        </div>

        {loading ? (
              <ListSkeleton rows={3} />
            ) : (
              sorted.map((job) => {
            const busy = busyIds.has(job.id);
            const isEditing = editingId === job.id;
            const isOpen = expanded.has(job.id);
            const surface = surfaceByKey[heartbeatSurfaceKey(job)];
            const summary = surfaceLastSummary(surface) || (job.last_summary || "").trim();
            const learnings = surfaceLearnings(surface);
            const lastRunAt = surfaceLastRunAt(surface) || job.last_run_at;
            const agentId = heartbeatAgentId(job, surface);
            const agentName = agents.find((a) => a.id === agentId)?.name || agentId;
            const reportMode = heartbeatReportMode(job, surface);
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
                          {agentId && (
                            <span>
                              {agentName}
                            </span>
                          )}
                          {job.deliver && job.deliver !== "local" && (
                            <span className="text-foreground/70">
                              → {job.deliver}
                            </span>
                          )}
                          <span>{reportModeLabel(reportMode)}</span>
                          <span>
                            last run{" "}
                            <span className={statusTone(job.last_status)}>
                              {formatRelative(lastRunAt)}
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

                    {learnings && (
                      <button
                        type="button"
                        onClick={() => toggleExpanded(`${job.id}:learnings`)}
                        className="mt-2 flex w-full items-start gap-1.5 rounded-md bg-secondary/20 p-2.5 text-left"
                      >
                        {expanded.has(`${job.id}:learnings`) ? (
                          <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <span
                          className={cn(
                            "whitespace-pre-wrap text-xs text-muted-foreground",
                            !expanded.has(`${job.id}:learnings`) && "line-clamp-2",
                          )}
                        >
                          {learnings}
                        </span>
                      </button>
                    )}
                  </>
                )}
              </div>
            );
              })
            )}

            {!loading && sorted.length === 0 && (
              <div className="rounded-lg border border-dashed border-border bg-card/20 p-8 text-center text-sm text-muted-foreground">
                No heartbeats yet. Create one above.
              </div>
            )}
      </section>
    </div>
  );
}
