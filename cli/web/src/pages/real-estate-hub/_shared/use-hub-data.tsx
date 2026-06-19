import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
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

const SOURCE_INBOX_REFRESH_LIMIT = 3000;
const HUB_DATA_STORAGE_KEY = "elevate.realEstateHubData.v1";
const HUB_DATA_FRESH_MS = 10_000;
const HUB_DATA_PERSIST_MIN_INTERVAL_MS = 60_000;
const HUB_DATA_STORAGE_MAX_AGE_MS = 10 * 60_000;

type HubRequestFlags = {
  includeAdminTaskData: boolean;
  includeAgentHub: boolean;
  includeMemoryGraph: boolean;
  includeOrchestration: boolean;
  includeSourceInbox: boolean;
  includeWorkflowData: boolean;
};

type HubDataCoverage = {
  actionRuns?: boolean;
  agentHub?: boolean;
  cronJobs?: boolean;
  dealTasks?: boolean;
  sessions?: boolean;
  sourceInbox?: boolean;
  status?: boolean;
};

type CachedHubData = {
  actionRuns: AdminActionRun[];
  cachedAt: number;
  coverage: HubDataCoverage;
  cronJobs: CronJob[];
  dealTasks: AdminDealTask[];
  sessions: SessionInfo[];
  snapshot: AgentHubSnapshot | null;
  sourceInbox: SourceInboxResponse | null;
  status: StatusResponse | null;
};

type HubLoadResult = {
  data: CachedHubData;
  error: string | null;
};

const hubDataInflight = new Map<string, Promise<HubLoadResult>>();
let sharedHubDataCache: CachedHubData | null = null;
let pendingHubDataPersist: CachedHubData | null = null;
let hubDataPersistTimer: number | null = null;
let lastHubDataPersistAt = 0;

function routeHas(pathname: string, segment: string): boolean {
  return pathname === segment || pathname.startsWith(`${segment}/`);
}

export function flagsForPath(pathname: string): HubRequestFlags {
  const includeMemoryGraph = routeHas(pathname, "/memory");
  const includeWorkflowData =
    pathname === "/" ||
    routeHas(pathname, "/today") ||
    routeHas(pathname, "/leads") ||
    routeHas(pathname, "/admin") ||
    routeHas(pathname, "/social-media");
  const includeSourceInbox =
    pathname === "/" ||
    routeHas(pathname, "/today") ||
    routeHas(pathname, "/leads");
  const includeAdminTaskData =
    routeHas(pathname, "/today") ||
    pathname === "/";
  const includeOrchestration = pathname === "/" || routeHas(pathname, "/today");
  const includeAgentHub = includeMemoryGraph || includeOrchestration || includeAdminTaskData;

  return {
    includeAdminTaskData,
    includeAgentHub,
    includeMemoryGraph,
    includeOrchestration,
    includeSourceInbox,
    includeWorkflowData,
  };
}

function flagsKey(flags: HubRequestFlags): string {
  return [
    flags.includeAgentHub,
    flags.includeMemoryGraph,
    flags.includeOrchestration,
    flags.includeWorkflowData,
    flags.includeSourceInbox,
    flags.includeAdminTaskData,
  ].join(":");
}

function emptyCachedHubData(): CachedHubData {
  return {
    actionRuns: [],
    cachedAt: 0,
    coverage: {},
    cronJobs: [],
    dealTasks: [],
    sessions: [],
    snapshot: null,
    sourceInbox: null,
    status: null,
  };
}

function normalizeCachedHubData(value: unknown): CachedHubData | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Partial<CachedHubData>;
  const cachedAt = typeof record.cachedAt === "number" ? record.cachedAt : 0;
  if (!cachedAt || Date.now() - cachedAt > HUB_DATA_STORAGE_MAX_AGE_MS) return null;
  return {
    actionRuns: Array.isArray(record.actionRuns) ? record.actionRuns : [],
    cachedAt,
    coverage: record.coverage && typeof record.coverage === "object" ? record.coverage : {},
    cronJobs: Array.isArray(record.cronJobs) ? record.cronJobs : [],
    dealTasks: Array.isArray(record.dealTasks) ? record.dealTasks : [],
    sessions: Array.isArray(record.sessions) ? record.sessions : [],
    snapshot: record.snapshot ?? null,
    sourceInbox: record.sourceInbox ?? null,
    status: record.status ?? null,
  };
}

function readCachedHubData(): CachedHubData | null {
  if (sharedHubDataCache) return sharedHubDataCache;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(HUB_DATA_STORAGE_KEY);
    if (!raw) return null;
    const cached = normalizeCachedHubData(JSON.parse(raw));
    if (!cached) {
      window.localStorage.removeItem(HUB_DATA_STORAGE_KEY);
      return null;
    }
    sharedHubDataCache = cached;
    return cached;
  } catch {
    return null;
  }
}

function scheduleHubDataPersist(data: CachedHubData): void {
  if (typeof window === "undefined") return;
  pendingHubDataPersist = data;
  if (hubDataPersistTimer !== null) return;
  const delay = Math.max(250, HUB_DATA_PERSIST_MIN_INTERVAL_MS - (Date.now() - lastHubDataPersistAt));
  hubDataPersistTimer = window.setTimeout(() => {
    hubDataPersistTimer = null;
    const next = pendingHubDataPersist;
    pendingHubDataPersist = null;
    if (!next) return;
    try {
      window.localStorage.setItem(HUB_DATA_STORAGE_KEY, JSON.stringify(next));
      lastHubDataPersistAt = Date.now();
    } catch {
      // LocalStorage is just a startup accelerator. If it is full, in-memory
      // cache still keeps route switches instant.
    }
  }, delay);
}

function writeCachedHubData(data: CachedHubData): CachedHubData {
  sharedHubDataCache = data;
  scheduleHubDataPersist(data);
  return data;
}

function hasRequiredCoverage(data: CachedHubData, flags: HubRequestFlags): boolean {
  if (!data.coverage.status) return false;
  if (flags.includeAgentHub && !data.coverage.agentHub) return false;
  if (flags.includeWorkflowData && (!data.coverage.sessions || !data.coverage.cronJobs)) return false;
  if (flags.includeSourceInbox && !data.coverage.sourceInbox) return false;
  if (flags.includeAdminTaskData && (!data.coverage.dealTasks || !data.coverage.actionRuns)) return false;
  return true;
}

function hasVisibleHubData(data: CachedHubData | null): boolean {
  return Boolean(
    data &&
      (data.snapshot ||
        data.status ||
        data.sourceInbox ||
        data.sessions.length ||
        data.cronJobs.length ||
        data.dealTasks.length ||
        data.actionRuns.length),
  );
}

async function loadHubData(flags: HubRequestFlags, force = false): Promise<HubLoadResult> {
  const cached = readCachedHubData();
  if (
    !force &&
    cached &&
    Date.now() - cached.cachedAt < HUB_DATA_FRESH_MS &&
    hasRequiredCoverage(cached, flags)
  ) {
    return { data: cached, error: null };
  }

  const key = flagsKey(flags);
  const inflight = hubDataInflight.get(key);
  if (inflight) return inflight;

  const promise = (async () => {
    const previous = readCachedHubData() ?? emptyCachedHubData();
    const [
      hubResult,
      statusResult,
      sessionsResult,
      cronResult,
      sourceInboxResult,
      dealTasksResult,
      actionRunsResult,
    ] = await Promise.allSettled([
      flags.includeAgentHub
        ? api.getAgentHub({
            lite: true,
            includeMemoryGraph: flags.includeMemoryGraph,
            includeOrchestration: flags.includeOrchestration,
          })
        : Promise.resolve(null),
      api.getStatus({ refresh: force }),
      flags.includeWorkflowData ? api.getSessions(36, 0, { includeTotal: false }) : Promise.resolve(null),
      flags.includeWorkflowData ? api.getCronJobs({ compact: true }) : Promise.resolve(null),
      flags.includeSourceInbox ? api.getSourceInbox(SOURCE_INBOX_REFRESH_LIMIT) : Promise.resolve(null),
      flags.includeAdminTaskData ? api.getAdminDealTasks({ status: "open", limit: 200 }) : Promise.resolve(null),
      flags.includeAdminTaskData ? api.getAdminActionRuns({ limit: 200 }) : Promise.resolve(null),
    ]);

    const next: CachedHubData = {
      ...previous,
      cachedAt: Date.now(),
      coverage: { ...previous.coverage },
    };

    if (hubResult.status === "fulfilled" && hubResult.value) {
      next.snapshot = hubResult.value;
      next.coverage.agentHub = true;
    }
    if (statusResult.status === "fulfilled") {
      next.status = statusResult.value;
      next.coverage.status = true;
    }
    if (sessionsResult.status === "fulfilled" && sessionsResult.value) {
      next.sessions = (sessionsResult.value as PaginatedSessions).sessions;
      next.coverage.sessions = true;
    }
    if (cronResult.status === "fulfilled" && cronResult.value) {
      next.cronJobs = cronResult.value;
      next.coverage.cronJobs = true;
    }
    if (sourceInboxResult.status === "fulfilled" && sourceInboxResult.value) {
      next.sourceInbox = sourceInboxResult.value;
      next.coverage.sourceInbox = true;
    }
    if (dealTasksResult.status === "fulfilled" && dealTasksResult.value) {
      next.dealTasks = dealTasksResult.value.items;
      next.coverage.dealTasks = true;
    }
    if (actionRunsResult.status === "fulfilled" && actionRunsResult.value) {
      next.actionRuns = actionRunsResult.value.items;
      next.coverage.actionRuns = true;
    }

    const failed = [hubResult, statusResult, sessionsResult, cronResult, sourceInboxResult, dealTasksResult, actionRunsResult].find(
      (result) => result.status === "rejected",
    );
    const error =
      failed?.status === "rejected"
        ? failed.reason instanceof Error
          ? failed.reason.message
          : "Some hub data failed"
        : null;

    return { data: writeCachedHubData(next), error };
  })();

  hubDataInflight.set(key, promise);
  try {
    return await promise;
  } finally {
    if (hubDataInflight.get(key) === promise) {
      hubDataInflight.delete(key);
    }
  }
}

export async function preloadRealEstateHubData(pathname = window.location.pathname): Promise<void> {
  await loadHubData(flagsForPath(pathname)).catch(() => undefined);
}

export function useRealEstateHubData(): HubData {
  const { pathname } = useLocation();
  const requestFlags = useMemo(() => flagsForPath(pathname), [pathname]);
  const initialCache = readCachedHubData();
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(() => initialCache?.snapshot ?? null);
  const [status, setStatus] = useState<StatusResponse | null>(() => initialCache?.status ?? null);
  const [sourceInbox, setSourceInboxState] = useState<SourceInboxResponse | null>(() => initialCache?.sourceInbox ?? null);
  const [sessions, setSessions] = useState<SessionInfo[]>(() => initialCache?.sessions ?? []);
  const [cronJobs, setCronJobs] = useState<CronJob[]>(() => initialCache?.cronJobs ?? []);
  const [dealTasks, setDealTasks] = useState<AdminDealTask[]>(() => initialCache?.dealTasks ?? []);
  const [actionRuns, setActionRuns] = useState<AdminActionRun[]>(() => initialCache?.actionRuns ?? []);
  const [loading, setLoading] = useState(() => !hasVisibleHubData(initialCache));
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshSeq = useRef(0);

  const applyCachedData = useCallback((next: CachedHubData) => {
    setSnapshot(next.snapshot);
    setStatus(next.status);
    setSourceInboxState(next.sourceInbox);
    setSessions(next.sessions);
    setCronJobs(next.cronJobs);
    setDealTasks(next.dealTasks);
    setActionRuns(next.actionRuns);
  }, []);

  const setSourceInbox = useCallback((nextSourceInbox: SourceInboxResponse | null) => {
    setSourceInboxState(nextSourceInbox);
    const next = {
      ...(readCachedHubData() ?? emptyCachedHubData()),
      cachedAt: Date.now(),
      coverage: {
        ...(readCachedHubData()?.coverage ?? {}),
        sourceInbox: Boolean(nextSourceInbox),
      },
      sourceInbox: nextSourceInbox,
    };
    writeCachedHubData(next);
  }, []);

  const refresh = useCallback(async (options?: { force?: boolean }) => {
    const refreshId = ++refreshSeq.current;
    setRefreshing(true);
    setError(null);
    try {
      const result = await loadHubData(requestFlags, options?.force);
      if (refreshSeq.current !== refreshId) return;
      applyCachedData(result.data);
      setError(result.error);
    } finally {
      if (refreshSeq.current === refreshId) {
        setRefreshing(false);
      }
    }
  }, [applyCachedData, requestFlags]);

  useEffect(() => {
    let cancelled = false;
    const cached = readCachedHubData();
    if (cached) applyCachedData(cached);
    setLoading(!hasVisibleHubData(cached));
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

  // Instant refresh the moment the agent finishes a turn (the common
  // "I told it to add/move/update X and want to see it" case). The 25s poll
  // below stays as the fallback for background cron/heartbeat changes.
  useRefreshOnAgentTurn(refresh);

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

  return { actionRuns, cronJobs, dealTasks, error, loading, refresh, refreshing, setSourceInbox, sourceInbox, sessions, snapshot, status };
}

export function useHubHeader(
  title: string,
  data: HubData,
  options?: {
    onRefresh?: () => void | Promise<void>;
    refreshing?: boolean;
    /** Extra content appended after the gateway status in the breadcrumb bar
     *  (e.g. Memory folds its "· N jobs" here instead of a separate hero). */
    afterExtra?: ReactNode;
  },
) {
  const { setAfterTitle, setEnd, setTitle } = usePageHeader();
  const afterExtra = options?.afterExtra ?? null;
  const gatewayOnline = Boolean(data.snapshot?.gateway.running || data.status?.gateway_running);
  const isRefreshing = data.loading || data.refreshing || Boolean(options?.refreshing);
  const defaultRefresh = useCallback(() => void data.refresh({ force: true }), [data.refresh]);
  const refresh = options?.onRefresh ?? defaultRefresh;

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
        {afterExtra}
      </span>,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={isRefreshing}>
        <RefreshCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setTitle(null);
      setAfterTitle(null);
      setEnd(null);
    };
  }, [afterExtra, gatewayOnline, isRefreshing, refresh, setAfterTitle, setEnd, setTitle, title]);
}
