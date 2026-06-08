import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Clock, History, Loader2, RefreshCw, UserRound, X } from "lucide-react";
import { api } from "@/lib/api";
import type { SurfaceApproval, SurfaceTask } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { Select, SelectOption } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Approvals = operator decisions plus human-assigned tasks. CortextOS */
/*  exposes Your Tasks / Approvals / History; Elevate backs those lanes */
/*  with native surface_tasks and surface_approvals only.               */
/* ------------------------------------------------------------------ */

type ApprovalTab = "human" | "pending" | "history";
type BadgeTone = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";

const PRIORITY_TONE: Record<string, string> = {
  urgent: "text-destructive",
  high: "text-warning",
  normal: "text-muted-foreground",
  low: "text-muted-foreground/70",
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

function unique(values: Array<string | null | undefined>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const clean = String(value || "").trim();
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

function approvalVariant(status: string): BadgeTone {
  if (status === "approved") return "success";
  if (status === "rejected") return "destructive";
  return "outline";
}

function taskVariant(status: string): BadgeTone {
  if (status === "completed") return "success";
  if (status === "blocked") return "warning";
  if (status === "cancelled") return "destructive";
  if (status === "in_progress") return "secondary";
  return "outline";
}

function categoryLabel(category?: string | null): string {
  return String(category || "other").replace(/-/g, " ");
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] uppercase tracking-wide text-muted-foreground/80">
        {label}
      </Label>
      {children}
    </div>
  );
}

function ApprovalDetail({
  approval,
  onClose,
  onResolved,
}: {
  approval: SurfaceApproval;
  onClose: () => void;
  onResolved: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const pending = approval.status === "pending";

  const resolve = async (decision: "approve" | "reject") => {
    setBusy(decision);
    try {
      await api.resolveSurfaceApproval(approval.id, decision, note.trim() || undefined);
      onResolved();
      onClose();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{approval.title}</p>
        <p className="text-[11px] text-muted-foreground">Approval ID: {approval.id}</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={approvalVariant(approval.status)}>{approval.status}</Badge>
        <Badge variant="secondary">{categoryLabel(approval.category)}</Badge>
        {approval.surface && <Badge variant="outline">{approval.surface}</Badge>}
      </div>

      <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
        <div>
          <span className="block text-[11px] uppercase tracking-wide text-muted-foreground/70">Requested by</span>
          <span className="font-medium text-foreground/85">{approval.surface || "system"}</span>
        </div>
        <div>
          <span className="block text-[11px] uppercase tracking-wide text-muted-foreground/70">Created</span>
          <span>{timeAgo(approval.createdAt) || approval.createdAt || "-"}</span>
        </div>
        {approval.resolvedAt && (
          <>
            <div>
              <span className="block text-[11px] uppercase tracking-wide text-muted-foreground/70">Resolved by</span>
              <span className="font-medium text-foreground/85">{approval.resolvedBy || "-"}</span>
            </div>
            <div>
              <span className="block text-[11px] uppercase tracking-wide text-muted-foreground/70">Resolved</span>
              <span>{timeAgo(approval.resolvedAt) || approval.resolvedAt}</span>
            </div>
          </>
        )}
      </div>

      {approval.description && (
        <Field label="Context">
          <p className="whitespace-pre-wrap rounded-md bg-secondary/30 px-3 py-2 text-xs leading-5 text-muted-foreground">
            {approval.description}
          </p>
        </Field>
      )}

      {approval.resolutionNote && (
        <Field label="Resolution note">
          <p className="whitespace-pre-wrap rounded-md bg-secondary/30 px-3 py-2 text-xs leading-5 text-muted-foreground">
            {approval.resolutionNote}
          </p>
        </Field>
      )}

      {pending && (
        <Field label="Decision note">
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            placeholder="Optional note for this decision"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-foreground/30"
          />
        </Field>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={!!busy}>
          Close
        </Button>
        {pending && (
          <>
            <Button
              variant="ghost"
              onClick={() => resolve("reject")}
              disabled={!!busy}
              className="text-destructive hover:text-destructive"
            >
              {busy === "reject" ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
              Reject
            </Button>
            <Button onClick={() => resolve("approve")} disabled={!!busy}>
              {busy === "approve" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Approve
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function ApprovalCard({
  approval,
  onOpen,
  onChanged,
}: {
  approval: SurfaceApproval;
  onOpen: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const pending = approval.status === "pending";

  const resolve = async (decision: "approve" | "reject") => {
    setBusy(decision);
    try {
      await api.resolveSurfaceApproval(approval.id, decision);
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="transition-colors hover:bg-secondary/20">
      <CardContent className="space-y-2 p-3">
        <button type="button" onClick={onOpen} className="block w-full space-y-2 text-left">
          <div className="flex flex-wrap items-start gap-1.5">
            <p className="min-w-0 flex-1 text-sm font-medium leading-5 text-foreground">{approval.title}</p>
            <Badge variant={approvalVariant(approval.status)} className="shrink-0">{approval.status}</Badge>
            <Badge variant="secondary" className="shrink-0">{categoryLabel(approval.category)}</Badge>
          </div>
          {approval.description && (
            <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">{approval.description}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span>{approval.surface || "system"}</span>
            <Clock className="h-3 w-3" />
            <span>{timeAgo(approval.createdAt)}</span>
            {approval.resolvedAt && <span>resolved {timeAgo(approval.resolvedAt)}</span>}
          </div>
        </button>
        {pending && (
          <div className="flex justify-end gap-2 border-t border-border pt-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => resolve("reject")}
              disabled={!!busy}
              className="text-destructive hover:text-destructive"
            >
              {busy === "reject" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
              Reject
            </Button>
            <Button size="sm" onClick={() => resolve("approve")} disabled={!!busy}>
              {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              Approve
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HumanTaskCard({
  task,
  onOpen,
  onDone,
}: {
  task: SurfaceTask;
  onOpen: () => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const done = async () => {
    setBusy(true);
    try {
      await api.updateSurfaceTask(task.id, { status: "completed" });
      onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="transition-colors hover:bg-secondary/20">
      <CardContent className="flex items-start justify-between gap-3 p-3">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 space-y-1 text-left">
          <p className="line-clamp-2 text-sm font-medium leading-5 text-foreground">{task.title}</p>
          {task.description && <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">{task.description}</p>}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span className={cn("font-medium", PRIORITY_TONE[task.priority])}>{task.priority}</span>
            <Badge variant={taskVariant(task.status)}>{task.status.replace("_", " ")}</Badge>
            <span>from {task.createdBy || task.created_by || task.assignee || "unknown"}</span>
            <Clock className="h-3 w-3" />
            <span>{timeAgo(task.createdAt || task.created_at)}</span>
          </div>
        </button>
        <Button size="sm" variant="outline" onClick={done} disabled={busy} className="shrink-0">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Done
        </Button>
      </CardContent>
    </Card>
  );
}

function CardSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-start gap-1.5">
          <Skeleton className="h-5 min-w-0 flex-1" />
          <Skeleton className="h-5 w-16 shrink-0 rounded-full" />
          <Skeleton className="h-5 w-20 shrink-0 rounded-full" />
        </div>
        <Skeleton className="h-4 w-4/5" />
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-12" />
        </div>
      </CardContent>
    </Card>
  );
}

function CardListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="grid gap-2" aria-busy="true">
      {Array.from({ length: rows }).map((_, index) => (
        <CardSkeleton key={index} />
      ))}
    </div>
  );
}

export default function ApprovalsPage() {
  const [pending, setPending] = useState<SurfaceApproval[]>([]);
  const [resolved, setResolved] = useState<SurfaceApproval[]>([]);
  const [humanTasks, setHumanTasks] = useState<SurfaceTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<ApprovalTab>("pending");
  const [surfaceFilter, setSurfaceFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedApproval, setSelectedApproval] = useState<SurfaceApproval | null>(null);
  const [selectedTask, setSelectedTask] = useState<SurfaceTask | null>(null);

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    try {
      const [pendingResp, resolvedResp, humanResp] = await Promise.all([
        api.listSurfaceApprovals({ status: "pending" }),
        api.listSurfaceApprovals({ status: "resolved" }),
        api.listSurfaceTasks({ assignee: "human" }),
      ]);
      setPending(pendingResp.approvals || []);
      setResolved(resolvedResp.approvals || []);
      setHumanTasks((humanResp.tasks || []).filter((task) => task.status !== "completed" && !task.archived));
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load(false);
    const id = window.setInterval(() => load(true), 30000);
    return () => window.clearInterval(id);
  }, [load]);

  const surfaces = useMemo(
    () => unique([...pending, ...resolved].map((approval) => approval.surface)),
    [pending, resolved],
  );
  const categories = useMemo(
    () => unique([...pending, ...resolved].map((approval) => approval.category)),
    [pending, resolved],
  );
  const historyItems = useMemo(
    () => resolved.filter((approval) => {
      if (surfaceFilter && approval.surface !== surfaceFilter) return false;
      if (categoryFilter && approval.category !== categoryFilter) return false;
      return true;
    }),
    [categoryFilter, resolved, surfaceFilter],
  );

  const openApproval = selectedApproval;
  const openTask = selectedTask;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold text-foreground">Approvals</h1>
          <p className="text-sm text-muted-foreground">
            Human tasks, pending decisions, and resolved approval history.
          </p>
        </div>
        <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </Button>
      </header>

      {openApproval && (
        <Modal title="Approval" onClose={() => setSelectedApproval(null)}>
          <ApprovalDetail
            approval={openApproval}
            onClose={() => setSelectedApproval(null)}
            onResolved={() => load(true)}
          />
        </Modal>
      )}

      {openTask && (
        <Modal title="Your task" onClose={() => setSelectedTask(null)}>
          <div className="space-y-3">
            <p className="text-sm font-medium text-foreground">{openTask.title}</p>
            {openTask.description && (
              <p className="whitespace-pre-wrap rounded-md bg-secondary/30 px-3 py-2 text-xs leading-5 text-muted-foreground">
                {openTask.description}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <Badge variant={taskVariant(openTask.status)}>{openTask.status.replace("_", " ")}</Badge>
              <span className={cn("font-medium", PRIORITY_TONE[openTask.priority])}>{openTask.priority}</span>
              {openTask.project && <Badge variant="outline">{openTask.project}</Badge>}
              <span>{timeAgo(openTask.createdAt || openTask.created_at)}</span>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setSelectedTask(null)}>
                Close
              </Button>
              <Button
                onClick={async () => {
                  await api.updateSurfaceTask(openTask.id, { status: "completed" });
                  setSelectedTask(null);
                  await load(true);
                }}
              >
                <Check className="h-4 w-4" />
                Done
              </Button>
            </div>
          </div>
        </Modal>
      )}

      <div className="flex flex-wrap gap-1.5 border-b border-border pb-2">
        {([
          { key: "human", label: "Your Tasks", icon: UserRound, count: humanTasks.length },
          { key: "pending", label: "Approvals", icon: Check, count: pending.length },
          { key: "history", label: "History", icon: History, count: resolved.length },
        ] as Array<{ key: ApprovalTab; label: string; icon: typeof Check; count: number }>).map((item) => {
          const Icon = item.icon;
          const active = tab === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition-colors",
                active
                  ? "border-foreground/20 bg-secondary text-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {item.label}
              {item.count > 0 && (
                <span className="rounded-full bg-foreground/10 px-1.5 py-0.5 text-[10px] tabular-nums">
                  {item.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load approvals: {error}
        </div>
      ) : tab === "human" ? (
        loading ? (
          <CardListSkeleton rows={5} />
        ) : humanTasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
            No tasks assigned to you right now.
          </div>
        ) : (
          <div className="grid gap-2">
            {humanTasks.map((task) => (
              <HumanTaskCard
                key={task.id}
                task={task}
                onOpen={() => setSelectedTask(task)}
                onDone={() => load(true)}
              />
            ))}
          </div>
        )
      ) : tab === "pending" ? (
        loading ? (
          <CardListSkeleton rows={5} />
        ) : pending.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
            No pending approvals. You are all caught up.
          </div>
        ) : (
          <div className="grid gap-2">
            {pending.map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                onOpen={() => setSelectedApproval(approval)}
                onChanged={() => load(true)}
              />
            ))}
          </div>
        )
      ) : (
        <div className="space-y-4">
          <section className="rounded-lg border border-border bg-card/40 p-3">
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Surface">
                <Select value={surfaceFilter} onValueChange={setSurfaceFilter} className="w-52">
                  <SelectOption value="">All surfaces</SelectOption>
                  {surfaces.map((surface) => (
                    <SelectOption key={surface} value={surface}>
                      {surface}
                    </SelectOption>
                  ))}
                </Select>
              </Field>
              <Field label="Category">
                <Select value={categoryFilter} onValueChange={setCategoryFilter} className="w-52">
                  <SelectOption value="">All categories</SelectOption>
                  {categories.map((category) => (
                    <SelectOption key={category} value={category}>
                      {categoryLabel(category)}
                    </SelectOption>
                  ))}
                </Select>
              </Field>
              {(surfaceFilter || categoryFilter) && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSurfaceFilter("");
                    setCategoryFilter("");
                  }}
                >
                  Clear filters
                </Button>
              )}
              {loading ? (
                <Skeleton className="ml-auto h-4 w-28" />
              ) : (
                <span className="ml-auto text-xs text-muted-foreground">
                  Showing {historyItems.length} of {resolved.length}
                </span>
              )}
            </div>
          </section>

          {loading ? (
            <CardListSkeleton rows={5} />
          ) : historyItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
              No resolved approvals found.
            </div>
          ) : (
            <div className="grid gap-2">
              {historyItems.map((approval) => (
                <ApprovalCard
                  key={approval.id}
                  approval={approval}
                  onOpen={() => setSelectedApproval(approval)}
                  onChanged={() => load(true)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
