import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useState,
  type ComponentType,
} from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  CheckCircle2,
  Clock,
  Database as DatabaseIcon,
  FileCheck2,
  Home,
  Loader2,
  Megaphone,
  MessageSquare,
  Network,
  RefreshCw,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AgentHubMemoryNode,
  AgentHubSnapshot,
  CronJob,
  PaginatedSessions,
  SessionInfo,
  StatusResponse,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MemoryConstellation } from "@/components/MemoryConstellation";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";

type HubData = {
  cronJobs: CronJob[];
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  sessions: SessionInfo[];
  snapshot: AgentHubSnapshot | null;
  status: StatusResponse | null;
};

function useRealEstateHubData(): HubData {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const [hubResult, statusResult, sessionsResult, cronResult] =
      await Promise.allSettled([
        api.getAgentHub(),
        api.getStatus(),
        api.getSessions(36),
        api.getCronJobs(),
      ]);

    if (hubResult.status === "fulfilled") setSnapshot(hubResult.value);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sessionsResult.status === "fulfilled") {
      setSessions((sessionsResult.value as PaginatedSessions).sessions);
    }
    if (cronResult.status === "fulfilled") setCronJobs(cronResult.value);

    const failed = [
      hubResult,
      statusResult,
      sessionsResult,
      cronResult,
    ].find((result) => result.status === "rejected");

    if (failed?.status === "rejected") {
      setError(failed.reason instanceof Error ? failed.reason.message : "Some hub data failed");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    refresh()
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Hub failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  return { cronJobs, error, loading, refresh, sessions, snapshot, status };
}

function useHubHeader(title: string, data: HubData) {
  const { setAfterTitle, setEnd, setTitle } = usePageHeader();
  const gatewayOnline = Boolean(data.snapshot?.gateway.running || data.status?.gateway_running);

  useLayoutEffect(() => {
    setTitle(title);
    setAfterTitle(
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            gatewayOnline ? "bg-success" : "bg-muted-foreground/45",
          )}
        />
        {gatewayOnline ? "Local gateway online" : "Local gateway offline"}
      </span>,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={() => void data.refresh()} disabled={data.loading}>
        <RefreshCw className={cn("h-3.5 w-3.5", data.loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setTitle(null);
      setAfterTitle(null);
      setEnd(null);
    };
  }, [data.loading, data.refresh, gatewayOnline, setAfterTitle, setEnd, setTitle, title]);
}

function sessionMatches(session: SessionInfo, keywords: string[]): boolean {
  const haystack = [
    session.title ?? "",
    session.preview ?? "",
    session.source ?? "",
    session.model ?? "",
  ]
    .join(" ")
    .toLowerCase();
  return keywords.some((keyword) => haystack.includes(keyword));
}

function jobMatches(job: CronJob, keywords: string[]): boolean {
  const haystack = [job.name ?? "", job.prompt, job.schedule_display ?? "", job.deliver ?? ""]
    .join(" ")
    .toLowerCase();
  return keywords.some((keyword) => haystack.includes(keyword));
}

function sessionTitle(session: SessionInfo): string {
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled chat";
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

function LoadingState() {
  return (
    <div className="flex min-h-[42vh] items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-primary" />
    </div>
  );
}

function HubShell({
  children,
  data,
  eyebrow,
  hero,
  icon: Icon,
  title,
}: {
  children: React.ReactNode;
  data: HubData;
  eyebrow: string;
  hero: string;
  icon: ComponentType<{ className?: string }>;
  title: string;
}) {
  if (data.loading && !data.snapshot && !data.status) return <LoadingState />;

  return (
    <div className="real-estate-hub flex flex-col gap-5 pb-6">
      <section className="relative overflow-hidden rounded-[1.6rem] border border-border bg-card/78 p-5 shadow-[0_28px_90px_color-mix(in_srgb,var(--background-base)_58%,transparent)] sm:p-6">
        <div className="pointer-events-none absolute inset-0 opacity-80 [background:radial-gradient(circle_at_18%_0%,color-mix(in_srgb,var(--color-primary)_18%,transparent),transparent_31%),radial-gradient(circle_at_85%_18%,color-mix(in_srgb,var(--color-success)_10%,transparent),transparent_28%)]" />
        <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
                <Icon className="h-4 w-4" />
              </span>
              {eyebrow}
            </div>
            <h1 className="mt-4 max-w-3xl text-3xl font-semibold leading-tight text-foreground sm:text-4xl">
              {title}
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              {hero}
            </p>
            {data.error && (
              <div className="mt-4 rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">
                {data.error}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 self-start">
            <HubMetric
              icon={Activity}
              label="Gateway"
              value={data.snapshot?.gateway.running || data.status?.gateway_running ? "Online" : "Offline"}
            />
            <HubMetric
              icon={Users}
              label="Sessions"
              value={data.snapshot?.sessions.total ?? data.sessions.length}
            />
            <HubMetric
              icon={Brain}
              label="Memory facts"
              value={data.snapshot ? compactNumber(data.snapshot.memory.facts) : "0"}
            />
            <HubMetric
              icon={CalendarClock}
              label="Timed tasks"
              value={data.cronJobs.filter((job) => job.enabled).length}
            />
          </div>
        </div>
      </section>

      {children}
    </div>
  );
}

function HubMetric({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-2xl border border-border/70 bg-background/35 px-3 py-3">
      <div className="flex items-center gap-2 text-[0.72rem] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <div className="mt-1 truncate text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

function platformDisplayName(name: string): string {
  const cleaned = name.replace(/[-_]/g, " ");
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

type BoardAction = {
  detail: string;
  icon: ComponentType<{ className?: string }>;
  id: string;
  meta: string;
  status: string;
  title: string;
  to: string;
  variant?: "success" | "warning" | "outline";
};

function pendingApprovalCount(data: HubData): number {
  const pendingPairings =
    data.snapshot?.platforms.reduce(
      (total, platform) => total + platform.pending_pairings.length,
      0,
    ) ?? 0;
  const waitingRuns =
    data.snapshot?.orchestration?.runs?.filter((run) => {
      if (!run || typeof run !== "object") return false;
      return JSON.stringify(run).toLowerCase().includes("waiting_for_approval");
    }).length ?? 0;
  return pendingPairings + waitingRuns;
}

function sessionAction(
  session: SessionInfo,
  titlePrefix: string,
  icon: ComponentType<{ className?: string }>,
): BoardAction {
  return {
    detail: session.preview?.trim() || `${session.message_count} saved message${session.message_count === 1 ? "" : "s"}.`,
    icon,
    id: `session-${session.id}`,
    meta: `${session.source ?? "local"} / ${timeAgo(session.last_active)}`,
    status: session.is_active ? "active" : "resume",
    title: `${titlePrefix}: ${sessionTitle(session)}`,
    to: `/chat?resume=${encodeURIComponent(session.id)}`,
    variant: session.is_active ? "success" : "outline",
  };
}

function jobAction(
  job: CronJob,
  titlePrefix: string,
  icon: ComponentType<{ className?: string }>,
): BoardAction {
  return {
    detail: job.prompt,
    icon,
    id: `job-${job.id}`,
    meta: job.next_run_at ? `Next ${isoTimeAgo(job.next_run_at)}` : job.schedule_display || job.schedule.display,
    status: job.last_error ? "error" : job.enabled ? "scheduled" : "paused",
    title: `${titlePrefix}: ${job.name || job.prompt.slice(0, 68)}`,
    to: "/cron",
    variant: job.last_error ? "warning" : job.enabled ? "success" : "outline",
  };
}

function approvalActions(data: HubData): BoardAction[] {
  const pairingActions =
    data.snapshot?.platforms.flatMap((platform) =>
      platform.pending_pairings.map((pairing) => ({
        detail: `${pairing.user_name || pairing.user_id} is waiting to pair with ${platformDisplayName(platform.name)}.`,
        icon: ShieldCheck,
        id: `pairing-${platform.name}-${pairing.code}`,
        meta: `${pairing.age_minutes}m old`,
        status: "approve",
        title: `Approve ${platformDisplayName(platform.name)} pairing`,
        to: "/today",
        variant: "warning" as const,
      })),
    ) ?? [];
  const waitingRunCount =
    data.snapshot?.orchestration?.runs?.filter((run) => {
      if (!run || typeof run !== "object") return false;
      return JSON.stringify(run).toLowerCase().includes("waiting_for_approval");
    }).length ?? 0;
  const runAction =
    waitingRunCount > 0
      ? [
          {
            detail: `${waitingRunCount} agent run${waitingRunCount === 1 ? "" : "s"} need a human decision before continuing.`,
            icon: AlertTriangle,
            id: "waiting-runs",
            meta: "agent orchestration",
            status: "review",
            title: "Review waiting agent approvals",
            to: "/today",
            variant: "warning" as const,
          },
        ]
      : [];
  return [...pairingActions, ...runAction];
}

const APPROVAL_CUE_KEYWORDS = ["approval", "approve", "review", "send", "gate"];

function approvalCueCount(sessions: SessionInfo[], jobs: CronJob[]): number {
  return (
    sessions.filter((session) => sessionMatches(session, APPROVAL_CUE_KEYWORDS)).length +
    jobs.filter((job) => jobMatches(job, APPROVAL_CUE_KEYWORDS)).length
  );
}

function approvalCueActions(
  sessions: SessionInfo[],
  jobs: CronJob[],
  lane: string,
): BoardAction[] {
  const sessionCues = sessions
    .filter((session) => sessionMatches(session, APPROVAL_CUE_KEYWORDS))
    .slice(0, 3)
    .map((session) => ({
      ...sessionAction(session, `${lane} approval`, ShieldCheck),
      status: "review",
      variant: "warning" as const,
    }));
  const jobCues = jobs
    .filter((job) => jobMatches(job, APPROVAL_CUE_KEYWORDS))
    .slice(0, 3)
    .map((job) => ({
      ...jobAction(job, `${lane} review`, ShieldCheck),
      status: "review",
      variant: "warning" as const,
    }));
  return [...sessionCues, ...jobCues];
}

function ActionBoard({
  actions,
  empty,
  title,
}: {
  actions: BoardAction[];
  empty: string;
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant={actions.length ? "warning" : "success"}>{actions.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {actions.length ? (
          actions.slice(0, 8).map((action) => {
            const Icon = action.icon;
            return (
              <div
                key={action.id}
                className="flex items-start gap-3 rounded-2xl border border-border/55 bg-background/35 px-3 py-3"
              >
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/20">
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                      {action.title}
                    </div>
                    <Badge variant={action.variant ?? "outline"}>{action.status}</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                    {action.detail}
                  </p>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <span className="truncate text-[0.72rem] text-muted-foreground">{action.meta}</span>
                    <Link
                      className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-7 px-2.5")}
                      to={action.to}
                    >
                      Open
                    </Link>
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-8 text-sm text-muted-foreground">
            {empty}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MemoryGraphView({
  nodes,
  edges,
}: {
  nodes: AgentHubMemoryNode[];
  edges: { source: string; target: string; type: string }[];
}) {
  return (
    <MemoryConstellation
      className="min-h-[38rem]"
      edges={edges}
      nodes={nodes}
    />
  );
}

function RecentSessions({
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
      <CardContent className="space-y-2">
        {sessions.length ? (
          sessions.slice(0, 6).map((session) => (
            <div
              key={session.id}
              className="flex items-center gap-3 rounded-2xl border border-border/55 bg-background/35 px-3 py-2.5"
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
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-6 text-sm text-muted-foreground">
            {empty}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TimedTasks({
  empty = "No timed tasks match this area yet.",
  jobs,
  title = "Timed tasks",
}: {
  empty?: string;
  jobs: CronJob[];
  title?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">{jobs.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {jobs.length ? (
          jobs.slice(0, 6).map((job) => (
            <div
              key={job.id}
              className="grid gap-2 rounded-2xl border border-border/55 bg-background/35 px-3 py-2.5"
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
                <Badge variant={job.enabled ? "success" : "warning"}>{job.state}</Badge>
              </div>
              <div className="flex flex-wrap gap-2 text-[0.72rem] text-muted-foreground">
                <span>{job.deliver ?? "local"}</span>
                {job.next_run_at && <span>Next {isoTimeAgo(job.next_run_at)}</span>}
                {job.last_error && <span className="text-destructive">Error</span>}
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-6 text-sm text-muted-foreground">
            {empty}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function WorkflowStrip({
  items,
}: {
  items: Array<{ icon: ComponentType<{ className?: string }>; label: string; value: string | number }>;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <HubMetric key={item.label} icon={item.icon} label={item.label} value={item.value} />
      ))}
    </div>
  );
}

export function RealEstateTodayPage() {
  const data = useRealEstateHubData();
  useHubHeader("Today", data);

  const liveSessions = data.sessions.filter((session) => session.is_active);
  const enabledAgents = data.snapshot?.agents.filter((agent) => agent.enabled) ?? [];
  const enabledJobs = data.cronJobs.filter((job) => job.enabled);
  const todayActions = [
    ...approvalActions(data),
    ...liveSessions.slice(0, 3).map((session) => sessionAction(session, "Continue", MessageSquare)),
    ...enabledJobs.slice(0, 4).map((job) => jobAction(job, "Scheduled", CalendarClock)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Real Estate Command Center"
      hero="A local-first operating board for lead priority, admin/document work, social pulse, approvals, and the agent team. Ads stays visible as a later lane."
      icon={Home}
      title="Elevate Agent is ready to run from one real-estate hub."
    >
      <WorkflowStrip
        items={[
          { icon: Bot, label: "Agent team", value: enabledAgents.length },
          { icon: MessageSquare, label: "Live sessions", value: liveSessions.length },
          { icon: Clock, label: "Running tasks", value: enabledJobs.length },
          {
            icon: ShieldCheck,
            label: "Today approvals",
            value: pendingApprovalCount(data),
          },
        ]}
      />
      <ActionBoard
        actions={todayActions}
        empty="Nothing urgent is waiting. Start a chat, schedule a pulse, or continue a recent session when work comes in."
        title="Today's action board"
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <RecentSessions
          title="Recent operator activity"
          sessions={data.sessions}
          empty="No local sessions have been recorded yet."
        />
        <TimedTasks jobs={enabledJobs} empty="No enabled timed tasks yet." />
      </div>
    </HubShell>
  );
}

export function RealEstateLeadsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Leads", data);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ["lead", "outreach", "buyer", "seller", "follow-up", "follow up"]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["lead", "outreach", "follow-up", "follow up", "buyer", "seller"]),
  );
  const activeSessions = sessions.filter((session) => session.is_active);
  const actions = [
    ...approvalCueActions(sessions, jobs, "Lead"),
    ...jobs
      .filter((job) => !jobMatches(job, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((job) => jobAction(job, "Follow up", CalendarClock)),
    ...sessions
      .filter((session) => !sessionMatches(session, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((session) => sessionAction(session, "Lead thread", MessageSquare)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Lead Desk"
      hero="A sales board for who needs a reply, which conversations should be resumed, what follow-ups are scheduled, and what outreach needs approval."
      icon={Users}
      title="Leads shows the next sales moves."
    >
      <WorkflowStrip
        items={[
          {
            icon: MessageSquare,
            label: "Lead chats",
            value: sessions.length,
          },
          { icon: CalendarClock, label: "Follow-up tasks", value: jobs.length },
          {
            icon: Target,
            label: "Active threads",
            value: activeSessions.length,
          },
          {
            icon: CheckCircle2,
            label: "Review gates",
            value: approvalCueCount(sessions, jobs),
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Lead action board"
          empty="No lead actions are waiting yet. When outreach sessions, follow-up schedules, or approvals exist, they will show up here."
        />
        <TimedTasks jobs={jobs} empty="No lead follow-up schedules yet." title="Lead follow-ups" />
      </div>
      <RecentSessions
        title="Lead conversations"
        sessions={sessions}
        empty="No lead-specific sessions found yet. Telegram, chat, and outreach runs will appear here when they include lead context."
      />
    </HubShell>
  );
}

export function RealEstateAdminPage() {
  const data = useRealEstateHubData();
  useHubHeader("Admin", data);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, [
      "admin",
      "listing",
      "deal",
      "transaction",
      "cma",
      "seller update",
      "showing",
      "weekly",
      "relisting",
      "mlc",
      "digisign",
      "webforms",
      "contract",
      "paperwork",
      "document",
      "skyslope",
    ]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, [
      "admin",
      "listing",
      "deal",
      "transaction",
      "seller update",
      "showing",
      "weekly",
      "relisting",
      "mlc",
      "digisign",
      "webforms",
      "contract",
      "paperwork",
      "document",
      "skyslope",
    ]),
  );
  const activeSessions = sessions.filter((session) => session.is_active);
  const actions = [
    ...approvalCueActions(sessions, jobs, "Admin"),
    ...jobs
      .filter((job) => !jobMatches(job, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((job) => jobAction(job, "Admin check", CalendarClock)),
    ...sessions
      .filter((session) => !sessionMatches(session, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((session) => sessionAction(session, "Admin workflow", FileCheck2)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Admin Desk"
      hero="An admin board for listings, deals, CMA work, seller updates, forms, signatures, brokerage checklists, and nightly follow-through."
      icon={BriefcaseBusiness}
      title="Admin shows the next listing and deal moves."
    >
      <WorkflowStrip
        items={[
          {
            icon: Building2,
            label: "Admin sessions",
            value: sessions.length,
          },
          { icon: CalendarClock, label: "Nightly checks", value: jobs.length },
          {
            icon: FileCheck2,
            label: "Active workflows",
            value: activeSessions.length,
          },
          {
            icon: CheckCircle2,
            label: "Review gates",
            value: approvalCueCount(sessions, jobs),
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Admin action board"
          empty="No admin actions are waiting yet. CMA, seller-update, MLC, signing, and listing/deal sessions will appear here."
        />
        <TimedTasks jobs={jobs} empty="No admin/document schedules yet." title="Admin automations" />
      </div>
      <RecentSessions
        title="Admin work"
        sessions={sessions}
        empty="No admin-specific sessions found yet. CMA, seller updates, MLC, DigiSign, WebForms, and listing/deal cron work will land here."
      />
    </HubShell>
  );
}

export function RealEstateAdsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Ads", data);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ["ads", "paid", "campaign", "email", "copy", "mailjet", "listing ad", "audience"]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["ads", "paid", "campaign", "email", "mailjet", "market stats", "listing ad"]),
  );
  const activeSessions = sessions.filter((session) => session.is_active);
  const actions = [
    ...approvalCueActions(sessions, jobs, "Ads"),
    ...jobs
      .filter((job) => !jobMatches(job, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((job) => jobAction(job, "Campaign check", CalendarClock)),
    ...sessions
      .filter((session) => !sessionMatches(session, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((session) => sessionAction(session, "Ads work", Target)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Ads Studio"
      hero="A lightweight paid-media board for campaign checks, launch prep, creative review, and approvals. Full ad account views can come later."
      icon={Target}
      title="Ads shows paid-media work waiting on the operator."
    >
      <WorkflowStrip
        items={[
          {
            icon: Target,
            label: "Ad sessions",
            value: sessions.length,
          },
          { icon: CalendarClock, label: "Campaign schedules", value: jobs.length },
          {
            icon: Activity,
            label: "Active work",
            value: activeSessions.length,
          },
          {
            icon: Megaphone,
            label: "Review gates",
            value: approvalCueCount(sessions, jobs),
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Ads action board"
          empty="No paid-media actions are waiting yet. Campaign schedules and ad sessions will appear here."
        />
        <TimedTasks jobs={jobs} empty="No ad schedules yet." title="Campaign schedules" />
      </div>
      <RecentSessions
        title="Ad work"
        sessions={sessions}
        empty="No ad-specific sessions found yet."
      />
    </HubShell>
  );
}

export function RealEstateSocialMediaPage() {
  const data = useRealEstateHubData();
  useHubHeader("Social Media", data);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ["social", "caption", "hook", "post", "reel", "instagram", "facebook", "buffer"]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["social", "caption", "hook", "post", "reel", "instagram", "facebook", "buffer"]),
  );
  const activeSessions = sessions.filter((session) => session.is_active);
  const actions = [
    ...approvalCueActions(sessions, jobs, "Social"),
    ...jobs
      .filter((job) => !jobMatches(job, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((job) => jobAction(job, "Social pulse", CalendarClock)),
    ...sessions
      .filter((session) => !sessionMatches(session, APPROVAL_CUE_KEYWORDS))
      .slice(0, 5)
      .map((session) => sessionAction(session, "Content work", Megaphone)),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Social Studio"
      hero="A content board for best-post reviews, last-30-day pulse checks, hooks, captions, approvals, and scheduled social follow-through."
      icon={Megaphone}
      title="Social Media shows the next content moves."
    >
      <WorkflowStrip
        items={[
          {
            icon: Megaphone,
            label: "Social sessions",
            value: sessions.length,
          },
          { icon: CalendarClock, label: "Post schedules", value: jobs.length },
          {
            icon: Activity,
            label: "Active work",
            value: activeSessions.length,
          },
          {
            icon: MessageSquare,
            label: "Review gates",
            value: approvalCueCount(sessions, jobs),
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Social action board"
          empty="No social actions are waiting yet. Pulse schedules, caption work, and content approvals will appear here."
        />
        <TimedTasks jobs={jobs} empty="No social schedules yet." title="Post schedules" />
      </div>
      <RecentSessions
        title="Social work"
        sessions={sessions}
        empty="No social-media sessions found yet."
      />
    </HubShell>
  );
}

export function RealEstateTasksPage() {
  const data = useRealEstateHubData();
  useHubHeader("Tasks", data);
  const activeSessions = data.sessions.filter((session) => session.is_active);
  const enabledJobs = data.cronJobs.filter((job) => job.enabled);
  const erroredJobs = data.cronJobs.filter((job) => job.last_error);

  return (
    <HubShell
      data={data}
      eyebrow="Task Board"
      hero="A practical view of what the local agent is running now, what is scheduled, and where attention is needed."
      icon={CalendarClock}
      title="Tasks, automations, and active sessions in one place."
    >
      <WorkflowStrip
        items={[
          { icon: Activity, label: "Active sessions", value: activeSessions.length },
          { icon: CalendarClock, label: "Enabled tasks", value: enabledJobs.length },
          { icon: Clock, label: "Paused tasks", value: data.cronJobs.filter((job) => !job.enabled).length },
          { icon: FileCheck2, label: "Task errors", value: erroredJobs.length },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <TimedTasks jobs={data.cronJobs} empty="No timed tasks have been created yet." title="All timed tasks" />
        <RecentSessions
          title="Active sessions"
          sessions={activeSessions}
          empty="No sessions are active right now."
        />
      </div>
    </HubShell>
  );
}

export function RealEstateMemoryPage() {
  const data = useRealEstateHubData();
  useHubHeader("Memory", data);
  const memory = data.snapshot?.memory;

  return (
    <HubShell
      data={data}
      eyebrow="Memory Graph"
      hero="A workable knowledge view for local facts, entities, session segments, embeddings, and the graph-style memory layer."
      icon={Brain}
      title="Memory should feel inspectable, not invisible."
    >
      <WorkflowStrip
        items={[
          { icon: Brain, label: "Facts", value: memory?.facts ?? 0 },
          { icon: Network, label: "Entities", value: memory?.entities ?? 0 },
          { icon: DatabaseIcon, label: "Embeddings", value: memory?.embeddings ?? 0 },
          { icon: CalendarClock, label: "Session segments", value: memory?.journal.session_segment_count ?? 0 },
        ]}
      />
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card className="bg-[#1e1e1d] p-0">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle>Knowledge graph</CardTitle>
              <Badge variant={memory?.embedding.enabled ? "success" : "outline"}>
                {memory?.embedding.enabled ? "Embeddings on" : "Embeddings off"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <MemoryGraphView
              nodes={memory?.graph.nodes ?? []}
              edges={memory?.graph.edges ?? []}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Memory pipeline</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <HubMetric icon={Clock} label="Pending" value={memory?.journal.pending ?? 0} />
              <HubMetric icon={CheckCircle2} label="Processed" value={memory?.journal.processed ?? 0} />
              <HubMetric icon={AlertTriangle} label="Failed" value={memory?.journal.failed ?? 0} />
              <HubMetric icon={MessageSquare} label="Active sessions" value={memory?.journal.active_session_count ?? 0} />
            </div>
            <div className="rounded-2xl border border-border/55 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
              <div className="font-semibold text-foreground">
                {memory?.provider ?? "memory"} / {memory?.embedding.provider ?? "embedding provider"}
              </div>
              <div className="mt-1 truncate">{memory?.db_path ?? "No memory database path yet."}</div>
              <div className="mt-2">
                {memory?.embedding.model
                  ? `${memory.embedding.model} using ${memory.embedding.api_key_env || "local config"}`
                  : "Embedding model not configured."}
              </div>
            </div>
            <div className="space-y-2">
              {(memory?.journal.sessions ?? []).slice(0, 6).map((session) => (
                <div
                  key={`${session.session_id}-${session.session_day}`}
                  className="rounded-2xl border border-border/55 bg-background/35 px-3 py-2 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium text-foreground">{session.session_day}</span>
                    <Badge variant="outline">{session.total}</Badge>
                  </div>
                  <div className="mt-1 truncate text-muted-foreground">{session.session_id}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </HubShell>
  );
}
