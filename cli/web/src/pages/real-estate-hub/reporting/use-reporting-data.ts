import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import {
  buildReportingSnapshot,
  reportingInputsFromFetchResults,
  REPORTING_DEAL_LIMIT,
  REPORTING_PERIOD_DAYS,
  REPORTING_SEND_LIMIT,
} from "./reporting-data";
import type { ReportingSnapshotInput } from "./reporting-data";

// Coverage is context only, not a funnel input. Keep this bounded so opening
// Reporting does not rebuild the full source-inbox profile universe.
const REPORTING_SOURCE_LIMIT = 500;
export const REPORTING_REQUEST_TIMEOUT_MS = 12_000;
export const REPORTING_AUTO_REFRESH_MS = 120_000;

const EMPTY_INPUTS: ReportingSnapshotInput = {
  inbox: null,
  sends: null,
  deals: null,
  goals: null,
};

export function withReportingTimeout<T>(
  request: Promise<T>,
  label: string,
  timeoutMs = REPORTING_REQUEST_TIMEOUT_MS,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      reject(new Error(`${label} timed out after ${Math.ceil(timeoutMs / 1000)} seconds.`));
    }, timeoutMs);
    request.then(
      (value) => {
        globalThis.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        globalThis.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/**
 * Fetches the reporting sources once per refresh and recomputes the snapshot
 * for the requested window. The fetches are window-independent (newest-first
 * reads bounded by REPORTING_SEND_LIMIT / REPORTING_DEAL_LIMIT), so changing
 * `periodDays` is a pure client-side recompute — no refetch required.
 */
export function useReportingData(periodDays: number = REPORTING_PERIOD_DAYS) {
  const [inputs, setInputs] = useState<ReportingSnapshotInput>(EMPTY_INPUTS);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [initialAsOf] = useState(Date.now);
  const requestSequence = useRef(0);
  const inflight = useRef<Promise<void> | null>(null);
  const mounted = useRef(true);

  const runRefresh = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setRefreshing(true);

    const results = await Promise.allSettled([
      withReportingTimeout(
        api.getSourceInbox(REPORTING_SOURCE_LIMIT, { debug: true }),
        "Lead coverage",
      ),
      withReportingTimeout(
        api.getSourceInboxSent(REPORTING_SEND_LIMIT, false),
        "Send history",
      ),
      withReportingTimeout(
        api.getAdminDeals({ status: null, limit: REPORTING_DEAL_LIMIT }),
        "Closed deals",
      ),
      withReportingTimeout(api.getCrmGoals(), "Goals"),
    ]);

    if (!mounted.current || sequence !== requestSequence.current) return;
    const next = reportingInputsFromFetchResults(results);
    setInputs(next.inputs);
    if (next.fulfilledCount > 0) setUpdatedAt(Date.now());
    setError(
      next.failures.length > 0
        ? next.fulfilledCount === 0
          ? `Reporting is unavailable. Could not refresh ${next.failures.join(", ")}.`
          : `Reporting is partial. Could not refresh ${next.failures.join(", ")}.`
        : null,
    );
    setLoading(false);
    setRefreshing(false);
  }, []);

  const refresh = useCallback((): Promise<void> => {
    if (inflight.current) return inflight.current;
    const request = runRefresh().finally(() => {
      if (inflight.current === request) inflight.current = null;
    });
    inflight.current = request;
    return request;
  }, [runRefresh]);

  useEffect(() => {
    mounted.current = true;
    const initialLoad = window.setTimeout(() => void refresh(), 0);
    return () => {
      window.clearTimeout(initialLoad);
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, [refresh]);

  useRefreshOnAgentTurn(refresh);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const refreshIfVisible = () => {
      if (!document.hidden) void refresh();
    };
    const interval = window.setInterval(refreshIfVisible, REPORTING_AUTO_REFRESH_MS);
    document.addEventListener("visibilitychange", refreshIfVisible);
    window.addEventListener("focus", refreshIfVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshIfVisible);
      window.removeEventListener("focus", refreshIfVisible);
    };
  }, [refresh]);

  const snapshot = useMemo(
    () => buildReportingSnapshot(inputs, updatedAt ?? initialAsOf, periodDays),
    [initialAsOf, inputs, periodDays, updatedAt],
  );

  return { snapshot, loading, refreshing, error, updatedAt, refresh };
}
