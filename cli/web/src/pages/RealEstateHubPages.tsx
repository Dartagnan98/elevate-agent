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
  KeyRound,
  Link2,
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
  SourceConnectorsResponse,
  SourceConnectorStatus,
  StatusResponse,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  sourceConnectors: SourceConnectorsResponse | null;
  snapshot: AgentHubSnapshot | null;
  status: StatusResponse | null;
};

const REAL_ESTATE_SKILL_TARGETS = {
  leads: ["outreach", "outreach-send", "property-lookup", "gmail-doc-router"],
  admin: [
    "cma",
    "seller-updates",
    "showing-time",
    "weekly-listing",
    "relisting",
    "mlc",
    "digisign",
    "webforms",
    "skyleigh-vault",
  ],
  "social-media": ["social-media", "humanizer", "graphify"],
  ads: ["marketing", "market-stats-watcher", "graphify", "humanizer"],
} as const;

const WORKFLOW_LABELS: Record<keyof typeof REAL_ESTATE_SKILL_TARGETS, string> = {
  leads: "Leads",
  admin: "Admin",
  "social-media": "Social Media",
  ads: "Ads",
};

const AREA_CONNECTORS: Record<
  keyof typeof REAL_ESTATE_SKILL_TARGETS,
  string[]
> = {
  leads: ["apple-messages", "sms-provider", "android-device", "rcs", "crm", "social", "email"],
  admin: ["crm", "skills", "admin-requirements", "document-storage", "forms-signing", "market-stats"],
  "social-media": ["social", "skills", "market-stats", "email"],
  ads: ["market-stats", "skills", "email", "social"],
};

function useRealEstateHubData(): HubData {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [sourceConnectors, setSourceConnectors] = useState<SourceConnectorsResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const [hubResult, statusResult, sessionsResult, cronResult, sourceResult] =
      await Promise.allSettled([
        api.getAgentHub(),
        api.getStatus(),
        api.getSessions(36),
        api.getCronJobs(),
        api.getSourceConnectors(),
      ]);

    if (hubResult.status === "fulfilled") setSnapshot(hubResult.value);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sessionsResult.status === "fulfilled") {
      setSessions((sessionsResult.value as PaginatedSessions).sessions);
    }
    if (cronResult.status === "fulfilled") setCronJobs(cronResult.value);
    if (sourceResult.status === "fulfilled") setSourceConnectors(sourceResult.value);

    const failed = [
      hubResult,
      statusResult,
      sessionsResult,
      cronResult,
      sourceResult,
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

  return { cronJobs, error, loading, refresh, sessions, sourceConnectors, snapshot, status };
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

function sourceReady(connector: SourceConnectorStatus): boolean {
  return connector.state === "connected" || connector.state === "import_only";
}

function sourceMatchesArea(connector: SourceConnectorStatus, area: keyof typeof AREA_CONNECTORS): boolean {
  return AREA_CONNECTORS[area].includes(connector.id);
}

function readyConnectorCount(data: HubData, area?: keyof typeof AREA_CONNECTORS): number {
  const connectors = data.sourceConnectors?.connectors ?? [];
  return connectors.filter((connector) => {
    if (area && !sourceMatchesArea(connector, area)) return false;
    return sourceReady(connector);
  }).length;
}

function platformDisplayName(name: string): string {
  const cleaned = name.replace(/[-_]/g, " ");
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function sourceStateVariant(state: SourceConnectorStatus["state"]): "success" | "warning" | "outline" {
  if (state === "connected" || state === "import_only") return "success";
  if (state === "needs_operator" || state === "error" || state === "blocked") return "warning";
  return "outline";
}

function ConnectorReadiness({
  data,
}: {
  data: HubData;
}) {
  const items = (Object.keys(AREA_CONNECTORS) as Array<keyof typeof AREA_CONNECTORS>).map((key) => {
    const connectors = data.sourceConnectors?.connectors.filter((connector) =>
      sourceMatchesArea(connector, key),
    ) ?? [];
    const ready = connectors.filter(sourceReady).length;
    const pending = connectors.filter((connector) => connector.state === "needs_operator" || connector.state === "not_configured").length;
    return {
      connectors,
      key,
      label: WORKFLOW_LABELS[key],
      pending,
      ready,
    };
  });

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.key} className="bg-card/72">
          <CardHeader className="p-4">
            <div className="flex items-center justify-between gap-3">
              <CardTitle>{item.label}</CardTitle>
              <Badge variant={item.ready ? "success" : "outline"}>
                {item.ready}/{item.connectors.length}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 p-4 pt-0">
            <div className="grid gap-1.5">
              {item.connectors.slice(0, 4).map((connector) => {
                return (
                  <div
                    key={connector.id}
                    className="flex items-center justify-between gap-2 rounded-xl bg-background/35 px-2.5 py-1.5 text-xs"
                  >
                    <span className="truncate text-foreground">{connector.label}</span>
                    <Badge variant={sourceStateVariant(connector.state)}>{connector.state.replace(/_/g, " ")}</Badge>
                  </div>
                );
              })}
              {!item.connectors.length && (
                <div className="rounded-xl border border-dashed border-border bg-background/25 px-3 py-3 text-xs text-muted-foreground">
                  No connector surface is configured for this lane yet.
                </div>
              )}
            </div>
            <div className="flex items-center justify-between gap-2 text-xs leading-5 text-muted-foreground">
              <span>
                {item.pending
                  ? `${item.pending} connector setup item${item.pending === 1 ? "" : "s"} waiting`
                  : "Connector status, records, and setup prompts live here."}
              </span>
              <Link
                to="/config"
                className="shrink-0 text-primary hover:underline"
              >
                Settings
              </Link>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function SalesFocusBoard({
  items,
  note = "Connector setup, API credentials, imports, and source repair live in Settings. This page is for doing the work after the data is available.",
  title,
}: {
  items: Array<{
    icon: ComponentType<{ className?: string }>;
    label: string;
    summary: string;
    value: string | number;
  }>;
  note?: string;
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">operations</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <div
              key={item.label}
              className="rounded-2xl border border-border/55 bg-background/35 p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2.5">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/20">
                    <item.icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground">{item.label}</div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.summary}</p>
                  </div>
                </div>
                <Badge variant="outline">{item.value}</Badge>
              </div>
            </div>
          ))}
        </div>
        <div className="rounded-2xl border border-border/45 bg-background/25 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {note}
        </div>
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

function ApprovalInbox({ data }: { data: HubData }) {
  const pendingPairings =
    data.snapshot?.platforms.flatMap((platform) =>
      platform.pending_pairings.map((pairing) => ({ pairing, platform })),
    ) ?? [];
  const waitingRuns =
    data.snapshot?.orchestration?.runs?.filter((run) => {
      if (!run || typeof run !== "object") return false;
      return JSON.stringify(run).toLowerCase().includes("waiting_for_approval");
    }).length ?? 0;
  const approvalSurfaces =
    data.snapshot?.harness && "safety" in data.snapshot.harness
      ? data.snapshot.harness.safety.approval_surfaces
      : [];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Pending approvals</CardTitle>
            <Badge variant={pendingPairings.length || waitingRuns ? "warning" : "success"}>
              {pendingPairings.length + waitingRuns}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {pendingPairings.map(({ pairing, platform }) => (
            <div
              key={`${platform.name}-${pairing.code}`}
              className="rounded-2xl border border-warning/25 bg-warning/10 px-3 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-foreground">
                    {platformDisplayName(platform.name)} pairing
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {pairing.user_name || pairing.user_id} / {pairing.age_minutes}m old
                  </div>
                </div>
                <Badge variant="warning">{pairing.code}</Badge>
              </div>
              <div className="mt-2 rounded-xl bg-background/35 px-2.5 py-1.5 text-xs text-muted-foreground">
                Approve from CLI or platform command until dashboard approval actions are wired.
              </div>
            </div>
          ))}
          {waitingRuns > 0 && (
            <div className="rounded-2xl border border-warning/25 bg-warning/10 px-3 py-3 text-sm">
              {waitingRuns} orchestration run{waitingRuns === 1 ? "" : "s"} waiting for approval.
            </div>
          )}
          {!pendingPairings.length && waitingRuns === 0 && (
            <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-8 text-sm text-muted-foreground">
              No approvals are waiting. Pairing codes, send gates, and command approvals will collect here.
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Approval policy</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <HubMetric
              icon={ShieldCheck}
              label="External actions"
              value={
                data.snapshot?.harness && "safety" in data.snapshot.harness
                  ? data.snapshot.harness.safety.external_actions_policy
                  : "review"
              }
            />
            <HubMetric
              icon={AlertTriangle}
              label="Waiting runs"
              value={waitingRuns}
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(approvalSurfaces.length ? approvalSurfaces : ["terminal", "messaging", "send gate"]).map((surface) => (
              <Badge key={surface} variant="outline">
                {surface}
              </Badge>
            ))}
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            Approvals should be visible before an agent sends messages, runs risky terminal work, or pairs a new messaging user.
          </p>
        </CardContent>
      </Card>
    </div>
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

  return (
    <HubShell
      data={data}
      eyebrow="Real Estate Command Center"
      hero="A local-first operating view for lead priority, admin/document process, social pulse, and the agent team. Ads stays visible as a later lane."
      icon={Home}
      title="Elevate Agent is ready to run from one real-estate hub."
    >
      <WorkflowStrip
        items={[
          { icon: Bot, label: "Agent team", value: enabledAgents.length },
          { icon: MessageSquare, label: "Live sessions", value: liveSessions.length },
          { icon: Clock, label: "Running tasks", value: enabledJobs.length },
          {
            icon: Link2,
            label: "Connectors ready",
            value: readyConnectorCount(data),
          },
        ]}
      />
      <ConnectorReadiness data={data} />
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

  return (
    <HubShell
      data={data}
      eyebrow="Lead Desk"
      hero="Prioritize who needs work, who is cooling off, what leads just came through, and which outreach workflow should run next. Setup and imports stay in Settings."
      icon={Users}
      title="Leads shows the people who need attention now."
    >
      <WorkflowStrip
        items={[
          { icon: MessageSquare, label: "Lead conversations", value: sessions.length },
          { icon: CalendarClock, label: "Follow-up tasks", value: jobs.length },
          { icon: Target, label: "Scoring", value: "AI" },
          { icon: CheckCircle2, label: "Approved sends", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SalesFocusBoard
          title="Lead workbench"
          items={[
            {
              icon: MessageSquare,
              label: "Needs follow-up",
              value: sessions.length,
              summary: "Open reply-needed conversations, overdue touches, warm reactivation, and leads the outreach skill should handle next.",
            },
            {
              icon: AlertTriangle,
              label: "Falling out",
              value: "watch",
              summary: "Flag leads going quiet, missed replies, cold stretches, low-intent drift, and people who need a better next touch.",
            },
            {
              icon: Target,
              label: "New lead scoring",
              value: "rank",
              summary: "Score new inbound leads from CRM, Messages, email, or manual intake and explain why each one matters.",
            },
            {
              icon: CheckCircle2,
              label: "Approved outreach",
              value: "gated",
              summary: "Draft texts, emails, and DM replies stay human-approved before the outreach-send gate touches the real world.",
            },
          ]}
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

  return (
    <HubShell
      data={data}
      eyebrow="Admin Desk"
      hero="Run the signed-listing and deal process: CMA handoff, seller updates, forms, signatures, brokerage checklists, nightly status checks, and the local listing/deal database."
      icon={BriefcaseBusiness}
      title="Admin owns listings and deals once the real work starts."
    >
      <WorkflowStrip
        items={[
          { icon: Building2, label: "Listing/deal records", value: sessions.length },
          { icon: CalendarClock, label: "Nightly checks", value: jobs.length },
          {
            icon: FileCheck2,
            label: "Doc process",
            value: "phases",
          },
          { icon: CheckCircle2, label: "Approvals", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SalesFocusBoard
          title="Admin workbench"
          items={[
            {
              icon: DatabaseIcon,
              label: "Listing/deal database",
              value: sessions.length,
              summary: "Create one local record per listing or signed deal with stage, people, dates, documents, blockers, and artifact history.",
            },
            {
              icon: FileCheck2,
              label: "Document process",
              value: "MLC",
              summary: "Use Skyleigh tools phases for MLC, DigiSign, WebForms, forms, signatures, packets, and what documents are still needed.",
            },
            {
              icon: CalendarClock,
              label: "Nightly admin pulse",
              value: jobs.length,
              summary: "Cron checks where listings/deals are at, what changed, what is stale, and what needs tomorrow’s human attention.",
            },
            {
              icon: CheckCircle2,
              label: "Seller and client outputs",
              value: "queued",
              summary: "Seller updates, weekly reports, feedback summaries, and admin handoffs stay review-gated before sending.",
            },
          ]}
          note="SkySlope, brokerage software, document storage, forms providers, and skill-output imports are configured in Settings. Admin is the operating room after those sources exist."
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

  return (
    <HubShell
      data={data}
      eyebrow="Ads Studio"
      hero="Park paid media here for now. This lane will eventually inherit Facebook and Google Ads views, budgets, approvals, and reporting from the paid-ads stack."
      icon={Target}
      title="Ads is visible, but it is not the main workflow yet."
    >
      <WorkflowStrip
        items={[
          { icon: Target, label: "Ad sessions", value: sessions.length },
          { icon: CalendarClock, label: "Campaign schedules", value: jobs.length },
          { icon: Activity, label: "Approval queue", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
          { icon: Megaphone, label: "Creative review", value: "drafts" },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SalesFocusBoard
          title="Ads workbench"
          items={[
            {
              icon: Target,
              label: "Campaign briefs later",
              value: sessions.length,
              summary: "Keep paid campaign ideas, listing ad angles, audience notes, and market positioning here until the ads workspace is ported.",
            },
            {
              icon: Megaphone,
              label: "Creative drafts",
              value: "review",
              summary: "Ad copy, hooks, graphics, landing-page notes, and email campaign drafts can be reviewed without publishing.",
            },
            {
              icon: CalendarClock,
              label: "Flight schedules",
              value: jobs.length,
              summary: "Recurring campaign checks, reporting cadences, market stat pulls, and launch reminders.",
            },
            {
              icon: CheckCircle2,
              label: "Approved launches",
              value: "gated",
              summary: "Ads should not publish or alter budgets until the operator approves the exact action.",
            },
          ]}
          note="Ads setup is intentionally lighter for now. Facebook, Google, and Composio-style ad account setup belongs in Settings, and the richer ads console can be ported later."
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

  return (
    <HubShell
      data={data}
      eyebrow="Social Studio"
      hero="Run a content pulse from connected platforms: best posts, weak posts, last-30-day metrics, hooks, captions, and scheduled organic follow-up."
      icon={Megaphone}
      title="Social Media watches content performance and turns it into next posts."
    >
      <WorkflowStrip
        items={[
          { icon: Megaphone, label: "Social sessions", value: sessions.length },
          { icon: CalendarClock, label: "Post schedules", value: jobs.length },
          { icon: Activity, label: "30-day pulse", value: "auto" },
          { icon: MessageSquare, label: "Content queue", value: "drafts" },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SalesFocusBoard
          title="Social workbench"
          items={[
            {
              icon: MessageSquare,
              label: "Best-post analysis",
              value: sessions.length,
              summary: "Pull recent performance, identify the posts that worked, and convert the insight into the next content prompts.",
            },
            {
              icon: Megaphone,
              label: "Post drafts",
              value: "review",
              summary: "Generate hooks, captions, reels, listing moments, market updates, and nurture content before scheduling.",
            },
            {
              icon: CalendarClock,
              label: "Pulse cadence",
              value: jobs.length,
              summary: "Run daily, weekly, or last-30-day social checks so metrics keep syncing into the local content workspace.",
            },
            {
              icon: CheckCircle2,
              label: "Approved posts",
              value: "gated",
              summary: "Keep final captions and assets in an approval lane before anything posts externally.",
            },
          ]}
          note="Social account setup, Facebook/Instagram permissions, and Composio access belong in Settings. This page stays focused on the content queue."
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

export function RealEstateApprovalsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Approvals", data);
  const pendingPairings =
    data.snapshot?.platforms.reduce(
      (total, platform) => total + platform.pending_pairings.length,
      0,
    ) ?? 0;

  return (
    <HubShell
      data={data}
      eyebrow="Approval Center"
      hero="Review pairing codes, send gates, risky command approval policy, and orchestration waits before anything leaves the local agent."
      icon={ShieldCheck}
      title="Approvals are the trust gate for local agent work."
    >
      <WorkflowStrip
        items={[
          { icon: KeyRound, label: "Pairing approvals", value: pendingPairings },
          {
            icon: ShieldCheck,
            label: "External policy",
            value:
              data.snapshot?.harness && "safety" in data.snapshot.harness
                ? data.snapshot.harness.safety.external_actions_policy
                : "review",
          },
          {
            icon: AlertTriangle,
            label: "Review required",
            value:
              data.snapshot?.harness && "safety" in data.snapshot.harness
                ? data.snapshot.harness.safety.human_communication_requires_review
                  ? "Yes"
                  : "No"
                : "Unknown",
          },
          {
            icon: Network,
            label: "Approval surfaces",
            value:
              data.snapshot?.harness && "safety" in data.snapshot.harness
                ? data.snapshot.harness.safety.approval_surfaces.length
                : 0,
          },
        ]}
      />
      <ApprovalInbox data={data} />
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
