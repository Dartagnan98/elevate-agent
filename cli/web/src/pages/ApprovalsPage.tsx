import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, RefreshCw, X } from "lucide-react";
import { api } from "@/lib/api";
import type { SurfaceApproval } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Approvals = the decisions board. A heartbeat/experiment run creates */
/*  an approval when it produces something needing sign-off; the realtor */
/*  approves or rejects HERE (dashboard only — never Telegram). Mirrors  */
/*  CTRL Flow /ai/approvals.                                             */
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

type StatusVariant = "default" | "secondary" | "outline" | "success" | "warning";

function statusVariant(status: string): StatusVariant {
  if (status === "approved") return "success";
  if (status === "rejected") return "warning";
  return "outline";
}

function ApprovalCard({
  approval,
  onChanged,
}: {
  approval: SurfaceApproval;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const pending = approval.status === "pending";

  const resolve = async (decision: "approve" | "reject") => {
    setBusy(true);
    try {
      await api.resolveSurfaceApproval(approval.id, decision);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={statusVariant(approval.status)} className="shrink-0">
            {approval.status}
          </Badge>
          <Badge variant="secondary" className="shrink-0">
            {approval.category}
          </Badge>
          {approval.surface && (
            <span className="text-[11px] text-muted-foreground">· {approval.surface}</span>
          )}
          <span className="ml-auto text-[11px] text-muted-foreground/70">
            {timeAgo(approval.createdAt)}
          </span>
        </div>
        <p className="text-sm font-medium text-foreground">{approval.title}</p>
        {approval.description && (
          <p className="whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
            {approval.description}
          </p>
        )}
        {!pending && approval.resolutionNote && (
          <p className="text-[11px] italic text-muted-foreground">
            {approval.resolvedBy}: {approval.resolutionNote}
          </p>
        )}
        {pending && (
          <div className="flex justify-end gap-2 pt-1">
            <Button
              variant="ghost"
              onClick={() => resolve("reject")}
              disabled={busy}
              className="text-destructive hover:text-destructive"
            >
              <X className="h-4 w-4" /> Reject
            </Button>
            <Button onClick={() => resolve("approve")} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Approve
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type Tab = "pending" | "resolved";

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<SurfaceApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("pending");

  const load = useCallback(
    async (refresh: boolean, which: Tab) => {
      if (refresh) setRefreshing(true);
      try {
        const resp = await api.listSurfaceApprovals({ status: which });
        setApprovals(resp.approvals || []);
        setError(null);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    setLoading(true);
    load(false, tab);
    const id = window.setInterval(() => load(true, tab), 30000);
    return () => window.clearInterval(id);
  }, [load, tab]);

  const pendingCount = tab === "pending" ? approvals.length : undefined;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold text-foreground">Approvals</h1>
          <p className="text-sm text-muted-foreground">
            Sign off on what your surfaces propose. Dashboard only.
          </p>
        </div>
        <Button variant="ghost" onClick={() => load(true, tab)} disabled={refreshing}>
          {refreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Refresh
        </Button>
      </header>

      <div className="flex gap-1.5 border-b border-border pb-2">
        {(["pending", "resolved"] as Tab[]).map((t) => {
          const active = tab === t;
          return (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "h-8 rounded-md border px-3 text-xs font-medium capitalize transition-colors",
                active
                  ? "border-foreground/20 bg-secondary text-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
              )}
            >
              {t === "resolved" ? "History" : "Pending"}
              {t === "pending" && pendingCount ? ` (${pendingCount})` : ""}
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load approvals: {error}
        </div>
      ) : approvals.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          {tab === "pending" ? "Nothing waiting on you." : "No resolved approvals yet."}
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} onChanged={() => load(true, tab)} />
          ))}
        </div>
      )}
    </div>
  );
}
