import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { StatusResponse } from "@/lib/api";

const POLL_MS = 10_000;

function sameShellStatus(a: StatusResponse | null, b: StatusResponse): boolean {
  return (
    a?.gateway_state === b.gateway_state &&
    a?.gateway_running === b.gateway_running &&
    a?.active_sessions === b.active_sessions
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
    const load = () => {
      if (document.visibilityState === "hidden") return;
      api
        .getStatus()
        .then((next) => {
          if (!cancelled) {
            setStatus((prev) => (sameShellStatus(prev, next) ? prev : next));
          }
        })
        .catch(() => {});
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    load();
    const id = setInterval(load, POLL_MS);
    window.addEventListener("focus", load);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      window.removeEventListener("focus", load);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return status;
}
