import { useCallback, useEffect, useMemo, useState } from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { ArrowRight, Hash, Loader2, MessageSquare, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentHandoff } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Comms = the agent message bus. Agents hand work to each other via   */
/*  handoffs (from → to, task, status); this is the feed. The Channels   */
/*  panel shows the external delivery channels (Telegram/etc.). Mirrors  */
/*  cortextOS /ai/comms (message feed + channels).                       */
/* ------------------------------------------------------------------ */

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

type SV = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";
function statusVariant(s: string): SV {
  switch (s) {
    case "completed":
    case "done":
      return "success";
    case "failed":
    case "error":
      return "destructive";
    case "in_progress":
    case "claimed":
      return "secondary";
    case "pending":
    case "queued":
      return "outline";
    default:
      return "outline";
  }
}
const PRIORITY_TONE: Record<string, string> = {
  urgent: "text-destructive",
  high: "text-warning",
  normal: "text-muted-foreground",
  low: "text-muted-foreground/70",
};

function HandoffRow({
  h,
  nameOf,
}: {
  h: AgentHandoff;
  nameOf: (id: string) => string;
}) {
  return (
    <li className="space-y-1.5 rounded-md border border-border bg-card/40 p-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        <span className="font-medium text-foreground/90">{nameOf(h.fromAgentId)}</span>
        <ArrowRight className="h-3 w-3 text-muted-foreground" />
        <span className="font-medium text-foreground/90">{nameOf(h.toAgentId)}</span>
        <Badge variant={statusVariant(String(h.status))} className="shrink-0">
          {String(h.status).replace("_", " ")}
        </Badge>
        <span className={cn("font-medium", PRIORITY_TONE[h.priority])}>{h.priority}</span>
        <span className="ml-auto text-muted-foreground/70">{timeAgo(h.createdAt)}</span>
      </div>
      <p className="text-xs font-medium leading-5 text-foreground/90">{h.title}</p>
      {h.task && <p className="line-clamp-2 text-[11px] leading-5 text-muted-foreground">{h.task}</p>}
      {h.errorMessage && (
        <p className="text-[11px] text-destructive">{h.errorMessage}</p>
      )}
    </li>
  );
}

export default function CommsPage() {
  const [handoffs, setHandoffs] = useState<AgentHandoff[]>([]);
  const [channels, setChannels] = useState<
    { platform: string; id: string; name: string; type?: string }[]
  >([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState<string>("");

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [hs, ch, hub] = await Promise.all([
        api.getAgentHandoffs({ limit: 100 }),
        api.getCommsChannels().catch(() => ({ channels: [] as typeof channels })),
        api
          .getAgentHub({ lite: true })
          .catch(() => ({ agents: [] as { id: string; name: string }[] })),
      ]);
      setHandoffs(hs.items || []);
      setChannels(ch.channels || []);
      const m: Record<string, string> = {};
      for (const a of hub.agents || []) m[a.id] = a.name;
      setNames(m);
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

  const nameOf = useCallback(
    (id: string) => names[id] || (id ? id.replace(/-/g, " ") : "—"),
    [names],
  );

  const agentIds = useMemo(() => {
    const set = new Set<string>();
    for (const h of handoffs) {
      if (h.fromAgentId) set.add(h.fromAgentId);
      if (h.toAgentId) set.add(h.toAgentId);
    }
    return [...set];
  }, [handoffs]);

  const feed = useMemo(() => {
    const f = agentFilter
      ? handoffs.filter((h) => h.fromAgentId === agentFilter || h.toAgentId === agentFilter)
      : handoffs;
    return [...f].sort(
      (a, b) => new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime(),
    );
  }, [handoffs, agentFilter]);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-foreground" />
            <h1 className="text-lg font-semibold text-foreground">Comms</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            The agent bus — how your agents hand work to each other, and the channels they reach out on.
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
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load comms: {error}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          {/* Message feed */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
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
              {agentIds.map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setAgentFilter(id)}
                  className={cn(
                    "h-7 rounded-md border px-2.5 text-[11px] font-medium capitalize transition-colors",
                    agentFilter === id
                      ? "border-foreground/20 bg-secondary text-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {nameOf(id)}
                </button>
              ))}
            </div>
            {feed.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
                No handoffs yet — agents will show their cross-talk here as they pass work.
              </div>
            ) : (
              <ul className="space-y-2">
                {feed.map((h) => (
                  <HandoffRow key={h.id} h={h} nameOf={nameOf} />
                ))}
              </ul>
            )}
          </div>

          {/* Channels */}
          <div className="space-y-2">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
              Channels
            </span>
            {channels.length === 0 ? (
              <Card>
                <CardContent className="p-3 text-[11px] italic text-muted-foreground/70">
                  No channels connected. Connect Telegram/Slack/etc. to route agent output.
                </CardContent>
              </Card>
            ) : (
              <ul className="space-y-1.5">
                {channels.map((c) => (
                  <li
                    key={`${c.platform}:${c.id}`}
                    className="flex items-center gap-2 rounded-md border border-border bg-card/40 p-2"
                  >
                    <Hash className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-foreground/90">{c.name}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {c.platform}
                        {c.type ? ` · ${c.type}` : ""}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
