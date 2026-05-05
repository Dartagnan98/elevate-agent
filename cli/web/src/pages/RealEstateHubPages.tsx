import {
  createContext,
  forwardRef,
  lazy,
  memo,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
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
  Trophy,
  Award,
  ThumbsUp,
  ThumbsDown,
  Users,
  Video,
  XCircle,
  Zap,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AgentHubMemoryNode,
  AgentHubSnapshot,
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
  SourceInboxResponse,
  SourceInboxThread,
  SocialIdea,
  SocialMetricRow,
  SocialPlatformBlock,
  SocialSnapshot,
  StatusResponse,
  ThreadContextMessage,
  ThreadContextResponse,
} from "@/lib/api";
import { X as CloseIcon, StickyNote } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
const MemoryConstellation = lazy(() =>
  import("@/components/MemoryConstellation").then((m) => ({ default: m.MemoryConstellation })),
);
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";

type HubData = {
  cronJobs: CronJob[];
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const [hubResult, statusResult, sessionsResult, cronResult, sourceInboxResult] =
      await Promise.allSettled([
        api.getAgentHub(),
        api.getStatus(),
        api.getSessions(36),
        api.getCronJobs(),
        api.getSourceInbox(200),
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

  return { cronJobs, error, loading, refresh, sourceInbox, sessions, snapshot, status };
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

function sourceRecordCount(data: HubData, key: string): number {
  return Number(data.sourceInbox?.recordCounts?.[key] ?? 0);
}

function threadWhen(thread: SourceInboxThread): string {
  return thread.latestAt ? isoTimeAgo(thread.latestAt) : "unsynced";
}

function heatVariant(item: { heatLabel: string }): "default" | "success" | "warning" | "destructive" | "outline" {
  if (item.heatLabel === "hot") return "destructive";
  if (item.heatLabel === "warm") return "warning";
  if (item.heatLabel === "watch") return "success";
  return "outline";
}

type HeatTone = {
  dot: string;
  pill: string;
  text: string;
  ring: string;
  label: string;
};

function heatStyles(label: string): HeatTone {
  switch (label) {
    case "hot":
      return {
        dot: "bg-destructive",
        pill: "bg-destructive/12 text-destructive border-destructive/45",
        text: "text-destructive",
        ring: "ring-destructive/30",
        label: "Hot lead",
      };
    case "warm":
      return {
        dot: "bg-warning",
        pill: "bg-warning/12 text-warning border-warning/45",
        text: "text-warning",
        ring: "ring-warning/30",
        label: "Warm lead",
      };
    case "watch":
      return {
        dot: "bg-success",
        pill: "bg-success/12 text-success border-success/40",
        text: "text-success",
        ring: "ring-success/30",
        label: "Lead to watch",
      };
    case "dead":
      return {
        dot: "bg-foreground/30",
        pill: "bg-card text-foreground/55 border-border line-through",
        text: "text-foreground/55",
        ring: "ring-border",
        label: "Dead lead",
      };
    default:
      return {
        dot: "bg-foreground/40",
        pill: "bg-card text-foreground/70 border-border",
        text: "text-foreground/70",
        ring: "ring-border",
        label: "Cold lead",
      };
  }
}

function inboundWaitMinutes(thread: SourceInboxThread): number | null {
  if (!thread.latestAt) return null;
  if (thread.direction !== "inbound") return null;
  const ts = Date.parse(thread.latestAt);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, (Date.now() - ts) / 60000);
}

type ResponsePulse = {
  unanswered: number;
  median: number | null;
  longest: number | null;
  longestThread: SourceInboxThread | null;
  breached5: number;
  breached30: number;
  breached60: number;
};

function computeResponsePulse(threads: SourceInboxThread[]): ResponsePulse {
  const waits: Array<{ minutes: number; thread: SourceInboxThread }> = [];
  for (const thread of threads) {
    const minutes = inboundWaitMinutes(thread);
    if (minutes === null) continue;
    waits.push({ minutes, thread });
  }
  if (waits.length === 0) {
    return {
      unanswered: 0,
      median: null,
      longest: null,
      longestThread: null,
      breached5: 0,
      breached30: 0,
      breached60: 0,
    };
  }
  const sorted = waits.slice().sort((a, b) => a.minutes - b.minutes);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1
      ? sorted[mid].minutes
      : (sorted[mid - 1].minutes + sorted[mid].minutes) / 2;
  const longest = sorted[sorted.length - 1];
  return {
    unanswered: waits.length,
    median,
    longest: longest.minutes,
    longestThread: longest.thread,
    breached5: waits.filter((w) => w.minutes >= 5).length,
    breached30: waits.filter((w) => w.minutes >= 30).length,
    breached60: waits.filter((w) => w.minutes >= 60).length,
  };
}

function formatMinutes(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 1440) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes - h * 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  return `${Math.floor(minutes / 1440)}d`;
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

function leadThreadBuckets(threads: SourceInboxThread[]) {
  const hot = threads.filter((thread) => thread.heatLabel === "hot").slice(0, 10);
  const followUp = threads
    .filter((thread) => thread.heatLabel !== "hot" && (thread.direction === "inbound" || thread.heatLabel === "warm"))
    .slice(0, 10);
  const placed = new Set<string>([...hot, ...followUp].map((t) => t.id));
  const remaining = threads.filter((thread) => !placed.has(thread.id));
  const watch: SourceInboxThread[] = [];
  const seenSources = new Set<string>(
    [...hot, ...followUp].map((t) => String(t.sourceId ?? "")),
  );
  for (const thread of remaining) {
    const sid = String(thread.sourceId ?? "");
    if (!seenSources.has(sid) && watch.length < 10) {
      watch.push(thread);
      seenSources.add(sid);
    }
  }
  for (const thread of remaining) {
    if (watch.length >= 10) break;
    if (!watch.includes(thread)) watch.push(thread);
  }
  return { followUp, hot, watch };
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

function contactBuckets(profiles: SourceInboxProfile[]) {
  const crmContacts = profiles.filter((profile) => profile.hasCrm).slice(0, 12);
  const active = profiles
    .filter((profile) => !profile.hasCrm && profile.hasConversation && !profile.isPotentialLead)
    .slice(0, 8);
  const potential = profiles
    .filter((profile) => profile.isPotentialLead && !profile.hasCrm)
    .slice(0, 8);
  return { active, crmContacts, potential };
}

function profileWhen(profile: SourceInboxProfile): string {
  return profile.latestAt ? isoTimeAgo(profile.latestAt) : "unsynced";
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

  return (
    <div
      className={cn(
        "group transition-colors",
        variant === "card"
          ? "rounded-xl border border-border bg-card px-3 py-3 hover:bg-card/80"
          : "px-3 py-3 hover:bg-card/40",
      )}
    >
      <div className="flex items-start gap-3">
        <span
          aria-label={heat.label}
          role="img"
          className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", heat.dot)}
        />
        <div className="min-w-0 flex-1">
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
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/75">
            {thread.latestText}
          </p>
          <div className="font-mono-ui mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-muted-foreground">
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
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const drafts = allDrafts.filter((d) => !dismissedIds.has(d.id));
  const visibleDrafts = drafts.slice(0, pageSize);
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
          </div>
        )}
      </CardHeader>
      <CardContent
        className={cn(
          "relative",
          density === "compact"
            ? "grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3"
            : "space-y-3",
        )}
      >
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
                  "group rounded-xl border bg-card px-3 py-2.5 transition-colors hover:bg-card/80",
                  isFocused ? "border-primary/40 ring-2 ring-primary/30" : "border-border",
                  isSelected && "border-primary/50 bg-primary/5",
                )}
              >
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
          <div className="col-span-full px-4 py-10 text-center">
            <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
              Inbox empty
            </h4>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{fallbackEmpty}</p>
          </div>
        )}
        {selectedVisible.length > 0 && (
          <div
            className="sticky bottom-3 left-0 right-0 z-20 col-span-full mx-auto flex w-fit max-w-full items-center gap-2 rounded-full border border-border bg-card px-3 py-2 shadow-[0_18px_48px_color-mix(in_srgb,var(--background-base)_55%,transparent)]"
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

type ThreadDrawerTarget = { sourceId: string; threadId: string } | null;

const ThreadDrawerContext = createContext<{
  openThread: (sourceId: string, threadId: string) => void;
} | null>(null);

function useThreadDrawer() {
  return useContext(ThreadDrawerContext);
}

export function ThreadDrawerProvider({
  children,
  data,
}: {
  children: ReactNode;
  data: HubData;
}) {
  const [target, setTarget] = useState<ThreadDrawerTarget>(null);
  const openThread = useCallback((sourceId: string, threadId: string) => {
    setTarget({ sourceId, threadId });
  }, []);
  const close = useCallback(() => setTarget(null), []);
  const ctx = useMemo(() => ({ openThread }), [openThread]);
  return (
    <ThreadDrawerContext.Provider value={ctx}>
      {children}
      {target && <ThreadDrawer data={data} target={target} onClose={close} />}
    </ThreadDrawerContext.Provider>
  );
}

function fmtMessageTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function ThreadMessageBubble({ message }: { message: ThreadContextMessage }) {
  const inbound = message.direction !== "outbound";
  return (
    <div className={cn("flex flex-col gap-1.5", inbound ? "items-start" : "items-end")}>
      <div
        className={cn(
          "max-w-[82%] rounded-2xl px-3.5 py-2.5 text-[0.875rem] leading-[1.45] whitespace-pre-wrap break-words text-foreground",
          inbound
            ? "bg-card border border-border"
            : "bg-primary/15 border border-primary/45",
        )}
      >
        {message.text || <span className="text-foreground/55 italic">(no text)</span>}
      </div>
      <div
        className="flex items-center gap-1.5 text-[0.68rem] uppercase tracking-[0.08em] text-foreground/55"
        style={{ fontFamily: "var(--theme-font-mono)" }}
      >
        {message.sender && <span className="font-medium">{message.sender}</span>}
        {message.sender && message.timestamp && <span>·</span>}
        {message.timestamp && <span>{fmtMessageTimestamp(message.timestamp)}</span>}
      </div>
    </div>
  );
}

function ThreadDrawer({
  data,
  target,
  onClose,
}: {
  data: HubData;
  target: { sourceId: string; threadId: string };
  onClose: () => void;
}) {
  const [context, setContext] = useState<ThreadContextResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getThreadContext(target.sourceId, target.threadId);
      setContext(result);
      setReply(result.pendingDraft?.draftText ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [target.sourceId, target.threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  useLayoutEffect(() => {
    if (!loading && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [loading, context?.messages.length]);

  const sendDraft = useCallback(
    async (action: "approve" | "skip") => {
      if (!context?.pendingDraft) return;
      setSubmitting(true);
      try {
        await api.updateSourceInboxDraft(
          context.pendingDraft.sourceId,
          context.pendingDraft.taskId,
          action,
          reply,
        );
        await data.refresh();
        onClose();
      } catch (err) {
        window.alert(`Failed to ${action} draft: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        setSubmitting(false);
      }
    },
    [context?.pendingDraft, data, onClose, reply],
  );

  const meta = context?.meta;
  const sends = context?.sends ?? [];
  const messages = context?.messages ?? [];

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 flex justify-end bg-black/55 backdrop-blur-sm animate-[fade-in_120ms_ease-out]"
    >
      <div
        className="flex h-full w-full max-w-[1100px] flex-col border-l border-border bg-background shadow-[0_24px_90px_rgba(0,0,0,0.32)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="truncate text-[1.05rem] font-semibold leading-tight text-foreground">
              {context?.personName ?? "Loading thread..."}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {context?.source?.label && (
                <Badge
                  variant="outline"
                  className="border-border text-foreground/85 text-[0.7rem] font-medium"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.source.label}
                </Badge>
              )}
              {context?.source?.ownerAgent && (
                <Badge
                  variant="outline"
                  className="border-border text-foreground/85 text-[0.7rem] font-medium"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.source.ownerAgent}
                </Badge>
              )}
              {meta?.label && (
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[0.7rem] font-semibold",
                    meta.label === "hot" && "border-destructive/60 bg-destructive/10 text-destructive",
                    meta.label === "warm" && "border-warning/60 bg-warning/10 text-warning",
                    meta.label === "cold" && "border-border text-foreground/75",
                    meta.label === "dead" && "border-border/60 text-foreground/55",
                  )}
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {meta.label} {typeof meta.score === "number" ? meta.score : ""}
                </Badge>
              )}
              {context && (
                <span
                  className="text-[0.7rem] font-medium uppercase tracking-[0.08em] text-foreground/65"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.messageCount} {context.messageCount === 1 ? "message" : "messages"}
                </span>
              )}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="text-foreground/75 hover:text-foreground">
            <CloseIcon className="h-4 w-4" />
          </Button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col border-r border-border">
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5">
              {loading && (
                <div className="flex items-center justify-center py-12 text-xs font-medium text-foreground/65">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading thread...
                </div>
              )}
              {error && (
                <div className="rounded-xl border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
                  {error}
                </div>
              )}
              {!loading && !error && messages.length === 0 && (
                <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-border bg-card/60 px-6 py-12 text-center">
                  <div
                    className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-foreground/55"
                    style={{ fontFamily: "var(--theme-font-mono)" }}
                  >
                    Empty thread
                  </div>
                  <div className="text-sm text-foreground/75">
                    No messages on file yet.
                  </div>
                </div>
              )}
              {!loading && messages.length > 0 && (
                <div className="space-y-4">
                  {messages.map((message) => (
                    <ThreadMessageBubble key={message.id || `${message.timestamp}-${message.text.slice(0, 12)}`} message={message} />
                  ))}
                </div>
              )}
            </div>

            {context?.pendingDraft && (
              <div className="border-t border-border bg-card/70 px-5 py-4">
                <div
                  className="mb-2 flex items-center justify-between text-[0.68rem] font-semibold uppercase tracking-[0.1em]"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  <span className="flex items-center gap-1.5 text-primary">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                    Draft reply · awaiting approval
                  </span>
                  <span className="text-foreground/65">{context.pendingDraft.channel}</span>
                </div>
                <textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  rows={4}
                  className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2.5 text-sm leading-5 text-foreground placeholder:text-foreground/45 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <div className="mt-2.5 flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void sendDraft("skip")}
                    disabled={submitting}
                    className="text-foreground/75 hover:text-foreground"
                  >
                    Skip
                  </Button>
                  <Button size="sm" onClick={() => void sendDraft("approve")} disabled={submitting || !reply.trim()}>
                    {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                    Send
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="min-h-0 overflow-y-auto bg-card/30 px-5 py-5">
            <ThreadContextSidebar context={context} loading={loading} sends={sends} />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function ThreadContextSidebar({
  context,
  loading,
  sends,
}: {
  context: ThreadContextResponse | null;
  loading: boolean;
  sends: ThreadContextResponse["sends"];
}) {
  if (loading || !context) {
    return (
      <div className="font-mono-ui text-[0.7rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground/80">
        Loading context...
      </div>
    );
  }
  const meta = context.meta;
  const lead = context.lead;
  const activity = context.activity ?? [];
  const sectionLabel =
    "font-mono-ui flex items-center gap-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-foreground/70";
  const sectionShell =
    "rounded-2xl border border-border bg-background px-3.5 py-3.5";
  const displayScore = meta?.score ?? lead?.score ?? null;
  const scoreLabel = meta?.label ?? (lead?.stage || lead?.leadSource || null);
  return (
    <div className="space-y-3.5">
      <section className={sectionShell}>
        <h4 className={sectionLabel}>Lead score</h4>
        {displayScore !== null ? (
          <>
            <div className="mt-2 flex items-baseline gap-2.5">
              <span className="text-[2.25rem] font-semibold leading-none tracking-tight text-primary">
                {displayScore}
              </span>
              {scoreLabel && (
                <span className="font-mono-ui text-[0.7rem] font-semibold uppercase tracking-[0.1em] text-foreground/70">
                  {scoreLabel}
                </span>
              )}
            </div>
            {meta?.reason && (
              <p className="mt-2.5 text-[0.8rem] leading-[1.5] text-foreground">{meta.reason}</p>
            )}
            {!meta && lead?.summary && (
              <p className="mt-2.5 text-[0.8rem] leading-[1.5] text-foreground">{lead.summary}</p>
            )}
            {lead && (lead.leadSource || lead.assignedUser || lead.tags.length > 0) && (
              <div className="mt-2.5 space-y-1.5">
                {lead.leadSource && (
                  <div className="flex items-center gap-1.5 text-[0.72rem] text-foreground/75">
                    <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground/80">
                      source
                    </span>
                    <span>{lead.leadSource}</span>
                  </div>
                )}
                {lead.assignedUser && (
                  <div className="flex items-center gap-1.5 text-[0.72rem] text-foreground/75">
                    <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground/80">
                      owner
                    </span>
                    <span>{lead.assignedUser}</span>
                  </div>
                )}
                {lead.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {lead.tags
                      .filter((t) => t !== "crm-lead" && !t.endsWith("-crm"))
                      .slice(0, 6)
                      .map((tag) => (
                        <span
                          key={tag}
                          className="font-mono-ui inline-flex items-center rounded-full border border-border/60 bg-card px-2 py-0.5 text-[0.65rem] font-medium text-foreground/75"
                        >
                          {tag}
                        </span>
                      ))}
                  </div>
                )}
              </div>
            )}
            {(meta?.scoredBy || meta?.scoredAt) && (
              <div className="font-mono-ui mt-2.5 text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                {meta.scoredBy ? `by ${meta.scoredBy}` : null}
                {meta.scoredBy && meta.scoredAt ? " · " : ""}
                {meta.scoredAt ? fmtMessageTimestamp(meta.scoredAt) : ""}
              </div>
            )}
          </>
        ) : (
          <p className="mt-2 text-[0.8rem] text-muted-foreground">Not yet scored.</p>
        )}
      </section>

      {lead && (lead.emails.length > 0 || lead.phones.length > 0) && (
        <section className={sectionShell}>
          <h4 className={sectionLabel}>Contact</h4>
          <div className="mt-2 space-y-1">
            {lead.phones.slice(0, 3).map((phone) => (
              <div key={phone} className="text-[0.8rem] text-foreground">
                {phone}
              </div>
            ))}
            {lead.emails.slice(0, 3).map((email) => (
              <div key={email} className="truncate text-[0.8rem] text-foreground">
                {email}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={sectionShell}>
        <h4 className={sectionLabel}>
          <StickyNote className="h-3 w-3" />
          Notes
        </h4>
        <p className="mt-2 text-[0.8rem] leading-[1.5] text-muted-foreground">
          {lead?.summary || "No notes yet."}
        </p>
      </section>

      <section className={sectionShell}>
        <h4 className={sectionLabel}>
          <Activity className="h-3 w-3" />
          Property activity
        </h4>
        {activity.length === 0 ? (
          <p className="mt-2 text-[0.8rem] leading-[1.5] text-muted-foreground">
            No activity logged yet.
          </p>
        ) : (
          <ul className="mt-2.5 space-y-2">
            {activity.slice(0, 6).map((event) => (
              <li key={event.id} className="rounded-xl border-b border-border/40 px-3 py-2 last:border-b-0">
                <div className="font-mono-ui flex items-center justify-between text-[0.66rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <span>{event.type.replace(/_/g, " ")}</span>
                  {event.timestamp && (
                    <span className="text-muted-foreground/80">{fmtMessageTimestamp(event.timestamp)}</span>
                  )}
                </div>
                {(event.title || event.summary) && (
                  <p className="mt-1.5 line-clamp-2 text-[0.8rem] leading-[1.45] text-foreground">
                    {event.title || event.summary}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={sectionShell}>
        <h4 className={sectionLabel}>Send history</h4>
        {sends.length === 0 ? (
          <p className="mt-2 text-[0.8rem] text-muted-foreground">No prior sends.</p>
        ) : (
          <ul className="mt-2.5 space-y-2">
            {sends.slice(0, 8).map((send) => (
              <li key={send.id} className="rounded-xl border-b border-border/40 px-3 py-2.5 last:border-b-0">
                <div className="font-mono-ui flex items-center justify-between text-[0.66rem] font-semibold uppercase tracking-[0.08em]">
                  <span className="text-foreground/75">{send.channel ?? "send"}</span>
                  <span
                    className={cn(
                      send.status === "sent" || send.status === "delivered"
                        ? "text-success"
                        : send.status === "failed"
                          ? "text-destructive"
                          : "text-muted-foreground",
                    )}
                  >
                    {send.status ?? "unknown"}
                  </span>
                </div>
                {send.payload?.text && (
                  <p className="mt-1.5 line-clamp-3 text-[0.8rem] leading-[1.45] text-foreground">
                    {String(send.payload.text)}
                  </p>
                )}
                {send.createdAt && (
                  <div className="font-mono-ui mt-1.5 text-[0.65rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                    {fmtMessageTimestamp(send.createdAt)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
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
  threads,
}: {
  active: string | null;
  drafts: number;
  followUps: number;
  hot: number;
  onSelect: (id: string | null) => void;
  options: LeadSourceOption[];
  pulse?: ResponsePulse;
  threads: number;
}) {
  const stats: Array<{ label: string; value: number | string; tone: "warning" | "default" | "muted" | "destructive" }> = [
    { label: "Drafts to approve", value: drafts, tone: drafts > 0 ? "warning" : "muted" },
    { label: "Hot leads", value: hot, tone: hot > 0 ? "default" : "muted" },
    { label: "Open threads", value: threads, tone: "default" },
    { label: "Follow-ups scheduled", value: followUps, tone: "muted" },
  ];
  if (pulse) {
    stats.push({
      label: "Unanswered",
      value: pulse.unanswered,
      tone: pulse.breached30 > 0 ? "destructive" : pulse.unanswered > 0 ? "warning" : "muted",
    });
    stats.push({
      label: "Median wait",
      value: formatMinutes(pulse.median),
      tone: (pulse.median ?? 0) >= 30 ? "destructive" : (pulse.median ?? 0) >= 5 ? "warning" : "muted",
    });
    stats.push({
      label: "Longest wait",
      value: formatMinutes(pulse.longest),
      tone: (pulse.longest ?? 0) >= 60 ? "destructive" : (pulse.longest ?? 0) >= 30 ? "warning" : "muted",
    });
  }

  return (
    <div className="flex flex-col gap-2.5 rounded-2xl border border-border bg-card px-3.5 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5">
        {stats.map((stat) => (
          <div key={stat.label} className="flex items-baseline gap-1.5">
            <span
              className={cn(
                "text-base font-semibold tabular-nums leading-none",
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
        ))}
      </div>
      {options.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 border-t border-border/55 pt-2">
          <span className="font-mono-ui mr-0.5 inline-flex items-center gap-1 text-[0.66rem] uppercase tracking-[0.14em] text-muted-foreground">
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
              meta={`${option.drafts ? `${option.drafts} drafts · ` : ""}${option.threads}`}
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

type AgentLaneId = "new-outreach" | "hot-leads-watcher" | "follow-ups";

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

function OutreachLanesGrid({
  cronJobs,
  onChanged,
}: {
  cronJobs: CronJob[];
  onChanged: () => Promise<void>;
}) {
  return (
    <div className="flex flex-col gap-2">
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
    <div className="grid grid-cols-1 items-center gap-3 rounded-2xl border border-border bg-card px-3 py-2.5 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_auto]">
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
    <div className="space-y-2">
      <div className="flex items-center justify-between">
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
        <div className="rounded-2xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          Composio rejected the saved key. Update it in Config to import these channels.
        </div>
      ) : connections.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card px-3 py-2 text-xs text-foreground/70">
          No Composio accounts linked yet. Connect Instagram, Gmail, Twilio, or any other app from the Config page.
        </div>
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
      <CardContent className="flex flex-col gap-4">
        {live.length > 0 && (
          <div className="space-y-2">
            <h4 className="font-mono-ui text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground/80">
              Live
            </h4>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {live.map((source) => (
                <LiveChannelCard
                  key={source.id}
                  source={source}
                  threads={threadsBySource.get(source.id) ?? []}
                />
              ))}
            </div>
          </div>
        )}

        <ComposioChannelStrip />

        {available.length > 0 && (
          <div className="space-y-2">
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
      className="group block rounded-2xl border border-border/55 bg-card p-3 transition-colors hover:border-border hover:bg-card/80"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary ring-1 ring-primary/25">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
          {source.label}
        </div>
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
      <div className="font-mono-ui mt-2.5 text-[0.72rem] tabular-nums text-muted-foreground">
        <span className="text-warning">{compactCount(state.uncontacted)}</span> uncontacted ·{" "}
        <span className="text-success">{compactCount(state.contacted)}</span> contacted ·{" "}
        <span className="text-foreground">{compactCount(totalRecords)}</span> records
      </div>
      {source.nextOperatorStep && !source.connected && (
        <p className="mt-2 line-clamp-2 text-[0.72rem] leading-4 text-muted-foreground">
          {source.nextOperatorStep}
        </p>
      )}
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
      <Icon className="h-3 w-3" />
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
  { id: "inbox" as const, label: "Inbox", icon: Inbox },
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
      const { [id]: _drop, ...rest } = prev;
      return rest;
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
  const [tab, setTab] = useState<LeadTab>("inbox");

  const allThreads = data.sourceInbox?.threads ?? [];
  const allDrafts = data.sourceInbox?.drafts ?? [];
  const allSources = data.sourceInbox?.sources ?? [];

  const filterOptions = useMemo<LeadSourceOption[]>(() => {
    const seen = new Map<string, LeadSourceOption>();
    for (const source of allSources) {
      if (!source.connected && !source.importOnly) continue;
      seen.set(source.id, {
        id: source.id,
        label: source.label,
        drafts: 0,
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
    return Array.from(seen.values()).filter((option) => option.threads > 0 || option.drafts > 0);
  }, [allDrafts, allSources, allThreads]);

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

  return (
    <ThreadDrawerProvider data={data}>
    <HubShell
      data={data}
      eyebrow="Lead Desk"
      icon={Inbox}
      title="Today's sales moves."
    >
      <div className="flex w-full flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <LeadsTabBar active={tab} onChange={setTab} />
          {tab === "templates" && (
            <span className="text-xs text-foreground/70">
              Templates control what the agent says. Edits apply on the next lane run.
            </span>
          )}
        </div>

        {tab === "templates" ? (
          <TemplatesPanel />
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
          description="New Outreach, Hot Leads Watcher, Follow-ups."
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
          </>
        )}
      </div>
    </HubShell>
    </ThreadDrawerProvider>
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

function formatCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

function formatPct(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

// Total/cumulative time fields — show as hours. Returned in ms unless noted.
const MS_TOTAL_TIME_KEYS = new Set([
  "ig_reels_video_view_total_time",
  "post_video_view_time_organic",
]);
const MIN_TOTAL_TIME_KEYS = new Set([
  "estimated_minutes_watched", // YouTube — minutes
]);
// Per-view averages — show as seconds (hours would be too small to read).
const MS_AVG_TIME_KEYS = new Set([
  "ig_reels_avg_watch_time",
  "post_video_avg_time_watched",
]);
const SEC_AVG_TIME_KEYS = new Set([
  "avg_view_duration_sec",
]);
const PCT_KEYS = new Set([
  "engagement_rate",
  "hook_rate",
  "hold_rate",
  "avg_view_percentage",
]);

function formatHours(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0h";
  const h = ms / 3_600_000;
  if (h >= 100) return `${h.toFixed(0)}h`;
  if (h >= 10) return `${h.toFixed(1)}h`;
  if (h >= 1) return `${h.toFixed(2)}h`;
  // Sub-hour totals — degrade gracefully so we never claim "0h" on a real value.
  const m = ms / 60_000;
  if (m >= 1) return `${m.toFixed(1)}m`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatSeconds(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0s";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

function formatIsoDuration(iso: string): string {
  // PT#H#M#S → "1h 23m 4s"
  const re = /PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?/;
  const m = iso.match(re);
  if (!m) return iso;
  const [, h, mm, s] = m;
  const parts: string[] = [];
  if (h) parts.push(`${h}h`);
  if (mm) parts.push(`${mm}m`);
  if (s) parts.push(`${Math.round(Number(s))}s`);
  return parts.join(" ") || "0s";
}

function prettifyMetricKey(key: string): string {
  const map: Record<string, string> = {
    likes: "likes",
    comments: "comments",
    shares: "shares",
    saved: "saves",
    views: "views",
    reach: "reach",
    plays: "plays",
    impressions: "impressions",
    total_interactions: "total interactions",
    profile_visits: "profile visits",
    profile_activity: "profile activity",
    follows: "follows",
    navigation: "navigation",
    replies: "replies",
    ig_reels_video_view_total_time: "total watch time",
    ig_reels_avg_watch_time: "avg watch time",
    post_video_view_time_organic: "total watch time",
    post_video_avg_time_watched: "avg watch time",
    avg_view_duration_sec: "avg watch time",
    avg_view_percentage: "avg view %",
    estimated_minutes_watched: "total watch time",
    duration_iso: "duration",
    view_count: "views",
    like_count: "likes",
    comment_count: "comments",
    dislike_count: "dislikes",
    favorite_count: "favorites",
    engagement_rate: "engagement rate",
    hook_rate: "hook rate",
    hold_rate: "hold rate",
  };
  return map[key] ?? key.replace(/_/g, " ");
}

function formatMetricValue(key: string, value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") {
    if (key === "duration_iso" && value.startsWith("PT")) return formatIsoDuration(value);
    return value;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  if (PCT_KEYS.has(key)) return `${(value * 100).toFixed(1)}%`;
  if (MS_TOTAL_TIME_KEYS.has(key)) return formatHours(value);
  if (MIN_TOTAL_TIME_KEYS.has(key)) return formatHours(value * 60_000);
  if (MS_AVG_TIME_KEYS.has(key)) return formatSeconds(value);
  if (SEC_AVG_TIME_KEYS.has(key)) return formatSeconds(value * 1000);
  return formatCompact(value);
}

function platformDot(platform: string): string {
  const map: Record<string, string> = {
    instagram: "bg-[oklch(0.62_0.14_350)]",
    tiktok: "bg-[oklch(0.65_0.13_15)]",
    youtube: "bg-[oklch(0.58_0.16_30)]",
    facebook: "bg-[oklch(0.58_0.13_245)]",
    linkedin: "bg-[oklch(0.55_0.13_240)]",
  };
  return map[platform.toLowerCase()] ?? "bg-muted-foreground";
}

function IdeaCard({
  idea,
  onAction,
  busy,
}: {
  idea: SocialIdea;
  onAction: (action: "approve" | "reject" | "edit", edit?: Partial<SocialIdea>) => Promise<void>;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Partial<SocialIdea>>({
    hook: idea.hook,
    concept: idea.concept,
    best_post_time: idea.best_post_time ?? "",
    target_audience: idea.target_audience ?? "",
  });

  const grounded = idea.grounded_in || {};
  const chipTone = "bg-background/40 text-foreground/80 border-border/60";
  const groundedChips = [
    grounded.metric ? { label: "metric", text: grounded.metric, tone: chipTone } : null,
    grounded.trend ? { label: "trend", text: grounded.trend, tone: chipTone } : null,
    grounded.signal ? { label: "signal", text: grounded.signal, tone: chipTone } : null,
  ].filter((x): x is { label: string; text: string; tone: string } => !!x);

  return (
    <div className="rounded-xl bg-background/30 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("h-2 w-2 rounded-full", platformDot(idea.platform))} />
        <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-muted-foreground">
          {idea.platform} · {idea.format}
        </span>
        {idea.best_post_time && (
          <Badge variant="outline" className="text-[0.65rem]">
            <Clock className="mr-1 h-3 w-3" />
            {idea.best_post_time}
          </Badge>
        )}
      </div>

      {editing ? (
        <div className="space-y-2">
          <input
            value={draft.hook ?? ""}
            onChange={(e) => setDraft({ ...draft, hook: e.target.value })}
            placeholder="Hook (first 3 seconds)"
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium"
          />
          <textarea
            value={draft.concept ?? ""}
            onChange={(e) => setDraft({ ...draft, concept: e.target.value })}
            placeholder="Concept"
            rows={3}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              value={(draft.best_post_time as string) ?? ""}
              onChange={(e) => setDraft({ ...draft, best_post_time: e.target.value })}
              placeholder="Best post time"
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
            <input
              value={(draft.target_audience as string) ?? ""}
              onChange={(e) => setDraft({ ...draft, target_audience: e.target.value })}
              placeholder="Target audience"
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
        </div>
      ) : (
        <>
          <div className="text-sm font-semibold leading-snug text-foreground">{idea.hook}</div>
          <p className="text-xs leading-5 text-muted-foreground">{idea.concept}</p>
          {idea.outline && idea.outline.length > 0 && (
            <ol className="text-xs leading-5 text-muted-foreground space-y-0.5 pl-4 list-decimal">
              {idea.outline.slice(0, 4).map((beat, i) => (
                <li key={i}>{beat}</li>
              ))}
            </ol>
          )}
        </>
      )}

      {groundedChips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {groundedChips.map((chip) => (
            <span
              key={chip.label}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.65rem] font-medium",
                chip.tone,
              )}
              title={chip.text}
            >
              <span className="font-mono-ui uppercase tracking-wider">{chip.label}</span>
              <span className="max-w-[16rem] truncate">{chip.text}</span>
            </span>
          ))}
        </div>
      )}

      {idea.reasoning && !editing && (
        <p className="text-[0.7rem] italic leading-4 text-muted-foreground/80">
          {idea.reasoning}
        </p>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="text-[0.65rem] text-muted-foreground/70">
          {idea.timestamp ? isoTimeAgo(idea.timestamp) : ""}
        </div>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(false)}
                disabled={busy}
                className="min-h-[44px] px-3"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={async () => {
                  await onAction("edit", draft);
                  setEditing(false);
                }}
                disabled={busy}
                className="min-h-[44px] px-3"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save edit"}
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(true)}
                disabled={busy}
                aria-label="Edit idea"
                className="min-h-[44px] min-w-[44px]"
              >
                <PencilLine className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onAction("reject")}
                disabled={busy}
                aria-label="Reject idea"
                className="min-h-[44px] min-w-[44px] text-destructive hover:text-destructive"
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="sm"
                onClick={() => onAction("approve")}
                disabled={busy}
                aria-label="Approve idea"
                className="min-h-[44px] px-3"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
                <span className="ml-1">Approve</span>
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
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

  return (
    <HubShell
      data={data}
      eyebrow="Social Studio"
      icon={Megaphone}
      title="Social Media · weekly content engine"
    >
      <WorkflowStrip
        items={[
          { icon: Megaphone, label: "Posts (30d)", value: totals?.post_count ?? 0 },
          { icon: Activity, label: "Reach (30d)", value: formatCompact(totals?.reach) },
          ...(avgEngagement != null
            ? [{ icon: ThumbsUp, label: "Avg engagement", value: formatPct(avgEngagement, 2) }]
            : []),
          ...(avgHook != null
            ? [{ icon: Sparkles, label: "Avg hook rate", value: formatPct(avgHook, 2) }]
            : []),
        ]}
      />

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
        <CardContent className="space-y-3">
          {loadingSocial && !ideas.length ? (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : ideas.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-8 text-sm text-muted-foreground text-center">
              No ideas waiting. The engine queues 5–10 every Monday morning.
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
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Your posts
              <Badge variant="outline">{filteredPosts.length}</Badge>
            </CardTitle>
            <div className="flex items-center gap-2">
              <label className="font-mono-ui flex items-center gap-1.5 text-[0.65rem] uppercase tracking-wider text-muted-foreground">
                <span>Lookback</span>
                <select
                  value={lookbackDays}
                  onChange={(e) => setLookbackDays(Number(e.target.value))}
                  disabled={refreshing !== null}
                  className="font-mono-ui min-h-[44px] rounded-md border border-border bg-background px-2 text-[0.7rem] uppercase tracking-wider text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                >
                  <option value={30}>30d</option>
                  <option value={90}>90d</option>
                  <option value={180}>180d</option>
                  <option value={365}>1y</option>
                  <option value={730}>2y</option>
                </select>
              </label>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefreshAll}
                disabled={refreshing !== null}
                className="font-mono-ui min-h-[44px] px-4 text-[0.7rem] uppercase tracking-wider"
              >
                {refreshing ? "pulling…" : "refresh from platforms"}
              </Button>
            </div>
          </div>
          {recentPosts.length > 0 && (
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
          )}
        </CardHeader>
        <CardContent className="space-y-5">
          <div id={panelId} role="tabpanel" aria-labelledby={activeTabId} tabIndex={0} className="focus:outline-none">
            {platformFilter === "youtube" ? (
              <YouTubeTabView posts={recentPosts} onSelect={setSelectedPost} />
            ) : (
              <>
                {(["instagram", "facebook", "tiktok"].includes(platformFilter) ||
                  platformFilter === "all") && (
                  <PlatformRankingsBlock posts={filteredPosts} onSelect={setSelectedPost} />
                )}
                {filteredPosts.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-10 text-sm text-muted-foreground text-center">
                    {recentPosts.length === 0
                      ? "No posts pulled yet. Click \"refresh from platforms\" above to pull live from every connected account."
                      : `No ${platformFilter} posts.`}
                  </div>
                ) : (
                  <>
                    <div className="grid gap-3 items-start grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
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
                      <div className="flex justify-center pt-4">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPostLimit((n) => n + 100)}
                          className="font-mono-ui min-h-[44px] px-4 text-[0.7rem] uppercase tracking-wider"
                        >
                          Show more ({filteredPosts.length - postLimit} remaining)
                        </Button>
                      </div>
                    )}
                  </>
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

function ytNum(row: SocialMetricRow, key: string): number {
  const v = (row.metrics as Record<string, unknown>)?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function ytEngagementScore(row: SocialMetricRow): number {
  const likes = ytNum(row, "like_count");
  const comments = ytNum(row, "comment_count");
  const views = ytNum(row, "view_count");
  if (views <= 0) return 0;
  return (likes + comments * 2) / views;
}

function YouTubeTabView({
  posts,
  onSelect,
}: {
  posts: SocialMetricRow[];
  onSelect: (row: SocialMetricRow) => void;
}) {
  const ytAll = useMemo(
    () => posts.filter((p) => (p.platform || "").toLowerCase() === "youtube"),
    [posts],
  );
  const channelRow = useMemo(
    () => ytAll.find((p) => (p.media_type || "").toUpperCase() === "ACCOUNT"),
    [ytAll],
  );
  const videos = useMemo(
    () => ytAll.filter((p) => (p.media_type || "").toUpperCase() !== "ACCOUNT"),
    [ytAll],
  );
  const sumComments = useMemo(
    () => videos.reduce((a, r) => a + ytNum(r, "comment_count"), 0),
    [videos],
  );

  const channelMetrics = (channelRow?.metrics ?? {}) as Record<string, unknown>;
  const subCount =
    typeof channelMetrics.subscriber_count === "number" ? channelMetrics.subscriber_count : null;
  const channelViews =
    typeof channelMetrics.view_count === "number" ? channelMetrics.view_count : null;
  const videoCount =
    typeof channelMetrics.video_count === "number" ? channelMetrics.video_count : null;

  const rankings = useMemo(() => {
    const top = (key: string) =>
      [...videos]
        .sort((a, b) => ytNum(b, key) - ytNum(a, key))
        .filter((r) => ytNum(r, key) > 0)
        .slice(0, 3);
    const eng = [...videos]
      .map((r) => ({ row: r, score: ytEngagementScore(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((x) => x.row);
    const least = [...videos]
      .filter((r) => ytNum(r, "view_count") > 0)
      .sort((a, b) => ytNum(a, "view_count") - ytNum(b, "view_count"))
      .slice(0, 3);
    return {
      views: top("view_count"),
      likes: top("like_count"),
      comments: top("comment_count"),
      engagement: eng,
      least,
    };
  }, [videos]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <YouTubeStatTile label="Subscribers" value={formatCompact(subCount)} hint="lifetime" />
        <YouTubeStatTile label="Channel views" value={formatCompact(channelViews)} hint="lifetime" />
        <YouTubeStatTile label="Videos" value={formatCompact(videoCount)} hint="published" />
        <YouTubeStatTile
          label="Comments (pulled)"
          value={formatCompact(sumComments)}
          hint={`across ${videos.length} videos`}
        />
      </div>

      {videos.length > 0 && (
        <section aria-labelledby="yt-rankings-heading" className="space-y-3">
          <div className="flex items-center gap-2">
            <Trophy aria-hidden="true" className="h-4 w-4 text-warning" />
            <h3
              id="yt-rankings-heading"
              className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-foreground/80"
            >
              Rankings
            </h3>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
            <RankPanel
              title="Most views"
              rows={rankings.views}
              formatValue={(r) => formatCompact(ytNum(r, "view_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most likes"
              rows={rankings.likes}
              formatValue={(r) => formatCompact(ytNum(r, "like_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most comments"
              rows={rankings.comments}
              formatValue={(r) => formatCompact(ytNum(r, "comment_count"))}
              onSelect={onSelect}
            />
            <RankPanel
              title="Most engagement"
              rows={rankings.engagement}
              formatValue={(r) => `${(ytEngagementScore(r) * 100).toFixed(2)}%`}
              onSelect={onSelect}
            />
            <RankPanel
              title="Least views"
              rows={rankings.least}
              formatValue={(r) => formatCompact(ytNum(r, "view_count"))}
              onSelect={onSelect}
              tone="muted"
            />
          </div>
        </section>
      )}

      {videos.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-10 text-sm text-muted-foreground text-center">
          No YouTube videos pulled yet. Click "refresh from platforms" above to pull the channel.
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
          {videos
            .slice()
            .sort((a, b) => ytNum(b, "view_count") - ytNum(a, "view_count"))
            .map((row) => (
              <YouTubeVideoCard
                key={`${row.platform}:${row.post_id}`}
                row={row}
                onClick={() => onSelect(row)}
              />
            ))}
        </div>
      )}
    </div>
  );
}

function YouTubeStatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-background/40 px-3 py-3">
      <div className="font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-foreground tabular-nums">{value}</div>
      {hint && (
        <div className="mt-0.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground/70">
          {hint}
        </div>
      )}
    </div>
  );
}

function RankPanel({
  title,
  rows,
  formatValue,
  onSelect,
  tone,
}: {
  title: string;
  rows: SocialMetricRow[];
  formatValue: (row: SocialMetricRow) => string;
  onSelect: (row: SocialMetricRow) => void;
  tone?: "muted";
}) {
  return (
    <div className="rounded-xl bg-background/30 p-3 space-y-2">
      <div
        className={cn(
          "font-mono-ui text-[0.65rem] uppercase tracking-wider",
          tone === "muted" ? "text-muted-foreground" : "text-foreground/80",
        )}
      >
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/40 bg-background/20 px-2 py-3 text-center text-[0.7rem] text-muted-foreground">
          No data yet
        </div>
      ) : (
        <ol className="space-y-1.5">
          {rows.map((row, idx) => (
            <li key={`${row.post_id}-${idx}`}>
              <button
                type="button"
                onClick={() => onSelect(row)}
                className="group flex min-h-[44px] w-full items-center gap-2 rounded-lg border border-border/40 bg-background/30 px-2.5 py-2 text-left transition hover:border-primary/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              >
                <span className="font-mono-ui w-4 text-center text-[0.65rem] text-muted-foreground">
                  {idx + 1}
                </span>
                <span className="flex-1 truncate text-xs text-foreground/85 group-hover:text-foreground">
                  {row.caption || "(untitled)"}
                </span>
                <span className="font-mono-ui text-[0.7rem] tabular-nums text-foreground/90">
                  {formatValue(row)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cross-platform metric resolver. Each platform names the same concept
// differently — IG uses `likes`/`saved`/`shares`, FB uses `like_count`/
// `reaction_count`/`comments_count`, TikTok uses `digg_count`/`play_count`/
// `share_count`/`save_count`. Read in priority order; first hit wins.
// ---------------------------------------------------------------------------
const METRIC_LOOKUP: Record<string, string[]> = {
  views: [
    "views", "view_count", "plays", "play_count", "video_views",
    "post_video_views", "post_impressions",
  ],
  likes: ["likes", "like_count", "reaction_count", "digg_count"],
  comments: ["comments", "comment_count", "comments_count"],
  shares: ["shares", "share_count"],
  saves: ["saved", "saves", "save_count"],
  reach: ["reach"],
};

function readMetric(row: SocialMetricRow, logical: string): number {
  const m = (row.metrics || {}) as Record<string, unknown>;
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  for (const key of METRIC_LOOKUP[logical] || []) {
    for (const src of [m, raw, fbPost]) {
      const v = src[key];
      if (typeof v === "number" && Number.isFinite(v)) return v;
      if (typeof v === "string") {
        const n = Number(v);
        if (Number.isFinite(n)) return n;
      }
    }
  }
  return 0;
}

function genericEngagement(row: SocialMetricRow): number {
  const likes = readMetric(row, "likes");
  const comments = readMetric(row, "comments");
  const shares = readMetric(row, "shares");
  const saves = readMetric(row, "saves");
  const views = readMetric(row, "views");
  const total = likes + comments * 2 + shares * 3 + saves * 2;
  if (views > 0) return total / views;
  return 0;
}

function totalActivity(row: SocialMetricRow): number {
  return (
    readMetric(row, "likes") +
    readMetric(row, "comments") +
    readMetric(row, "shares") +
    readMetric(row, "saves")
  );
}

// Hook rate = % of people who watched after seeing the post.
// IG: views / reach. FB: post_video_views / post_impressions.
// TikTok Display API and YouTube Data API don't expose impressions/reach.
function derivedHookRate(row: SocialMetricRow): number | null {
  const platform = (row.platform || "").toLowerCase();
  const m = (row.metrics || {}) as Record<string, unknown>;
  const backend = m.hook_rate;
  if (typeof backend === "number" && Number.isFinite(backend) && backend > 0) {
    return backend;
  }
  if (platform === "instagram") {
    const views = readMetric(row, "views");
    const reach = readMetric(row, "reach");
    if (views > 0 && reach > 0) return Math.min(views / reach, 1);
    return null;
  }
  if (platform === "facebook") {
    const videoViews = Number(m.post_video_views) || 0;
    const impressions =
      Number(m.post_impressions) || Number(m.post_impressions_unique) || 0;
    if (videoViews > 0 && impressions > 0) return Math.min(videoViews / impressions, 1);
    return null;
  }
  return null;
}

// Hold rate = % of the video the average viewer watched.
// IG: ig_reels_avg_watch_time (ms) / duration_sec. Requires `duration` in fetcher.
// FB needs a separate /video?fields=length lookup (not yet wired).
// TikTok Display API has no avg_watch_time. YouTube Analytics API not exposed.
function derivedHoldRate(row: SocialMetricRow): number | null {
  const platform = (row.platform || "").toLowerCase();
  const m = (row.metrics || {}) as Record<string, unknown>;
  const backend = m.hold_rate;
  if (typeof backend === "number" && Number.isFinite(backend) && backend > 0) {
    return backend;
  }
  if (platform === "instagram") {
    const avgMs = Number(m.ig_reels_avg_watch_time) || 0;
    const durSec = Number(m.duration_sec ?? m.duration) || 0;
    if (avgMs > 0 && durSec > 0) return Math.min(avgMs / (durSec * 1000), 1);
    return null;
  }
  if (platform === "facebook") {
    // post_video_avg_time_watched is in milliseconds; need video length to ratio.
    const avgMs = Number(m.post_video_avg_time_watched) || 0;
    const raw = (row.raw || {}) as Record<string, unknown>;
    const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
    const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)
      ?.data as Array<Record<string, unknown>> | undefined)?.[0];
    const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
    const fbSrc = fbMedia.source as string | undefined;
    const lengthSec =
      Number((fbAttach as Record<string, unknown> | undefined)?.video_length) ||
      Number(fbMedia.length) ||
      0;
    if (avgMs > 0 && lengthSec > 0 && fbSrc) {
      return Math.min(avgMs / (lengthSec * 1000), 1);
    }
    return null;
  }
  return null;
}

function PlatformRankingsBlock({
  posts,
  onSelect,
}: {
  posts: SocialMetricRow[];
  onSelect: (row: SocialMetricRow) => void;
}) {
  // YouTube has its own block; ACCOUNT rows aren't posts.
  const eligible = useMemo(
    () =>
      posts.filter(
        (p) =>
          (p.platform || "").toLowerCase() !== "youtube" &&
          (p.media_type || "").toUpperCase() !== "ACCOUNT",
      ),
    [posts],
  );

  const panels = useMemo(() => {
    const top = (logical: string) =>
      [...eligible]
        .sort((a, b) => readMetric(b, logical) - readMetric(a, logical))
        .filter((r) => readMetric(r, logical) > 0)
        .slice(0, 3);
    const eng = [...eligible]
      .map((r) => ({ row: r, score: genericEngagement(r) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map((x) => x.row);
    const least = [...eligible]
      .filter((r) => totalActivity(r) > 0)
      .sort((a, b) => totalActivity(a) - totalActivity(b))
      .slice(0, 3);

    const fmtCount = (key: string) => (r: SocialMetricRow) => formatCompact(readMetric(r, key));
    return [
      { title: "Most views", rows: top("views"), format: fmtCount("views") },
      { title: "Most likes", rows: top("likes"), format: fmtCount("likes") },
      { title: "Most comments", rows: top("comments"), format: fmtCount("comments") },
      { title: "Most shares", rows: top("shares"), format: fmtCount("shares") },
      { title: "Most saves", rows: top("saves"), format: fmtCount("saves") },
      {
        title: "Most engagement",
        rows: eng,
        format: (r: SocialMetricRow) => `${(genericEngagement(r) * 100).toFixed(2)}%`,
      },
      {
        title: "Least performing",
        rows: least,
        format: (r: SocialMetricRow) => `${formatCompact(totalActivity(r))} ints`,
        tone: "muted" as const,
      },
    ].filter((p) => p.rows.length > 0);
  }, [eligible]);

  if (!panels.length) return null;

  return (
    <section aria-labelledby="rankings-heading" className="space-y-3">
      <div className="flex items-center gap-2">
        <Trophy aria-hidden="true" className="h-4 w-4 text-warning" />
        <h3
          id="rankings-heading"
          className="font-mono-ui text-[0.7rem] uppercase tracking-wider text-foreground/80"
        >
          Rankings
        </h3>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {panels.map((panel) => (
          <RankPanel
            key={panel.title}
            title={panel.title}
            rows={panel.rows}
            formatValue={panel.format}
            onSelect={onSelect}
            tone={panel.tone}
          />
        ))}
      </div>
    </section>
  );
}

function YouTubeVideoCard({
  row,
  onClick,
}: {
  row: SocialMetricRow;
  onClick: () => void;
}) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb;
  const m = (row.metrics || {}) as Record<string, unknown>;
  const caption = row.caption || "";
  const isShort = (row.media_type || "").toUpperCase() === "SHORT";
  const duration = m.duration_iso as string | undefined;

  const views = ytNum(row, "view_count");
  const likes = ytNum(row, "like_count");
  const comments = ytNum(row, "comment_count");
  const engagement = ytEngagementScore(row);

  const skipKeys = new Set([
    "view_count",
    "like_count",
    "comment_count",
    "duration_iso",
    "avg_view_duration_sec",
    "avg_view_percentage",
  ]);
  const extraChips: Array<{ label: string; value: string }> = [];
  for (const [k, v] of Object.entries(m)) {
    if (k.startsWith("_") || skipKeys.has(k)) continue;
    if (v == null) continue;
    if (typeof v !== "number" && typeof v !== "string") continue;
    extraChips.push({ label: prettifyMetricKey(k), value: formatMetricValue(k, v) });
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col text-left rounded-2xl border border-border/40 bg-background/30 overflow-hidden transition hover:border-border"
    >
      <div className="relative aspect-video w-full bg-background/40">
        {thumb ? (
          <img
            src={thumb}
            alt={caption ? caption.slice(0, 100) : ""}
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
            <Video className="h-8 w-8" />
          </div>
        )}
        <div className="absolute top-1.5 left-1.5 flex items-center gap-1 rounded-full bg-background/85 backdrop-blur px-2 py-0.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", platformDot("youtube"))} />
          <span className="font-mono-ui text-[0.6rem] uppercase tracking-wider">
            {isShort ? "short" : "video"}
          </span>
        </div>
        {duration && (
          <div className="absolute bottom-1.5 right-1.5 rounded bg-background/85 backdrop-blur px-1.5 py-0.5 font-mono-ui text-[0.6rem] tabular-nums">
            {formatIsoDuration(duration)}
          </div>
        )}
        {engagement > 0 && (
          <div className="absolute top-1.5 right-1.5 rounded bg-primary/90 px-1.5 py-0.5 font-mono-ui text-[0.6rem] uppercase tracking-wider text-primary-foreground">
            ER {(engagement * 100).toFixed(2)}%
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 p-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug text-foreground/90 group-hover:text-foreground">
          {caption || "(untitled)"}
        </h3>
        <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
          {row.posted_at ? isoTimeAgo(row.posted_at) : "—"}
        </div>
        <div className="grid grid-cols-3 gap-1.5 pt-1">
          <YouTubeMetricCell label="views" value={formatCompact(views)} />
          <YouTubeMetricCell label="likes" value={formatCompact(likes)} />
          <YouTubeMetricCell label="comments" value={formatCompact(comments)} />
        </div>
        {extraChips.length > 0 && (
          <div className="font-mono-ui flex flex-wrap gap-x-2 gap-y-0.5 pt-1 text-[0.62rem] text-muted-foreground">
            {extraChips.map((chip, i) => (
              <span key={`${chip.label}-${i}`} className="whitespace-nowrap">
                {chip.value}
                <span className="ml-0.5 text-muted-foreground/55">{chip.label}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

function YouTubeMetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/40 bg-background/40 px-2 py-1">
      <div className="font-mono-ui text-[0.55rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-semibold tabular-nums text-foreground/90">{value}</div>
    </div>
  );
}

function PlatformTablist({
  tabs,
  active,
  onChange,
  idPrefix,
  panelId,
}: {
  tabs: Array<{ label: string; count: number }>;
  active: string;
  onChange: (label: string) => void;
  idPrefix: string;
  panelId: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const handleKey = (idx: number) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End")
      return;
    e.preventDefault();
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    onChange(tabs[next].label);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label="Filter posts by platform" className="flex flex-wrap items-center gap-1.5 pt-1">
      {tabs.map((t, i) => (
        <PlatformTab
          key={t.label}
          ref={(el) => {
            refs.current[i] = el;
          }}
          id={`${idPrefix}-tab-${t.label}`}
          label={t.label}
          count={t.count}
          active={active === t.label}
          onClick={() => onChange(t.label)}
          onKeyDown={handleKey(i)}
          controlsId={panelId}
        />
      ))}
    </div>
  );
}

const PlatformTab = forwardRef<HTMLButtonElement, {
  id: string;
  label: string;
  active: boolean;
  count: number;
  onClick: () => void;
  onKeyDown?: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
  controlsId?: string;
}>(function PlatformTab({ id, label, active, count, onClick, onKeyDown, controlsId }, ref) {
  return (
    <button
      ref={ref}
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      aria-controls={controlsId}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex min-h-[44px] items-center gap-1.5 rounded-full border px-3 py-2 font-mono-ui text-[0.65rem] uppercase tracking-wider transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
        active
          ? "border-primary bg-primary/10 text-primary"
          : "border-border/60 bg-background/20 text-muted-foreground hover:border-border hover:text-foreground",
      )}
    >
      {label !== "all" && (
        <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", platformDot(label))} />
      )}
      <span>{label}</span>
      <span className="text-foreground/60">{count}</span>
    </button>
  );
});

// Single source of truth — delegates to the cross-platform readers so IG/FB/TT/YT
// rank consistently. Adds a tiny activity tiebreaker so two posts with identical
// rates don't shuffle randomly.
function computeEngagementScore(row: SocialMetricRow): number {
  const score = genericEngagement(row);
  const activity = totalActivity(row);
  if (score > 0) return score * 100 + activity * 0.001;
  return activity;
}

function PostDetailModal({ row, onClose }: { row: SocialMetricRow; onClose: () => void }) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
  const fbImage = (fbMedia.image as { src?: string } | undefined)?.src;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb ||
    (fbPost.full_picture as string | undefined) ||
    fbImage ||
    (raw.full_picture as string | undefined) ||
    (raw.media_url as string | undefined);
  const caption = row.caption || (fbPost.message as string | undefined) || "";
  const m = (row.metrics || {}) as Record<string, unknown>;
  const page = (m._page as string | undefined) || "";
  const hookRate = derivedHookRate(row);
  const holdRate = derivedHoldRate(row);
  const engagementRate =
    typeof m.engagement_rate === "number" ? (m.engagement_rate as number) : null;
  // Hook/hold render as their own row above the grid; drop the raw fields
  // from the grid so we don't show them twice.
  const metricEntries = Object.entries(m).filter(
    ([k]) => !k.startsWith("_") && k !== "hook_rate" && k !== "hold_rate",
  );

  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const root = dialogRef.current;
    if (root) {
      const first = root.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      (first ?? root).focus();
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key === "Tab" && root) {
        const focusable = Array.from(
          root.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((el) => !el.hasAttribute("aria-hidden"));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocused.current?.focus?.();
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-border bg-card shadow-2xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <span id={titleId} className="sr-only">
          {caption ? caption.slice(0, 120) : `${row.platform} post detail`}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close post detail"
          className="absolute right-3 top-3 z-10 inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-background/80 px-3 font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
        >
          close
        </button>
        <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="relative aspect-[9/16] bg-background/40 md:aspect-auto md:min-h-[480px]">
            {thumb ? (
              <img
                src={thumb}
                alt={caption ? caption.slice(0, 100) : ""}
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <div
                aria-hidden="true"
                className="absolute inset-0 flex items-center justify-center text-muted-foreground/40"
              >
                <Activity className="h-8 w-8" />
              </div>
            )}
            <div className="absolute top-3 left-3 flex items-center gap-1.5 rounded-full bg-background/85 backdrop-blur px-2.5 py-1">
              <span
                aria-hidden="true"
                className={cn("h-2 w-2 rounded-full", platformDot(row.platform))}
              />
              <span className="font-mono-ui text-[0.65rem] uppercase tracking-wider">{row.platform}</span>
            </div>
          </div>
          <div className="space-y-4 p-5">
            <div>
              {page && (
                <div className="font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground">
                  {page}
                </div>
              )}
              <div className="mt-1 flex items-center justify-between gap-3">
                <span className="font-mono-ui text-xs text-muted-foreground">
                  {row.posted_at ? new Date(row.posted_at).toLocaleString() : "—"}
                </span>
                {row.permalink && (
                  <a
                    href={row.permalink}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="Open original post in new tab"
                    className="font-mono-ui inline-flex min-h-[44px] items-center px-3 text-[0.65rem] uppercase tracking-wider text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                  >
                    open ↗
                  </a>
                )}
              </div>
            </div>
            {caption && (
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/85">
                {caption}
              </p>
            )}
            {(engagementRate != null || hookRate != null || holdRate != null) && (
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    Engagement
                  </div>
                  <div className="mt-0.5 text-sm font-semibold tabular-nums text-primary">
                    {engagementRate != null ? `${(engagementRate * 100).toFixed(2)}%` : "—"}
                  </div>
                </div>
                <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    Hook rate
                  </div>
                  <div className="mt-0.5 text-sm font-semibold tabular-nums text-primary">
                    {hookRate != null ? `${(hookRate * 100).toFixed(1)}%` : "—"}
                  </div>
                </div>
                <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
                  <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    Hold rate
                  </div>
                  <div className="mt-0.5 text-sm font-semibold tabular-nums text-primary">
                    {holdRate != null ? `${(holdRate * 100).toFixed(1)}%` : "—"}
                  </div>
                </div>
              </div>
            )}
            {metricEntries.length > 0 ? (
              <div>
                <div className="mb-2 font-mono-ui text-[0.65rem] uppercase tracking-wider text-muted-foreground">
                  Metrics
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {metricEntries.map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-border/40 bg-background/30 px-3 py-2">
                      <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                        {prettifyMetricKey(k)}
                      </div>
                      <div className="mt-0.5 text-sm font-medium tabular-nums">
                        {formatMetricValue(k, v)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-border/40 bg-background/20 px-3 py-4 text-center text-xs text-muted-foreground">
                No metrics returned for this post yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function RealVideoCard({
  row,
  onClick,
  highlight,
}: {
  row: SocialMetricRow;
  onClick?: () => void;
  highlight?: boolean;
}) {
  const raw = (row.raw || {}) as Record<string, unknown>;
  const fbPost = (raw.post as Record<string, unknown> | undefined) || {};
  const fbAttach = ((fbPost.attachments as Record<string, unknown> | undefined)?.data as Array<Record<string, unknown>> | undefined)?.[0];
  const fbMedia = (fbAttach?.media as Record<string, unknown> | undefined) || {};
  const fbImage = (fbMedia.image as { src?: string } | undefined)?.src;
  const ytSnippet = raw.snippet as Record<string, unknown> | undefined;
  const ytThumb =
    (ytSnippet?.thumbnail as string | undefined) ||
    ((ytSnippet?.thumbnails as Record<string, { url?: string }> | undefined)?.high?.url as string | undefined);
  const thumb =
    (raw.thumbnail_url as string | undefined) ||
    (raw.thumbnail as string | undefined) ||
    ytThumb ||
    (fbPost.full_picture as string | undefined) ||
    fbImage ||
    (raw.full_picture as string | undefined) ||
    (raw.media_url as string | undefined);
  const m = (row.metrics || {}) as Record<string, unknown>;
  const engagementRate =
    typeof m.engagement_rate === "number" ? (m.engagement_rate as number) : null;
  const hookRate = derivedHookRate(row);
  const holdRate = derivedHoldRate(row);
  const caption = row.caption || (fbPost.message as string | undefined) || "";
  const captionDisplay = caption.trim() || "Untitled post";

  // Two metrics max — pick the most meaningful for this row.
  // Video: views + likes. Static: likes + comments. Story: reach + replies.
  const views = readMetric(row, "views");
  const likes = readMetric(row, "likes");
  const comments = readMetric(row, "comments");
  const shares = readMetric(row, "shares");
  const candidates: Array<[string, number]> = [
    ["views", views],
    ["likes", likes],
    ["comments", comments],
    ["shares", shares],
  ];
  const topMetrics = candidates.filter(([, v]) => v > 0).slice(0, 2);

  // Pick a single rate to show — hold > hook > engagement (descending priority of insight value).
  const primaryRate: { label: string; value: number } | null =
    holdRate != null
      ? { label: "hold", value: holdRate }
      : hookRate != null
        ? { label: "hook", value: hookRate }
        : engagementRate != null
          ? { label: "eng", value: engagementRate }
          : null;

  const handleClick = (e: ReactMouseEvent) => {
    if (onClick) {
      e.preventDefault();
      onClick();
    }
  };

  const Inner = (
    <div className="space-y-2">
      <div
        className={cn(
          "relative aspect-[9/16] overflow-hidden rounded-xl bg-background/40 border transition",
          highlight ? "border-primary" : "border-border/40 group-hover:border-border",
        )}
      >
        {thumb ? (
          <img
            src={thumb}
            alt={caption ? caption.slice(0, 100) : ""}
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div aria-hidden="true" className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
            <Activity className="h-6 w-6" />
          </div>
        )}
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-2 left-2 h-2 w-2 rounded-full ring-2 ring-background/80",
            platformDot(row.platform),
          )}
          title={row.platform}
        />
      </div>
      <div className="space-y-1">
        <p className="line-clamp-2 text-[0.78rem] leading-snug text-foreground">
          {captionDisplay}
        </p>
        {topMetrics.length > 0 && (
          <div className="flex items-baseline gap-3 text-[0.7rem] text-muted-foreground">
            {topMetrics.map(([label, value]) => (
              <span key={label} className="whitespace-nowrap">
                <span className="font-medium tabular-nums text-foreground">
                  {formatCompact(value)}
                </span>{" "}
                {label}
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center justify-between text-[0.65rem] text-muted-foreground/80">
          <span className="font-mono-ui uppercase tracking-wider">
            {row.posted_at ? isoTimeAgo(row.posted_at) : "—"}
          </span>
          {primaryRate && (
            <span className="font-mono-ui tabular-nums uppercase tracking-wider text-foreground/70">
              {(primaryRate.value * 100).toFixed(1)}% {primaryRate.label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
  if (onClick) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className="group block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary rounded-xl"
      >
        {Inner}
      </button>
    );
  }
  return row.permalink ? (
    <a
      href={row.permalink}
      target="_blank"
      rel="noopener noreferrer"
      className="group block focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary rounded-xl"
    >
      {Inner}
    </a>
  ) : (
    <div>{Inner}</div>
  );
}

function PlatformBlockCard({
  platform,
  block,
}: {
  platform: string;
  block: SocialPlatformBlock;
}) {
  const { totals, averages, top_posts, post_count } = block;
  return (
    <div className="rounded-xl bg-background/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", platformDot(platform))} />
          <span className="font-mono-ui text-[0.7rem] uppercase tracking-wider">{platform}</span>
        </div>
        <span className="text-[0.7rem] text-muted-foreground">{post_count} posts</span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="font-mono-ui text-sm font-semibold">{formatCompact(totals?.reach)}</div>
          <div className="text-[0.6rem] text-muted-foreground uppercase tracking-wider">Reach</div>
        </div>
        <div>
          <div className="font-mono-ui text-sm font-semibold">{formatPct(averages?.engagement_rate, 2)}</div>
          <div className="text-[0.6rem] text-muted-foreground uppercase tracking-wider">Eng</div>
        </div>
        <div>
          <div className="font-mono-ui text-sm font-semibold">
            {formatPct(averages?.hook_rate ?? averages?.hold_rate, 2)}
          </div>
          <div className="text-[0.6rem] text-muted-foreground uppercase tracking-wider">
            {averages?.hook_rate != null ? "Hook" : "Hold"}
          </div>
        </div>
      </div>

      {top_posts && top_posts.length > 0 && (
        <div className="space-y-1.5">
          <div className="font-mono-ui text-[0.6rem] uppercase tracking-wider text-muted-foreground">Top performers</div>
          {top_posts.slice(0, 3).map((p) => (
            <a
              key={p.post_id}
              href={p.permalink ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg border border-border/40 bg-background/30 px-2 py-1.5 text-xs hover:border-primary/40"
            >
              <span className="flex-1 truncate">{p.caption || "(no caption)"}</span>
              <span className="font-mono-ui text-[0.65rem] text-muted-foreground">
                {formatPct(p.derived?.engagement_rate, 1)}
              </span>
              {p.permalink && <ExternalLink className="h-3 w-3 text-muted-foreground" />}
            </a>
          ))}
        </div>
      )}
    </div>
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
          { icon: DatabaseIcon, label: "Documents", value: memory?.documents ?? 0 },
          { icon: FileText, label: "Chunks", value: memory?.chunks ?? 0 },
          { icon: GitBranch, label: "Communities", value: memory?.community_reports ?? 0 },
          { icon: Network, label: "Relations", value: memory?.relations ?? 0 },
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
