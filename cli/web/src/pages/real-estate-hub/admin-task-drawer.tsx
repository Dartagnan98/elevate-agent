import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { ExternalLink, Loader2, X as CloseIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminActionRun, AdminDealTask } from "@/lib/api";
import type { HubData } from "./_shared/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type AdminTaskTarget =
  | { kind: "deal-task"; id: string }
  | { kind: "action-run"; id: string }
  | null;

const AdminTaskDrawerContext = createContext<{
  openDealTask: (taskId: string) => void;
  openActionRun: (runId: string) => void;
} | null>(null);

export function useAdminTaskDrawer() {
  return useContext(AdminTaskDrawerContext);
}

export function AdminTaskDrawerProvider({
  children,
  data,
}: {
  children: ReactNode;
  data: HubData;
}) {
  const [target, setTarget] = useState<AdminTaskTarget>(null);
  const openDealTask = useCallback((id: string) => setTarget({ kind: "deal-task", id }), []);
  const openActionRun = useCallback((id: string) => setTarget({ kind: "action-run", id }), []);
  const close = useCallback(() => setTarget(null), []);
  const ctx = useMemo(() => ({ openDealTask, openActionRun }), [openDealTask, openActionRun]);
  return (
    <AdminTaskDrawerContext.Provider value={ctx}>
      {children}
      {target && <AdminTaskDialog data={data} target={target} onClose={close} />}
    </AdminTaskDrawerContext.Provider>
  );
}

function AdminTaskDialog({
  data,
  target,
  onClose,
}: {
  data: HubData;
  target: NonNullable<AdminTaskTarget>;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const task: AdminDealTask | null = useMemo(() => {
    if (target.kind !== "deal-task") return null;
    return data.dealTasks.find((t) => t.id === target.id) ?? null;
  }, [data.dealTasks, target]);

  const run: AdminActionRun | null = useMemo(() => {
    if (target.kind !== "action-run") return null;
    return data.actionRuns.find((r) => r.id === target.id) ?? null;
  }, [data.actionRuns, target]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={target.kind === "deal-task" ? "Deal task detail" : "Action run detail"}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-6 animate-[fade-in_120ms_ease-out]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-lg border border-border bg-background shadow-[0_24px_90px_rgba(0,0,0,0.32)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <div className="font-mono-ui text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
              {target.kind === "deal-task" ? "Deal task" : "Action run"}
            </div>
            <div className="mt-1 truncate text-[1.02rem] font-semibold leading-tight text-foreground">
              {task?.title || run?.registryName || run?.skill || <Skeleton className="h-5 w-48" />}
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close task drawer"
            title="Close"
            className="text-foreground/75 hover:text-foreground"
          >
            <CloseIcon className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 text-sm leading-5">
          {task && <DealTaskBody task={task} data={data} onClose={onClose} />}
          {run && <ActionRunBody run={run} data={data} onClose={onClose} />}
          {!task && !run && (
            <p className="text-xs text-muted-foreground/80">
              This item is no longer in the active queue. It may have been completed or moved.
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <Link
            to="/admin"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            Open in admin
            <ExternalLink className="h-3 w-3" />
          </Link>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function DealTaskBody({
  task,
  data,
  onClose,
}: {
  task: AdminDealTask;
  data: HubData;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runWithAi = useCallback(async () => {
    if (!task.skill) return;
    setBusy(true);
    setError(null);
    try {
      await api.runAdminDealTask({
        dealId: task.dealId,
        skill: task.skill,
        title: task.title,
        sourceTaskId: task.id,
        runNow: true,
      });
      await data.refresh();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [data, onClose, task]);

  return (
    <div className="space-y-3">
      <DetailRow label="Deal" value={task.dealTitle} />
      <DetailRow label="Stage" value={task.stageName} />
      {task.skill && <DetailRow label="Skill" value={task.skill} mono />}
      {task.description && (
        <div>
          <div className="font-mono-ui mb-1 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            Description
          </div>
          <p className="whitespace-pre-wrap text-[0.85rem] text-foreground/90">{task.description}</p>
        </div>
      )}
      <DetailRow label="Status" value={task.status} mono />

      {error && (
        <div className="rounded-md border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
          {error}
        </div>
      )}

      {task.canRunWithAi && task.skill && task.status !== "done" && task.status !== "completed" && (
        <div className="pt-2">
          <Button size="sm" onClick={() => void runWithAi()} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Run with AI
          </Button>
        </div>
      )}
    </div>
  );
}

function ActionRunBody({
  run,
  data,
  onClose,
}: {
  run: AdminActionRun;
  data: HubData;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = useCallback(
    async (approved: boolean) => {
      setBusy(approved ? "approve" : "cancel");
      setError(null);
      try {
        await api.approveAdminActionRun(run.id, { approved, runNow: approved });
        await data.refresh();
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [data, onClose, run.id],
  );

  const canAct =
    run.status === "needs_input" ||
    run.status === "blocked" ||
    run.status === "error" ||
    run.status === "failed";

  return (
    <div className="space-y-3">
      <DetailRow label="Status" value={run.status} mono tone={run.status === "error" || run.status === "failed" ? "danger" : run.status === "needs_input" ? "warn" : "neutral"} />
      {run.registryName && <DetailRow label="Action" value={run.registryName} />}
      {run.skill && <DetailRow label="Skill" value={run.skill} mono />}
      {run.errorMessage && (
        <div>
          <div className="font-mono-ui mb-1 text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
            Error
          </div>
          <p className="whitespace-pre-wrap rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-[0.82rem] text-destructive">
            {run.errorMessage}
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
          {error}
        </div>
      )}

      {canAct && (
        <div className="flex flex-wrap gap-2 pt-2">
          <Button size="sm" onClick={() => void act(true)} disabled={busy !== null}>
            {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Approve &amp; run
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void act(false)}
            disabled={busy !== null}
            className="text-foreground/75 hover:text-foreground"
          >
            {busy === "cancel" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "warn" | "danger" | "neutral";
}) {
  return (
    <div className="flex items-baseline gap-3">
      <div className="font-mono-ui min-w-[5.5rem] text-[0.6rem] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "flex-1 text-[0.85rem] text-foreground/90",
          mono && "font-mono-ui",
          tone === "warn" && "text-warning",
          tone === "danger" && "text-destructive",
        )}
      >
        {value}
      </div>
    </div>
  );
}
