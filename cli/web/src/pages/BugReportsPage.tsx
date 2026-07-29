import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJSON } from "@/lib/api";
import { usePageHeader } from "@/contexts/usePageHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Check, RotateCcw, Loader2, ExternalLink } from "lucide-react";

type BugReport = {
  id: string;
  number: number;
  note: string;
  page: string | null;
  pageTitle: string | null;
  dealId: string | null;
  dealTitle: string | null;
  userAgent: string | null;
  viewport: string | null;
  reporter: string | null;
  consoleErrors: string[];
  screenshot: string | null;
  status: string;
  createdAt: string | null;
  resolvedAt: string | null;
};

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

export function BugReportsPage() {
  const { setTitle } = usePageHeader();
  const [reports, setReports] = useState<BugReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"open" | "all">("open");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);

  useEffect(() => {
    setTitle("Bug Reports");
    return () => setTitle(null);
  }, [setTitle]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await fetchJSON<{ ok: boolean; reports: BugReport[] }>(
        "/api/bug-reports",
        { headers: { "cache-control": "no-cache" } },
      );
      setReports(res.reports ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load reports.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setResolved = useCallback(
    async (r: BugReport, resolved: boolean) => {
      setBusyId(r.id);
      try {
        await fetchJSON(`/api/bug-reports/${r.id}/resolve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resolved }),
        });
        setReports((prev) =>
          prev.map((x) =>
            x.id === r.id
              ? { ...x, status: resolved ? "resolved" : "open" }
              : x,
          ),
        );
      } catch {
        /* leave as-is on failure */
      } finally {
        setBusyId(null);
      }
    },
    [],
  );

  const shown = useMemo(
    () => reports.filter((r) => (filter === "open" ? r.status === "open" : true)),
    [reports, filter],
  );
  const openCount = useMemo(
    () => reports.filter((r) => r.status === "open").length,
    [reports],
  );

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 p-4 sm:p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Bug Reports</h1>
          <p className="text-xs text-muted-foreground">
            {openCount} open · {reports.length} total
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
          {(["open", "all"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={cn(
                "rounded px-2.5 py-1 text-xs capitalize transition-colors",
                filter === f
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {loading ? (
        <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : shown.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
          {filter === "open"
            ? "No open bug reports. Nice."
            : "No bug reports yet."}
        </div>
      ) : (
        <ul className="space-y-3">
          {shown.map((r) => (
            <li
              key={r.id}
              className={cn(
                "rounded-lg border border-border bg-card p-3 shadow-sm",
                r.status === "resolved" && "opacity-60",
              )}
            >
              <div className="flex gap-3">
                {r.screenshot && (
                  <button
                    type="button"
                    onClick={() => setZoom(r.screenshot)}
                    className="shrink-0"
                    title="View screenshot"
                  >
                    <img
                      src={r.screenshot}
                      alt="Screenshot"
                      className="h-20 w-28 rounded border border-border object-cover"
                    />
                  </button>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="whitespace-pre-wrap break-words text-sm text-foreground">
                      <span className="mr-1.5 text-xs font-medium text-muted-foreground">
                        #{r.number}
                      </span>
                      {r.note}
                    </p>
                    {r.status === "resolved" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busyId === r.id}
                        onClick={() => setResolved(r, false)}
                        className="shrink-0 text-xs"
                      >
                        <RotateCcw className="mr-1 h-3 w-3" /> Reopen
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busyId === r.id}
                        onClick={() => setResolved(r, true)}
                        className="shrink-0 text-xs text-[#5E8AD0] hover:text-[#4a76bc]"
                      >
                        {busyId === r.id ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : (
                          <Check className="mr-1 h-3 w-3" />
                        )}
                        Mark fixed
                      </Button>
                    )}
                  </div>

                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                    <span>{timeAgo(r.createdAt)}</span>
                    {r.page && (
                      <span className="inline-flex items-center gap-1">
                        <ExternalLink className="h-3 w-3" />
                        {r.page}
                      </span>
                    )}
                    {r.viewport && <span>{r.viewport}</span>}
                    {r.dealId && <span>deal {r.dealId.slice(0, 8)}</span>}
                    {r.reporter && <span>by {r.reporter}</span>}
                  </div>

                  {r.consoleErrors && r.consoleErrors.length > 0 && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
                        {r.consoleErrors.length} recent error
                        {r.consoleErrors.length > 1 ? "s" : ""}
                      </summary>
                      <pre className="mt-1 max-h-40 overflow-auto rounded bg-background/60 p-2 text-[10px] leading-snug text-muted-foreground">
                        {r.consoleErrors.join("\n")}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {zoom && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-6"
          onClick={() => setZoom(null)}
        >
          <img
            src={zoom}
            alt="Screenshot full"
            className="max-h-full max-w-full rounded border border-border object-contain"
          />
        </div>
      )}
    </div>
  );
}

export default BugReportsPage;
