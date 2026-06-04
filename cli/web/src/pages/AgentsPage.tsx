import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Bot,
  Clock,
  FlaskConical,
  KanbanSquare,
  Loader2,
  Plus,
  RefreshCw,
  Settings2,
  Target,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  HeartbeatSurface,
  HeartbeatExperimentSurface,
  SurfaceTask,
} from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/utils";
import {
  CycleRow,
  ExperimentRow,
  NewCycleForm,
  NewSurfaceForm,
  SurfaceGoalsForm,
  SurfaceSettingsForm,
  timeAgo,
  titleCase,
} from "./ExperimentsPage";

/* ------------------------------------------------------------------ */
/*  Agents = the fleet hub. A roster of surface-agents; click one to    */
/*  open its detail with sub-tabs (Profile/Settings/Goals/Experiments/  */
/*  Crons/Tasks/Memory) that reuse the same building blocks the rest of */
/*  the app uses. Mirrors cortextOS /ai/agents + the agent-detail tabs. */
/* ------------------------------------------------------------------ */

type DetailTab =
  | "profile"
  | "settings"
  | "goals"
  | "experiments"
  | "crons"
  | "tasks"
  | "memory";

const DETAIL_TABS: { key: DetailTab; label: string; icon: typeof Bot }[] = [
  { key: "profile", label: "Profile", icon: Bot },
  { key: "settings", label: "Settings", icon: Settings2 },
  { key: "goals", label: "Goals", icon: Target },
  { key: "experiments", label: "Experiments", icon: FlaskConical },
  { key: "crons", label: "Crons", icon: Clock },
  { key: "tasks", label: "Tasks", icon: KanbanSquare },
  { key: "memory", label: "Memory", icon: Activity },
];

function cfgVal(config: unknown, key: string): string {
  const c = (config || {}) as Record<string, unknown>;
  const v = c[key];
  return typeof v === "string" ? v : "";
}

/* ----------------------------- roster card ------------------------ */

function AgentCard({
  surface,
  exp,
  onOpen,
  onToggle,
}: {
  surface: HeartbeatSurface;
  exp?: HeartbeatExperimentSurface;
  onOpen: () => void;
  onToggle: (enabled: boolean) => void;
}) {
  const enabled = !!surface.config?.enabled;
  const cycles = exp?.cycles.length ?? 0;
  const model = cfgVal(surface.config, "model") || "default";
  return (
    <Card className="transition-colors hover:border-foreground/20">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <button type="button" onClick={onOpen} className="min-w-0 text-left">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 shrink-0 text-muted-foreground" />
              <CardTitle>{titleCase(surface.surface)}</CardTitle>
              <Badge variant={enabled ? "success" : "secondary"} className="shrink-0">
                {enabled ? "on" : "off"}
              </Badge>
            </div>
            <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">
              {cfgVal(surface.config, "goal") || "No role set."}
            </p>
          </button>
          <Switch checked={enabled} onCheckedChange={onToggle} />
        </div>
      </CardHeader>
      <CardContent>
        <button
          type="button"
          onClick={onOpen}
          className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left text-[11px] text-muted-foreground"
        >
          <span>{surface.runCount} runs</span>
          <span>last {timeAgo(surface.lastRun?.ran_at as string | undefined)}</span>
          <span className="inline-flex items-center gap-1">
            <FlaskConical className="h-3 w-3" />
            {cycles} {cycles === 1 ? "cycle" : "cycles"}
          </span>
          <span>{surface.automations.length} crons</span>
          <Badge variant="outline" className="shrink-0">
            {model}
          </Badge>
        </button>
      </CardContent>
    </Card>
  );
}

/* ----------------------------- detail tabs ------------------------ */

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Bot;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition-colors",
        active
          ? "border-foreground/20 bg-secondary text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

function ProfileTab({ surface }: { surface: HeartbeatSurface }) {
  const rows: { label: string; value: string }[] = [
    { label: "Role", value: cfgVal(surface.config, "goal") || "—" },
    { label: "Cadence", value: cfgVal(surface.config, "cadence") || "—" },
    { label: "Status", value: surface.config?.enabled ? "Enabled" : "Disabled" },
    { label: "Runs", value: String(surface.runCount) },
    {
      label: "Last run",
      value: surface.lastRun?.summary
        ? `${surface.lastRun.summary} (${timeAgo(surface.lastRun.ran_at as string | undefined)})`
        : "never",
    },
    { label: "Model", value: cfgVal(surface.config, "model") || "harness default" },
    { label: "Route", value: cfgVal(surface.config, "deliver") || "local (in-app)" },
  ];
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex gap-3 rounded-md bg-secondary/30 px-3 py-2">
          <span className="w-20 shrink-0 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
            {r.label}
          </span>
          <span className="text-xs leading-5 text-foreground/90">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

function CronsTab({
  surface,
  onChanged,
}: {
  surface: HeartbeatSurface;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const toggle = async (id: string, enabled: boolean) => {
    setBusy(id);
    try {
      await api.setHeartbeatAutomationEnabled(id, enabled);
      onChanged();
    } finally {
      setBusy(null);
    }
  };
  if (surface.automations.length === 0) {
    return (
      <p className="text-xs italic text-muted-foreground/70">
        No automations for this agent. Add recurring jobs on the Automations page.
      </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {surface.automations.map((a) => (
        <li
          key={a.id}
          className="flex items-center justify-between gap-3 rounded-md bg-secondary/30 p-2.5"
        >
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-foreground/90">{a.name}</p>
            <p className="text-[11px] text-muted-foreground">
              {a.schedule} · last {timeAgo(a.last_run_at)}
            </p>
          </div>
          <Switch
            checked={a.enabled}
            disabled={busy === a.id}
            onCheckedChange={(v) => toggle(a.id, v)}
          />
        </li>
      ))}
    </ul>
  );
}

function TasksTab({ surface }: { surface: string }) {
  const [tasks, setTasks] = useState<SurfaceTask[] | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .listSurfaceTasks({ assignee: surface })
      .then((r) => alive && setTasks(r.tasks || []))
      .catch(() => alive && setTasks([]));
    return () => {
      alive = false;
    };
  }, [surface]);
  if (tasks === null) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (tasks.length === 0) {
    return (
      <p className="text-xs italic text-muted-foreground/70">
        No tasks dispatched to this agent. Dispatch from the Tasks page.
      </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {tasks.map((t) => (
        <li key={t.id} className="space-y-1 rounded-md bg-secondary/30 p-2.5">
          <div className="flex items-center gap-1.5">
            <Badge variant="secondary" className="shrink-0">
              {t.status.replace("_", " ")}
            </Badge>
            <span className="text-xs font-medium text-foreground/90">{t.title}</span>
          </div>
          {t.description && (
            <p className="line-clamp-2 text-[11px] text-muted-foreground">{t.description}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

function AgentDetail({
  surface,
  exp,
  onBack,
  onChanged,
}: {
  surface: HeartbeatSurface;
  exp?: HeartbeatExperimentSurface;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("profile");
  const [showNewCycle, setShowNewCycle] = useState(false);
  const enabled = !!surface.config?.enabled;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> All agents
        </button>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{enabled ? "On" : "Off"}</span>
          <Switch
            checked={enabled}
            onCheckedChange={async (v) => {
              await api.setHeartbeatSurfaceEnabled(surface.surface, v);
              onChanged();
            }}
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Bot className="h-5 w-5 text-foreground" />
        <h1 className="text-lg font-semibold text-foreground">{titleCase(surface.surface)}</h1>
      </div>

      <div className="flex flex-wrap gap-1.5 border-b border-border pb-2">
        {DETAIL_TABS.map((t) => (
          <TabButton
            key={t.key}
            active={tab === t.key}
            onClick={() => setTab(t.key)}
            icon={t.icon}
            label={t.label}
          />
        ))}
      </div>

      <div>
        {tab === "profile" && <ProfileTab surface={surface} />}
        {tab === "settings" && (
          <SurfaceSettingsForm surface={surface.surface} onClose={onChanged} />
        )}
        {tab === "goals" && <SurfaceGoalsForm surface={surface.surface} onClose={onChanged} />}
        {tab === "experiments" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                Research Cycles
              </span>
              <Button
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                onClick={() => setShowNewCycle(true)}
              >
                <Plus className="h-3 w-3" /> New cycle
              </Button>
            </div>
            {exp && exp.cycles.length > 0 ? (
              <ul className="space-y-1.5">
                {exp.cycles.map((c, i) => (
                  <CycleRow
                    key={c.name || i}
                    cycle={c}
                    surface={surface.surface}
                    onChanged={onChanged}
                  />
                ))}
              </ul>
            ) : (
              <p className="text-xs italic text-muted-foreground/70">
                No cycles yet — add one to start a research track.
              </p>
            )}
            <div className="space-y-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                Experiments
              </span>
              {exp && exp.experiments.length > 0 ? (
                <ul className="space-y-1.5">
                  {exp.experiments.map((e, i) => (
                    <ExperimentRow key={e.id || i} exp={e} />
                  ))}
                </ul>
              ) : (
                <p className="text-xs italic text-muted-foreground/70">No experiments yet.</p>
              )}
            </div>
            {showNewCycle && (
              <Modal
                title={`New cycle · ${titleCase(surface.surface)}`}
                onClose={() => setShowNewCycle(false)}
              >
                <NewCycleForm
                  surface={surface.surface}
                  onClose={() => setShowNewCycle(false)}
                  onCreated={onChanged}
                />
              </Modal>
            )}
          </div>
        )}
        {tab === "crons" && <CronsTab surface={surface} onChanged={onChanged} />}
        {tab === "tasks" && <TasksTab surface={surface.surface} />}
        {tab === "memory" && (
          <div>
            {(surface.learnings || "").trim() ? (
              <pre className="whitespace-pre-wrap break-words font-mono-ui text-xs leading-5 text-foreground/90">
                {surface.learnings}
              </pre>
            ) : (
              <p className="text-xs italic text-muted-foreground/70">
                No learnings recorded yet — they accumulate as this agent runs.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------- page ----------------------------- */

export default function AgentsPage() {
  const [surfaces, setSurfaces] = useState<HeartbeatSurface[]>([]);
  const [expSurfaces, setExpSurfaces] = useState<HeartbeatExperimentSurface[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [s, e] = await Promise.all([
        api.getHeartbeatSurfaces({ refresh }),
        api
          .getHeartbeatExperiments({ refresh })
          .catch(() => ({ surfaces: [] as HeartbeatExperimentSurface[] })),
      ]);
      setSurfaces(s.surfaces || []);
      setExpSurfaces((e.surfaces || []) as HeartbeatExperimentSurface[]);
      setError(null);
    } catch (err) {
      setError(String(err));
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

  const expBySurface = useMemo(() => {
    const m: Record<string, HeartbeatExperimentSurface> = {};
    for (const s of expSurfaces) m[s.surface] = s;
    return m;
  }, [expSurfaces]);

  const current = selected ? surfaces.find((s) => s.surface === selected) : null;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 pb-16">
      {!current && (
        <header className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-foreground" />
              <h1 className="text-lg font-semibold text-foreground">Agents</h1>
            </div>
            <p className="text-sm text-muted-foreground">
              Your surface-agents — each runs its own loop, goals, and experiments.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
              {refreshing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Refresh
            </Button>
            <Button onClick={() => setShowNew(true)}>
              <Plus className="h-4 w-4" /> New agent
            </Button>
          </div>
        </header>
      )}

      {showNew && (
        <Modal title="New agent (surface)" onClose={() => setShowNew(false)}>
          <NewSurfaceForm onClose={() => setShowNew(false)} onCreated={() => load(true)} />
        </Modal>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load agents: {error}
        </div>
      ) : current ? (
        <AgentDetail
          surface={current}
          exp={expBySurface[current.surface]}
          onBack={() => setSelected(null)}
          onChanged={() => load(true)}
        />
      ) : surfaces.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          No agents yet — create one to get started.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {surfaces.map((s) => (
            <AgentCard
              key={s.surface}
              surface={s}
              exp={expBySurface[s.surface]}
              onOpen={() => setSelected(s.surface)}
              onToggle={async (v) => {
                await api.setHeartbeatSurfaceEnabled(s.surface, v);
                load(true);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
