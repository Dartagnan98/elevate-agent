import { useCallback, useEffect, useMemo, useState } from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { Activity, Clock, FlaskConical, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListSkeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Activity = the fleet feed. Everything the agents did — heartbeat     */
/*  runs and cron runs — newest first, filterable by agent. Mirrors      */
/*  cortextOS /ai/activity.                                              */
/* ------------------------------------------------------------------ */

type Item = {
  kind: string;
  agent: string;
  ts: string;
  title: string;
  detail?: string | null;
  status?: string;
};

function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/[-_]/g, " ") : s;
}

function KindGlyph({ kind }: { kind: string }) {
  if (kind === "heartbeat") return <Activity className="h-4 w-4 text-success" />;
  if (kind === "experiment") return <FlaskConical className="h-4 w-4 text-warning" />;
  return <Clock className="h-4 w-4 text-muted-foreground" />;
}

export default function ActivityPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState("");

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const resp = await api.getActivity({ limit: 150 });
      setItems(resp.items || []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
    const id = window.setInterval(() => load(true), 20000);
    return () => window.clearInterval(id);
  }, [load]);
  useRefreshOnAgentTurn(() => void load(true));

  const agents = useMemo(() => [...new Set(items.map((i) => i.agent))], [items]);
  const feed = useMemo(
    () => (agentFilter ? items.filter((i) => i.agent === agentFilter) : items),
    [items, agentFilter],
  );

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-foreground" />
            <h1 className="text-lg font-semibold text-foreground">Activity</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Everything your agents did — heartbeat runs and scheduled jobs, newest first.
          </p>
        </div>
        <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Refresh
        </Button>
      </header>

      {loading ? (
        <ListSkeleton rows={6} />
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load activity: {error}
        </div>
      ) : (
        <>
          {agents.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setAgentFilter("")}
                className={cn(
                  "h-7 rounded-md border px-2.5 text-[11px] font-medium transition-colors",
                  agentFilter === ""
                    ? "border-foreground/20 bg-secondary text-foreground"
                    : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                All
              </button>
              {agents.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAgentFilter(a)}
                  className={cn(
                    "h-7 rounded-md border px-2.5 text-[11px] font-medium transition-colors",
                    agentFilter === a
                      ? "border-foreground/20 bg-secondary text-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {titleCase(a)}
                </button>
              ))}
            </div>
          )}

          {feed.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
              No activity yet — runs show up here as your agents fire.
            </div>
          ) : (
            <ul className="space-y-2">
              {feed.map((i, idx) => (
                <li
                  key={`${i.kind}-${i.agent}-${i.ts}-${idx}`}
                  className="flex items-start gap-3 rounded-md border border-border bg-card/40 p-2.5"
                >
                  <div className="mt-0.5 shrink-0">
                    <KindGlyph kind={i.kind} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-xs font-medium text-foreground">{titleCase(i.agent)}</span>
                      <Badge variant="secondary" className="shrink-0">
                        {i.kind}
                      </Badge>
                      {i.status && i.status !== "ok" && (
                        <Badge variant="warning" className="shrink-0">
                          {i.status}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs leading-5 text-foreground/90">{i.title}</p>
                    {i.detail && (
                      <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{i.detail}</p>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] text-muted-foreground/80">{timeAgo(i.ts)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
