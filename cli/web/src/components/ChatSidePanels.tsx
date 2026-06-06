import {
  AlertCircle,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  CircleDot,
  File as FileIcon,
  FileCode,
  FileStack,
  FileText,
  Folder,
  Image as ImageIcon,
  ListChecks,
  Loader2,
  PanelRight,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { SessionFileItem, TodoItem, TodoStatus } from "@/lib/api-types";
import { Markdown } from "@/components/Markdown";
import { cn } from "@/lib/utils";

export type SidePanelMode = "none" | "preview" | "artifacts" | "plan" | "tasks" | "files";

// ---------------------------------------------------------------------------
// Shared shell — mirrors ArtifactPreviewPane so every side panel reads the
// same: rounded-xl card, chat tokens, icon-badge header, soft-surface body.
// ---------------------------------------------------------------------------

function PanelShell({
  icon,
  title,
  subtitle,
  actions,
  onClose,
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="@container flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--chat-border)] bg-[var(--chat-surface)] text-[var(--chat-text)] shadow-[0_24px_60px_-20px_rgba(0,0,0,0.7),0_1px_0_rgba(255,255,255,0.04)_inset]">
      <header className="flex shrink-0 items-start gap-2 px-3 pb-3 pt-3 @[28rem]:gap-3 @[28rem]:px-4 @[28rem]:pt-4">
        <div className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-[8px] border border-[var(--chat-border)] bg-[var(--chat-surface-soft)] text-[var(--chat-accent)] @[24rem]:flex">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[0.95rem] font-semibold leading-5">{title}</h2>
          {subtitle ? (
            <p className="mt-1 truncate text-[0.72rem] leading-4 text-[var(--chat-muted)]">
              {subtitle}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          <Button
            aria-label="Close panel"
            className="h-7 w-7 rounded-[7px] p-0 @[24rem]:h-8 @[24rem]:w-8"
            onClick={onClose}
            size="sm"
            type="button"
            variant="ghost"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto border-t border-[var(--chat-border)] bg-[var(--chat-surface-soft)]">
        {children}
      </div>
    </div>
  );
}

function PanelEmpty({
  icon,
  title,
  body,
}: {
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="max-w-xs text-center">
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-[8px] border border-[var(--chat-border)] bg-[var(--chat-surface)] text-[var(--chat-accent)]">
          {icon}
        </div>
        <div className="mt-3 text-sm font-semibold text-[var(--chat-muted-strong)]">
          {title}
        </div>
        <p className="mt-1 text-xs leading-5 text-[var(--chat-muted)]">{body}</p>
      </div>
    </div>
  );
}

function PanelError({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="max-w-sm rounded-[8px] border border-[color-mix(in_srgb,var(--chat-danger)_34%,transparent)] bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-4 text-sm text-[var(--chat-danger)]">
        <div className="font-semibold">Could not load this panel</div>
        <div className="mt-1 break-words text-xs opacity-90">{message}</div>
      </div>
    </div>
  );
}

function PanelSectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="px-1 text-[11px] font-medium uppercase tracking-wider text-[var(--chat-muted)]">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header selector — the "little icon" dropdown (Preview / Files / Background
// tasks / Plan). No Diff, no Terminal.
// ---------------------------------------------------------------------------

const SELECTOR_ROWS: {
  mode: SidePanelMode;
  label: string;
  icon: ReactNode;
  hint?: string;
}[] = [
  { mode: "preview", label: "Preview", icon: <FileText className="h-4 w-4" />, hint: "⇧⌘P" },
  { mode: "artifacts", label: "Artifacts", icon: <FileStack className="h-4 w-4" /> },
  { mode: "files", label: "Files", icon: <Folder className="h-4 w-4" />, hint: "⇧⌘F" },
  { mode: "tasks", label: "Background tasks", icon: <Boxes className="h-4 w-4" /> },
  { mode: "plan", label: "Plan", icon: <ListChecks className="h-4 w-4" /> },
];

export function SidePanelSelector({
  mode,
  onSelect,
  runningTasks = 0,
}: {
  mode: SidePanelMode;
  onSelect: (mode: SidePanelMode) => void;
  runningTasks?: number;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; right: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const toggle = useCallback(() => {
    setOpen((prev) => {
      if (prev) return false;
      const rect = btnRef.current?.getBoundingClientRect();
      if (rect) {
        setCoords({ top: rect.bottom + 6, right: window.innerWidth - rect.right });
      }
      return true;
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      // The menu is portaled to document.body, so it is NOT inside btnRef —
      // must check it separately or mousedown closes the menu before a row's
      // click can land (the row unmounts), making every option a no-op.
      if (btnRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        aria-label="Side panels"
        aria-expanded={open}
        title="Side panels"
        className={cn(
          // .icon-btn forces `display:grid` + a fixed 26px box, which stacks the
          // icon over the chevron and rides it up against the top border. Force a
          // centered inline row with auto width so it sits inline with the title.
          "icon-btn relative !inline-flex !w-auto items-center gap-0.5 px-1.5",
          mode !== "none" && "text-[var(--chat-accent)]",
        )}
      >
        <PanelRight className="h-3.5 w-3.5" />
        <ChevronDown className="h-3 w-3 opacity-70" />
        {runningTasks > 0 && mode !== "tasks" ? (
          // Live pulse: a background task is running. Nudges the user toward the
          // Background tasks panel without auto-stealing their view.
          <span
            className="absolute -right-0.5 -top-0.5 flex h-2 w-2"
            title={`${runningTasks} background task${runningTasks === 1 ? "" : "s"} running`}
          >
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--chat-accent)] opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--chat-accent)]" />
          </span>
        ) : null}
      </button>
      {open && coords
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[80] min-w-[212px] overflow-hidden rounded-[10px] border border-[var(--chat-border)] bg-[var(--chat-surface)] p-1 shadow-[0_24px_60px_-16px_rgba(0,0,0,0.7),0_1px_0_rgba(255,255,255,0.03)_inset]"
              style={{ top: coords.top, right: coords.right }}
            >
              {SELECTOR_ROWS.map((row) => {
                const active = mode === row.mode;
                return (
                  <button
                    key={row.mode}
                    type="button"
                    onClick={() => {
                      onSelect(row.mode);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-[7px] px-2.5 py-1.5 text-left text-[13px] transition-colors",
                      "text-[var(--chat-text)] hover:bg-[var(--chat-surface-strong)]",
                      active && "bg-[var(--chat-surface-strong)]",
                    )}
                  >
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center text-[var(--chat-muted-strong)]">
                      {row.icon}
                    </span>
                    <span className="flex-1 truncate">{row.label}</span>
                    {row.mode === "tasks" && runningTasks > 0 ? (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--chat-accent)_15%,transparent)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--chat-accent)]">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--chat-accent)] opacity-75" />
                          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--chat-accent)]" />
                        </span>
                        {runningTasks}
                      </span>
                    ) : null}
                    {row.hint ? (
                      <span className="shrink-0 text-[11px] tabular-nums text-[var(--chat-muted)]">
                        {row.hint}
                      </span>
                    ) : null}
                    {active ? (
                      <Check className="h-3.5 w-3.5 shrink-0 text-[var(--chat-accent)]" />
                    ) : null}
                  </button>
                );
              })}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Plan panel — the session todo list (source: GET /api/sessions/:id/todos).
// ---------------------------------------------------------------------------

const STATUS_GLYPH: Record<TodoStatus, { icon: ReactNode; tone: string }> = {
  pending: { icon: <Circle className="h-4 w-4" />, tone: "text-[var(--chat-muted)]" },
  in_progress: { icon: <CircleDot className="h-4 w-4" />, tone: "text-[var(--chat-accent)]" },
  completed: { icon: <CheckCircle2 className="h-4 w-4" />, tone: "text-[var(--color-success)]" },
  cancelled: { icon: <XCircle className="h-4 w-4" />, tone: "text-[var(--chat-muted)]" },
};

function PlanRow({ item }: { item: TodoItem }) {
  const glyph = STATUS_GLYPH[item.status] ?? STATUS_GLYPH.pending;
  return (
    <li className="flex items-start gap-2.5 rounded-[7px] px-2.5 py-1.5 hover:bg-[var(--chat-surface-strong)]/50">
      <span className={cn("mt-px shrink-0", glyph.tone)}>{glyph.icon}</span>
      <span
        className={cn(
          "text-[13px] leading-5",
          item.status === "completed" && "text-[var(--chat-muted)] line-through",
          item.status === "cancelled" && "text-[var(--chat-muted)] line-through opacity-70",
          item.status === "in_progress" && "font-medium text-[var(--chat-text)]",
          item.status === "pending" && "text-[var(--chat-muted-strong)]",
        )}
      >
        {item.content}
      </span>
    </li>
  );
}

export function PlanPanel({
  sessionId,
  refreshSignal,
  onClose,
}: {
  sessionId: string;
  refreshSignal: number;
  onClose: () => void;
}) {
  const [todos, setTodos] = useState<TodoItem[] | null>(null);
  const [planMd, setPlanMd] = useState<string>("");
  const [planTitle, setPlanTitle] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setTodos([]);
      setPlanMd("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([
      api.getSessionPlan(sessionId),
      api.getSessionTodos(sessionId),
    ])
      .then(([planRes, todoRes]) => {
        if (cancelled) return;
        if (planRes.status === "fulfilled") {
          setPlanMd(planRes.value.plan || "");
          setPlanTitle(planRes.value.title || "");
        }
        if (todoRes.status === "fulfilled") {
          setTodos(Array.isArray(todoRes.value.todos) ? todoRes.value.todos : []);
        }
        if (planRes.status === "rejected" && todoRes.status === "rejected") {
          setError((planRes.reason as Error)?.message ?? "Failed to load plan");
        } else {
          setError(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, refreshSignal]);

  const total = todos?.length ?? 0;
  const completed = todos?.filter((t) => t.status === "completed").length ?? 0;
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const hasPlan = planMd.trim().length > 0;
  const isEmpty = !hasPlan && total === 0;

  return (
    <PanelShell
      icon={<ListChecks className="h-4.5 w-4.5" />}
      title="Plan"
      subtitle={
        hasPlan
          ? planTitle || "Proposed plan"
          : total
            ? `${completed} of ${total} done`
            : "Plan for this session"
      }
      onClose={onClose}
    >
      {total > 0 ? (
        <div className="sticky top-0 z-10 border-b border-[var(--chat-border)] bg-[var(--chat-surface-soft)] px-4 pb-2.5 pt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--chat-surface-strong)]">
            <div
              className="h-full rounded-full bg-[var(--chat-accent)] transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      ) : null}
      {loading && todos === null && !hasPlan ? (
        <div className="flex flex-col gap-3 p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-4 w-full animate-pulse rounded-[6px] bg-[var(--chat-border)]" />
          ))}
        </div>
      ) : error && isEmpty ? (
        <PanelError message={error} />
      ) : isEmpty ? (
        <PanelEmpty
          icon={<ListChecks className="h-5 w-5" />}
          title="No plan yet"
          body="In plan mode the agent writes its full plan here for you to review and approve."
        />
      ) : (
        <div className="flex flex-col">
          {hasPlan ? (
            <div className="chat-message-prose border-b border-[var(--chat-border)] px-4 py-3 text-[var(--chat-text)] [&_a]:text-[var(--chat-accent)] [&_table]:text-[12px]">
              <Markdown content={planMd} />
            </div>
          ) : null}
          {total > 0 ? (
            <>
              {hasPlan ? (
                <PanelSectionLabel>
                  <span className="px-2 pt-2">Checklist</span>
                </PanelSectionLabel>
              ) : null}
              <ul className="flex flex-col gap-0.5 p-2">
                {todos!.map((item, index) => (
                  <PlanRow key={item.id || `todo-${index}`} item={item} />
                ))}
              </ul>
            </>
          ) : null}
        </div>
      )}
    </PanelShell>
  );
}

// ---------------------------------------------------------------------------
// Background tasks panel — every off-thread task (subagent runs, mixtures,
// handoffs) the session spawns. Fed a unified list built in ChatPage from the
// subagent lifecycle + the background tool stream.
// ---------------------------------------------------------------------------

// One background task as the panel renders it. Built in ChatPage from
// SubagentEntry (rich: goal/model/tool count) and background ToolEntry rows.
export interface BackgroundTaskItem {
  id: string;
  kind: "subagent" | "mixture" | "handoff" | "task";
  label: string;
  status: "running" | "done" | "error";
  detail?: string;
  model?: string;
  toolCount?: number;
  startedAt?: number;
  completedAt?: number;
}

function relativeTime(ts?: number): string {
  if (!ts) return "";
  const diff = Date.now() - ts;
  if (diff < 60_000) return "just now";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function TaskStatusBadge({ status }: { status: BackgroundTaskItem["status"] }) {
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--chat-accent)_15%,transparent)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--chat-accent)]">
        <Loader2 className="h-3 w-3 animate-spin" />
        Running
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--chat-danger)_15%,transparent)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--chat-danger)]">
        <AlertCircle className="h-3 w-3" />
        Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--chat-surface-strong)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--chat-muted-strong)]">
      <Check className="h-3 w-3" />
      Done
    </span>
  );
}

const KIND_LABEL: Record<BackgroundTaskItem["kind"], string> = {
  subagent: "Subagent",
  mixture: "Mixture of agents",
  handoff: "Handoff",
  task: "Task",
};

function TaskCard({ task }: { task: BackgroundTaskItem }) {
  return (
    <div className="rounded-[9px] border border-[var(--chat-border)] bg-[var(--chat-surface)] px-3 py-2.5">
      <div className="flex items-center gap-2">
        <TaskStatusBadge status={task.status} />
        <span className="truncate text-[13px] font-medium text-[var(--chat-text)]">
          {task.label}
        </span>
        <span className="ml-auto shrink-0 text-[11px] tabular-nums text-[var(--chat-muted)]">
          {relativeTime(task.completedAt ?? task.startedAt)}
        </span>
      </div>
      {(task.model || task.toolCount || task.kind !== "subagent") && (
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--chat-muted)]">
          <span className="uppercase tracking-wide">{KIND_LABEL[task.kind]}</span>
          {task.model ? <span>· {task.model}</span> : null}
          {task.toolCount ? (
            <span>· {task.toolCount} tool{task.toolCount === 1 ? "" : "s"}</span>
          ) : null}
        </div>
      )}
      {task.detail ? (
        <p className="mt-1.5 line-clamp-3 break-words text-[12px] leading-5 text-[var(--chat-muted-strong)]">
          {task.detail}
        </p>
      ) : null}
    </div>
  );
}

export function BackgroundTasksPanel({
  tasks,
  onClose,
}: {
  tasks: BackgroundTaskItem[];
  onClose: () => void;
}) {
  const running = tasks.filter((task) => task.status === "running");
  const finished = tasks.filter((task) => task.status !== "running");

  return (
    <PanelShell
      icon={<Boxes className="h-4.5 w-4.5" />}
      title="Background tasks"
      subtitle={tasks.length ? `${tasks.length} this session` : "Subagent + handoff activity"}
      onClose={onClose}
    >
      {tasks.length === 0 ? (
        <PanelEmpty
          icon={<Boxes className="h-5 w-5" />}
          title="No background tasks"
          body="Subagent runs, mixtures, and handoffs from this session show up here."
        />
      ) : (
        <div className="flex flex-col gap-3 p-3">
          {running.length > 0 ? (
            <div className="flex flex-col gap-2">
              <PanelSectionLabel>Running</PanelSectionLabel>
              <div className="flex flex-col gap-2">
                {running.map((task) => (
                  <TaskCard key={task.id} task={task} />
                ))}
              </div>
            </div>
          ) : null}
          {finished.length > 0 ? (
            <div className="flex flex-col gap-2">
              <PanelSectionLabel>Finished</PanelSectionLabel>
              <div className="flex flex-col gap-2">
                {finished.map((task) => (
                  <TaskCard key={task.id} task={task} />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </PanelShell>
  );
}

// ---------------------------------------------------------------------------
// Artifacts — a card list of everything generated this session (PDFs, HTML,
// images, files). Same card language as Background tasks; clicking a card opens
// it in the Preview pane.
// ---------------------------------------------------------------------------

// Minimal shape the card renders — structurally compatible with ChatPage's
// ArtifactEntry (kept local to avoid a circular import back into ChatPage).
export interface ArtifactListItem {
  id: string;
  title: string;
  kind: string;
  createdAt: number;
  detail?: string;
  path?: string;
  source?: string;
  status?: "error" | "ok";
}

function artifactKindIcon(kind: string) {
  switch (kind) {
    case "image":
      return <ImageIcon className="h-4 w-4" />;
    case "html":
      return <FileCode className="h-4 w-4" />;
    case "pdf":
    case "text":
      return <FileText className="h-4 w-4" />;
    default:
      return <FileIcon className="h-4 w-4" />;
  }
}

function ArtifactCard<T extends ArtifactListItem>({
  item,
  onOpen,
}: {
  item: T;
  onOpen: (item: T) => void;
}) {
  const detail = item.path || item.detail || item.source || "";
  return (
    <button
      type="button"
      onClick={() => onOpen(item)}
      className="w-full rounded-[9px] border border-[var(--chat-border)] bg-[var(--chat-surface)] px-3 py-2.5 text-left transition-colors hover:bg-[var(--chat-surface-strong)]"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-[var(--chat-muted-strong)]">
          {artifactKindIcon(item.kind)}
        </span>
        <span className="truncate text-[13px] font-medium text-[var(--chat-text)]">
          {item.title}
        </span>
        {item.status === "error" ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--chat-danger)_15%,transparent)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--chat-danger)]">
            <AlertCircle className="h-3 w-3" />
            Error
          </span>
        ) : null}
        <span className="ml-auto shrink-0 text-[11px] tabular-nums text-[var(--chat-muted)]">
          {relativeTime(item.createdAt)}
        </span>
      </div>
      {detail ? (
        <p className="mt-1.5 line-clamp-2 break-words text-[12px] leading-5 text-[var(--chat-muted-strong)]">
          {detail}
        </p>
      ) : null}
    </button>
  );
}

export function ArtifactsPanel<T extends ArtifactListItem>({
  artifacts,
  onOpen,
  onClose,
}: {
  artifacts: T[];
  onOpen: (item: T) => void;
  onClose: () => void;
}) {
  // Newest first.
  const items = useMemo(() => artifacts.slice().reverse(), [artifacts]);
  return (
    <PanelShell
      icon={<FileStack className="h-4.5 w-4.5" />}
      title="Artifacts"
      subtitle={items.length ? `${items.length} this session` : "Generated files & previews"}
      onClose={onClose}
    >
      {items.length === 0 ? (
        <PanelEmpty
          icon={<FileStack className="h-5 w-5" />}
          title="No artifacts yet"
          body="PDFs, documents, images, and files the agent generates this session show up here. Tap one to preview it."
        />
      ) : (
        <div className="flex flex-col gap-2 p-3">
          {items.map((item) => (
            <ArtifactCard key={item.id} item={item} onOpen={onOpen} />
          ))}
        </div>
      )}
    </PanelShell>
  );
}

// ---------------------------------------------------------------------------
// Preview (empty) — Preview always opens; this is the no-artifact state so the
// panel still pops up instead of being a dead/disabled menu row.
// ---------------------------------------------------------------------------

export function EmptyPreviewPanel({ onClose }: { onClose: () => void }) {
  return (
    <PanelShell icon={<FileText className="h-4.5 w-4.5" />} title="Preview" onClose={onClose}>
      <PanelEmpty
        icon={<FileText className="h-5 w-5" />}
        title="No preview"
        body="Open a file from Files, or click a file the agent created, to preview it here."
      />
    </PanelShell>
  );
}

// ---------------------------------------------------------------------------
// Files panel — the files the agent actually worked on this session. Elevate
// chats have no single workspace dir (agents touch scattered absolute paths),
// so the list comes from GET /api/sessions/:id/files (server-side scan of the
// file paths passed to file tools), grouped by directory. Click → Preview.
// ---------------------------------------------------------------------------

function dirOf(path: string): string {
  const i = path.lastIndexOf("/");
  return i > 0 ? path.slice(0, i) : "/";
}

function shortDir(path: string): string {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 2) return path;
  return `…/${parts.slice(-2).join("/")}`;
}

export function FilesPanel({
  sessionId,
  onOpenFile,
  onClose,
}: {
  sessionId: string;
  onOpenFile: (path: string, name: string) => void;
  onClose: () => void;
}) {
  const [files, setFiles] = useState<SessionFileItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!sessionId) {
      setFiles([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .getSessionFiles(sessionId)
      .then((response) => {
        if (cancelled) return;
        setFiles(Array.isArray(response.files) ? response.files : []);
        setError(null);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const total = files?.length ?? 0;

  const groups = useMemo(() => {
    const list = files ?? [];
    const query = filter.trim().toLowerCase();
    const filtered = list.filter(
      (file) =>
        !query ||
        file.name.toLowerCase().includes(query) ||
        file.path.toLowerCase().includes(query),
    );
    const map = new Map<string, SessionFileItem[]>();
    for (const file of filtered) {
      const dir = dirOf(file.path);
      const arr = map.get(dir) ?? [];
      arr.push(file);
      map.set(dir, arr);
    }
    return [...map.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([dir, items]) => ({
        dir,
        items: items.sort((a, b) => a.name.localeCompare(b.name)),
      }));
  }, [files, filter]);

  return (
    <PanelShell
      icon={<Folder className="h-4.5 w-4.5" />}
      title="Files"
      subtitle={
        total ? `${total} file${total === 1 ? "" : "s"} this session` : "Files the agent worked on"
      }
      onClose={onClose}
    >
      {total > 0 ? (
        <div className="sticky top-0 z-10 border-b border-[var(--chat-border)] bg-[var(--chat-surface-soft)] p-2">
          <input
            type="text"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter files…"
            className="w-full rounded-[7px] border border-[var(--chat-border)] bg-[var(--chat-surface)] px-2.5 py-1.5 text-[12.5px] text-[var(--chat-text)] outline-none placeholder:text-[var(--chat-muted)] focus:border-[var(--chat-accent)]"
          />
        </div>
      ) : null}
      {loading && files === null ? (
        <div className="flex flex-col gap-2 p-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-4 w-full animate-pulse rounded-[6px] bg-[var(--chat-border)]" />
          ))}
        </div>
      ) : error ? (
        <PanelError message={error} />
      ) : total === 0 ? (
        <PanelEmpty
          icon={<Folder className="h-5 w-5" />}
          title="No files yet"
          body="Files the agent reads or writes in this session show up here."
        />
      ) : groups.length === 0 ? (
        <PanelEmpty
          icon={<Folder className="h-5 w-5" />}
          title="No matches"
          body="No files match your filter."
        />
      ) : (
        <div className="flex flex-col gap-3 p-2">
          {groups.map((group) => (
            <div key={group.dir} className="flex flex-col">
              <div
                className="flex items-center gap-1.5 px-1.5 py-1 text-[11px] font-medium text-[var(--chat-muted)]"
                title={group.dir}
              >
                <Folder className="h-3 w-3 shrink-0" />
                <span className="truncate">{shortDir(group.dir)}</span>
              </div>
              {group.items.map((file) => (
                <button
                  key={file.path}
                  type="button"
                  onClick={() => onOpenFile(file.path, file.name)}
                  title={file.path}
                  className="flex w-full items-center gap-2 rounded-[6px] py-1 pl-5 pr-2 text-left text-[12.5px] text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
                >
                  <FileIcon className="h-3.5 w-3.5 shrink-0 text-[var(--chat-muted)]" />
                  <span className="truncate">{file.name}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </PanelShell>
  );
}
