import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  CalendarClock,
  FileCheck2,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AccessStatusResponse } from "@/lib/api";
import {
  AdminActionRuns,
  AdminDealTasks,
  AgentHandoffsCard,
  AgentWorkerCard,
  HubShell,
  RecentSessions,
  TimedTasks,
  useHubHeader,
  useRealEstateHubData,
  WorkflowStrip,
} from "@/pages/real-estate-hub/_shared";

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
