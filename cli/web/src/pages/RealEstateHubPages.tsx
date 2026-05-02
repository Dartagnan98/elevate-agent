import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useState,
  type ComponentType,
} from "react";
import {
  Activity,
  Bot,
  Brain,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  CheckCircle2,
  Clock,
  FileCheck2,
  Home,
  Loader2,
  Megaphone,
  MessageSquare,
  RefreshCw,
  Route,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentHubSnapshot,
  CronJob,
  PaginatedSessions,
  SessionInfo,
  SkillInfo,
  StatusResponse,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";

type HubData = {
  cronJobs: CronJob[];
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  sessions: SessionInfo[];
  skills: SkillInfo[];
  snapshot: AgentHubSnapshot | null;
  status: StatusResponse | null;
};

type SkillGroup = {
  available: SkillInfo[];
  missing: string[];
};

const REAL_ESTATE_SKILL_TARGETS = {
  leads: ["outreach", "outreach-send", "property-lookup", "gmail-doc-router"],
  listings: ["cma", "seller-updates", "showing-time", "weekly-listing", "relisting"],
  deals: ["mlc", "digisign", "webforms", "skyleigh-vault"],
  marketing: ["marketing", "humanizer", "graphify", "market-stats-watcher"],
} as const;

const WORKFLOW_LABELS: Record<keyof typeof REAL_ESTATE_SKILL_TARGETS, string> = {
  leads: "Leads",
  listings: "Listings",
  deals: "Deals",
  marketing: "Marketing",
};

function useRealEstateHubData(): HubData {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const [hubResult, statusResult, sessionsResult, cronResult, skillsResult] =
      await Promise.allSettled([
        api.getAgentHub(),
        api.getStatus(),
        api.getSessions(36),
        api.getCronJobs(),
        api.getSkills(),
      ]);

    if (hubResult.status === "fulfilled") setSnapshot(hubResult.value);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sessionsResult.status === "fulfilled") {
      setSessions((sessionsResult.value as PaginatedSessions).sessions);
    }
    if (cronResult.status === "fulfilled") setCronJobs(cronResult.value);
    if (skillsResult.status === "fulfilled") setSkills(skillsResult.value);

    const failed = [
      hubResult,
      statusResult,
      sessionsResult,
      cronResult,
      skillsResult,
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

  return { cronJobs, error, loading, refresh, sessions, skills, snapshot, status };
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

function skillGroup(skills: SkillInfo[], names: readonly string[]): SkillGroup {
  const byName = new Map(skills.map((skill) => [skill.name, skill]));
  return {
    available: names.flatMap((name) => {
      const skill = byName.get(name);
      return skill ? [skill] : [];
    }),
    missing: names.filter((name) => !byName.has(name)),
  };
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

function ReadinessGrid({
  data,
}: {
  data: HubData;
}) {
  const items = (Object.keys(REAL_ESTATE_SKILL_TARGETS) as Array<
    keyof typeof REAL_ESTATE_SKILL_TARGETS
  >).map((key) => {
    const group = skillGroup(data.skills, REAL_ESTATE_SKILL_TARGETS[key]);
    return {
      key,
      group,
      label: WORKFLOW_LABELS[key],
    };
  });

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.key} className="bg-card/72">
          <CardHeader className="p-4">
            <div className="flex items-center justify-between gap-3">
              <CardTitle>{item.label}</CardTitle>
              <Badge variant={item.group.missing.length ? "warning" : "success"}>
                {item.group.available.length}/{REAL_ESTATE_SKILL_TARGETS[item.key].length}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 p-4 pt-0">
            <div className="flex flex-wrap gap-1.5">
              {item.group.available.map((skill) => (
                <Badge key={skill.name} variant={skill.enabled ? "success" : "outline"}>
                  {skill.name}
                </Badge>
              ))}
              {item.group.missing.map((name) => (
                <Badge key={name} variant="outline">
                  {name}
                </Badge>
              ))}
            </div>
            <div className="text-xs leading-5 text-muted-foreground">
              {item.group.missing.length
                ? "Some workflow skills are not installed in this local package yet."
                : "Workflow skills are present locally."}
            </div>
          </CardContent>
        </Card>
      ))}
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

function SkillRunway({
  group,
  title,
}: {
  group: SkillGroup;
  title: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <Badge variant={group.missing.length ? "warning" : "success"}>
            {group.available.length} ready
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-2 sm:grid-cols-2">
          {group.available.map((skill) => (
            <div key={skill.name} className="rounded-2xl border border-border/55 bg-background/35 px-3 py-3">
              <div className="flex items-center justify-between gap-2">
                <div className="truncate text-sm font-semibold text-foreground">{skill.name}</div>
                <Badge variant={skill.enabled ? "success" : "outline"}>
                  {skill.enabled ? "Enabled" : "Off"}
                </Badge>
              </div>
              <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                {skill.description || skill.category || "Local workflow skill"}
              </div>
            </div>
          ))}
          {group.missing.map((name) => (
            <div key={name} className="rounded-2xl border border-dashed border-border bg-background/25 px-3 py-3">
              <div className="text-sm font-semibold text-muted-foreground">{name}</div>
              <div className="mt-1 text-xs leading-5 text-muted-foreground">
                Not present in this local skill package.
              </div>
            </div>
          ))}
        </div>
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
      hero="A local-first operating view for leads, listings, deals, marketing, and the agent team."
      icon={Home}
      title="Elevate Agent is ready to run from one real-estate hub."
    >
      <WorkflowStrip
        items={[
          { icon: Bot, label: "Agent team", value: enabledAgents.length },
          { icon: MessageSquare, label: "Live sessions", value: liveSessions.length },
          { icon: Clock, label: "Running tasks", value: enabledJobs.length },
          {
            icon: Sparkles,
            label: "Enabled skills",
            value: data.snapshot?.skills.enabled ?? data.skills.filter((skill) => skill.enabled).length,
          },
        ]}
      />
      <ReadinessGrid data={data} />
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
  const group = skillGroup(data.skills, REAL_ESTATE_SKILL_TARGETS.leads);
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
          { icon: Route, label: "Outreach skills", value: group.available.length },
          { icon: CalendarClock, label: "Follow-up tasks", value: jobs.length },
          {
            icon: CheckCircle2,
            label: "Send gate",
            value: group.available.some((skill) => skill.name === "outreach-send") ? "Ready" : "Missing",
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SkillRunway group={group} title="Lead workflow skills" />
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

export function RealEstateListingsPage() {
  const data = useRealEstateHubData();
  useHubHeader("Listings", data);
  const group = skillGroup(data.skills, REAL_ESTATE_SKILL_TARGETS.listings);
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
          { icon: FileCheck2, label: "Listing skills", value: group.available.length },
          { icon: CalendarClock, label: "Scheduled reports", value: jobs.length },
          {
            icon: Brain,
            label: "Memory segments",
            value: data.snapshot?.memory.journal.session_segment_count ?? 0,
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SkillRunway group={group} title="Listing workflow skills" />
        <TimedTasks jobs={jobs} empty="No listing schedules yet." title="Listing automations" />
      </div>
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
  const group = skillGroup(data.skills, REAL_ESTATE_SKILL_TARGETS.deals);
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
          { icon: FileCheck2, label: "Deal skills", value: group.available.length },
          { icon: CalendarClock, label: "Deal reminders", value: jobs.length },
          { icon: CheckCircle2, label: "Review gate", value: group.available.some((skill) => skill.name === "digisign") ? "Ready" : "Missing" },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SkillRunway group={group} title="Deal workflow skills" />
        <TimedTasks jobs={jobs} empty="No deal reminders yet." title="Deal tasks" />
      </div>
      <RecentSessions title="Deal work" sessions={sessions} empty="No deal-specific sessions found yet." />
    </HubShell>
  );
}

export function RealEstateMarketingPage() {
  const data = useRealEstateHubData();
  useHubHeader("Marketing", data);
  const group = skillGroup(data.skills, REAL_ESTATE_SKILL_TARGETS.marketing);
  const sessions = data.sessions.filter((session) =>
    sessionMatches(session, ["marketing", "social", "campaign", "email", "copy", "buffer", "mailjet"]),
  );
  const jobs = data.cronJobs.filter((job) =>
    jobMatches(job, ["marketing", "social", "campaign", "email", "buffer", "mailjet", "market stats"]),
  );

  return (
    <HubShell
      data={data}
      eyebrow="Marketing Studio"
      hero="Coordinate campaigns, email, social publishing, market stats, and brand-safe copy from the local skill stack."
      icon={Megaphone}
      title="Marketing is a production lane, not a pile of prompts."
    >
      <WorkflowStrip
        items={[
          { icon: Megaphone, label: "Campaign sessions", value: sessions.length },
          { icon: Sparkles, label: "Creative skills", value: group.available.length },
          { icon: CalendarClock, label: "Content schedules", value: jobs.length },
          { icon: Activity, label: "Skill loads", value: data.snapshot?.skills.enabled ?? group.available.length },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <SkillRunway group={group} title="Marketing workflow skills" />
        <TimedTasks jobs={jobs} empty="No marketing schedules yet." title="Content schedules" />
      </div>
      <RecentSessions
        title="Marketing work"
        sessions={sessions}
        empty="No marketing-specific sessions found yet."
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
