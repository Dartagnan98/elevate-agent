type StartupPerfEvent = {
  detail?: string;
  durationMs?: number;
  name: string;
  startMs: number;
  status?: number;
};

type StartupPerfSnapshot = {
  events: StartupPerfEvent[];
  reason: string;
  totalMs: number;
};

declare global {
  interface Window {
    __ELEVATE_STARTUP_PERF__?: StartupPerfSnapshot;
  }
}

const TRACE_WINDOW_MS = 30_000;
const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
const events: StartupPerfEvent[] = [];
const reportedReasons = new Set<string>();

function nowMs(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function elapsedMs(): number {
  return nowMs() - startedAt;
}

function stillTracing(): boolean {
  return elapsedMs() <= TRACE_WINDOW_MS;
}

export function markStartup(name: string, detail?: string): void {
  if (!stillTracing()) return;
  events.push({
    detail,
    name,
    startMs: Math.round(elapsedMs()),
  });
}

export function recordStartupApiTiming(
  url: string,
  method: string,
  status: number,
  durationMs: number,
  ok: boolean,
): void {
  if (!stillTracing()) return;
  const route = url.split("?")[0] || url;
  events.push({
    durationMs: Math.round(durationMs),
    name: `api:${method.toUpperCase()} ${route}`,
    startMs: Math.round(elapsedMs() - durationMs),
    status,
    detail: ok ? undefined : "error",
  });
}

export function reportStartup(reason: string): void {
  const totalMs = Math.round(elapsedMs());
  const snapshot: StartupPerfSnapshot = {
    events: [...events],
    reason,
    totalMs,
  };
  if (typeof window !== "undefined") {
    window.__ELEVATE_STARTUP_PERF__ = snapshot;
  }
  if (reportedReasons.has(reason)) return;
  reportedReasons.add(reason);
  if (typeof console === "undefined") return;
  const rows = snapshot.events.map((event) => ({
    ms: event.startMs,
    event: event.name,
    duration: event.durationMs == null ? "" : event.durationMs,
    status: event.status ?? "",
    detail: event.detail ?? "",
  }));
  console.groupCollapsed(`[startup] ${reason} in ${totalMs}ms`);
  console.table(rows);
  console.groupEnd();
}

markStartup("web:startup-performance-loaded");
