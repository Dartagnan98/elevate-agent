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
  Puzzle,
  RefreshCw,
  Settings2,
  Target,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentHubAgent,
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
  SurfaceGoalsForm,
  SurfaceSettingsForm,
  timeAgo,
} from "./ExperimentsPage";

/* ------------------------------------------------------------------ */
/*  Agents = ONE roster (the real Agent Hub agents) with the cortextOS  */
/*  detail tabs. Each agent's heartbeat/experiments/goals/memory live   */
/*  on its surface (Admin→admin, Outreach→leads; others create one on   */
/*  demand). Skills/toolsets/platforms come from the Agent Hub. This is  */
/*  the unified backbone — not a separate surface list.                 */
/* ------------------------------------------------------------------ */

// An agent's heartbeat workspace is a surface. Most map by id; the leads
// surface is historically owned by the Outreach agent.
const AGENT_SURFACE_MAP: Record<string, string> = { outreach: "leads" };
const surfaceKeyFor = (agentId: string) => AGENT_SURFACE_MAP[agentId] ?? agentId;

type DetailTab =
  | "profile"
  | "settings"
  | "goals"
  | "heartbeat"
  | "experiments"
  | "crons"
  | "tasks"
  | "memory";

const DETAIL_TABS: { key: DetailTab; label: string; icon: typeof Bot; needsSurface: boolean }[] = [
  { key: "profile", label: "Profile", icon: Bot, needsSurface: false },
  { key: "heartbeat", label: "Heartbeat", icon: Activity, needsSurface: false },
  { key: "settings", label: "Settings", icon: Settings2, needsSurface: true },
  { key: "goals", label: "Goals", icon: Target, needsSurface: true },
  { key: "experiments", label: "Experiments", icon: FlaskConical, needsSurface: true },
  { key: "crons", label: "Crons", icon: Clock, needsSurface: false },
  { key: "tasks", label: "Tasks", icon: KanbanSquare, needsSurface: false },
  { key: "memory", label: "Memory", icon: Activity, needsSurface: true },
];

function statusTone(status: string): "success" | "warning" | "secondary" {
  if (status === "online" || status === "ready") return "success";
  if (status === "needs_model" || status === "needs_telegram") return "warning";
  return "secondary";
}

function Chips({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <span className="text-[11px] italic text-muted-foreground/60">{empty}</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((s) => (
        <span key={s} className="rounded bg-secondary/50 px-1.5 py-0.5 text-[11px] text-foreground/80">
          {s}
        </span>
      ))}
    </div>
  );
}

/* ----------------------------- roster card ------------------------ */

function AgentCard({
  agent,
  surface,
  exp,
  onOpen,
  onToggle,
}: {
  agent: AgentHubAgent;
  surface?: HeartbeatSurface;
  exp?: HeartbeatExperimentSurface;
  onOpen: () => void;
  onToggle: (enabled: boolean) => void;
}) {
  const cycles = exp?.cycles.length ?? 0;
  return (
    <Card className="transition-colors hover:border-foreground/20">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <button type="button" onClick={onOpen} className="min-w-0 text-left">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 shrink-0 text-muted-foreground" />
              <CardTitle>{agent.name}</CardTitle>
              <Badge variant={statusTone(agent.status)} className="shrink-0">
                {agent.status}
              </Badge>
            </div>
            <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">
              {agent.description || agent.role || "No role set."}
            </p>
          </button>
          <Switch checked={agent.enabled} onCheckedChange={onToggle} />
        </div>
      </CardHeader>
      <CardContent>
        <button
          type="button"
          onClick={onOpen}
          className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left text-[11px] text-muted-foreground"
        >
          <span className="inline-flex items-center gap-1">
            <Puzzle className="h-3 w-3" />
            {agent.skills.length} skills
          </span>
          <span>{agent.toolsets.length} tools</span>
          {surface ? (
            <>
              <span>{surface.runCount} runs</span>
              <span className="inline-flex items-center gap-1">
                <FlaskConical className="h-3 w-3" />
                {cycles} {cycles === 1 ? "cycle" : "cycles"}
              </span>
            </>
          ) : (
            <span className="italic text-muted-foreground/60">no heartbeat</span>
          )}
        </button>
      </CardContent>
    </Card>
  );
}

/* ----------------------------- tab chrome ------------------------- */

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

function CreateHeartbeatCTA({
  agent,
  surfaceKey,
  onCreated,
}: {
  agent: AgentHubAgent;
  surfaceKey: string;
  onCreated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await api.createHeartbeatSurface({ surface: surfaceKey, title: agent.name });
      onCreated();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-lg border border-dashed border-border p-6 text-center">
      <p className="text-sm text-muted-foreground">
        {agent.name} has no heartbeat yet. Give it a work loop, experiments, and goals.
      </p>
      <Button className="mt-3" onClick={create} disabled={busy}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        Create heartbeat
      </Button>
    </div>
  );
}

function ProfileTab({ agent }: { agent: AgentHubAgent }) {
  return (
    <div className="space-y-3">
      <div className="flex gap-3 rounded-md bg-secondary/30 px-3 py-2">
        <span className="w-20 shrink-0 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          Role
        </span>
        <span className="text-xs leading-5 text-foreground/90">
          {agent.description || agent.role || "—"}
        </span>
      </div>
      <div className="space-y-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          Skills
        </span>
        <Chips items={agent.skills} empty="No skills installed." />
      </div>
      <div className="space-y-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          Toolsets
        </span>
        <Chips items={agent.toolsets} empty="No toolsets." />
      </div>
      <div className="space-y-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          Platforms
        </span>
        <Chips items={agent.platforms} empty="No platforms connected." />
      </div>
      <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
        <span>{agent.session_count} sessions</span>
        <span>{agent.active_session_count} active</span>
        {agent.telegramLane?.configured && <Badge variant="secondary">Telegram</Badge>}
      </div>
    </div>
  );
}

function HeartbeatTab({
  agent,
  surface,
  surfaceKey,
  onChanged,
}: {
  agent: AgentHubAgent;
  surface?: HeartbeatSurface;
  surfaceKey: string;
  onChanged: () => void;
}) {
  if (!surface) {
    return <CreateHeartbeatCTA agent={agent} surfaceKey={surfaceKey} onCreated={onChanged} />;
  }
  const cfg = (surface.config || {}) as Record<string, unknown>;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-md bg-secondary/30 px-3 py-2">
        <div>
          <p className="text-xs font-medium text-foreground/90">Work loop</p>
          <p className="text-[11px] text-muted-foreground">
            {(cfg.cadence as string) || "—"} · {surface.runCount} runs · last{" "}
            {timeAgo(surface.lastRun?.ran_at as string | undefined)}
          </p>
        </div>
        <Switch
          checked={!!surface.config?.enabled}
          onCheckedChange={async (v) => {
            await api.setHeartbeatSurfaceEnabled(surfaceKey, v);
            onChanged();
          }}
        />
      </div>
      {surface.lastRun?.summary && (
        <div className="rounded-md border border-border bg-card/40 p-3">
          <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/80">
            Last run
          </span>
          <p className="mt-0.5 text-xs leading-5 text-foreground/90">{surface.lastRun.summary}</p>
        </div>
      )}
    </div>
  );
}

function CronsTab({ surface, onChanged }: { surface?: HeartbeatSurface; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const automations = surface?.automations ?? [];
  const toggle = async (id: string, enabled: boolean) => {
    setBusy(id);
    try {
      await api.setHeartbeatAutomationEnabled(id, enabled);
      onChanged();
    } finally {
      setBusy(null);
    }
  };
  if (automations.length === 0) {
    return (
      <p className="text-xs italic text-muted-foreground/70">
        No automations for this agent. Add recurring jobs on the Automations page.
      </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {automations.map((a) => (
        <li key={a.id} className="flex items-center justify-between gap-3 rounded-md bg-secondary/30 p-2.5">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-foreground/90">{a.name}</p>
            <p className="text-[11px] text-muted-foreground">
              {a.schedule} · last {timeAgo(a.last_run_at)}
            </p>
          </div>
          <Switch checked={a.enabled} disabled={busy === a.id} onCheckedChange={(v) => toggle(a.id, v)} />
        </li>
      ))}
    </ul>
  );
}

function TasksTab({ agentId, surfaceKey }: { agentId: string; surfaceKey: string }) {
  const [tasks, setTasks] = useState<SurfaceTask[] | null>(null);
  useEffect(() => {
    let alive = true;
    // tasks may be assigned by agent id or by surface key
    Promise.all([
      api.listSurfaceTasks({ assignee: agentId }).catch(() => ({ tasks: [] as SurfaceTask[] })),
      surfaceKey !== agentId
        ? api.listSurfaceTasks({ assignee: surfaceKey }).catch(() => ({ tasks: [] as SurfaceTask[] }))
        : Promise.resolve({ tasks: [] as SurfaceTask[] }),
    ])
      .then(([a, b]) => {
        if (!alive) return;
        const seen = new Set<string>();
        const merged = [...a.tasks, ...b.tasks].filter((t) => !seen.has(t.id) && seen.add(t.id));
        setTasks(merged);
      })
      .catch(() => alive && setTasks([]));
    return () => {
      alive = false;
    };
  }, [agentId, surfaceKey]);
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
  agent,
  surface,
  exp,
  onBack,
  onChanged,
}: {
  agent: AgentHubAgent;
  surface?: HeartbeatSurface;
  exp?: HeartbeatExperimentSurface;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("profile");
  const [showNewCycle, setShowNewCycle] = useState(false);
  const surfaceKey = surfaceKeyFor(agent.id);
  const hasSurface = !!surface;
  const needsSurfaceGate =
    DETAIL_TABS.find((t) => t.key === tab)?.needsSurface && !hasSurface;

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
          <span className="text-xs text-muted-foreground">{agent.enabled ? "Enabled" : "Disabled"}</span>
          <Switch
            checked={agent.enabled}
            onCheckedChange={async (v) => {
              await api.updateAgent(agent.id, { enabled: v });
              onChanged();
            }}
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Bot className="h-5 w-5 text-foreground" />
        <h1 className="text-lg font-semibold text-foreground">{agent.name}</h1>
        <Badge variant={statusTone(agent.status)}>{agent.status}</Badge>
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
        {tab === "profile" && <ProfileTab agent={agent} />}
        {tab === "heartbeat" && (
          <HeartbeatTab
            agent={agent}
            surface={surface}
            surfaceKey={surfaceKey}
            onChanged={onChanged}
          />
        )}
        {needsSurfaceGate ? (
          tab !== "profile" && tab !== "heartbeat" && tab !== "crons" && tab !== "tasks" ? (
            <CreateHeartbeatCTA agent={agent} surfaceKey={surfaceKey} onCreated={onChanged} />
          ) : null
        ) : (
          <>
            {tab === "settings" && <SurfaceSettingsForm surface={surfaceKey} onClose={onChanged} />}
            {tab === "goals" && <SurfaceGoalsForm surface={surfaceKey} onClose={onChanged} />}
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
                      <CycleRow key={c.name || i} cycle={c} surface={surfaceKey} onChanged={onChanged} />
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
                  <Modal title={`New cycle · ${agent.name}`} onClose={() => setShowNewCycle(false)}>
                    <NewCycleForm
                      surface={surfaceKey}
                      onClose={() => setShowNewCycle(false)}
                      onCreated={onChanged}
                    />
                  </Modal>
                )}
              </div>
            )}
            {tab === "memory" && (
              <div>
                {(surface?.learnings || "").trim() ? (
                  <pre className="whitespace-pre-wrap break-words font-mono-ui text-xs leading-5 text-foreground/90">
                    {surface!.learnings}
                  </pre>
                ) : (
                  <p className="text-xs italic text-muted-foreground/70">
                    No learnings recorded yet — they accumulate as this agent runs.
                  </p>
                )}
              </div>
            )}
          </>
        )}
        {tab === "crons" && <CronsTab surface={surface} onChanged={onChanged} />}
        {tab === "tasks" && <TasksTab agentId={agent.id} surfaceKey={surfaceKey} />}
      </div>
    </div>
  );
}

/* ------------------------------- page ----------------------------- */

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentHubAgent[]>([]);
  const [surfaces, setSurfaces] = useState<HeartbeatSurface[]>([]);
  const [expSurfaces, setExpSurfaces] = useState<HeartbeatExperimentSurface[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [hub, s, e] = await Promise.all([
        api.getAgentHub({ includeSkills: true, includeToolsets: true }),
        api.getHeartbeatSurfaces({ refresh }),
        api
          .getHeartbeatExperiments({ refresh })
          .catch(() => ({ surfaces: [] as HeartbeatExperimentSurface[] })),
      ]);
      setAgents(hub.agents || []);
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

  const surfaceByKey = useMemo(() => {
    const m: Record<string, HeartbeatSurface> = {};
    for (const s of surfaces) m[s.surface] = s;
    return m;
  }, [surfaces]);
  const expByKey = useMemo(() => {
    const m: Record<string, HeartbeatExperimentSurface> = {};
    for (const s of expSurfaces) m[s.surface] = s;
    return m;
  }, [expSurfaces]);

  const current = selected ? agents.find((a) => a.id === selected) : null;

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
              Your fleet — skills, crons, heartbeat, experiments, goals, and memory per agent.
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
          agent={current}
          surface={surfaceByKey[surfaceKeyFor(current.id)]}
          exp={expByKey[surfaceKeyFor(current.id)]}
          onBack={() => setSelected(null)}
          onChanged={() => load(true)}
        />
      ) : agents.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          No agents found.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {agents.map((a) => (
            <AgentCard
              key={a.id}
              agent={a}
              surface={surfaceByKey[surfaceKeyFor(a.id)]}
              exp={expByKey[surfaceKeyFor(a.id)]}
              onOpen={() => setSelected(a.id)}
              onToggle={async (v) => {
                await api.updateAgent(a.id, { enabled: v });
                load(true);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
