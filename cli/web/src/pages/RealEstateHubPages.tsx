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
  FileText,
  GitBranch,
  Home,
  Loader2,
  Megaphone,
  MessageSquare,
  Network,
  PencilLine,
  RefreshCw,
  Send,
  ShieldCheck,
  Target,
  Users,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  AgentHubMemoryNode,
  AgentHubSnapshot,
  CronJob,
  PaginatedSessions,
  SessionInfo,
  SourceInboxDraft,
  SourceInboxProfile,
  SourceInboxResponse,
  SourceInboxThread,
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
        api.getSourceInbox(64),
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

function heatVariant(item: { heatLabel: string }): "default" | "success" | "warning" | "outline" {
  if (item.heatLabel === "hot") return "warning";
  if (item.heatLabel === "warm") return "success";
  return "outline";
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
  const watch = threads
    .filter((thread) => !hot.includes(thread) && !followUp.includes(thread))
    .slice(0, 10);
  return { followUp, hot, watch };
}

function sourceSummary(data: HubData): Array<{ label: string; count: number; state: string }> {
  const sources = data.sourceInbox?.sources ?? [];
  return sources
    .filter((source) => Number(source.recordCounts?.conversations ?? source.recordCounts?.contacts ?? 0) > 0)
    .map((source) => ({
      label: source.label,
      count: Number(source.recordCounts?.conversations ?? source.recordCounts?.contacts ?? 0),
      state: source.importOnly ? "snapshot" : source.connected ? "live" : source.state,
    }))
    .slice(0, 5);
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

function LeadBoardRow({
  data,
  thread,
}: {
  data: HubData;
  thread: SourceInboxThread;
}) {
  const mark = async (action: "done" | "archive") => {
    await api.updateSourceInboxThread(thread.sourceId, thread.threadId, action);
    await data.refresh();
  };

  return (
    <div className="group rounded-2xl border border-border/55 bg-background/35 px-3 py-3 transition-colors hover:bg-background/55">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
            thread.heatLabel === "hot" ? "bg-warning" : thread.heatLabel === "warm" ? "bg-success" : "bg-muted-foreground/45",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
              {thread.personName}
            </div>
            <Badge variant={heatVariant(thread)}>{thread.heatScore}</Badge>
          </div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {thread.latestText}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">{thread.sourceLabel}</Badge>
            <Badge variant="outline">{thread.channel}</Badge>
            <Badge variant="outline">{threadWhen(thread)}</Badge>
            {thread.messageCount > 1 && <Badge variant="outline">{thread.messageCount} msgs</Badge>}
          </div>
        </div>
      </div>
      <div className="mt-3 flex justify-end gap-1.5">
        <Button size="sm" variant="outline" onClick={() => void mark("done")}>
          Done
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void mark("archive")}>
          Remove
        </Button>
      </div>
    </div>
  );
}

function LeadBoardColumn({
  data,
  empty,
  threads,
  title,
}: {
  data: HubData;
  empty: string;
  threads: SourceInboxThread[];
  title: string;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-muted-foreground">{title}</div>
        <Badge variant={threads.length ? "outline" : "secondary"}>{threads.length}</Badge>
      </div>
      <div className="space-y-2">
        {threads.length ? (
          threads.map((thread) => <LeadBoardRow key={thread.id} data={data} thread={thread} />)
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
}: {
  data: HubData;
}) {
  const threads = data.sourceInbox?.threads ?? [];
  const buckets = leadThreadBuckets(threads);
  const sources = sourceSummary(data);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Lead workboard</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Prioritized people from CRM, Messages, and other lead sources. Checking a row off hides it from this board without deleting source data.
            </p>
          </div>
          <Badge variant={threads.length ? "warning" : "outline"}>{threads.length} open</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {sources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {sources.map((source) => (
              <div
                key={source.label}
                className="flex items-center gap-2 rounded-full border border-border/60 bg-background/35 px-3 py-1.5 text-xs text-muted-foreground"
              >
                <span className="font-semibold text-foreground">{source.label}</span>
                <span>{source.count}</span>
                <Badge variant="outline">{source.state}</Badge>
              </div>
            ))}
          </div>
        )}
        <div className="grid gap-4 xl:grid-cols-3">
          <LeadBoardColumn
            data={data}
            title="Hot now"
            threads={buckets.hot}
            empty="No hot leads yet. Lofty, Messages, and future CRM imports will promote high-priority people here."
          />
          <LeadBoardColumn
            data={data}
            title="Needs follow-up"
            threads={buckets.followUp}
            empty="No reply-needed or warm leads waiting."
          />
          <LeadBoardColumn
            data={data}
            title="Watch list"
            threads={buckets.watch}
            empty="No lower-priority leads to watch."
          />
        </div>
      </CardContent>
    </Card>
  );
}

function draftWhen(draft: SourceInboxDraft): string {
  return draft.latestAt ? isoTimeAgo(draft.latestAt) : "unsynced";
}

function DraftMessagesBoard({
  data,
  title = "Draft follow-ups",
}: {
  data: HubData;
  title?: string;
}) {
  const drafts = data.sourceInbox?.drafts ?? [];
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftEdits, setDraftEdits] = useState<Record<string, string>>({});

  const updateDraft = async (
    draft: SourceInboxDraft,
    action: "approve" | "edit" | "skip",
    text = draft.draftText,
  ) => {
    await api.updateSourceInboxDraft(draft.sourceId, draft.taskId, action, text);
    setEditingId(null);
    setDraftEdits((current) => {
      const next = { ...current };
      delete next[draft.id];
      return next;
    });
    await data.refresh();
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{title}</CardTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Approval-gated replies for follow-ups, texts, DMs, and comments. Approving only marks the draft ready; it does not send automatically.
            </p>
          </div>
          <Badge variant={drafts.length ? "warning" : "outline"}>{drafts.length} waiting</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {drafts.length ? (
          drafts.slice(0, 8).map((draft) => {
            const isEditing = editingId === draft.id;
            const draftText = draftEdits[draft.id] ?? draft.draftText;
            return (
              <div
                key={draft.id}
                className="rounded-2xl border border-border/60 bg-background/35 px-3 py-3 transition-colors hover:bg-background/55"
              >
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-1.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-warning/12 text-warning">
                    <MessageSquare className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                        {draft.personName}
                      </div>
                      <Badge variant={draft.generated ? "outline" : "warning"}>
                        {draft.generated ? "suggested" : "draft"}
                      </Badge>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{draft.sourceLabel}</Badge>
                      <Badge variant="outline">{draft.channel}</Badge>
                      <Badge variant="outline">{draftWhen(draft)}</Badge>
                    </div>
                    {draft.context && (
                      <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {draft.context}
                      </p>
                    )}
                  </div>
                </div>
                {isEditing ? (
                  <div className="mt-3 space-y-2">
                    <textarea
                      value={draftText}
                      onChange={(event) =>
                        setDraftEdits((current) => ({ ...current, [draft.id]: event.target.value }))
                      }
                      className="min-h-24 w-full resize-y rounded-2xl border border-border/70 bg-background/60 px-3 py-2 text-sm leading-6 text-foreground outline-none transition focus:border-primary/45 focus:ring-2 focus:ring-primary/10"
                    />
                    <div className="flex justify-end gap-1.5">
                      <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                        Cancel
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => void updateDraft(draft, "edit", draftText)}>
                        Save edit
                      </Button>
                      <Button size="sm" onClick={() => void updateDraft(draft, "approve", draftText)}>
                        Approve
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="mt-3 rounded-2xl bg-card/45 px-3 py-3 text-sm leading-6 text-foreground">
                      {draft.draftText}
                    </p>
                    <div className="mt-3 flex flex-wrap justify-end gap-1.5">
                      <Button size="sm" variant="ghost" onClick={() => void updateDraft(draft, "skip")}>
                        <XCircle className="h-3.5 w-3.5" />
                        Skip
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setEditingId(draft.id);
                          setDraftEdits((current) => ({ ...current, [draft.id]: draft.draftText }));
                        }}
                      >
                        <PencilLine className="h-3.5 w-3.5" />
                        Edit
                      </Button>
                      <Button size="sm" onClick={() => void updateDraft(draft, "approve")}>
                        <Send className="h-3.5 w-3.5" />
                        Approve
                      </Button>
                    </div>
                  </>
                )}
              </div>
            );
          })
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-8 text-sm leading-6 text-muted-foreground">
            No draft replies are waiting. Composio social imports, CRM follow-ups, and outreach tasks can feed approval-gated messages here.
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
    <HubShell
      data={data}
      eyebrow="Real Estate Command Center"
      hero="A local-first operating board for lead priority, admin/document work, social pulse, approvals, and the agent team. Ads stays visible as a later lane."
      icon={Home}
      title="Elevate Agent is ready to run from one real-estate hub."
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
  const openLeadThreads = Number(data.sourceInbox?.recordCounts?.threads ?? 0);
  const hotLeadThreads = sourceRecordCount(data, "hotThreads");
  const people = sourceRecordCount(data, "people");
  const crmPeople = sourceRecordCount(data, "crmPeople");
  const potentialLeads = sourceRecordCount(data, "potentialLeads");
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
          { icon: Target, label: "Hot leads", value: hotLeadThreads },
          { icon: Send, label: "Drafts waiting", value: sourceRecordCount(data, "drafts") },
          { icon: MessageSquare, label: "Open threads", value: openLeadThreads },
          {
            icon: CalendarClock,
            label: "Follow-up tasks",
            value: jobs.length,
          },
        ]}
      />
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_28rem]">
        <LeadWorkBoard data={data} />
        <DraftMessagesBoard data={data} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ActionBoard
          actions={actions}
          title="Lead action board"
          empty="No lead actions are waiting yet. When outreach sessions, follow-up schedules, or approvals exist, they will show up here."
        />
        <TimedTasks jobs={jobs} empty="No lead follow-up schedules yet." title="Lead follow-ups" />
      </div>
      <WorkflowStrip
        items={[
          { icon: Users, label: "People", value: people },
          { icon: DatabaseIcon, label: "CRM matched", value: crmPeople },
          { icon: Megaphone, label: "Social potentials", value: potentialLeads },
          { icon: CheckCircle2, label: "Review gates", value: approvalCueCount(sessions, jobs) },
        ]}
      />
      <ClientInboxPreview data={data} title="Source preview" />
      <ContactOverviewBoard data={data} />
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
