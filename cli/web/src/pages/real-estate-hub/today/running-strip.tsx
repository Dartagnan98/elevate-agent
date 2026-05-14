import { Activity, CalendarClock, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";
import type { AdminActionRun, CronJob, SessionInfo } from "@/lib/api";
import { isoTimeAgo, timeAgo } from "@/lib/utils";
import { sessionTitle } from "../_shared/agent-widgets";
import { cn } from "@/lib/utils";

export function RunningStrip({
  scheduled,
  live,
  running,
}: {
  scheduled: CronJob[];
  live: SessionInfo[];
  running: AdminActionRun[];
}) {
  return (
    <section aria-label="What's running" className="grid gap-3 lg:grid-cols-2">
      <ScheduledCard jobs={scheduled} />
      <LiveCard live={live} running={running} />
    </section>
  );
}

function ScheduledCard({ jobs }: { jobs: CronJob[] }) {
  return (
    <Card
      icon={CalendarClock}
      title="Scheduled · next 24h"
      meta={jobs.length === 0 ? "Nothing queued" : `${jobs.length} upcoming`}
      to="/cron"
    >
      {jobs.length === 0 ? (
        <EmptyRow message="No timed tasks set to fire today." />
      ) : (
        <ul className="divide-y divide-border">
          {jobs.map((job) => (
            <li key={job.id} className="flex items-start gap-2.5 px-3 py-2">
              <span className="mt-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[0.85rem] leading-5 text-foreground">
                  {job.name || job.prompt.slice(0, 80)}
                </div>
                <div className="font-mono-ui mt-0.5 truncate text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {job.next_run_at ? `Fires ${isoTimeAgo(job.next_run_at)}` : job.schedule_display}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function LiveCard({ live, running }: { live: SessionInfo[]; running: AdminActionRun[] }) {
  const total = live.length + running.length;
  return (
    <Card
      icon={Activity}
      title="In flight"
      meta={total === 0 ? "Idle" : `${total} running`}
      to="/tasks"
    >
      {total === 0 ? (
        <EmptyRow message="No live sessions or running actions." />
      ) : (
        <ul className="divide-y divide-border">
          {live.map((session) => (
            <li key={`s-${session.id}`} className="flex items-start gap-2.5 px-3 py-2">
              <span className="mt-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <Link
                    to={`/chat?resume=${encodeURIComponent(session.id)}`}
                    className="truncate text-[0.85rem] leading-5 text-foreground hover:underline"
                  >
                    {sessionTitle(session)}
                  </Link>
                </div>
                <div className="font-mono-ui mt-0.5 truncate text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                  Active {timeAgo(session.last_active)}
                </div>
              </div>
            </li>
          ))}
          {running.map((run) => (
            <li key={`r-${run.id}`} className="flex items-start gap-2.5 px-3 py-2">
              <span
                className={cn(
                  "mt-0.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full",
                  run.status === "running" || run.status === "in_progress"
                    ? "bg-warning animate-pulse"
                    : "bg-muted-foreground",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[0.85rem] leading-5 text-foreground">
                  {run.registryName || run.skill || "Action run"}
                </div>
                <div className="font-mono-ui mt-0.5 truncate text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {run.status}
                  {run.startedAt ? ` · ${isoTimeAgo(run.startedAt)}` : ""}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Card({
  icon: Icon,
  title,
  meta,
  to,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  meta: string;
  to: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-border bg-card">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-3 py-2">
        <div className="flex items-baseline gap-2">
          <Icon className="h-3.5 w-3.5 self-center text-muted-foreground" />
          <h3 className="text-[0.85rem] font-semibold leading-tight tracking-[-0.005em] text-foreground">
            {title}
          </h3>
          <span className="font-mono-ui text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
            {meta}
          </span>
        </div>
        <Link
          to={to}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Open
        </Link>
      </header>
      {children}
    </div>
  );
}

function EmptyRow({ message }: { message: string }) {
  return <p className="px-3 py-2 text-xs text-muted-foreground/80">{message}</p>;
}
