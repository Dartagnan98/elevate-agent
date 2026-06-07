import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Clock,
  FlaskConical,
  KanbanSquare,
  Loader2,
  Plus,
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
import { Switch } from "@/components/ui/switch";
import { Modal } from "@/components/ui/modal";
import { ListSkeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  CycleRow,
  ExperimentRow,
  NewCycleForm,
  SurfaceGoalsForm,
  SurfaceSettingsForm,
  timeAgo,
} from "@/pages/ExperimentsPage";

/* ------------------------------------------------------------------ */
/*  AgentLoops — the cortextOS loop tabs (Heartbeat/Settings/Goals/     */
/*  Experiments/Crons/Tasks/Memory) for ONE Agent Hub agent, shown as   */
/*  a collapsible section inside that agent's card. The agent's loops    */
/*  live on its heartbeat surface (Outreach→leads, others→id; created    */
/*  on demand). This is what makes the Agent Hub the single config page. */
/* ------------------------------------------------------------------ */

const AGENT_SURFACE_MAP: Record<string, string> = { outreach: "leads" };
const surfaceKeyFor = (agentId: string) => AGENT_SURFACE_MAP[agentId] ?? agentId;

type LoopTab =
  | "heartbeat"
  | "settings"
  | "goals"
  | "experiments"
  | "crons"
  | "tasks"
  | "memory";

const TABS: { key: LoopTab; label: string; icon: typeof Activity; needsSurface: boolean }[] = [
  { key: "heartbeat", label: "Heartbeat", icon: Activity, needsSurface: false },
  { key: "settings", label: "Settings", icon: Settings2, needsSurface: true },
  { key: "goals", label: "Goals", icon: Target, needsSurface: true },
  { key: "experiments", label: "Experiments", icon: FlaskConical, needsSurface: true },
  { key: "crons", label: "Crons", icon: Clock, needsSurface: false },
  { key: "tasks", label: "Tasks", icon: KanbanSquare, needsSurface: false },
  { key: "memory", label: "Memory", icon: Activity, needsSurface: true },
];

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Activity;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[11px] font-medium transition-colors",
        active
          ? "border-foreground/20 bg-secondary text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}

function TasksTab({ agentId, surfaceKey }: { agentId: string; surfaceKey: string }) {
  const [tasks, setTasks] = useState<SurfaceTask[] | null>(null);
  useEffect(() => {
    let alive = true;
    Promise.all([
      api.listSurfaceTasks({ assignee: agentId }).catch(() => ({ tasks: [] as SurfaceTask[] })),
      surfaceKey !== agentId
        ? api.listSurfaceTasks({ assignee: surfaceKey }).catch(() => ({ tasks: [] as SurfaceTask[] }))
        : Promise.resolve({ tasks: [] as SurfaceTask[] }),
    ])
      .then(([a, b]) => {
        if (!alive) return;
        const seen = new Set<string>();
        setTasks([...a.tasks, ...b.tasks].filter((t) => !seen.has(t.id) && seen.add(t.id)));
      })
      .catch(() => alive && setTasks([]));
    return () => {
      alive = false;
    };
  }, [agentId, surfaceKey]);
  if (tasks === null)
    return <ListSkeleton rows={2} className="py-1" />;
  if (!tasks.length)
    return (
      <p className="text-[11px] italic text-muted-foreground/70">
        No tasks dispatched to this agent.
      </p>
    );
  return (
    <ul className="space-y-1.5">
      {tasks.map((t) => (
        <li key={t.id} className="space-y-1 rounded-md bg-secondary/30 p-2">
          <div className="flex items-center gap-1.5">
            <Badge variant="secondary" className="shrink-0">
              {t.status.replace("_", " ")}
            </Badge>
            <span className="text-[11px] font-medium text-foreground/90">{t.title}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function AgentLoops({
  agentId,
  agentName,
  defaultOpen = false,
}: {
  agentId: string;
  agentName: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<LoopTab>("heartbeat");
  const [showNewCycle, setShowNewCycle] = useState(false);
  const [surface, setSurface] = useState<HeartbeatSurface | undefined>();
  const [exp, setExp] = useState<HeartbeatExperimentSurface | undefined>();
  const [busyCreate, setBusyCreate] = useState(false);

  const surfaceKey = surfaceKeyFor(agentId);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, e] = await Promise.all([
        api.getHeartbeatSurfaces({ refresh: true }),
        api
          .getHeartbeatExperiments({ refresh: true })
          .catch(() => ({ surfaces: [] as HeartbeatExperimentSurface[] })),
      ]);
      setSurface((s.surfaces || []).find((x) => x.surface === surfaceKey));
      setExp((e.surfaces || []).find((x) => x.surface === surfaceKey));
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  }, [surfaceKey]);

  useEffect(() => {
    if (open && !loaded) load();
  }, [open, loaded, load]);

  const createHeartbeat = async () => {
    setBusyCreate(true);
    try {
      await api.createHeartbeatSurface({ surface: surfaceKey, title: agentName });
      await load();
    } finally {
      setBusyCreate(false);
    }
  };

  const hasSurface = !!surface;
  const tabDef = TABS.find((t) => t.key === tab);
  const gated = tabDef?.needsSurface && !hasSurface;

  const cfg = (surface?.config || {}) as Record<string, unknown>;

  return (
    <div className="mt-3 rounded-md border border-border/70 bg-card/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80 hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        Heartbeat · Experiments · Goals
        {!hasSurface && loaded && (
          <span className="ml-auto text-[10px] normal-case italic text-muted-foreground/60">
            not set up
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-3 border-t border-border/70 p-3">
          {loading && !loaded ? (
            <ListSkeleton rows={2} className="py-1" />
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5">
                {TABS.map((t) => (
                  <TabButton
                    key={t.key}
                    active={tab === t.key}
                    onClick={() => setTab(t.key)}
                    icon={t.icon}
                    label={t.label}
                  />
                ))}
              </div>

              {tab === "heartbeat" &&
                (hasSurface ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between rounded-md bg-secondary/30 px-3 py-2">
                      <div>
                        <p className="text-xs font-medium text-foreground/90">Work loop</p>
                        <p className="text-[11px] text-muted-foreground">
                          {(cfg.cadence as string) || "—"} · {surface!.runCount} runs · last{" "}
                          {timeAgo(surface!.lastRun?.ran_at as string | undefined)}
                        </p>
                      </div>
                      <Switch
                        checked={!!surface!.config?.enabled}
                        onCheckedChange={async (v) => {
                          await api.setHeartbeatSurfaceEnabled(surfaceKey, v);
                          load();
                        }}
                      />
                    </div>
                    {surface!.lastRun?.summary && (
                      <div className="rounded-md border border-border bg-card/40 p-2.5">
                        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/80">
                          Last run
                        </span>
                        <p className="mt-0.5 text-[11px] leading-5 text-foreground/90">
                          {surface!.lastRun.summary}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-border p-4 text-center">
                    <p className="text-xs text-muted-foreground">
                      {agentName} has no heartbeat yet — give it a work loop, experiments, and goals.
                    </p>
                    <Button className="mt-2.5 h-8" onClick={createHeartbeat} disabled={busyCreate}>
                      {busyCreate ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Plus className="h-4 w-4" />
                      )}
                      Create heartbeat
                    </Button>
                  </div>
                ))}

              {gated && tab !== "heartbeat" && tab !== "crons" && tab !== "tasks" && (
                <p className="text-[11px] italic text-muted-foreground/70">
                  Create a heartbeat first (Heartbeat tab) to use {tab}.
                </p>
              )}

              {!gated && tab === "settings" && (
                <SurfaceSettingsForm surface={surfaceKey} onClose={load} />
              )}
              {!gated && tab === "goals" && (
                <SurfaceGoalsForm surface={surfaceKey} onClose={load} />
              )}
              {!gated && tab === "experiments" && (
                <div className="space-y-3">
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
                        <CycleRow key={c.name || i} cycle={c} surface={surfaceKey} onChanged={load} />
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[11px] italic text-muted-foreground/70">No cycles yet.</p>
                  )}
                  {exp && exp.experiments.length > 0 && (
                    <ul className="space-y-1.5">
                      {exp.experiments.map((e, i) => (
                        <ExperimentRow key={e.id || i} exp={e} />
                      ))}
                    </ul>
                  )}
                  {showNewCycle && (
                    <Modal title={`New cycle · ${agentName}`} onClose={() => setShowNewCycle(false)}>
                      <NewCycleForm
                        surface={surfaceKey}
                        onClose={() => setShowNewCycle(false)}
                        onCreated={load}
                      />
                    </Modal>
                  )}
                </div>
              )}
              {tab === "crons" &&
                (surface?.automations.length ? (
                  <ul className="space-y-1.5">
                    {surface.automations.map((a) => (
                      <li
                        key={a.id}
                        className="flex items-center justify-between gap-3 rounded-md bg-secondary/30 p-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-[11px] font-medium text-foreground/90">
                            {a.name}
                          </p>
                          <p className="text-[10px] text-muted-foreground">
                            {a.schedule} · last {timeAgo(a.last_run_at)}
                          </p>
                        </div>
                        <Switch
                          checked={a.enabled}
                          onCheckedChange={async (v) => {
                            await api.setHeartbeatAutomationEnabled(a.id, v);
                            load();
                          }}
                        />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] italic text-muted-foreground/70">
                    No automations. Add recurring jobs on the Automations page.
                  </p>
                ))}
              {tab === "tasks" && <TasksTab agentId={agentId} surfaceKey={surfaceKey} />}
              {!gated && tab === "memory" && (
                <div>
                  {(surface?.learnings || "").trim() ? (
                    <pre className="whitespace-pre-wrap break-words font-mono-ui text-[11px] leading-5 text-foreground/90">
                      {surface!.learnings}
                    </pre>
                  ) : (
                    <p className="text-[11px] italic text-muted-foreground/70">
                      No learnings recorded yet.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
