import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { StatusResponse } from "@/lib/api";

const POLL_MS = 10_000;

/**
 * Sentinel returned when the /api/status fetch fails outright — the backend
 * itself is unreachable. Distinct from a healthy response and from the initial
 * `null` (never-loaded), so a dead backend is representable rather than served
 * as silently-stale prior data.
 */
export const BACKEND_UNREACHABLE = {
  gateway_state: "unreachable",
  gateway_running: false,
  database: { reachable: false, latency_ms: null, error: "Backend unreachable" },
} as StatusResponse;

export function isBackendUnreachable(status: StatusResponse | null): boolean {
  return status === BACKEND_UNREACHABLE;
}

function sameShellStatus(a: StatusResponse | null, b: StatusResponse): boolean {
  return (
    a?.gateway_state === b.gateway_state &&
    a?.gateway_running === b.gateway_running &&
    a?.active_sessions === b.active_sessions &&
    a?.database?.reachable === b.database?.reachable
  );
}

/**
 * Light-weight status poll for the app shell (sidebar). The Status page uses
 * its own faster interval; we keep this slower to avoid duplicate load.
 */
export function useSidebarStatus() {
  const [status, setStatus] = useState<StatusResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = (refresh = false) => {
      if (document.visibilityState === "hidden") return;
      api
        .getStatus({ refresh })
        .then((next) => {
          if (!cancelled) {
            setStatus((prev) => (sameShellStatus(prev, next) ? prev : next));
          }
        })
        .catch(() => {
          // A failed fetch means the backend is unreachable. Surface it as an
          // explicit sentinel instead of swallowing it and keeping stale data.
          if (!cancelled) setStatus(BACKEND_UNREACHABLE);
        });
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") load(true);
    };
    load(true);
    const id = setInterval(load, POLL_MS);
    const onFocus = () => load(true);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return status;
}
