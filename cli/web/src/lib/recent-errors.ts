/**
 * Tiny ring buffer of recent runtime errors, attached once at module load.
 * The bug reporter reads this so a non-technical user never has to describe
 * what the app threw — it rides along automatically.
 */
const MAX = 20;
const buffer: string[] = [];

function push(entry: string) {
  buffer.push(entry);
  if (buffer.length > MAX) buffer.shift();
}

let installed = false;
export function installRecentErrorCapture() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (e) => {
    const where = e.filename ? ` (${e.filename}:${e.lineno})` : "";
    push(`error: ${e.message ?? "unknown"}${where}`);
  });
  window.addEventListener("unhandledrejection", (e) => {
    const reason = (e as PromiseRejectionEvent).reason;
    const msg = reason?.message ?? String(reason ?? "unknown");
    push(`unhandledrejection: ${msg}`);
  });
}

export function recentErrors(): string[] {
  return [...buffer];
}
