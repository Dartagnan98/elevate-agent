import { useCallback, useEffect, useMemo, useState } from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { Link, useSearchParams } from "react-router-dom";
import { Archive, ArrowRight, CheckCircle2, ExternalLink, LayoutGrid, List, Loader2, MessageSquare, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentHandoff, AgentHubAgent, SurfaceTask, SurfaceTaskAuditEvent, SurfaceTaskStaleReport } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Modal } from "@/components/ui/modal";
import { BoardSkeleton } from "@/components/ui/skeleton";
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
  { key: "cancelled", label: "Cancelled" },
];

const PRIORITY_TONE: Record<string, string> = {
  urgent: "text-destructive",
  high: "text-warning",
  normal: "text-muted-foreground",
  low: "text-muted-foreground/70",
};

type BadgeTone = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";

function statusVariant(status: string): BadgeTone {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
    case "cancelled":
      return "destructive";
    case "running":
    case "in_progress":
      return "secondary";
    case "waiting_human":
    case "blocked":
      return "warning";
    default:
      return "outline";
  }
}

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

function taskBlockers(task: SurfaceTask): string[] {
  return task.blockedBy ?? task.blocked_by ?? [];
}

function taskAssignee(task: SurfaceTask): string {
  return task.assignee || task.assigned_to || "";
}

function taskOutputLabel(output: unknown): string {
  if (typeof output === "string") return output;
  if (output && typeof output === "object") {
    const obj = output as Record<string, unknown>;
    return String(obj.label || obj.value || obj.path || obj.url || obj.type || "output");
  }
  return String(output ?? "output");
}

function taskOutputHref(output: unknown): string | null {
  if (typeof output === "string") return output.startsWith("/") ? output : null;
  if (output && typeof output === "object") {
    const obj = output as Record<string, unknown>;
    const raw = obj.url || obj.value || obj.path;
    const text = typeof raw === "string" ? raw : "";
    return text.startsWith("/") || text.startsWith("http://") || text.startsWith("https://") ? text : null;
  }
  return null;
}

function TaskOutputs({ outputs }: { outputs?: unknown[] | null }) {
  if (!outputs?.length) return null;
  return (
    <ul className="space-y-1 text-xs text-muted-foreground">
      {outputs.map((output, i) => {
        const label = taskOutputLabel(output);
        const href = taskOutputHref(output);
        return (
          <li key={`${label}-${i}`} className="rounded bg-secondary/30 px-2 py-1">
            {href ? (
              <a href={href} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-foreground/85 hover:underline">
                <span className="truncate">{label}</span>
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
            ) : (
              <span className="break-words">{label}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function TaskOutputPreview({ outputs }: { outputs?: unknown[] | null }) {
  if (!outputs?.length) return <span className="text-muted-foreground/60">none</span>;
  return (
    <div className="flex max-w-[220px] flex-wrap gap-1">
      {outputs.slice(0, 2).map((output, i) => {
        const label = taskOutputLabel(output);
        const href = taskOutputHref(output);
        const content = <span className="max-w-[140px] truncate">{label}</span>;
        return href ? (
          <a
            key={`${label}-${i}`}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex max-w-full items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] text-foreground/80 hover:border-foreground/30"
            onClick={(event) => event.stopPropagation()}
          >
            {content}
            <ExternalLink className="h-3 w-3 shrink-0" />
          </a>
        ) : (
          <span key={`${label}-${i}`} className="inline-flex max-w-full rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
            {content}
          </span>
        );
      })}
      {outputs.length > 2 && <span className="text-[11px] text-muted-foreground">+{outputs.length - 2}</span>}
    </div>
  );
}

function TaskDependencyPicker({
  label,
  taskId,
  tasks,
  selected,
  onChange,
}: {
  label: string;
  taskId?: string;
  tasks: SurfaceTask[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const options = tasks.filter((task) => task.id !== taskId);
  const selectedSet = new Set(selected);
  const toggle = (id: string, checked: boolean) => {
    if (checked) onChange(unique([...selected, id]));
    else onChange(selected.filter((value) => value !== id));
  };
  return (
    <Field label={label}>
      <div className="max-h-36 space-y-1 overflow-y-auto rounded-md border border-border bg-background p-2">
        {options.length === 0 ? (
          <p className="px-1 py-2 text-[11px] italic text-muted-foreground/60">no tasks</p>
        ) : (
          options.map((task) => (
            <label key={task.id} className="flex items-start gap-2 rounded px-1 py-1 text-xs text-foreground/90 hover:bg-secondary/30">
              <input
                type="checkbox"
                checked={selectedSet.has(task.id)}
                onChange={(event) => toggle(task.id, event.target.checked)}
                className="mt-0.5 accent-foreground"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{task.title}</span>
                <span className="text-[11px] text-muted-foreground">{task.assignee || "unassigned"} · {task.status}</span>
              </span>
            </label>
          ))
        )}
      </div>
    </Field>
  );
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
  taskMap,
  onClick,
  onDragStart,
  onDragEnd,
  dragging,
}: {
  task: SurfaceTask;
  taskMap: Map<string, SurfaceTask>;
  onClick: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  dragging: boolean;
}) {
  const blockers = taskBlockers(task);
  const unresolved = task.unresolvedDependencyIds ?? [];
  const blocks = task.blocks ?? [];
  return (
    <button
      type="button"
      draggable
      onClick={onClick}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        // Firefox requires data to be set for drag to start.
        e.dataTransfer.setData("text/plain", task.id);
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      className={cn(
        "w-full space-y-1.5 rounded-md border border-border bg-card/60 p-2.5 text-left transition-colors hover:border-foreground/20 cursor-grab active:cursor-grabbing",
        dragging && "opacity-40",
      )}
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
        {task.claimOwner && (
          <Badge variant="outline" className="shrink-0">
            claimed
          </Badge>
        )}
        {task.dueDate && (
          <Badge variant={new Date(task.dueDate).getTime() < Date.now() && task.status !== "completed" ? "warning" : "outline"} className="shrink-0">
            due {timeAgo(task.dueDate) || task.dueDate.slice(0, 10)}
          </Badge>
        )}
        {blockers.length > 0 && (
          <Badge variant={unresolved.length > 0 ? "warning" : "outline"} className="shrink-0">
            {unresolved.length > 0 ? `${unresolved.length} blocked` : `${blockers.length} deps`}
          </Badge>
        )}
        {blocks.length > 0 && (
          <Badge variant="outline" className="shrink-0">
            blocks {blocks.length}
          </Badge>
        )}
        <span className="text-muted-foreground/70">{timeAgo(task.createdAt)}</span>
      </div>
      {unresolved.length > 0 && (
        <p className="truncate text-[11px] text-muted-foreground">
          waiting on {unresolved.map((id) => taskMap.get(id)?.title || id).join(", ")}
        </p>
      )}
    </button>
  );
}

function TaskListView({
  tasks,
  taskMap,
  onTaskClick,
  onMoveTask,
}: {
  tasks: SurfaceTask[];
  taskMap: Map<string, SurfaceTask>;
  onTaskClick: (task: SurfaceTask) => void;
  onMoveTask: (id: string, next: SurfaceTask["status"]) => void;
}) {
  if (tasks.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border/60 p-6 text-center text-xs italic text-muted-foreground/60">
        no tasks match these filters
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card/40">
      <table className="w-full min-w-[920px] text-left text-xs">
        <thead className="border-b border-border bg-secondary/20 text-[11px] uppercase tracking-wide text-muted-foreground/80">
          <tr>
            <th className="px-3 py-2 font-medium">Task</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Priority</th>
            <th className="px-3 py-2 font-medium">Assignee</th>
            <th className="px-3 py-2 font-medium">Project</th>
            <th className="px-3 py-2 font-medium">Due</th>
            <th className="px-3 py-2 font-medium">Outputs</th>
            <th className="px-3 py-2 font-medium">Move</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70">
          {tasks.map((task) => {
            const blockers = taskBlockers(task);
            const unresolved = task.unresolvedDependencyIds ?? [];
            return (
              <tr key={task.id} className="align-top transition-colors hover:bg-secondary/20">
                <td className="max-w-[320px] px-3 py-2">
                  <button
                    type="button"
                    onClick={() => onTaskClick(task)}
                    className="block max-w-full text-left text-xs font-medium leading-5 text-foreground/90 hover:underline"
                  >
                    <span className="line-clamp-2">{task.title}</span>
                  </button>
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                    {task.createdBy && <span>by {task.createdBy}</span>}
                    {task.createdAt && <span>{timeAgo(task.createdAt)}</span>}
                    {task.claimOwner && <Badge variant="outline">claimed</Badge>}
                    {task.needsApproval && <Badge variant="warning">approval</Badge>}
                    {blockers.length > 0 && (
                      <Badge variant={unresolved.length > 0 ? "warning" : "outline"}>
                        {unresolved.length > 0 ? `${unresolved.length} blocked` : `${blockers.length} deps`}
                      </Badge>
                    )}
                    {(task.blocks?.length || 0) > 0 && (
                      <Badge variant="outline">blocks {task.blocks!.length}</Badge>
                    )}
                  </div>
                  {unresolved.length > 0 && (
                    <p className="mt-1 truncate text-[11px] text-muted-foreground">
                      waiting on {unresolved.map((id) => taskMap.get(id)?.title || id).join(", ")}
                    </p>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Badge variant={statusVariant(task.status)}>{task.status.replace("_", " ")}</Badge>
                </td>
                <td className="px-3 py-2">
                  <span className={cn("font-medium", PRIORITY_TONE[task.priority])}>{task.priority}</span>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{taskAssignee(task) || "unassigned"}</td>
                <td className="px-3 py-2 text-muted-foreground">{task.project || "-"}</td>
                <td className="px-3 py-2 text-muted-foreground">
                  {task.dueDate ? timeAgo(task.dueDate) || task.dueDate.slice(0, 10) : "-"}
                </td>
                <td className="px-3 py-2">
                  <TaskOutputPreview outputs={task.outputs} />
                </td>
                <td className="w-36 px-3 py-2">
                  <Select
                    value={task.status}
                    onValueChange={(next) => onMoveTask(task.id, next as SurfaceTask["status"])}
                    buttonClassName="h-8 text-xs"
                  >
                    {COLUMNS.map((column) => (
                      <SelectOption key={column.key} value={column.key}>
                        {column.label}
                      </SelectOption>
                    ))}
                  </Select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CreateTaskForm({
  surfaces,
  tasks,
  onClose,
  onCreated,
}: {
  surfaces: string[];
  tasks: SurfaceTask[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assignee, setAssignee] = useState(surfaces[0] || "human");
  const [priority, setPriority] = useState("normal");
  const [project, setProject] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [needsApproval, setNeedsApproval] = useState(false);
  const [blockedBy, setBlockedBy] = useState<string[]>([]);
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
        due_date: dueDate.trim() || undefined,
        needs_approval: needsApproval,
        blocked_by: blockedBy,
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
      <Field label="Due date (optional)">
        <Input value={dueDate} onChange={(e) => setDueDate(e.target.value)} type="datetime-local" />
      </Field>
      <TaskDependencyPicker
        label="Blocked by"
        tasks={tasks}
        selected={blockedBy}
        onChange={setBlockedBy}
      />
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
  tasks,
  claimAgent,
  onClose,
  onChanged,
}: {
  task: SurfaceTask;
  tasks: SurfaceTask[];
  claimAgent: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<SurfaceTask["status"]>(task.status);
  const [blockedBy, setBlockedBy] = useState<string[]>(taskBlockers(task));
  const [audit, setAudit] = useState<SurfaceTaskAuditEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const taskMap = useMemo(() => new Map(tasks.map((item) => [item.id, item])), [tasks]);

  useEffect(() => {
    let cancelled = false;
    api.getSurfaceTaskAudit(task.id).then((res) => {
      if (!cancelled) setAudit(res.events || []);
    }).catch(() => {
      if (!cancelled) setAudit([]);
    });
    return () => { cancelled = true; };
  }, [task.id]);

  const save = async (next: SurfaceTask["status"]) => {
    setBusy(true);
    setErr(null);
    try {
      await api.updateSurfaceTask(task.id, { status: next });
      setStatus(next);
      onChanged();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const claim = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.claimSurfaceTask(task.id, { agent: claimAgent || task.assignee || "executive-assistant" });
      onChanged();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.deleteSurfaceTask(task.id);
      onChanged();
      onClose();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveDependencies = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.updateSurfaceTask(task.id, { blocked_by: blockedBy });
      onChanged();
    } catch (e) {
      setErr(String(e));
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
        {task.createdBy && <span className="text-muted-foreground">created by {task.createdBy}</span>}
        {task.claimOwner && <Badge variant="outline">claimed by {task.claimOwner}</Badge>}
        {task.dueDate && <Badge variant="outline">due {task.dueDate}</Badge>}
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
      <TaskDependencyPicker
        label="Blocked by"
        taskId={task.id}
        tasks={tasks}
        selected={blockedBy}
        onChange={setBlockedBy}
      />
      {(task.blocks?.length || 0) > 0 && (
        <Field label="Blocks">
          <div className="flex flex-wrap gap-1.5">
            {task.blocks!.map((id) => (
              <Badge key={id} variant="outline">
                {taskMap.get(id)?.title || id}
              </Badge>
            ))}
          </div>
        </Field>
      )}
      {(task.unresolvedDependencies?.length || 0) > 0 && (
        <Field label="Waiting on">
          <div className="flex flex-wrap gap-1.5">
            {task.unresolvedDependencies!.map((dep) => (
              <Badge key={dep.id} variant="warning">
                {dep.title || dep.id} · {dep.status || "open"}
              </Badge>
            ))}
          </div>
        </Field>
      )}
      {(task.outputs?.length || 0) > 0 && (
        <Field label="Outputs">
          <TaskOutputs outputs={task.outputs} />
        </Field>
      )}
      {task.result && (
        <Field label="Result">
          <p className="whitespace-pre-wrap rounded bg-secondary/30 px-2 py-1 text-xs text-muted-foreground">{task.result}</p>
        </Field>
      )}
      {audit.length > 0 && (
        <Field label="Audit">
          <div className="max-h-36 space-y-1 overflow-y-auto rounded-md border border-border bg-background p-2">
            {audit.slice(-12).map((event) => (
              <div key={event.id} className="flex items-start justify-between gap-2 text-[11px] text-muted-foreground">
                <span>
                  <span className="font-medium text-foreground/80">{event.event}</span>
                  {event.actor ? ` · ${event.actor}` : ""}
                  {event.to ? ` · ${event.from || "none"} -> ${event.to}` : ""}
                </span>
                <span className="shrink-0">{timeAgo(event.createdAt || event.ts)}</span>
              </div>
            ))}
          </div>
        </Field>
      )}
      {err && <p className="text-xs text-destructive">{err}</p>}
      <div className="flex items-center justify-between pt-1">
        <Button
          variant="ghost"
          onClick={remove}
          disabled={busy}
          className="text-destructive hover:text-destructive"
        >
          <Trash2 className="h-4 w-4" /> Delete
        </Button>
        <div className="flex gap-2">
          {task.status === "pending" && (
            <Button variant="ghost" onClick={claim} disabled={busy || !!task.claimOwner}>
              <CheckCircle2 className="h-4 w-4" /> Claim
            </Button>
          )}
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <Button onClick={saveDependencies} disabled={busy}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function TasksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const agentParam = searchParams.get("agent") || "";
  const [tasks, setTasks] = useState<SurfaceTask[]>([]);
  const [handoffs, setHandoffs] = useState<AgentHandoff[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<SurfaceTask | null>(null);
  const [surfaces, setSurfaces] = useState<string[]>([]);
  const [agents, setAgents] = useState<AgentHubAgent[]>([]);
  const [agentFilter, setAgentFilter] = useState(agentParam);
  const [view, setView] = useState<"board" | "list">("board");
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<SurfaceTask["status"] | null>(null);
  const [staleReport, setStaleReport] = useState<SurfaceTaskStaleReport | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [t, exp, hub] = await Promise.all([
        api.listSurfaceTasks(),
        api.getHeartbeatExperiments().catch(() => ({ surfaces: [] as { surface: string }[] })),
        api.getAgentHub({ lite: true }).catch(() => ({ agents: [] as AgentHubAgent[] })),
      ]);
      const hs = await api.getAgentHandoffs({ limit: 50 }).catch(() => ({ items: [] as AgentHandoff[] }));
      setTasks(t.tasks || []);
      setHandoffs(hs.items || []);
      setAgents(hub.agents || []);
      setSurfaces(unique([...(hub.agents || []).map((agent) => agent.id), ...(exp.surfaces || []).map((s) => s.surface)]));
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
  useEffect(() => {
    setAgentFilter(agentParam);
  }, [agentParam]);
  useRefreshOnAgentTurn(() => void load(true));

  const updateAgentFilter = (next: string) => {
    setAgentFilter(next);
    const params = new URLSearchParams(searchParams);
    if (next) params.set("agent", next);
    else params.delete("agent");
    setSearchParams(params, { replace: true });
  };

  const moveTask = useCallback(
    async (id: string, next: SurfaceTask["status"]) => {
      const current = tasks.find((t) => t.id === id);
      if (!current || current.status === next) return;
      // Optimistic — move the card immediately, reconcile on reload.
      setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, status: next } : t)));
      try {
        await api.updateSurfaceTask(id, { status: next });
        void load(true);
      } catch (e) {
        // Roll back on failure.
        setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, status: current.status } : t)));
        setError(String(e));
      }
    },
    [tasks, load],
  );

  const taskMap = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks]);
  const projects = useMemo(() => unique(tasks.map((task) => task.project)), [tasks]);
  const visibleTasks = useMemo(
    () => tasks.filter((task) => {
      if (agentFilter && taskAssignee(task) !== agentFilter) return false;
      if (statusFilter && task.status !== statusFilter) return false;
      if (priorityFilter && task.priority !== priorityFilter) return false;
      if (projectFilter && (task.project || "") !== projectFilter) return false;
      return true;
    }),
    [agentFilter, priorityFilter, projectFilter, statusFilter, tasks],
  );
  const boardColumns = useMemo(
    () => (statusFilter ? COLUMNS.filter((column) => column.key === statusFilter) : COLUMNS),
    [statusFilter],
  );

  const byStatus = useMemo(() => {
    const map: Record<string, SurfaceTask[]> = {
      pending: [],
      in_progress: [],
      blocked: [],
      completed: [],
      cancelled: [],
    };
    for (const t of visibleTasks) (map[t.status] || map.pending).push(t);
    return map;
  }, [visibleTasks]);

  const openHandoffs = useMemo(
    () => handoffs
      .filter((h) => !["completed", "failed", "cancelled"].includes(String(h.status)))
      .filter((h) => !agentFilter || h.toAgentId === agentFilter || h.fromAgentId === agentFilter)
      .slice(0, 8),
    [agentFilter, handoffs],
  );

  const checkStale = async () => {
    setActionBusy("stale");
    try {
      const report = await api.checkSurfaceTaskStale();
      setStaleReport(report);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionBusy(null);
    }
  };

  const archiveCompleted = async () => {
    setActionBusy("archive");
    try {
      await api.archiveSurfaceTasks({ older_than_days: 7 });
      await load(true);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionBusy(null);
    }
  };

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
          <Button variant="ghost" onClick={checkStale} disabled={actionBusy === "stale"}>
            {actionBusy === "stale" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Check stale
          </Button>
          <Button variant="ghost" onClick={archiveCompleted} disabled={actionBusy === "archive"}>
            {actionBusy === "archive" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Archive className="h-4 w-4" />
            )}
            Archive
          </Button>
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
            tasks={tasks}
            onClose={() => setShowCreate(false)}
            onCreated={() => load(true)}
          />
        </Modal>
      )}
      {selected && (
        <Modal title="Task" onClose={() => setSelected(null)} wide>
          <TaskDetail
            task={selected}
            tasks={tasks}
            claimAgent={agentFilter || selected.assignee || "executive-assistant"}
            onClose={() => setSelected(null)}
            onChanged={() => load(true)}
          />
        </Modal>
      )}

      <section className="rounded-lg border border-border bg-card/40 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Agent">
            <Select value={agentFilter} onValueChange={updateAgentFilter} className="w-56">
              <SelectOption value="">All agents</SelectOption>
              {agents.map((agent) => (
                <SelectOption key={agent.id} value={agent.id}>
                  {agent.name || agent.id}
                </SelectOption>
              ))}
            </Select>
          </Field>
          <Field label="Status">
            <Select value={statusFilter} onValueChange={setStatusFilter} className="w-44">
              <SelectOption value="">All statuses</SelectOption>
              {COLUMNS.map((column) => (
                <SelectOption key={column.key} value={column.key}>
                  {column.label}
                </SelectOption>
              ))}
            </Select>
          </Field>
          <Field label="Priority">
            <Select value={priorityFilter} onValueChange={setPriorityFilter} className="w-40">
              <SelectOption value="">All priorities</SelectOption>
              <SelectOption value="urgent">urgent</SelectOption>
              <SelectOption value="high">high</SelectOption>
              <SelectOption value="normal">normal</SelectOption>
              <SelectOption value="low">low</SelectOption>
            </Select>
          </Field>
          <Field label="Project">
            <Select value={projectFilter} onValueChange={setProjectFilter} className="w-48" disabled={projects.length === 0}>
              <SelectOption value="">All projects</SelectOption>
              {projects.map((project) => (
                <SelectOption key={project} value={project}>
                  {project}
                </SelectOption>
              ))}
            </Select>
          </Field>
          <div className="flex items-center gap-1 rounded-md border border-border bg-background p-1">
            <Button
              type="button"
              variant={view === "board" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("board")}
              aria-label="Board view"
            >
              <LayoutGrid className="h-4 w-4" />
              Board
            </Button>
            <Button
              type="button"
              variant={view === "list" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("list")}
              aria-label="List view"
            >
              <List className="h-4 w-4" />
              List
            </Button>
          </div>
          {(agentFilter || statusFilter || priorityFilter || projectFilter) && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                updateAgentFilter("");
                setStatusFilter("");
                setPriorityFilter("");
                setProjectFilter("");
              }}
            >
              Clear filters
            </Button>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            Showing {visibleTasks.length} of {tasks.length}
          </span>
        </div>
      </section>

      {staleReport && (
        <section className="grid gap-2 rounded-lg border border-border bg-card/50 p-3 text-xs text-muted-foreground sm:grid-cols-4">
          <span>In progress stale: <b className="text-foreground">{staleReport.counts?.stale_in_progress ?? staleReport.stale_in_progress.length}</b></span>
          <span>Pending stale: <b className="text-foreground">{staleReport.counts?.stale_pending ?? staleReport.stale_pending.length}</b></span>
          <span>Human waiting: <b className="text-foreground">{staleReport.counts?.stale_human ?? staleReport.stale_human.length}</b></span>
          <span>Overdue: <b className="text-foreground">{staleReport.counts?.overdue ?? staleReport.overdue.length}</b></span>
        </section>
      )}

      {loading ? (
        <BoardSkeleton rows={3} />
      ) : error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load tasks: {error}
        </div>
      ) : (
        <>
          <section className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <span className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                <MessageSquare className="h-3.5 w-3.5" />
                Agent handoffs
              </span>
              <Link to="/comms" className="text-[11px] text-muted-foreground hover:text-foreground">
                Open Comms
              </Link>
            </div>
            {openHandoffs.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/60 p-4 text-center text-[11px] italic text-muted-foreground/60">
                no open agent handoffs
              </div>
            ) : (
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                {openHandoffs.map((handoff) => (
                  <Link
                    key={handoff.id}
                    to={`/comms?agent=${encodeURIComponent(handoff.toAgentId)}`}
                    className="space-y-1.5 rounded-md border border-border bg-card/60 p-2.5 transition-colors hover:border-foreground/20"
                  >
                    <p className="line-clamp-2 text-xs font-medium leading-5 text-foreground/90">{handoff.title}</p>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                      <span>{handoff.fromAgentId}</span>
                      <ArrowRight className="h-3 w-3 text-muted-foreground" />
                      <span>{handoff.toAgentId}</span>
                      <Badge variant={statusVariant(String(handoff.status))}>
                        {String(handoff.status).replace("_", " ")}
                      </Badge>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </section>

          {view === "list" ? (
            <TaskListView
              tasks={visibleTasks}
              taskMap={taskMap}
              onTaskClick={setSelected}
              onMoveTask={moveTask}
            />
          ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {boardColumns.map((col) => (
              <div key={col.key} className="space-y-2">
                <div className="flex items-center justify-between px-1">
                  <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                    {col.label}
                  </span>
                  <span className="text-[11px] tabular-nums text-muted-foreground/70">
                    {byStatus[col.key].length}
                  </span>
                </div>
                <div
                  onDragOver={(e) => {
                    if (!draggingId) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                    if (dropTarget !== col.key) setDropTarget(col.key);
                  }}
                  onDragLeave={(e) => {
                    // Only clear when leaving the column entirely, not its children.
                    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                      setDropTarget((prev) => (prev === col.key ? null : prev));
                    }
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    const id = e.dataTransfer.getData("text/plain") || draggingId;
                    setDropTarget(null);
                    setDraggingId(null);
                    if (id) void moveTask(id, col.key);
                  }}
                  className={cn(
                    "space-y-2 rounded-lg border border-dashed border-border/60 p-2 min-h-[80px] transition-colors",
                    dropTarget === col.key && draggingId && "border-foreground/40 bg-foreground/5",
                  )}
                >
                  {byStatus[col.key].length === 0 ? (
                    <p className="px-1 py-3 text-center text-[11px] italic text-muted-foreground/60">
                      {dropTarget === col.key && draggingId ? "drop here" : "nothing here"}
                    </p>
                  ) : (
                    byStatus[col.key].map((t) => (
                      <TaskCard
                        key={t.id}
                        task={t}
                        taskMap={taskMap}
                        onClick={() => setSelected(t)}
                        onDragStart={() => setDraggingId(t.id)}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDropTarget(null);
                        }}
                        dragging={draggingId === t.id}
                      />
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
          )}
        </>
      )}
    </div>
  );
}
