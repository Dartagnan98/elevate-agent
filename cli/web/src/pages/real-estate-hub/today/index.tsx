import { useMemo } from "react";
import { Home } from "lucide-react";
import { HubShell, useHubHeader, useRealEstateHubData } from "../_shared";
import { buildTodayData } from "./data";
import { DayShape } from "./day-shape";
import { PriorityQueue } from "./priority-queue";
import { PulseStrip } from "./pulse-strip";
import { RunningStrip } from "./running-strip";

export function RealEstateTodayPage() {
  const data = useRealEstateHubData();
  useHubHeader("Today", data);

  const view = useMemo(
    () =>
      buildTodayData({
        sourceInbox: data.sourceInbox,
        actionRuns: data.actionRuns,
        dealTasks: data.dealTasks,
        cronJobs: data.cronJobs,
        sessions: data.sessions,
      }),
    [data.sourceInbox, data.actionRuns, data.dealTasks, data.cronJobs, data.sessions],
  );

  return (
    <HubShell
      data={data}
      eyebrow="Real Estate Command Center"
      icon={Home}
      title="Elevate Agent · Today"
    >
      <div className="space-y-4">
        <PulseStrip stats={view.pulse} />
        <PriorityQueue items={view.priority} />
        <DayShape hourBuckets={view.hourBuckets} dayBuckets={view.dayBuckets} />
        <RunningStrip scheduled={view.scheduled} live={view.live} running={view.running} />
      </div>
    </HubShell>
  );
}
