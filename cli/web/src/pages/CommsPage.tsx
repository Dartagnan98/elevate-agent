import { useCallback, useEffect, useMemo, useState } from "react";
import { useRefreshOnAgentTurn } from "@/lib/useRefreshOnAgentTurn";
import { useSearchParams } from "react-router-dom";
import { ArrowDownUp, ArrowRight, CheckCircle, Hash, ListTodo, Loader2, MessageSquare, Play, RefreshCw, Search, Send, Users, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentCommsChannel, AgentCommsChannelResponse, AgentCommsMessage, AgentHandoff } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ListSkeleton, Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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

type AgentOption = { id: string; name: string };

function HandoffRow({
  h,
  nameOf,
  selected,
  onOpen,
}: {
  h: AgentHandoff;
  nameOf: (id: string) => string;
  selected: boolean;
  onOpen: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={cn(
          "w-full space-y-1.5 rounded-md border bg-card/40 p-2.5 text-left transition-colors hover:border-foreground/20",
          selected ? "border-foreground/30" : "border-border",
        )}
      >
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
      </button>
    </li>
  );
}

function HandoffComposerSkeleton() {
  // Mirrors the HandoffComposer card 1:1 so the right pane stays consistent
  // (no real-form-with-empty-dropdowns pop) while comms data loads.
  return (
    <div className="rounded-lg border border-border bg-card/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-56 max-w-full" />
        </div>
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="grid gap-1">
            <Skeleton className="h-3 w-10" />
            <Skeleton className="h-8 rounded-md" />
          </div>
        ))}
      </div>
      <Skeleton className="mt-2 h-8 w-full rounded-md" />
      <Skeleton className="mt-2 h-[4.5rem] w-full rounded-md" />
      <div className="mt-2 flex items-center justify-between gap-2">
        <Skeleton className="h-8 w-32 rounded-md" />
        <Skeleton className="h-8 w-32 rounded-md" />
      </div>
    </div>
  );
}

function HandoffComposer({
  agents,
  loading,
  onCreated,
}: {
  agents: AgentOption[];
  loading?: boolean;
  onCreated: (handoff: AgentHandoff) => void;
}) {
  const executive = agents.find((agent) => agent.id === "executive-assistant") ?? agents[0];
  const firstTarget = agents.find((agent) => agent.id !== executive?.id) ?? agents[0];
  const [fromAgentId, setFromAgentId] = useState(executive?.id ?? "executive-assistant");
  const [toAgentId, setToAgentId] = useState(firstTarget?.id ?? "admin");
  const [title, setTitle] = useState("");
  const [task, setTask] = useState("");
  const [priority, setPriority] = useState("normal");
  const [runNow, setRunNow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fromAgentId && executive?.id) setFromAgentId(executive.id);
    if (!toAgentId && firstTarget?.id) setToAgentId(firstTarget.id);
  }, [executive?.id, firstTarget?.id, fromAgentId, toAgentId]);

  const submit = async () => {
    if (!task.trim() || !fromAgentId || !toAgentId || fromAgentId === toAgentId) return;
    setBusy(true);
    setError(null);
    try {
      const handoff = await api.createAgentHandoff({
        fromAgentId,
        toAgentId,
        title: title.trim() || undefined,
        task: task.trim(),
        priority: priority as "low" | "normal" | "high" | "urgent",
        runNow,
      });
      setTitle("");
      setTask("");
      setPriority("normal");
      setRunNow(false);
      onCreated(handoff);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create handoff");
    } finally {
      setBusy(false);
    }
  };

  if (loading && agents.length === 0) return <HandoffComposerSkeleton />;

  return (
    <div className="rounded-lg border border-border bg-card/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-foreground">Give an agent a task</p>
          <p className="text-[11px] text-muted-foreground">Creates a durable handoff in the same bus agents use.</p>
        </div>
        <Badge variant="outline">handoff</Badge>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <label className="grid gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          From
          <select
            value={fromAgentId}
            onChange={(event) => setFromAgentId(event.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs normal-case text-foreground"
          >
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>{agent.name}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
          To
          <select
            value={toAgentId}
            onChange={(event) => setToAgentId(event.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs normal-case text-foreground"
          >
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>{agent.name}</option>
            ))}
          </select>
        </label>
      </div>
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder="Title"
        className="mt-2 h-8 w-full rounded-md border border-border bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground/60"
      />
      <textarea
        value={task}
        onChange={(event) => setTask(event.target.value)}
        rows={3}
        placeholder="Task details"
        className="mt-2 w-full resize-y rounded-md border border-border bg-background px-2.5 py-2 text-xs leading-5 text-foreground placeholder:text-muted-foreground/60"
      />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <select
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
          >
            <option value="urgent">urgent</option>
            <option value="high">high</option>
            <option value="normal">normal</option>
            <option value="low">low</option>
          </select>
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={runNow}
              onChange={(event) => setRunNow(event.target.checked)}
              className="accent-foreground"
            />
            Run now
          </label>
        </div>
        <Button size="sm" onClick={submit} disabled={busy || !task.trim() || fromAgentId === toAgentId}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          Create handoff
        </Button>
      </div>
      {error && <p className="mt-2 text-[11px] text-destructive">{error}</p>}
    </div>
  );
}

function HandoffThread({
  handoff,
  loading,
  nameOf,
  onClose,
  onChanged,
}: {
  handoff: AgentHandoff | null;
  loading: boolean;
  nameOf: (id: string) => string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [note, setNote] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    setNote("");
    setResult("");
    setBusy(null);
  }, [handoff?.id]);

  if (!handoff) {
    return (
      <Card>
        <CardContent className="p-3 text-[11px] italic text-muted-foreground/70">
          Select a handoff to inspect the thread and actions.
        </CardContent>
      </Card>
    );
  }

  const refresh = async () => {
    onChanged();
  };
  const addNote = async () => {
    if (!note.trim()) return;
    setBusy("note");
    try {
      await api.createAgentHandoffMessage(handoff.id, {
        fromAgentId: handoff.toAgentId,
        toAgentId: handoff.fromAgentId,
        kind: "note",
        content: note.trim(),
      });
      setNote("");
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const complete = async (status: "completed" | "failed") => {
    setBusy(status);
    try {
      await api.completeAgentHandoff(handoff.id, {
        status,
        actor: handoff.toAgentId,
        result: status === "completed" ? { summary: result.trim() || "Marked complete." } : null,
        errorMessage: status === "failed" ? result.trim() || "Marked failed." : null,
      });
      setResult("");
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const approve = async () => {
    setBusy("approve");
    try {
      await api.approveAgentHandoff(handoff.id, { approved: true, runNow: false, actor: handoff.fromAgentId });
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const runQueue = async () => {
    setBusy("run");
    try {
      await api.runAgentWorkerTick({ agentId: handoff.toAgentId });
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const createTaskFromThread = async (source?: { id?: string; content?: string }) => {
    const sourceText = String(source?.content || handoff.task || "").trim();
    if (!sourceText) return;
    const busyKey = source?.id ? `task:${source.id}` : "task:thread";
    setBusy(busyKey);
    try {
      const title = source?.id
        ? `${handoff.title}: follow up`
        : handoff.title || sourceText.slice(0, 72);
      const created = await api.createSurfaceTask({
        title: title.slice(0, 120),
        description: [
          source?.id ? "Created from a Comms thread message." : "Created from a Comms handoff thread.",
          `Thread: ${handoff.id}`,
          `From: ${handoff.fromAgentId}`,
          `To: ${handoff.toAgentId}`,
          "",
          sourceText,
        ].join("\n"),
        assignee: handoff.toAgentId,
        priority: handoff.priority,
        project: "agent-comms",
      });
      await api.createAgentHandoffMessage(handoff.id, {
        fromAgentId: handoff.fromAgentId,
        toAgentId: handoff.toAgentId,
        kind: "note",
        content: `Created task ${created.task.id}: ${created.task.title}`,
        payload: { taskId: created.task.id, sourceMessageId: source?.id || null },
      });
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-3 p-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-medium leading-5 text-foreground">{handoff.title}</p>
            <p className="text-[11px] text-muted-foreground">
              {nameOf(handoff.fromAgentId)} → {nameOf(handoff.toAgentId)} · {timeAgo(handoff.updatedAt)}
            </p>
          </div>
          <button type="button" className="text-[11px] text-muted-foreground hover:text-foreground" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={statusVariant(String(handoff.status))}>{String(handoff.status).replace("_", " ")}</Badge>
          <span className={cn("text-[11px] font-medium", PRIORITY_TONE[handoff.priority])}>{handoff.priority}</span>
          {handoff.cronJobId && <span className="text-[11px] text-muted-foreground">cron {handoff.cronJobId}</span>}
        </div>
        <p className="whitespace-pre-wrap rounded-md bg-secondary/30 p-2 text-xs leading-5 text-muted-foreground">
          {handoff.task}
        </p>
        {loading ? (
          <ListSkeleton rows={3} />
        ) : (
          <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
            {(handoff.messages ?? []).map((message) => (
              <div key={message.id} className="rounded-md border border-border bg-background/50 p-2">
                <div className="mb-1 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                  <span>{nameOf(message.fromAgentId)}</span>
                  {message.toAgentId && <span>→ {nameOf(message.toAgentId)}</span>}
                  <Badge variant={statusVariant(message.kind)}>{message.kind}</Badge>
                  <span className="ml-auto">{timeAgo(message.createdAt)}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-1.5 text-[10px]"
                    onClick={() => createTaskFromThread({ id: message.id, content: message.content })}
                    disabled={busy !== null || !message.content?.trim()}
                  >
                    {busy === `task:${message.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <ListTodo className="h-3 w-3" />}
                    Task
                  </Button>
                </div>
                <p className="whitespace-pre-wrap text-[11px] leading-5 text-foreground/85">{message.content}</p>
              </div>
            ))}
            {(handoff.messages ?? []).length === 0 && (
              <p className="text-[11px] italic text-muted-foreground">No messages yet.</p>
            )}
          </div>
        )}
        {handoff.status === "queued" && (
          <Button size="sm" variant="outline" onClick={runQueue} disabled={busy !== null}>
            {busy === "run" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            Run agent queue
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => createTaskFromThread()} disabled={busy !== null || !handoff.task?.trim()}>
          {busy === "task:thread" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ListTodo className="h-3.5 w-3.5" />}
          Create task
        </Button>
        {handoff.status === "waiting_human" && (
          <Button size="sm" variant="outline" onClick={approve} disabled={busy !== null}>
            {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}
            Approve
          </Button>
        )}
        {!["completed", "failed", "cancelled"].includes(String(handoff.status)) && (
          <div className="space-y-2">
            <textarea
              value={result}
              onChange={(event) => setResult(event.target.value)}
              rows={2}
              placeholder="Result summary or failure reason"
              className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-2 text-xs leading-5 text-foreground placeholder:text-muted-foreground/60"
            />
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => complete("completed")} disabled={busy !== null}>
                {busy === "completed" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}
                Complete
              </Button>
              <Button size="sm" variant="destructive" onClick={() => complete("failed")} disabled={busy !== null}>
                {busy === "failed" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                Fail
              </Button>
            </div>
          </div>
        )}
        <div className="space-y-2 border-t border-border pt-3">
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            placeholder="Add an agent note"
            className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-2 text-xs leading-5 text-foreground placeholder:text-muted-foreground/60"
          />
          <Button size="sm" variant="outline" onClick={addNote} disabled={busy !== null || !note.trim()}>
            {busy === "note" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Add note
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function CommsFeedList({
  messages,
  loading,
  nameOf,
  onOpenPair,
  onOpenHandoff,
}: {
  messages: AgentCommsMessage[];
  loading?: boolean;
  nameOf: (id: string) => string;
  onOpenPair: (pair: string) => void;
  onOpenHandoff: (handoffId: string) => void;
}) {
  if (loading && messages.length === 0) {
    return <ListSkeleton rows={6} />;
  }
  if (messages.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
        No messages yet.
      </div>
    );
  }
  return (
    <ul className="space-y-2">
      {messages.map((msg) => (
        <li key={msg.id}>
          <button
            type="button"
            onClick={() => onOpenPair(msg.pair)}
            className="w-full rounded-md border border-border bg-card/50 p-2.5 text-left transition-colors hover:border-foreground/20"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
              <span className="font-medium text-foreground/90">{nameOf(msg.from)}</span>
              <ArrowRight className="h-3 w-3 text-muted-foreground" />
              <span className="font-medium text-foreground/90">{nameOf(msg.to)}</span>
              <Badge variant={statusVariant(msg.kind)}>{msg.kind.replace("_", " ")}</Badge>
              <span className={cn("font-medium", PRIORITY_TONE[msg.priority])}>{msg.priority}</span>
              <span className="ml-auto text-muted-foreground/70">{timeAgo(msg.timestamp)}</span>
            </div>
            {msg.title && <p className="mt-1 text-xs font-medium text-foreground/90">{msg.title}</p>}
            <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-muted-foreground">{msg.text}</p>
            <div className="mt-2 flex justify-end">
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[10px]"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenHandoff(msg.handoffId);
                }}
              >
                Thread
              </Button>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ChannelListPanel({
  channels,
  loading,
  selectedPair,
  query,
  nameOf,
  onSelect,
}: {
  channels: AgentCommsChannel[];
  loading?: boolean;
  selectedPair: string | null;
  query: string;
  nameOf: (id: string) => string;
  onSelect: (pair: string) => void;
}) {
  const visible = channels.filter((channel) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return channel.pair.toLowerCase().includes(q)
      || channel.agents.some((agent) => nameOf(agent).toLowerCase().includes(q));
  });
  if (loading && channels.length === 0) {
    return <ListSkeleton rows={6} />;
  }
  if (visible.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-4 text-center text-[11px] italic text-muted-foreground/60">
        no channels
      </div>
    );
  }
  return (
    <ul className="space-y-1.5">
      {visible.map((channel) => {
        const last = channel.last_message || channel.lastMessage;
        return (
          <li key={channel.pair}>
            <button
              type="button"
              onClick={() => onSelect(channel.pair)}
              className={cn(
                "w-full rounded-md border bg-card/50 p-2 text-left transition-colors hover:border-foreground/20",
                selectedPair === channel.pair ? "border-foreground/30" : "border-border",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-xs font-medium text-foreground/90">
                  {channel.agents.map(nameOf).join(" ↔ ")}
                </p>
                <span className="text-[10px] tabular-nums text-muted-foreground/70">
                  {channel.message_count || channel.messageCount || 0}
                </span>
              </div>
              {last && (
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                  {nameOf(last.from)}: {last.text}
                </p>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function ChannelTranscript({
  conversation,
  loading,
  sortOrder,
  nameOf,
  onToggleSort,
  onSend,
  onOpenHandoff,
}: {
  conversation: AgentCommsChannelResponse | null;
  loading: boolean;
  sortOrder: "asc" | "desc";
  nameOf: (id: string) => string;
  onToggleSort: () => void;
  onSend: (body: { toAgentId: string; text: string; priority: "low" | "normal" | "high" | "urgent" }) => Promise<void>;
  onOpenHandoff: (handoffId: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [priority, setPriority] = useState<"low" | "normal" | "high" | "urgent">("normal");
  const [sending, setSending] = useState(false);
  const participants = conversation?.agents ?? [];
  const userAgent = participants.find((agent) => ["human", "human-web", "operator", "dashboard"].includes(agent));
  const targetAgent = participants.find((agent) => agent !== userAgent) || participants[1] || participants[0] || "";
  const canSend = Boolean(conversation && userAgent && targetAgent);
  const messages = conversation?.messages ?? [];
  const sorted = sortOrder === "asc" ? messages : [...messages].reverse();

  const submit = async () => {
    if (!draft.trim() || !targetAgent) return;
    setSending(true);
    try {
      await onSend({ toAgentId: targetAgent, text: draft.trim(), priority });
      setDraft("");
      setPriority("normal");
    } finally {
      setSending(false);
    }
  };

  if (!conversation) {
    return (
      <div className="flex h-full min-h-[360px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        Select a channel.
      </div>
    );
  }
  return (
    <div className="flex h-[calc(100vh-310px)] min-h-[460px] flex-col overflow-hidden rounded-lg border border-border bg-card/30">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {participants.map(nameOf).join(" ↔ ")}
          </p>
          <p className="text-[10px] text-muted-foreground">{conversation.count} messages</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onToggleSort}>
          <ArrowDownUp className="h-3.5 w-3.5" />
          {sortOrder === "asc" ? "Newest down" : "Newest up"}
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {loading ? (
          <ListSkeleton rows={4} />
        ) : sorted.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No messages in this channel.</p>
        ) : (
          sorted.map((msg) => {
            const isFirst = msg.from === participants[0];
            return (
              <div key={msg.id} className={cn("flex", isFirst ? "justify-start" : "justify-end")}>
                <div className={cn(
                  "max-w-[78%] rounded-xl border px-3 py-2 text-sm shadow-sm",
                  isFirst ? "rounded-bl-sm bg-muted/60 border-border/50" : "rounded-br-sm bg-primary/10 border-primary/20",
                )}>
                  <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                    <span className="font-medium text-foreground/90">{nameOf(msg.from)}</span>
                    <Badge variant={statusVariant(msg.kind)}>{msg.kind.replace("_", " ")}</Badge>
                    {msg.priority === "urgent" && <Badge variant="destructive">urgent</Badge>}
                    <button
                      type="button"
                      onClick={() => onOpenHandoff(msg.handoffId)}
                      className="ml-auto hover:text-foreground"
                    >
                      thread
                    </button>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-xs leading-5 text-foreground/85">{msg.text}</p>
                  <p className="mt-1 text-right text-[10px] text-muted-foreground">{timeAgo(msg.timestamp)}</p>
                </div>
              </div>
            );
          })
        )}
      </div>
      {canSend && (
        <div className="shrink-0 space-y-2 border-t border-border bg-background/80 p-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            rows={2}
            placeholder={`Message ${nameOf(targetAgent)}...`}
            className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm leading-5 text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-foreground/30"
          />
          <div className="flex items-center justify-between gap-2">
            <select
              value={priority}
              onChange={(event) => setPriority(event.target.value as typeof priority)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
            >
              <option value="urgent">urgent</option>
              <option value="high">high</option>
              <option value="normal">normal</option>
              <option value="low">low</option>
            </select>
            <Button size="sm" onClick={() => void submit()} disabled={!draft.trim() || sending}>
              {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              Send
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function CommsPage() {
  const [handoffs, setHandoffs] = useState<AgentHandoff[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [deliveryChannels, setDeliveryChannels] = useState<
    { platform: string; id: string; name: string; type?: string }[]
  >([]);
  const [feedMessages, setFeedMessages] = useState<AgentCommsMessage[]>([]);
  const [conversationChannels, setConversationChannels] = useState<AgentCommsChannel[]>([]);
  const [conversation, setConversation] = useState<AgentCommsChannelResponse | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [names, setNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meetingSearch, setMeetingSearch] = useState("");
  const [channelSearch, setChannelSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [searchParams, setSearchParams] = useSearchParams();
  const agentParam = searchParams.get("agent") ?? "";
  const pairParam = searchParams.get("pair") ?? "";
  const [agentFilter, setAgentFilter] = useState<string>(agentParam);
  const [selectedPair, setSelectedPair] = useState<string | null>(pairParam || null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedHandoff, setSelectedHandoff] = useState<AgentHandoff | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    setAgentFilter(agentParam);
  }, [agentParam]);

  const updateParams = useCallback(
    (patch: { agent?: string | null; pair?: string | null }) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (patch.agent !== undefined) {
          if (patch.agent) next.set("agent", patch.agent);
          else next.delete("agent");
        }
        if (patch.pair !== undefined) {
          if (patch.pair) next.set("pair", patch.pair);
          else next.delete("pair");
        }
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const selectAgentFilter = useCallback((agentId: string) => {
    setAgentFilter(agentId);
    updateParams({ agent: agentId });
  }, [updateParams]);

  const openPair = useCallback((pair: string) => {
    setSelectedPair(pair);
    updateParams({ pair });
  }, [updateParams]);

  const loadConversation = useCallback(async (pair: string | null) => {
    if (!pair) {
      setConversation(null);
      return;
    }
    setConversationLoading(true);
    try {
      setConversation(await api.getCommsChannel(pair, { limit: 250 }));
    } finally {
      setConversationLoading(false);
    }
  }, []);

  const load = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const [feed, conv, hs, ch, hub] = await Promise.all([
        api.getCommsFeed({ limit: 250, search: meetingSearch || undefined, agent: agentFilter || undefined }),
        api.getCommsChannels({ includeArchived: showArchived, limit: 250 }),
        api.getAgentHandoffs({ limit: 100 }),
        api.getCommsDeliveryChannels().catch(() => ({ channels: [] as { platform: string; id: string; name: string; type?: string }[] })),
        api.getAgentHub({ lite: true }).catch(() => ({ agents: [] as { id: string; name: string }[] })),
      ]);
      setFeedMessages(feed || []);
      setConversationChannels(conv || []);
      setHandoffs(hs.items || []);
      setDeliveryChannels(ch.channels || []);
      setAgents((hub.agents || []).map((agent) => ({ id: agent.id, name: agent.name })));
      const m: Record<string, string> = {
        "human-web": "You",
        human: "You",
        system: "System",
      };
      for (const a of hub.agents || []) m[a.id] = a.name;
      setNames(m);
      const nextPair = selectedPair || pairParam || conv?.[0]?.pair || null;
      if (!selectedPair && nextPair) {
        setSelectedPair(nextPair);
      }
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [agentFilter, meetingSearch, pairParam, selectedPair, showArchived]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      void load(false);
    }, 150);
    return () => window.clearTimeout(t);
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => load(true), 20000);
    return () => window.clearInterval(id);
  }, [load]);

  useEffect(() => {
    void loadConversation(selectedPair);
  }, [loadConversation, selectedPair]);

  useRefreshOnAgentTurn(() => void load(true));

  const openHandoff = useCallback(async (handoffId: string) => {
    setSelectedId(handoffId);
    setDetailLoading(true);
    try {
      setSelectedHandoff(await api.getAgentHandoff(handoffId));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const refreshSelected = useCallback(async () => {
    await load(true);
    await loadConversation(selectedPair);
    if (selectedId) {
      await openHandoff(selectedId);
    }
  }, [load, loadConversation, openHandoff, selectedId, selectedPair]);

  const nameOf = useCallback(
    (id: string) => names[id] || (id ? id.replace(/-/g, " ") : "—"),
    [names],
  );

  const agentIds = useMemo(() => {
    const set = new Set<string>();
    for (const msg of feedMessages) {
      if (msg.from && !["human", "human-web"].includes(msg.from)) set.add(msg.from);
      if (msg.to && !["human", "human-web"].includes(msg.to)) set.add(msg.to);
    }
    for (const h of handoffs) {
      if (h.fromAgentId) set.add(h.fromAgentId);
      if (h.toAgentId) set.add(h.toAgentId);
    }
    return [...set];
  }, [feedMessages, handoffs]);

  const handoffFeed = useMemo(() => {
    const f = agentFilter
      ? handoffs.filter((h) => h.fromAgentId === agentFilter || h.toAgentId === agentFilter)
      : handoffs;
    return [...f].sort(
      (a, b) => new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime(),
    );
  }, [handoffs, agentFilter]);

  const sendChannelMessage = useCallback(
    async (body: { toAgentId: string; text: string; priority: "low" | "normal" | "high" | "urgent" }) => {
      await api.sendCommsMessage({
        fromAgentId: "human-web",
        toAgentId: body.toAgentId,
        text: body.text,
        priority: body.priority,
      });
      await load(true);
      await loadConversation(selectedPair);
    },
    [load, loadConversation, selectedPair],
  );

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 pb-16">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-foreground" />
            <h1 className="text-lg font-semibold text-foreground">Comms</h1>
          </div>
          <p className="text-sm text-muted-foreground">Meeting Room, agent channels, and handoff threads.</p>
        </div>
        <Button variant="ghost" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </Button>
      </header>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Couldn't load comms: {error}
        </div>
      ) : (
        <Tabs defaultValue="meeting-room">
          {(active, setActive) => (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <TabsList>
                  <TabsTrigger active={active === "meeting-room"} value="meeting-room" onClick={() => setActive("meeting-room")}>
                    <MessageSquare className="mr-1 h-3.5 w-3.5" />
                    Meeting Room
                  </TabsTrigger>
                  <TabsTrigger active={active === "channels"} value="channels" onClick={() => setActive("channels")}>
                    <Users className="mr-1 h-3.5 w-3.5" />
                    Active Channels
                    {conversationChannels.length > 0 && (
                      <span className="ml-1.5 rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">
                        {conversationChannels.length}
                      </span>
                    )}
                  </TabsTrigger>
                  <TabsTrigger active={active === "handoffs"} value="handoffs" onClick={() => setActive("handoffs")}>
                    <ListTodo className="mr-1 h-3.5 w-3.5" />
                    Handoffs
                  </TabsTrigger>
                </TabsList>
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => selectAgentFilter("")}
                    className={cn(
                      "h-7 rounded-md border px-2.5 text-[11px] font-medium transition-colors",
                      agentFilter === "" ? "border-foreground/20 bg-secondary text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
                    )}
                  >
                    All
                  </button>
                  {agentIds.slice(0, 10).map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => selectAgentFilter(id)}
                      className={cn(
                        "h-7 rounded-md border px-2.5 text-[11px] font-medium capitalize transition-colors",
                        agentFilter === id ? "border-foreground/20 bg-secondary text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {nameOf(id)}
                    </button>
                  ))}
                  {loading && agentIds.length === 0 && (
                    <>
                      <Skeleton className="h-7 w-16 rounded-md" />
                      <Skeleton className="h-7 w-20 rounded-md" />
                      <Skeleton className="h-7 w-16 rounded-md" />
                    </>
                  )}
                </div>
              </div>

              {active === "meeting-room" && (
                <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
                  <div className="space-y-3">
                    <div className="relative">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <input
                        value={meetingSearch}
                        onChange={(event) => setMeetingSearch(event.target.value)}
                        placeholder="Search messages..."
                        className="h-9 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-foreground/30"
                      />
                    </div>
                    <CommsFeedList
                      messages={feedMessages}
                      loading={loading}
                      nameOf={nameOf}
                      onOpenPair={(pair) => {
                        openPair(pair);
                        setActive("channels");
                      }}
                      onOpenHandoff={(id) => {
                        void openHandoff(id);
                        setActive("handoffs");
                      }}
                    />
                  </div>
                  <div className="space-y-3">
                    <HandoffComposer
                      agents={agents}
                      loading={loading}
                      onCreated={(handoff) => {
                        void load(true);
                        openPair([handoff.fromAgentId, handoff.toAgentId].sort().join("--"));
                        void openHandoff(handoff.id);
                      }}
                    />
                    <Card>
                      <CardContent className="space-y-2 p-3">
                        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                          Delivery
                        </span>
                        {loading && deliveryChannels.length === 0 ? (
                          <div className="space-y-1.5">
                            <Skeleton className="h-[2.625rem] w-full rounded-md" />
                            <Skeleton className="h-[2.625rem] w-full rounded-md" />
                          </div>
                        ) : deliveryChannels.length === 0 ? (
                          <p className="text-[11px] italic text-muted-foreground/70">No delivery channels connected.</p>
                        ) : (
                          <ul className="space-y-1.5">
                            {deliveryChannels.slice(0, 8).map((c) => (
                              <li key={`${c.platform}:${c.id}`} className="flex items-center gap-2 rounded-md border border-border bg-card/40 p-2">
                                <Hash className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                                <div className="min-w-0">
                                  <p className="truncate text-xs font-medium text-foreground/90">{c.name}</p>
                                  <p className="text-[10px] text-muted-foreground">{c.platform}{c.type ? ` · ${c.type}` : ""}</p>
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                </div>
              )}

              {active === "channels" && (
                <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <input
                          type="checkbox"
                          checked={showArchived}
                          onChange={(event) => setShowArchived(event.target.checked)}
                          className="accent-foreground"
                        />
                        Archived
                      </label>
                    </div>
                    <div className="relative">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <input
                        value={channelSearch}
                        onChange={(event) => setChannelSearch(event.target.value)}
                        placeholder="Filter channels..."
                        className="h-9 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-foreground/30"
                      />
                    </div>
                    <ChannelListPanel
                      channels={conversationChannels}
                      loading={loading}
                      selectedPair={selectedPair}
                      query={channelSearch}
                      nameOf={nameOf}
                      onSelect={openPair}
                    />
                  </div>
                  <ChannelTranscript
                    conversation={conversation}
                    loading={conversationLoading}
                    sortOrder={sortOrder}
                    nameOf={nameOf}
                    onToggleSort={() => setSortOrder((v) => (v === "asc" ? "desc" : "asc"))}
                    onSend={sendChannelMessage}
                    onOpenHandoff={(id) => {
                      void openHandoff(id);
                      setActive("handoffs");
                    }}
                  />
                </div>
              )}

              {active === "handoffs" && (
                <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
                  <div className="space-y-3">
                    <HandoffComposer
                      agents={agents}
                      loading={loading}
                      onCreated={(handoff) => {
                        void load(true);
                        void openHandoff(handoff.id);
                      }}
                    />
                    {loading && handoffFeed.length === 0 ? (
                      <ListSkeleton rows={6} />
                    ) : handoffFeed.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
                        No handoffs yet.
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {handoffFeed.map((h) => (
                          <HandoffRow
                            key={h.id}
                            h={h}
                            nameOf={nameOf}
                            selected={selectedId === h.id}
                            onOpen={() => void openHandoff(h.id)}
                          />
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="space-y-2">
                    <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                      Thread
                    </span>
                    <HandoffThread
                      handoff={selectedHandoff}
                      loading={detailLoading}
                      nameOf={nameOf}
                      onClose={() => {
                        setSelectedId(null);
                        setSelectedHandoff(null);
                      }}
                      onChanged={() => void refreshSelected()}
                    />
                  </div>
                </div>
              )}
            </>
          )}
        </Tabs>
      )}
    </div>
  );
}
