import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Check,
  Clock,
  Loader2,
  MessageSquare,
  Play,
  Repeat,
  XCircle,
  Zap,
} from "lucide-react";
import {
  api,
  type AdminActionRun,
  type AdminDealTask,
  type AgentHubSnapshot,
  type CronJob,
  type SessionInfo,
} from "@/lib/api";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HubMetric } from "./hub-metric";

type AdminRunTone = "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
export type AdminRunBusy = { id: string; action: "approve" | "cancel" } | null;

export function sessionTitle(session: SessionInfo): string {
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled chat";
}

export function adminRunStatusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" | "success" | "warning" {
  if (status === "succeeded" || status === "completed") return "success";
  if (status === "failed" || status === "cancelled") return "destructive";
  if (status === "waiting_human" || status === "waiting_external") return "warning";
  if (status === "running" || status === "queued") return "secondary";
  return "outline";
}

function adminRunRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function adminRunText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function adminRunList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim()) return [item.trim()];
    const record = adminRunRecord(item);
    const label =
      adminRunText(record.label) ||
      adminRunText(record.name) ||
      adminRunText(record.key) ||
      adminRunText(record.field);
    return label ? [label] : [];
  });
}

function adminRunPrompt(run: AdminActionRun): Record<string, unknown> {
  const direct = adminRunRecord(run.humanPrompt);
  if (Object.keys(direct).length > 0) return direct;
  const resultPrompt = adminRunRecord(adminRunRecord(run.result).humanPrompt);
  return resultPrompt;
}

function adminRunTitle(run: AdminActionRun): string {
  const prompt = adminRunPrompt(run);
  return (
    adminRunText(prompt.title) ||
    adminRunText(prompt.question) ||
    adminRunText(prompt.summary) ||
    run.registryName ||
    run.skill ||
    "Admin run"
  );
}

function adminRunMessage(run: AdminActionRun): string {
  const prompt = adminRunPrompt(run);
  return (
    adminRunText(prompt.message) ||
    adminRunText(prompt.body) ||
    adminRunText(prompt.prompt) ||
    adminRunText(prompt.decisionNeeded) ||
    adminRunText(prompt.reason)
  );
}

function adminRunRequiredFields(run: AdminActionRun): string[] {
  const prompt = adminRunPrompt(run);
  const fields = [
    ...adminRunList(prompt.requiredFields),
    ...adminRunList(prompt.missingFields),
    ...adminRunList(prompt.inputsNeeded),
    ...adminRunList(prompt.fields),
  ];
  return Array.from(new Set(fields)).slice(0, 10);
}

function adminRunDeliveryInfo(run: AdminActionRun): { label: string; detail: string; variant: AdminRunTone } {
  const delivery = adminRunRecord(adminRunRecord(run.payload).delivery);
  if (Object.keys(delivery).length > 0) {
    const deliver = adminRunText(delivery.deliver) || "local";
    const channel = deliver.startsWith("telegram") ? "Telegram" : "Delivery";
    const attempted = delivery.attempted === true;
    const ok = delivery.ok === true;
    const error = adminRunText(delivery.error);
    const suppressed = adminRunText(delivery.suppressedReason);
    if (ok) {
      return { label: `${channel} notified`, detail: deliver, variant: "success" };
    }
    if (attempted && error) {
      return { label: `${channel} failed`, detail: error, variant: "destructive" };
    }
    if (suppressed) {
      return { label: `${channel} skipped`, detail: suppressed.replace(/_/g, " "), variant: "outline" };
    }
    return { label: `${channel} not sent`, detail: deliver, variant: "warning" };
  }
  if (run.cronJobId) {
    return {
      label: "Telegram pending",
      detail: "Cron will record delivery after the Admin response.",
      variant: "outline",
    };
  }
  return {
    label: "UI queue only",
    detail: "No cron delivery is attached to this run yet.",
    variant: "outline",
  };
}

function handoffStatusVariant(status: string): "success" | "warning" | "outline" | "secondary" | "destructive" {
  if (status === "completed" || status === "succeeded") return "success";
  if (status === "failed") return "destructive";
  if (status === "waiting_human") return "warning";
  if (status === "queued" || status === "running") return "warning";
  return "outline";
}

export function RecentSessions({
  empty,
  sessions,
  title,
}: {
  empty: string;
  sessions: SessionInfo[];
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">{sessions.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {sessions.length ? (
          sessions.slice(0, 6).map((session) => (
            <div
              key={session.id}
              className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
            >
              <span
                className={cn(
                  "h-2.5 w-2.5 shrink-0 rounded-full",
                  session.is_active ? "bg-success" : "bg-muted-foreground/40",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground">
                  {sessionTitle(session)}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                  <span>{session.source ?? "local"}</span>
                  <span>{timeAgo(session.last_active)}</span>
                  <span>{session.message_count} messages</span>
                </div>
              </div>
              <Badge variant="outline">{session.tool_call_count} tools</Badge>
            </div>
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function TimedTasks({
  empty = "No timed tasks match this area yet.",
  jobs,
  title = "Timed tasks",
}: {
  empty?: string;
  jobs: CronJob[];
  title?: string;
}) {
  const automationBadge = (job: CronJob) => {
    if (job.last_error) return { label: "error", variant: "warning" as const };
    if (job.alignment_status === "blocked") return { label: "blocked", variant: "warning" as const };
    if (job.alignment_status === "optional") return { label: "optional", variant: "outline" as const };
    if (job.alignment_status === "legacy") return { label: "legacy", variant: "warning" as const };
    if (job.enabled) return { label: job.state || "scheduled", variant: "success" as const };
    return { label: job.state || "paused", variant: "outline" as const };
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">{jobs.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {jobs.length ? (
          jobs.slice(0, 6).map((job) => (
            <div
              key={job.id}
              className="grid gap-1.5 py-3 first:pt-0 last:pb-0"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-foreground">
                    {job.name || job.prompt.slice(0, 70)}
                  </div>
                  <div className="mt-0.5 text-[0.72rem] text-muted-foreground">
                    {job.schedule_display || job.schedule.display}
                  </div>
                </div>
                {(() => {
                  const badge = automationBadge(job);
                  return <Badge variant={badge.variant}>{badge.label}</Badge>;
                })()}
              </div>
              <div className="flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                <span>{job.deliver ?? "local"}</span>
                {job.next_run_at && <span>Next {isoTimeAgo(job.next_run_at)}</span>}
                {!job.enabled && !job.next_run_at && <span>Paused</span>}
                {job.last_error && <span className="text-destructive">Error</span>}
              </div>
              {(job.paused_reason || job.alignment_reason || job.last_error) && (
                <p className="line-clamp-2 text-[0.72rem] leading-5 text-muted-foreground">
                  {job.paused_reason || job.alignment_reason || job.last_error}
                </p>
              )}
            </div>
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AdminDealTasks({
  empty = "No transaction tasks need attention.",
  onChanged,
  tasks,
  title = "Transaction tasks",
}: {
  empty?: string;
  onChanged?: () => Promise<void> | void;
  tasks: AdminDealTask[];
  title?: string;
}) {
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const runTask = async (task: AdminDealTask) => {
    if (!task.canRunWithAi || !task.skill || runningTaskId) return;
    setRunningTaskId(task.id);
    try {
      await api.runAdminDealTask({
        dealId: task.dealId,
        skill: task.skill,
        title: task.title,
        sourceTaskId: task.id,
        runNow: true,
      });
      await onChanged?.();
    } finally {
      setRunningTaskId(null);
    }
  };
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant={tasks.length ? "warning" : "outline"}>{tasks.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/40">
        {tasks.length ? (
          tasks.slice(0, 10).map((task) => (
            <div key={task.id} className="grid gap-2 py-3 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-foreground">{task.title}</span>
                    {task.canRunWithAi && (
                      <Badge variant="success" className="gap-1">
                        <Bot className="h-3 w-3" />
                        AI
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                    <span>{task.dealTitle}</span>
                    <span>{task.side}</span>
                    <span>{task.stageName || `Stage ${task.currentStage + 1}`}</span>
                    {task.skill && <span>{task.skill}</span>}
                  </div>
                </div>
                <Badge variant={adminRunStatusVariant(task.status)}>{task.status.replace(/_/g, " ")}</Badge>
              </div>
              {task.description && (
                <div className="text-[0.76rem] leading-5 text-muted-foreground">{task.description}</div>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                {task.canRunWithAi && task.skill && task.status === "available" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={runningTaskId !== null}
                    onClick={() => void runTask(task)}
                  >
                    {runningTaskId === task.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    Run AI
                  </Button>
                )}
                <Link
                  to="/admin"
                  className="inline-flex h-9 items-center rounded-md px-2 font-mono-ui text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-primary hover:text-primary/80"
                >
                  Open deal
                </Link>
              </div>
            </div>
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AdminActionRuns({
  empty = "No Admin action runs yet.",
  onChanged,
  runs,
  title = "Admin action runs",
}: {
  empty?: string;
  onChanged?: () => Promise<void> | void;
  runs: AdminActionRun[];
  title?: string;
}) {
  const [busyRun, setBusyRun] = useState<AdminRunBusy>(null);
  const resolveRun = async (run: AdminActionRun, approved: boolean) => {
    if (busyRun || run.status !== "waiting_human") return;
    setBusyRun({ id: run.id, action: approved ? "approve" : "cancel" });
    try {
      await api.approveAdminActionRun(run.id, { approved, runNow: approved });
      await onChanged?.();
    } finally {
      setBusyRun(null);
    }
  };
  const visibleRuns = [...runs]
    .sort((a, b) => {
      if (a.status === "waiting_human" && b.status !== "waiting_human") return -1;
      if (a.status !== "waiting_human" && b.status === "waiting_human") return 1;
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    })
    .slice(0, 12);
  const waitingCount = runs.filter((run) => run.status === "waiting_human").length;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>{title}</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Human-gated Admin work that needs a decision before the pipeline can move.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {waitingCount > 0 && <Badge variant="warning">{waitingCount} waiting</Badge>}
            <Badge variant={runs.some((run) => ["failed", "waiting_human"].includes(run.status)) ? "warning" : "outline"}>
              {runs.length}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2">
        {visibleRuns.length ? (
          visibleRuns.map((run) => (
            <AdminRunDecisionRow
              key={run.id}
              busyRun={busyRun}
              run={run}
              onApprove={() => void resolveRun(run, true)}
              onCancel={() => void resolveRun(run, false)}
            />
          ))
        ) : (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function AgentHandoffsCard({
  handoffs,
}: {
  handoffs?: AgentHubSnapshot["handoffs"];
}) {
  const recent = handoffs?.recent ?? [];
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Agent handoffs</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Cross-agent work moving through the local orchestration bus.
            </p>
          </div>
          <Badge variant={(handoffs?.open ?? 0) > 0 ? "warning" : "outline"}>
            {handoffs?.open ?? 0} open
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-2">
          <HubMetric icon={Clock} label="Queued" value={handoffs?.queued ?? 0} />
          <HubMetric icon={Bot} label="Running" value={handoffs?.running ?? 0} />
          <HubMetric icon={AlertTriangle} label="Human" value={handoffs?.waitingHuman ?? 0} />
        </div>
        <div className="divide-y divide-border/40">
          {recent.length ? (
            recent.slice(0, 6).map((handoff) => (
              <div key={handoff.id} className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">
                      {handoff.title}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                      <span>{handoff.fromAgentId}</span>
                      <span>to</span>
                      <span>{handoff.toAgentId}</span>
                      <span>{isoTimeAgo(handoff.updatedAt)}</span>
                    </div>
                  </div>
                  <Badge variant={handoffStatusVariant(String(handoff.status))}>
                    {String(handoff.status).replace(/_/g, " ")}
                  </Badge>
                </div>
              </div>
            ))
          ) : (
            <p className="px-1 py-1 text-xs text-muted-foreground/80">No handoffs yet.</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function AgentWorkerCard({
  memory,
  worker,
}: {
  memory?: AgentHubSnapshot["memory"];
  worker?: AgentHubSnapshot["agentWorker"];
}) {
  const heartbeat = worker?.heartbeat;
  const wake = worker?.wake;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>Wake loop</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              The local worker that drains handoffs, heartbeats, and queued agent work.
            </p>
          </div>
          <Badge variant={worker?.enabled ? "success" : "outline"}>
            {worker?.state ?? "unknown"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <HubMetric icon={Repeat} label="Handoffs drained" value={worker?.drained.handoffs ?? 0} />
          <HubMetric icon={Activity} label="Admin runs" value={worker?.drained.adminRuns ?? 0} />
          <HubMetric icon={Brain} label="Memory queue" value={memory?.journal.pending ?? 0} />
          <HubMetric icon={Zap} label="Wake count" value={wake?.count ?? 0} />
        </div>
        <div className="rounded-md border border-border/55 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
          <div className="font-semibold text-foreground">
            {worker?.loop?.running ? "Loop running" : "Loop idle"}
          </div>
          <div className="mt-1">
            Heartbeat {heartbeat?.enabled ? "enabled" : "disabled"}
            {heartbeat?.nextBeatAt ? ` - next ${isoTimeAgo(heartbeat.nextBeatAt)}` : ""}
          </div>
          <div className="mt-1">
            Wake {wake?.pending ? "pending" : "clear"}
            {wake?.lastReason ? ` - ${wake.lastReason}` : ""}
          </div>
          {worker?.lastError && <div className="mt-2 text-destructive">{worker.lastError}</div>}
        </div>
      </CardContent>
    </Card>
  );
}

export function AdminRunDecisionRow({
  busyRun,
  compact = false,
  onApprove,
  onCancel,
  run,
}: {
  busyRun: AdminRunBusy;
  compact?: boolean;
  onApprove: () => void;
  onCancel: () => void;
  run: AdminActionRun;
}) {
  const waiting = run.status === "waiting_human";
  const message = adminRunMessage(run);
  const requiredFields = adminRunRequiredFields(run);
  const delivery = adminRunDeliveryInfo(run);
  const busyAction = busyRun?.id === run.id ? busyRun.action : null;
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        waiting ? "border-warning/35 bg-warning/10" : "border-border/45 bg-background/30",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium leading-5 text-foreground">{adminRunTitle(run)}</div>
          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[0.72rem] text-muted-foreground">
            <span>{run.skill ?? "admin"}</span>
            <span>Deal {run.dealId.slice(0, 8)}</span>
            {run.cronJobId && <span>Cron {run.cronJobId.slice(0, 8)}</span>}
            <span>{isoTimeAgo(run.updatedAt)}</span>
          </div>
        </div>
        <Badge variant={adminRunStatusVariant(run.status)}>{run.status.replace(/_/g, " ")}</Badge>
      </div>

      {message && (
        <p className={cn("mt-2 text-[0.78rem] leading-5 text-foreground/85", !waiting && "line-clamp-3")}>
          {message}
        </p>
      )}

      {requiredFields.length > 0 && waiting && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {requiredFields.map((field) => (
            <span
              key={field}
              className="inline-flex max-w-full items-center rounded-full border border-warning/25 bg-background/40 px-2 py-0.5 text-[0.68rem] text-warning"
            >
              <span className="truncate">{field}</span>
            </span>
          ))}
        </div>
      )}

      {run.errorMessage && (
        <div className="mt-2 rounded-md border border-destructive/25 bg-destructive/10 px-2 py-1.5 text-[0.72rem] leading-5 text-destructive">
          {run.errorMessage}
        </div>
      )}

      <div className={cn("mt-2 flex flex-wrap items-center justify-between gap-2", compact && "items-start")}>
        <div className="flex min-w-0 items-center gap-1.5 text-[0.72rem] text-muted-foreground" title={delivery.detail}>
          <MessageSquare className="h-3.5 w-3.5 shrink-0" />
          <Badge variant={delivery.variant}>{delivery.label}</Badge>
          {!compact && <span className="min-w-0 truncate">{delivery.detail}</span>}
        </div>
        {waiting && (
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            <Button size="sm" variant="outline" disabled={busyRun !== null} onClick={onCancel}>
              {busyAction === "cancel" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              Needs revision
            </Button>
            <Button size="sm" disabled={busyRun !== null} onClick={onApprove}>
              {busyAction === "approve" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Approve and run
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
