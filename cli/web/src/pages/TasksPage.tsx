import { useCallback, useEffect, useMemo, useState } from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { SurfaceTask } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Tasks = dispatch work to a surface (or a human). A pending task     */
/*  assigned to a surface is drained by that surface's next heartbeat   */
/*  WORK run (drafts-only). Click-to-open kanban; mirrors CTRL Flow.    */
/* ------------------------------------------------------------------ */

const COLUMNS: { key: SurfaceTask["status"]; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "in_progress", label: "In Progress" },
  { key: "blocked", label: "Blocked" },
  { key: "completed", label: "Completed" },
];

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

function TaskCard({
  task,
  onClick,
}: {
  task: SurfaceTask;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full space-y-1.5 rounded-md border border-border bg-card/60 p-2.5 text-left transition-colors hover:border-foreground/20"
    >
      <p className="text-xs font-medium leading-5 text-foreground/90">{task.title}</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        <span className={cn("font-medium", PRIORITY_TONE[task.priority])}>{task.priority}</span>
        {task.assignee && (
          <Badge variant="secondary" className="shrink-0">
            {task.assignee}
          </Badge>
        )}
        {task.needsApproval && (
          <Badge variant="warning" className="shrink-0">
            approval
          </Badge>
        )}
        {(task.outputs?.length || 0) > 0 && (
          <span className="text-muted-foreground">{task.outputs!.length} out</span>
        )}
        <span className="text-muted-foreground/70">{timeAgo(task.createdAt)}</span>
      </div>
    </button>
  );
}

function CreateTaskForm({
  surfaces,
  onClose,
  onCreated,
}: {
  surfaces: string[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assignee, setAssignee] = useState(surfaces[0] || "human");
  const [priority, setPriority] = useState("normal");
  const [project, setProject] = useState("");
  const [needsApproval, setNeedsApproval] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await api.createSurfaceTask({
        title: title.trim(),
        description: description.trim() || undefined,
        assignee,
        priority,
        project: project.trim() || undefined,
        needs_approval: needsApproval,
      });
      onCreated();
      onClose();
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <Field label="Title">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus placeholder="Draft follow-ups for cold leads" />
      </Field>
      <Field label="Description">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="What needs doing. The surface drains this on its next run (drafts only)."
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-foreground/30"
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Assignee">
          <Select value={assignee} onValueChange={setAssignee}>
            {surfaces.map((s) => (
              <SelectOption key={s} value={s}>
                {s}
              </SelectOption>
            ))}
            <SelectOption value="human">human (you)</SelectOption>
          </Select>
        </Field>
        <Field label="Priority">
          <Select value={priority} onValueChange={setPriority}>
            <SelectOption value="urgent">urgent</SelectOption>
            <SelectOption value="high">high</SelectOption>
            <SelectOption value="normal">normal</SelectOption>
            <SelectOption value="low">low</SelectOption>
          </Select>
        </Field>
      </div>
      <Field label="Project (optional)">
        <Input value={project} onChange={(e) => setProject(e.target.value)} placeholder="Q3 listings" />
      </Field>
      <label className="flex items-center gap-2 text-xs text-foreground/90">
        <input
          type="checkbox"
          checked={needsApproval}
          onChange={(e) => setNeedsApproval(e.target.checked)}
          className="accent-foreground"
        />
        Needs approval before the surface acts
      </label>
      {err && <p className="text-xs text-destructive">{err}</p>}
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={!title.trim() || busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Create task
        </Button>
      </div>
    </div>
  );
}

function TaskDetail({
  task,
  onClose,
  onChanged,
}: {
  task: SurfaceTask;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<SurfaceTask["status"]>(task.status);

  const save = async (next: SurfaceTask["status"]) => {
    setBusy(true);
    try {
      await api.updateSurfaceTask(task.id, { status: next });
      setStatus(next);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteSurfaceTask(task.id);
      onChanged();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-foreground">{task.title}</p>
      {task.description && (
        <p className="whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
          {task.description}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <Badge variant="secondary">{task.assignee || "unassigned"}</Badge>
        <span className={cn("font-medium", PRIORITY_TONE[task.priority])}>{task.priority}</span>
        {task.project && <span className="text-muted-foreground">· {task.project}</span>}
        {task.needsApproval && <Badge variant="warning">approval</Badge>}
      </div>
      <Field label="Status">
        <Select value={status} onValueChange={(v) => save(v as SurfaceTask["status"])}>
          {COLUMNS.map((c) => (
            <SelectOption key={c.key} value={c.key}>
              {c.label}
            </SelectOption>
          ))}
        </Select>
      </Field>
      {(task.outputs?.length || 0) > 0 && (
        <Field label="Outputs">
          <ul className="space-y-1 text-xs text-muted-foreground">
            {task.outputs!.map((o, i) => (
              <li key={i} className="rounded bg-secondary/30 px-2 py-1">
                {typeof o === "string" ? o : JSON.stringify(o)}
              </li>
            ))}
          </ul>
        </Field>
      )}
      <div className="flex items-center justify-between pt-1">
        <Button
          variant="ghost"
          onClick={remove}
          disabled={busy}
          className="text-destructive hover:text-destructive"
        >
          <Trash2 className="h-4 w-4" /> Delete
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Close
        </Button>
      </div>
    </div>
  );
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<SurfaceTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<SurfaceTask | null>(null);
  const [surfaces, setSurfaces] = useState<string[]>([]);

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [t, exp] = await Promise.all([
        api.listSurfaceTasks(),
        api.getHeartbeatExperiments().catch(() => ({ surfaces: [] as { surface: string }[] })),
      ]);
      setTasks(t.tasks || []);
      setSurfaces((exp.surfaces || []).map((s) => s.surface));
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
    const id = window.setInterval(() => load(true), 30000);
    return () => window.clearInterval(id);
  }, [load]);
  useRefreshOnAgentTurn(() => void load(true));

  const byStatus = useMemo(() => {
    const map: Record<string, SurfaceTask[]> = {
      pending: [],
      in_progress: [],
      blocked: [],
      completed: [],
    };
    for (const t of tasks) (map[t.status] || map.pending).push(t);
    return map;
  }, [tasks]);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold text-foreground">Tasks</h1>
          <p className="text-sm text-muted-foreground">
            Dispatch work to a surface — drained on its next heartbeat (drafts only).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Refresh
          </Button>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4" /> New task
          </Button>
        </div>
      </header>

      {showCreate && (
        <Modal title="New task" onClose={() => setShowCreate(false)}>
          <CreateTaskForm
            surfaces={surfaces}
            onClose={() => setShowCreate(false)}
            onCreated={() => load(true)}
          />
        </Modal>
      )}
      {selected && (
        <Modal title="Task" onClose={() => setSelected(null)} wide>
          <TaskDetail
            task={selected}
            onClose={() => setSelected(null)}
            onChanged={() => load(true)}
          />
        </Modal>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load tasks: {error}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {COLUMNS.map((col) => (
            <div key={col.key} className="space-y-2">
              <div className="flex items-center justify-between px-1">
                <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                  {col.label}
                </span>
                <span className="text-[11px] tabular-nums text-muted-foreground/70">
                  {byStatus[col.key].length}
                </span>
              </div>
              <div className="space-y-2 rounded-lg border border-dashed border-border/60 p-2 min-h-[80px]">
                {byStatus[col.key].length === 0 ? (
                  <p className="px-1 py-3 text-center text-[11px] italic text-muted-foreground/60">
                    nothing here
                  </p>
                ) : (
                  byStatus[col.key].map((t) => (
                    <TaskCard key={t.id} task={t} onClick={() => setSelected(t)} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
