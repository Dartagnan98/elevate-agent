import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Activity, CheckSquare, Loader2, RotateCcw, Send, X as CloseIcon, StickyNote } from "lucide-react";
import { api } from "@/lib/api";
import type { ThreadContextMessage, ThreadContextResponse } from "@/lib/api";
import type { SourceInboxDraft } from "@/lib/api-types";
import type { HubData } from "../RealEstateHubPages";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListSkeleton, Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { LeadStatusControl } from "./_shared/lead-status-control";

type ThreadDrawerExtras = { skippedDraft?: SourceInboxDraft };
type ThreadDrawerTarget =
  | { sourceId: string; threadId: string; extras?: ThreadDrawerExtras }
  | null;

const ThreadDrawerContext = createContext<{
  openThread: (
    sourceId: string,
    threadId: string,
    extras?: ThreadDrawerExtras,
  ) => void;
} | null>(null);

export function useThreadDrawer() {
  return useContext(ThreadDrawerContext);
}

export function ThreadDrawerProvider({
  children,
  data,
}: {
  children: ReactNode;
  data: HubData;
}) {
  const [target, setTarget] = useState<ThreadDrawerTarget>(null);
  const openThread = useCallback(
    (sourceId: string, threadId: string, extras?: ThreadDrawerExtras) => {
      setTarget({ sourceId, threadId, extras });
    },
    [],
  );
  const close = useCallback(() => setTarget(null), []);
  const ctx = useMemo(() => ({ openThread }), [openThread]);
  return (
    <ThreadDrawerContext.Provider value={ctx}>
      {children}
      {target && <ThreadDrawer data={data} target={target} onClose={close} />}
    </ThreadDrawerContext.Provider>
  );
}

function fmtMessageTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function ThreadMessageBubble({ message }: { message: ThreadContextMessage }) {
  const inbound = message.direction !== "outbound";
  return (
    <div className={cn("flex flex-col gap-1.5", inbound ? "items-start" : "items-end")}>
      <div
        className={cn(
          "max-w-[82%] rounded-lg px-3.5 py-2.5 text-[0.875rem] leading-[1.45] whitespace-pre-wrap break-words text-foreground",
          inbound
            ? "bg-background border border-border"
            : "bg-primary/15 border border-primary/45",
        )}
      >
        {message.text || <span className="text-foreground/55 italic">(no text)</span>}
      </div>
      <div
        className="flex items-center gap-1.5 text-[0.68rem] uppercase tracking-[0.08em] text-foreground/55"
        style={{ fontFamily: "var(--theme-font-mono)" }}
      >
        {message.sender && <span className="font-medium">{message.sender}</span>}
        {message.sender && message.timestamp && <span>·</span>}
        {message.timestamp && <span>{fmtMessageTimestamp(message.timestamp)}</span>}
      </div>
    </div>
  );
}

function ThreadDrawer({
  data,
  target,
  onClose,
}: {
  data: HubData;
  target: { sourceId: string; threadId: string; extras?: ThreadDrawerExtras };
  onClose: () => void;
}) {
  const skippedDraft = target.extras?.skippedDraft;
  const [context, setContext] = useState<ThreadContextResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getThreadContext(target.sourceId, target.threadId);
      setContext(result);
      setReply(result.pendingDraft?.draftText ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [target.sourceId, target.threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  useLayoutEffect(() => {
    if (!loading && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [loading, context?.messages.length]);

  const sendDraft = useCallback(
    async (action: "approve" | "skip") => {
      if (!context?.pendingDraft) return;
      setSubmitting(true);
      try {
        const nextInbox = await api.updateSourceInboxDraft(
          context.pendingDraft.sourceId,
          context.pendingDraft.taskId,
          action,
          reply,
        );
        data.setSourceInbox(nextInbox);
        onClose();
      } catch (err) {
        window.alert(`Failed to ${action} draft: ${err instanceof Error ? err.message : String(err)}`);
      } finally {
        setSubmitting(false);
      }
    },
    [context?.pendingDraft, data, onClose, reply],
  );

  const restoreSkippedDraft = useCallback(async () => {
    if (!skippedDraft || restoring) return;
    setRestoring(true);
    try {
      const nextInbox = await api.updateSourceInboxDraft(
        skippedDraft.sourceId,
        skippedDraft.taskId,
        "restore",
        skippedDraft.draftText,
      );
      data.setSourceInbox(nextInbox);
      onClose();
    } catch (err) {
      window.alert(`Failed to restore skipped draft: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRestoring(false);
    }
  }, [data, onClose, restoring, skippedDraft]);

  const meta = context?.meta;
  const sends = context?.sends ?? [];
  const messages = context?.messages ?? [];

  const profile = useMemo(() => {
    const profiles = data.sourceInbox?.profiles ?? [];
    const composite = `${target.sourceId}:${target.threadId}`;
    for (const p of profiles) {
      for (const key of p.threadIds ?? []) {
        if (!key) continue;
        if (key === composite) return p;
        const colonAt = key.indexOf(":");
        if (colonAt >= 0 && key.slice(colonAt + 1) === target.threadId) return p;
      }
    }
    return null;
  }, [data.sourceInbox?.profiles, target.sourceId, target.threadId]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center animate-[fade-in_120ms_ease-out] sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Close thread"
        onClick={onClose}
        className="absolute inset-0 z-0 bg-background/80"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 flex h-full w-full flex-col bg-card shadow-[0_24px_90px_rgba(0,0,0,0.32)] sm:h-[calc(100vh-3rem)] sm:max-h-[calc(100vh-3rem)] sm:min-h-[640px] sm:w-full sm:max-w-[56rem] sm:rounded-md sm:border sm:border-border lg:max-w-[68rem] xl:max-w-[80rem]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="truncate text-[1.05rem] font-semibold leading-tight text-foreground">
              {context?.personName ?? "Loading thread..."}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {context?.source?.label && (
                <Badge
                  variant="outline"
                  className="border-border text-foreground/85 text-[0.7rem] font-medium"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.source.label}
                </Badge>
              )}
              {context?.source?.ownerAgent && (
                <Badge
                  variant="outline"
                  className="border-border text-foreground/85 text-[0.7rem] font-medium"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.source.ownerAgent}
                </Badge>
              )}
              {meta?.label && (
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[0.7rem] font-semibold",
                    meta.label === "hot" && "border-destructive/60 bg-destructive/10 text-destructive",
                    meta.label === "warm" && "border-warning/60 bg-warning/10 text-warning",
                    meta.label === "cold" && "border-border text-foreground/75",
                    meta.label === "dead" && "border-border/60 text-foreground/55",
                  )}
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {meta.label} {typeof meta.score === "number" ? meta.score : ""}
                </Badge>
              )}
              {context && (
                <span
                  className="text-[0.7rem] font-medium uppercase tracking-[0.08em] text-foreground/65"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  {context.messageCount} {context.messageCount === 1 ? "message" : "messages"}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {profile && (
              <LeadStatusControl
                profileId={profile.id}
                status={profile.status}
                onChanged={(nextInbox) => {
                  if (nextInbox) data.setSourceInbox(nextInbox);
                }}
                selectClassName="w-36"
                selectButtonClassName="h-8 px-2 text-xs"
              />
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              aria-label="Close thread drawer"
              title="Close"
              className="text-foreground/75 hover:text-foreground"
            >
              <CloseIcon className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col border-r border-border">
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5">
              {skippedDraft && (
                <div className="mb-4 rounded-md border border-warning/55 bg-warning/10 px-3.5 py-3">
                  <div
                    className="mb-1.5 flex items-center justify-between text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-warning"
                    style={{ fontFamily: "var(--theme-font-mono)" }}
                  >
                    <span>Skipped draft{skippedDraft.skippedAt ? ` · ${fmtMessageTimestamp(skippedDraft.skippedAt)}` : ""}</span>
                    <span className="text-foreground/65">{skippedDraft.channel}</span>
                  </div>
                  {skippedDraft.context && (
                    <p className="mb-2 line-clamp-3 text-[0.78rem] leading-5 text-foreground/70">
                      <span
                        className="mr-1.5 uppercase tracking-[0.08em] text-foreground/55"
                        style={{ fontFamily: "var(--theme-font-mono)", fontSize: "0.65rem" }}
                      >
                        Context:
                      </span>
                      {skippedDraft.context}
                    </p>
                  )}
                  <p className="whitespace-pre-wrap break-words text-sm leading-5 text-foreground">
                    {skippedDraft.draftText || <span className="text-foreground/55 italic">(empty draft)</span>}
                  </p>
                  <div className="mt-2.5 flex justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void restoreSkippedDraft()}
                      disabled={restoring}
                    >
                      {restoring ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      Restore
                    </Button>
                  </div>
                </div>
              )}
              {loading && (
                <ListSkeleton rows={4} />
              )}
              {error && (
                <div className="rounded-md border border-destructive/55 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
                  {error}
                </div>
              )}
              {!loading && !error && messages.length === 0 && !skippedDraft && (
                <p className="px-1 py-1 text-xs text-muted-foreground/80">No messages on file yet.</p>
              )}
              {!loading && messages.length > 0 && (
                <div className="space-y-4">
                  {messages.map((message) => (
                    <ThreadMessageBubble key={message.id || `${message.timestamp}-${message.text.slice(0, 12)}`} message={message} />
                  ))}
                </div>
              )}
            </div>

            {context?.pendingDraft && (
              <div className="border-t border-border bg-background/60 px-5 py-4">
                <div
                  className="mb-2 flex items-center justify-between text-[0.68rem] font-semibold uppercase tracking-[0.1em]"
                  style={{ fontFamily: "var(--theme-font-mono)" }}
                >
                  <span className="flex items-center gap-1.5 text-primary">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                    Draft reply · awaiting approval
                  </span>
                  <span className="text-foreground/65">{context.pendingDraft.channel}</span>
                </div>
                <textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  rows={4}
                  className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2.5 text-sm leading-5 text-foreground placeholder:text-foreground/45 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <div className="mt-2.5 flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void sendDraft("skip")}
                    disabled={submitting}
                    className="text-foreground/75 hover:text-foreground"
                  >
                    Skip
                  </Button>
                  <Button size="sm" onClick={() => void sendDraft("approve")} disabled={submitting || !reply.trim()}>
                    {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                    Send
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="min-h-0 overflow-y-auto bg-background/40 px-5 py-5">
            <ThreadContextSidebar context={context} loading={loading} sends={sends} />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function ThreadContextSidebar({
  context,
  loading,
  sends,
}: {
  context: ThreadContextResponse | null;
  loading: boolean;
  sends: ThreadContextResponse["sends"];
}) {
  if (loading || !context) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-3 w-28" />
        <ListSkeleton rows={3} />
      </div>
    );
  }
  const meta = context.meta;
  const lead = context.lead;
  const activity = context.activity ?? [];
  const notes = context.notes ?? [];
  const tasks = context.tasks ?? [];
  const sectionLabel =
    "font-mono-ui flex items-center gap-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-foreground/70";
  const sectionClass = "py-5 first:pt-0 last:pb-0";
  const displayScore = meta?.score ?? lead?.score ?? null;
  const scoreLabel = meta?.label ?? (lead?.stage || lead?.leadSource || null);
  const hasContact = Boolean(lead && (lead.emails.length > 0 || lead.phones.length > 0));
  return (
    <div className="divide-y divide-border/40">
      <section className={sectionClass}>
        <h4 className={sectionLabel}>Lead score</h4>
        {displayScore !== null ? (
          <>
            <div className="mt-2 flex items-baseline gap-2.5">
              <span className="text-[2.25rem] font-semibold leading-none tracking-tight text-primary">
                {displayScore}
              </span>
              {scoreLabel && (
                <span className="font-mono-ui text-[0.7rem] font-semibold uppercase tracking-[0.1em] text-foreground/70">
                  {scoreLabel}
                </span>
              )}
            </div>
            {meta?.reason && (
              <p className="mt-2.5 text-[0.8rem] leading-[1.5] text-foreground">{meta.reason}</p>
            )}
            {!meta && lead?.summary && (
              <p className="mt-2.5 text-[0.8rem] leading-[1.5] text-foreground">{lead.summary}</p>
            )}
            {lead && (lead.leadSource || lead.assignedUser || lead.tags.length > 0) && (
              <div className="mt-2.5 space-y-1.5">
                {lead.leadSource && (
                  <div className="flex items-center gap-1.5 text-[0.72rem] text-foreground/75">
                    <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground/80">
                      source
                    </span>
                    <span>{lead.leadSource}</span>
                  </div>
                )}
                {lead.assignedUser && (
                  <div className="flex items-center gap-1.5 text-[0.72rem] text-foreground/75">
                    <span className="font-mono-ui text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground/80">
                      owner
                    </span>
                    <span>{lead.assignedUser}</span>
                  </div>
                )}
                {lead.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {lead.tags
                      .filter((t) => t !== "crm-lead" && !t.endsWith("-crm"))
                      .slice(0, 6)
                      .map((tag) => (
                        <span
                          key={tag}
                          className="font-mono-ui inline-flex items-center rounded-full border border-border/60 bg-background px-2 py-0.5 text-[0.65rem] font-medium text-foreground/75"
                        >
                          {tag}
                        </span>
                      ))}
                  </div>
                )}
              </div>
            )}
            {(meta?.scoredBy || meta?.scoredAt) && (
              <div className="font-mono-ui mt-2.5 text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                {meta.scoredBy ? `by ${meta.scoredBy}` : null}
                {meta.scoredBy && meta.scoredAt ? " · " : ""}
                {meta.scoredAt ? fmtMessageTimestamp(meta.scoredAt) : ""}
              </div>
            )}
          </>
        ) : (
          <p className="mt-2 text-[0.8rem] text-muted-foreground">Not yet scored.</p>
        )}
      </section>

      {hasContact && lead && (
        <section className={sectionClass}>
          <h4 className={sectionLabel}>Contact</h4>
          <div className="mt-2 space-y-1">
            {lead.phones.slice(0, 3).map((phone) => (
              <div key={phone} className="text-[0.8rem] text-foreground">
                {phone}
              </div>
            ))}
            {lead.emails.slice(0, 3).map((email) => (
              <div key={email} className="truncate text-[0.8rem] text-foreground">
                {email}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={sectionClass}>
        <h4 className={sectionLabel}>
          <StickyNote className="h-3 w-3" />
          Notes
          {notes.length > 0 && (
            <span className="font-mono-ui text-[0.62rem] font-medium text-muted-foreground/70">
              {notes.length}
            </span>
          )}
        </h4>
        {notes.length === 0 ? (
          <p className="mt-2 text-[0.8rem] leading-[1.5] text-muted-foreground">
            {lead?.summary || "No notes yet."}
          </p>
        ) : (
          <ul className="mt-2 space-y-2.5">
            {notes.slice(0, 8).map((note) => (
              <li key={note.id} className="rounded-md border border-border/40 bg-background/60 px-3 py-2">
                <div className="font-mono-ui flex items-center justify-between gap-2 text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  <span>{note.author || "note"}</span>
                  {note.timestamp && (
                    <span className="text-muted-foreground/70">{fmtMessageTimestamp(note.timestamp)}</span>
                  )}
                </div>
                <p className="mt-1 whitespace-pre-line text-[0.8rem] leading-[1.5] text-foreground">
                  {note.summary}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {tasks.length > 0 && (
        <section className={sectionClass}>
          <h4 className={sectionLabel}>
            <CheckSquare className="h-3 w-3" />
            Tasks
            <span className="font-mono-ui text-[0.62rem] font-medium text-muted-foreground/70">
              {tasks.length}
            </span>
          </h4>
          <ul className="mt-2 space-y-1.5">
            {tasks.slice(0, 6).map((task) => (
              <li key={task.id} className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                    task.status === "done"
                      ? "bg-success"
                      : task.status === "in_progress"
                        ? "bg-primary"
                        : "bg-muted-foreground/60"
                  )}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="text-[0.8rem] leading-[1.4] text-foreground">
                    {task.title}
                  </div>
                  {(task.dueAt || task.status) && (
                    <div className="font-mono-ui mt-0.5 flex items-center gap-1.5 text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground">
                      <span>{task.status.replace(/_/g, " ")}</span>
                      {task.dueAt && (
                        <>
                          <span aria-hidden>·</span>
                          <span>due {fmtMessageTimestamp(task.dueAt)}</span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={sectionClass}>
        <h4 className={sectionLabel}>
          <Activity className="h-3 w-3" />
          Property activity
          {activity.length > 0 && (
            <span className="font-mono-ui text-[0.62rem] font-medium text-muted-foreground/70">
              {activity.length}
            </span>
          )}
        </h4>
        {activity.length === 0 ? (
          <p className="mt-2 text-[0.8rem] leading-[1.5] text-muted-foreground">
            No activity logged yet.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border/30">
            {activity.slice(0, 8).map((event) => {
              const label = (event.subtype || event.type).replace(/_/g, " ");
              return (
                <li key={event.id} className="py-2.5 first:pt-0 last:pb-0">
                  <div className="font-mono-ui flex items-center justify-between gap-2 text-[0.66rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    <span>{label}</span>
                    {event.timestamp && (
                      <span className="text-muted-foreground/80">{fmtMessageTimestamp(event.timestamp)}</span>
                    )}
                  </div>
                  {(event.title || event.summary) && (
                    <p className="mt-1 line-clamp-2 text-[0.8rem] leading-[1.45] text-foreground">
                      {event.title || event.summary}
                    </p>
                  )}
                  {event.address && (
                    <p className="font-mono-ui mt-0.5 text-[0.66rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                      {event.address}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={sectionClass}>
        <h4 className={sectionLabel}>Send history</h4>
        {sends.length === 0 ? (
          <p className="mt-2 text-[0.8rem] text-muted-foreground">No prior sends.</p>
        ) : (
          <ul className="mt-2 divide-y divide-border/30">
            {sends.slice(0, 8).map((send) => (
              <li key={send.id} className="py-2.5 first:pt-0 last:pb-0">
                <div className="font-mono-ui flex items-center justify-between gap-2 text-[0.66rem] font-semibold uppercase tracking-[0.08em]">
                  <span className="text-foreground/75">{send.channel ?? "send"}</span>
                  <span
                    className={cn(
                      send.status === "sent" || send.status === "delivered"
                        ? "text-success"
                        : send.status === "failed"
                          ? "text-destructive"
                          : "text-muted-foreground",
                    )}
                  >
                    {send.status ?? "unknown"}
                  </span>
                </div>
                {(() => {
                  // Codex audit P2 (2026-05-05): older outreach_db rows
                  // store the body at payload.draft_text; future
                  // operational.db rows may put it at the top level.
                  // Fall back through every shape we've shipped so the
                  // history doesn't render blank.
                  const body =
                    (send.payload?.text as string | undefined) ||
                    (send.payload?.draft_text as string | undefined) ||
                    ((send as { draftText?: string }).draftText) ||
                    ((send as { text?: string }).text);
                  return body ? (
                    <p className="mt-1 line-clamp-3 text-[0.8rem] leading-[1.45] text-foreground">
                      {String(body)}
                    </p>
                  ) : null;
                })()}
                {send.createdAt && (
                  <div className="font-mono-ui mt-1 text-[0.65rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                    {fmtMessageTimestamp(send.createdAt)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
