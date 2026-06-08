import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentCommsMessage,
  AgentHubAgent,
  AgentHubSnapshot,
  CronJob,
  HeartbeatSurface,
  HeartbeatSurfacesResponse,
  SurfaceApproval,
  SurfaceTask,
  TodayDashboardResponse,
} from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, isoTimeAgo, timeAgo as epochTimeAgo } from "@/lib/utils";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";

type OverviewState = {
  agentHub: AgentHubSnapshot | null;
  surfaces: HeartbeatSurface[];
  tasks: SurfaceTask[];
  approvals: SurfaceApproval[];
  comms: AgentCommsMessage[];
  crons: CronJob[];
  today: TodayDashboardResponse | null;
};

type BadgeTone = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";

type ActionItem = {
  id: string;
  title: string;
  detail: string;
  href: string;
  tone: BadgeTone;
  label: string;
};

type ActivityItem = {
  id: string;
  title: string;
  detail: string;
  ts?: string | null;
  href: string;
  tone: BadgeTone;
  icon: ReactNode;
};

const EMPTY_STATE: OverviewState = {
  agentHub: null,
  surfaces: [],
  tasks: [],
  approvals: [],
  comms: [],
  crons: [],
  today: null,
};

function nowDayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

function createdAt(task: SurfaceTask): string | null | undefined {
  return task.createdAt || task.created_at;
}

function completedAt(task: SurfaceTask): string | null | undefined {
  return task.completedAt || task.completed_at;
}

function taskAssignee(task: SurfaceTask): string {
  return task.assignee || task.assigned_to || "";
}

function isoAgo(iso?: string | null): string {
  if (!iso) return "-";
  return isoTimeAgo(iso);
}

function titleize(value?: string | null): string {
  const text = String(value || "").trim();
  if (!text) return "Unassigned";
  return text
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function taskOpen(task: SurfaceTask): boolean {
  return !task.archived && !["completed", "cancelled"].includes(task.status);
}

function agentHealthy(agent: AgentHubAgent): boolean {
  if (!agent.enabled || agent.lifecycleSummary?.suspended) return false;
  return ["online", "ready"].includes(agent.status);
}

function agentNeedsAttention(agent: AgentHubAgent): boolean {
  if (!agent.enabled) return false;
  if (agent.lifecycleSummary?.suspended) return true;
  if (["needs_model", "needs_telegram", "offline"].includes(agent.status)) return true;
  if ((agent.queueSummary?.waitingHuman || 0) > 0) return true;
  if ((agent.automationSummary?.failures || 0) > 0) return true;
  return false;
}

function agentStatusTone(agent: AgentHubAgent): BadgeTone {
  if (!agent.enabled || agent.lifecycleSummary?.suspended) return "secondary";
  if (agentHealthy(agent)) return "success";
  if (agentNeedsAttention(agent)) return "warning";
  return "outline";
}

function recentAgentTime(agent: AgentHubAgent): string | null {
  const candidates = [
    agent.observability?.lastScopedTickAt,
    agent.observability?.lastWakeAt,
    agent.queueSummary?.lastWorkerTickAt,
    agent.automationSummary?.lastRunAt,
  ].filter(Boolean) as string[];
  if (!candidates.length) return null;
  return candidates.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
}

function metricToneClass(tone: BadgeTone): string {
  switch (tone) {
    case "success":
      return "text-success";
    case "warning":
      return "text-warning";
    case "destructive":
      return "text-destructive";
    default:
      return "text-foreground";
  }
}

function MetricTile({
  icon,
  label,
  value,
  meta,
  tone = "default",
  href,
  loading,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  meta: string;
  tone?: BadgeTone;
  href: string;
  loading?: boolean;
}) {
  return (
    <Link
      to={href}
      className="group block rounded-md border border-border bg-card/45 p-3 transition-colors hover:border-foreground/25 hover:bg-card"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className="text-muted-foreground group-hover:text-foreground">{icon}</div>
      </div>
      {loading ? (
        <>
          <Skeleton className="mt-2 h-8 w-16" />
          <Skeleton className="mt-1 h-3 w-28" />
        </>
      ) : (
        <>
          <div className={cn("mt-2 text-2xl font-semibold tracking-normal", metricToneClass(tone))}>
            {value}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{meta}</div>
        </>
      )}
    </Link>
  );
}

function RowSkeleton() {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-border bg-background/35 p-3">
      <div className="min-w-0 flex-1 space-y-2">
        <Skeleton className="h-4 w-2/5" />
        <Skeleton className="h-3 w-3/5" />
      </div>
      <Skeleton className="h-5 w-14 shrink-0 rounded-full" />
    </div>
  );
}

function ActionRequired({ items, loading }: { items: ActionItem[]; loading?: boolean }) {
  if (loading) {
    return (
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-warning" />
            <CardTitle>Action Required</CardTitle>
          </div>
          <Skeleton className="h-5 w-8 rounded-full" />
        </CardHeader>
        <CardContent className="space-y-2">
          <RowSkeleton />
          <RowSkeleton />
        </CardContent>
      </Card>
    );
  }
  if (!items.length) {
    return (
      <Card>
        <CardContent className="flex items-center justify-between gap-3 p-4">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-success" />
            <div>
              <div className="text-sm font-medium text-foreground">No blocked action</div>
              <div className="text-xs text-muted-foreground">Agents, tasks, and approvals are clear.</div>
            </div>
          </div>
          <Badge variant="success">Clear</Badge>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-warning" />
          <CardTitle>Action Required</CardTitle>
        </div>
        <Badge variant="warning">{items.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item) => (
          <Link
            key={item.id}
            to={item.href}
            className="flex items-start justify-between gap-3 rounded-md border border-border bg-background/35 p-3 hover:border-foreground/25"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-foreground">{item.title}</div>
              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.detail}</div>
            </div>
            <Badge variant={item.tone} className="shrink-0">
              {item.label}
            </Badge>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

function AgentFleet({ agents, loading }: { agents: AgentHubAgent[]; loading?: boolean }) {
  const ordered = useMemo(
    () =>
      [...agents].sort((a, b) => {
        const score = (agent: AgentHubAgent) => (agentNeedsAttention(agent) ? 0 : agentHealthy(agent) ? 2 : 1);
        return score(a) - score(b) || a.name.localeCompare(b.name);
      }),
    [agents],
  );
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-foreground" />
          <CardTitle>Agent Status</CardTitle>
        </div>
        <Link to="/hub" className="text-xs font-medium text-muted-foreground hover:text-foreground">
          Open Hub
        </Link>
      </CardHeader>
      <CardContent className="space-y-2">
        {loading ? (
          <>
            <RowSkeleton />
            <RowSkeleton />
            <RowSkeleton />
            <RowSkeleton />
          </>
        ) : ordered.length === 0 ? (
          <div className="rounded-md border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
            No agents configured.
          </div>
        ) : (
          ordered.slice(0, 8).map((agent) => {
            const last = recentAgentTime(agent);
            return (
              <Link
                key={agent.id}
                to={`/hub?agent=${encodeURIComponent(agent.id)}`}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-background/35 p-3 hover:border-foreground/25"
              >
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        agentHealthy(agent)
                          ? "bg-success"
                          : agentNeedsAttention(agent)
                            ? "bg-warning"
                            : "bg-muted-foreground/45",
                      )}
                    />
                    <span className="truncate text-sm font-medium text-foreground">{agent.name}</span>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {titleize(agent.role)} · queue {agent.queueSummary?.queued || 0} · waiting{" "}
                    {agent.queueSummary?.waitingHuman || 0}
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Badge variant={agentStatusTone(agent)}>{agent.lifecycleSummary?.suspended ? "Suspended" : agent.status}</Badge>
                  <span className="text-[11px] text-muted-foreground">{last ? isoAgo(last) : "no runs"}</span>
                </div>
              </Link>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

function LiveActivity({ items, loading }: { items: ActivityItem[]; loading?: boolean }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-foreground" />
          <CardTitle>Live Activity</CardTitle>
        </div>
        <Link to="/activity" className="text-xs font-medium text-muted-foreground hover:text-foreground">
          View Feed
        </Link>
      </CardHeader>
      <CardContent className="space-y-2">
        {loading ? (
          <>
            <RowSkeleton />
            <RowSkeleton />
            <RowSkeleton />
            <RowSkeleton />
          </>
        ) : items.length === 0 ? (
          <div className="rounded-md border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
            No recent activity.
          </div>
        ) : (
          items.slice(0, 7).map((item) => (
            <Link
              key={item.id}
              to={item.href}
              className="flex items-start gap-3 rounded-md border border-border bg-background/35 p-3 hover:border-foreground/25"
            >
              <div className="mt-0.5 text-muted-foreground">{item.icon}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-foreground">{item.title}</span>
                  <Badge variant={item.tone} className="shrink-0">
                    {item.detail}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{isoAgo(item.ts)}</div>
              </div>
            </Link>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function FocusCardSkeleton() {
  return (
    <div className="rounded-md border border-border bg-background/35 p-3 space-y-2">
      <div className="flex items-center justify-between gap-3">
        <Skeleton className="h-4 w-2/5" />
        <Skeleton className="h-5 w-10 shrink-0 rounded-full" />
      </div>
      <Skeleton className="h-3 w-4/5" />
    </div>
  );
}

function FocusPanel({ surfaces, tasks, loading }: { surfaces: HeartbeatSurface[]; tasks: SurfaceTask[]; loading?: boolean }) {
  const focusSurfaces = surfaces
    .filter((surface) => surface.config?.goal || surface.lastRun?.summary || surface.lastRun?.did)
    .slice(0, 5);
  const completedToday = tasks.filter((task) => completedAt(task)?.startsWith(nowDayKey())).slice(0, 5);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-foreground" />
          <CardTitle>Current Focus</CardTitle>
        </div>
        <Link to="/heartbeat" className="text-xs font-medium text-muted-foreground hover:text-foreground">
          Heartbeats
        </Link>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground">Work Loops</div>
          {loading ? (
            <>
              <FocusCardSkeleton />
              <FocusCardSkeleton />
              <FocusCardSkeleton />
            </>
          ) : focusSurfaces.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              No active focus recorded.
            </div>
          ) : (
            focusSurfaces.map((surface) => (
              <div key={surface.surface} className="rounded-md border border-border bg-background/35 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="truncate text-sm font-medium text-foreground">{surface.config?.surface || titleize(surface.surface)}</div>
                  <Badge variant={surface.config?.enabled === false ? "secondary" : "success"}>
                    {surface.config?.enabled === false ? "Off" : "On"}
                  </Badge>
                </div>
                <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {surface.config?.goal || surface.lastRun?.summary || surface.lastRun?.did || "No focus"}
                </div>
              </div>
            ))
          )}
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground">Today&apos;s Progress</div>
          {loading ? (
            <>
              <FocusCardSkeleton />
              <FocusCardSkeleton />
              <FocusCardSkeleton />
            </>
          ) : completedToday.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              No completed tasks today.
            </div>
          ) : (
            completedToday.map((task) => (
              <Link key={task.id} to={`/tasks?task=${encodeURIComponent(task.id)}`} className="block rounded-md border border-border bg-background/35 p-3 hover:border-foreground/25">
                <div className="truncate text-sm font-medium text-foreground">{task.title}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {titleize(taskAssignee(task))} · {isoAgo(completedAt(task))}
                </div>
              </Link>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function SystemHealth({ agents, crons, surfaces, loading }: { agents: AgentHubAgent[]; crons: CronJob[]; surfaces: HeartbeatSurface[]; loading?: boolean }) {
  const [open, setOpen] = useState(false);
  const enabledAgents = agents.filter((agent) => agent.enabled);
  const healthy = enabledAgents.filter(agentHealthy).length;
  const attention = enabledAgents.filter(agentNeedsAttention).length;
  const cronFailures = crons.filter((job) => job.last_error || job.last_status === "failed").length;
  const disabledLoops = surfaces.filter((surface) => surface.config?.enabled === false).length;
  const tone: BadgeTone = attention || cronFailures ? "warning" : "success";
  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-muted/25"
      >
        <div className="flex items-center gap-3">
          <ShieldCheck className={cn("h-5 w-5", tone === "success" ? "text-success" : "text-warning")} />
          <div>
            <div className="text-sm font-semibold text-foreground">System Health</div>
            {loading ? (
              <Skeleton className="mt-1 h-3 w-64" />
            ) : (
              <div className="text-xs text-muted-foreground">
                {healthy}/{enabledAgents.length} agents healthy · {cronFailures} cron failures · {disabledLoops} loops off
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {loading ? (
            <Skeleton className="h-5 w-16 rounded-full" />
          ) : (
            <Badge variant={tone}>{attention || cronFailures ? "Review" : "Healthy"}</Badge>
          )}
          {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
        </div>
      </button>
      {open && (
        <CardContent className="border-t border-border">
          <div className="grid gap-2 md:grid-cols-2">
            {enabledAgents.map((agent) => {
              const last = recentAgentTime(agent);
              return (
                <div key={agent.id} className="rounded-md border border-border bg-background/35 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-medium text-foreground">{agent.name}</div>
                    <Badge variant={agentStatusTone(agent)}>{agent.lifecycleSummary?.suspended ? "Suspended" : agent.status}</Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <div>Queued {agent.queueSummary?.queued || 0}</div>
                    <div>Running {agent.queueSummary?.running || 0}</div>
                    <div>Waiting {agent.queueSummary?.waitingHuman || 0}</div>
                    <div>Last {last ? isoAgo(last) : "none"}</div>
                  </div>
                  {agent.lifecycleSummary?.reason && (
                    <div className="mt-2 line-clamp-2 text-xs text-warning">{agent.lifecycleSummary.reason}</div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export default function OverviewPage() {
  const [state, setState] = useState<OverviewState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [agentHub, heartbeatResp, taskResp, approvalResp, comms, crons, today] = await Promise.all([
        api.getAgentHub({
          lite: true,
          includeMemoryGraph: false,
          includeSessionTotal: false,
          includeOrchestration: true,
          includeSkills: false,
          includeToolsets: false,
          includeHarness: true,
        }),
        api.getHeartbeatSurfaces({ refresh }),
        api.listSurfaceTasks({ include_archived: false }),
        api.listSurfaceApprovals({ status: "pending" }),
        api.getCommsFeed({ limit: 30 }),
        api.getCronJobs({ compact: true, refresh }),
        api.getToday(60),
      ]);
      setState({
        agentHub,
        surfaces: (heartbeatResp as HeartbeatSurfacesResponse).surfaces || [],
        tasks: taskResp.tasks || [],
        approvals: approvalResp.approvals || [],
        comms: comms || [],
        crons: crons || [],
        today,
      });
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
    const id = window.setInterval(() => void load(true), 20000);
    return () => window.clearInterval(id);
  }, [load]);
  useRefreshOnAgentTurn(() => void load(true));

  const agents = state.agentHub?.agents || [];
  const enabledAgents = agents.filter((agent) => agent.enabled);
  const healthyAgents = enabledAgents.filter(agentHealthy);
  const attentionAgents = enabledAgents.filter(agentNeedsAttention);
  const openTasks = state.tasks.filter(taskOpen);
  const blockedTasks = openTasks.filter((task) => task.status === "blocked");
  const todayKey = nowDayKey();
  const tasksToday = state.tasks.filter((task) => createdAt(task)?.startsWith(todayKey) || completedAt(task)?.startsWith(todayKey));
  const humanTasks = openTasks.filter((task) => taskAssignee(task).toLowerCase() === "human");
  const cronFailures = state.crons.filter((job) => job.last_error || job.last_status === "failed");

  const actions = useMemo<ActionItem[]>(() => {
    const items: ActionItem[] = [];
    for (const task of humanTasks.slice(0, 3)) {
      items.push({
        id: `human-${task.id}`,
        title: task.title,
        detail: `${titleize(taskAssignee(task))} · ${task.priority}`,
        href: `/tasks?task=${encodeURIComponent(task.id)}`,
        tone: "warning",
        label: "Task",
      });
    }
    for (const approval of state.approvals.slice(0, 3)) {
      items.push({
        id: `approval-${approval.id}`,
        title: approval.title,
        detail: approval.description || titleize(approval.category),
        href: "/approvals",
        tone: "warning",
        label: "Approval",
      });
    }
    for (const task of blockedTasks.slice(0, 3)) {
      items.push({
        id: `blocked-${task.id}`,
        title: task.title,
        detail: `${titleize(taskAssignee(task))} · blocked`,
        href: `/tasks?task=${encodeURIComponent(task.id)}`,
        tone: "destructive",
        label: "Blocked",
      });
    }
    for (const agent of attentionAgents.slice(0, 3)) {
      items.push({
        id: `agent-${agent.id}`,
        title: agent.name,
        detail: agent.lifecycleSummary?.reason || `Status ${agent.status}`,
        href: `/hub?agent=${encodeURIComponent(agent.id)}`,
        tone: "warning",
        label: "Agent",
      });
    }
    for (const job of cronFailures.slice(0, 2)) {
      items.push({
        id: `cron-${job.id}`,
        title: job.name || job.id,
        detail: job.last_error || job.last_status || "Cron needs attention",
        href: "/cron",
        tone: "destructive",
        label: "Cron",
      });
    }
    return items.slice(0, 8);
  }, [attentionAgents, blockedTasks, cronFailures, humanTasks, state.approvals]);

  const liveItems = useMemo<ActivityItem[]>(() => {
    const comms = state.comms.map((message) => ({
      id: `comms-${message.id}`,
      title: `${titleize(message.from)} to ${titleize(message.to)}`,
      detail: message.priority || "message",
      ts: message.timestamp || message.createdAt,
      href: `/comms?agent=${encodeURIComponent(message.from)}`,
      tone: (message.priority === "urgent" || message.priority === "high" ? "warning" : "outline") as BadgeTone,
      icon: <MessageSquare className="h-4 w-4" />,
    }));
    const runs = (state.today?.running || []).map((run, index) => {
      const record = run as unknown as Record<string, unknown>;
      const title = String(record.title || record.name || record.command || `Run ${index + 1}`);
      const ts = typeof record.started_at === "string" ? record.started_at : typeof record.startedAt === "string" ? record.startedAt : state.today?.generatedAt;
      return {
        id: `run-${String(record.id || index)}`,
        title,
        detail: "running",
        ts,
        href: "/activity",
        tone: "success" as BadgeTone,
        icon: <Activity className="h-4 w-4" />,
      };
    });
    const recentCrons = state.crons
      .filter((job) => job.last_run_at)
      .slice(0, 6)
      .map((job) => ({
        id: `cron-${job.id}`,
        title: job.name || job.id,
        detail: job.last_status || "cron",
        ts: job.last_run_at,
        href: "/cron",
        tone: (job.last_error || job.last_status === "failed" ? "destructive" : "outline") as BadgeTone,
        icon: <Clock className="h-4 w-4" />,
      }));
    return [...runs, ...comms, ...recentCrons].sort((a, b) => new Date(b.ts || 0).getTime() - new Date(a.ts || 0).getTime());
  }, [state.comms, state.crons, state.today]);

  const generated = state.agentHub?.generated_at ? epochTimeAgo(state.agentHub.generated_at) : state.today?.generatedAt ? isoAgo(state.today.generatedAt) : "-";

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 pb-16">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-foreground" />
            <h1 className="text-lg font-semibold text-foreground">Overview</h1>
          </div>
          <p className="text-sm text-muted-foreground">Fleet status, action queue, work loops, and live operations.</p>
        </div>
        <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </Button>
      </header>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn&apos;t load overview: {error}
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile
              icon={<Bot className="h-4 w-4" />}
              label="Agents Online"
              value={`${healthyAgents.length}/${enabledAgents.length}`}
              meta={`${attentionAgents.length} need review · ${generated}`}
              tone={attentionAgents.length ? "warning" : "success"}
              href="/hub"
              loading={loading}
            />
            <MetricTile
              icon={<CheckCircle2 className="h-4 w-4" />}
              label="Tasks Today"
              value={String(tasksToday.length)}
              meta={`${openTasks.length} open · ${blockedTasks.length} blocked`}
              tone={blockedTasks.length ? "warning" : "default"}
              href="/tasks"
              loading={loading}
            />
            <MetricTile
              icon={<ShieldCheck className="h-4 w-4" />}
              label="Approvals"
              value={String(state.approvals.length)}
              meta={`${humanTasks.length} human tasks`}
              tone={state.approvals.length ? "warning" : "success"}
              href="/approvals"
              loading={loading}
            />
            <MetricTile
              icon={<Clock className="h-4 w-4" />}
              label="Automations"
              value={String(state.crons.filter((job) => job.enabled).length)}
              meta={`${cronFailures.length} failures · ${state.surfaces.length} loops`}
              tone={cronFailures.length ? "destructive" : "default"}
              href="/cron"
              loading={loading}
            />
          </div>

          <ActionRequired items={actions} loading={loading} />

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.85fr)]">
            <AgentFleet agents={agents} loading={loading} />
            <LiveActivity items={liveItems} loading={loading} />
          </div>

          <FocusPanel surfaces={state.surfaces} tasks={state.tasks} loading={loading} />

          <SystemHealth agents={agents} crons={state.crons} surfaces={state.surfaces} loading={loading} />
        </>
      )}
    </div>
  );
}
