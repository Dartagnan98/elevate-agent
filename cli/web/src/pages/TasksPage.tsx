import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CheckSquare,
  ExternalLink,
  File,
  FileCode,
  FileText,
  ImageIcon,
  LayoutGrid,
  List,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AgentHubAgent, SurfaceTask } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { Select, SelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

type TaskStatus = SurfaceTask["status"];
type TaskPriority = SurfaceTask["priority"];
type ViewMode = "kanban" | "list";
type BadgeTone = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";
type ButtonTone = "default" | "outline" | "destructive" | "secondary";

const BOARD_COLUMNS: { key: Exclude<TaskStatus, "cancelled">; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "in_progress", label: "In Progress" },
  { key: "blocked", label: "Blocked" },
  { key: "completed", label: "Completed (today)" },
];

const STATUS_FILTERS: { key: TaskStatus; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "in_progress", label: "In Progress" },
  { key: "blocked", label: "Blocked" },
  { key: "completed", label: "Completed" },
];

const STATUS_TRANSITIONS: Record<TaskStatus, { label: string; status: TaskStatus; variant: ButtonTone }[]> = {
  pending: [
    { label: "Start", status: "in_progress", variant: "default" },
    { label: "Block", status: "blocked", variant: "destructive" },
  ],
  in_progress: [
    { label: "Complete", status: "completed", variant: "default" },
    { label: "Block", status: "blocked", variant: "destructive" },
    { label: "Back to Pending", status: "pending", variant: "outline" },
  ],
  blocked: [
    { label: "Unblock", status: "in_progress", variant: "default" },
    { label: "Back to Pending", status: "pending", variant: "outline" },
  ],
  completed: [
    { label: "Reopen", status: "pending", variant: "outline" },
  ],
  cancelled: [
    { label: "Reopen", status: "pending", variant: "outline" },
  ],
};

const PRIORITY_ORDER: Record<TaskPriority, number> = {
  urgent: 0,
  high: 1,
  normal: 2,
  low: 3,
};

const STATUS_ORDER: Record<TaskStatus, number> = {
  blocked: 0,
  in_progress: 1,
  pending: 2,
  completed: 3,
  cancelled: 4,
};

function unique(values: Array<string | null | undefined>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const clean = String(value || "").trim();
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out.sort((a, b) => a.localeCompare(b));
}

function taskAssignee(task: SurfaceTask): string {
  return task.assignee || task.assigned_to || "";
}

function taskOrg(task: SurfaceTask): string {
  return task.org || "default";
}

function taskNeedsApproval(task: SurfaceTask): boolean {
  return Boolean(task.needsApproval || task.needs_approval);
}

function createdAt(task: SurfaceTask): string | null | undefined {
  return task.createdAt || task.created_at;
}

function updatedAt(task: SurfaceTask): string | null | undefined {
  return task.updatedAt || task.updated_at;
}

function completedAt(task: SurfaceTask): string | null | undefined {
  return task.completedAt || task.completed_at;
}

function dueDate(task: SurfaceTask): string | null | undefined {
  return task.dueDate || task.due_date;
}

function parseTime(iso?: string | null): number {
  if (!iso) return 0;
  const time = new Date(iso).getTime();
  return Number.isFinite(time) ? time : 0;
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
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

function isCompletedToday(task: SurfaceTask): boolean {
  if (task.status !== "completed") return false;
  const raw = completedAt(task) || updatedAt(task);
  if (!raw) return false;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return (
    date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
  );
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusVariant(status: TaskStatus): BadgeTone {
  switch (status) {
    case "completed":
      return "success";
    case "blocked":
      return "warning";
    case "in_progress":
      return "secondary";
    case "cancelled":
      return "destructive";
    default:
      return "outline";
  }
}

function priorityVariant(priority: TaskPriority): BadgeTone {
  switch (priority) {
    case "urgent":
      return "destructive";
    case "high":
      return "warning";
    case "normal":
      return "secondary";
    default:
      return "outline";
  }
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
  if (typeof output === "string") {
    return output.startsWith("/") || output.startsWith("http://") || output.startsWith("https://") ? output : null;
  }
  if (output && typeof output === "object") {
    const obj = output as Record<string, unknown>;
    const raw = obj.url || obj.value || obj.path;
    const text = typeof raw === "string" ? raw : "";
    return text.startsWith("/") || text.startsWith("http://") || text.startsWith("https://") ? text : null;
  }
  return null;
}

function outputIcon(output: unknown) {
  const label = taskOutputLabel(output).toLowerCase();
  const ext = label.split(".").pop() || "";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return ImageIcon;
  if (ext === "md" || ext === "txt" || ext === "doc" || ext === "docx" || ext === "pdf") return FileText;
  if (["ts", "tsx", "js", "jsx", "json", "html", "css", "sh", "py"].includes(ext)) return FileCode;
  return File;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label className="text-xs font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: TaskStatus }) {
  return <Badge variant={statusVariant(status)}>{statusLabel(status)}</Badge>;
}

function PriorityBadge({ priority }: { priority: TaskPriority }) {
  return <Badge variant={priorityVariant(priority)}>{statusLabel(priority)}</Badge>;
}

function OrgBadge({ org }: { org?: string | null }) {
  return <Badge variant="outline">{org || "default"}</Badge>;
}

function TaskCard({ task, onClick }: { task: SurfaceTask; onClick: (task: SurfaceTask) => void }) {
  const assignee = taskAssignee(task);
  return (
    <button
      type="button"
      onClick={() => onClick(task)}
      className="w-full cursor-pointer rounded-md border border-border bg-card p-3 text-left transition-colors hover:bg-secondary/30"
    >
      <div className="space-y-2">
        <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
          {task.title}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <PriorityBadge priority={task.priority} />
          <OrgBadge org={task.org} />
        </div>
        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          {assignee ? (
            <span className="max-w-[140px] truncate">{assignee}</span>
          ) : (
            <span className="italic">Unassigned</span>
          )}
          <span className="shrink-0">{timeAgo(createdAt(task))}</span>
        </div>
      </div>
    </button>
  );
}

function KanbanBoard({
  tasks,
  completedTodayTasks,
  onTaskClick,
}: {
  tasks: SurfaceTask[];
  completedTodayTasks: SurfaceTask[];
  onTaskClick: (task: SurfaceTask) => void;
}) {
  const columns = BOARD_COLUMNS.map((column) => ({
    ...column,
    tasks: column.key === "completed"
      ? completedTodayTasks
      : tasks.filter((task) => task.status === column.key),
  }));

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
      {columns.map((column) => (
        <div key={column.key} className="flex flex-col gap-2">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <StatusBadge status={column.key} />
              <span className="text-xs text-muted-foreground">{column.tasks.length}</span>
            </div>
          </div>
          <div className="h-[calc(100vh-280px)] min-h-[300px] overflow-y-auto pr-1">
            <div className="flex flex-col gap-2 px-0.5 pb-1 pt-0.5">
              {column.tasks.length === 0 ? (
                <p className="px-2 py-8 text-center text-xs text-muted-foreground">
                  No tasks
                </p>
              ) : (
                column.tasks.map((task) => (
                  <TaskCard key={task.id} task={task} onClick={onTaskClick} />
                ))
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

type SortField = "title" | "status" | "priority" | "assignee" | "org" | "created_at";
type SortDir = "asc" | "desc";

function TaskListTable({ tasks, onTaskClick }: { tasks: SurfaceTask[]; onTaskClick: (task: SurfaceTask) => void }) {
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const copy = [...tasks];
    copy.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "title":
          cmp = a.title.localeCompare(b.title);
          break;
        case "status":
          cmp = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
          break;
        case "priority":
          cmp = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
          break;
        case "assignee":
          cmp = taskAssignee(a).localeCompare(taskAssignee(b));
          break;
        case "org":
          cmp = taskOrg(a).localeCompare(taskOrg(b));
          break;
        case "created_at":
          cmp = parseTime(createdAt(a)) - parseTime(createdAt(b));
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [tasks, sortDir, sortField]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/50" />;
    return sortDir === "asc" ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />;
  };

  const columns: { field: SortField; label: string }[] = [
    { field: "title", label: "Title" },
    { field: "status", label: "Status" },
    { field: "priority", label: "Priority" },
    { field: "assignee", label: "Assignee" },
    { field: "org", label: "Org" },
    { field: "created_at", label: "Created" },
  ];

  return (
    <div className="overflow-x-auto rounded-md border border-border bg-card/40">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-border text-xs text-muted-foreground">
          <tr>
            {columns.map((column) => (
              <th key={column.field} className="px-3 py-2 font-medium">
                <button
                  type="button"
                  onClick={() => toggleSort(column.field)}
                  className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
                >
                  {column.label}
                  <SortIcon field={column.field} />
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70">
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                No tasks found
              </td>
            </tr>
          ) : (
            sorted.map((task) => (
              <tr
                key={task.id}
                onClick={() => onTaskClick(task)}
                className="cursor-pointer transition-colors hover:bg-secondary/20"
              >
                <td className="max-w-[320px] truncate px-3 py-2 font-medium">{task.title}</td>
                <td className="px-3 py-2"><StatusBadge status={task.status} /></td>
                <td className="px-3 py-2"><PriorityBadge priority={task.priority} /></td>
                <td className="px-3 py-2 text-muted-foreground">{taskAssignee(task) || "-"}</td>
                <td className="px-3 py-2"><OrgBadge org={task.org} /></td>
                <td className="px-3 py-2 text-muted-foreground">{timeAgo(createdAt(task)) || "-"}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function TaskFilters({
  orgs,
  agents,
  projects,
  filters,
  onChange,
  onClearAll,
}: {
  orgs: string[];
  agents: string[];
  projects: string[];
  filters: { org: string; agent: string; priority: string; project: string; status: string };
  onChange: (key: keyof TaskFiltersProps, value: string) => void;
  onClearAll: () => void;
}) {
  const active = filters.org !== "all"
    || filters.agent !== "all"
    || filters.priority !== "all"
    || filters.project !== "all"
    || filters.status !== "all";

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-card/40 p-3">
      <Field label="Org">
        <Select value={filters.org} onValueChange={(value) => onChange("org", value)} className="w-40">
          <SelectOption value="all">All Orgs</SelectOption>
          {orgs.map((org) => (
            <SelectOption key={org} value={org}>{org}</SelectOption>
          ))}
        </Select>
      </Field>
      <Field label="Agent">
        <Select value={filters.agent} onValueChange={(value) => onChange("agent", value)} className="w-48">
          <SelectOption value="all">All Agents</SelectOption>
          {agents.map((agent) => (
            <SelectOption key={agent} value={agent}>{agent}</SelectOption>
          ))}
        </Select>
      </Field>
      <Field label="Priority">
        <Select value={filters.priority} onValueChange={(value) => onChange("priority", value)} className="w-40">
          <SelectOption value="all">All Priorities</SelectOption>
          <SelectOption value="urgent">Urgent</SelectOption>
          <SelectOption value="high">High</SelectOption>
          <SelectOption value="normal">Normal</SelectOption>
          <SelectOption value="low">Low</SelectOption>
        </Select>
      </Field>
      <Field label="Status">
        <Select value={filters.status} onValueChange={(value) => onChange("status", value)} className="w-40">
          <SelectOption value="all">All Statuses</SelectOption>
          {STATUS_FILTERS.map((status) => (
            <SelectOption key={status.key} value={status.key}>{status.label}</SelectOption>
          ))}
        </Select>
      </Field>
      {projects.length > 0 && (
        <Field label="Project">
          <Select value={filters.project} onValueChange={(value) => onChange("project", value)} className="w-48">
            <SelectOption value="all">All Projects</SelectOption>
            {projects.map((project) => (
              <SelectOption key={project} value={project}>{project}</SelectOption>
            ))}
          </Select>
        </Field>
      )}
      {active && (
        <Button type="button" variant="ghost" size="sm" onClick={onClearAll}>
          Clear all
        </Button>
      )}
    </div>
  );
}

type TaskFiltersProps = {
  org: string;
  agent: string;
  priority: string;
  project: string;
  status: string;
};

function CreateTaskForm({
  agents,
  projects,
  onClose,
  onCreated,
}: {
  agents: string[];
  projects: string[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assignee, setAssignee] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [project, setProject] = useState("");
  const [needsApproval, setNeedsApproval] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setTitle("");
    setDescription("");
    setAssignee("");
    setPriority("normal");
    setProject("");
    setNeedsApproval(false);
  };

  const submit = async () => {
    if (!title.trim()) {
      setError("Title is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.createSurfaceTask({
        title: title.trim(),
        description: description.trim() || undefined,
        assignee: assignee || undefined,
        priority,
        project: project || undefined,
        needs_approval: needsApproval,
      });
      reset();
      onCreated();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-4 py-1">
      {error && (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
      <Field label="Title">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={500}
          placeholder="Task title..."
          autoFocus
        />
      </Field>
      <Field label="Description">
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={2000}
          rows={4}
          placeholder="Optional description..."
          className="w-full rounded-sm border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-ring/70"
        />
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Assignee">
          <Select value={assignee} onValueChange={setAssignee}>
            <SelectOption value="">Unassigned</SelectOption>
            {agents.map((agent) => (
              <SelectOption key={agent} value={agent}>{agent}</SelectOption>
            ))}
          </Select>
        </Field>
        <Field label="Priority">
          <Select value={priority} onValueChange={(value) => setPriority(value as TaskPriority)}>
            <SelectOption value="urgent">Urgent</SelectOption>
            <SelectOption value="high">High</SelectOption>
            <SelectOption value="normal">Normal</SelectOption>
            <SelectOption value="low">Low</SelectOption>
          </Select>
        </Field>
      </div>
      {projects.length > 0 && (
        <Field label="Project">
          <Select value={project} onValueChange={setProject}>
            <SelectOption value="">None</SelectOption>
            {projects.map((item) => (
              <SelectOption key={item} value={item}>{item}</SelectOption>
            ))}
          </Select>
        </Field>
      )}
      <div className="flex items-center gap-3">
        <Switch checked={needsApproval} onCheckedChange={setNeedsApproval} />
        <Label className="cursor-pointer text-sm text-foreground">Needs approval before execution</Label>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button type="button" onClick={submit} disabled={!title.trim() || submitting}>
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Create Task
        </Button>
      </div>
    </div>
  );
}

function OutputList({ outputs }: { outputs?: unknown[] | null }) {
  if (!outputs?.length) return null;
  return (
    <div className="space-y-1">
      {outputs.map((output, index) => {
        const Icon = outputIcon(output);
        const label = taskOutputLabel(output);
        const href = taskOutputHref(output);
        const content = (
          <>
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <p className="break-words text-sm font-medium text-foreground">{label}</p>
              {href && <p className="break-all text-xs text-muted-foreground">{href}</p>}
            </div>
            {href && <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
          </>
        );
        return href ? (
          <a
            key={`${label}-${index}`}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="flex items-start gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-secondary/30"
          >
            {content}
          </a>
        ) : (
          <div key={`${label}-${index}`} className="flex items-start gap-2 rounded-md px-2 py-1.5">
            {content}
          </div>
        );
      })}
    </div>
  );
}

function TaskDetailSheet({
  task,
  open,
  agents,
  onOpenChange,
  onStatusChange,
  onDelete,
  onEdit,
}: {
  task: SurfaceTask | null;
  open: boolean;
  agents: string[];
  onOpenChange: (open: boolean) => void;
  onStatusChange: (taskId: string, status: TaskStatus, note?: string) => Promise<void>;
  onDelete: (taskId: string) => Promise<void>;
  onEdit: (task: SurfaceTask) => void;
}) {
  const [note, setNote] = useState("");
  const [updating, setUpdating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editPriority, setEditPriority] = useState<TaskPriority>("normal");
  const [editAssignee, setEditAssignee] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onOpenChange, open]);

  useEffect(() => {
    if (!open || !task) {
      setEditing(false);
      setConfirmDelete(false);
      setError(null);
      setNote("");
      return;
    }
    setError(null);
    setConfirmDelete(false);
  }, [open, task?.id, task]);

  if (!open || !task) return null;

  const transitions = STATUS_TRANSITIONS[task.status] ?? [];
  const assignee = taskAssignee(task);
  const agentChoices = unique([...agents, assignee]);

  const startEditing = () => {
    setEditTitle(task.title);
    setEditDesc(task.description || "");
    setEditPriority(task.priority);
    setEditAssignee(assignee);
    setEditing(true);
    setError(null);
  };

  const saveEdit = async () => {
    if (!editTitle.trim()) {
      setError("Title is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await api.updateSurfaceTask(task.id, {
        title: editTitle.trim(),
        description: editDesc.trim() || undefined,
        priority: editPriority,
        assignee: editAssignee || undefined,
      });
      setEditing(false);
      onEdit(result.task);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleStatusChange = async (nextStatus: TaskStatus) => {
    setUpdating(true);
    setError(null);
    try {
      await onStatusChange(task.id, nextStatus, note.trim() || undefined);
      setNote("");
    } catch (e) {
      setError(String(e));
    } finally {
      setUpdating(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setError(null);
    try {
      await onDelete(task.id);
    } catch (e) {
      setError(String(e));
      setDeleting(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 p-4 backdrop-blur-sm"
      onMouseDown={() => onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Task details"
        className="relative flex max-h-[88vh] min-h-0 w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-border bg-card shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="border-b border-border px-4 py-4">
          <div className="flex items-start gap-2 pr-8">
            {editing ? (
              <Input
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
                className="text-lg font-semibold"
                placeholder="Task title..."
              />
            ) : (
              <>
                <h2 className="flex-1 text-lg font-semibold leading-snug text-foreground">{task.title}</h2>
                <Button type="button" variant="ghost" size="icon" onClick={startEditing} aria-label="Edit task">
                  <Pencil className="h-4 w-4" />
                </Button>
              </>
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => onOpenChange(false)}
              aria-label="Close task"
              className="absolute right-3 top-3"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Task ID: {task.id}</p>
        </div>

        {error && (
          <div className="mx-4 mt-4 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={task.status} />
            {editing ? (
              <Select value={editPriority} onValueChange={(value) => setEditPriority(value as TaskPriority)} className="w-32">
                <SelectOption value="urgent">Urgent</SelectOption>
                <SelectOption value="high">High</SelectOption>
                <SelectOption value="normal">Normal</SelectOption>
                <SelectOption value="low">Low</SelectOption>
              </Select>
            ) : (
              <PriorityBadge priority={task.priority} />
            )}
            <OrgBadge org={task.org} />
            {taskNeedsApproval(task) && <Badge variant="warning">Needs Approval</Badge>}
          </div>

          <div className="border-t border-border" />

          <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <div>
              <span className="text-muted-foreground">Assignee</span>
              {editing ? (
                <Select value={editAssignee} onValueChange={setEditAssignee} className="mt-1">
                  <SelectOption value="">Unassigned</SelectOption>
                  {agentChoices.map((agent) => (
                    <SelectOption key={agent} value={agent}>{agent}</SelectOption>
                  ))}
                </Select>
              ) : (
                <p className="font-medium text-foreground">{assignee || "Unassigned"}</p>
              )}
            </div>
            <div>
              <span className="text-muted-foreground">Project</span>
              <p className="font-medium text-foreground">{task.project || "-"}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Created</span>
              <p className="font-medium text-foreground">{formatDateTime(createdAt(task))}</p>
            </div>
            {updatedAt(task) && (
              <div>
                <span className="text-muted-foreground">Updated</span>
                <p className="font-medium text-foreground">{formatDateTime(updatedAt(task))}</p>
              </div>
            )}
            {completedAt(task) && (
              <div>
                <span className="text-muted-foreground">Completed</span>
                <p className="font-medium text-foreground">{formatDateTime(completedAt(task))}</p>
              </div>
            )}
            {dueDate(task) && (
              <div>
                <span className="text-muted-foreground">Due</span>
                <p className="font-medium text-foreground">{formatDateTime(dueDate(task))}</p>
              </div>
            )}
          </div>

          <div className="border-t border-border" />

          {editing ? (
            <Field label="Description">
              <textarea
                value={editDesc}
                onChange={(event) => setEditDesc(event.target.value)}
                rows={4}
                placeholder="Task description..."
                className="w-full rounded-sm border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-ring/70"
              />
            </Field>
          ) : task.description ? (
            <div>
              <p className="mb-1 text-sm text-muted-foreground">Description</p>
              <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{task.description}</p>
            </div>
          ) : null}

          {editing && (
            <div className="flex gap-2">
              <Button type="button" size="sm" onClick={saveEdit} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Save Changes
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                Cancel
              </Button>
            </div>
          )}

          {!editing && task.notes && (
            <>
              <div className="border-t border-border" />
              <div>
                <p className="mb-1 text-sm text-muted-foreground">Notes</p>
                <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{task.notes}</p>
              </div>
            </>
          )}

          {!editing && (task.outputs?.length || 0) > 0 && (
            <>
              <div className="border-t border-border" />
              <div>
                <p className="mb-2 text-sm text-muted-foreground">Deliverables ({task.outputs?.length || 0})</p>
                <OutputList outputs={task.outputs} />
              </div>
            </>
          )}

          {!editing && task.result && (
            <>
              <div className="border-t border-border" />
              <div>
                <p className="mb-1 text-sm text-muted-foreground">Result</p>
                <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{task.result}</p>
              </div>
            </>
          )}

          {!editing && (
            <>
              <div className="border-t border-border" />
              <Field label="Add note (optional)">
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  maxLength={2000}
                  rows={4}
                  placeholder="Note for status change..."
                  className="w-full rounded-sm border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-ring/70"
                />
              </Field>
            </>
          )}
        </div>

        {!editing && (
          <div className="border-t border-border px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              {transitions.map((transition) => (
                <Button
                  key={`${transition.status}-${transition.label}`}
                  type="button"
                  size="sm"
                  variant={transition.variant}
                  disabled={updating || deleting}
                  onClick={() => handleStatusChange(transition.status)}
                >
                  {updating ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {transition.label}
                </Button>
              ))}
              <div className="ml-auto">
                {confirmDelete ? (
                  <div className="flex items-center gap-1">
                    <span className="mr-1 text-xs text-destructive">Delete?</span>
                    <Button type="button" variant="destructive" size="sm" disabled={deleting} onClick={handleDelete}>
                      {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      Yes
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => setConfirmDelete(false)} disabled={deleting}>
                      No
                    </Button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => setConfirmDelete(true)}
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

const DEFAULT_FILTERS: TaskFiltersProps = {
  org: "all",
  agent: "all",
  priority: "all",
  project: "all",
  status: "all",
};

export default function TasksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const agentParam = searchParams.get("agent") || "";
  const [view, setView] = useState<ViewMode>("kanban");
  const [tasks, setTasks] = useState<SurfaceTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<TaskFiltersProps>({
    ...DEFAULT_FILTERS,
    agent: agentParam || "all",
  });
  const [selectedTask, setSelectedTask] = useState<SurfaceTask | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [agents, setAgents] = useState<string[]>([]);

  const fetchTasks = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    try {
      const [taskRes, hubRes, experimentsRes] = await Promise.all([
        api.listSurfaceTasks(),
        api.getAgentHub({ lite: true }).catch(() => ({ agents: [] as AgentHubAgent[] })),
        api.getHeartbeatExperiments().catch(() => ({ surfaces: [] as { surface: string }[] })),
      ]);
      const hubAgents = (hubRes.agents || []).map((agent) => agent.id);
      const heartbeatAgents = (experimentsRes.surfaces || []).map((surface) => surface.surface);
      setTasks(taskRes.tasks || []);
      setAgents(unique([...hubAgents, ...heartbeatAgents, ...(taskRes.tasks || []).map((task) => taskAssignee(task))]));
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void fetchTasks(false);
  }, [fetchTasks]);

  useEffect(() => {
    const id = window.setInterval(() => void fetchTasks(true), 30000);
    return () => window.clearInterval(id);
  }, [fetchTasks]);

  useEffect(() => {
    setFilters((previous) => ({
      ...previous,
      agent: agentParam || "all",
    }));
  }, [agentParam]);

  const orgs = useMemo(() => unique(tasks.map((task) => task.org)), [tasks]);
  const projects = useMemo(() => unique(tasks.map((task) => task.project)), [tasks]);

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (filters.org !== "all" && taskOrg(task) !== filters.org) return false;
      if (filters.agent !== "all" && taskAssignee(task) !== filters.agent) return false;
      if (filters.priority !== "all" && task.priority !== filters.priority) return false;
      if (filters.status !== "all" && task.status !== filters.status) return false;
      if (filters.project !== "all" && (task.project || "") !== filters.project) return false;
      return true;
    });
  }, [filters, tasks]);

  const displayTasks = view === "kanban"
    ? filteredTasks.filter((task) => task.status !== "completed" && task.status !== "cancelled")
    : filteredTasks;

  const completedToday = useMemo(
    () => filteredTasks.filter(isCompletedToday),
    [filteredTasks],
  );

  const updateFilter = (key: keyof TaskFiltersProps, value: string) => {
    setFilters((previous) => ({ ...previous, [key]: value }));
    if (key === "agent") {
      const params = new URLSearchParams(searchParams);
      if (value && value !== "all") params.set("agent", value);
      else params.delete("agent");
      setSearchParams(params, { replace: true });
    }
  };

  const clearFilters = () => {
    setFilters(DEFAULT_FILTERS);
    const params = new URLSearchParams(searchParams);
    params.delete("agent");
    setSearchParams(params, { replace: true });
  };

  const openTask = (task: SurfaceTask) => {
    setSelectedTask(task);
    setSheetOpen(true);
  };

  const handleStatusChange = async (taskId: string, status: TaskStatus, note?: string) => {
    await api.updateSurfaceTask(taskId, { status, notes: note });
    setSheetOpen(false);
    setSelectedTask(null);
    await fetchTasks(true);
  };

  const handleDelete = async (taskId: string) => {
    await api.deleteSurfaceTask(taskId);
    setSheetOpen(false);
    setSelectedTask(null);
    await fetchTasks(true);
  };

  const handleEdit = (task: SurfaceTask) => {
    setSelectedTask(task);
    void fetchTasks(true);
  };

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-6xl space-y-6 pb-16">
        <h1 className="text-2xl font-semibold text-foreground">Tasks</h1>
        <div className="space-y-4">
          <div className="h-10 w-full animate-pulse rounded-md bg-secondary/30" />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-64 animate-pulse rounded-md bg-secondary/30" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 pb-16">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-semibold text-foreground">Tasks</h1>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-md border border-border bg-card/40 p-0.5">
            <Button
              type="button"
              variant={view === "kanban" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("kanban")}
            >
              <LayoutGrid className="h-4 w-4" />
              Board
            </Button>
            <Button
              type="button"
              variant={view === "list" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setView("list")}
            >
              <List className="h-4 w-4" />
              List
            </Button>
          </div>
          <Button type="button" size="sm" onClick={() => setShowCreate(true)} disabled={refreshing}>
            <Plus className="h-4 w-4" />
            New Task
          </Button>
        </div>
      </div>

      {showCreate && (
        <Modal title="Create Task" onClose={() => setShowCreate(false)}>
          <CreateTaskForm
            agents={agents}
            projects={projects}
            onClose={() => setShowCreate(false)}
            onCreated={() => void fetchTasks(true)}
          />
        </Modal>
      )}

      <TaskFilters
        orgs={orgs}
        agents={agents}
        projects={projects}
        filters={filters}
        onChange={updateFilter}
        onClearAll={clearFilters}
      />

      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          Could not load tasks: {error}
        </div>
      )}

      {tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border py-16 text-center">
          <CheckSquare className="mb-4 h-12 w-12 text-muted-foreground/30" />
          <h3 className="mb-1 text-lg font-medium text-foreground">No tasks yet</h3>
          <p className="mb-4 max-w-sm text-sm text-muted-foreground">
            Create your first task to start tracking work across your agents.
          </p>
          <Button type="button" size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4" />
            New Task
          </Button>
        </div>
      ) : view === "kanban" ? (
        <KanbanBoard
          tasks={displayTasks}
          completedTodayTasks={completedToday}
          onTaskClick={openTask}
        />
      ) : (
        <TaskListTable tasks={displayTasks} onTaskClick={openTask} />
      )}

      <TaskDetailSheet
        task={selectedTask}
        open={sheetOpen}
        agents={agents}
        onOpenChange={(open) => {
          setSheetOpen(open);
          if (!open) setSelectedTask(null);
        }}
        onStatusChange={handleStatusChange}
        onDelete={handleDelete}
        onEdit={handleEdit}
      />
    </div>
  );
}
