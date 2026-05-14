import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import {
  AlertTriangle,
  Bot,
  CalendarClock,
  Loader2,
  Repeat,
  Sparkles,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AccessStatusResponse,
  AdminDealTask,
  AgentHubSnapshot,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, isoTimeAgo } from "@/lib/utils";
import {
  AdminActionRuns,
  AdminDealTasks,
  HubShell,
  RecentSessions,
  TimedTasks,
  adminRunStatusVariant,
  useHubHeader,
  useRealEstateHubData,
} from "@/pages/real-estate-hub/_shared";

type Handoff = NonNullable<AgentHubSnapshot["handoffs"]>["recent"][number];

export function RealEstateTasksPage() {
  const data = useRealEstateHubData();
  const [accessStatus, setAccessStatus] = useState<AccessStatusResponse | null>(null);
  useHubHeader("Tasks", data);

  useEffect(() => {
    let cancelled = false;
    api
      .getAccessStatus()
      .then((status) => {
        if (!cancelled) setAccessStatus(status);
      })
      .catch(() => {
        if (!cancelled) setAccessStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handoffs = data.snapshot?.handoffs;
  const worker = data.snapshot?.agentWorker;
  const adminPackActive = Boolean(accessStatus?.packs.realEstateAdmin);

  const activeSessions = useMemo(
    () => data.sessions.filter((s) => s.is_active),
    [data.sessions],
  );
  const enabledJobs = useMemo(
    () => data.cronJobs.filter((j) => j.enabled),
    [data.cronJobs],
  );
  const openActionRuns = useMemo(
    () =>
      data.actionRuns.filter(
        (r) => !["succeeded", "completed", "skipped", "cancelled"].includes(r.status),
      ),
    [data.actionRuns],
  );
  const waitingHumanHandoffs = useMemo<Handoff[]>(
    () => (handoffs?.recent ?? []).filter((h) => h.status === "waiting_human"),
    [handoffs],
  );
  const pendingDealTasks = useMemo<AdminDealTask[]>(
    () =>
      adminPackActive
        ? data.dealTasks.filter((t) => t.status === "available" || t.status === "waiting_human")
        : [],
    [data.dealTasks, adminPackActive],
  );
  const waitingActionRuns = useMemo(
    () => openActionRuns.filter((r) => r.status === "waiting_human"),
    [openActionRuns],
  );
  const runningActionRuns = useMemo(
    () => openActionRuns.filter((r) => r.status === "running" || r.status === "queued"),
    [openActionRuns],
  );

  const waitingTotal =
    waitingHumanHandoffs.length + pendingDealTasks.length + waitingActionRuns.length;
  const inFlight = (handoffs?.queued ?? 0) + (handoffs?.running ?? 0) + runningActionRuns.length;

  return (
    <HubShell data={data} eyebrow="Operations" icon={CalendarClock} title="Tasks">
      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryTile
          icon={AlertTriangle}
          label="Waiting on you"
          value={waitingTotal}
          tone={waitingTotal > 0 ? "warn" : "neutral"}
        />
        <SummaryTile
          icon={Bot}
          label="In flight"
          value={inFlight}
          tone={inFlight > 0 ? "active" : "neutral"}
        />
        <SummaryTile
          icon={CalendarClock}
          label="Scheduled"
          value={enabledJobs.length}
          tone="neutral"
        />
      </div>

      <ApprovalBoard
        handoffs={waitingHumanHandoffs}
        dealTasks={pendingDealTasks}
        runs={waitingActionRuns}
        adminPackActive={adminPackActive}
        onChanged={data.refresh}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <InFlightCard
          worker={worker}
          handoffs={handoffs}
          runningCount={runningActionRuns.length}
        />
        <RecentSessions
          title="Active sessions"
          sessions={activeSessions}
          empty="No sessions are active."
        />
      </div>

      {adminPackActive && openActionRuns.length > 0 && (
        <AdminActionRuns runs={openActionRuns} onChanged={data.refresh} />
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <TimedTasks jobs={data.cronJobs} title="Scheduled automations" empty="No timed tasks scheduled." />
        <RecentSessions
          title="Recent sessions"
          sessions={data.sessions.filter((s) => !s.is_active).slice(0, 6)}
          empty="No recent sessions."
        />
      </div>

      {adminPackActive && pendingDealTasks.length === 0 && data.dealTasks.length > 0 && (
        <AdminDealTasks tasks={data.dealTasks} onChanged={data.refresh} title="All transaction tasks" />
      )}
    </HubShell>
  );
}

function SummaryTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: number;
  tone: "neutral" | "warn" | "active";
}) {
  const valueClass =
    tone === "warn"
      ? "text-warning"
      : tone === "active"
        ? "text-primary"
        : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}

function ApprovalBoard({
  handoffs,
  dealTasks,
  runs,
  adminPackActive,
  onChanged,
}: {
  handoffs: Handoff[];
  dealTasks: AdminDealTask[];
  runs: ReturnType<typeof useRealEstateHubData>["actionRuns"];
  adminPackActive: boolean;
  onChanged: () => void | Promise<void>;
}) {
  const total = handoffs.length + dealTasks.length + runs.length;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-warning" />
            Waiting on you
          </CardTitle>
          <Badge variant={total ? "warning" : "outline"}>{total}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground/80">
            Nothing waiting on a human — agents will surface items here when they need a decision or input.
          </p>
        ) : (
          <div className="grid gap-3 xl:grid-cols-3">
            <ApprovalColumn label="Handoffs" count={handoffs.length}>
              {handoffs.length === 0 ? (
                <ColumnEmpty>No agent handoffs waiting.</ColumnEmpty>
              ) : (
                handoffs.map((h) => <HandoffRow key={h.id} handoff={h} />)
              )}
            </ApprovalColumn>
            <ApprovalColumn label="Deal tasks" count={dealTasks.length}>
              {!adminPackActive ? (
                <ColumnEmpty>Admin pack not active.</ColumnEmpty>
              ) : dealTasks.length === 0 ? (
                <ColumnEmpty>No transaction tasks need input.</ColumnEmpty>
              ) : (
                dealTasks.slice(0, 8).map((task) => (
                  <DealTaskRow key={task.id} task={task} onChanged={onChanged} />
                ))
              )}
            </ApprovalColumn>
            <ApprovalColumn label="Admin runs" count={runs.length}>
              {runs.length === 0 ? (
                <ColumnEmpty>No admin runs waiting on input.</ColumnEmpty>
              ) : (
                runs.slice(0, 8).map((run) => (
                  <div key={run.id} className="rounded-md border border-border/50 bg-background/40 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-medium text-foreground">
                        {run.registryName || run.skill || "Admin run"}
                      </span>
                      <Badge variant={adminRunStatusVariant(run.status)}>
                        {run.status.replace(/_/g, " ")}
                      </Badge>
                    </div>
                    <div className="mt-1 text-[0.72rem] text-muted-foreground">
                      {isoTimeAgo(run.createdAt)}
                    </div>
                  </div>
                ))
              )}
            </ApprovalColumn>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ApprovalColumn({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-baseline gap-2">
        <h4 className="text-sm font-medium text-foreground">{label}</h4>
        <span className="font-mono-ui text-[0.7rem] tabular-nums text-muted-foreground/80">
          {count}
        </span>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function ColumnEmpty({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-1 py-1 text-xs text-muted-foreground/70">{children}</p>
  );
}

function humanizeAgentId(id: string): string {
  if (!id) return "agent";
  const parts = id.replace(/[_-]+/g, " ").trim().split(/\s+/);
  if (parts.length === 0) return id;
  return parts.map((p, i) => (i === 0 ? p[0].toUpperCase() + p.slice(1) : p)).join(" ");
}

function HandoffRow({ handoff }: { handoff: Handoff }) {
  return (
    <div className="rounded-md border border-border/50 bg-background/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">
            {handoff.title}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.72rem] text-muted-foreground">
            <span>{humanizeAgentId(handoff.fromAgentId)}</span>
            <span>→</span>
            <span>{humanizeAgentId(handoff.toAgentId)}</span>
            <span className="text-muted-foreground/70">{isoTimeAgo(handoff.updatedAt)}</span>
          </div>
        </div>
        <Badge variant="warning">waiting</Badge>
      </div>
    </div>
  );
}

function DealTaskRow({
  task,
  onChanged,
}: {
  task: AdminDealTask;
  onChanged: () => void | Promise<void>;
}) {
  const [running, setRunning] = useState(false);
  const runAi = async () => {
    if (!task.canRunWithAi || !task.skill || running) return;
    setRunning(true);
    try {
      await api.runAdminDealTask({
        dealId: task.dealId,
        skill: task.skill,
        title: task.title,
        sourceTaskId: task.id,
        runNow: true,
      });
      await onChanged();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="rounded-md border border-border/50 bg-background/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-sm font-medium text-foreground">{task.title}</span>
            {task.canRunWithAi && (
              <Badge variant="success" className="gap-1 px-1.5 py-0">
                <Bot className="h-3 w-3" />
                AI
              </Badge>
            )}
          </div>
          <div className="mt-1 truncate text-[0.72rem] text-muted-foreground">
            {task.dealTitle} · {task.side} · {task.stageName || `Stage ${task.currentStage + 1}`}
          </div>
        </div>
        <Badge variant={adminRunStatusVariant(task.status)}>
          {task.status.replace(/_/g, " ")}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap justify-end gap-1.5">
        {task.canRunWithAi && task.skill && task.status === "available" && (
          <Button size="sm" variant="outline" disabled={running} onClick={runAi}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Run AI
          </Button>
        )}
        <Link
          to={`/admin?deal=${encodeURIComponent(task.dealId)}`}
          className={cn(buttonVariants({ size: "sm", variant: "ghost" }))}
        >
          Open deal
        </Link>
      </div>
    </div>
  );
}

function InFlightCard({
  worker,
  handoffs,
  runningCount,
}: {
  worker?: AgentHubSnapshot["agentWorker"];
  handoffs?: AgentHubSnapshot["handoffs"];
  runningCount: number;
}) {
  const loopRunning = worker?.loop?.running ?? false;
  const heartbeat = worker?.heartbeat;
  const wake = worker?.wake;
  const queued = handoffs?.queued ?? 0;
  const running = handoffs?.running ?? 0;
  const total = queued + running + runningCount;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Repeat className="h-4 w-4 text-primary" />
            In flight
          </CardTitle>
          <Badge variant={total > 0 ? "secondary" : "outline"}>{total}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Queued" value={queued} />
          <Stat label="Running" value={running + runningCount} />
          <Stat label="Wakes" value={wake?.count ?? 0} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.72rem] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Dot ok={Boolean(worker?.enabled)} />
            worker {worker?.enabled ? worker?.state : "disabled"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Dot ok={loopRunning} />
            loop {loopRunning ? "on" : "off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Dot ok={Boolean(heartbeat?.enabled)} />
            heartbeat
            {heartbeat?.intervalSeconds ? ` ${heartbeat.intervalSeconds}s` : ""}
          </span>
          {worker?.lastError && (
            <span className="text-warning">{worker.lastError}</span>
          )}
        </div>
        {wake?.lastReason && (
          <p className="truncate text-[0.72rem] text-muted-foreground/80">
            Last wake — {wake.lastReason}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-[0.65rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-1.5 w-1.5 rounded-full ${ok ? "bg-success" : "bg-warning"}`}
    />
  );
}

