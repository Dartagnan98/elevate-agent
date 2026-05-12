import {
  createElement,
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  AlertTriangle,
  BookText,
  Bot,
  Brain,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  Check,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  Clock,
  Database as DatabaseIcon,
  ExternalLink,
  FileCheck2,
  FileText,
  Flame,
  Filter,
  GitBranch,
  Home,
  Inbox,
  Loader2,
  HelpCircle,
  Mail,
  Megaphone,
  MessageSquare,
  Phone,
  Square as SquareIcon,
  Timer,
  Share2,
  Smartphone,
  Network,
  Pause,
  PencilLine,
  Play,
  Plug,
  Plus,
  Radar,
  RefreshCw,
  Repeat,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  TrendingDown,
  Award,
  ThumbsUp,
  ThumbsDown,
  Users,
  XCircle,
  Zap,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AdminActionRun,
  AdminContact,
  AdminDeal,
  AdminDealCreateRequest,
  AdminDealSide,
  AdminDealTask,
  AdminProvinceGuideCoverage,
  AdminSetupSnapshot,
  AccessStatusResponse,
  DealAttachmentCreateRequest,
  DealContactCreateRequest,
  DealContext,
  AgentHubMemoryNode,
  AgentHubSnapshot,
  BuyerWatchlistEntry,
  ComposioConnectedAccount,
  ComposioStatus,
  CronJob,
  OutreachLane,
  OutreachLaneOverview,
  OutreachOverview,
  OutreachTemplate,
  PaginatedSessions,
  SessionInfo,
  SourceConnectorStatus,
  SourceInboxDraft,
  SourceInboxProfile,
  SourceInboxProfileVerifier,
  SourceInboxResponse,
  SourceInboxThread,
  SocialIdea,
  SocialMetricRow,
  SocialSnapshot,
  StatusResponse,
} from "@/lib/api";
import { X as CloseIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { ThreadDrawerProvider, useThreadDrawer } from "@/pages/real-estate-hub/thread-drawer";
import {
  computeResponsePulse,
  contactBuckets,
  formatMinutes,
  heatStyles,
  heatVariant,
  inboundWaitMinutes,
  leadThreadBuckets,
  profileWhen,
  threadWhen,
  type ResponsePulse,
} from "@/pages/real-estate-hub/utils";
import {
  PROFILE_ACTION_BUCKETS,
  PROFILE_ADMIN_SIDE_COPY,
  isActiveProfileThread,
  profileActionBucket,
  profileActionSort,
  profileContactLine,
  profileConversationSort,
  profileHasActiveConversation,
  profileHasVerifier,
  profileHandoffBadgeLabel,
  profileHandoffIsActive,
  profileHandoffSide,
  profilePrimaryContactId,
  profileSkillWorkflowContext,
  profileSkillWorkflowName,
  profileSkillWorkflowPrompt,
  profileSourceMeta,
  profileVerifierSummary,
  profileVerifiers,
  threadSortTime,
  verifierSummary,
  type ProfileActionBucketId,
  type ProfileAdminDealIds,
  type ProfileHandoffIds,
  type ProfilePendingAdminAction,
} from "@/pages/real-estate-hub/profile-workflow";
import {
  adminSetupDraftFromSnapshot,
  adminSetupPayloadFromDraft,
  type AdminSetupDraft,
} from "@/pages/real-estate-hub/admin-setup";
import {
  IdeaCard,
  PlatformBlockCard,
  PlatformRankingsBlock,
  PlatformTablist,
  PostDetailModal,
  RealVideoCard,
  YouTubeTabView,
  computeEngagementScore,
  formatCompact,
  formatPct,
} from "@/pages/real-estate-hub/social-media-widgets";

export type HubData = {
  actionRuns: AdminActionRun[];
  cronJobs: CronJob[];
  dealTasks: AdminDealTask[];
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  sourceInbox: SourceInboxResponse | null;
  sessions: SessionInfo[];
  snapshot: AgentHubSnapshot | null;
  status: StatusResponse | null;
};

function useRealEstateHubData(): HubData {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [sourceInbox, setSourceInbox] = useState<SourceInboxResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [dealTasks, setDealTasks] = useState<AdminDealTask[]>([]);
  const [actionRuns, setActionRuns] = useState<AdminActionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const [hubResult, statusResult, sessionsResult, cronResult, sourceInboxResult, dealTasksResult, actionRunsResult] =
      await Promise.allSettled([
        api.getAgentHub(),
        api.getStatus(),
        api.getSessions(36),
        api.getCronJobs(),
        api.getSourceInbox(200),
        api.getAdminDealTasks({ status: "open", limit: 200 }),
        api.getAdminActionRuns({ limit: 200 }),
      ]);

    if (hubResult.status === "fulfilled") setSnapshot(hubResult.value);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sessionsResult.status === "fulfilled") {
      setSessions((sessionsResult.value as PaginatedSessions).sessions);
    }
    if (cronResult.status === "fulfilled") setCronJobs(cronResult.value);
    if (sourceInboxResult.status === "fulfilled") {
      setSourceInbox(sourceInboxResult.value);
    } else {
      setSourceInbox(null);
    }
    if (dealTasksResult.status === "fulfilled") {
      setDealTasks(dealTasksResult.value.items);
    } else {
      setDealTasks([]);
    }
    if (actionRunsResult.status === "fulfilled") {
      setActionRuns(actionRunsResult.value.items);
    } else {
      setActionRuns([]);
    }

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

  return { actionRuns, cronJobs, dealTasks, error, loading, refresh, sourceInbox, sessions, snapshot, status };
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
  const haystack = [
    job.name ?? "",
    job.prompt,
    job.schedule_display ?? "",
    job.deliver ?? "",
    job.skill ?? "",
    ...(job.skills ?? []),
  ]
    .join(" ")
    .toLowerCase();
  return keywords.some((keyword) => haystack.includes(keyword));
}

function sessionTitle(session: SessionInfo): string {
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled chat";
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
  icon: Icon,
  title,
}: {
  children: React.ReactNode;
  data: HubData;
  eyebrow: string;
  hero?: string;
  icon: ComponentType<{ className?: string }>;
  title: string;
}) {
  if (data.loading && !data.snapshot && !data.status) return <LoadingState />;

  const gatewayOnline = !!(data.snapshot?.gateway.running || data.status?.gateway_running);
  const activeJobs = data.cronJobs.filter((job) => job.enabled).length;

  return (
    <div className="real-estate-hub flex flex-col gap-4 pb-6">
      <section className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
        <div className="min-w-0 flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.68rem] uppercase tracking-[0.14em] text-muted-foreground font-semibold">
              {eyebrow}
            </div>
            <h1 className="text-xl font-semibold leading-tight text-foreground sm:text-[1.6rem]">
              {title}
            </h1>
          </div>
        </div>
        <div className="font-mono-ui flex items-center gap-2 text-[0.72rem] text-muted-foreground">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1",
              gatewayOnline
                ? "border-success/45 bg-success/10 text-success"
                : "border-destructive/45 bg-destructive/10 text-destructive",
            )}
          >
            <span
              className={cn("h-1.5 w-1.5 rounded-full", gatewayOnline ? "bg-success" : "bg-destructive")}
            />
            Agent {gatewayOnline ? "online" : "offline"}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1">
            <Timer className="h-3 w-3" />
            {activeJobs} job{activeJobs === 1 ? "" : "s"}
          </span>
        </div>
        {data.error && (
          <div className="basis-full rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">
            {data.error}
          </div>
        )}
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
    meta: job.next_run_at ? `Next ${isoTimeAgo(job.next_run_at)}` : job.schedule_display || job.schedule.display || "Scheduled",
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
      <CardContent className="divide-y divide-border/40">
        {actions.length ? (
          actions.slice(0, 8).map((action) => {
            const Icon = action.icon;
            return (
              <div
                key={action.id}
                className="flex items-start gap-3 py-3 first:pt-0 last:pb-0"
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
          <div className="py-10 text-sm text-muted-foreground">
            {empty}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function sourceRecordCount(data: HubData, key: string): number {
  return Number(data.sourceInbox?.recordCounts?.[key] ?? 0);
}

function ClientInboxPreview({
  data,
  title = "Lead inbox",
}: {
  data: HubData;
  title?: string;
}) {
  const threads = data.sourceInbox?.threads ?? [];
  const sources = data.sourceInbox?.sources ?? [];
  const connected = sources.filter((source) => source.connected || source.importOnly);
  const blocked = sources.filter((source) => source.blocked);
  const messageCount = sourceRecordCount(data, "messages");
  const conversationCount = sourceRecordCount(data, "conversations");
  const hotCount = sourceRecordCount(data, "hotThreads");

  const updateThread = async (thread: SourceInboxThread, action: "done" | "archive") => {
    await api.updateSourceInboxThread(thread.sourceId, thread.threadId, action);
    await data.refresh();
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>{title}</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Source-aware conversations from Messages, Lofty CRM, email, SMS, and future lead channels.
            </p>
          </div>
          <Badge variant={threads.length ? "success" : blocked.length ? "warning" : "outline"}>
            {threads.length ? "actionable" : blocked.length ? "needs access" : "empty"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-2">
          <HubMetric icon={MessageSquare} label="Messages" value={messageCount} />
          <HubMetric icon={Users} label="Threads" value={conversationCount} />
          <HubMetric icon={Target} label="Hot" value={hotCount} />
        </div>
        {threads.length ? (
          <div className="space-y-2">
            {threads.slice(0, 7).map((thread, index) => {
              const inbound = thread.direction !== "outbound";
              return (
                <div
                  key={thread.id || `${thread.sourceId}-${thread.threadId}-${index}`}
                  className="rounded-2xl border border-border/55 bg-background/35 px-3 py-3"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        inbound ? "bg-success" : "bg-primary",
                      )}
                    />
                    <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                      {thread.personName}
                    </div>
                    <span className="shrink-0 text-[0.72rem] text-muted-foreground">
                      {threadWhen(thread)}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                    {thread.latestText}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge variant={heatVariant(thread)}>{thread.heatLabel} {thread.heatScore}</Badge>
                    <Badge variant="outline">{thread.sourceLabel}</Badge>
                    <Badge variant="outline">{thread.channel}</Badge>
                    <Badge variant="outline">{inbound ? "inbound" : "outbound"}</Badge>
                    <div className="ml-auto flex gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => void updateThread(thread, "done")}>
                        Done
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void updateThread(thread, "archive")}>
                        Remove
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : blocked.length ? (
          <div className="rounded-2xl border border-warning/35 bg-warning/10 px-4 py-4 text-sm text-muted-foreground">
            <div className="font-semibold text-foreground">A lead source needs access before it can show client rows.</div>
            <div className="mt-2 space-y-2">
              {blocked.slice(0, 3).map((source) => (
                <div key={source.id}>
                  <span className="font-medium text-foreground">{source.label}: </span>
                  {source.nextOperatorStep || source.lastError || "Open Settings and reconnect this source."}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-8 text-sm text-muted-foreground">
            No client-source rows are visible yet. Import Messages or sync Lofty CRM, then refresh this board.
          </div>
        )}
        {connected.length > 0 && (
          <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
            {connected.slice(0, 4).map((source) => (
              <Badge key={source.id} variant="outline">
                {source.label} {source.importOnly ? "snapshot" : "live"}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function sourceSummary(data: HubData): Array<{ label: string; count: number; state: string }> {
  const sources = data.sourceInbox?.sources ?? [];
  const sourceCount = (source: typeof sources[number]): number =>
    Number(
      source.recordCounts?.conversations
        ?? source.recordCounts?.contacts
        ?? source.recordCounts?.messages
        ?? 0,
    );
  return sources
    .filter((source) => sourceCount(source) > 0)
    .map((source) => ({
      label: source.label,
      count: sourceCount(source),
      state: source.importOnly ? "snapshot" : source.connected ? "live" : source.state,
    }))
    .slice(0, 8);
}

function ContactProfileRow({ profile }: { profile: SourceInboxProfile }) {
  return (
    <div className="rounded-2xl border border-border/55 bg-background/35 px-3 py-3">
      <div className="flex min-w-0 items-start gap-3">
        <span
          className={cn(
            "mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
            profile.heatLabel === "hot" ? "bg-warning" : profile.heatLabel === "warm" ? "bg-success" : "bg-muted-foreground/45",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
              {profile.displayName}
            </div>
            <Badge variant={profile.hasCrm ? "success" : profile.isPotentialLead ? "warning" : "outline"}>
              {profile.hasCrm ? "CRM" : profile.isPotentialLead ? "potential" : "conversation"}
            </Badge>
          </div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {profile.latestText || "No recent context yet."}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant={heatVariant(profile)}>
              {profile.heatLabel} {profile.heatScore}
            </Badge>
            {profile.crmStage && <Badge variant="outline">{profile.crmStage}</Badge>}
            {profile.leadSource && <Badge variant="outline">{profile.leadSource}</Badge>}
            {profile.sources.slice(0, 2).map((source) => (
              <Badge key={source} variant="outline">{source}</Badge>
            ))}
            {profile.channels.slice(0, 2).map((channel) => (
              <Badge key={channel} variant="outline">{channel}</Badge>
            ))}
            <Badge variant="outline">{profileWhen(profile)}</Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

function ContactColumn({
  empty,
  profiles,
  title,
}: {
  empty: string;
  profiles: SourceInboxProfile[];
  title: string;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-muted-foreground">{title}</div>
        <Badge variant={profiles.length ? "outline" : "secondary"}>{profiles.length}</Badge>
      </div>
      <div className="space-y-2">
        {profiles.length ? (
          profiles.map((profile) => <ContactProfileRow key={profile.id} profile={profile} />)
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-3 py-6 text-xs leading-5 text-muted-foreground">
            {empty}
          </div>
        )}
      </div>
    </div>
  );
}

function ContactOverviewBoard({ data }: { data: HubData }) {
  const profiles = data.sourceInbox?.profiles ?? [];
  const buckets = contactBuckets(profiles);
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Contact overview</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              CRM contacts are the main source of truth. Conversations from Messages, SMS, email, and social attach when phone, email, or name matches.
            </p>
          </div>
          <Badge variant="outline">{profiles.length} people</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)_minmax(0,0.85fr)]">
          <ContactColumn
            title="CRM contacts"
            profiles={buckets.crmContacts}
            empty="No CRM contacts are synced yet. Lofty/FUB/CRM people will anchor this column."
          />
          <ContactColumn
            title="Current conversations"
            profiles={buckets.active}
            empty="No unmatched active conversations yet."
          />
          <ContactColumn
            title="Potential social leads"
            profiles={buckets.potential}
            empty="No out-of-CRM social leads yet. Facebook/Instagram DMs with buyer/seller language will appear here."
          />
        </div>
      </CardContent>
    </Card>
  );
}

function LeadProfilesWorkbench({
  onChanged,
  showHeader = true,
  profiles,
  threads,
}: {
  onChanged: () => Promise<void>;
  showHeader?: boolean;
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();
  const [pendingProfileAction, setPendingProfileAction] = useState<ProfilePendingAdminAction | null>(null);
  const [profileHandoffs, setProfileHandoffs] = useState<Record<string, ProfileHandoffIds>>({});
  const [existingDealIds, setExistingDealIds] = useState<Record<string, ProfileAdminDealIds>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let live = true;
    Promise.all([
      api.getAdminDeals({ status: "active", limit: 200 }),
      api.getAgentHandoffs({ fromAgentId: "executive-assistant", toAgentId: "admin", limit: 500 }),
    ])
      .then(([dealsResponse, handoffsResponse]) => {
        if (!live) return;
        const nextDeals: Record<string, ProfileAdminDealIds> = {};
        for (const deal of dealsResponse.items) {
          const sourceProfileId = deal.extraToggles?.sourceProfileId;
          if (typeof sourceProfileId === "string" && (deal.side === "listing" || deal.side === "buyer")) {
            nextDeals[sourceProfileId] = {
              ...nextDeals[sourceProfileId],
              [deal.side]: deal.id,
            };
          }
        }
        const nextHandoffs: Record<string, ProfileHandoffIds> = {};
        for (const handoff of handoffsResponse.items) {
          if (!handoff.profileId) continue;
          const side = profileHandoffSide(handoff);
          if (!side) continue;
          const existing = nextHandoffs[handoff.profileId]?.[side];
          if (existing && Date.parse(existing.updatedAt || "") >= Date.parse(handoff.updatedAt || "")) continue;
          nextHandoffs[handoff.profileId] = {
            ...nextHandoffs[handoff.profileId],
            [side]: handoff,
          };
        }
        setExistingDealIds(nextDeals);
        setProfileHandoffs(nextHandoffs);
      })
      .catch(() => {
        if (live) {
          setExistingDealIds({});
          setProfileHandoffs({});
        }
      });
    return () => {
      live = false;
    };
  }, []);

  const threadsByProfileId = useMemo(() => {
    const byAnyThreadId = new Map<string, SourceInboxThread>();
    for (const thread of threads) {
      byAnyThreadId.set(thread.id, thread);
      byAnyThreadId.set(thread.threadId, thread);
    }
    const next = new Map<string, SourceInboxThread[]>();
    for (const profile of profiles) {
      const matches: SourceInboxThread[] = [];
      for (const threadId of profile.threadIds) {
        const thread = byAnyThreadId.get(threadId);
        if (thread && !matches.some((match) => match.id === thread.id)) {
          matches.push(thread);
        }
      }
      if (matches.length) {
        matches.sort((a, b) => {
          const active = Number(isActiveProfileThread(b)) - Number(isActiveProfileThread(a));
          if (active !== 0) return active;
          return threadSortTime(b) - threadSortTime(a);
        });
        next.set(profile.id, matches);
      }
    }
    return next;
  }, [profiles, threads]);

  const threadByProfileId = useMemo(() => {
    const next = new Map<string, SourceInboxThread>();
    for (const [profileId, profileThreads] of threadsByProfileId) {
      const activeThread = profileThreads.find(isActiveProfileThread);
      next.set(profileId, activeThread ?? profileThreads[0]);
    }
    return next;
  }, [threadsByProfileId]);

  const combinedDealIdsByProfile = useMemo(() => {
    const next: Record<string, ProfileAdminDealIds> = {};
    for (const [profileId, dealIds] of Object.entries(existingDealIds)) {
      next[profileId] = { ...dealIds };
    }
    return next;
  }, [existingDealIds]);

  const profileSections = useMemo(() => {
    const grouped: Record<ProfileActionBucketId, SourceInboxProfile[]> = {
      "active-conversation": [],
      "push-admin": [],
      "needs-verifier": [],
      "follow-up": [],
      "in-admin": [],
    };
    for (const profile of profiles) {
      grouped[
        profileActionBucket(
          profile,
          combinedDealIdsByProfile[profile.id],
          profileHasActiveConversation(profile, threadsByProfileId.get(profile.id)),
        )
      ].push(profile);
    }
    return PROFILE_ACTION_BUCKETS.map((bucket) => ({
      ...bucket,
      profiles: grouped[bucket.id]
        .slice()
        .sort(bucket.id === "active-conversation" ? profileConversationSort : profileActionSort),
    })).filter((section) => section.profiles.length > 0);
  }, [combinedDealIdsByProfile, profiles, threadsByProfileId]);

  const queueProfileSkillWorkflow = async (profile: SourceInboxProfile, side: AdminDealSide) => {
    if (pendingProfileAction) return;
    const sideCopy = PROFILE_ADMIN_SIDE_COPY[side];
    setPendingProfileAction({ profileId: profile.id, side });
    setErrors((prev) => {
      const next = { ...prev };
      delete next[profile.id];
      return next;
    });
    try {
      const verifiers = profileVerifiers(profile);
      if (!verifiers.length) {
        setErrors((prev) => ({
          ...prev,
          [profile.id]: "Add or sync a phone/email verifier before sending this profile to Admin.",
        }));
        return;
      }
      const setup = await api.getAdminSetup();
      if (!setup.complete) {
        setErrors((prev) => ({
          ...prev,
          [profile.id]: `Admin setup must be completed before ${sideCopy.errorLabel}. Missing: ${setup.missingRequiredKeys.join(", ")}`,
        }));
        return;
      }
      const priorHandoff = profileHandoffs[profile.id]?.[side];
      const activeHandoff = profileHandoffIsActive(priorHandoff);
      const handoff = await api.createAgentHandoff({
        fromAgentId: "executive-assistant",
        toAgentId: "admin",
        title: profileSkillWorkflowName(profile, side),
        task: profileSkillWorkflowPrompt(profile, side),
        priority: side === "listing" ? "high" : "normal",
        profileId: profile.id,
        contactId: profilePrimaryContactId(profile),
        conversationId: profile.conversationIds?.[0] ?? null,
        payload: {
          targetSide: side,
          workflow: sideCopy.workflow,
          workflowLabel: sideCopy.workflowLabel,
          skill: sideCopy.skill,
          profileContext: JSON.parse(profileSkillWorkflowContext(profile, side)),
          verifiers,
        },
        idempotencyKey: priorHandoff && !activeHandoff
          ? `profile-admin-handoff:${profile.id}:${sideCopy.workflow}:${Date.now()}`
          : `profile-admin-handoff:${profile.id}:${sideCopy.workflow}`,
        runNow: true,
      });
      setProfileHandoffs((prev) => ({
        ...prev,
        [profile.id]: {
          ...prev[profile.id],
          [side]: handoff,
        },
      }));
      await onChanged();
    } catch (error) {
      setErrors((prev) => ({
        ...prev,
        [profile.id]: error instanceof Error ? error.message : `Could not queue ${sideCopy.errorLabel}`,
      }));
    } finally {
      setPendingProfileAction(null);
    }
  };

  const openProfileThread = (profile: SourceInboxProfile) => {
    const thread = threadByProfileId.get(profile.id);
    if (!thread) return;
    if (drawer) {
      drawer.openThread(thread.sourceId, thread.threadId);
      return;
    }
    const params = new URLSearchParams({ source: thread.sourceId, thread: thread.threadId });
    navigate(`/chat?${params.toString()}`);
  };

  if (!profiles.length) {
    return (
      <div className="px-4 py-8 text-center">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          No profiles yet
        </h4>
        <p className="mt-2 text-sm leading-6 text-foreground/75">
          Synced contacts and conversations will appear here with buyer and seller admin handoff actions.
        </p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/40">
      {showHeader && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-foreground">Profiles</div>
            <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
              People built from CRM, inbox, SMS, and social sources, with active conversations pinned first.
            </p>
          </div>
          <Badge variant="outline">{profiles.length} profiles</Badge>
        </div>
      )}

      {profileSections.map((section) => (
        <div key={section.id} className="divide-y divide-border/40">
          <div className="bg-background/30 px-4 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/90">
                {section.label}
              </div>
              <Badge variant="outline">{section.profiles.length}</Badge>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {section.description}
            </p>
          </div>

          {section.profiles.map((profile) => {
            const thread = threadByProfileId.get(profile.id);
            const activeConversation = profileHasActiveConversation(profile, threadsByProfileId.get(profile.id));
            const dealIds = combinedDealIdsByProfile[profile.id] ?? {};
            const sellerDealId = dealIds.listing;
            const buyerDealId = dealIds.buyer;
            const sellerPending =
              pendingProfileAction?.profileId === profile.id && pendingProfileAction.side === "listing";
            const buyerPending =
              pendingProfileAction?.profileId === profile.id && pendingProfileAction.side === "buyer";
            const sellerHandoff = profileHandoffs[profile.id]?.listing;
            const buyerHandoff = profileHandoffs[profile.id]?.buyer;
            const error = errors[profile.id];
            const canHandoff = profileHasVerifier(profile);
            const sellerHandoffLabel = profileHandoffBadgeLabel(sellerHandoff, "listing");
            const buyerHandoffLabel = profileHandoffBadgeLabel(buyerHandoff, "buyer");
            return (
              <div key={profile.id} className="px-4 py-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "h-2.5 w-2.5 rounded-full",
                          profile.heatLabel === "hot"
                            ? "bg-destructive"
                            : profile.heatLabel === "warm"
                              ? "bg-warning"
                              : profile.heatLabel === "watch"
                                ? "bg-success"
                                : "bg-muted-foreground/45",
                        )}
                      />
                      <div className="min-w-0 truncate text-sm font-semibold text-foreground">
                        {profile.displayName}
                      </div>
                      <Badge variant={heatVariant(profile)}>
                        {profile.heatLabel} {profile.heatScore}
                      </Badge>
                      {profile.hasCrm && <Badge variant="success">CRM</Badge>}
                      {profile.isPotentialLead && <Badge variant="warning">potential lead</Badge>}
                      {activeConversation && <Badge variant="success">active conversation</Badge>}
                      <Badge variant={profileHasVerifier(profile) ? "success" : "warning"}>
                        {profileVerifierSummary(profile)}
                      </Badge>
                      {sellerHandoffLabel && <Badge variant={sellerHandoff?.status === "failed" ? "destructive" : "warning"}>{sellerHandoffLabel}</Badge>}
                      {buyerHandoffLabel && <Badge variant={buyerHandoff?.status === "failed" ? "destructive" : "warning"}>{buyerHandoffLabel}</Badge>}
                      {sellerDealId && <Badge variant="success">{PROFILE_ADMIN_SIDE_COPY.listing.badgeLabel}</Badge>}
                      {buyerDealId && <Badge variant="success">{PROFILE_ADMIN_SIDE_COPY.buyer.badgeLabel}</Badge>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                      {profile.latestText || "No recent source context yet."}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[0.72rem] text-muted-foreground">
                      <Badge variant="outline">{profileSourceMeta(profile)}</Badge>
                      <Badge variant="outline">{profileContactLine(profile)}</Badge>
                      {profilePrimaryContactId(profile) && <Badge variant="outline">DB contact</Badge>}
                      <Badge variant="outline">{profile.threadCount} thread{profile.threadCount === 1 ? "" : "s"}</Badge>
                      <Badge variant="outline">{profileWhen(profile)}</Badge>
                      {profile.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="outline">{tag}</Badge>
                      ))}
                    </div>
                    {error && (
                      <p className="mt-2 text-xs leading-5 text-destructive">
                        {error}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!thread}
                      onClick={() => openProfileThread(profile)}
                    >
                      <MessageSquare className="h-3.5 w-3.5" />
                      Open thread
                    </Button>
                    {sellerDealId ? (
                      <Link
                        to="/admin"
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-9 px-3")}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {PROFILE_ADMIN_SIDE_COPY.listing.openLabel}
                      </Link>
                    ) : (
	                      <Button
	                        type="button"
	                        size="sm"
	                        variant="outline"
	                        onClick={() => queueProfileSkillWorkflow(profile, "listing")}
	                        disabled={pendingProfileAction !== null || !canHandoff || profileHandoffIsActive(sellerHandoff)}
	                      >
	                        {sellerPending ? (
	                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
	                        ) : profileHandoffIsActive(sellerHandoff) ? (
	                          <CheckCircle2 className="h-3.5 w-3.5" />
	                        ) : (
	                          <Home className="h-3.5 w-3.5" />
	                        )}
	                        {profileHandoffIsActive(sellerHandoff)
	                          ? PROFILE_ADMIN_SIDE_COPY.listing.queuedLabel
	                          : PROFILE_ADMIN_SIDE_COPY.listing.actionLabel}
                      </Button>
                    )}
                    {buyerDealId ? (
                      <Link
                        to="/admin"
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-9 px-3")}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {PROFILE_ADMIN_SIDE_COPY.buyer.openLabel}
                      </Link>
                    ) : (
                      <Button
                        type="button"
	                        size="sm"
	                        variant="outline"
	                        onClick={() => queueProfileSkillWorkflow(profile, "buyer")}
	                        disabled={pendingProfileAction !== null || !canHandoff || profileHandoffIsActive(buyerHandoff)}
	                      >
	                        {buyerPending ? (
	                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
	                        ) : profileHandoffIsActive(buyerHandoff) ? (
	                          <CheckCircle2 className="h-3.5 w-3.5" />
	                        ) : (
	                          <Users className="h-3.5 w-3.5" />
	                        )}
	                        {profileHandoffIsActive(buyerHandoff)
	                          ? PROFILE_ADMIN_SIDE_COPY.buyer.queuedLabel
	                          : PROFILE_ADMIN_SIDE_COPY.buyer.actionLabel}
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function LeadProfilesListPage({
  onChanged,
  profiles,
  threads,
}: {
  onChanged: () => Promise<void>;
  profiles: SourceInboxProfile[];
  threads: SourceInboxThread[];
}) {
  const verifiedCount = profiles.filter(profileHasVerifier).length;
  const potentialLeadCount = profiles.filter((profile) => profile.isPotentialLead).length;

  return (
    <section
      id="leads-panel-profiles"
      role="tabpanel"
      aria-labelledby="leads-tab-profiles"
      className="space-y-3"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-foreground">Profile list</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Active conversations stay at the top, then verified profiles queue buyer workflows or seller CMA before Admin handoff.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{profiles.length} total</Badge>
          <Badge variant={verifiedCount ? "success" : "warning"}>{verifiedCount} verified</Badge>
          <Badge variant={potentialLeadCount ? "warning" : "outline"}>{potentialLeadCount} potential leads</Badge>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <LeadProfilesWorkbench
          onChanged={onChanged}
          showHeader={false}
          profiles={profiles}
          threads={threads}
        />
      </div>
    </section>
  );
}

const LeadBoardRow = memo(function LeadBoardRow({
  data,
  thread,
  showOpenThread = true,
  variant = "card",
}: {
  data: HubData;
  thread: SourceInboxThread;
  showOpenThread?: boolean;
  variant?: "card" | "list";
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();

  const mark = async (action: "done" | "archive") => {
    await api.updateSourceInboxThread(thread.sourceId, thread.threadId, action);
    await data.refresh();
  };

  const openInChat = async () => {
    try {
      await api.updateSourceInboxThread(thread.sourceId, thread.threadId, "open");
    } catch {
      // best-effort
    }
    if (drawer) {
      drawer.openThread(thread.sourceId, thread.threadId);
      return;
    }
    const params = new URLSearchParams({
      thread: thread.threadId,
      source: thread.sourceId,
    });
    navigate(`/chat?${params.toString()}`);
  };

  const inbound = thread.direction !== "outbound";
  const heat = heatStyles(thread.heatLabel);
  const wait = inboundWaitMinutes(thread);

  const isList = variant === "list";

  const metaRow = (
    <div className="font-mono-ui mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-muted-foreground">
      <span>{thread.sourceLabel}</span>
      <span aria-hidden>·</span>
      <span>{thread.channel}</span>
      <span aria-hidden>·</span>
      <span>{inbound ? "in" : "out"}</span>
      <span aria-hidden>·</span>
      <span>{threadWhen(thread)}</span>
      {thread.messageCount > 1 && (
        <>
          <span aria-hidden>·</span>
          <span>{thread.messageCount} msgs</span>
        </>
      )}
      {inbound && wait != null && wait >= 5 && (
        <span
          className={cn(
            "rounded-full border px-1.5 py-0.5",
            wait >= 60
              ? "border-destructive/45 bg-destructive/10 text-destructive"
              : wait >= 30
                ? "border-warning/45 bg-warning/10 text-warning"
                : "border-border bg-card text-foreground/70",
          )}
        >
          waited {formatMinutes(wait)}
        </span>
      )}
    </div>
  );

  const headerRow = (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
        {thread.personName}
      </div>
      <span
        className={cn(
          "font-mono-ui inline-flex items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold",
          heat.pill,
        )}
      >
        {thread.heatScore}
      </span>
    </div>
  );

  const previewText = (
    <p className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/75">
      {thread.latestText}
    </p>
  );

  if (isList) {
    return (
      <div className="group flex items-start gap-3 px-3 py-3 transition-colors first:pt-3 last:pb-3 hover:bg-foreground/[0.02]">
        <span
          aria-label={heat.label}
          role="img"
          className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", heat.dot)}
        />
        <div className="min-w-0 flex-1">
          {headerRow}
          {previewText}
          {metaRow}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-11 w-11 p-0 text-foreground/60 hover:text-foreground sm:h-9 sm:w-9"
            onClick={() => void mark("archive")}
            aria-label={`Remove ${thread.personName} from list`}
            title="Remove"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-11 w-11 p-0 text-foreground/60 hover:text-foreground sm:h-9 sm:w-9"
            onClick={() => void mark("done")}
            aria-label={`Mark ${thread.personName} done`}
            title="Mark done"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
          </Button>
          {showOpenThread && (
            <Button
              size="sm"
              className="h-11 px-3 sm:h-9"
              onClick={() => void openInChat()}
              aria-label={`Open thread with ${thread.personName}`}
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="group rounded-xl border border-border bg-card px-3 py-3 transition-colors hover:bg-card/80">
      <div className="flex items-start gap-3">
        <span
          aria-label={heat.label}
          role="img"
          className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", heat.dot)}
        />
        <div className="min-w-0 flex-1">
          {headerRow}
          {previewText}
          {metaRow}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-1.5">
        <Button
          size="sm"
          variant="ghost"
          className="h-11 px-3 sm:h-9"
          onClick={() => void mark("archive")}
          aria-label={`Remove ${thread.personName} from list`}
        >
          Remove
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-11 px-3 sm:h-9"
          onClick={() => void mark("done")}
          aria-label={`Mark ${thread.personName} done`}
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          Done
        </Button>
        {showOpenThread && (
          <Button
            size="sm"
            className="h-11 px-3 sm:h-9"
            onClick={() => void openInChat()}
            aria-label={`Open thread with ${thread.personName}`}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open thread
          </Button>
        )}
      </div>
    </div>
  );
});

function LeadBoardColumn({
  data,
  empty,
  threads,
  title,
  showOpenThread = true,
}: {
  data: HubData;
  empty: string;
  threads: SourceInboxThread[];
  title: string;
  showOpenThread?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-muted-foreground">{title}</div>
        <Badge variant={threads.length ? "outline" : "secondary"}>{threads.length}</Badge>
      </div>
      <div className="space-y-2">
        {threads.length ? (
          threads.map((thread) => (
            <LeadBoardRow
              key={thread.id}
              data={data}
              thread={thread}
              showOpenThread={showOpenThread}
            />
          ))
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-3 py-6 text-xs leading-5 text-muted-foreground">
            {empty}
          </div>
        )}
      </div>
    </div>
  );
}

function LeadWorkBoard({
  data,
  threads: threadsOverride,
  layout = "kanban",
  showSources = true,
}: {
  data: HubData;
  threads?: SourceInboxThread[];
  layout?: "kanban" | "stack";
  showSources?: boolean;
}) {
  const threads = threadsOverride ?? data.sourceInbox?.threads ?? [];
  const buckets = leadThreadBuckets(threads);
  const sources = sourceSummary(data);

  const columns = [
    { title: "Hot now", threads: buckets.hot, empty: "No hot leads yet." },
    { title: "Needs follow-up", threads: buckets.followUp, empty: "No reply-needed leads." },
    { title: "Watch list", threads: buckets.watch, empty: "Nothing on the watch list." },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Lead workboard</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Prioritized people from CRM, Messages, and other lead sources. Marking a row hides it without touching source data.
            </p>
          </div>
          <Badge variant={threads.length ? "warning" : "outline"}>{threads.length} open</Badge>
        </div>
      </CardHeader>
      <CardContent className={cn(layout === "kanban" ? "space-y-4" : "space-y-5")}>
        {showSources && sources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {sources.map((source) => (
              <div
                key={source.label}
                className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-foreground/70"
              >
                <span className="font-semibold text-foreground">{source.label}</span>
                <span>{source.count}</span>
                <Badge variant="outline">{source.state}</Badge>
              </div>
            ))}
          </div>
        )}
        {layout === "kanban" ? (
          <div className="grid gap-4 xl:grid-cols-3">
            {columns.map((column) => (
              <LeadBoardColumn
                key={column.title}
                data={data}
                title={column.title}
                threads={column.threads}
                empty={column.empty}
              />
            ))}
          </div>
        ) : (
          columns.map((column) => (
            <section key={column.title} className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {column.title}
                </h3>
                <Badge variant={column.threads.length ? "outline" : "secondary"}>
                  {column.threads.length}
                </Badge>
              </div>
              {column.threads.length ? (
                <div className="space-y-2">
                  {column.threads.map((thread) => (
                    <LeadBoardRow key={thread.id} data={data} thread={thread} />
                  ))}
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-border bg-background/20 px-3 py-4 text-xs text-muted-foreground">
                  {column.empty}
                </div>
              )}
            </section>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function draftWhen(draft: SourceInboxDraft): string {
  return draft.latestAt ? isoTimeAgo(draft.latestAt) : "unsynced";
}

function DraftMessagesBoard({
  data,
  drafts: draftsOverride,
  emptyMessage,
  keyboard = false,
  pageSize = 8,
  showOpenThread = true,
  title = "Draft follow-ups",
}: {
  data: HubData;
  drafts?: SourceInboxDraft[];
  emptyMessage?: string;
  keyboard?: boolean;
  pageSize?: number;
  showOpenThread?: boolean;
  title?: string;
}) {
  const drawer = useThreadDrawer();
  const navigate = useNavigate();
  const allDrafts = draftsOverride ?? data.sourceInbox?.drafts ?? [];
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftEdits, setDraftEdits] = useState<Record<string, string>>({});
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [density, setDensity] = useState<"compact" | "expanded">("compact");
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const drafts = allDrafts.filter((d) => !dismissedIds.has(d.id));
  const visibleDrafts = showAll ? drafts : drafts.slice(0, pageSize);
  const selectedVisible = visibleDrafts.filter((d) => selectedIds.has(d.id));
  const allVisibleSelected = visibleDrafts.length > 0 && selectedVisible.length === visibleDrafts.length;

  useEffect(() => {
    const liveIds = new Set(allDrafts.map((d) => d.id));
    setDismissedIds((current) => {
      if (current.size === 0) return current;
      let changed = false;
      const next = new Set<string>();
      current.forEach((id) => {
        if (liveIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      return changed ? next : current;
    });
    setSelectedIds((current) => {
      if (current.size === 0) return current;
      let changed = false;
      const next = new Set<string>();
      current.forEach((id) => {
        if (liveIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [allDrafts]);

  useEffect(() => {
    if (!visibleDrafts.length) {
      setFocusedId(null);
      return;
    }
    if (!focusedId || !visibleDrafts.some((draft) => draft.id === focusedId)) {
      setFocusedId(visibleDrafts[0]?.id ?? null);
    }
  }, [focusedId, visibleDrafts]);

  const updateDraft = useCallback(
    async (
      draft: SourceInboxDraft,
      action: "approve" | "edit" | "skip",
      text = draft.draftText,
    ) => {
      const isDismiss = action === "approve" || action === "skip";
      if (isDismiss) {
        setDismissedIds((current) => {
          const next = new Set(current);
          next.add(draft.id);
          return next;
        });
        setEditingId((current) => (current === draft.id ? null : current));
        setExpandedId((current) => (current === draft.id ? null : current));
        setDraftEdits((current) => {
          if (!(draft.id in current)) return current;
          const next = { ...current };
          delete next[draft.id];
          return next;
        });
      }
      try {
        await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, action, text);
        if (!isDismiss) {
          setEditingId(null);
          setDraftEdits((current) => {
            const next = { ...current };
            delete next[draft.id];
            return next;
          });
        }
        void data.refresh();
      } catch (error) {
        if (isDismiss) {
          setDismissedIds((current) => {
            const next = new Set(current);
            next.delete(draft.id);
            return next;
          });
        }
        console.error("Failed to update draft", error);
        window.alert(`Failed to ${action} draft: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [data],
  );

  const openInChat = useCallback(
    async (draft: SourceInboxDraft) => {
      try {
        await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, "open", draft.draftText);
      } catch {
        // best-effort
      }
      if (drawer) {
        drawer.openThread(draft.sourceId, draft.threadId);
        return;
      }
      const params = new URLSearchParams({
        thread: draft.threadId,
        source: draft.sourceId,
        draft: draft.taskId,
      });
      navigate(`/chat?${params.toString()}`);
    },
    [drawer, navigate],
  );

  useEffect(() => {
    if (!keyboard) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!visibleDrafts.length) return;
      const currentIndex = Math.max(
        0,
        visibleDrafts.findIndex((draft) => draft.id === focusedId),
      );
      const focused = visibleDrafts[currentIndex];

      const move = (delta: number) => {
        const next = visibleDrafts[(currentIndex + delta + visibleDrafts.length) % visibleDrafts.length];
        if (next) {
          setFocusedId(next.id);
          requestAnimationFrame(() => {
            rowRefs.current[next.id]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          });
        }
      };

      switch (event.key) {
        case "ArrowDown":
        case "j":
          event.preventDefault();
          move(1);
          break;
        case "ArrowUp":
        case "k":
          event.preventDefault();
          move(-1);
          break;
        case "a":
        case "A":
          if (focused) {
            event.preventDefault();
            void updateDraft(focused, "approve");
          }
          break;
        case "s":
        case "S":
          if (focused) {
            event.preventDefault();
            void updateDraft(focused, "skip");
          }
          break;
        case "e":
        case "E":
          if (focused) {
            event.preventDefault();
            setEditingId(focused.id);
            setDraftEdits((current) => ({ ...current, [focused.id]: focused.draftText }));
          }
          break;
        case "o":
        case "O":
          if (focused && showOpenThread) {
            event.preventDefault();
            void openInChat(focused);
          }
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [focusedId, keyboard, openInChat, showOpenThread, updateDraft, visibleDrafts]);

  const toggleSelected = useCallback((id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((current) => {
      if (visibleDrafts.length > 0 && visibleDrafts.every((d) => current.has(d.id))) {
        const next = new Set(current);
        visibleDrafts.forEach((d) => next.delete(d.id));
        return next;
      }
      const next = new Set(current);
      visibleDrafts.forEach((d) => next.add(d.id));
      return next;
    });
  }, [visibleDrafts]);

  const runBulk = useCallback(
    async (action: "approve" | "skip") => {
      if (selectedVisible.length === 0 || bulkBusy) return;
      setBulkBusy(true);
      try {
        for (const draft of selectedVisible) {
          await updateDraft(draft, action);
        }
        setSelectedIds(new Set());
      } finally {
        setBulkBusy(false);
      }
    },
    [bulkBusy, selectedVisible, updateDraft],
  );

  const fallbackEmpty =
    emptyMessage ??
    "No draft replies are waiting. Composio social imports, CRM follow-ups, and outreach tasks can feed approval-gated messages here.";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <CardTitle>{title}</CardTitle>
              <span
                className={cn(
                  "font-mono-ui inline-flex items-center rounded-full border px-2 py-0.5 text-[0.68rem] font-semibold",
                  drafts.length
                    ? "border-warning/45 bg-warning/10 text-warning"
                    : "border-border bg-card text-muted-foreground",
                )}
              >
                {drafts.length} waiting
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Approval-gated. Nothing sends until you click Approve.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {keyboard && drafts.length > 0 && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setHelpOpen((v) => !v)}
                  aria-expanded={helpOpen}
                  aria-haspopup="dialog"
                  aria-label="Keyboard shortcuts"
                  className="font-mono-ui inline-flex h-11 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-[0.72rem] text-muted-foreground transition hover:bg-card/70 sm:h-9"
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                  Shortcuts
                </button>
                {helpOpen && (
                  <div
                    role="dialog"
                    className="absolute right-0 top-[calc(100%+6px)] z-30 w-64 rounded-xl border border-border bg-card p-3 shadow-lg"
                  >
                    <div className="font-mono-ui mb-2 text-[0.66rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      Keyboard
                    </div>
                    <ul className="space-y-1.5 text-xs text-foreground">
                      {[
                        ["↑ ↓ / J K", "navigate"],
                        ["A", "approve"],
                        ["E", "edit"],
                        ["S", "skip"],
                        ...(showOpenThread ? [["O", "open thread"] as const] : []),
                      ].map(([key, label]) => (
                        <li key={key} className="flex items-center justify-between gap-2">
                          <kbd
                            aria-keyshortcuts={key}
                            className="font-mono-ui rounded border border-border bg-background/40 px-1.5 py-0.5 text-[0.7rem]"
                          >
                            {key}
                          </kbd>
                          <span className="text-muted-foreground">{label}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            <div
              className="font-mono-ui inline-flex h-11 overflow-hidden rounded-full border border-border text-[0.7rem] sm:h-9"
              role="group"
              aria-label="Layout density"
            >
              <button
                type="button"
                onClick={() => setDensity("compact")}
                aria-pressed={density === "compact"}
                className={cn(
                  "px-3 transition",
                  density === "compact"
                    ? "bg-primary/15 text-foreground"
                    : "text-muted-foreground hover:bg-card/70",
                )}
              >
                Compact
              </button>
              <button
                type="button"
                onClick={() => setDensity("expanded")}
                aria-pressed={density === "expanded"}
                className={cn(
                  "px-3 transition",
                  density === "expanded"
                    ? "bg-primary/15 text-foreground"
                    : "text-muted-foreground hover:bg-card/70",
                )}
              >
                Expanded
              </button>
            </div>
          </div>
        </div>
        {visibleDrafts.length > 0 && (
          <div className="font-mono-ui mt-3 flex flex-wrap items-center gap-3 border-t border-border/60 pt-3 text-xs text-muted-foreground">
            <button
              type="button"
              onClick={toggleSelectAll}
              aria-pressed={allVisibleSelected}
              className="inline-flex h-11 items-center gap-2 rounded-full border border-border bg-card px-3 hover:bg-card/70 sm:h-9"
            >
              {allVisibleSelected ? (
                <CheckSquare className="h-3.5 w-3.5 text-primary" />
              ) : (
                <SquareIcon className="h-3.5 w-3.5 text-muted-foreground/80" />
              )}
              {allVisibleSelected ? "Clear" : "Select all"}
            </button>
            <span className="text-muted-foreground">
              {selectedVisible.length} selected · {visibleDrafts.length} shown
              {drafts.length > visibleDrafts.length ? ` of ${drafts.length}` : ""}
            </span>
            {drafts.length > pageSize && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-foreground hover:bg-card/70"
              >
                {showAll ? `Show first ${pageSize}` : `Show all ${drafts.length}`}
              </button>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent className="relative divide-y divide-border/40">
        {visibleDrafts.length ? (
          visibleDrafts.map((draft) => {
            const isEditing = editingId === draft.id;
            const draftText = draftEdits[draft.id] ?? draft.draftText;
            const isFocused = keyboard && focusedId === draft.id;
            const isExpanded = density === "expanded" || expandedId === draft.id || isEditing;
            const isSelected = selectedIds.has(draft.id);
            const heat = heatStyles(String(draft.leadLabel ?? ""));
            return (
              <div
                key={draft.id}
                ref={(node) => {
                  rowRefs.current[draft.id] = node;
                }}
                onMouseEnter={() => keyboard && setFocusedId(draft.id)}
                className={cn(
                  "group relative py-3 transition-colors first:pt-0 last:pb-0",
                  isFocused && "bg-primary/[0.06]",
                  isSelected && !isFocused && "bg-primary/[0.04]",
                  !isFocused && !isSelected && "hover:bg-foreground/[0.02]",
                )}
              >
                {isFocused && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 w-0.5 rounded-full bg-primary"
                  />
                )}
                <div className="flex w-full min-w-0 items-start gap-2">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSelected(draft.id);
                    }}
                    aria-pressed={isSelected}
                    aria-label={isSelected ? `Deselect draft for ${draft.personName}` : `Select draft for ${draft.personName}`}
                    className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition hover:border-primary/45 hover:text-primary sm:mt-0.5 sm:h-6 sm:w-6"
                  >
                    {isSelected ? (
                      <CheckSquare className="h-3.5 w-3.5 text-primary" />
                    ) : (
                      <SquareIcon className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (isEditing) return;
                      setExpandedId((current) => (current === draft.id ? null : draft.id));
                    }}
                    className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
                    aria-expanded={isExpanded}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                          {draft.personName}
                        </div>
                        <span className="font-mono-ui shrink-0 text-[0.7rem] text-muted-foreground">
                          {draftWhen(draft)}
                        </span>
                      </div>
                      <div className="font-mono-ui mt-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.7rem] text-muted-foreground">
                        <span className="truncate">{draft.sourceLabel}</span>
                        <span aria-hidden className="opacity-50">·</span>
                        <span className="truncate">{draft.channel}</span>
                        {draft.leadLabel && (
                          <>
                            <span aria-hidden className="opacity-50">·</span>
                            <span
                              className={cn(
                                "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[0.66rem] font-semibold",
                                heat.pill,
                              )}
                              title={draft.scoreReason ?? undefined}
                            >
                              {String(draft.leadLabel)}
                              {typeof draft.score === "number" ? ` ${draft.score}` : ""}
                            </span>
                          </>
                        )}
                        {draft.generated && (
                          <>
                            <span aria-hidden className="opacity-50">·</span>
                            <span className="text-warning">suggested</span>
                          </>
                        )}
                      </div>
                      <p
                        className={cn(
                          "mt-1.5 text-xs leading-5 text-foreground",
                          !isExpanded && "line-clamp-2",
                        )}
                      >
                        {draft.draftText}
                      </p>
                    </div>
                  </button>
                  {!isEditing && (
                    <div className="flex shrink-0 items-center gap-1 opacity-80 transition group-hover:opacity-100">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void updateDraft(draft, "skip");
                        }}
                        title="Skip"
                        aria-label={`Skip draft for ${draft.personName}`}
                        className="flex h-11 w-11 items-center justify-center rounded-full text-muted-foreground transition hover:bg-destructive/12 hover:text-destructive sm:h-9 sm:w-9"
                      >
                        <XCircle className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void updateDraft(draft, "approve", draft.draftText);
                        }}
                        title="Approve"
                        aria-label={`Approve draft for ${draft.personName}`}
                        className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/15 text-primary transition hover:bg-primary/25 sm:h-9 sm:w-9"
                      >
                        <Send className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>
                {isExpanded && (
                  <div className="mt-2 space-y-2 border-t border-border/55 pt-2">
                    {draft.context && !isEditing && (
                      <p className="text-[0.72rem] leading-5 text-muted-foreground">
                        {draft.context}
                      </p>
                    )}
                    {isEditing && (
                      <textarea
                        value={draftText}
                        onChange={(event) =>
                          setDraftEdits((current) => ({ ...current, [draft.id]: event.target.value }))
                        }
                        className="min-h-24 w-full resize-y rounded-xl border border-border bg-background/60 px-2.5 py-2 text-sm leading-6 text-foreground outline-none transition focus:border-primary/45 focus:ring-2 focus:ring-primary/15"
                      />
                    )}
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      {!isEditing && showOpenThread && (
                        <Button size="sm" variant="ghost" className="h-11 px-3 sm:h-9" onClick={() => void openInChat(draft)}>
                          <ExternalLink className="h-3.5 w-3.5" />
                          Thread
                        </Button>
                      )}
                      {!isEditing && (
                        <Button size="sm" variant="ghost" className="h-11 px-3 sm:h-9" onClick={() => void updateDraft(draft, "skip")}>
                          <XCircle className="h-3.5 w-3.5" />
                          Skip
                        </Button>
                      )}
                      {isEditing ? (
                        <>
                          <Button size="sm" variant="ghost" className="h-11 px-3 sm:h-9" onClick={() => setEditingId(null)}>
                            Cancel
                          </Button>
                          <Button size="sm" variant="outline" className="h-11 px-3 sm:h-9" onClick={() => void updateDraft(draft, "edit", draftText)}>
                            Save
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-11 px-3 sm:h-9"
                          onClick={() => {
                            setEditingId(draft.id);
                            setDraftEdits((current) => ({ ...current, [draft.id]: draft.draftText }));
                          }}
                        >
                          <PencilLine className="h-3.5 w-3.5" />
                          Edit
                        </Button>
                      )}
                      <Button
                        size="sm"
                        className="h-11 px-3 sm:h-9"
                        onClick={() => void updateDraft(draft, "approve", isEditing ? draftText : draft.draftText)}
                      >
                        <Send className="h-3.5 w-3.5" />
                        Approve
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <div className="px-4 py-10 text-center">
            <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
              Inbox empty
            </h4>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{fallbackEmpty}</p>
          </div>
        )}
        {selectedVisible.length > 0 && (
          <div
            className="sticky bottom-3 left-0 right-0 z-20 mx-auto mt-3 flex w-fit max-w-full items-center gap-2 rounded-full border border-border bg-card px-3 py-2 shadow-[0_18px_48px_color-mix(in_srgb,var(--background-base)_55%,transparent)]"
            role="region"
            aria-label="Bulk actions"
          >
            <span className="font-mono-ui text-[0.72rem] text-muted-foreground">
              {selectedVisible.length} selected
            </span>
            <Button
              size="sm"
              variant="ghost"
              className="h-11 px-3 sm:h-9"
              disabled={bulkBusy}
              onClick={() => setSelectedIds(new Set())}
            >
              Clear
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-11 px-3 sm:h-9"
              disabled={bulkBusy}
              onClick={() => void runBulk("skip")}
            >
              <XCircle className="h-3.5 w-3.5" />
              Skip {selectedVisible.length}
            </Button>
            <Button
              size="sm"
              className="h-11 px-3 sm:h-9"
              disabled={bulkBusy}
              onClick={() => void runBulk("approve")}
            >
              {bulkBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Approve {selectedVisible.length}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}


function HotLeadsList({
  data,
  threads,
}: {
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const hot = leadThreadBuckets(threads).hot.slice(0, 8);
  if (!hot.length) {
    return (
      <div className="px-4 py-8 text-center">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          No hot leads
        </h4>
        <p className="mt-2 text-sm leading-6 text-foreground/75">
          Recent replies, viewing requests, and repeat opens push leads here automatically.
        </p>
      </div>
    );
  }
  return (
    <div className="divide-y divide-border/40">
      {hot.map((thread) => (
        <LeadBoardRow key={thread.id} data={data} thread={thread} showOpenThread variant="list" />
      ))}
    </div>
  );
}

function LeadPipelineTabs({
  buyers,
  data,
  threads,
}: {
  buyers: BuyerWatchlistEntry[];
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const followUpCount = leadThreadBuckets(threads).followUp.length;
  const buyerCount = buyers.length;
  const defaultTab = followUpCount > 0 || buyerCount === 0 ? "follow-ups" : "buyers";

  return (
    <div className="rounded-2xl border border-border bg-card">
      <Tabs defaultValue={defaultTab}>
        {(active, setActive) => (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
              <TabsList>
                <TabsTrigger
                  active={active === "follow-ups"}
                  value="follow-ups"
                  onClick={() => setActive("follow-ups")}
                >
                  <span>Follow-ups</span>
                  <span
                    className={cn(
                      "font-mono-ui ml-2 rounded-full px-1.5 py-0.5 text-[0.62rem] tabular-nums",
                      active === "follow-ups"
                        ? "bg-foreground/10 text-foreground"
                        : "bg-foreground/5 text-muted-foreground",
                    )}
                  >
                    {followUpCount}
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  active={active === "buyers"}
                  value="buyers"
                  onClick={() => setActive("buyers")}
                >
                  <span>Buyer searches</span>
                  <span
                    className={cn(
                      "font-mono-ui ml-2 rounded-full px-1.5 py-0.5 text-[0.62rem] tabular-nums",
                      active === "buyers"
                        ? "bg-foreground/10 text-foreground"
                        : "bg-foreground/5 text-muted-foreground",
                    )}
                  >
                    {buyerCount}
                  </span>
                </TabsTrigger>
              </TabsList>
              <span className="hidden truncate text-xs text-muted-foreground sm:inline">
                {active === "follow-ups"
                  ? "Replies waiting on you, hottest first."
                  : "MLS buyers actively shopping."}
              </span>
            </div>
            <div>
              {active === "follow-ups" ? (
                <FollowUpThreadsList data={data} threads={threads} />
              ) : (
                <PrivateSearchBuyersList buyers={buyers} />
              )}
            </div>
          </>
        )}
      </Tabs>
    </div>
  );
}

function FollowUpThreadsList({
  data,
  threads,
}: {
  data: HubData;
  threads: SourceInboxThread[];
}) {
  const followUps = leadThreadBuckets(threads).followUp.slice(0, 8);
  if (!followUps.length) {
    return (
      <div className="px-4 py-8 text-center">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          Inbox zero on replies
        </h4>
        <p className="mt-2 text-sm leading-6 text-foreground/75">
          People who replied to your outreach across email, SMS, Messenger, IG and WhatsApp surface here, hottest first.
        </p>
      </div>
    );
  }
  return (
    <div className="divide-y divide-border/40">
      {followUps.map((thread) => (
        <LeadBoardRow key={thread.id} data={data} thread={thread} showOpenThread variant="list" />
      ))}
    </div>
  );
}

function PrivateSearchBuyersList({ buyers }: { buyers: BuyerWatchlistEntry[] }) {
  if (!buyers.length) {
    return (
      <div className="px-4 py-8 text-center">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          No active buyer searches yet
        </h4>
        <p className="mt-2 text-sm leading-6 text-foreground/75">
          Run the MLS analyzer to score buyers actively searching the board. Results land here ranked by score and recency.
        </p>
      </div>
    );
  }
  return (
    <div className="divide-y divide-border/40">
      {buyers.map((buyer) => (
        <BuyerWatchlistRow key={buyer.id} buyer={buyer} />
      ))}
    </div>
  );
}

function BuyerWatchlistRow({ buyer }: { buyer: BuyerWatchlistEntry }) {
  const score = typeof buyer.score === "number" ? buyer.score : null;
  const tier = (buyer.tier ?? "").toUpperCase();
  const days = typeof buyer.days === "number" ? buyer.days : null;
  const searches = (buyer.searches ?? []).filter(Boolean);
  const tone =
    tier === "HOT"
      ? "border-destructive/45 bg-destructive/10 text-destructive"
      : tier === "WARM"
        ? "border-warning/45 bg-warning/10 text-warning"
        : "border-border bg-card text-foreground/70";
  const dot =
    tier === "HOT"
      ? "bg-destructive"
      : tier === "WARM"
        ? "bg-warning"
        : "bg-foreground/40";

  return (
    <div className="group flex items-start gap-3 px-3 py-3 transition-colors first:pt-3 last:pb-3 hover:bg-foreground/[0.02]">
      <span aria-hidden="true" className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", dot)} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
            {buyer.name || "Unnamed buyer"}
          </div>
          {score !== null && (
            <span
              className={cn(
                "font-mono-ui inline-flex items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold",
                tone,
              )}
            >
              {score}
            </span>
          )}
        </div>
        {searches.length > 0 && (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/75">
            {searches.join(" · ")}
          </p>
        )}
        <div className="font-mono-ui mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-muted-foreground">
          {tier && <span>{tier.toLowerCase()}</span>}
          {tier && (days != null || buyer.lastActivity) && <span aria-hidden>·</span>}
          {days != null ? (
            <span>{days === 0 ? "today" : `${days}d ago`}</span>
          ) : buyer.lastActivity ? (
            <span>{buyer.lastActivity}</span>
          ) : null}
          {buyer.email && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1">
                <Mail className="h-3 w-3" />
                <span className="truncate">{buyer.email}</span>
              </span>
            </>
          )}
          {buyer.phone && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1">
                <Phone className="h-3 w-3" />
                {buyer.phone}
              </span>
            </>
          )}
          {buyer.sourceLabel && (
            <>
              <span aria-hidden>·</span>
              <span>{buyer.sourceLabel}</span>
            </>
          )}
        </div>
      </div>
      {buyer.profileUrl && (
        <a
          href={buyer.profileUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open MLS profile for ${buyer.name}`}
          className={cn(
            buttonVariants({ size: "sm", variant: "outline" }),
            "h-11 shrink-0 px-3 sm:h-9",
          )}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Profile
        </a>
      )}
    </div>
  );
}

function SkippedDraftsList({ data }: { data: HubData }) {
  const skipped = data.sourceInbox?.skippedDrafts ?? [];
  const [restoredIds, setRestoredIds] = useState<Set<string>>(() => new Set());

  const visible = skipped.filter((d) => !restoredIds.has(d.id));

  useEffect(() => {
    setRestoredIds((current) => {
      if (current.size === 0) return current;
      const liveIds = new Set(skipped.map((d) => d.id));
      let changed = false;
      const next = new Set<string>();
      current.forEach((id) => {
        if (liveIds.has(id)) next.add(id);
        else changed = true;
      });
      return changed ? next : current;
    });
  }, [skipped]);

  const restore = useCallback(
    async (draft: SourceInboxDraft) => {
      setRestoredIds((current) => {
        const next = new Set(current);
        next.add(draft.id);
        return next;
      });
      try {
        await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, "restore", draft.draftText);
        void data.refresh();
      } catch (error) {
        setRestoredIds((current) => {
          const next = new Set(current);
          next.delete(draft.id);
          return next;
        });
        window.alert(`Failed to restore: ${error instanceof Error ? error.message : String(error)}`);
      }
    },
    [data],
  );

  if (!visible.length) {
    return (
      <div className="px-4 py-8 text-center">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          Nothing skipped
        </h4>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Skipped drafts auto-clear after 3 days.
        </p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/40">
      {visible.map((draft) => (
        <div
          key={draft.id}
          className="group flex items-start gap-2 px-2.5 py-2.5 transition-colors hover:bg-card/40"
        >
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-foreground/8 text-muted-foreground">
            <XCircle className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-1.5">
              <div className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                {draft.personName}
              </div>
              <span className="font-mono-ui shrink-0 text-[0.66rem] text-muted-foreground">
                {draft.skippedAt ? isoTimeAgo(draft.skippedAt) : "—"}
              </span>
            </div>
            <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {draft.draftText}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void restore(draft)}
            title="Restore to queue"
            aria-label={`Restore draft for ${draft.personName}`}
            className="font-mono-ui inline-flex h-11 shrink-0 items-center rounded-full px-3 text-[0.7rem] font-semibold text-muted-foreground transition hover:bg-primary/12 hover:text-primary sm:h-9"
          >
            Restore
          </button>
        </div>
      ))}
    </div>
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
    <Suspense
      fallback={
        <div className="font-mono-ui flex min-h-[38rem] items-center justify-center text-[0.72rem] text-muted-foreground/80">
          Loading graph…
        </div>
      }
    >
      <MemoryConstellation
        className="min-h-[38rem]"
        edges={edges}
        nodes={nodes}
      />
    </Suspense>
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
          <div className="py-8 text-sm text-muted-foreground">
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
          <div className="py-8 text-sm text-muted-foreground">
            {empty}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AdminDealTasks({
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
          <div className="py-8 text-sm text-muted-foreground">{empty}</div>
        )}
      </CardContent>
    </Card>
  );
}

function AdminActionRuns({
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
          <div className="py-8 text-sm text-muted-foreground">{empty}</div>
        )}
      </CardContent>
    </Card>
  );
}

function handoffStatusVariant(status: string): "success" | "warning" | "outline" | "secondary" | "destructive" {
  if (status === "completed" || status === "succeeded") return "success";
  if (status === "failed") return "destructive";
  if (status === "waiting_human") return "warning";
  if (status === "queued" || status === "running") return "warning";
  return "outline";
}

function AgentHandoffsCard({
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
            <div className="py-8 text-sm text-muted-foreground">No handoffs yet.</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function AgentWorkerCard({
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
        <div className="rounded-2xl border border-border/55 bg-background/35 p-3 text-xs leading-5 text-muted-foreground">
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

function AdminRunDecisionRow({
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

function WorkflowStrip({
  items,
}: {
  items: Array<{
    icon?: ComponentType<{ className?: string }>;
    label: string;
    value: string | number;
  }>;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3 rounded-xl border border-border bg-card px-5 py-4">
      {items.map((item, i) => (
        <div key={item.label} className="flex items-baseline gap-2">
          {i > 0 && (
            <span aria-hidden="true" className="hidden text-border sm:inline-block">·</span>
          )}
          <span className="text-xl font-semibold tabular-nums text-foreground">
            {item.value}
          </span>
          <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
            {item.label}
          </span>
        </div>
      ))}
    </div>
  );
}

export function RealEstateTodayPage() {
  const data = useRealEstateHubData();
  useHubHeader("Today", data);

  const liveSessions = data.sessions.filter((session) => session.is_active);
  const enabledJobs = data.cronJobs.filter((job) => job.enabled);
  const openLeadThreads = Number(data.sourceInbox?.recordCounts?.threads ?? 0);
  const hotLeadThreads = sourceRecordCount(data, "hotThreads");
  const draftCount = sourceRecordCount(data, "drafts");
  const todayActions = [
    ...approvalActions(data),
    ...liveSessions.slice(0, 3).map((session) => sessionAction(session, "Continue", MessageSquare)),
    ...enabledJobs.slice(0, 4).map((job) => jobAction(job, "Scheduled", CalendarClock)),
  ];

  return (
    <ThreadDrawerProvider data={data}>
    <HubShell
      data={data}
      eyebrow="Real Estate Command Center"
      icon={Home}
      title="Elevate Agent · Today"
    >
      <WorkflowStrip
        items={[
          { icon: Target, label: "Hot leads", value: hotLeadThreads },
          { icon: MessageSquare, label: "Open threads", value: openLeadThreads },
          { icon: Send, label: "Drafts waiting", value: draftCount },
          { icon: Clock, label: "Timed tasks", value: enabledJobs.length },
        ]}
      />
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_28rem]">
        <LeadWorkBoard data={data} />
        <DraftMessagesBoard data={data} title="Drafts waiting" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={todayActions}
          empty="Nothing urgent is waiting. Start a chat, schedule a pulse, or continue a recent session when work comes in."
          title="Today's action board"
        />
        <TimedTasks jobs={enabledJobs} empty="No enabled timed tasks yet." />
      </div>
      <ClientInboxPreview data={data} title="Today's lead inbox" />
      <ContactOverviewBoard data={data} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <RecentSessions
          title="Recent operator activity"
          sessions={data.sessions}
          empty="No local sessions have been recorded yet."
        />
        <ActionBoard
          actions={data.snapshot?.agents.filter((agent) => agent.enabled).slice(0, 4).map((agent) => ({
            detail: agent.description || "Agent is available for routed real-estate work.",
            icon: Bot,
            id: `agent-${agent.id}`,
            meta: agent.role || "agent team",
            status: agent.status,
            title: agent.name,
            to: "/hub",
            variant: agent.status === "online" ? "success" : "outline" as const,
          })) ?? []}
          empty="No enabled agents are configured yet."
          title="Agent team"
        />
      </div>
    </HubShell>
    </ThreadDrawerProvider>
  );
}

type LeadSourceOption = {
  id: string;
  label: string;
  drafts: number;
  profiles: number;
  threads: number;
};

function LeadFilterBar({
  active,
  drafts,
  followUps,
  hot,
  onSelect,
  options,
  pulse,
  profiles,
  threads,
}: {
  active: string | null;
  drafts: number;
  followUps: number;
  hot: number;
  onSelect: (id: string | null) => void;
  options: LeadSourceOption[];
  pulse?: ResponsePulse;
  profiles: number;
  threads: number;
}) {
  type Stat = {
    label: string;
    value: number | string;
    tone: "warning" | "default" | "muted" | "destructive";
    emphasis?: "primary" | "secondary";
  };
  const queueStats: Stat[] = [
    { label: "Drafts to approve", value: drafts, tone: drafts > 0 ? "warning" : "muted", emphasis: "primary" },
    { label: "Hot leads", value: hot, tone: hot > 0 ? "default" : "muted", emphasis: "primary" },
    { label: "Profiles", value: profiles, tone: profiles > 0 ? "default" : "muted", emphasis: "primary" },
    { label: "Open threads", value: threads, tone: "default", emphasis: "primary" },
    { label: "Follow-ups scheduled", value: followUps, tone: "muted", emphasis: "primary" },
  ];
  const slaStats: Stat[] = [];
  if (pulse) {
    slaStats.push({
      label: "Unanswered",
      value: pulse.unanswered,
      tone: pulse.breached30 > 0 ? "destructive" : pulse.unanswered > 0 ? "warning" : "muted",
      emphasis: "secondary",
    });
    slaStats.push({
      label: "Median wait",
      value: formatMinutes(pulse.median),
      tone: (pulse.median ?? 0) >= 30 ? "destructive" : (pulse.median ?? 0) >= 5 ? "warning" : "muted",
      emphasis: "secondary",
    });
    slaStats.push({
      label: "Longest wait",
      value: formatMinutes(pulse.longest),
      tone: (pulse.longest ?? 0) >= 60 ? "destructive" : (pulse.longest ?? 0) >= 30 ? "warning" : "muted",
      emphasis: "secondary",
    });
  }

  const renderStat = (stat: Stat) => (
    <div key={stat.label} className="flex items-baseline gap-1.5">
      <span
        className={cn(
          "font-semibold tabular-nums leading-none",
          stat.emphasis === "primary" ? "text-lg" : "text-sm",
          stat.tone === "warning" && "text-warning",
          stat.tone === "destructive" && "text-destructive",
          stat.tone === "default" && "text-foreground",
          stat.tone === "muted" && "text-muted-foreground",
        )}
      >
        {stat.value}
      </span>
      <span className="font-mono-ui text-[0.68rem] uppercase tracking-[0.12em] text-muted-foreground">
        {stat.label}
      </span>
    </div>
  );

  return (
    <div className="rounded-2xl border border-border bg-card">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 px-4 py-3">
        {queueStats.map(renderStat)}
        {slaStats.length > 0 && (
          <span aria-hidden="true" className="hidden h-4 self-center border-l border-border/60 sm:inline-block" />
        )}
        {slaStats.map(renderStat)}
      </div>
      {options.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border/40 px-4 py-2.5">
          <span className="font-mono-ui mr-1 inline-flex items-center gap-1 text-[0.66rem] uppercase tracking-[0.14em] text-muted-foreground">
            <Filter className="h-3 w-3" />
            Filter
          </span>
          <FilterChip
            active={active === null}
            label="All"
            onClick={() => onSelect(null)}
          />
          {options.map((option) => (
            <FilterChip
              key={option.id}
              active={active === option.id}
              label={option.label}
              meta={`${option.drafts ? `${option.drafts} drafts · ` : ""}${option.profiles ? `${option.profiles} profiles · ` : ""}${option.threads}`}
              onClick={() => onSelect(option.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  label,
  meta,
  onClick,
}: {
  active: boolean;
  label: string;
  meta?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex h-11 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors sm:h-8",
        active
          ? "border-primary/45 bg-primary/12 text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-card/70 hover:text-foreground",
      )}
    >
      <span>{label}</span>
      {meta && (
        <span
          className={cn(
            "font-mono-ui rounded-full px-1.5 py-0.5 text-[0.62rem] tabular-nums",
            active ? "bg-primary/18 text-foreground" : "bg-foreground/8 text-muted-foreground",
          )}
        >
          {meta}
        </span>
      )}
    </button>
  );
}

function CollapsibleSection({
  children,
  count,
  defaultOpen = false,
  description,
  title,
}: {
  children: React.ReactNode;
  count?: number;
  defaultOpen?: boolean;
  description?: string;
  title: string;
}) {
  return (
    <details
      className="group rounded-2xl border border-border bg-card [&_summary]:list-none"
      open={defaultOpen}
    >
      <summary className="flex min-h-[3rem] cursor-pointer items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-foreground hover:bg-card/70">
        <span className="flex min-w-0 items-center gap-2">
          <h3 className="text-sm font-semibold">{title}</h3>
          {typeof count === "number" && (
            <span className="font-mono-ui inline-flex items-center rounded-full border border-border bg-background/40 px-2 py-0.5 text-[0.66rem] font-semibold text-foreground/75">
              {count}
            </span>
          )}
          {description && (
            <span className="truncate text-xs font-normal text-foreground/70 sm:inline">
              {description}
            </span>
          )}
        </span>
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="border-t border-border/55 px-4 py-4">{children}</div>
    </details>
  );
}

type AgentLaneId = "new-outreach" | "hot-leads-watcher" | "follow-ups" | "private-searches";

type AgentLaneDef = {
  id: AgentLaneId;
  name: string;
  tagline: string;
  icon: ComponentType<{ className?: string }>;
  schedule: string;
  scheduleLabel: string;
  matchKeywords: string[];
  prompt: string;
  cronName: string;
};

const AGENT_LANES: AgentLaneDef[] = [
  {
    id: "new-outreach",
    name: "New Outreach",
    tagline: "Daily first-touch on fresh leads from every connected source.",
    icon: Sparkles,
    schedule: "0 8 * * *",
    scheduleLabel: "Daily · 8:00am",
    matchKeywords: ["new outreach", "outreach", "first touch", "first-touch"],
    cronName: "New Outreach",
    prompt:
      "Run the outreach skill. Pull fresh leads from every connected source (CRM, SMS, email, social via Composio) that have not yet received a first-touch in the last 14 days. For each one: enrich from CRM + property-lookup, draft a personalized first message on the channel they came in from, and write the draft to the source inbox for approval. Do not send. Mark each lead as touched only after the human approves.",
  },
  {
    id: "hot-leads-watcher",
    name: "Hot Leads Watcher",
    tagline: "Daily scan for the hottest leads across channels.",
    icon: Radar,
    schedule: "0 8 * * *",
    scheduleLabel: "Daily · 8:00am",
    matchKeywords: ["hot lead", "hot leads", "watcher", "heat"],
    cronName: "Hot Leads Watcher",
    prompt:
      "Run the outreach skill in monitor mode. Scan every connected source (Lofty CRM, Apple Messages, Gmail, SMS, social via Composio) for hot signals since the last run: inbound replies, viewing requests, repeat opens, CRM stage moves, listing alerts. Re-score heat across the inbox and surface the top 10 hottest leads. For any lead with a brand-new inbound message that needs a reply, draft a same-channel response and queue it for approval. Do not send.",
  },
  {
    id: "follow-ups",
    name: "Follow-ups",
    tagline: "Re-touches scheduled threads that went cold.",
    icon: Repeat,
    schedule: "0 10,15 * * *",
    scheduleLabel: "Twice daily · 10a + 3p",
    matchKeywords: ["follow-up", "follow up", "followup", "nurture"],
    cronName: "Follow-ups",
    prompt:
      "Run the outreach skill in nurture mode. For every lead with an open thread whose last outbound was 3+ days ago without a reply (or whose CRM stage is in nurture), draft a context-aware follow-up on the same channel they were last contacted. Use the relationship history, last touch, and CRM stage to pick the angle. Queue every draft for approval. Do not send.",
  },
  {
    id: "private-searches",
    name: "Private Searches",
    tagline: "Nightly MLS PCS scrape → score → watchlist → CRM sync.",
    icon: Filter,
    schedule: "0 3 * * *",
    scheduleLabel: "Daily · 3:00am",
    matchKeywords: [
      "private search",
      "private searches",
      "pcs",
      "xposure",
      "saved search",
      "watchlist",
    ],
    cronName: "Private Searches",
    prompt:
      "Run the PCS pipeline: (1) scrape every registered buyer with a Private Client Search from Xposure MLS, push deltas to the CRM tagged xposure-pcs; (2) score each buyer HOT (active ≤30d) / WARM (≤90d) / cold; (3) for HOT buyers, pull their saved-search criteria (areas, beds, property type) and update the CRM stage + tag; (4) build a branded watchlist PDF with cover + per-lead cards (score, last active, areas, beds, call script). Stage results in the source dir. Do not send any messages.",
  },
];

function laneCronJob(lane: AgentLaneDef, jobs: CronJob[]): CronJob | undefined {
  const target = lane.cronName.toLowerCase();
  return (
    jobs.find((job) => (job.name ?? "").toLowerCase() === target) ??
    jobs.find((job) => jobMatches(job, lane.matchKeywords))
  );
}

function laneStatus(job: CronJob | undefined): {
  label: string;
  tone: "success" | "warning" | "muted" | "destructive";
} {
  if (!job) return { label: "Not started", tone: "muted" };
  if (job.last_error) return { label: "Error", tone: "destructive" };
  if (!job.enabled || job.state === "paused") return { label: "Paused", tone: "warning" };
  const nextMs = job.next_run_at ? Date.parse(job.next_run_at) : NaN;
  const lastMs = job.last_run_at ? Date.parse(job.last_run_at) : NaN;
  const now = Date.now();
  if (Number.isFinite(nextMs) && nextMs <= now && (!Number.isFinite(lastMs) || lastMs < nextMs)) {
    return { label: "Running", tone: "success" };
  }
  if (Number.isFinite(lastMs) && now - lastMs < 5 * 60 * 1000) {
    return { label: "Just ran", tone: "success" };
  }
  return { label: "Scheduled", tone: "muted" };
}

const ADMIN_WORKFLOW_KEYWORDS = [
  "admin",
  "listing",
  "deal",
  "transaction",
  "cma",
  "seller update",
  "seller-update",
  "showing",
  "showingtime",
  "showing time",
  "weekly",
  "relisting",
  "mlc",
  "signing",
  "signing-package",
  "digisign",
  "webforms",
  "contract",
  "paperwork",
  "document",
  "doc router",
  "gmail-doc-router",
  "gmail doc",
  "skyslope",
  "photo-cleanup",
  "listing-build",
  "offer-review",
  "subject-removal",
  "closing-admin",
  "market stats",
  "market-stats",
];

const DEFAULT_ADMIN_AUTOMATIONS = [
  {
    name: "Gmail Doc Router",
    schedule: "0 9 * * 1",
    skill: "gmail-doc-router",
    skills: ["gmail-doc-router"],
    deliver: "local",
    workdir: "/Users/dartagnanpatricio/.elevate/tmp/client-tools",
    prompt:
      "Run the gmail-doc-router skill. Check the last 7 days of Gmail attachments, match listing documents to active Elevate deals with deal-matcher, file documents to the correct Drive folder, and write artifacts/checklist evidence back to the deal with admin-result-writer. Do not send messages.",
  },
  {
    name: "Seller Update",
    schedule: "0 16 * * 1-5",
    skill: "seller-update",
    skills: ["seller-update"],
    deliver: "local",
    workdir: "/Users/dartagnanpatricio/.elevate/tmp/client-tools",
    prompt:
      "Run the seller-update skill. Pull ShowingTime feedback/activity for active listings, match each listing to an Elevate deal, write the digest back to SQLite, and create Gmail seller-update drafts. Never send directly.",
  },
  {
    name: "Market Stats Watcher",
    schedule: "0 7 * * 1",
    skill: "market-stats-watcher",
    skills: ["market-stats-watcher"],
    deliver: "local",
    workdir: "/Users/dartagnanpatricio/.elevate/tmp/client-tools",
    prompt:
      "Run the market-stats-watcher skill. Pull fresh market-stat emails and route useful market context into the real estate knowledge/admin workflow. Do not send messages.",
  },
];

function OutreachLanesGrid({
  cronJobs,
  onChanged,
}: {
  cronJobs: CronJob[];
  onChanged: () => Promise<void>;
}) {
  // Idempotently install/converge the default lanes the first time this view
  // renders. Server-side ``ensure-lanes`` updates an existing lane if the
  // default delivery, prompt, schedule, skills, or workdir changed. localStorage gate
  // means we don't hit the endpoint on every navigation; the UI still
  // converges if a lane was deleted (clear the flag from devtools).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const FLAG = "elevate.lanes.defaults_installed_v1";
    if (window.localStorage.getItem(FLAG) === "1") return;
    let cancelled = false;
    (async () => {
      try {
        await api.ensureLaneCronJobs(
          AGENT_LANES.map((lane) => ({
            name: lane.cronName,
            schedule: lane.schedule,
            prompt: lane.prompt,
            deliver: "local",
          })),
        );
        if (!cancelled) {
          window.localStorage.setItem(FLAG, "1");
          await onChanged();
        }
      } catch {
        // Best-effort install — if the endpoint is unavailable, the
        // legacy "Start" button on each card still works.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="divide-y divide-border/40">
      {AGENT_LANES.map((lane) => (
        <AgentLaneStripRow
          key={lane.id}
          lane={lane}
          job={laneCronJob(lane, cronJobs)}
          onChanged={onChanged}
        />
      ))}
    </div>
  );
}

function AgentLaneStripRow({
  lane,
  job,
  onChanged,
}: {
  lane: AgentLaneDef;
  job: CronJob | undefined;
  onChanged: () => Promise<void>;
}) {
  const Icon = lane.icon;
  const status = laneStatus(job);
  const [busy, setBusy] = useState<"start" | "trigger" | "toggle" | null>(null);

  const start = async () => {
    setBusy("start");
    try {
      await api.createCronJob({
        name: lane.cronName,
        schedule: lane.schedule,
        prompt: lane.prompt,
        deliver: "local",
      });
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const trigger = async () => {
    if (!job) return;
    setBusy("trigger");
    try {
      await api.triggerCronJob(job.id);
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const toggle = async () => {
    if (!job) return;
    setBusy("toggle");
    try {
      if (job.state === "paused" || !job.enabled) {
        await api.resumeCronJob(job.id);
      } else {
        await api.pauseCronJob(job.id);
      }
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid grid-cols-1 items-center gap-3 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_auto]">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">{lane.name}</span>
            <span
              className={cn(
                "font-mono-ui inline-flex items-center rounded-full px-2 py-0.5 text-[0.62rem] font-semibold uppercase tracking-[0.14em]",
                status.tone === "success" && "bg-success/12 text-success ring-1 ring-success/25",
                status.tone === "warning" && "bg-warning/12 text-warning ring-1 ring-warning/25",
                status.tone === "destructive" && "bg-destructive/12 text-destructive ring-1 ring-destructive/25",
                status.tone === "muted" && "bg-card text-muted-foreground ring-1 ring-border",
              )}
            >
              {status.label}
            </span>
          </div>
          <p className="mt-0.5 line-clamp-1 text-[0.72rem] text-muted-foreground">{lane.tagline}</p>
        </div>
      </div>

      <div className="font-mono-ui flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.7rem] tabular-nums text-foreground/70">
        <span>
          <span className="text-[0.62rem] uppercase tracking-[0.16em] text-muted-foreground/80">sched</span>{" "}
          <span className="text-foreground">{job?.schedule_display || lane.scheduleLabel}</span>
        </span>
        <span className="text-foreground/35">·</span>
        <span>
          <span className="text-[0.62rem] uppercase tracking-[0.16em] text-muted-foreground/80">last</span>{" "}
          <span className="text-foreground">{job?.last_run_at ? isoTimeAgo(job.last_run_at) : "—"}</span>
        </span>
        <span className="text-foreground/35">·</span>
        <span>
          <span className="text-[0.62rem] uppercase tracking-[0.16em] text-muted-foreground/80">next</span>{" "}
          <span className="text-foreground">
            {job?.next_run_at ? isoTimeAgo(job.next_run_at) : job ? "queued" : "—"}
          </span>
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {job ? (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void trigger()}
              disabled={busy !== null}
              className="h-11 px-3 text-xs sm:h-9"
              aria-label={`Run ${lane.name} now`}
            >
              <Zap className="h-3.5 w-3.5" />
              Run
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void toggle()}
              disabled={busy !== null}
              className="h-11 px-3 text-xs sm:h-9"
              aria-label={
                job.state === "paused" || !job.enabled
                  ? `Resume ${lane.name}`
                  : `Pause ${lane.name}`
              }
            >
              {job.state === "paused" || !job.enabled ? (
                <>
                  <Play className="h-3.5 w-3.5" />
                  Resume
                </>
              ) : (
                <>
                  <Pause className="h-3.5 w-3.5" />
                  Pause
                </>
              )}
            </Button>
            <Link
              to={`/cron?edit=${job.id}`}
              aria-label={`Edit ${lane.name} schedule`}
              className={cn(
                buttonVariants({ variant: "ghost", size: "sm" }),
                "h-11 px-3 text-xs text-foreground/70 hover:text-foreground sm:h-9",
              )}
            >
              <PencilLine className="h-3.5 w-3.5" />
              Edit
            </Link>
          </>
        ) : (
          <Button
            size="sm"
            onClick={() => void start()}
            disabled={busy !== null}
            className="h-11 px-3 text-xs sm:h-9"
          >
            <Plus className="h-3.5 w-3.5" />
            {busy === "start" ? "Starting…" : `Start ${lane.name}`}
          </Button>
        )}
      </div>
      {job?.last_error && (
        <div className="col-span-full rounded-xl border border-destructive/25 bg-destructive/8 px-3 py-2 text-[0.72rem] leading-5 text-destructive">
          {job.last_error}
        </div>
      )}
    </div>
  );
}

const SOURCE_ICON_BY_ID: Record<string, ComponentType<{ className?: string }>> = {
  "apple-messages": MessageSquare,
  "sms-provider": Phone,
  "android-device": Smartphone,
  rcs: Phone,
  crm: DatabaseIcon,
  social: Share2,
  email: Mail,
  skills: Network,
  "market-stats": Activity,
  "admin-requirements": BriefcaseBusiness,
  "document-storage": FileText,
  "forms-signing": FileCheck2,
};

const OUTREACH_CATEGORIES = new Set(["messages", "leads"]);

function sourceIcon(source: SourceConnectorStatus): ComponentType<{ className?: string }> {
  return SOURCE_ICON_BY_ID[source.id] ?? Inbox;
}

function compactCount(value: number): string {
  if (value >= 10000) {
    return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
  }
  return new Intl.NumberFormat().format(value);
}

type ContactState = {
  uncontacted: number;
  contacted: number;
};

function contactStateFromThreads(threads: SourceInboxThread[]): ContactState {
  let contacted = 0;
  let uncontacted = 0;
  for (const thread of threads) {
    if (thread.outboundCount > 0) contacted += 1;
    else uncontacted += 1;
  }
  return { contacted, uncontacted };
}

function contactStateFromProfiles(
  profiles: SourceInboxProfile[],
  threadsById: Map<string, SourceInboxThread>,
): ContactState {
  let contacted = 0;
  let uncontacted = 0;
  for (const profile of profiles) {
    const touched = profile.threadIds.some((id) => {
      const thread = threadsById.get(id);
      return thread ? thread.outboundCount > 0 : false;
    });
    if (touched) contacted += 1;
    else uncontacted += 1;
  }
  return { contacted, uncontacted };
}

function ComposioChannelStrip() {
  const [status, setStatus] = useState<ComposioStatus | null>(null);
  const [connections, setConnections] = useState<ComposioConnectedAccount[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await api.getComposioStatus();
        if (cancelled) return;
        setStatus(s);
        if (!s.valid) {
          setConnections([]);
          return;
        }
        const conns = await api.getComposioConnections();
        if (cancelled) return;
        const data = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
        setConnections(Array.isArray(data) ? data : data.items ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading || !status) return null;
  if (!status.hasKey) return null;

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
          Composio {status.valid ? `· ${connections.length} connected` : "· key invalid"}
        </h4>
        <Link
          to="/config#composio"
          className="text-xs text-foreground/65 transition-colors hover:text-foreground"
        >
          Manage
        </Link>
      </div>
      {!status.valid ? (
        <p className="text-xs leading-5 text-warning">
          Composio rejected the saved key. Update it in Config to import these channels.
        </p>
      ) : connections.length === 0 ? (
        <p className="text-xs leading-5 text-muted-foreground">
          No Composio accounts linked yet. Connect Instagram, Gmail, Twilio, or any other app from the Config page.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {connections.map((conn, idx) => (
            <span
              key={String(conn.id ?? idx)}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-foreground"
            >
              {conn.toolkit?.logo && (
                <img
                  src={conn.toolkit.logo}
                  alt=""
                  width={14}
                  height={14}
                  loading="lazy"
                  decoding="async"
                  className="h-3.5 w-3.5 rounded-sm"
                />
              )}
              <span>{conn.toolkit?.name ?? conn.toolkit?.slug ?? "app"}</span>
              {conn.status === "ACTIVE" && (
                <span aria-label="active" className="h-1.5 w-1.5 rounded-full bg-success" />
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ChannelsPanel({
  profiles,
  sources,
  threads,
}: {
  profiles: SourceInboxProfile[];
  sources: SourceConnectorStatus[];
  threads: SourceInboxThread[];
}) {
  const threadsById = useMemo(() => {
    const map = new Map<string, SourceInboxThread>();
    for (const thread of threads) map.set(thread.id, thread);
    return map;
  }, [threads]);

  const threadsBySource = useMemo(() => {
    const grouped = new Map<string, SourceInboxThread[]>();
    for (const thread of threads) {
      const list = grouped.get(thread.sourceId) ?? [];
      list.push(thread);
      grouped.set(thread.sourceId, list);
    }
    return grouped;
  }, [threads]);

  const { live, available } = useMemo(() => {
    const liveList: SourceConnectorStatus[] = [];
    const availableList: SourceConnectorStatus[] = [];
    for (const source of sources) {
      if (!OUTREACH_CATEGORIES.has(source.category)) continue;
      if (source.connected || source.importOnly || source.blocked || source.state === "needs_operator" || source.state === "error") {
        liveList.push(source);
      } else {
        availableList.push(source);
      }
    }
    return { live: liveList, available: availableList };
  }, [sources]);

  const cross = contactStateFromProfiles(profiles, threadsById);
  const totalContacts = cross.contacted + cross.uncontacted;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Plug className="h-4 w-4 text-foreground/65" />
              Channels
            </CardTitle>
            <p className="font-mono-ui mt-1.5 text-[0.72rem] tabular-nums text-muted-foreground">
              {compactCount(cross.contacted)} contacted · {compactCount(cross.uncontacted)} uncontacted ·{" "}
              {compactCount(totalContacts)} people · {live.length} live{available.length ? ` · ${available.length} available` : ""}
            </p>
          </div>
          <Link
            to="/config#composio"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "h-11 px-3 text-xs sm:h-9")}
            aria-label="Connect a new channel from Config"
          >
            <Plus className="h-3.5 w-3.5" />
            Connect channel
          </Link>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-7">
        {live.length > 0 && (
          <div className="divide-y divide-border/40">
            {live.map((source) => (
              <LiveChannelCard
                key={source.id}
                source={source}
                threads={threadsBySource.get(source.id) ?? []}
              />
            ))}
          </div>
        )}

        <ComposioChannelStrip />

        {available.length > 0 && (
          <div className="space-y-2.5">
            <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
              Available — connect to expand the inbox
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {available.map((source) => (
                <AvailableChannelChip key={source.id} source={source} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LiveChannelCard({
  source,
  threads,
}: {
  source: SourceConnectorStatus;
  threads: SourceInboxThread[];
}) {
  const Icon = sourceIcon(source);
  const state = contactStateFromThreads(threads);
  const totalRecords = Object.values(source.recordCounts ?? {}).reduce(
    (sum, value) => sum + (Number(value) || 0),
    0,
  );
  const tone = source.blocked
    ? "destructive"
    : source.connected
      ? "success"
      : source.importOnly
        ? "default"
        : "warning";
  const stateLabel = source.connected
    ? "live"
    : source.importOnly
      ? "import only"
      : source.blocked
        ? "blocked"
        : source.state === "needs_operator"
          ? "needs setup"
          : "error";

  return (
    <Link
      to="/config#composio"
      aria-label={`Configure ${source.label} channel — ${stateLabel}, ${compactCount(state.uncontacted)} uncontacted, ${compactCount(state.contacted)} contacted, ${compactCount(totalRecords)} records`}
      className="group flex items-start gap-3 py-3 transition-colors first:pt-0 last:pb-0 hover:bg-foreground/[0.02]"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
        {createElement(Icon, { className: "h-4 w-4" })}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-sm font-semibold text-foreground">{source.label}</span>
          <span
            className={cn(
              "font-mono-ui inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-[0.14em]",
              tone === "success" && "bg-success/12 text-success ring-1 ring-success/25",
              tone === "warning" && "bg-warning/12 text-warning ring-1 ring-warning/25",
              tone === "destructive" && "bg-destructive/12 text-destructive ring-1 ring-destructive/25",
              tone === "default" && "bg-primary/12 text-primary ring-1 ring-primary/25",
            )}
          >
            {stateLabel}
          </span>
        </div>
        {source.nextOperatorStep && !source.connected && (
          <p className="mt-1 line-clamp-2 text-[0.72rem] leading-4 text-muted-foreground">
            {source.nextOperatorStep}
          </p>
        )}
      </div>
      <div className="font-mono-ui shrink-0 self-center text-right text-[0.72rem] tabular-nums leading-tight text-muted-foreground">
        <div>
          <span className="text-warning">{compactCount(state.uncontacted)}</span> uncontacted
        </div>
        <div className="mt-0.5">
          <span className="text-success">{compactCount(state.contacted)}</span> contacted
          <span className="text-muted-foreground/60"> · </span>
          <span className="text-foreground/85">{compactCount(totalRecords)}</span> records
        </div>
      </div>
    </Link>
  );
}

function AvailableChannelChip({ source }: { source: SourceConnectorStatus }) {
  const Icon = sourceIcon(source);
  return (
    <Link
      to="/config#composio"
      aria-label={`Connect ${source.label} channel`}
      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-foreground/75 transition-colors hover:border-primary/55 hover:bg-card/80 hover:text-foreground"
    >
      {createElement(Icon, { className: "h-3 w-3" })}
      <span>{source.label}</span>
      <Plus className="h-3 w-3" />
    </Link>
  );
}

const LANE_META: Record<OutreachLane, { label: string; icon: typeof Sparkles; tone: string }> = {
  "new-outreach": { label: "New Outreach", icon: Sparkles, tone: "text-primary" },
  "hot-leads-watcher": { label: "Hot Leads Watcher", icon: Flame, tone: "text-warning" },
  "follow-ups": { label: "Follow-ups", icon: Repeat, tone: "text-success" },
};

const LEAD_TABS = [
  { id: "action-board" as const, label: "Action Board", icon: Radar },
  { id: "profiles" as const, label: "Profiles", icon: Users },
  { id: "templates" as const, label: "Templates", icon: BookText },
];

type LeadTab = (typeof LEAD_TABS)[number]["id"];

function LeadsTabBar({ active, onChange }: { active: LeadTab; onChange: (tab: LeadTab) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Leads view"
      className="inline-flex items-center gap-1 rounded-full border border-border bg-card p-1 text-xs"
    >
      {LEAD_TABS.map((tab) => {
        const Icon = tab.icon;
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`leads-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`leads-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={cn(
              "inline-flex h-9 items-center gap-1.5 rounded-full px-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/55",
              selected
                ? "bg-foreground text-background"
                : "text-foreground/70 hover:bg-foreground/5 hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

function LaneOverviewCard({
  laneOv,
  onSuggest,
  suggesting,
}: {
  laneOv: OutreachLaneOverview;
  onSuggest: (lane: OutreachLane) => void;
  suggesting: boolean;
}) {
  const meta = LANE_META[laneOv.lane];
  const Icon = meta.icon;
  return (
    <div className="rounded-2xl border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon className={cn("h-4 w-4", meta.tone)} />
          <span className="text-sm font-semibold text-foreground">{meta.label}</span>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onSuggest(laneOv.lane)}
          disabled={suggesting}
          className="h-11 px-3 text-xs sm:h-9"
          aria-label={`Suggest a new ${meta.label} variant`}
        >
          {suggesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          Suggest variant
        </Button>
      </div>

      <div className="font-mono-ui mt-3 flex items-baseline gap-3 text-[0.78rem] tabular-nums text-muted-foreground">
        <span>
          <span className="text-base font-semibold text-foreground">{laneOv.activeTemplates}</span>{" "}
          <span className="text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground/80">active</span>
        </span>
        <span className="text-foreground/35">·</span>
        <span>
          <span className="text-base font-semibold text-foreground">{laneOv.totalAttempts}</span>{" "}
          <span className="text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground/80">sent</span>
        </span>
        <span className="text-foreground/35">·</span>
        <span>
          <span className="text-base font-semibold text-foreground">
            {(laneOv.laneReplyRate * 100).toFixed(0)}%
          </span>{" "}
          <span className="text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground/80">reply</span>
        </span>
      </div>

      <div className="mt-3 space-y-1.5">
        {laneOv.best ? (
          <div className="flex items-start gap-2 text-xs">
            <Award className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
            <div className="min-w-0">
              <span className="text-foreground/65">Best: </span>
              <span className="text-foreground">{laneOv.best.name}</span>
              <span className="text-foreground/65">
                {" "}· {(laneOv.best.replyRate * 100).toFixed(0)}% / {laneOv.best.uses} sends
              </span>
            </div>
          </div>
        ) : (
          <div className="text-xs text-foreground/65">
            Need {Math.max(5 - laneOv.totalAttempts, 5)}+ more sends to rank.
          </div>
        )}
        {laneOv.worst && (
          <div className="flex items-start gap-2 text-xs">
            <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
            <div className="min-w-0">
              <span className="text-foreground/65">Weakest: </span>
              <span className="text-foreground">{laneOv.worst.name}</span>
              <span className="text-foreground/65">
                {" "}· {(laneOv.worst.replyRate * 100).toFixed(0)}% / {laneOv.worst.uses} sends
              </span>
            </div>
          </div>
        )}
        {laneOv.drift.length > 0 && (
          <div className="flex items-start gap-2 text-xs">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            <div className="text-foreground/70">
              <span className="text-foreground">{laneOv.drift[0].template.name}</span> dropped{" "}
              <span className="text-warning">{laneOv.drift[0].deltaPct}%</span> in last 30d.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PendingApprovalRow({
  template,
  onApprove,
  onReject,
  busy,
}: {
  template: OutreachTemplate;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/8 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-warning" />
          <span className="text-sm font-medium text-foreground">{template.name}</span>
          <Badge variant="warning" className="text-[10px]">
            pending approval
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onReject(template.id)}
            disabled={busy}
            className="h-9 px-3 text-xs"
            aria-label={`Reject template ${template.name}`}
          >
            <ThumbsDown className="h-3.5 w-3.5" />
            Reject
          </Button>
          <Button
            size="sm"
            onClick={() => onApprove(template.id)}
            disabled={busy}
            className="h-9 px-3 text-xs"
            aria-label={`Approve template ${template.name}`}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
            Approve
          </Button>
        </div>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
        {template.body}
      </p>
      {template.rationale && (
        <p className="mt-2 text-xs italic text-muted-foreground">
          Why: {template.rationale}
        </p>
      )}
    </div>
  );
}

function TemplatesPanel() {
  const [templates, setTemplates] = useState<OutreachTemplate[]>([]);
  const [overview, setOverview] = useState<OutreachOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Record<string, { name: string; body: string }>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [suggestingLane, setSuggestingLane] = useState<OutreachLane | null>(null);
  const [showNew, setShowNew] = useState<OutreachLane | null>(null);
  const [draft, setDraft] = useState<{ lane: OutreachLane; name: string; body: string }>({
    lane: "new-outreach",
    name: "",
    body: "",
  });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [tplRes, ovRes] = await Promise.all([
        api.getOutreachTemplates(),
        api.getOutreachOverview(),
      ]);
      setTemplates(tplRes.templates);
      setOverview(ovRes);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const suggest = async (lane: OutreachLane) => {
    setSuggestingLane(lane);
    try {
      await api.suggestOutreachTemplate({ lane });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSuggestingLane(null);
    }
  };

  const approve = async (id: string) => {
    setSavingId(id);
    try {
      await api.approveOutreachTemplate(id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };

  const reject = async (id: string) => {
    setSavingId(id);
    try {
      await api.rejectOutreachTemplate(id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };

  const grouped = useMemo(() => {
    const map: Record<OutreachLane, OutreachTemplate[]> = {
      "new-outreach": [],
      "hot-leads-watcher": [],
      "follow-ups": [],
    };
    for (const t of templates) {
      if (t.status !== "active" && t.status !== undefined && t.status !== null) continue;
      if (map[t.lane]) map[t.lane].push(t);
    }
    return map;
  }, [templates]);

  const pendingByLane = useMemo(() => {
    const map: Record<OutreachLane, OutreachTemplate[]> = {
      "new-outreach": [],
      "hot-leads-watcher": [],
      "follow-ups": [],
    };
    for (const t of templates) {
      if (t.status === "pending_approval" && map[t.lane]) map[t.lane].push(t);
    }
    return map;
  }, [templates]);

  const startEdit = (t: OutreachTemplate) => {
    setEditing((prev) => ({ ...prev, [t.id]: { name: t.name, body: t.body } }));
  };
  const cancelEdit = (id: string) => {
    setEditing((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };
  const saveEdit = async (t: OutreachTemplate) => {
    const draftEdit = editing[t.id];
    if (!draftEdit) return;
    setSavingId(t.id);
    try {
      await api.updateOutreachTemplate(t.id, { name: draftEdit.name, body: draftEdit.body });
      cancelEdit(t.id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };
  const toggleActive = async (t: OutreachTemplate) => {
    setSavingId(t.id);
    try {
      await api.updateOutreachTemplate(t.id, { active: !t.active });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };
  const remove = async (t: OutreachTemplate) => {
    if (!confirm(`Delete template "${t.name}"? Past attempts stay logged.`)) return;
    setSavingId(t.id);
    try {
      await api.deleteOutreachTemplate(t.id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };
  const createNew = async () => {
    if (!draft.name.trim() || !draft.body.trim()) return;
    setSavingId("__new__");
    try {
      await api.createOutreachTemplate({
        lane: draft.lane,
        name: draft.name.trim(),
        body: draft.body.trim(),
      });
      setDraft({ lane: draft.lane, name: "", body: "" });
      setShowNew(null);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingId(null);
    }
  };

  if (loading && templates.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-border/40 bg-card/40 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading templates…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-2xl border border-border/45 bg-card/40 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">Templates overview</div>
            <p className="mt-1 max-w-prose text-xs text-muted-foreground">
              What's working, what's not, and fresh variants for approval. Best/worst rank after{" "}
              {overview?.thresholds.minUsesForRanking ?? 5}+ sends. Drift flags templates whose 30-day
              reply rate dropped {overview?.thresholds.driftDropPct ?? 30}%+ vs all-time.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{templates.length} total · {templates.filter((t) => t.active).length} active</span>
            {(overview?.pendingTotal ?? 0) > 0 && (
              <Badge variant="warning" className="text-[10px]">
                {overview!.pendingTotal} pending
              </Badge>
            )}
          </div>
        </div>
        {error && (
          <div className="mt-3 rounded-lg border border-destructive/35 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}
      </div>

      {overview && (
        <div className="grid gap-3 lg:grid-cols-3">
          {overview.lanes.map((laneOv) => (
            <LaneOverviewCard
              key={laneOv.lane}
              laneOv={laneOv}
              onSuggest={suggest}
              suggesting={suggestingLane === laneOv.lane}
            />
          ))}
        </div>
      )}

      {(Object.keys(LANE_META) as OutreachLane[]).map((lane) => {
        const meta = LANE_META[lane];
        const Icon = meta.icon;
        const list = grouped[lane];
        return (
          <Card key={lane} className="border-border/45 bg-card/40">
            <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0 pb-3">
              <div className="flex items-center gap-2">
                <Icon className={cn("h-4 w-4", meta.tone)} />
                <CardTitle className="text-sm font-semibold text-foreground">
                  {meta.label}
                </CardTitle>
                <Badge variant="outline" className="text-[10px]">
                  {list.length} template{list.length === 1 ? "" : "s"}
                </Badge>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowNew(lane);
                  setDraft({ lane, name: "", body: "" });
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                New template
              </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 pt-0">
              {pendingByLane[lane].length > 0 && (
                <div className="space-y-2">
                  <h4 className="font-mono-ui flex items-center gap-2 text-[0.7rem] uppercase tracking-[0.12em] text-warning">
                    <Sparkles className="h-3 w-3" />
                    {pendingByLane[lane].length} variant{pendingByLane[lane].length === 1 ? "" : "s"} awaiting approval
                  </h4>
                  {pendingByLane[lane].map((p) => (
                    <PendingApprovalRow
                      key={p.id}
                      template={p}
                      onApprove={approve}
                      onReject={reject}
                      busy={savingId === p.id}
                    />
                  ))}
                </div>
              )}
              {showNew === lane && (
                <div className="rounded-xl border border-primary/35 bg-primary/5 p-3">
                  <input
                    type="text"
                    placeholder="Template name (e.g. 'Quick warm intro')"
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                    className="w-full rounded-md border border-border/60 bg-background/60 px-3 py-1.5 text-sm text-foreground outline-none focus:border-primary/60"
                  />
                  <textarea
                    placeholder="Message body. Use {first_name}, {city}, {topic}, {source}, {area}, {signal}."
                    rows={4}
                    value={draft.body}
                    onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                    className="mt-2 w-full resize-y rounded-md border border-border/60 bg-background/60 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60"
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setShowNew(null);
                        setDraft({ lane, name: "", body: "" });
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={createNew}
                      disabled={!draft.name.trim() || !draft.body.trim() || savingId === "__new__"}
                    >
                      {savingId === "__new__" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      Save template
                    </Button>
                  </div>
                </div>
              )}

              {list.length === 0 && showNew !== lane && (
                <div className="rounded-xl border border-dashed border-border/45 bg-background/20 px-4 py-6 text-center text-xs text-muted-foreground">
                  No templates yet. The agent on this lane will skip drafting until at least one exists.
                </div>
              )}

              {list.map((t) => {
                const editingDraft = editing[t.id];
                const isEditing = Boolean(editingDraft);
                return (
                  <div
                    key={t.id}
                    className={cn(
                      "rounded-xl border bg-background/30 p-3 transition-colors",
                      t.active ? "border-border/55" : "border-border/30 opacity-65",
                    )}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      {isEditing ? (
                        <input
                          type="text"
                          value={editingDraft.name}
                          onChange={(e) =>
                            setEditing((prev) => ({
                              ...prev,
                              [t.id]: { ...editingDraft, name: e.target.value },
                            }))
                          }
                          className="flex-1 min-w-0 rounded-md border border-border/60 bg-background/60 px-2 py-1 text-sm font-medium text-foreground outline-none focus:border-primary/60"
                        />
                      ) : (
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-foreground">{t.name}</span>
                          {!t.active && (
                            <Badge variant="outline" className="text-[10px]">
                              paused
                            </Badge>
                          )}
                        </div>
                      )}
                      <div className="flex items-center gap-1">
                        {isEditing ? (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => cancelEdit(t.id)}
                              disabled={savingId === t.id}
                            >
                              <XCircle className="h-3.5 w-3.5" />
                            </Button>
                            <Button size="sm" onClick={() => saveEdit(t)} disabled={savingId === t.id}>
                              {savingId === t.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Check className="h-3.5 w-3.5" />
                              )}
                              Save
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => toggleActive(t)}
                              disabled={savingId === t.id}
                              title={t.active ? "Pause this template" : "Activate this template"}
                            >
                              {t.active ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => startEdit(t)}>
                              <PencilLine className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => remove(t)}
                              disabled={savingId === t.id}
                              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                    {isEditing ? (
                      <textarea
                        rows={4}
                        value={editingDraft.body}
                        onChange={(e) =>
                          setEditing((prev) => ({
                            ...prev,
                            [t.id]: { ...editingDraft, body: e.target.value },
                          }))
                        }
                        className="mt-2 w-full resize-y rounded-md border border-border/60 bg-background/60 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60"
                      />
                    ) : (
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                        {t.body}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                      <span>Used {t.uses}×</span>
                      <span>· {t.replies} repl{t.replies === 1 ? "y" : "ies"}</span>
                      {t.uses > 0 && (
                        <span>· {(t.replyRate * 100).toFixed(0)}% reply rate</span>
                      )}
                      {t.wins > 0 && <span>· {t.wins} won</span>}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

export function RealEstateLeadsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Leads", data);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [tab, setTab] = useState<LeadTab>("action-board");

  const allThreads = useMemo(() => data.sourceInbox?.threads ?? [], [data.sourceInbox?.threads]);
  const allDrafts = useMemo(() => data.sourceInbox?.drafts ?? [], [data.sourceInbox?.drafts]);
  const allProfiles = useMemo(() => data.sourceInbox?.profiles ?? [], [data.sourceInbox?.profiles]);
  const allSources = useMemo(() => data.sourceInbox?.sources ?? [], [data.sourceInbox?.sources]);

  const filterOptions = useMemo<LeadSourceOption[]>(() => {
    const seen = new Map<string, LeadSourceOption>();
    for (const source of allSources) {
      if (!source.connected && !source.importOnly) continue;
      seen.set(source.id, {
        id: source.id,
        label: source.label,
        drafts: 0,
        profiles: 0,
        threads: 0,
      });
    }
    for (const thread of allThreads) {
      const entry = seen.get(thread.sourceId);
      if (entry) entry.threads += 1;
    }
    for (const draft of allDrafts) {
      const entry = seen.get(draft.sourceId);
      if (entry) entry.drafts += 1;
    }
    for (const profile of allProfiles) {
      for (const sourceId of profile.sourceIds) {
        const entry = seen.get(sourceId);
        if (entry) entry.profiles += 1;
      }
    }
    return Array.from(seen.values()).filter(
      (option) => option.threads > 0 || option.drafts > 0 || option.profiles > 0,
    );
  }, [allDrafts, allProfiles, allSources, allThreads]);

  const filterFn = useCallback(
    (sourceId: string) => sourceFilter === null || sourceId === sourceFilter,
    [sourceFilter],
  );

  const threads = useMemo(
    () => allThreads.filter((thread) => filterFn(thread.sourceId)),
    [allThreads, filterFn],
  );
  const drafts = useMemo(
    () => allDrafts.filter((draft) => filterFn(draft.sourceId)),
    [allDrafts, filterFn],
  );
  const profiles = useMemo(
    () => allProfiles.filter((profile) => sourceFilter === null || profile.sourceIds.includes(sourceFilter)),
    [allProfiles, sourceFilter],
  );

  const followUpJobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["lead", "outreach", "follow-up", "follow up", "buyer", "seller"]),
  );
  const leadJobIds = new Set(followUpJobs.map((job) => job.id));
  const leadSessions = data.sessions.filter((session) => {
    if (sessionMatches(session, ["lead", "outreach", "buyer", "seller", "follow-up", "follow up"])) {
      return true;
    }
    if ((session.source ?? "") === "cron" && session.id?.startsWith("cron_")) {
      const jobIdGuess = session.id.replace(/^cron_/, "").split("_", 1)[0];
      return leadJobIds.has(jobIdGuess);
    }
    return false;
  });

  const hotLeads = threads.filter((thread) => thread.heatLabel === "hot").length;
  const blockedSources = allSources.filter((source) => source.blocked);
  const pulse = useMemo(() => computeResponsePulse(threads), [threads]);

  const refresh = data.refresh;
  const shellIcon = tab === "profiles" ? Users : tab === "templates" ? BookText : Radar;
  const shellTitle =
    tab === "profiles"
      ? "Lead profiles."
      : tab === "templates"
        ? "Lead templates."
        : "Lead action board.";

  return (
    <ThreadDrawerProvider data={data}>
    <HubShell
      data={data}
      eyebrow="Lead Desk"
      icon={shellIcon}
      title={shellTitle}
    >
      <div className="flex w-full flex-col gap-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <LeadsTabBar active={tab} onChange={setTab} />
          {tab === "profiles" && (
            <span className="text-xs text-foreground/70">
              A searchable source-filtered list of people, separate from the action board.
            </span>
          )}
          {tab === "templates" && (
            <span className="text-xs text-foreground/70">
              Templates control what the agent says. Edits apply on the next lane run.
            </span>
          )}
        </div>

        {tab === "templates" ? (
          <div id="leads-panel-templates" role="tabpanel" aria-labelledby="leads-tab-templates">
            <TemplatesPanel />
          </div>
        ) : (
          <>
            <LeadFilterBar
              active={sourceFilter}
              drafts={drafts.length}
              followUps={followUpJobs.length}
              hot={hotLeads}
              onSelect={setSourceFilter}
              options={filterOptions}
              pulse={pulse}
              profiles={profiles.length}
              threads={threads.length}
            />

            {blockedSources.length > 0 && (
              <div className="rounded-2xl border border-warning/40 bg-warning/8 px-4 py-3 text-sm text-foreground">
                <div className="flex items-center gap-2 text-warning">
                  <AlertTriangle className="h-4 w-4" />
                  <span className="font-semibold">A lead source needs access.</span>
                </div>
                <div className="mt-2 space-y-1.5 text-xs text-foreground/75">
                  {blockedSources.slice(0, 3).map((source) => (
                    <div key={source.id}>
                      <span className="font-medium text-foreground">{source.label}: </span>
                      {source.nextOperatorStep || source.lastError || "Open Settings and reconnect this source."}
                    </div>
                  ))}
                  <Link
                    to="/config#composio"
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-2 h-9 px-3")}
                  >
                    Open Settings
                  </Link>
                </div>
              </div>
            )}

            {tab === "profiles" ? (
              <LeadProfilesListPage
                onChanged={refresh}
                profiles={profiles}
                threads={threads}
              />
            ) : (
              <section
                id="leads-panel-action-board"
                role="tabpanel"
                aria-labelledby="leads-tab-action-board"
                className="space-y-5"
              >
                <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
                  <DraftMessagesBoard
                    data={data}
                    drafts={drafts}
                    keyboard
                    pageSize={12}
                    showOpenThread={false}
                    title="Approve replies"
                    emptyMessage={
                      sourceFilter
                        ? "No drafts waiting from this source. Switch the filter or wait for the next agent run."
                        : "Inbox zero on drafts. New approvals will land here as your agent generates replies."
                    }
                  />

                  <div className="flex flex-col gap-4">
                    <CollapsibleSection
                      title="Hot leads"
                      count={leadThreadBuckets(threads).hot.length}
                      description="Top scored leads across every connected source."
                      defaultOpen
                    >
                      <HotLeadsList data={data} threads={threads} />
                    </CollapsibleSection>

                    <LeadPipelineTabs
                      buyers={data.sourceInbox?.privateSearchBuyers ?? []}
                      data={data}
                      threads={threads}
                    />

                    <CollapsibleSection
                      title="Recently skipped"
                      count={(data.sourceInbox?.skippedDrafts ?? []).length}
                      description="Skipped in the last 3 days. Restore brings it back to the queue."
                    >
                      <SkippedDraftsList data={data} />
                    </CollapsibleSection>
                  </div>
                </div>

                <CollapsibleSection
                  title="Channels"
                  description="Connected sources, profiles, and routing."
                >
                  <ChannelsPanel
                    profiles={data.sourceInbox?.profiles ?? []}
                    sources={allSources}
                    threads={allThreads}
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  title="Outreach lanes"
                  description="New Outreach, Hot Leads Watcher, Follow-ups, Private Searches."
                >
                  <OutreachLanesGrid cronJobs={data.cronJobs} onChanged={refresh} />
                </CollapsibleSection>

                <CollapsibleSection
                  title="Lead activity"
                  count={leadSessions.length}
                  description="What the agent just did across your inbox."
                >
                  <RecentSessions
                    title="Recent agent runs"
                    sessions={leadSessions}
                    empty="No agent activity yet. Once a lane runs, its sessions will surface here."
                  />
                </CollapsibleSection>

                <CollapsibleSection
                  title="All scheduled jobs"
                  count={followUpJobs.length}
                  description="Every lead-related cron the agent is running."
                >
                  <TimedTasks
                    jobs={followUpJobs}
                    empty="No additional schedules yet. Add custom ones from /cron."
                    title="Lead schedules"
                  />
                </CollapsibleSection>
              </section>
            )}
          </>
        )}
      </div>
    </HubShell>
    </ThreadDrawerProvider>
  );
}

// ─── Admin Hub kanban ────────────────────────────────────────────────────────
// Cards open into a side panel with collapsible per-stage checklists.

const ADMIN_STAGE_NUMBERS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as const;

type AdminSide = "listing" | "buyer";
type AdminStageNumber = (typeof ADMIN_STAGE_NUMBERS)[number];

const CANADIAN_PROVINCES: Array<{ code: string; label: string }> = [
  { code: "AB", label: "Alberta" },
  { code: "BC", label: "British Columbia" },
  { code: "MB", label: "Manitoba" },
  { code: "NB", label: "New Brunswick" },
  { code: "NL", label: "Newfoundland and Labrador" },
  { code: "NS", label: "Nova Scotia" },
  { code: "NT", label: "Northwest Territories" },
  { code: "NU", label: "Nunavut" },
  { code: "ON", label: "Ontario" },
  { code: "PEI", label: "Prince Edward Island" },
  { code: "QC", label: "Quebec" },
  { code: "SK", label: "Saskatchewan" },
  { code: "YK", label: "Yukon" },
];

type AdminStageLabel = {
  title: string;
  subtitle: string;
};

type AdminColumn = {
  stage: AdminStageNumber;
  stageNumber: string;
  stageLabel?: string;
  labels: Record<AdminSide, AdminStageLabel>;
};

type AdminChecklistItem = { id: string; label: string };

type AdminPhaseAutomationInfo = {
  agents: string[];
  background: string[];
  moveSignal: string;
  approvalGate?: string;
};

type AdminEnumField =
  | "signing_authority"
  | "fintrac_form_type"
  | "listing_track"
  | "property_subtype"
  | "estate_status"
  | "transaction_type"
  | "listing_type";

type AdminToggleField =
  | "pep"
  | "tenanted"
  | "poa_signing"
  | "corporate"
  | "has_suite"
  | "multiple_offers"
  | "family_member"
  | "dual_rep"
  | "unrepresented_other_side"
  | "lockbox"
  | "delayed_offer"
  | "sale_of_buyers_property";

type AdminConditionField = AdminEnumField | AdminToggleField;
type AdminConditionValue = string | boolean | null;
type AdminCompletedByStage = Partial<Record<AdminStageNumber, Record<string, boolean>>>;

type AdminSourceContext = {
  profileName?: string;
  latestText?: string;
  latestAt?: string;
  heatLabel?: string;
  heatScore?: number;
  sources: string[];
  channels: string[];
  contactIds: string[];
  conversationIds: string[];
  verifiers: SourceInboxProfileVerifier[];
  rejectedContactId?: string;
};

type AdminCard = {
  id: string;
  side: AdminSide;
  stage: AdminStageNumber;
  client: string;
  contactInitials: string;
  property?: string;
  nextLabel?: string;
  nextDate?: string;
  daysOut?: number;
  pinnedTop25?: boolean;
  completedByStage?: AdminCompletedByStage;
  conditions?: Partial<Record<AdminConditionField, AdminConditionValue>>;
  sourceContext?: AdminSourceContext;
};

const ADMIN_SIDE_LABELS: Record<AdminSide, { title: string; description: string }> = {
  listing: {
    title: "Listing Admin",
    description: "CMA through closed file",
  },
  buyer: {
    title: "Buyer Admin",
    description: "Walkthrough through one-week follow-up",
  },
};

const ADMIN_COLUMNS: AdminColumn[] = [
  {
    stage: 0,
    stageNumber: "S0",
    stageLabel: "Commitment",
    labels: {
      listing: { title: "CMA / Prospect", subtitle: "Appointment + valuation" },
      buyer: { title: "Intake", subtitle: "Profile + budget" },
    },
  },
  {
    stage: 1,
    stageNumber: "S1",
    stageLabel: "Intake",
    labels: {
      listing: { title: "Listing Intake", subtitle: "Collect info for MLC" },
      buyer: { title: "Search Setup", subtitle: "Criteria + MLS" },
    },
  },
  {
    stage: 2,
    stageNumber: "S2",
    stageLabel: "Docs",
    labels: {
      listing: { title: "MLC / Documents", subtitle: "Create docs + signing" },
      buyer: { title: "Tours", subtitle: "Route + notes" },
    },
  },
  {
    stage: 3,
    stageNumber: "S3",
    stageLabel: "Photos",
    labels: {
      listing: { title: "Photos Ready", subtitle: "Photo capture + review" },
      buyer: { title: "Follow-Up", subtitle: "Feedback + fit" },
    },
  },
  {
    stage: 4,
    stageNumber: "S4",
    stageLabel: "MLS",
    labels: {
      listing: { title: "MLS Entry", subtitle: "Listing build + launch prep" },
      buyer: { title: "Offer Prep", subtitle: "Comps + CPS" },
    },
  },
  {
    stage: 5,
    stageNumber: "S5",
    stageLabel: "Live",
    labels: {
      listing: { title: "Listing Live / Marketing", subtitle: "MLS live + seller updates" },
      buyer: { title: "Accepted", subtitle: "Lender + docs" },
    },
  },
  {
    stage: 6,
    stageNumber: "S6",
    stageLabel: "Contract",
    labels: {
      listing: { title: "Accepted Offer", subtitle: "Contract review + dates" },
      buyer: { title: "Conditions", subtitle: "Inspection + strata" },
    },
  },
  {
    stage: 7,
    stageNumber: "S7",
    stageLabel: "Subjects",
    labels: {
      listing: { title: "Subject Removal", subtitle: "Subjects + lawyer package" },
      buyer: { title: "Subjects Off", subtitle: "Deposit + dates" },
    },
  },
  {
    stage: 8,
    stageNumber: "S8",
    stageLabel: "Closing",
    labels: {
      listing: { title: "Closing", subtitle: "Conveyance + possession" },
      buyer: { title: "Closing", subtitle: "Lawyer + walkthrough" },
    },
  },
  {
    stage: 9,
    stageNumber: "S9",
    stageLabel: "Closed",
    labels: {
      listing: { title: "Closed", subtitle: "Archive + nurture" },
      buyer: { title: "Possession", subtitle: "Gift + follow-up" },
    },
  },
];

const ADMIN_PHASE_AUTOMATIONS: Record<AdminSide, Record<AdminStageNumber, AdminPhaseAutomationInfo>> = {
  listing: {
    0: {
      agents: ["seller-package", "cma"],
      background: [],
      moveSignal: "CMA ready + seller package sent",
      approvalGate: "approve package/draft",
    },
    1: {
      agents: ["mlc", "deal-matcher"],
      background: [],
      moveSignal: "listing intake complete",
      approvalGate: "confirm price + launch plan",
    },
    2: {
      agents: ["mlc", "signing-package", "skyslope-sync"],
      background: ["gmail-doc-router"],
      moveSignal: "signed MLC + docs verified",
      approvalGate: "approve signing/docs",
    },
    3: {
      agents: ["photo-cleanup"],
      background: [],
      moveSignal: "photos approved",
      approvalGate: "human photo approval",
    },
    4: {
      agents: ["property-lookup", "listing-build"],
      background: [],
      moveSignal: "MLS package approved",
      approvalGate: "approve MLS copy/package",
    },
    5: {
      agents: ["marketing"],
      background: ["seller-update"],
      moveSignal: "offer accepted",
      approvalGate: "approve outgoing drafts",
    },
    6: {
      agents: ["offer-review"],
      background: ["gmail-doc-router"],
      moveSignal: "accepted-offer dates verified",
      approvalGate: "review offer terms",
    },
    7: {
      agents: ["subject-removal", "signing-package"],
      background: ["gmail-doc-router"],
      moveSignal: "subjects removed + deposit verified",
      approvalGate: "confirm subject removal",
    },
    8: {
      agents: ["closing-admin"],
      background: ["gmail-doc-router"],
      moveSignal: "closing package complete",
      approvalGate: "confirm conveyance package",
    },
    9: {
      agents: ["skyslope-sync", "marketing"],
      background: [],
      moveSignal: "file closed + nurture queued",
      approvalGate: "approve closeout",
    },
  },
  buyer: {
    0: { agents: [], background: [], moveSignal: "profile verified" },
    1: { agents: [], background: [], moveSignal: "search criteria ready" },
    2: { agents: [], background: [], moveSignal: "showing notes complete" },
    3: { agents: [], background: [], moveSignal: "follow-up complete" },
    4: { agents: [], background: [], moveSignal: "offer package ready" },
    5: { agents: [], background: [], moveSignal: "accepted-offer checklist complete" },
    6: { agents: [], background: [], moveSignal: "conditions tracked" },
    7: { agents: [], background: [], moveSignal: "subjects removed" },
    8: { agents: [], background: [], moveSignal: "closing checklist complete" },
    9: { agents: [], background: [], moveSignal: "possession follow-up queued" },
  },
};

// Per-stage checklist catalog. Card state (completedByStage) overlays this.
const ADMIN_STAGE_CHECKLISTS: Record<AdminSide, Record<AdminStageNumber, AdminChecklistItem[]>> = {
  listing: {
    0: [
    { id: "draft-cma-followup", label: "Draft CMA follow-up message" },
    { id: "pricing-recap", label: "Send pricing recap to seller" },
    { id: "missing-info-list", label: "Identify info needed before listing paperwork" },
    ],
    1: [
    { id: "workflow_stage_1_complete", label: "Listing details verified" },
    ],
    2: [
    { id: "workflow_title_ordered", label: "Title ordered" },
    { id: "workflow_sign_ordered", label: "Sign ordered" },
    { id: "workflow_stage_2_complete", label: "Signed docs verified" },
    ],
    3: [
    { id: "workflow_photos_in_drive", label: "Photos in Drive" },
    { id: "workflow_jeff_photo_review", label: "Photo review complete" },
    { id: "workflow_stage_3_complete", label: "Photos approved for listing" },
    ],
    4: [
    { id: "workflow_evalue_bc_age_verified", label: "eValue BC age verified" },
    { id: "workflow_listing_description_approved", label: "Listing description approved" },
    { id: "workflow_feature_sheet_uploaded", label: "Feature sheet uploaded" },
    { id: "workflow_ai_edited_photos_labelled", label: "AI-edited photos labelled" },
    { id: "workflow_stage_4_complete", label: "MLS package approved" },
    ],
    5: [
    { id: "workflow_just_listed_blast_sent", label: "Just listed blast sent" },
    { id: "workflow_social_posts_published", label: "Social posts published" },
    { id: "workflow_flodesk_mailout_sent", label: "Flodesk mailout sent" },
    { id: "workflow_lofty_text_blast_sent", label: "Lofty text blast sent" },
    { id: "workflow_stage_5_complete", label: "Live marketing checklist complete" },
    ],
    6: [
    { id: "workflow_within_24hrs_contract_reviewed", label: "Contract reviewed within 24 hours" },
    { id: "workflow_email_buyer_accepted_offer_checklist_sent", label: "Accepted-offer checklist email sent" },
    { id: "workflow_fintrac_drivers_occupation_employer_captured", label: "FINTRAC details captured" },
    { id: "workflow_calendar_dates_added", label: "Calendar dates added" },
    { id: "workflow_moving_checklist_sent", label: "Moving checklist sent" },
    { id: "workflow_stage_6_complete", label: "Accepted-offer admin verified" },
    ],
    7: [
    { id: "workflow_subject_removal_form_sent", label: "Subject removal form sent" },
    { id: "workflow_title_charges_verified", label: "Title charges verified" },
    { id: "workflow_bir_pds_received", label: "BIR + PDS received" },
    { id: "workflow_lawyer_info_requested", label: "Lawyer info requested" },
    { id: "workflow_stage_7_complete", label: "Subject removal verified" },
    ],
    8: [
    { id: "workflow_conveyancer_package_sent", label: "Conveyancer package sent" },
    { id: "workflow_down_payment_to_trust", label: "Down payment to trust" },
    { id: "workflow_mortgage_instructions_received", label: "Mortgage instructions received" },
    { id: "workflow_insurance_binder_confirmed", label: "Insurance binder confirmed" },
    { id: "workflow_client_signed_lawyer", label: "Client signed at lawyer" },
    { id: "workflow_funds_released", label: "Funds released" },
    { id: "workflow_stage_8_complete", label: "Closing admin verified" },
    ],
    9: [
    { id: "workflow_commission_submitted", label: "Commission submitted" },
    { id: "workflow_skyslope_deal_closed", label: "SkySlope deal closed" },
    { id: "workflow_sold_update_sent", label: "Sold update sent" },
    { id: "workflow_closing_gift_sent", label: "Closing gift sent" },
    { id: "workflow_review_requested", label: "Review requested" },
    { id: "workflow_stage_9_complete", label: "Closed file archived" },
    ],
  },
  buyer: {
    0: [
    { id: "buyer-profile", label: "Buyer profile (budget, financing, areas, beds, must-haves)" },
    { id: "search-criteria", label: "MLS / Lofty search filter built" },
    ],
    1: [
    { id: "shortlist", label: "Property shortlist + ranked-fit" },
    { id: "showing-route", label: "Showing route + itinerary" },
    { id: "preview-notes", label: "Preview notes per property" },
    ],
    2: [
    { id: "followup-draft", label: "Per-showing follow-up draft" },
    { id: "feedback-summary", label: "Feedback summary (liked / disliked / dealbreakers)" },
    ],
    3: [
    { id: "criteria-update", label: "Buyer criteria updated" },
    { id: "comp-pull", label: "Comparable sales pulled" },
    { id: "cps-checklist", label: "CPS input checklist + offer strategy" },
    ],
    4: [
    { id: "lender-paperwork", label: "Lender paperwork sent" },
    { id: "accepted-offer-checklist", label: "Accepted-offer checklist run" },
    { id: "doc-list", label: "Doc list (CPS, addenda, disclosures, deposit receipt)" },
    ],
    5: [
    { id: "inspection-booked", label: "Inspection booked" },
    { id: "insurance-deadline", label: "Insurance deadline tracked" },
    { id: "strata-review", label: "Strata review (if applicable)" },
    ],
    6: [
    { id: "deposit-due", label: "Deposit due date tracked" },
    { id: "lawyer-info", label: "Lawyer / conveyancer info captured" },
    { id: "skyslope-docs", label: "SkySlope missing-doc list cleared" },
    ],
    7: [
    { id: "subjects-removed", label: "All subjects removed" },
    { id: "deposit-received", label: "Deposit received" },
    { id: "completion-locked", label: "Completion + possession dates locked" },
    ],
    8: [
    { id: "lawyer-final-docs", label: "Final docs forwarded to lawyer" },
    { id: "completion-checklist", label: "Completion checklist complete" },
    { id: "final-walkthrough", label: "Final walkthrough scheduled" },
    ],
    9: [
    { id: "utility-reminder", label: "Utility / change-of-address reminder sent" },
    { id: "key-handoff", label: "Key handoff coordinated" },
    { id: "closing-gift", label: "Closing gift sent" },
    { id: "thank-you", label: "Thank-you / review / referral drafts queued" },
    { id: "one-week-followup", label: "One-week-after follow-up scheduled" },
    { id: "anniversary", label: "Anniversary reminder added" },
    ],
  },
};

const ADMIN_ENUM_CONDITIONS: Array<{
  field: AdminEnumField;
  label: string;
  options: Array<{ value: string; label: string }>;
}> = [
  {
    field: "signing_authority",
    label: "Signing authority",
    options: [
      { value: "seller", label: "Seller" },
      { value: "buyer", label: "Buyer" },
      { value: "both", label: "Both clients" },
      { value: "poa", label: "Power of attorney" },
      { value: "corporate", label: "Corporate signer" },
      { value: "estate_executor", label: "Estate executor" },
    ],
  },
  {
    field: "fintrac_form_type",
    label: "FINTRAC form type",
    options: [
      { value: "individual", label: "Individual" },
      { value: "corporation", label: "Corporation" },
      { value: "estate", label: "Estate" },
      { value: "poa", label: "Power of attorney" },
      { value: "third_party", label: "Third party" },
    ],
  },
  {
    field: "listing_track",
    label: "Listing track",
    options: [
      { value: "standard", label: "Standard" },
      { value: "rush", label: "Rush" },
      { value: "pre_market", label: "Pre-market" },
      { value: "relist", label: "Relist" },
    ],
  },
  {
    field: "property_subtype",
    label: "Property subtype",
    options: [
      { value: "detached", label: "Detached" },
      { value: "townhouse", label: "Townhouse" },
      { value: "condo", label: "Condo" },
      { value: "strata", label: "Strata" },
      { value: "acreage", label: "Acreage" },
      { value: "land", label: "Land" },
      { value: "multifamily", label: "Multifamily" },
    ],
  },
  {
    field: "estate_status",
    label: "Estate status",
    options: [
      { value: "none", label: "None" },
      { value: "estate_sale", label: "Estate sale" },
      { value: "probate_pending", label: "Probate pending" },
      { value: "probate_granted", label: "Probate granted" },
    ],
  },
  {
    field: "transaction_type",
    label: "Transaction type",
    options: [
      { value: "residential", label: "Residential" },
      { value: "commercial", label: "Commercial" },
      { value: "referral", label: "Referral" },
      { value: "assignment", label: "Assignment" },
    ],
  },
  {
    field: "listing_type",
    label: "Listing type",
    options: [
      { value: "mls", label: "MLS" },
      { value: "exclusive", label: "Exclusive" },
      { value: "coming_soon", label: "Coming soon" },
      { value: "mere_posting", label: "Mere posting" },
    ],
  },
];

const ADMIN_TOGGLE_CONDITIONS: Array<{ field: AdminToggleField; label: string }> = [
  { field: "pep", label: "PEP" },
  { field: "tenanted", label: "Tenanted" },
  { field: "poa_signing", label: "POA signing" },
  { field: "corporate", label: "Corporate" },
  { field: "has_suite", label: "Has suite" },
  { field: "multiple_offers", label: "Multiple offers" },
  { field: "family_member", label: "Family member" },
  { field: "dual_rep", label: "Dual representation" },
  { field: "unrepresented_other_side", label: "Unrepresented other side" },
  { field: "lockbox", label: "Lockbox" },
  { field: "delayed_offer", label: "Delayed offer" },
  { field: "sale_of_buyers_property", label: "Sale of buyer's property" },
];

const ADMIN_CONDITION_FIELD_SET = new Set<string>([
  ...ADMIN_ENUM_CONDITIONS.map((item) => item.field),
  ...ADMIN_TOGGLE_CONDITIONS.map((item) => item.field),
]);

const ADMIN_DEAL_CONDITION_API_KEYS: Record<AdminConditionField, keyof AdminDeal> = {
  signing_authority: "signingAuthority",
  fintrac_form_type: "fintracFormType",
  listing_track: "listingTrack",
  property_subtype: "propertySubtype",
  estate_status: "estateStatus",
  transaction_type: "transactionType",
  listing_type: "listingType",
  pep: "pep",
  tenanted: "tenanted",
  poa_signing: "poaSigning",
  corporate: "corporate",
  has_suite: "hasSuite",
  multiple_offers: "multipleOffers",
  family_member: "familyMember",
  dual_rep: "dualRep",
  unrepresented_other_side: "unrepresentedOtherSide",
  lockbox: "lockbox",
  delayed_offer: "delayedOffer",
  sale_of_buyers_property: "saleOfBuyersProperty",
};

function isAdminConditionField(field: string): field is AdminConditionField {
  return ADMIN_CONDITION_FIELD_SET.has(field);
}

function isAdminSide(value: unknown): value is AdminSide {
  return value === "listing" || value === "buyer";
}

function toAdminStage(value: unknown): AdminStageNumber {
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isInteger(numeric) && ADMIN_STAGE_NUMBERS.includes(numeric as AdminStageNumber)) {
    return numeric as AdminStageNumber;
  }
  return 0;
}

function adminStageDefinition(stage: AdminStageNumber): AdminColumn {
  return ADMIN_COLUMNS.find((column) => column.stage === stage) ?? ADMIN_COLUMNS[0];
}

function adminStageLabel(side: AdminSide, stage: AdminStageNumber): AdminStageLabel {
  return adminStageDefinition(stage).labels[side];
}

function adminStageChecklist(side: AdminSide, stage: AdminStageNumber): AdminChecklistItem[] {
  return ADMIN_STAGE_CHECKLISTS[side][stage];
}

function adminPhaseAutomation(side: AdminSide, stage: AdminStageNumber): AdminPhaseAutomationInfo {
  return ADMIN_PHASE_AUTOMATIONS[side][stage];
}

function adminNextStage(card: AdminCard): AdminStageNumber | null {
  if (card.stage >= 9) return null;
  return (card.stage + 1) as AdminStageNumber;
}

function getStageProgress(card: AdminCard, stage: AdminStageNumber): { done: number; total: number; nextItem?: string } {
  const items = adminStageChecklist(card.side, stage);
  const completed = card.completedByStage?.[stage] ?? {};
  let done = 0;
  let nextItem: string | undefined;
  for (const item of items) {
    if (completed[item.id]) done++;
    else if (!nextItem) nextItem = item.label;
  }
  return { done, total: items.length, nextItem };
}

function getCardProgress(card: AdminCard): { done: number; total: number; nextItem?: string } {
  return getStageProgress(card, card.stage);
}

function adminChecklistStageForItem(side: AdminSide, itemId: string): AdminStageNumber | null {
  for (const stage of ADMIN_STAGE_NUMBERS) {
    if (adminStageChecklist(side, stage).some((item) => item.id === itemId)) {
      return stage;
    }
  }
  return null;
}

function initialsFromTitle(title: string): string {
  const words = title
    .replace(/[^a-z0-9\s&]/gi, " ")
    .split(/\s+/)
    .filter(Boolean);
  const initials = words
    .slice(0, 2)
    .map((word) => word.slice(0, 1).toUpperCase())
    .join("");
  return initials || "AD";
}

function adminConditionValueFromDeal(deal: AdminDeal, field: AdminConditionField): AdminConditionValue {
  const value = deal[ADMIN_DEAL_CONDITION_API_KEYS[field]];
  if (value === undefined) return null;
  if (typeof value === "string" || typeof value === "boolean" || value == null) {
    return value;
  }
  return String(value);
}

function adminConditionsFromDeal(deal: AdminDeal): Partial<Record<AdminConditionField, AdminConditionValue>> {
  const conditions: Partial<Record<AdminConditionField, AdminConditionValue>> = {};
  for (const field of ADMIN_CONDITION_FIELD_SET) {
    if (isAdminConditionField(field)) {
      conditions[field] = adminConditionValueFromDeal(deal, field);
    }
  }
  return conditions;
}

function completedStagesFromDeal(deal: AdminDeal, side: AdminSide): AdminCompletedByStage {
  const completed: AdminCompletedByStage = {};
  const extraToggles = deal.extraToggles ?? {};
  for (const stage of ADMIN_STAGE_NUMBERS) {
    const stageCompleted: Record<string, boolean> = {};
    for (const item of adminStageChecklist(side, stage)) {
      if (extraToggles[item.id] === true) {
        stageCompleted[item.id] = true;
      }
    }
    if (Object.keys(stageCompleted).length > 0) {
      completed[stage] = stageCompleted;
    }
  }
  return completed;
}

function adminStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean)
    .slice(0, 6);
}

function adminStringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function adminNumberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function adminVerifierList(value: unknown): SourceInboxProfileVerifier[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const kind = adminStringValue(record.kind);
      const verifierValue = adminStringValue(record.value);
      const key = adminStringValue(record.key);
      if (!kind || !verifierValue || !key) return null;
      return { kind, value: verifierValue, key };
    })
    .filter((item): item is SourceInboxProfileVerifier => item !== null)
    .slice(0, 6);
}

function adminSourceContextFromDeal(deal: AdminDeal): AdminSourceContext | undefined {
  const extra = deal.extraToggles ?? {};
  if (!adminStringValue(extra.sourceProfileId) && extra.workflow !== "cma") return undefined;
  return {
    profileName: adminStringValue(extra.profileDisplayName) ?? adminStringValue(extra.sourceProfileName),
    latestText: adminStringValue(extra.profileLatestText) ?? adminStringValue(extra.sourceLatestText),
    latestAt: adminStringValue(extra.profileLatestAt) ?? adminStringValue(extra.sourceLatestAt),
    heatLabel: adminStringValue(extra.profileHeatLabel) ?? adminStringValue(extra.sourceHeatLabel),
    heatScore: adminNumberValue(extra.profileHeatScore) ?? adminNumberValue(extra.sourceHeatScore),
    sources: adminStringList(extra.profileSources).length
      ? adminStringList(extra.profileSources)
      : adminStringList(extra.sourceLabels),
    channels: adminStringList(extra.profileChannels).length
      ? adminStringList(extra.profileChannels)
      : adminStringList(extra.sourceChannels),
    contactIds: adminStringList(extra.profileContactIds).length
      ? adminStringList(extra.profileContactIds)
      : adminStringList(extra.sourceContactIds),
    conversationIds: adminStringList(extra.profileConversationIds).length
      ? adminStringList(extra.profileConversationIds)
      : adminStringList(extra.sourceConversationIds),
    verifiers: adminVerifierList(extra.profileVerifiers).length
      ? adminVerifierList(extra.profileVerifiers)
      : adminVerifierList(extra.sourceVerifiers),
    rejectedContactId: adminStringValue(extra.sourcePrimaryContactIdRejected),
  };
}

function adminCardFromDeal(deal: AdminDeal): AdminCard {
  const side = isAdminSide(deal.side) ? deal.side : "listing";
  const stage = toAdminStage(deal.currentStage);
  const stageLabel = adminStageLabel(side, stage);
  const property = deal.listingAddress || (deal.province ? `${deal.province} deal` : undefined);
  return {
    id: deal.id,
    side,
    stage,
    client: deal.title || "Untitled deal",
    contactInitials: initialsFromTitle(deal.title || "Admin deal"),
    property,
    nextLabel: stageLabel.title,
    pinnedTop25: deal.extraToggles?.pinnedTop25 === true || deal.extraToggles?.top25 === true,
    completedByStage: completedStagesFromDeal(deal, side),
    conditions: adminConditionsFromDeal(deal),
    sourceContext: adminSourceContextFromDeal(deal),
  };
}

function applyLocalDealField(card: AdminCard, field: string, value: AdminConditionValue): AdminCard {
  if (isAdminConditionField(field)) {
    return {
      ...card,
      conditions: {
        ...(card.conditions ?? {}),
        [field]: value,
      },
    };
  }

  const stage = adminChecklistStageForItem(card.side, field);
  if (stage == null) return card;

  const currentStageState = card.completedByStage?.[stage] ?? {};
  const nextStageState = { ...currentStageState };
  if (value === true) nextStageState[field] = true;
  else delete nextStageState[field];

  return {
    ...card,
    completedByStage: {
      ...(card.completedByStage ?? {}),
      [stage]: nextStageState,
    },
  };
}

function replaceCardFromDeal(cards: AdminCard[], deal: AdminDeal): AdminCard[] {
  const nextCard = adminCardFromDeal(deal);
  return cards.map((card) => (card.id === nextCard.id ? nextCard : card));
}

function isApiNotFound(error: unknown): boolean {
  return error instanceof Error && /^404\b/.test(error.message);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function useAdminSetup(): {
  setup: AdminSetupSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setSetup: (setup: AdminSetupSnapshot) => void;
} {
  const [setup, setSetup] = useState<AdminSetupSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSetup(await api.getAdminSetup());
    } catch (err) {
      setError(errorMessage(err, "Admin setup failed"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { setup, loading, error, refresh, setSetup };
}

function AdminSetupField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[0.72rem] font-medium text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-10 w-full rounded-xl border border-border/60 bg-background/55 px-3 text-[0.86rem] text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
      />
    </label>
  );
}

function AdminSetupLaunch({
  setup,
  onSetupUpdated,
}: {
  setup: AdminSetupSnapshot;
  onSetupUpdated: (setup: AdminSetupSnapshot) => void;
}) {
  const [draft, setDraft] = useState<AdminSetupDraft>(() => adminSetupDraftFromSnapshot(setup));
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    setDraft(adminSetupDraftFromSnapshot(setup));
  }, [setup]);

  const updateDraft = useCallback(
    (field: keyof AdminSetupDraft, value: string) => {
      setDraft((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const submit = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
      onSetupUpdated(updated);
      setSavedMessage(
        updated.missingRequiredKeys.length === 0
          ? "Saved. Verify connections before Admin can start."
          : "Saved. Finish and verify the missing setup items before Admin can start.",
      );
    } catch (err) {
      setError(errorMessage(err, "Save admin setup failed"));
    } finally {
      setSaving(false);
    }
  }, [draft, onSetupUpdated]);

  const verify = useCallback(async () => {
    setVerifying(true);
    setError(null);
    setSavedMessage(null);
    try {
      await api.updateAdminSetup(adminSetupPayloadFromDraft(draft));
      const verified = await api.verifyAdminSetup();
      if (verified.missingRequiredKeys.length === 0) {
        const completed = await api.completeAdminSetup();
        onSetupUpdated(completed);
        setSavedMessage("Admin setup is verified and ready.");
      } else {
        onSetupUpdated(verified);
        setSavedMessage("Checked live connectors. Finish the missing setup items before Admin can start.");
      }
    } catch (err) {
      setError(errorMessage(err, "Verify admin setup failed"));
    } finally {
      setVerifying(false);
    }
  }, [draft, onSetupUpdated]);

  const missingLabels = useMemo(() => {
    const labels = new Map(setup.items.map((item) => [item.key, item.label]));
    return setup.missingRequiredKeys.map((key) => labels.get(key) ?? key);
  }, [setup.items, setup.missingRequiredKeys]);
  const readinessBlockers = useMemo(
    () => (setup.readiness ?? []).filter((item) => !item.ready),
    [setup.readiness],
  );
  const verificationWarnings = setup.verificationWarnings ?? [];

  return (
    <div className="space-y-4 rounded-2xl border border-primary/30 bg-primary/5 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.16)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[0.78rem] font-semibold uppercase tracking-[0.16em] text-primary">
            <ShieldCheck className="h-4 w-4" />
            Admin setup required
          </div>
          <h2 className="mt-2 text-xl font-semibold tracking-normal text-foreground">Connect the admin operating stack first.</h2>
          <p className="mt-1 max-w-3xl text-[0.86rem] leading-6 text-muted-foreground">
            Admin automations stay paused until the realtor profile, province package, accounts, providers, approval lane, and regional memory are configured.
          </p>
        </div>
        <div className="min-w-[10rem] rounded-xl border border-border/60 bg-background/45 p-3">
          <div className="font-mono-ui text-[0.7rem] uppercase tracking-[0.14em] text-muted-foreground">Readiness</div>
          <div className="mt-1 text-2xl font-semibold text-foreground">{setup.completionPct}%</div>
          <div className="mt-2 h-1.5 rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${setup.completionPct}%` }} />
          </div>
        </div>
      </div>

      {missingLabels.length > 0 && (
        <div className="rounded-xl border border-warning/35 bg-warning/10 px-3 py-2 text-[0.8rem] text-warning">
          Missing: {missingLabels.join(", ")}
        </div>
      )}
      {readinessBlockers.length > 0 && (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {readinessBlockers.slice(0, 9).map((item) => (
            <div
              key={item.key}
              className="min-w-0 rounded-xl border border-border/60 bg-background/45 px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[0.78rem] font-semibold text-foreground">{item.label}</span>
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-2 py-0.5 font-mono-ui text-[0.62rem] uppercase tracking-[0.1em]",
                    item.state === "needs_runtime_verification"
                      ? "border-warning/35 bg-warning/10 text-warning"
                      : "border-border/60 bg-muted/30 text-muted-foreground",
                  )}
                >
                  {item.state.replaceAll("_", " ")}
                </span>
              </div>
              <p className="mt-1 text-[0.74rem] leading-5 text-muted-foreground">{item.action}</p>
            </div>
          ))}
          {readinessBlockers.length > 9 && (
            <div className="rounded-xl border border-border/60 bg-background/45 px-3 py-2 text-[0.76rem] leading-5 text-muted-foreground">
              {readinessBlockers.length - 9} more setup item{readinessBlockers.length - 9 === 1 ? "" : "s"} still need attention.
            </div>
          )}
        </div>
      )}
      {verificationWarnings.length > 0 && (
        <div className="rounded-xl border border-border/60 bg-background/45 px-3 py-2 text-[0.78rem] leading-5 text-muted-foreground">
          {verificationWarnings.join(" ")}
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-3">
        <AdminSetupField label="Realtor legal name" value={draft.realtorLegalName} onChange={(v) => updateDraft("realtorLegalName", v)} />
        <AdminSetupField label="Licensed / public name" value={draft.licenseName} onChange={(v) => updateDraft("licenseName", v)} />
        <AdminSetupField label="Brokerage" value={draft.brokerageName} onChange={(v) => updateDraft("brokerageName", v)} />
        <AdminSetupField label="Team / PREC" value={draft.teamName} onChange={(v) => updateDraft("teamName", v)} />
        <AdminSetupField label="Province" value={draft.province} onChange={(v) => updateDraft("province", v.toUpperCase())} placeholder="BC, AB, ON..." />
        <AdminSetupField label="Market" value={draft.market} onChange={(v) => updateDraft("market", v)} placeholder="Kamloops, Calgary..." />
        <AdminSetupField label="Board memberships" value={draft.boardMemberships} onChange={(v) => updateDraft("boardMemberships", v)} placeholder="AOIR, FVREB..." />
        <AdminSetupField label="Managing broker/admin email" value={draft.managingBrokerEmail} onChange={(v) => updateDraft("managingBrokerEmail", v)} />
        <AdminSetupField label="Admin approval channel" value={draft.approvalChannel} onChange={(v) => updateDraft("approvalChannel", v)} placeholder="Telegram Admin bot/lane" />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <AdminSetupField label="Email" value={draft.emailProvider} onChange={(v) => updateDraft("emailProvider", v)} placeholder="Gmail / Outlook account" />
        <AdminSetupField label="Calendar" value={draft.calendarProvider} onChange={(v) => updateDraft("calendarProvider", v)} placeholder="Google Calendar / Outlook" />
        <AdminSetupField label="Cloud drive" value={draft.driveProvider} onChange={(v) => updateDraft("driveProvider", v)} placeholder="Google Drive / SharePoint" />
        <AdminSetupField label="CRM" value={draft.crmProvider} onChange={(v) => updateDraft("crmProvider", v)} placeholder="Lofty, kvCORE, BoldTrail..." />
        <AdminSetupField label="MLS / board portal" value={draft.mlsProvider} onChange={(v) => updateDraft("mlsProvider", v)} placeholder="Matrix, Xposure, Paragon..." />
        <AdminSetupField label="Forms provider" value={draft.formsProvider} onChange={(v) => updateDraft("formsProvider", v)} placeholder="WEBForms / TransactionDesk" />
        <AdminSetupField label="Signing provider" value={draft.signingProvider} onChange={(v) => updateDraft("signingProvider", v)} placeholder="DigiSign / DocuSign" />
        <AdminSetupField label="Compliance platform" value={draft.complianceProvider} onChange={(v) => updateDraft("complianceProvider", v)} placeholder="SkySlope / Lone Wolf" />
        <AdminSetupField label="Showing platform" value={draft.showingProvider} onChange={(v) => updateDraft("showingProvider", v)} placeholder="ShowingTime / BrokerBay" />
        <AdminSetupField label="Photo processing" value={draft.photoProcessingProvider} onChange={(v) => updateDraft("photoProcessingProvider", v)} placeholder="Drive + Nano Banana / Higgsfield" />
        <AdminSetupField label="FINTRAC / ID workflow" value={draft.fintracProvider} onChange={(v) => updateDraft("fintracProvider", v)} placeholder="Fintracker / manual FIN# capture" />
        <AdminSetupField label="Folder pattern" value={draft.defaultFolderPattern} onChange={(v) => updateDraft("defaultFolderPattern", v)} />
        <AdminSetupField label="Commission / service notes" value={draft.commissionNotes} onChange={(v) => updateDraft("commissionNotes", v)} />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <AdminSetupField label="MLS login URL" value={draft.mlsLoginUrl} onChange={(v) => updateDraft("mlsLoginUrl", v)} placeholder="https://..." />
        <AdminSetupField label="MLS credential ref" value={draft.mlsCredentialRef} onChange={(v) => updateDraft("mlsCredentialRef", v)} placeholder="Saved browser / keychain / 1Password" />
        <AdminSetupField label="SkySlope login URL" value={draft.complianceLoginUrl} onChange={(v) => updateDraft("complianceLoginUrl", v)} placeholder="https://..." />
        <AdminSetupField label="SkySlope credential ref" value={draft.complianceCredentialRef} onChange={(v) => updateDraft("complianceCredentialRef", v)} placeholder="Saved browser / keychain / 1Password" />
        <AdminSetupField label="Showing login URL" value={draft.showingLoginUrl} onChange={(v) => updateDraft("showingLoginUrl", v)} placeholder="https://..." />
        <AdminSetupField label="Showing credential ref" value={draft.showingCredentialRef} onChange={(v) => updateDraft("showingCredentialRef", v)} placeholder="Saved browser / keychain / 1Password" />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <label className="block min-w-0">
          <span className="mb-1 block text-[0.72rem] font-medium text-muted-foreground">Browser-use notes</span>
          <textarea
            value={draft.browserWorkflowNotes}
            onChange={(event) => updateDraft("browserWorkflowNotes", event.target.value)}
            placeholder="Board portal quirks, browser profile, MFA expectations, where to find MLS number, showing feedback, compliance status, and confirmation screens."
            className="min-h-28 w-full rounded-xl border border-border/60 bg-background/55 px-3 py-2 text-[0.86rem] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
          />
        </label>
        <label className="block min-w-0">
          <span className="mb-1 block text-[0.72rem] font-medium text-muted-foreground">Regional memory</span>
          <textarea
            value={draft.regionalMemory}
            onChange={(event) => updateDraft("regionalMemory", event.target.value)}
            placeholder="Province docs, local MLS quirks, deposit rules, admin emails, property lookup sources, showing platform notes."
            className="min-h-28 w-full rounded-xl border border-border/60 bg-background/55 px-3 py-2 text-[0.86rem] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
          />
        </label>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <label className="block min-w-0">
          <span className="mb-1 block text-[0.72rem] font-medium text-muted-foreground">Approval policy</span>
          <textarea
            value={draft.approvalPolicy}
            onChange={(event) => updateDraft("approvalPolicy", event.target.value)}
            placeholder="What AI can draft/upload, what needs approval, whether docs/MLS/signing can ever send without a human."
            className="min-h-28 w-full rounded-xl border border-border/60 bg-background/55 px-3 py-2 text-[0.86rem] leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
          />
        </label>
      </div>

      {(error || savedMessage) && (
        <div className={cn("rounded-xl border px-3 py-2 text-[0.8rem]", error ? "border-destructive/35 bg-destructive/10 text-destructive" : "border-success/35 bg-success/10 text-success")}>
          {error || savedMessage}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3">
        <div className="text-[0.76rem] leading-5 text-muted-foreground">
          Admin deal creation, profile handoffs, stage moves, task launches, and default automation seeding are blocked until this reaches 100%.
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => void verify()} disabled={saving || verifying}>
            {verifying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Verify connections
          </Button>
          <Button onClick={() => void submit()} disabled={saving || verifying}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
          Save setup
          </Button>
        </div>
      </div>
    </div>
  );
}

function useAdminDeals(): {
  deals: AdminCard[];
  loading: boolean;
  error: string | null;
  usingDevFallback: boolean;
  refresh: () => Promise<void>;
  moveDeal: (dealId: string, toStage: AdminStageNumber) => Promise<void>;
  setDealToggle: (dealId: string, field: string, value: AdminConditionValue) => Promise<void>;
  addLocalDeal: (card: AdminCard) => void;
  replaceLocalDeal: (placeholderId: string, deal: AdminDeal) => void;
} {
  const [deals, setDeals] = useState<AdminCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [usingDevFallback, setUsingDevFallback] = useState(false);

  const loadDeals = useCallback(async () => {
    const response = await api.getAdminDeals({ limit: 200 });
    return response.items.map(adminCardFromDeal);
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const nextDeals = await loadDeals();
      if (nextDeals.length === 0) {
        setDeals([]);
        setUsingDevFallback(false);
      } else {
        setDeals(nextDeals);
        setUsingDevFallback(false);
      }
    } catch (err) {
      setError(errorMessage(err, "Admin deals failed"));
      setDeals([]);
      setUsingDevFallback(false);
    } finally {
      setLoading(false);
    }
  }, [loadDeals]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadDeals()
      .then((nextDeals) => {
        if (cancelled) return;
        if (nextDeals.length === 0) {
          setDeals([]);
          setUsingDevFallback(false);
        } else {
          setDeals(nextDeals);
          setUsingDevFallback(false);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(errorMessage(err, "Admin deals failed"));
        setDeals([]);
        setUsingDevFallback(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadDeals]);

  const moveDeal = useCallback(
    async (dealId: string, toStage: AdminStageNumber) => {
      setDeals((prev) =>
        prev.map((card) => (card.id === dealId ? { ...card, stage: toStage, nextLabel: adminStageLabel(card.side, toStage).title } : card)),
      );
      try {
        const updated = await api.moveAdminDeal(dealId, toStage);
        setDeals((prev) => replaceCardFromDeal(prev, updated));
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals/:id/move returned 404; keeping optimistic local stage update.");
          return;
        }
        setError(errorMessage(err, "Move deal failed"));
        await refresh();
      }
    },
    [refresh],
  );

  const setDealToggle = useCallback(
    async (dealId: string, field: string, value: AdminConditionValue) => {
      setDeals((prev) =>
        prev.map((card) => (card.id === dealId ? applyLocalDealField(card, field, value) : card)),
      );
      try {
        const updated = await api.setAdminDealToggle(dealId, field, value);
        setDeals((prev) => replaceCardFromDeal(prev, updated));
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals/:id/toggle returned 404; keeping optimistic local toggle update.");
          return;
        }
        setError(errorMessage(err, "Set deal toggle failed"));
        await refresh();
      }
    },
    [refresh],
  );

  const addLocalDeal = useCallback((card: AdminCard) => {
    setDeals((prev) => [card, ...prev]);
  }, []);

  const replaceLocalDeal = useCallback((placeholderId: string, deal: AdminDeal) => {
    const fresh = adminCardFromDeal(deal);
    setDeals((prev) => prev.map((card) => (card.id === placeholderId ? fresh : card)));
  }, []);

  return { deals, loading, error, usingDevFallback, refresh, moveDeal, setDealToggle, addLocalDeal, replaceLocalDeal };
}

function dueLabel(days?: number): { text: string; tone: "muted" | "warn" | "danger" | "ok" } {
  if (days == null) return { text: "—", tone: "muted" };
  if (days < 0) return { text: `${-days}d overdue`, tone: "danger" };
  if (days === 0) return { text: "today", tone: "warn" };
  if (days === 1) return { text: "tomorrow", tone: "warn" };
  if (days <= 3) return { text: `in ${days}d`, tone: "warn" };
  return { text: `in ${days}d`, tone: "ok" };
}

const AdminKanbanCard = memo(function AdminKanbanCard({
  card,
  onSelect,
  onDragStart,
}: {
  card: AdminCard;
  onSelect?: (id: string) => void;
  onDragStart?: (id: string) => void;
}) {
  const due = dueLabel(card.daysOut);
  const { done, total, nextItem } = getCardProgress(card);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <button
      type="button"
      draggable
      onClick={() => onSelect?.(card.id)}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", card.id);
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.(card.id);
      }}
      className="w-full text-left rounded-xl border border-border/60 bg-background/40 p-3 hover:border-border hover:bg-background/60 focus:outline-none focus:ring-2 focus:ring-primary/40 transition-colors cursor-grab active:cursor-grabbing"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="truncate text-[0.95rem] font-semibold leading-tight text-foreground">
          {card.client}
        </div>
        {card.pinnedTop25 && (
          <span title="TOP 25" className="inline-flex h-5 items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-1.5 font-mono-ui text-[0.65rem] font-semibold uppercase tracking-wider text-warning">
            <Flame className="h-2.5 w-2.5" />
            Top
          </span>
        )}
      </div>
      {card.property && (
        <div className="mt-1.5 flex items-start gap-1.5 text-[0.78rem] text-muted-foreground">
          <Building2 className="mt-[2px] h-3 w-3 shrink-0" />
          <span className="truncate">{card.property}</span>
        </div>
      )}
      {card.nextLabel && (
        <div className="mt-2 flex items-center gap-1.5 text-[0.78rem]">
          <CalendarClock className="h-3 w-3 text-muted-foreground" />
          <span className="truncate text-foreground">{card.nextLabel}</span>
          <span
            className={cn(
              "ml-auto shrink-0 font-mono-ui text-[0.7rem]",
              due.tone === "danger" && "text-destructive",
              due.tone === "warn" && "text-warning",
              due.tone === "ok" && "text-muted-foreground",
              due.tone === "muted" && "text-muted-foreground",
            )}
          >
            {due.text}
          </span>
        </div>
      )}
      <div className="mt-3">
        <div className="flex items-center justify-between text-[0.7rem] text-muted-foreground">
          <span>
            {done}/{total} done
          </span>
          <span className="font-mono-ui">{pct}%</span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Stage checklist progress"
          className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-border/50"
        >
          <div className="h-full bg-primary/70" style={{ width: `${pct}%` }} />
        </div>
        {nextItem && (
          <div className="mt-2 flex items-center gap-1.5 truncate text-[0.78rem] text-muted-foreground">
            <span className="font-mono-ui shrink-0 text-[0.65rem] uppercase tracking-wider">Next</span>
            <span className="truncate">{nextItem}</span>
          </div>
        )}
      </div>
    </button>
  );
});

function AdminPhaseSummary({
  phase,
  dense = false,
}: {
  phase: AdminPhaseAutomationInfo;
  dense?: boolean;
}) {
  const agentLimit = dense ? 2 : 3;
  const backgroundLimit = dense ? 1 : 2;
  const agents = phase.agents.slice(0, agentLimit);
  const background = phase.background.slice(0, backgroundLimit);
  const hiddenCount = Math.max(0, phase.agents.length - agents.length) + Math.max(0, phase.background.length - background.length);

  return (
    <div className={cn("flex flex-col gap-1.5", dense ? "mt-1.5" : "mt-2")}>
      <div className="flex flex-wrap gap-1">
        {agents.length > 0 ? (
          agents.map((agent) => (
            <span
              key={`agent-${agent}`}
              title={`Stage-entry skill: ${agent}`}
              className="inline-flex max-w-full items-center gap-1 rounded-full border border-primary/25 bg-primary/10 px-1.5 py-0.5 text-[0.62rem] text-primary"
            >
              <Bot className="h-2.5 w-2.5 shrink-0" />
              <span className="truncate">{agent}</span>
            </span>
          ))
        ) : (
          <span
            title="No stage-entry skill is wired for this phase yet"
            className="inline-flex items-center gap-1 rounded-full border border-border/50 bg-background/35 px-1.5 py-0.5 text-[0.62rem] text-muted-foreground"
          >
            <CheckSquare className="h-2.5 w-2.5 shrink-0" />
            task list
          </span>
        )}
        {background.map((skill) => (
          <span
            key={`background-${skill}`}
            title={`Background cron skill: ${skill}`}
            className="inline-flex max-w-full items-center gap-1 rounded-full border border-success/25 bg-success/10 px-1.5 py-0.5 text-[0.62rem] text-success"
          >
            <Repeat className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{skill}</span>
          </span>
        ))}
        {phase.approvalGate && (
          <span
            title={`Approval gate: ${phase.approvalGate}`}
            className="inline-flex max-w-full items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[0.62rem] text-warning"
          >
            <ShieldCheck className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">approval</span>
          </span>
        )}
        {hiddenCount > 0 && (
          <span className="inline-flex items-center rounded-full border border-border/45 bg-background/30 px-1.5 py-0.5 font-mono-ui text-[0.6rem] text-muted-foreground">
            +{hiddenCount}
          </span>
        )}
      </div>
      <div
        title={`Move signal: ${phase.moveSignal}`}
        className="flex min-w-0 items-center gap-1.5 text-[0.66rem] leading-tight text-muted-foreground"
      >
        <Target className="h-3 w-3 shrink-0 text-muted-foreground/80" />
        <span className="truncate">Moves on {phase.moveSignal}</span>
      </div>
    </div>
  );
}

function AdminKanbanColumn(props: {
  side: AdminSide;
  stage: AdminStageNumber;
  cards: AdminCard[];
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
  onCardDrop: (stage: AdminStageNumber) => void;
}) {
  const { side, stage, cards, onCardSelect, onCardDragStart, onCardDrop } = props;
  const column = adminStageDefinition(stage);
  const label = column.labels[side];
  const phase = adminPhaseAutomation(side, stage);
  const [isDragOver, setIsDragOver] = useState(false);
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        if (!isDragOver) setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragOver(false);
        onCardDrop(stage);
      }}
      className={cn(
        "flex h-full min-w-[18.5rem] flex-col rounded-2xl border bg-card/30 transition-colors",
        isDragOver ? "border-primary/60 bg-primary/5" : "border-border/60",
      )}
    >
      <div className="border-b border-border/60 px-3 py-2.5" title={label.subtitle}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-primary">
              {column.stageNumber}
            </span>
            <span className="truncate text-[0.88rem] font-semibold text-foreground">{label.title}</span>
          </div>
          <span className="font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground">
            {cards.length}
          </span>
        </div>
        <AdminPhaseSummary phase={phase} />
      </div>
      <div className="flex flex-col gap-2 p-2">
        {cards.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/40 bg-background/20 px-3 py-4 text-center text-[0.72rem] text-muted-foreground">
            <div>empty</div>
            <div className="mt-1 font-mono-ui text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground/80">
              {label.subtitle}
            </div>
          </div>
        ) : (
          cards.map((card) => (
            <AdminKanbanCard
              key={card.id}
              card={card}
              onSelect={onCardSelect}
              onDragStart={onCardDragStart}
            />
          ))
        )}
      </div>
    </div>
  );
}

function AdminKanbanSwimlane({
  side,
  title,
  description,
  cardsByStage,
  totalCount,
  onCardSelect,
  onCardDragStart,
  onCardDrop,
}: {
  side: AdminSide;
  title: string;
  description: string;
  cardsByStage: Record<AdminStageNumber, AdminCard[]>;
  totalCount: number;
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
  onCardDrop: (side: AdminSide, stage: AdminStageNumber) => void;
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
          {totalCount} active
        </span>
        <span className="hidden text-[0.72rem] text-muted-foreground sm:inline">{description}</span>
      </div>
      <div
        className="grid gap-2 overflow-x-auto pb-1"
        style={{ gridTemplateColumns: `repeat(${ADMIN_STAGE_NUMBERS.length}, 18.5rem)` }}
      >
        {ADMIN_STAGE_NUMBERS.map((stage) => (
          <AdminKanbanColumn
            key={`${side}-${stage}`}
            side={side}
            stage={stage}
            cards={cardsByStage[stage] ?? []}
            onCardSelect={onCardSelect}
            onCardDragStart={onCardDragStart}
            onCardDrop={(targetStage) => onCardDrop(side, targetStage)}
          />
        ))}
      </div>
    </section>
  );
}

function AdminTop25Strip({
  cards,
  devFallback,
  onCardSelect,
  onCardDragStart,
}: {
  cards: AdminCard[];
  devFallback: boolean;
  onCardSelect: (id: string) => void;
  onCardDragStart: (id: string) => void;
}) {
  const pinned = cards.filter((c) => c.pinnedTop25);
  return (
    <section className="rounded-2xl border border-warning/35 bg-warning/5 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <Flame className="h-4 w-4 text-warning" />
          <h2 className="text-[0.95rem] font-semibold text-foreground">TOP 25</h2>
          <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
            {pinned.length} pinned · {Math.max(0, 25 - pinned.length)} slots open
          </span>
          {devFallback && (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-[0.14em] text-warning">
              dev-fallback
            </span>
          )}
        </div>
        <span className="text-[0.72rem] text-muted-foreground hidden sm:inline">
          Pinned clients still live in their stage column.
        </span>
      </div>
      {pinned.length === 0 ? (
        <div className="mt-2 rounded-xl border border-dashed border-border/40 bg-background/20 px-3 py-4 text-center text-[0.72rem] text-muted-foreground">
          No clients pinned. Pin from any card to add to TOP 25.
          {devFallback && (
            <span className="ml-2 rounded-full border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-[0.14em] text-warning">
              dev-fallback
            </span>
          )}
        </div>
      ) : (
        <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
          {pinned.map((card) => (
            <div key={card.id} className="min-w-[16rem] max-w-[16rem]">
              <AdminKanbanCard card={card} onSelect={onCardSelect} onDragStart={onCardDragStart} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function AdminCardStageSection({
  card,
  stage,
  isCurrent,
  isPast,
  expanded,
  onToggleExpand,
  onToggleItem,
}: {
  card: AdminCard;
  stage: AdminStageNumber;
  isCurrent: boolean;
  isPast: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleItem: (itemId: string, completed: boolean) => void;
}) {
  const column = adminStageDefinition(stage);
  const label = column.labels[card.side];
  const phase = adminPhaseAutomation(card.side, stage);
  const items = adminStageChecklist(card.side, stage);
  const completed = card.completedByStage?.[stage] ?? {};
  const done = items.reduce((n, item) => n + (completed[item.id] ? 1 : 0), 0);
  const total = items.length;
  const allDone = total > 0 && done === total;

  return (
    <div
      className={cn(
        "rounded-xl border bg-background/30",
        isCurrent ? "border-primary/50" : "border-border/50",
      )}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left focus:outline-none focus:ring-2 focus:ring-primary/30 rounded-xl"
      >
        <div className="flex h-6 w-6 shrink-0 items-center justify-center">
          {isPast && allDone ? (
            <CheckCircle2 className="h-5 w-5 text-primary/80" />
          ) : isCurrent ? (
            <span className="inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
          ) : (
            <span className="inline-flex h-2.5 w-2.5 rounded-full border border-border" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "text-[0.86rem] font-semibold leading-tight",
                isCurrent ? "text-foreground" : isPast ? "text-foreground/85" : "text-muted-foreground",
              )}
            >
              {label.title}
            </span>
            {isCurrent && (
              <span className="font-mono-ui text-[0.58rem] uppercase tracking-[0.14em] text-primary">
                current
              </span>
            )}
          </div>
          <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
            {column.stageNumber} · {column.stageLabel ?? label.subtitle}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[0.66rem] leading-tight text-muted-foreground">
            <Target className="h-3 w-3 shrink-0 text-muted-foreground/80" />
            <span className="truncate">{phase.moveSignal}</span>
          </div>
        </div>
        <span
          className={cn(
            "font-mono-ui text-[0.66rem] tabular-nums",
            allDone ? "text-primary" : "text-muted-foreground",
          )}
        >
          {done}/{total}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="border-t border-border/50 px-3 py-2.5">
          <div className="mb-2 rounded-lg border border-border/45 bg-background/35 px-2 py-2">
            <AdminPhaseSummary phase={phase} dense />
            {phase.approvalGate && (
              <div className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[0.68rem] text-muted-foreground">
                <ShieldCheck className="h-3 w-3 shrink-0 text-warning" />
                <span className="truncate">Gate: {phase.approvalGate}</span>
              </div>
            )}
          </div>
          {items.length === 0 ? (
            <div className="text-[0.72rem] text-muted-foreground">No checklist items defined for this stage.</div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {items.map((item) => {
                const isDone = !!completed[item.id];
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => onToggleItem(item.id, !isDone)}
                      className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-background/60 focus:outline-none focus:ring-2 focus:ring-primary/30"
                    >
                      {isDone ? (
                        <CheckSquare className="mt-[1px] h-4 w-4 shrink-0 text-primary" />
                      ) : (
                        <SquareIcon className="mt-[1px] h-4 w-4 shrink-0 text-muted-foreground" />
                      )}
                      <span
                        className={cn(
                          "text-[0.82rem] leading-snug",
                          isDone ? "text-muted-foreground line-through decoration-muted-foreground/50" : "text-foreground",
                        )}
                      >
                        {item.label}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function AdminCardConditionsSection({
  card,
  onConditionChange,
}: {
  card: AdminCard;
  onConditionChange: (field: AdminConditionField, value: AdminConditionValue) => void;
}) {
  const conditions = card.conditions ?? {};
  return (
    <section className="mt-4">
      <h3 className="text-[0.86rem] font-semibold text-foreground">Conditions</h3>
      <div className="mt-2 space-y-4">
        <div>
          <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            Enums
          </div>
          <div className="divide-y divide-border/40">
            {ADMIN_ENUM_CONDITIONS.map((condition) => {
              const current = conditions[condition.field];
              const value = typeof current === "string" ? current : "";
              const hasCustomValue = value !== "" && !condition.options.some((option) => option.value === value);
              return (
                <label
                  key={condition.field}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="min-w-0 flex-1 text-[0.78rem] font-medium text-foreground">
                    {condition.label}
                  </span>
                  <select
                    value={value}
                    onChange={(event) => onConditionChange(condition.field, event.currentTarget.value || null)}
                    className="h-10 max-w-[12rem] rounded-md border border-border/60 bg-background px-2 text-[0.78rem] text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                  >
                    <option value="">Not set</option>
                    {hasCustomValue && <option value={value}>{value}</option>}
                    {condition.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
        </div>

        <div>
          <div className="font-mono-ui mb-1.5 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            Yes / No
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {ADMIN_TOGGLE_CONDITIONS.map((condition) => {
              const current = conditions[condition.field];
              const checked = current === true;
              const label = current == null ? "Unset" : checked ? "Yes" : "No";
              return (
                <button
                  key={condition.field}
                  type="button"
                  aria-pressed={checked}
                  onClick={() => onConditionChange(condition.field, !checked)}
                  className="flex min-h-11 items-center gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-background/60 focus:outline-none focus:ring-2 focus:ring-primary/30"
                >
                  {checked ? (
                    <CheckSquare className="h-4 w-4 shrink-0 text-primary" />
                  ) : (
                    <SquareIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1 text-[0.78rem] leading-tight text-foreground">
                    {condition.label}
                  </span>
                  <span className="font-mono-ui text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                    {label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function AdminCardSourceSection({ context }: { context: AdminSourceContext }) {
  const heat = context.heatLabel
    ? `${context.heatLabel}${context.heatScore != null ? ` ${context.heatScore}` : ""}`
    : null;
  return (
    <section className="mb-3 rounded-xl border border-border/60 bg-background/35 px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.86rem] font-semibold text-foreground">
          {context.profileName || "Source profile"}
        </span>
        {heat && <Badge variant={context.heatLabel ? heatVariant({ heatLabel: context.heatLabel }) : "outline"}>{heat}</Badge>}
        {context.contactIds.length > 0 && !context.rejectedContactId && <Badge variant="success">DB contact</Badge>}
        <Badge variant={context.verifiers.length > 0 ? "success" : "warning"}>
          {verifierSummary(context.verifiers)}
        </Badge>
        {context.rejectedContactId && <Badge variant="warning">source contact only</Badge>}
      </div>
      {context.latestText && (
        <p className="mt-2 line-clamp-3 text-[0.8rem] leading-5 text-muted-foreground">
          {context.latestText}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {context.sources.map((source) => (
          <Badge key={`source-${source}`} variant="outline">{source}</Badge>
        ))}
        {context.channels.map((channel) => (
          <Badge key={`channel-${channel}`} variant="outline">{channel}</Badge>
        ))}
        {context.conversationIds.length > 0 && (
          <Badge variant="outline">
            {context.conversationIds.length} conversation{context.conversationIds.length === 1 ? "" : "s"}
          </Badge>
        )}
        {context.latestAt && <Badge variant="outline">{isoTimeAgo(context.latestAt)}</Badge>}
      </div>
    </section>
  );
}

function isPersistedAdminDealId(id: string): boolean {
  return /^[a-f0-9]{32}$/i.test(id);
}

function adminContextDate(value?: string | null): string {
  if (!value) return "Not set";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return isoTimeAgo(value);
}

function adminContextMoney(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "Not set";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value);
}

function adminRunStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" | "success" | "warning" {
  if (status === "succeeded" || status === "completed") return "success";
  if (status === "failed" || status === "cancelled") return "destructive";
  if (status === "waiting_human" || status === "waiting_external") return "warning";
  if (status === "running" || status === "queued") return "secondary";
  return "outline";
}

type AdminRunTone = "default" | "secondary" | "destructive" | "outline" | "success" | "warning";
type AdminRunBusy = { id: string; action: "approve" | "cancel" } | null;

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

function AdminDealContextSection({
  context,
  loading,
  error,
  busy,
  onAdvance,
  onUpdateFields,
  onAddAttachment,
  onAddContact,
  onApproveRun,
  onCancelRun,
}: {
  context: DealContext | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onAdvance: (force?: boolean) => Promise<void>;
  onUpdateFields: (fields: Record<string, unknown>) => Promise<void>;
  onAddAttachment: (body: DealAttachmentCreateRequest) => Promise<void>;
  onAddContact: (body: DealContactCreateRequest) => Promise<void>;
  onApproveRun: (runId: string) => Promise<void>;
  onCancelRun: (runId: string) => Promise<void>;
}) {
  const [actionMode, setActionMode] = useState<"dates" | "doc" | "contact" | null>(null);
  const [approvalBusyRun, setApprovalBusyRun] = useState<AdminRunBusy>(null);
  const [fieldDraft, setFieldDraft] = useState({
    listingDate: "",
    subjectRemovalDate: "",
    depositDueDate: "",
    completionDate: "",
    possessionDate: "",
    mlsNumber: "",
    listPrice: "",
  });
  const [docDraft, setDocDraft] = useState({ kind: "cma_report", filePath: "", summary: "" });
  const [contactDraft, setContactDraft] = useState({ role: "lawyer", contactId: "", notes: "" });
  const deal = context?.deal ?? null;
  const primary = context?.primaryContact ?? null;
  const coContacts = context?.coContacts ?? [];
  const attachments = context?.attachments ?? [];
  const priorRuns = context?.priorRuns ?? [];
  const flow = context?.dealFlow ?? null;
  const gate = flow?.gate ?? null;
  const pendingHumanRuns = priorRuns.filter((run) => run.status === "waiting_human");
  const resolvePendingRun = async (run: AdminActionRun, approved: boolean) => {
    if (busy || approvalBusyRun) return;
    setApprovalBusyRun({ id: run.id, action: approved ? "approve" : "cancel" });
    try {
      if (approved) {
        await onApproveRun(run.id);
      } else {
        await onCancelRun(run.id);
      }
    } finally {
      setApprovalBusyRun(null);
    }
  };
  const dateRows: Array<[string, string]> = deal
    ? ([
        ["Listing", deal.listingDate],
        ["Offer", deal.offerDate],
        ["Subjects", deal.subjectRemovalDate],
        ["Deposit", deal.depositDueDate],
        ["Completion", deal.completionDate],
        ["Possession", deal.possessionDate],
      ] as Array<[string, string | null | undefined]>).flatMap(([label, value]) =>
        value ? [[label, value]] : [],
      )
    : [];
  const moneyRows: Array<[string, number]> = deal
    ? ([
        ["List price", deal.listPrice],
        ["Offer price", deal.offerPrice],
        ["Deposit", deal.depositAmount],
      ] as Array<[string, number | null | undefined]>).flatMap(([label, value]) =>
        typeof value === "number" ? [[label, value]] : [],
      )
    : [];

  return (
    <section className="mb-3 rounded-xl border border-border/60 bg-background/35 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <DatabaseIcon className="h-4 w-4 shrink-0 text-primary" />
          <h3 className="text-[0.88rem] font-semibold text-foreground">Transaction file</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {loading && (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              loading
            </Badge>
          )}
          {deal?.board && <Badge variant="outline">{deal.board}</Badge>}
          {deal?.market && <Badge variant="outline">{deal.market}</Badge>}
          {context && <Badge variant="outline">{attachments.length} docs</Badge>}
          {context && <Badge variant="outline">{priorRuns.length} runs</Badge>}
        </div>
      </div>

      {!loading && error && (
        <div className="mt-2 rounded-lg border border-warning/35 bg-warning/10 px-3 py-2 text-[0.78rem] text-warning">
          {error}
        </div>
      )}

      {!loading && !error && !context && (
        <div className="mt-2 rounded-lg border border-dashed border-border/50 bg-background/25 px-3 py-3 text-[0.78rem] text-muted-foreground">
          This preview card is not backed by a saved deal file yet.
        </div>
      )}

      {context && deal && (
        <div className="mt-3 space-y-3">
          {gate && (
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                    Phase gate
                  </div>
                  <div className="mt-1 text-[0.86rem] font-medium text-foreground">
                    {gate.stageName}
                    {gate.nextStageName ? ` -> ${gate.nextStageName}` : ""}
                  </div>
                </div>
                <Badge variant={gate.canAdvance ? "success" : "warning"}>
                  {gate.canAdvance ? "ready" : "blocked"}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2 text-[0.74rem] sm:grid-cols-2">
                <div>
                  <span className="text-muted-foreground">Checklist: </span>
                  <span className="text-foreground">
                    {gate.completedChecklist}/{gate.totalChecklist}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Package: </span>
                  <span className="text-foreground">{flow?.packageKey}</span>
                </div>
              </div>
              {(gate.missingChecklist.length > 0 || gate.missingFields.length > 0 || gate.missingDocs.length > 0 || gate.blockingRuns.length > 0) && (
                <div className="mt-2 space-y-1.5 text-[0.74rem]">
                  {gate.missingChecklist.slice(0, 4).map((item) => (
                    <div key={`check-${item.id}`} className="text-muted-foreground">
                      Missing checklist: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.missingFields.slice(0, 4).map((item) => (
                    <div key={`field-${item.field}`} className="text-muted-foreground">
                      Missing field: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.missingDocs.slice(0, 4).map((item) => (
                    <div key={`doc-${item.kind}`} className="text-muted-foreground">
                      Missing doc: <span className="text-foreground">{item.label}</span>
                    </div>
                  ))}
                  {gate.blockingRuns.slice(0, 4).map((run) => (
                    <div key={`run-${run.id}`} className="text-muted-foreground">
                      Waiting run: <span className="text-foreground">{run.label}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" disabled={!gate.canAdvance || busy} onClick={() => void onAdvance(false)}>
                  {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Advance phase
                </Button>
                {!gate.canAdvance && gate.nextStage != null && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void onAdvance(true)}>
                    Force advance
                  </Button>
                )}
              </div>
	            </div>
	          )}

	          {flow?.backgroundAutomations?.length ? (
	            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
	              <div className="flex flex-wrap items-center justify-between gap-2">
	                <div>
	                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
	                    Background automations
	                  </div>
	                  <div className="mt-1 text-[0.78rem] text-muted-foreground">
	                    Cron skills feed evidence into this deal; phases consume the results.
	                  </div>
	                </div>
	                <Badge variant="outline">{flow.backgroundAutomations.length}</Badge>
	              </div>
	              <div className="mt-2 grid gap-2 sm:grid-cols-2">
	                {flow.backgroundAutomations.map((item) => (
	                  <div key={item.id} className="rounded-md border border-border/40 bg-background/35 px-2 py-2">
	                    <div className="flex min-w-0 items-center justify-between gap-2">
	                      <span className="truncate text-[0.8rem] font-medium text-foreground">{item.name}</span>
	                      <Badge variant="secondary">{item.kind}</Badge>
	                    </div>
	                    <div className="mt-1 truncate font-mono-ui text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
	                      {item.skill}
	                    </div>
	                  </div>
	                ))}
	              </div>
	            </div>
	          ) : null}

	          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                Primary contact
              </div>
              <div className="mt-1 truncate text-[0.86rem] font-medium text-foreground">
                {primary?.displayName ?? "Not linked"}
              </div>
              {(primary?.primaryEmail || primary?.primaryPhone) && (
                <div className="mt-1 space-y-0.5 text-[0.74rem] text-muted-foreground">
                  {primary.primaryEmail && <div className="truncate">{primary.primaryEmail}</div>}
                  {primary.primaryPhone && <div>{primary.primaryPhone}</div>}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                Important dates
              </div>
              {dateRows.length > 0 ? (
                <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[0.74rem]">
                  {dateRows.slice(0, 6).map(([label, value]) => (
                    <div key={label} className="min-w-0">
                      <span className="text-muted-foreground">{label}: </span>
                      <span className="text-foreground">{adminContextDate(value)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1 text-[0.74rem] text-muted-foreground">No dates set</div>
              )}
            </div>
          </div>

          {(moneyRows.length > 0 || deal.mlsNumber || deal.legalDescription) && (
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                File details
              </div>
              <div className="mt-1 grid gap-x-3 gap-y-1 text-[0.74rem] sm:grid-cols-2">
                {moneyRows.map(([label, value]) => (
                  <div key={label}>
                    <span className="text-muted-foreground">{label}: </span>
                    <span className="text-foreground">{adminContextMoney(value)}</span>
                  </div>
                ))}
                {deal.mlsNumber && (
                  <div>
                    <span className="text-muted-foreground">MLS: </span>
                    <span className="text-foreground">{deal.mlsNumber}</span>
                  </div>
                )}
                {deal.legalDescription && (
                  <div className="sm:col-span-2">
                    <span className="text-muted-foreground">Legal: </span>
                    <span className="text-foreground">{deal.legalDescription}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                <Users className="h-3 w-3" />
                Co-contacts
              </div>
              {coContacts.length > 0 ? (
                <div className="mt-1.5 space-y-1">
                  {coContacts.slice(0, 3).map((item) => (
                    <div key={item.id} className="min-w-0 text-[0.74rem]">
                      <span className="font-medium text-foreground">{item.role}</span>
                      <span className="text-muted-foreground"> · </span>
                      <span className="text-muted-foreground">{item.contact?.displayName ?? item.contactId}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-[0.74rem] text-muted-foreground">None linked</div>
              )}
            </div>
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                <FileText className="h-3 w-3" />
                Documents
              </div>
              {attachments.length > 0 ? (
                <div className="mt-1.5 space-y-1">
                  {attachments.slice(0, 3).map((item) => (
                    <div key={item.id} className="min-w-0 text-[0.74rem]" title={item.filePath}>
                      <span className="font-medium text-foreground">{item.kind}</span>
                      {item.summary && <span className="text-muted-foreground"> · {item.summary}</span>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-[0.74rem] text-muted-foreground">No docs attached</div>
              )}
            </div>
            <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
              <div className="flex items-center gap-1.5 font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                <Clock className="h-3 w-3" />
                Prior runs
              </div>
              {priorRuns.length > 0 ? (
                <div className="mt-1.5 space-y-1.5">
                  {priorRuns.slice(0, 3).map((run) => (
                    <div key={run.id} className="min-w-0">
                      <div className="truncate text-[0.74rem] font-medium text-foreground">
                        {run.registryName ?? run.skill ?? "Admin run"}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        <Badge variant={adminRunStatusVariant(run.status)}>{run.status}</Badge>
                        <span className="text-[0.68rem] text-muted-foreground">{isoTimeAgo(run.updatedAt)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-1.5 text-[0.74rem] text-muted-foreground">No runs yet</div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-border/45 bg-background/30 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
                Source actions
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant={actionMode === "dates" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "dates" ? null : "dates")}>
                  <CalendarClock className="h-3.5 w-3.5" />
                  Dates
                </Button>
                <Button size="sm" variant={actionMode === "doc" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "doc" ? null : "doc")}>
                  <FileText className="h-3.5 w-3.5" />
                  Attach
                </Button>
                <Button size="sm" variant={actionMode === "contact" ? "default" : "outline"} onClick={() => setActionMode(actionMode === "contact" ? null : "contact")}>
                  <Users className="h-3.5 w-3.5" />
                  Co-contact
                </Button>
              </div>
            </div>

            {actionMode === "dates" && (
              <form
                className="mt-3 grid gap-2 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const fields = Object.fromEntries(
                    Object.entries(fieldDraft).filter(([, value]) => value.trim()),
                  );
                  void onUpdateFields(fields).then(() => {
                    setFieldDraft({
                      listingDate: "",
                      subjectRemovalDate: "",
                      depositDueDate: "",
                      completionDate: "",
                      possessionDate: "",
                      mlsNumber: "",
                      listPrice: "",
                    });
                    setActionMode(null);
                  });
                }}
              >
                {(["listingDate", "subjectRemovalDate", "depositDueDate", "completionDate", "possessionDate", "mlsNumber", "listPrice"] as const).map((field) => (
                  <label key={field} className="text-[0.72rem] text-muted-foreground">
                    {field}
                    <input
                      value={fieldDraft[field]}
                      onChange={(event) => setFieldDraft((prev) => ({ ...prev, [field]: event.target.value }))}
                      className="mt-1 h-10 w-full rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  </label>
                ))}
                <div className="sm:col-span-2">
                  <Button size="sm" type="submit" disabled={busy}>Update file fields</Button>
                </div>
              </form>
            )}

            {actionMode === "doc" && (
              <form
                className="mt-3 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onAddAttachment({
                    kind: docDraft.kind,
                    filePath: docDraft.filePath,
                    summary: docDraft.summary || null,
                  }).then(() => {
                    setDocDraft({ kind: "cma_report", filePath: "", summary: "" });
                    setActionMode(null);
                  });
                }}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <input value={docDraft.kind} onChange={(event) => setDocDraft((prev) => ({ ...prev, kind: event.target.value }))} placeholder="kind, e.g. cma_report" className="h-10 rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground" />
                  <input value={docDraft.filePath} onChange={(event) => setDocDraft((prev) => ({ ...prev, filePath: event.target.value }))} placeholder="/path/to/file.pdf" className="h-10 rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground" />
                </div>
                <input value={docDraft.summary} onChange={(event) => setDocDraft((prev) => ({ ...prev, summary: event.target.value }))} placeholder="summary" className="h-10 rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground" />
                <Button size="sm" type="submit" disabled={busy || !docDraft.kind.trim() || !docDraft.filePath.trim()}>Attach document</Button>
              </form>
            )}

            {actionMode === "contact" && (
              <form
                className="mt-3 grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void onAddContact({
                    role: contactDraft.role,
                    contactId: contactDraft.contactId,
                    notes: contactDraft.notes || null,
                  }).then(() => {
                    setContactDraft({ role: "lawyer", contactId: "", notes: "" });
                    setActionMode(null);
                  });
                }}
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <input value={contactDraft.role} onChange={(event) => setContactDraft((prev) => ({ ...prev, role: event.target.value }))} placeholder="role, e.g. lawyer" className="h-10 rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground" />
                  <input value={contactDraft.contactId} onChange={(event) => setContactDraft((prev) => ({ ...prev, contactId: event.target.value }))} placeholder="contact id" className="h-10 rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground" />
                </div>
                <input value={contactDraft.notes} onChange={(event) => setContactDraft((prev) => ({ ...prev, notes: event.target.value }))} placeholder="notes" className="h-10 rounded-md border border-border/60 bg-background px-2 text-[0.8rem] text-foreground" />
                <Button size="sm" type="submit" disabled={busy || !contactDraft.role.trim() || !contactDraft.contactId.trim()}>Add co-contact</Button>
              </form>
            )}
          </div>

          {pendingHumanRuns.length > 0 && (
            <div className="grid gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-warning">
                    Pending approvals
                  </div>
                  <div className="mt-1 text-[0.76rem] leading-5 text-muted-foreground">
                    These are the Admin decisions blocking the next run or phase move.
                  </div>
                </div>
                <Badge variant="warning">{pendingHumanRuns.length}</Badge>
              </div>
              <div className="mt-2 space-y-2">
                {pendingHumanRuns.map((run) => (
                  <AdminRunDecisionRow
                    key={run.id}
                    compact
                    busyRun={busy ? { id: "__busy__", action: "approve" } : approvalBusyRun}
                    run={run}
                    onApprove={() => void resolvePendingRun(run, true)}
                    onCancel={() => void resolvePendingRun(run, false)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function AdminCardDetailPanel({
  card,
  onClose,
  onToggleItem,
  onConditionChange,
  onMoveToNext,
  onDealUpdated,
}: {
  card: AdminCard;
  onClose: () => void;
  onToggleItem: (stage: AdminStageNumber, itemId: string, completed: boolean) => void;
  onConditionChange: (field: AdminConditionField, value: AdminConditionValue) => void;
  onMoveToNext: () => void;
  onDealUpdated: (deal: AdminDeal) => void;
}) {
  const nextStage = adminNextStage(card);
  const currentProgress = getCardProgress(card);
  const currentComplete = currentProgress.total > 0 && currentProgress.done === currentProgress.total;
  const currentStage = adminStageDefinition(card.stage);
  const currentLabel = currentStage.labels[card.side];
  const nextLabel = nextStage == null ? null : adminStageLabel(card.side, nextStage);

  const [expanded, setExpanded] = useState<Set<AdminStageNumber>>(() => new Set([card.stage]));
  const [dealContext, setDealContext] = useState<DealContext | null>(null);
  const [dealContextLoading, setDealContextLoading] = useState(false);
  const [dealContextError, setDealContextError] = useState<string | null>(null);
  const [dealActionBusy, setDealActionBusy] = useState(false);
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setExpanded((prev) => (prev.has(card.stage) ? prev : new Set([...prev, card.stage])));
  }, [card.stage]);

  useEffect(() => {
    let active = true;
    setDealContext(null);
    setDealContextError(null);
    if (!isPersistedAdminDealId(card.id)) {
      setDealContextLoading(false);
      return () => {
        active = false;
      };
    }
    setDealContextLoading(true);
    api.getDealContext(card.id)
      .then((context) => {
        if (active) setDealContext(context);
      })
      .catch((err) => {
        if (active) {
          setDealContextError(errorMessage(err, "Deal context failed"));
        }
      })
      .finally(() => {
        if (active) setDealContextLoading(false);
      });
    return () => {
      active = false;
    };
  }, [card.id]);

  const reloadDealContext = useCallback(async () => {
    if (!isPersistedAdminDealId(card.id)) return null;
    const context = await api.getDealContext(card.id);
    setDealContext(context);
    onDealUpdated(context.deal);
    return context;
  }, [card.id, onDealUpdated]);

  const runDealAction = useCallback(
    async (action: () => Promise<void>) => {
      setDealActionBusy(true);
      setDealContextError(null);
      try {
        await action();
      } catch (err) {
        setDealContextError(errorMessage(err, "Deal action failed"));
      } finally {
        setDealActionBusy(false);
      }
    },
    [],
  );

  const handleAdvancePhase = useCallback(
    (force = false) =>
      runDealAction(async () => {
        const context = await api.advanceDeal(card.id, force);
        setDealContext(context);
        onDealUpdated(context.deal);
      }),
    [card.id, onDealUpdated, runDealAction],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Focus trap + restore focus on close.
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (!root) return;

    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const getFocusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null,
      );

    queueMicrotask(() => {
      const focusables = getFocusables();
      focusables[0]?.focus();
    });

    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusables = getFocusables();
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, []);

  const toggleSection = (stage: AdminStageNumber) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage);
      else next.add(stage);
      return next;
    });
  };

  const due = dueLabel(card.daysOut);
  const laneLabel = ADMIN_SIDE_LABELS[card.side].title;
  const phaseGate = dealContext?.dealFlow?.gate ?? null;
  const showAdvancePrompt = nextStage != null && nextLabel && (phaseGate ? phaseGate.canAdvance : currentComplete);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close detail"
        onClick={onClose}
        className="absolute inset-0 bg-background/60 backdrop-blur-sm"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex h-full w-full flex-col bg-card shadow-2xl sm:h-auto sm:max-h-full sm:w-full sm:max-w-[36rem] sm:rounded-2xl sm:border sm:border-border/60"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-mono-ui text-[0.6rem] uppercase tracking-[0.16em] text-muted-foreground">
              <span>{laneLabel} admin</span>
              <span>·</span>
              <span className="text-primary">{currentStage.stageNumber}</span>
              <span>·</span>
              <span className="text-primary">{currentLabel.title}</span>
              {card.pinnedTop25 && (
                <span className="inline-flex items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-warning">
                  <Flame className="h-2.5 w-2.5" />
                  Top
                </span>
              )}
            </div>
            <h2 id={titleId} className="mt-0.5 text-[1rem] font-semibold leading-tight text-foreground">
              {card.client}
            </h2>
            {card.property && (
              <div className="mt-1 flex items-start gap-1.5 text-[0.78rem] text-muted-foreground">
                <Building2 className="mt-[2px] h-3.5 w-3.5 shrink-0" />
                <span>{card.property}</span>
              </div>
            )}
            {card.nextLabel && (
              <div className="mt-1 flex items-center gap-1.5 text-[0.78rem]">
                <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-foreground">{card.nextLabel}</span>
                <span
                  className={cn(
                    "font-mono-ui text-[0.68rem]",
                    due.tone === "danger" && "text-destructive",
                    due.tone === "warn" && "text-warning",
                    due.tone === "ok" && "text-muted-foreground",
                    due.tone === "muted" && "text-muted-foreground",
                  )}
                >
                  · {due.text}
                </span>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-background/60 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
            aria-label="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        {showAdvancePrompt && nextStage != null && nextLabel && (
          <div className="border-b border-border/60 bg-primary/5 px-4 py-2.5">
            <div className="flex items-center gap-2 text-[0.78rem]">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <span className="text-foreground">
                All {currentStage.stageNumber} items done - move to {nextLabel.title}?
              </span>
              <button
                type="button"
                onClick={() => {
                  if (phaseGate) void handleAdvancePhase(false);
                  else onMoveToNext();
                }}
                className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-3 py-2 font-mono-ui text-[0.66rem] uppercase tracking-wider text-primary hover:bg-primary/20 focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                Move card →
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {card.sourceContext && <AdminCardSourceSection context={card.sourceContext} />}
          <AdminDealContextSection
            context={dealContext}
            loading={dealContextLoading}
            error={dealContextError}
            busy={dealActionBusy}
            onAdvance={handleAdvancePhase}
            onUpdateFields={(fields) =>
              runDealAction(async () => {
                const deal = await api.updateDealFields(card.id, fields);
                onDealUpdated(deal);
                await reloadDealContext();
              })
            }
            onAddAttachment={(body) =>
              runDealAction(async () => {
                await api.addDealAttachment(card.id, body);
                await reloadDealContext();
              })
            }
            onAddContact={(body) =>
              runDealAction(async () => {
                await api.addDealContact(card.id, body);
                await reloadDealContext();
              })
            }
            onApproveRun={(runId) =>
              runDealAction(async () => {
                await api.approveAdminActionRun(runId, { approved: true, runNow: true });
                await reloadDealContext();
              })
            }
            onCancelRun={(runId) =>
              runDealAction(async () => {
                await api.approveAdminActionRun(runId, { approved: false, runNow: false });
                await reloadDealContext();
              })
            }
          />
          <div className="flex flex-col gap-2">
            {ADMIN_STAGE_NUMBERS.map((stage) => (
                <AdminCardStageSection
                  key={`${card.side}-${stage}`}
                  card={card}
                  stage={stage}
                  isCurrent={stage === card.stage}
                  isPast={stage < card.stage}
                  expanded={expanded.has(stage)}
                  onToggleExpand={() => toggleSection(stage)}
                  onToggleItem={(itemId, completed) => onToggleItem(stage, itemId, completed)}
                />
            ))}
          </div>
          <AdminCardConditionsSection card={card} onConditionChange={onConditionChange} />
        </div>
      </aside>
    </div>,
    document.body,
  );
}

function NewDealDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (placeholderCard: AdminCard, request: AdminDealCreateRequest) => Promise<void>;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const [title, setTitle] = useState("");
  const [side, setSide] = useState<AdminSide>("listing");
  const [stage, setStage] = useState<AdminStageNumber>(0);
  const [province, setProvince] = useState("");
  const [provinceCoverage, setProvinceCoverage] = useState<AdminProvinceGuideCoverage[]>([]);
  const [contactId, setContactId] = useState<string | null>(null);
  const [contactQuery, setContactQuery] = useState("");
  const [contacts, setContacts] = useState<AdminContact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactsError, setContactsError] = useState<string | null>(null);
  const [listingAddress, setListingAddress] = useState("");
  const [propertySubtype, setPropertySubtype] = useState("");
  const [listingType, setListingType] = useState("");
  const [signingAuthority, setSigningAuthority] = useState("");
  const [transactionType, setTransactionType] = useState("");
  const [notes, setNotes] = useState("");
  const [notesAutoFilled, setNotesAutoFilled] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (!root) return;
    const focusableSelector =
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const getFocusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null,
      );
    queueMicrotask(() => {
      const focusables = getFocusables();
      focusables[0]?.focus();
    });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = getFocusables();
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    root.addEventListener("keydown", onKey);
    return () => {
      root.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    api
      .getAdminJurisdiction()
      .then((jurisdiction) => {
        if (cancelled) return;
        setProvince(jurisdiction.province || "");
      })
      .catch(() => {});
    api
      .getAdminProvinceGuides()
      .then((guides) => {
        if (cancelled) return;
        if ("items" in guides) {
          setProvinceCoverage(guides.items);
        }
      })
      .catch(() => {
        if (!cancelled) setProvinceCoverage([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setContactsLoading(true);
    setContactsError(null);
    api
      .getAdminContacts({ limit: 200 })
      .then((response) => {
        if (cancelled) return;
        setContacts(response.items);
      })
      .catch((err) => {
        if (cancelled) return;
        setContactsError(err instanceof Error ? err.message : "Could not load contacts");
      })
      .finally(() => {
        if (!cancelled) setContactsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const provinceCoverageByCode = useMemo(() => {
    return new Map(provinceCoverage.map((item) => [item.province, item]));
  }, [provinceCoverage]);

  const selectedProvinceCoverage = provinceCoverageByCode.get(province);

  const filteredContacts = useMemo(() => {
    const q = contactQuery.trim().toLowerCase();
    if (!q) return contacts.slice(0, 8);
    return contacts
      .filter((contact) => {
        const haystack = [contact.displayName, contact.primaryEmail, contact.primaryPhone]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .slice(0, 8);
  }, [contacts, contactQuery]);

  const selectedContact = contacts.find((c) => c.id === contactId) ?? null;

  const handleSelectContact = (contact: AdminContact) => {
    setContactId(contact.id);
    setContactQuery("");
    if (!title.trim() && contact.displayName) {
      setTitle(contact.displayName);
    }
    if (!notes.trim() || notesAutoFilled) {
      const bits: string[] = [];
      if (contact.sourceKey) bits.push(`Source: ${contact.sourceKey}`);
      if (contact.type) bits.push(`Type: ${contact.type}`);
      if (contact.stage) bits.push(`Stage: ${contact.stage}`);
      if (contact.lastActivityAt) bits.push(`Last activity: ${isoTimeAgo(contact.lastActivityAt)}`);
      if (contact.ownerNotes) bits.push(`\nNotes: ${contact.ownerNotes}`);
      const filled = bits.join("\n");
      if (filled) {
        setNotes(filled);
        setNotesAutoFilled(true);
      }
    }
  };

  const clearContact = () => {
    setContactId(null);
    setContactQuery("");
    if (notesAutoFilled) {
      setNotes("");
      setNotesAutoFilled(false);
    }
  };

  const canSubmit = title.trim().length > 0 && province.trim().length > 0 && !submitting;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    const cleanTitle = title.trim();
    const cleanAddress = listingAddress.trim();
    const cleanNotes = notes.trim();
    const placeholderId = `local-${Date.now()}`;
    const stageLabel = adminStageLabel(side, stage);
    const conditions: Partial<Record<AdminConditionField, AdminConditionValue>> = {};
    const fields: Record<string, unknown> = {};
    if (side === "listing") {
      if (signingAuthority) {
        fields.signing_authority = signingAuthority;
        conditions.signing_authority = signingAuthority;
      }
      if (listingType) {
        fields.listing_type = listingType;
        conditions.listing_type = listingType;
      }
    } else if (transactionType) {
      fields.transaction_type = transactionType;
      conditions.transaction_type = transactionType;
    }
    if (propertySubtype) {
      fields.property_subtype = propertySubtype;
      conditions.property_subtype = propertySubtype;
    }
    if (cleanNotes) fields.notes = cleanNotes;
    const placeholder: AdminCard = {
      id: placeholderId,
      side,
      stage,
      client: cleanTitle,
      contactInitials: initialsFromTitle(cleanTitle),
      property: cleanAddress || `${province} deal`,
      nextLabel: stageLabel.title,
      pinnedTop25: false,
      completedByStage: {},
      conditions,
    };
    const request: AdminDealCreateRequest = {
      title: cleanTitle,
      side,
      province,
      currentStage: stage,
      primaryContactId: contactId,
      listingAddress: side === "listing" ? cleanAddress || null : null,
      fields,
    };
    try {
      await onCreated(placeholder, request);
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Could not create deal");
    } finally {
      setSubmitting(false);
    }
  };

  const subtypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "property_subtype")?.options ?? [];
  const listingTypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "listing_type")?.options ?? [];
  const signingAuthorityOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "signing_authority")?.options ?? [];
  const transactionTypeOptions =
    ADMIN_ENUM_CONDITIONS.find((c) => c.field === "transaction_type")?.options ?? [];

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close new deal"
        onClick={onClose}
        className="absolute inset-0 bg-background/60 backdrop-blur-sm"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex h-full w-full flex-col bg-card shadow-2xl sm:h-auto sm:max-h-[calc(100vh-3rem)] sm:w-full sm:max-w-[34rem] sm:rounded-2xl sm:border sm:border-border/60"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              New deal
            </div>
            <h2 id={titleId} className="mt-0.5 text-[1rem] font-semibold leading-tight text-foreground">
              Add a card to the board
            </h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="h-11 w-11 shrink-0" aria-label="Close">
            <CloseIcon className="h-4 w-4" />
          </Button>
        </div>
        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
          <div>
            <label className="font-mono-ui block text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground" htmlFor={`${titleId}-side`}>
              Side
            </label>
            <div id={`${titleId}-side`} role="radiogroup" className="mt-1.5 grid grid-cols-2 gap-2">
              {(["listing", "buyer"] as AdminSide[]).map((option) => {
                const active = side === option;
                const Icon = option === "listing" ? Home : Users;
                return (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setSide(option)}
                    className={cn(
                      "flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-[0.86rem] font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30",
                      active
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border/60 bg-background/40 text-muted-foreground hover:border-border hover:text-foreground",
                    )}
                  >
                    <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
                    {ADMIN_SIDE_LABELS[option].title}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label htmlFor={`${titleId}-province`} className="font-mono-ui block text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              Province / territory <span className="text-destructive">*</span>
            </label>
            <select
              id={`${titleId}-province`}
              value={province}
              onChange={(e) => setProvince(e.target.value)}
              required
              className="mt-1.5 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.88rem] text-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option value="">Select province</option>
              {CANADIAN_PROVINCES.map(({ code, label }) => {
                const coverage = provinceCoverageByCode.get(code);
                const suffix = coverage?.hasTransactionGuide ? " - full guide" : coverage ? " - reference" : "";
                return (
                  <option key={code} value={code}>
                    {label}
                    {suffix}
                  </option>
                );
              })}
            </select>
            {selectedProvinceCoverage && (
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span className="font-mono-ui rounded border border-border/50 bg-background/40 px-1.5 py-0.5 text-[0.58rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {selectedProvinceCoverage.hasTransactionGuide ? "full guide" : "reference"}
                </span>
                <span className="font-mono-ui rounded border border-border/50 bg-background/40 px-1.5 py-0.5 text-[0.58rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {selectedProvinceCoverage.referencePages} pages
                </span>
                {selectedProvinceCoverage.forms > 0 && (
                  <span className="font-mono-ui rounded border border-border/50 bg-background/40 px-1.5 py-0.5 text-[0.58rem] uppercase tracking-[0.12em] text-muted-foreground">
                    {selectedProvinceCoverage.forms} forms
                  </span>
                )}
              </div>
            )}
          </div>

          <div>
            <label htmlFor={`${titleId}-contact`} className="font-mono-ui block text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              Contact (optional)
            </label>
            {selectedContact ? (
              <div className="mt-1.5 rounded-lg border border-primary/40 bg-primary/5 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[0.92rem] font-semibold text-foreground">
                      {selectedContact.displayName ?? "(unnamed)"}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.74rem] text-muted-foreground">
                      {selectedContact.primaryEmail && (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3 w-3" aria-hidden />
                          <span className="truncate">{selectedContact.primaryEmail}</span>
                        </span>
                      )}
                      {selectedContact.primaryPhone && (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" aria-hidden />
                          <span>{selectedContact.primaryPhone}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <Button type="button" variant="ghost" size="sm" onClick={clearContact} className="shrink-0">
                    Change
                  </Button>
                </div>
                {(selectedContact.type || selectedContact.stage || selectedContact.sourceKey) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {selectedContact.type && (
                      <span className="font-mono-ui rounded border border-border/60 bg-background/50 px-1.5 py-0.5 text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                        {selectedContact.type}
                      </span>
                    )}
                    {selectedContact.stage && (
                      <span className="font-mono-ui rounded border border-border/60 bg-background/50 px-1.5 py-0.5 text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                        {selectedContact.stage}
                      </span>
                    )}
                    {selectedContact.sourceKey && (
                      <span className="font-mono-ui rounded border border-border/60 bg-background/50 px-1.5 py-0.5 text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                        src: {selectedContact.sourceKey}
                      </span>
                    )}
                  </div>
                )}
                {(selectedContact.lastActivityAt || selectedContact.ownerNotes) && (
                  <div className="mt-2 space-y-1 border-t border-primary/20 pt-2 text-[0.72rem] text-muted-foreground">
                    {selectedContact.lastActivityAt && (
                      <div className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" aria-hidden />
                        <span>last activity {isoTimeAgo(selectedContact.lastActivityAt)}</span>
                      </div>
                    )}
                    {selectedContact.ownerNotes && (
                      <div className="line-clamp-2 italic">"{selectedContact.ownerNotes}"</div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <>
                <input
                  id={`${titleId}-contact`}
                  type="text"
                  value={contactQuery}
                  onChange={(e) => setContactQuery(e.target.value)}
                  placeholder={contactsLoading ? "Loading contacts…" : "Search by name, email, phone"}
                  className="mt-1.5 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.88rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
                  autoComplete="off"
                />
                {contactsError && (
                  <div className="mt-1 text-[0.72rem] text-warning">{contactsError}</div>
                )}
                {filteredContacts.length > 0 && (
                  <div className="mt-1.5 max-h-48 overflow-y-auto rounded-lg border border-border/40 bg-background/50">
                    {filteredContacts.map((contact) => (
                      <button
                        key={contact.id}
                        type="button"
                        onClick={() => handleSelectContact(contact)}
                        className="flex w-full items-start gap-3 border-b border-border/30 px-3 py-2 text-left last:border-b-0 hover:bg-background/80 focus:outline-none focus:bg-background/80"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[0.86rem] font-medium text-foreground">
                            {contact.displayName ?? "(unnamed)"}
                          </div>
                          <div className="truncate text-[0.72rem] text-muted-foreground">
                            {contact.primaryEmail ?? contact.primaryPhone ?? "no contact info"}
                          </div>
                        </div>
                        {contact.type && (
                          <span className="font-mono-ui shrink-0 text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                            {contact.type}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                {!contactsLoading && contacts.length === 0 && !contactsError && (
                  <div className="mt-1 text-[0.72rem] text-muted-foreground">
                    No contacts in DB yet. Skip this field or sync your CRM first.
                  </div>
                )}
              </>
            )}
          </div>

          <div>
            <label htmlFor={`${titleId}-title`} className="font-mono-ui block text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              Title <span className="text-destructive">*</span>
            </label>
            <input
              id={`${titleId}-title`}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={side === "listing" ? "e.g. Lewis Creek seller" : "e.g. Tessa & Ryan"}
              required
              className="mt-1.5 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.88rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          <div>
            <label htmlFor={`${titleId}-stage`} className="font-mono-ui block text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              Starting stage
            </label>
            <select
              id={`${titleId}-stage`}
              value={stage}
              onChange={(e) => setStage(toAdminStage(Number(e.target.value)))}
              className="mt-1.5 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.88rem] text-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
            >
              {ADMIN_STAGE_NUMBERS.map((s) => {
                const def = adminStageDefinition(s);
                return (
                  <option key={s} value={s}>
                    {def.stageNumber} · {def.labels[side].title}
                  </option>
                );
              })}
            </select>
          </div>

          <div className="space-y-3 rounded-lg border border-border/40 bg-background/30 px-3 py-3">
            <div className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              {side === "listing" ? "Property" : "Search"}
            </div>
            {side === "listing" && (
              <div>
                <label htmlFor={`${titleId}-address`} className="block text-[0.74rem] text-muted-foreground">
                  Listing address
                </label>
                <input
                  id={`${titleId}-address`}
                  type="text"
                  value={listingAddress}
                  onChange={(e) => setListingAddress(e.target.value)}
                  placeholder="e.g. 123 Lewis Creek Rd, Kelowna BC"
                  className="mt-1 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.86rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor={`${titleId}-subtype`} className="block text-[0.74rem] text-muted-foreground">
                  Property type
                </label>
                <select
                  id={`${titleId}-subtype`}
                  value={propertySubtype}
                  onChange={(e) => setPropertySubtype(e.target.value)}
                  className="mt-1 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
                >
                  <option value="">— select —</option>
                  {subtypeOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {side === "listing" ? (
                <div>
                  <label htmlFor={`${titleId}-listing-type`} className="block text-[0.74rem] text-muted-foreground">
                    Listing type
                  </label>
                  <select
                    id={`${titleId}-listing-type`}
                    value={listingType}
                    onChange={(e) => setListingType(e.target.value)}
                    className="mt-1 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
                  >
                    <option value="">— select —</option>
                    {listingTypeOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div>
                  <label htmlFor={`${titleId}-tx-type`} className="block text-[0.74rem] text-muted-foreground">
                    Transaction type
                  </label>
                  <select
                    id={`${titleId}-tx-type`}
                    value={transactionType}
                    onChange={(e) => setTransactionType(e.target.value)}
                    className="mt-1 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
                  >
                    <option value="">— select —</option>
                    {transactionTypeOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {side === "listing" && (
              <div>
                <label htmlFor={`${titleId}-signing`} className="block text-[0.74rem] text-muted-foreground">
                  Signing authority
                </label>
                <select
                  id={`${titleId}-signing`}
                  value={signingAuthority}
                  onChange={(e) => setSigningAuthority(e.target.value)}
                  className="mt-1 h-11 w-full rounded-lg border border-border/60 bg-background px-3 text-[0.86rem] text-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
                >
                  <option value="">— select —</option>
                  {signingAuthorityOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label htmlFor={`${titleId}-notes`} className="font-mono-ui block text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
                Notes
              </label>
              {notesAutoFilled && (
                <span className="font-mono-ui text-[0.6rem] uppercase tracking-[0.12em] text-primary">
                  auto-filled from contact
                </span>
              )}
            </div>
            <textarea
              id={`${titleId}-notes`}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
                if (notesAutoFilled) setNotesAutoFilled(false);
              }}
              rows={3}
              placeholder="Anything relevant to start this deal — context, urgency, source"
              className="mt-1.5 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-[0.86rem] text-foreground placeholder:text-muted-foreground focus:border-border focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          {submitError && (
            <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-[0.78rem] text-destructive">
              {submitError}
            </div>
          )}

          <div className="mt-auto flex items-center justify-end gap-2 border-t border-border/60 pt-3">
            <Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Create deal
            </Button>
          </div>
        </form>
      </aside>
    </div>,
    document.body,
  );
}

function AdminKanbanBoard() {
  const adminDeals = useAdminDeals();
  const cards = adminDeals.deals;
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [activeSide, setActiveSide] = useState<AdminSide>("listing");
  const [showNewDeal, setShowNewDeal] = useState(false);
  const draggingIdRef = useRef<string | null>(null);

  const handleCreateDeal = useCallback(
    async (placeholder: AdminCard, request: AdminDealCreateRequest) => {
      adminDeals.addLocalDeal(placeholder);
      setActiveSide(placeholder.side);
      try {
        const created = await api.createAdminDeal(request);
        adminDeals.replaceLocalDeal(placeholder.id, created);
      } catch (err) {
        if (isApiNotFound(err)) {
          console.warn("POST /api/admin/deals returned 404; keeping optimistic local card.");
          return;
        }
        throw err;
      }
    },
    [adminDeals],
  );

  const selectedCard = cards.find((c) => c.id === selectedCardId) ?? null;

  const buckets = useMemo(() => {
    const empty = (): Record<AdminStageNumber, AdminCard[]> => ({
      0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [], 8: [], 9: [],
    });
    const byStage: Record<AdminSide, Record<AdminStageNumber, AdminCard[]>> = {
      listing: empty(),
      buyer: empty(),
    };
    const counts: Record<AdminSide, number> = { listing: 0, buyer: 0 };
    for (const card of cards) {
      byStage[card.side][card.stage].push(card);
      counts[card.side] += 1;
    }
    return { byStage, counts };
  }, [cards]);

  const handleMoveToNext = useCallback(
    (cardId: string) => {
      const card = cards.find((candidate) => candidate.id === cardId);
      const nextStage = card ? adminNextStage(card) : null;
      if (nextStage != null) void adminDeals.moveDeal(cardId, nextStage);
    },
    [adminDeals, cards],
  );

  const handleToggleItem = useCallback(
    (cardId: string, itemId: string, completed: boolean) => {
      void adminDeals.setDealToggle(cardId, itemId, completed);
    },
    [adminDeals],
  );

  const handleConditionChange = useCallback(
    (cardId: string, field: AdminConditionField, value: AdminConditionValue) => {
      void adminDeals.setDealToggle(cardId, field, value);
    },
    [adminDeals],
  );

  const handleCardDragStart = useCallback((cardId: string) => {
    draggingIdRef.current = cardId;
  }, []);

  const handleCardDrop = useCallback(
    (targetSide: AdminSide, targetStage: AdminStageNumber) => {
      const draggedId = draggingIdRef.current;
      draggingIdRef.current = null;
      if (!draggedId) return;
      const card = cards.find((candidate) => candidate.id === draggedId);
      if (!card) return;
      if (card.side !== targetSide) return; // cross-side moves not supported
      if (card.stage === targetStage) return;
      void adminDeals.moveDeal(draggedId, targetStage);
    },
    [adminDeals, cards],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-border/50 bg-card/30 px-3 py-2">
        <div role="status" aria-live="polite" className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
            {cards.length} admin deals
          </span>
          {adminDeals.loading && (
            <span className="inline-flex items-center gap-1 font-mono-ui text-[0.62rem] uppercase tracking-[0.14em] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              loading
            </span>
          )}
          {adminDeals.usingDevFallback && (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-mono-ui text-[0.58rem] uppercase tracking-[0.14em] text-warning">
              dev-fallback
            </span>
          )}
          {adminDeals.error && (
            <span className="truncate text-[0.72rem] text-warning">{adminDeals.error}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => setShowNewDeal(true)}>
            <Plus className="h-3.5 w-3.5" />
            New deal
          </Button>
          <Button variant="outline" size="sm" onClick={() => void adminDeals.refresh()} disabled={adminDeals.loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", adminDeals.loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>
      <AdminTop25Strip
        cards={cards}
        devFallback={adminDeals.usingDevFallback}
        onCardSelect={setSelectedCardId}
        onCardDragStart={handleCardDragStart}
      />
      {!adminDeals.loading && !adminDeals.error && cards.length === 0 && (
        <div className="rounded-2xl border border-dashed border-border/60 bg-card/25 px-4 py-6 text-center">
          <div className="text-[0.95rem] font-semibold text-foreground">No saved transaction files yet</div>
          <div className="mx-auto mt-1 max-w-xl text-[0.78rem] leading-5 text-muted-foreground">
            Create a real deal or push a qualified profile from Leads. The Admin board will stay empty until a saved source-of-truth deal exists.
          </div>
          <Button className="mt-3" size="sm" onClick={() => setShowNewDeal(true)}>
            <Plus className="h-3.5 w-3.5" />
            New deal
          </Button>
        </div>
      )}
      <div role="tablist" aria-label="Deal side" className="flex items-center gap-1 border-b border-border/60">
        {(["listing", "buyer"] as AdminSide[]).map((side) => {
          const active = activeSide === side;
          const Icon = side === "listing" ? Home : Users;
          return (
            <button
              key={side}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveSide(side)}
              className={cn(
                "-mb-px inline-flex min-h-11 items-center gap-2 border-b-2 px-3 py-2 text-[0.86rem] font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30",
                active
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className={cn("h-4 w-4", active ? "text-primary" : "text-muted-foreground")} />
              <span>{ADMIN_SIDE_LABELS[side].title}</span>
              <span
                className={cn(
                  "font-mono-ui text-[0.65rem] uppercase tracking-wider",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                {buckets.counts[side]}
              </span>
            </button>
          );
        })}
      </div>
      <AdminKanbanSwimlane
        side={activeSide}
        title={ADMIN_SIDE_LABELS[activeSide].title}
        description={ADMIN_SIDE_LABELS[activeSide].description}
        cardsByStage={buckets.byStage[activeSide]}
        totalCount={buckets.counts[activeSide]}
        onCardSelect={setSelectedCardId}
        onCardDragStart={handleCardDragStart}
        onCardDrop={handleCardDrop}
      />
      {selectedCard && (
        <AdminCardDetailPanel
          card={selectedCard}
          onClose={() => setSelectedCardId(null)}
          onToggleItem={(_stage, itemId, completed) => handleToggleItem(selectedCard.id, itemId, completed)}
          onConditionChange={(field, value) => handleConditionChange(selectedCard.id, field, value)}
          onMoveToNext={() => handleMoveToNext(selectedCard.id)}
          onDealUpdated={(deal) => adminDeals.replaceLocalDeal(selectedCard.id, deal)}
        />
      )}
      {showNewDeal && (
        <NewDealDialog onClose={() => setShowNewDeal(false)} onCreated={handleCreateDeal} />
      )}
    </div>
  );
}

export function RealEstateAdminPage() {
  const data = useRealEstateHubData();
  const adminSetup = useAdminSetup();
  useHubHeader("Admin", data);
  useEffect(() => {
    if (!adminSetup.setup?.complete) return;
    let cancelled = false;
    (async () => {
      try {
        const [cronDefaults, actionDefaults] = await Promise.all([
          api.ensureLaneCronJobs(DEFAULT_ADMIN_AUTOMATIONS),
          api.ensureDefaultAdminActions(),
        ]);
        const changedCronDefaults = cronDefaults.created.length + (cronDefaults.updated?.length ?? 0);
        const changedActionDefaults = actionDefaults.created.length + (actionDefaults.updated?.length ?? 0);
        if (!cancelled && (changedCronDefaults > 0 || changedActionDefaults > 0)) {
          await data.refresh();
        }
      } catch {
        // Best-effort defaults. Existing cron jobs still render, and the Cron
        // page/action registry can create these manually if the backend is unavailable.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [adminSetup.setup?.complete, data.refresh]);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ADMIN_WORKFLOW_KEYWORDS),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ADMIN_WORKFLOW_KEYWORDS),
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
      {adminSetup.loading && (
        <div className="rounded-2xl border border-border/50 bg-card/30 px-4 py-5 text-[0.86rem] text-muted-foreground">
          <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
          Loading Admin setup
        </div>
      )}
      {adminSetup.error && (
        <div className="rounded-2xl border border-warning/35 bg-warning/10 px-4 py-3 text-[0.84rem] text-warning">
          {adminSetup.error}
        </div>
      )}
      {!adminSetup.loading && adminSetup.setup && !adminSetup.setup.complete && (
        <AdminSetupLaunch setup={adminSetup.setup} onSetupUpdated={adminSetup.setSetup} />
      )}
      {!adminSetup.loading && adminSetup.setup && !adminSetup.setup.complete && (
        <TimedTasks jobs={jobs} empty="No admin/document schedules are installed yet." title="Admin automations" />
      )}
      {!adminSetup.loading && adminSetup.setup?.complete && (
        <>
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/admin/templates" className="inline-flex">
          <Button variant="outline" size="sm">
            <FileCheck2 className="h-3.5 w-3.5" />
            Templates
          </Button>
        </Link>
      </div>
      <AdminKanbanBoard />
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
        empty="No admin-specific sessions found yet. CMA, seller updates, MLC, signing packages, WebForms, and listing/deal cron work will land here."
      />
        </>
      )}
    </HubShell>
  );
}

export function RealEstateSocialMediaPage() {
  const data = useRealEstateHubData();
  useHubHeader("Social Media", data);

  const [snapshot, setSnapshot] = useState<SocialSnapshot | null>(null);
  const [ideas, setIdeas] = useState<SocialIdea[]>([]);
  const [recentPosts, setRecentPosts] = useState<SocialMetricRow[]>([]);
  const [loadingSocial, setLoadingSocial] = useState(true);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [socialError, setSocialError] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [selectedPost, setSelectedPost] = useState<SocialMetricRow | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [postLimit, setPostLimit] = useState<number>(100);
  const [lookbackDays, setLookbackDays] = useState<number>(730);
  const tabIdPrefix = useId();
  const panelId = useId();
  const activeTabId = `${tabIdPrefix}-tab-${platformFilter}`;
  const refreshAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    refreshAbortRef.current?.abort();
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    const { signal } = controller;
    setLoadingSocial(true);
    setSocialError(null);
    try {
      const [snapRes, ideaRes, recentRes] = await Promise.allSettled([
        api.getSocialSnapshot(signal),
        api.getSocialIdeas("pending", signal),
        api.getSocialRecentPosts(1000, signal),
      ]);
      if (signal.aborted) return;
      if (snapRes.status === "fulfilled") setSnapshot(snapRes.value);
      if (ideaRes.status === "fulfilled") setIdeas(ideaRes.value.items || []);
      if (recentRes.status === "fulfilled") setRecentPosts(recentRes.value.items || []);
    } catch (e) {
      if (signal.aborted) return;
      setSocialError(e instanceof Error ? e.message : "Failed to load social data");
    } finally {
      if (!signal.aborted) setLoadingSocial(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      refreshAbortRef.current?.abort();
    };
  }, [refresh]);

  useEffect(() => {
    setPostLimit(100);
  }, [platformFilter]);

  const handleIdeaAction = useCallback(
    async (recordId: string, action: "approve" | "reject" | "edit", edit?: Partial<SocialIdea>) => {
      setActingOn(recordId);
      try {
        await api.socialIdeaAction(recordId, { action, ...(edit ? { edit } : {}) });
        await refresh();
      } catch (e) {
        setSocialError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActingOn(null);
      }
    },
    [refresh],
  );

  const totals = snapshot?.totals;
  const platforms = snapshot?.platforms || {};
  const platformList = Object.entries(platforms);

  const avgEngagement = useMemo(() => {
    const vals = platformList
      .map(([, p]) => p.averages?.engagement_rate)
      .filter((v): v is number => v != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [platformList]);

  const avgHook = useMemo(() => {
    const vals = platformList
      .map(([, p]) => p.averages?.hook_rate)
      .filter((v): v is number => v != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }, [platformList]);

  const wow = snapshot?.wow_delta;

  const platformCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of recentPosts) {
      const p = (r.platform || "").toLowerCase();
      if (!p) continue;
      counts[p] = (counts[p] || 0) + 1;
    }
    return counts;
  }, [recentPosts]);

  const filteredPosts = useMemo(() => {
    const base = recentPosts.filter(
      (r) => (r.media_type || "").toUpperCase() !== "ACCOUNT",
    );
    if (platformFilter === "all") return base;
    return base.filter((r) => (r.platform || "").toLowerCase() === platformFilter);
  }, [recentPosts, platformFilter]);

  const topPerformers = useMemo(() => {
    const scored = recentPosts
      .map((r) => ({ row: r, score: computeEngagementScore(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3);
    return scored.map((x) => x.row);
  }, [recentPosts]);

  const handleRefreshAll = useCallback(async () => {
    setRefreshing("all");
    setSocialError(null);
    try {
      await api.refreshSocialMetrics({ lookbackDays, maxPosts: 200 });
      await refresh();
    } catch (e) {
      setSocialError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(null);
    }
  }, [refresh, lookbackDays]);

  const summaryStats: Array<{ label: string; value: string | number }> = [
    { label: "Posts", value: totals?.post_count ?? 0 },
    { label: "Reach", value: formatCompact(totals?.reach) },
    ...(avgEngagement != null
      ? [{ label: "Avg engagement", value: formatPct(avgEngagement, 2) }]
      : []),
    ...(avgHook != null
      ? [{ label: "Avg hook rate", value: formatPct(avgHook, 2) }]
      : []),
  ];

  return (
    <HubShell
      data={data}
      eyebrow="Social Studio"
      icon={Megaphone}
      title="Social Media · weekly content engine"
    >
      <WorkflowStrip items={summaryStats} />

      {socialError && (
        <div className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {socialError}
        </div>
      )}

      {snapshot && snapshot.exists === false && (
        <Card className="border-dashed">
          <CardContent className="py-6 text-center text-sm text-muted-foreground">
            <Sparkles className="mx-auto mb-2 h-5 w-5 text-muted-foreground/60" />
            No snapshot yet. The weekly content engine runs Mondays at 7am Pacific —
            once it pulls metrics from your connected platforms, this page comes alive.
            <div className="mt-2 text-[0.7rem] text-muted-foreground/70">
              {snapshot.message ?? "Connect at least one social platform in Channels to begin."}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              AI idea approval queue
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={ideas.length ? "warning" : "success"}>{ideas.length}</Badge>
              <Button
                size="sm"
                variant="ghost"
                onClick={refresh}
                disabled={loadingSocial}
                aria-label="Refresh idea queue"
                className="min-h-[44px] min-w-[44px]"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", loadingSocial && "animate-spin")} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {loadingSocial && !ideas.length ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : ideas.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border bg-background/25 px-6 py-12 text-center">
              <div className="mx-auto max-w-sm space-y-1.5">
                <h3 className="text-sm font-semibold text-foreground">No ideas waiting</h3>
                <p className="text-sm text-muted-foreground">
                  The engine queues 5–10 every Monday morning.
                </p>
              </div>
            </div>
          ) : (
            ideas.map((idea) => (
              <IdeaCard
                key={idea.source_record_id}
                idea={idea}
                busy={actingOn === idea.source_record_id}
                onAction={(action, edit) => handleIdeaAction(idea.source_record_id, action, edit)}
              />
            ))
          )}
        </CardContent>
      </Card>

      {platformList.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2">
                <Award className="h-4 w-4" />
                Per-platform performance
              </CardTitle>
              {wow && (
                <div className="font-mono-ui flex items-center gap-3 text-[0.7rem] text-muted-foreground">
                  <span>
                    Posts WoW{" "}
                    <span className={wow.post_count_delta >= 0 ? "text-success" : "text-destructive"}>
                      {wow.post_count_delta >= 0 ? "+" : ""}
                      {wow.post_count_delta}
                    </span>
                  </span>
                  {wow.engagement_rate_delta != null && (
                    <span>
                      Eng WoW{" "}
                      <span className={wow.engagement_rate_delta >= 0 ? "text-success" : "text-destructive"}>
                        {wow.engagement_rate_delta >= 0 ? "+" : ""}
                        {(wow.engagement_rate_delta * 100).toFixed(2)}pp
                      </span>
                    </span>
                  )}
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
              {platformList.map(([platform, block]) => (
                <PlatformBlockCard key={platform} platform={platform} block={block} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="space-y-1">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Activity className="h-4 w-4" />
                Your posts
              </CardTitle>
              <p className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                {recentPosts.length === 0
                  ? "Nothing pulled yet"
                  : `${recentPosts.length} pulled · last ${lookbackDays} days`}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="font-mono-ui flex items-center gap-1.5 text-[0.7rem] uppercase tracking-wider text-muted-foreground">
                <span>Lookback</span>
                <select
                  value={lookbackDays}
                  onChange={(e) => setLookbackDays(Number(e.target.value))}
                  disabled={refreshing !== null}
                  aria-label="Lookback period"
                  className="font-mono-ui min-h-[44px] rounded-md border border-border bg-background px-2 text-[0.75rem] uppercase tracking-wider text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                  <option value={180}>180 days</option>
                  <option value={365}>1 year</option>
                  <option value={730}>2 years</option>
                </select>
              </label>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefreshAll}
                disabled={refreshing !== null}
                className="font-mono-ui min-h-[44px] px-4 text-[0.75rem] uppercase tracking-wider"
              >
                {refreshing ? "pulling…" : "refresh from platforms"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-8">
          {recentPosts.length > 0 && (
            <div className="border-b border-border/40 pb-4">
              <PlatformTablist
                tabs={[
                  { label: "all", count: recentPosts.length },
                  ...Object.entries(platformCounts)
                    .sort(([, a], [, b]) => b - a)
                    .map(([p, c]) => ({ label: p, count: c })),
                ]}
                active={platformFilter}
                onChange={setPlatformFilter}
                idPrefix={tabIdPrefix}
                panelId={panelId}
              />
            </div>
          )}
          <div
            id={panelId}
            role="tabpanel"
            aria-labelledby={activeTabId}
            tabIndex={0}
            className="space-y-10 focus:outline-none"
          >
            {platformFilter === "youtube" ? (
              <YouTubeTabView posts={recentPosts} onSelect={setSelectedPost} />
            ) : (
              <>
                {(["instagram", "facebook", "tiktok"].includes(platformFilter) ||
                  platformFilter === "all") && (
                  <PlatformRankingsBlock posts={filteredPosts} onSelect={setSelectedPost} />
                )}
                {filteredPosts.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-border bg-background/25 px-6 py-16 text-center">
                    <div className="mx-auto max-w-md space-y-2">
                      <h3 className="text-base font-semibold text-foreground">
                        {recentPosts.length === 0 ? "No posts pulled yet" : "Nothing here"}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        {recentPosts.length === 0
                          ? "Click refresh from platforms above to pull live from every connected account."
                          : `No ${platformFilter} posts in the last ${lookbackDays} days. Connect ${platformFilter} or extend the lookback.`}
                      </p>
                    </div>
                  </div>
                ) : (
                  <section className="space-y-4" aria-labelledby="all-posts-heading">
                    <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                      <h3
                        id="all-posts-heading"
                        className="font-mono-ui text-[0.75rem] uppercase tracking-wider text-foreground"
                      >
                        All posts
                      </h3>
                      <span
                        className="font-mono-ui text-[0.7rem] uppercase tracking-wider tabular-nums text-muted-foreground"
                        aria-live="polite"
                      >
                        {Math.min(postLimit, filteredPosts.length)} of {filteredPosts.length}
                      </span>
                    </header>
                    <div className="grid gap-4 items-start grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
                      {(() => {
                        const topKeys = new Set(
                          platformFilter === "all"
                            ? topPerformers.map((r) => `${r.platform}:${r.post_id}`)
                            : [],
                        );
                        const ordered = [
                          ...filteredPosts.filter((r) => topKeys.has(`${r.platform}:${r.post_id}`)),
                          ...filteredPosts.filter((r) => !topKeys.has(`${r.platform}:${r.post_id}`)),
                        ];
                        return ordered.slice(0, postLimit).map((row) => (
                          <RealVideoCard
                            key={`${row.platform}:${row.post_id}`}
                            row={row}
                            onClick={() => setSelectedPost(row)}
                            highlight={topKeys.has(`${row.platform}:${row.post_id}`)}
                          />
                        ));
                      })()}
                    </div>
                    {filteredPosts.length > postLimit && (
                      <div className="mt-2 flex flex-wrap justify-center gap-2 border-t border-border/40 pt-6">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPostLimit((n) => n + 100)}
                          className="font-mono-ui min-h-[44px] px-4 text-[0.75rem] uppercase tracking-wider"
                        >
                          Show 100 more ({filteredPosts.length - postLimit} remaining)
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPostLimit(filteredPosts.length)}
                          className="font-mono-ui min-h-[44px] px-4 text-[0.75rem] uppercase tracking-wider"
                        >
                          Show all ({filteredPosts.length})
                        </Button>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {selectedPost && (
        <PostDetailModal row={selectedPost} onClose={() => setSelectedPost(null)} />
      )}
    </HubShell>
  );
}

// ---------------------------------------------------------------------------
// YouTube — tab inside /social-media. 16:9 cards, per-video metrics, rankings.
// ---------------------------------------------------------------------------

export function RealEstateTasksPage() {
  const data = useRealEstateHubData();
  const [accessStatus, setAccessStatus] = useState<AccessStatusResponse | null>(null);
  useHubHeader("Tasks", data);
  const activeSessions = data.sessions.filter((session) => session.is_active);
  const enabledJobs = data.cronJobs.filter((job) => job.enabled);
  const erroredJobs = data.cronJobs.filter((job) => job.last_error);
  const openActionRuns = data.actionRuns.filter(
    (run) => !["succeeded", "completed", "skipped", "cancelled"].includes(run.status),
  );
  const handoffs = data.snapshot?.handoffs;
  const worker = data.snapshot?.agentWorker;
  const memory = data.snapshot?.memory;
  const adminPackActive = Boolean(accessStatus?.packs.realEstateAdmin);

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

  return (
    <HubShell
      data={data}
      eyebrow="Task Board"
      hero="A practical view of what the local agent network is running now, what is scheduled, and where attention is needed."
      icon={CalendarClock}
      title="Agent handoffs, wake loops, automations, and sessions in one place."
    >
      <WorkflowStrip
        items={[
          { icon: Activity, label: "Active sessions", value: activeSessions.length },
          { icon: Bot, label: "Open handoffs", value: handoffs?.open ?? 0 },
          { icon: AlertTriangle, label: "Human waiting", value: handoffs?.waitingHuman ?? 0 },
          { icon: CalendarClock, label: "Enabled tasks", value: enabledJobs.length },
          { icon: Brain, label: "Memory queue", value: memory?.journal.pending ?? 0 },
          { icon: FileCheck2, label: "Task errors", value: erroredJobs.length },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <AgentHandoffsCard handoffs={handoffs} />
        <AgentWorkerCard memory={memory} worker={worker} />
      </div>
      {adminPackActive && (
        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <AdminDealTasks tasks={data.dealTasks} onChanged={data.refresh} />
          <AdminActionRuns runs={openActionRuns} onChanged={data.refresh} />
        </div>
      )}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <TimedTasks jobs={data.cronJobs} empty="No timed tasks have been created yet." title="All timed tasks" />
        <RecentSessions
          title="Active sessions"
          sessions={activeSessions}
          empty="No sessions are active right now."
        />
      </div>
      <div className="mt-4">
        <RecentSessions
          title="Recent sessions"
          sessions={data.sessions.filter((session) => !session.is_active).slice(0, 6)}
          empty="No recent sessions."
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
          { icon: DatabaseIcon, label: "Documents", value: memory?.documents ?? 0 },
          { icon: FileText, label: "Chunks", value: memory?.chunks ?? 0 },
          { icon: GitBranch, label: "Communities", value: memory?.community_reports ?? 0 },
          { icon: Network, label: "Relations", value: memory?.relations ?? 0 },
        ]}
      />
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_24rem]">
        <Card className="overflow-hidden bg-card/72 p-0">
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
