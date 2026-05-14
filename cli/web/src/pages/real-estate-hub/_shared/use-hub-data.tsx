import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type {
  AdminActionRun,
  AdminDealTask,
  AgentHubSnapshot,
  CronJob,
  PaginatedSessions,
  SessionInfo,
  SourceInboxResponse,
  StatusResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn } from "@/lib/utils";
import type { HubData } from "./types";

export function useRealEstateHubData(): HubData {
  const { pathname } = useLocation();
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [sourceInbox, setSourceInbox] = useState<SourceInboxResponse | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [cronJobs, setCronJobs] = useState<CronJob[]>([]);
  const [dealTasks, setDealTasks] = useState<AdminDealTask[]>([]);
  const [actionRuns, setActionRuns] = useState<AdminActionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshSeq = useRef(0);
  const includeMemoryGraph = pathname === "/memory" || pathname.startsWith("/memory/");
  const includeSourceInbox =
    pathname === "/" ||
    pathname === "/today" ||
    pathname.startsWith("/today/") ||
    pathname === "/leads" ||
    pathname.startsWith("/leads/");
  const includeAdminTaskData =
    pathname === "/tasks" ||
    pathname.startsWith("/tasks/") ||
    pathname === "/today" ||
    pathname.startsWith("/today/") ||
    pathname === "/";
  const includeOrchestration =
    pathname === "/" || pathname === "/today" || pathname.startsWith("/today/");
  const includeAgentHub = includeMemoryGraph || includeOrchestration || includeAdminTaskData;

  const refresh = useCallback(async () => {
    const refreshId = ++refreshSeq.current;
    setError(null);
    const [
      hubResult,
      statusResult,
      sessionsResult,
      cronResult,
    ] = await Promise.allSettled([
      includeAgentHub
        ? api.getAgentHub({
            lite: true,
            includeMemoryGraph,
            includeOrchestration,
          })
        : Promise.resolve(null),
      api.getStatus(),
      api.getSessions(36, 0, { includeTotal: false }),
      api.getCronJobs({ compact: true }),
    ]);

    if (refreshSeq.current !== refreshId) return;

    if (hubResult.status === "fulfilled") setSnapshot(hubResult.value);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sessionsResult.status === "fulfilled") {
      setSessions((sessionsResult.value as PaginatedSessions).sessions);
    }
    if (cronResult.status === "fulfilled") setCronJobs(cronResult.value);

    const failed = [hubResult, statusResult, sessionsResult, cronResult].find(
      (result) => result.status === "rejected",
    );

    if (failed?.status === "rejected") {
      setError(failed.reason instanceof Error ? failed.reason.message : "Some hub data failed");
    }

    void Promise.allSettled([
      includeSourceInbox ? api.getSourceInbox(200) : Promise.resolve(null),
      includeAdminTaskData ? api.getAdminDealTasks({ status: "open", limit: 200 }) : Promise.resolve(null),
      includeAdminTaskData ? api.getAdminActionRuns({ limit: 200 }) : Promise.resolve(null),
    ]).then(([sourceInboxResult, dealTasksResult, actionRunsResult]) => {
      if (refreshSeq.current !== refreshId) return;
      if (sourceInboxResult.status === "fulfilled" && sourceInboxResult.value) {
        setSourceInbox(sourceInboxResult.value);
      } else {
        setSourceInbox(null);
      }
      if (dealTasksResult.status === "fulfilled" && dealTasksResult.value) {
        setDealTasks(dealTasksResult.value.items);
      } else {
        setDealTasks([]);
      }
      if (actionRunsResult.status === "fulfilled" && actionRunsResult.value) {
        setActionRuns(actionRunsResult.value.items);
      } else {
        setActionRuns([]);
      }
    });
  }, [includeAdminTaskData, includeMemoryGraph, includeOrchestration, includeSourceInbox, includeAgentHub]);

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
      refreshSeq.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (!id) id = window.setInterval(() => void refresh(), 25_000);
    };
    const stop = () => {
      if (id) { window.clearInterval(id); id = null; }
    };
    const onVisibility = () => {
      if (document.hidden) stop();
      else { void refresh(); start(); }
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  return { actionRuns, cronJobs, dealTasks, error, loading, refresh, sourceInbox, sessions, snapshot, status };
}

export function useHubHeader(title: string, data: HubData) {
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
