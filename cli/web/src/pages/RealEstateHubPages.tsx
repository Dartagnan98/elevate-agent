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
  Route,
  ShieldCheck,
  Sparkles,
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
  listings: ["cma", "seller-updates", "showing-time", "weekly-listing", "relisting"],
  deals: ["mlc", "digisign", "webforms", "skyleigh-vault"],
  ads: ["marketing", "market-stats-watcher", "graphify", "humanizer"],
  "social-media": ["social-media", "humanizer", "graphify"],
} as const;

const WORKFLOW_LABELS: Record<keyof typeof REAL_ESTATE_SKILL_TARGETS, string> = {
  leads: "Leads",
  listings: "Listings",
  deals: "Deals",
  ads: "Ads",
  "social-media": "Social Media",
};

const AREA_CONNECTORS: Record<
  keyof typeof REAL_ESTATE_SKILL_TARGETS,
  string[]
> = {
  leads: ["apple-messages", "sms-provider", "android-device", "rcs", "crm", "social", "email"],
  listings: ["skills", "market-stats", "document-storage"],
  deals: ["crm", "skills", "admin-requirements", "document-storage", "forms-signing"],
  ads: ["market-stats", "skills", "email", "social"],
  "social-media": ["social", "skills", "market-stats"],
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

function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
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
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
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

function ConnectorPanel({
  area,
  data,
  title = "Connectors",
}: {
  area: keyof typeof AREA_CONNECTORS;
  data: HubData;
  title?: string;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const connectors = data.sourceConnectors?.connectors.filter((connector) =>
    sourceMatchesArea(connector, area),
  ) ?? [];

  const initialize = async (sourceId: string) => {
    setBusyId(sourceId);
    try {
      await api.scaffoldSourceConnector(sourceId);
      await data.refresh();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant="outline">{connectors.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {connectors.length ? (
          connectors.slice(0, 7).map((connector) => {
            const recordCount = connectorRecordTotal(connector);
            return (
              <div
                key={connector.id}
                className="rounded-2xl border border-border/55 bg-background/35 px-3 py-2.5"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Network className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-foreground">
                        {connector.label}
                      </div>
                      <div className="mt-0.5 text-[0.72rem] text-muted-foreground">
                        {connector.nextOperatorStep ?? connector.sourceDir}
                      </div>
                    </div>
                  </div>
                  <Badge variant={sourceStateVariant(connector.state)}>
                    {connector.state.replace(/_/g, " ")}
                  </Badge>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <Badge variant="outline">{connector.ownerAgent}</Badge>
                  <Badge variant="outline">{recordCount} records</Badge>
                  {connector.connectionType && <Badge variant="outline">{connector.connectionType}</Badge>}
                  <Button
                    className="ml-auto h-7 px-2.5"
                    size="sm"
                    variant={connector.sourceExists ? "outline" : "default"}
                    onClick={() => void initialize(connector.id)}
                    disabled={busyId === connector.id}
                  >
                    {busyId === connector.id ? "Writing" : connector.sourceExists ? "Refresh test files" : "Initialize"}
                  </Button>
                </div>
              </div>
            );
          })
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-background/25 px-4 py-6 text-sm text-muted-foreground">
            No connector status is available for this lane yet.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SkillDirectoryNotice({ area }: { area: keyof typeof REAL_ESTATE_SKILL_TARGETS }) {
  return (
    <Card className="bg-primary/5">
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Sparkles className="h-4 w-4 text-primary" />
            Workflow skills moved to Skills
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {WORKFLOW_LABELS[area]} skills stay in the skills directory so dashboards can stay focused on connectors, sessions, tasks, and approvals.
          </p>
        </div>
        <Link
          to="/skills"
          className="inline-flex h-8 shrink-0 items-center justify-center rounded-full border border-border/80 bg-card/60 px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-foreground/8 hover:text-foreground"
        >
          Open Skills
        </Link>
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
      hero="A local-first operating view for leads, listings, deals, ads, social media, and the agent team."
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
      hero="Track outreach readiness, follow-up automations, and client conversation activity without moving data out of the local agent."
      icon={Users}
      title="Leads live where the conversations and outreach skills live."
    >
      <WorkflowStrip
        items={[
          { icon: Target, label: "Lead sessions", value: sessions.length },
          { icon: Route, label: "Ready connectors", value: readyConnectorCount(data, "leads") },
          { icon: CalendarClock, label: "Follow-up tasks", value: jobs.length },
          { icon: CheckCircle2, label: "Approval queue", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ConnectorPanel area="leads" data={data} title="Lead connectors" />
        <TimedTasks jobs={jobs} empty="No lead follow-up schedules yet." title="Lead follow-ups" />
      </div>
      <SkillDirectoryNotice area="leads" />
      <RecentSessions
        title="Lead conversations"
        sessions={sessions}
        empty="No lead-specific sessions found yet. Telegram, chat, and outreach runs will appear here when they include lead context."
      />
    </HubShell>
  );
}

export function RealEstateListingsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Listings", data);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ["listing", "cma", "seller update", "showing", "weekly", "relisting"]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["listing", "seller update", "showing", "weekly", "relisting"]),
  );

  return (
    <HubShell
      data={data}
      eyebrow="Listing Studio"
      hero="Keep CMA, seller update, showing feedback, relisting, and weekly reporting skills visible from the same local workspace."
      icon={Building2}
      title="Listings get their own runway without leaving Elevate Agent."
    >
      <WorkflowStrip
        items={[
          { icon: Home, label: "Listing sessions", value: sessions.length },
          { icon: Link2, label: "Ready connectors", value: readyConnectorCount(data, "listings") },
          { icon: CalendarClock, label: "Scheduled reports", value: jobs.length },
          {
            icon: Brain,
            label: "Memory segments",
            value: data.snapshot?.memory.journal.session_segment_count ?? 0,
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ConnectorPanel area="listings" data={data} title="Listing connectors" />
        <TimedTasks jobs={jobs} empty="No listing schedules yet." title="Listing automations" />
      </div>
      <SkillDirectoryNotice area="listings" />
      <RecentSessions
        title="Listing work"
        sessions={sessions}
        empty="No listing-specific sessions found yet."
      />
    </HubShell>
  );
}

export function RealEstateDealsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Deals", data);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ["deal", "mlc", "digisign", "webforms", "contract", "paperwork", "transaction"]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["deal", "mlc", "digisign", "webforms", "contract", "paperwork", "transaction"]),
  );

  return (
    <HubShell
      data={data}
      eyebrow="Deal Room"
      hero="Surface paperwork, transaction, signature, and loopback workflows while keeping approvals local."
      icon={BriefcaseBusiness}
      title="Deals stay organized around forms, signatures, and handoffs."
    >
      <WorkflowStrip
        items={[
          { icon: BriefcaseBusiness, label: "Deal sessions", value: sessions.length },
          { icon: Link2, label: "Ready connectors", value: readyConnectorCount(data, "deals") },
          { icon: CalendarClock, label: "Deal reminders", value: jobs.length },
          { icon: CheckCircle2, label: "Approval queue", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ConnectorPanel area="deals" data={data} title="Deal connectors" />
        <TimedTasks jobs={jobs} empty="No deal reminders yet." title="Deal tasks" />
      </div>
      <SkillDirectoryNotice area="deals" />
      <RecentSessions title="Deal work" sessions={sessions} empty="No deal-specific sessions found yet." />
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
      hero="Plan listing ads, paid campaigns, email campaigns, market-update positioning, audiences, and creative briefs from the local skill stack."
      icon={Target}
      title="Ads handles paid demand, campaign angles, and conversion copy."
    >
      <WorkflowStrip
        items={[
          { icon: Target, label: "Ad sessions", value: sessions.length },
          { icon: Link2, label: "Ready connectors", value: readyConnectorCount(data, "ads") },
          { icon: CalendarClock, label: "Campaign schedules", value: jobs.length },
          { icon: Activity, label: "Approval queue", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ConnectorPanel area="ads" data={data} title="Ads connectors" />
        <TimedTasks jobs={jobs} empty="No ad schedules yet." title="Campaign schedules" />
      </div>
      <SkillDirectoryNotice area="ads" />
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
      hero="Turn listing moments, market updates, and campaign ideas into organic posts, hooks, captions, platform plans, and posting schedules."
      icon={Megaphone}
      title="Social Media handles organic content and platform adaptation."
    >
      <WorkflowStrip
        items={[
          { icon: Megaphone, label: "Social sessions", value: sessions.length },
          { icon: Link2, label: "Ready connectors", value: readyConnectorCount(data, "social-media") },
          { icon: CalendarClock, label: "Post schedules", value: jobs.length },
          { icon: Activity, label: "Approval queue", value: data.snapshot?.platforms.reduce((total, platform) => total + platform.pending_pairings.length, 0) ?? 0 },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <ConnectorPanel area="social-media" data={data} title="Social connectors" />
        <TimedTasks jobs={jobs} empty="No social schedules yet." title="Post schedules" />
      </div>
      <SkillDirectoryNotice area="social-media" />
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
