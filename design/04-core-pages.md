# Elevate: Core Pages
Sessions, Agent Hub, Cron, Skills, Config, Analytics, Logs, Env, Project, Docs, Desktop Setup.

---
## `src/pages/SessionsPage.tsx`
```tsx
import {
  useEffect,
  useLayoutEffect,
  useState,
  useCallback,
  useRef,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageSquare,
  Search,
  Trash2,
  Clock,
  Terminal,
  Globe,
  MessageCircle,
  Hash,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  SessionInfo,
  SessionMessage,
  SessionSearchResult,
  StatusResponse,
} from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Markdown } from "@/components/Markdown";
import { PlatformsCard } from "@/components/PlatformsCard";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { Input } from "@/components/ui/input";
import { useSystemActions } from "@/contexts/useSystemActions";
import { useToast } from "@/hooks/useToast";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { isDashboardEmbeddedChatEnabled } from "@/lib/dashboard-flags";

const SOURCE_CONFIG: Record<string, { icon: typeof Terminal; color: string }> =
  {
    cli: { icon: Terminal, color: "text-primary" },
    telegram: { icon: MessageCircle, color: "text-info" },
    discord: { icon: Hash, color: "text-accent" },
    slack: { icon: MessageSquare, color: "text-success" },
    whatsapp: { icon: Globe, color: "text-success" },
    cron: { icon: Clock, color: "text-warning" },
  };

/** Compact human format for token counts: 1234 -> "1.2K", 1_500_000 -> "1.5M". */
function formatTokenCount(n: number): string {
  if (!n || n < 0) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) {
    const k = n / 1000;
    return `${k >= 10 ? Math.round(k) : k.toFixed(1)}K`;
  }
  const m = n / 1_000_000;
  return `${m >= 10 ? Math.round(m) : m.toFixed(1)}M`;
}

/** Render an FTS5 snippet with highlighted matches.
 *  The backend wraps matches in >>> and <<< delimiters. */
function SnippetHighlight({ snippet }: { snippet: string }) {
  const parts: React.ReactNode[] = [];
  const regex = />>>(.*?)<<</g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = regex.exec(snippet)) !== null) {
    if (match.index > last) {
      parts.push(snippet.slice(last, match.index));
    }
    parts.push(
      <mark key={i++} className="bg-card text-warning px-0.5">
        {match[1]}
      </mark>,
    );
    last = regex.lastIndex;
  }
  if (last < snippet.length) {
    parts.push(snippet.slice(last));
  }
  return (
    <p className="text-xs text-muted-foreground/80 truncate max-w-lg mt-0.5">
      {parts}
    </p>
  );
}

function ToolCallBlock({
  toolCall,
}: {
  toolCall: { id: string; function: { name: string; arguments: string } };
}) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();

  let args = toolCall.function.arguments;
  try {
    args = JSON.stringify(JSON.parse(args), null, 2);
  } catch {
    // keep as-is
  }

  return (
    <div className="mt-2 rounded-md border border-border bg-card">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-warning cursor-pointer hover:bg-muted transition-colors"
        onClick={() => setOpen(!open)}
        aria-label={`${open ? t.common.collapse : t.common.expand} tool call ${toolCall.function.name}`}
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span className="font-mono-ui font-medium">
          {toolCall.function.name}
        </span>
        <span className="text-warning/50 ml-auto">{toolCall.id}</span>
      </button>
      {open && (
        <pre className="border-t border-border px-3 py-2 text-xs text-warning/80 overflow-x-auto whitespace-pre-wrap font-mono">
          {args}
        </pre>
      )}
    </div>
  );
}

function MessageBubble({
  msg,
  highlight,
}: {
  msg: SessionMessage;
  highlight?: string;
}) {
  const { t } = useI18n();

  const ROLE_STYLES: Record<
    string,
    { bg: string; text: string; label: string }
  > = {
    user: {
      bg: "bg-card",
      text: "text-primary",
      label: t.sessions.roles.user,
    },
    assistant: {
      bg: "bg-card",
      text: "text-success",
      label: t.sessions.roles.assistant,
    },
    system: {
      bg: "bg-muted",
      text: "text-muted-foreground",
      label: t.sessions.roles.system,
    },
    tool: {
      bg: "bg-card",
      text: "text-warning",
      label: t.sessions.roles.tool,
    },
  };

  const style = ROLE_STYLES[msg.role] ?? ROLE_STYLES.system;
  const label = msg.tool_name
    ? `${t.sessions.roles.tool}: ${msg.tool_name}`
    : style.label;

  // Check if any search term appears as a prefix of any word in content
  const isHit = (() => {
    if (!highlight || !msg.content) return false;
    const content = msg.content.toLowerCase();
    const terms = highlight.toLowerCase().split(/\s+/).filter(Boolean);
    return terms.some((term) => content.includes(term));
  })();

  // Split search query into terms for inline highlighting
  const highlightTerms =
    isHit && highlight ? highlight.split(/\s+/).filter(Boolean) : undefined;

  return (
    <div
      className={`${style.bg} p-3 ${isHit ? "ring-1 ring-warning/40" : ""}`}
      data-search-hit={isHit || undefined}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`text-xs font-semibold ${style.text}`}>{label}</span>
        {isHit && (
          <Badge variant="warning" className="text-[9px] py-0 px-1.5">
            {t.common.match}
          </Badge>
        )}
        {msg.timestamp && (
          <span className="text-[10px] text-muted-foreground">
            {timeAgo(msg.timestamp)}
          </span>
        )}
      </div>
      {msg.content &&
        (msg.role === "system" ? (
          <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
            {msg.content}
          </div>
        ) : (
          <Markdown content={msg.content} highlightTerms={highlightTerms} />
        ))}
      {msg.tool_calls && msg.tool_calls.length > 0 && (
        <div className="mt-1">
          {msg.tool_calls.map((tc) => (
            <ToolCallBlock key={tc.id} toolCall={tc} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Message list with auto-scroll to first search hit. */
function MessageList({
  messages,
  highlight,
}: {
  messages: SessionMessage[];
  highlight?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!highlight || !containerRef.current) return;
    // Scroll to first hit after render
    const timer = setTimeout(() => {
      const hit = containerRef.current?.querySelector("[data-search-hit]");
      if (hit) {
        hit.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [messages, highlight]);

  return (
    <div
      ref={containerRef}
      className="flex flex-col gap-3 min-h-0 flex-1 overflow-y-auto pr-2"
    >
      {messages.map((msg, i) => (
        <MessageBubble key={i} msg={msg} highlight={highlight} />
      ))}
    </div>
  );
}

function SessionRow({
  session,
  snippet,
  searchQuery,
  isExpanded,
  onOpenChat,
  onToggleDetails,
  onDelete,
  resumeInChatEnabled,
}: {
  session: SessionInfo;
  snippet?: string;
  searchQuery?: string;
  isExpanded: boolean;
  onOpenChat: () => void;
  onToggleDetails: () => void;
  onDelete: () => void;
  resumeInChatEnabled: boolean;
}) {
  const [messages, setMessages] = useState<SessionMessage[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  useEffect(() => {
    if (isExpanded && messages === null && !loading) {
      setLoading(true);
      api
        .getSessionMessages(session.id)
        .then((resp) => setMessages(resp.messages))
        .catch((err) => setError(String(err)))
        .finally(() => setLoading(false));
    }
  }, [isExpanded, session.id, messages, loading]);

  const sourceInfo = (session.source
    ? SOURCE_CONFIG[session.source]
    : null) ?? { icon: Globe, color: "text-muted-foreground" };
  const SourceIcon = sourceInfo.icon;
  const hasTitle = session.title && session.title !== "Untitled";

  return (
    <div
      id={`session-row-${session.id}`}
      className="overflow-hidden rounded-md border border-border bg-card transition-colors"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between p-3 text-left cursor-pointer hover:bg-secondary/30 transition-colors"
        onClick={onOpenChat}
        title={
          resumeInChatEnabled
            ? t.sessions.resumeInChat
            : "Start Agent Hub with chat enabled"
        }
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className={`shrink-0 ${sourceInfo.color}`}>
            <SourceIcon className="h-4 w-4" />
          </div>
          <div className="flex flex-col gap-0.5 min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={`text-sm truncate pr-2 ${hasTitle ? "font-medium" : "text-muted-foreground italic"}`}
              >
                {hasTitle
                  ? session.title
                  : session.preview
                    ? session.preview.slice(0, 60)
                    : t.sessions.untitledSession}
              </span>
              {session.is_active && (
                <Badge variant="success" className="text-[10px] shrink-0">
                  <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                  {t.common.live}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="truncate max-w-[120px] sm:max-w-[180px]">
                {(session.model ?? t.common.unknown).split("/").pop()}
              </span>
              <span className="text-border">&#183;</span>
              <span>
                {session.message_count} {t.common.msgs}
              </span>
              {session.tool_call_count > 0 && (
                <>
                  <span className="text-border">&#183;</span>
                  <span>
                    {session.tool_call_count} {t.common.tools}
                  </span>
                </>
              )}
              {(session.input_tokens > 0 || session.output_tokens > 0) && (
                <>
                  <span className="text-border">&#183;</span>
                  <span title={`${session.input_tokens.toLocaleString()} in / ${session.output_tokens.toLocaleString()} out`}>
                    {formatTokenCount(session.input_tokens)} in &middot; {formatTokenCount(session.output_tokens)} out
                  </span>
                </>
              )}
              <span className="text-border">&#183;</span>
              <span>{timeAgo(session.last_active)}</span>
            </div>
            {snippet && <SnippetHighlight snippet={snippet} />}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Badge variant="outline" className="text-[10px]">
            {session.source ?? "local"}
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-success"
            aria-label={t.sessions.resumeInChat}
            title={t.sessions.resumeInChat}
            onClick={(e) => {
              e.stopPropagation();
              onOpenChat();
            }}
          >
            <MessageSquare className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            aria-label="Show session details"
            title="Show session details"
            onClick={(e) => {
              e.stopPropagation();
              onToggleDetails();
            }}
          >
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${
                isExpanded ? "rotate-180" : ""
              }`}
            />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-destructive"
            aria-label={t.sessions.deleteSession}
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </button>

      {isExpanded && (
        <div className="border-t border-border bg-background p-4">
          {loading && (
            <p className="px-1 py-1 text-xs text-muted-foreground/80">
              {t.common.loading}
            </p>
          )}
          {error && (
            <p className="px-1 py-1 text-xs text-destructive">{error}</p>
          )}
          {messages && messages.length === 0 && (
            <p className="px-1 py-1 text-xs text-muted-foreground/80">
              {t.sessions.noMessages}
            </p>
          )}
          {messages && messages.length > 0 && (
            <MessageList messages={messages} highlight={searchQuery} />
          )}
        </div>
      )}
    </div>
  );
}

function LinkedSessionPanel({
  onClose,
  session,
  sessionId,
}: {
  onClose: () => void;
  session?: SessionInfo | null;
  sessionId: string;
}) {
  const [messages, setMessages] = useState<SessionMessage[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const title =
    session?.title && session.title !== "Untitled"
      ? session.title
      : session?.preview?.slice(0, 80) || "Selected chat";

  useEffect(() => {
    let cancelled = false;
    setMessages(null);
    setError(null);
    setLoading(true);
    api
      .getSessionMessages(sessionId)
      .then((resp) => {
        if (!cancelled) setMessages(resp.messages);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return (
    <Card className="border-primary">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="truncate text-base">{title}</CardTitle>
            <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline" className="text-[10px]">
                {session?.source ?? "session"}
              </Badge>
              <span className="font-mono-ui">{sessionId}</span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            aria-label={t.common.close}
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading…</p>
        )}
        {error && (
          <p className="px-1 py-1 text-xs text-destructive">{error}</p>
        )}
        {messages && messages.length === 0 && (
          <p className="px-1 py-1 text-xs text-muted-foreground/80">
            {t.sessions.noMessages}
          </p>
        )}
        {messages && messages.length > 0 && <MessageList messages={messages} />}
      </CardContent>
    </Card>
  );
}

export default function SessionsPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<
    SessionSearchResult[] | null
  >(null);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);
  const logScrollRef = useRef<HTMLPreElement | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [overviewSessions, setOverviewSessions] = useState<SessionInfo[]>([]);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { setAfterTitle, setEnd } = usePageHeader();
  const { activeAction, actionStatus, dismissLog } = useSystemActions();
  const resumeInChatEnabled = isDashboardEmbeddedChatEnabled();
  const linkedSessionId = searchParams.get("session");
  const linkedSession = linkedSessionId
    ? sessions.find((s) => s.id === linkedSessionId) ??
      overviewSessions.find((s) => s.id === linkedSessionId) ??
      null
    : null;
  const clearLinkedSession = useCallback(() => {
    setExpandedId(null);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("session");
      return next;
    });
  }, [setSearchParams]);

  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      setEnd(null);
      return;
    }
    setAfterTitle(
      <Badge variant="secondary" className="text-xs tabular-nums">
        {total}
      </Badge>,
    );
    setEnd(
      <div className="relative w-full min-w-0 sm:max-w-xs">
        {searching ? (
          <div className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-primary border-t-transparent" />
        ) : (
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        )}
        <Input
          placeholder={t.sessions.searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 pr-7 pl-8 text-xs"
        />
        {search && (
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer text-muted-foreground hover:text-foreground"
            onClick={() => setSearch("")}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    loading,
    search,
    searching,
    setAfterTitle,
    setEnd,
    t.sessions.searchPlaceholder,
    total,
  ]);

  const loadSessions = useCallback((p: number) => {
    setLoading(true);
    api
      .getSessions(PAGE_SIZE, p * PAGE_SIZE)
      .then((resp) => {
        setSessions(resp.sessions);
        setTotal(resp.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSessions(page);
  }, [loadSessions, page]);

  useEffect(() => {
    const loadOverview = () => {
      api.getStatus().then(setStatus).catch(() => {});
      api
        .getSessions(50, 0, { includeTotal: false })
        .then((r) => setOverviewSessions(r.sessions))
        .catch(() => {});
    };
    loadOverview();
    const id = setInterval(loadOverview, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const el = logScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [actionStatus?.lines]);

  // Debounced FTS search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!search.trim()) {
      setSearchResults(null);
      setSearching(false);
      return;
    }

    setSearching(true);
    debounceRef.current = setTimeout(() => {
      api
        .searchSessions(search.trim())
        .then((resp) => setSearchResults(resp.results))
        .catch(() => setSearchResults(null))
        .finally(() => setSearching(false));
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [search]);

  const sessionDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        try {
          await api.deleteSession(id);
          setSessions((prev) => prev.filter((s) => s.id !== id));
          setTotal((prev) => prev - 1);
          if (expandedId === id) setExpandedId(null);
          showToast(t.sessions.sessionDeleted, "success");
        } catch {
          showToast(t.sessions.failedToDelete, "error");
          throw new Error("delete failed");
        }
      },
      [expandedId, showToast, t.sessions.sessionDeleted, t.sessions.failedToDelete],
    ),
  });

  const pendingSession = sessionDelete.pendingId
    ? sessions.find((s) => s.id === sessionDelete.pendingId)
    : null;

  const openSessionInChat = useCallback(
    (id: string) => {
      if (!resumeInChatEnabled) {
        setExpandedId(id);
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set("session", id);
          return next;
        });
        return;
      }
      navigate(`/chat?resume=${encodeURIComponent(id)}`);
    },
    [navigate, resumeInChatEnabled, setSearchParams],
  );

  useEffect(() => {
    if (!linkedSessionId) return;
    setExpandedId(linkedSessionId);
    const timer = window.setTimeout(() => {
      document
        .getElementById(`session-row-${linkedSessionId}`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [linkedSessionId, sessions]);

  // Build snippet map from search results (session_id → snippet)
  const snippetMap = new Map<string, string>();
  if (searchResults) {
    for (const r of searchResults) {
      snippetMap.set(r.session_id, r.snippet);
    }
  }

  // When searching, filter sessions to those with FTS matches;
  // when not searching, show all sessions
  const filtered = searchResults
    ? sessions.filter((s) => snippetMap.has(s.id))
    : sessions;

  const platformEntries = status
    ? Object.entries(status.gateway_platforms ?? {})
    : [];
  const recentSessions = overviewSessions
    .filter((s) => !s.is_active)
    .slice(0, 5);

  const alerts: { message: string; detail?: string }[] = [];
  if (status) {
    if (status.gateway_state === "startup_failed") {
      alerts.push({
        message: t.status.gatewayFailedToStart,
        detail: status.gateway_exit_reason ?? undefined,
      });
    }
    const failedPlatformEntries = platformEntries.filter(
      ([, info]) => info.state === "fatal" || info.state === "disconnected",
    );
    for (const [name, info] of failedPlatformEntries) {
      const stateLabel =
        info.state === "fatal"
          ? t.status.platformError
          : t.status.platformDisconnected;
      alerts.push({
        message: `${name.charAt(0).toUpperCase() + name.slice(1)} ${stateLabel}`,
        detail: info.error_message ?? undefined,
      });
    }
  }

  if (loading) {
    return <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading sessions…</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={sessionDelete.isOpen}
        onCancel={sessionDelete.cancel}
        onConfirm={sessionDelete.confirm}
        title={t.sessions.confirmDeleteTitle}
        description={
          pendingSession?.title && pendingSession.title !== "Untitled"
            ? `"${pendingSession.title}" — ${t.sessions.confirmDeleteMessage}`
            : t.sessions.confirmDeleteMessage
        }
        loading={sessionDelete.isDeleting}
      />

      {alerts.length > 0 && (
        <div className="rounded-md border border-border bg-card p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="flex flex-col gap-2 min-w-0">
              {alerts.map((alert, i) => (
                <div key={i}>
                  <p className="text-sm font-medium text-destructive">
                    {alert.message}
                  </p>
                  {alert.detail && (
                    <p className="text-xs text-destructive/70 mt-0.5">
                      {alert.detail}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeAction && (
        <div className="overflow-hidden rounded-md border border-border bg-card">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
              {actionStatus?.running ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-warning" />
              ) : actionStatus?.exit_code === 0 ? (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
              ) : actionStatus !== null ? (
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" />
              ) : (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
              )}

              <span className="truncate text-xs font-medium tracking-normal">
                {activeAction === "restart"
                  ? t.status.restartGateway
                  : t.status.updateElevate}
              </span>

              <Badge
                variant={
                  actionStatus?.running
                    ? "warning"
                    : actionStatus?.exit_code === 0
                      ? "success"
                      : actionStatus
                        ? "destructive"
                        : "outline"
                }
                className="text-[10px] shrink-0"
              >
                {actionStatus?.running
                  ? t.status.running
                  : actionStatus?.exit_code === 0
                    ? t.status.actionFinished
                    : actionStatus
                      ? `${t.status.actionFailed} (${actionStatus.exit_code ?? "?"})`
                      : t.common.loading}
              </Badge>
            </div>

            <button
              type="button"
              onClick={dismissLog}
              className="shrink-0 opacity-60 hover:opacity-100 cursor-pointer"
              aria-label={t.common.close}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <pre
            ref={logScrollRef}
            className="max-h-72 overflow-auto px-3 py-2 font-mono-ui text-[11px] leading-relaxed whitespace-pre-wrap break-all"
          >
            {actionStatus?.lines && actionStatus.lines.length > 0
              ? actionStatus.lines.join("\n")
              : t.status.waitingForOutput}
          </pre>
        </div>
      )}

      {linkedSessionId && (
        <LinkedSessionPanel
          key={linkedSessionId}
          sessionId={linkedSessionId}
          session={linkedSession}
          onClose={clearLinkedSession}
        />
      )}

      {platformEntries.length > 0 && status && (
        <PlatformsCard platforms={platformEntries} />
      )}

      {recentSessions.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">
                {t.status.recentSessions}
              </CardTitle>
            </div>
          </CardHeader>

          <CardContent className="grid gap-3">
            {recentSessions.map((s) => (
              <div
                key={s.id}
                className="flex w-full cursor-pointer flex-col gap-2 rounded-md border border-border p-3 transition-colors hover:bg-muted sm:flex-row sm:items-center sm:justify-between"
                onClick={() => openSessionInChat(s.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openSessionInChat(s.id);
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <div className="flex flex-col gap-1 min-w-0 w-full">
                  <span className="font-medium text-sm truncate">
                    {s.title ?? t.common.untitled}
                  </span>

                  <span className="text-xs text-muted-foreground truncate">
                    <span className="font-mono-ui">
                      {(s.model ?? t.common.unknown).split("/").pop()}
                    </span>{" "}
                    · {s.message_count} {t.common.msgs} ·{" "}
                    {timeAgo(s.last_active)}
                  </span>

                  {s.preview && (
                    <span className="text-xs text-muted-foreground/70 truncate">
                      {s.preview}
                    </span>
                  )}
                </div>

                <Badge
                  variant="outline"
                  className="text-[10px] shrink-0 self-start sm:self-center"
                >
                  <MessageSquare className="mr-1 h-3 w-3" />
                  {s.source ?? "local"}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {filtered.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          {search
            ? t.sessions.noMatch
            : `${t.sessions.noSessions} — ${t.sessions.startConversation}`}
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-1.5">
            {filtered.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                snippet={snippetMap.get(s.id)}
                searchQuery={search || undefined}
                isExpanded={expandedId === s.id}
                onOpenChat={() => openSessionInChat(s.id)}
                onToggleDetails={() =>
                  setExpandedId((prev) => (prev === s.id ? null : s.id))
                }
                onDelete={() => sessionDelete.requestDelete(s.id)}
                resumeInChatEnabled={resumeInChatEnabled}
              />
            ))}
          </div>

          {/* Pagination — hidden during search */}
          {!searchResults && total > PAGE_SIZE && (
            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-muted-foreground">
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)}{" "}
                {t.common.of} {total}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 w-7 p-0"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                  aria-label={t.sessions.previousPage}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-xs text-muted-foreground px-2">
                  {t.common.page} {page + 1} {t.common.of}{" "}
                  {Math.ceil(total / PAGE_SIZE)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 w-7 p-0"
                  disabled={(page + 1) * PAGE_SIZE >= total}
                  onClick={() => setPage((p) => p + 1)}
                  aria-label={t.sessions.nextPage}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

```

---
## `src/pages/AgentHubPage.tsx`
```tsx
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  Brain,
  KeyRound,
  Loader2,
  Play,
  RefreshCw,
  RotateCw,
  Save,
  Sparkles,
  Terminal,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { FullWindowAurora } from "@/components/FullWindowAurora";
import type {
  AgentHubAgent,
  AgentHubSnapshot,
  EnvVarInfo,
  HarnessSnapshot,
} from "@/lib/api";
import { cn, isoTimeAgo, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";
import {
  AgentConfigEditor,
  AgentTelegramLaneEditor,
  type AgentEditPatch,
  type SkillEntry,
  type ToolsetEntry,
} from "@/components/agent-hub/AgentConfigEditor";

const STATUS_COPY: Record<string, string> = {
  online: "Online",
  ready: "Ready",
  offline: "Offline",
  disabled: "Disabled",
  needs_model: "Needs model",
  needs_telegram: "Needs Telegram",
};

function envPlaceholder(
  envVars: Record<string, EnvVarInfo> | null,
  key: string,
  fallback: string,
) {
  const info = envVars?.[key];
  return info?.is_set && info.redacted_value ? info.redacted_value : fallback;
}

function agentTelegramEnvSegment(agentId: string) {
  const segment = agentId.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return segment || "AGENT";
}

function telegramFieldForAgent(agentId: string, label?: string) {
  const segment = agentTelegramEnvSegment(agentId);
  return {
    agentId,
    tokenKey: `ELEVATE_AGENT_${segment}_TELEGRAM_BOT_TOKEN`,
    key: `ELEVATE_AGENT_${segment}_TELEGRAM_CHANNEL`,
    label: label || agentId,
  };
}

const EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN";
const EXECUTIVE_TELEGRAM_CHANNEL_KEY = "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL";

function looksLikeTelegramBotToken(value: string) {
  const text = value.trim().replace(/^telegram:/i, "");
  return /^\d{6,}:[A-Za-z0-9_-]{20,}$/.test(text);
}


function AgentCard({
  agent,
  availableSkills,
  availableToolsets,
  availablePlatforms,
  savingConfig,
  onConfigSave,
  telegramBotTokenPlaceholder,
  telegramBotTokenValue,
  telegramLanePlaceholder,
  telegramLaneValue,
  onTelegramLaneSave,
  onTelegramBotTokenChange,
  onTelegramLaneChange,
  savingTelegram,
}: {
  agent: AgentHubAgent;
  availableSkills: SkillEntry[];
  availableToolsets: ToolsetEntry[];
  availablePlatforms: string[];
  savingConfig: boolean;
  onConfigSave: (patch: AgentEditPatch) => Promise<void>;
  telegramBotTokenPlaceholder?: string;
  telegramBotTokenValue?: string;
  telegramLanePlaceholder?: string;
  telegramLaneValue?: string;
  onTelegramLaneSave?: () => void;
  onTelegramBotTokenChange?: (value: string) => void;
  onTelegramLaneChange?: (value: string) => void;
  savingTelegram?: boolean;
}) {
  return (
    <div className="rounded-md p-2 hover:bg-muted">
      <div className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{agent.name}</span>
          </div>
          <span className={cn(
            "inline-flex items-center gap-1.5 text-xs",
            agent.status === "active" ? "text-muted-foreground" : "text-warning"
          )}>
            <span className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              agent.status === "active" ? "bg-success" : "bg-warning"
            )} />
            {STATUS_COPY[agent.status] ?? agent.status}
          </span>
        </div>
        <div className="text-xs text-muted-foreground">{agent.description || agent.role}</div>
      </div>
      <div className="mt-2 space-y-3">
        {(agent.active_session_count > 0 || agent.session_count > 0) && (
          <div className="flex items-baseline gap-3 text-xs text-muted-foreground">
            {agent.active_session_count > 0 && (
              <span className="inline-flex items-baseline gap-1 text-success">
                <span className="font-medium tabular-nums">{agent.active_session_count}</span>
                <span>active now</span>
              </span>
            )}
            {agent.session_count > 0 && (
              <span className="inline-flex items-baseline gap-1">
                <span className="tabular-nums">{agent.session_count}</span>
                <span>{agent.session_count === 1 ? "session" : "sessions"} total</span>
              </span>
            )}
          </div>
        )}
        <ChipRow icon={Terminal} items={agent.platforms} empty="No platforms" />
        <ChipRow icon={Wrench} items={agent.toolsets} empty="Global tools" />
        {agent.skills.length > 0 && (
          <ChipRow icon={Sparkles} items={agent.skills} empty="No skills" />
        )}
        <AgentConfigEditor
          agent={agent}
          availableSkills={availableSkills}
          availableToolsets={availableToolsets}
          availablePlatforms={availablePlatforms}
          saving={savingConfig}
          onSave={onConfigSave}
        />
        {onTelegramLaneChange && onTelegramBotTokenChange && onTelegramLaneSave && (
          <AgentTelegramLaneEditor
            agent={agent}
            tokenValue={telegramBotTokenValue ?? ""}
            laneValue={telegramLaneValue ?? ""}
            tokenPlaceholder={telegramBotTokenPlaceholder}
            lanePlaceholder={telegramLanePlaceholder}
            onTokenChange={onTelegramBotTokenChange}
            onLaneChange={onTelegramLaneChange}
            onSave={onTelegramLaneSave}
            saving={Boolean(savingTelegram)}
          />
        )}
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-0 py-1">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className="truncate text-sm font-medium" title={String(value)}>
        {value}
      </div>
    </div>
  );
}

function ChipRow({
  items,
  empty,
}: {
  icon: typeof Terminal;
  items: string[];
  empty: string;
}) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
      {(items.length ? items : [empty]).slice(0, 7).map((item) => (
        <span key={item} className="max-w-full truncate">
          {item}
        </span>
      ))}
    </div>
  );
}

function TelegramGatewayControls({
  envVars,
  hasChanges,
  home,
  onHomeChange,
  onRestart,
  onSave,
  onTokenChange,
  saving,
  token,
  tokenConfigured,
}: {
  envVars: Record<string, EnvVarInfo> | null;
  hasChanges: boolean;
  home: string;
  onHomeChange: (value: string) => void;
  onRestart: () => void;
  onSave: () => void;
  onTokenChange: (value: string) => void;
  saving: boolean;
  token: string;
  tokenConfigured: boolean;
}) {
  const saveOnEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && hasChanges) {
      event.preventDefault();
      onSave();
    }
  };

  return (
    <div className="py-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-foreground">Executive Telegram</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className={cn("text-xs", tokenConfigured ? "text-muted-foreground" : "text-warning")}>
            {tokenConfigured ? "configured" : "needs token"}
          </span>
        </div>
      </div>
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
        <div className="grid gap-1">
          <div className="text-xs font-medium text-muted-foreground">Executive bot token</div>
          <Input
            autoComplete="new-password"
            type="password"
            value={token}
            placeholder={envPlaceholder(
              envVars,
              EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY,
              envPlaceholder(envVars, "TELEGRAM_BOT_TOKEN", "Executive BotFather token"),
            )}
            onChange={(event) => onTokenChange(event.target.value)}
            onKeyDown={saveOnEnter}
          />
        </div>
        <div className="grid gap-1">
          <div className="text-xs font-medium text-muted-foreground">Executive chat/topic</div>
          <Input
            value={home}
            placeholder={envPlaceholder(
              envVars,
              EXECUTIVE_TELEGRAM_CHANNEL_KEY,
              envPlaceholder(envVars, "TELEGRAM_HOME_CHANNEL", "Executive chat ID"),
            )}
            onChange={(event) => onHomeChange(event.target.value)}
            onKeyDown={saveOnEnter}
          />
        </div>
        <div className="flex gap-2 md:justify-end">
          <Button
            size="sm"
            onClick={onSave}
            disabled={saving || !hasChanges}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
          <Button size="sm" variant="outline" onClick={onRestart}>
            <RotateCw className="h-3.5 w-3.5" />
            Restart
          </Button>
        </div>
      </div>
    </div>
  );
}

function isHarnessSnapshot(value: AgentHubSnapshot["harness"]): value is HarnessSnapshot {
  return Boolean(value && "server" in value && "orchestration" in value);
}

function formatSavings(value: number | null | undefined) {
  if (typeof value !== "number") return "-";
  return `${value.toFixed(1)}%`;
}

function HarnessCard({ harness }: { harness?: AgentHubSnapshot["harness"] }) {
  if (!isHarnessSnapshot(harness)) {
    return (
      <div className="px-1">
        <div className="mb-2 text-sm font-medium">Harness</div>
        <div className="text-sm text-muted-foreground">
          Harness snapshot unavailable
        </div>
      </div>
    );
  }

  const best = harness.performance.best_profile;
  const worst = harness.performance.worst_profile;
  const connectedClients = harness.server.clients.filter((client) => client.connected);

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 px-1">
        <span className="text-sm font-medium">Harness</span>
        <span className="text-xs text-muted-foreground">· {harness.server.pattern}</span>
      </div>
      <div className="space-y-3 px-1">
        <div className="grid grid-cols-3 gap-2">
          <MiniMetric label="Ready" value={harness.orchestration.plan_graph.ready_runs} />
          <MiniMetric label="Blocked" value={harness.orchestration.plan_graph.blocked_runs} />
          <MiniMetric label="Safety" value={harness.safety.external_actions_policy} />
        </div>
        {harness.performance.available && (
          <div className="text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Baseline</span>
              <span>{harness.performance.baseline_request_tokens ?? 0} tokens</span>
            </div>
            <div className="mt-1 flex justify-between gap-2">
              <span className="text-muted-foreground">Best profile</span>
              <span>
                {best?.name ?? "-"} / {formatSavings(best?.savings_pct)}
              </span>
            </div>
            <div className="mt-1 flex justify-between gap-2">
              <span className="text-muted-foreground">Weakest profile</span>
              <span>
                {worst?.name ?? "-"} / {formatSavings(worst?.savings_pct)}
              </span>
            </div>
          </div>
        )}
        <details className="group text-xs">
          <summary className="cursor-pointer list-none text-muted-foreground hover:text-foreground">
            <span className="group-open:hidden">Show technical detail</span>
            <span className="hidden group-open:inline">Hide technical detail</span>
          </summary>
          <div className="mt-2 space-y-1.5">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Clients</span>
              <span>{connectedClients.length}/{harness.server.clients.length}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Routed runs</span>
              <span>{harness.orchestration.route_labeled_runs}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Recent events</span>
              <span>{harness.orchestration.recent_events}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Memory flow</span>
              <span>{harness.memory.pipeline.state}</span>
            </div>
            {harness.orchestration.lifecycle_states.length > 0 && (
              <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-muted-foreground">
                {harness.orchestration.lifecycle_states.slice(0, 7).map((state) => (
                  <span key={state}>{state}</span>
                ))}
              </div>
            )}
          </div>
        </details>
        {harness.memory.pipeline.recent_events?.length ? (
          <div className="text-xs">
            <div className="mb-1 text-muted-foreground">Memory activity</div>
            {harness.memory.pipeline.recent_events.slice(0, 3).map((event, index) => (
              <div key={`${event.timestamp ?? "event"}-${index}`} className="truncate">
                {event.kind ?? "memory"}{event.status ? ` / ${event.status}` : ""}
                {event.message ? `: ${event.message}` : ""}
              </div>
            ))}
          </div>
        ) : null}
        {harness.recommendations.length > 0 && (
          <div className="space-y-1 text-xs text-muted-foreground">
            {harness.recommendations.slice(0, 2).map((item) => (
              <div key={item}>- {item}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function HandoffBusCard({
  busy,
  handoffs,
  onRunWorker,
  onWakeWorker,
  worker,
}: {
  busy: boolean;
  handoffs: AgentHubSnapshot["handoffs"];
  onRunWorker: () => void;
  onWakeWorker: () => void;
  worker: AgentHubSnapshot["agentWorker"];
}) {
  const active = handoffs.queued + handoffs.running + handoffs.waitingHuman;
  const loopRunning = worker.loop?.running ?? false;
  const heartbeat = worker.heartbeat;
  const wake = worker.wake;
  const workerHealthy = worker.enabled && worker.state !== "error" && worker.state !== "disabled" && loopRunning;

  const primaryAction: { label: string; onClick: () => void } = (() => {
    if (!worker.enabled || worker.state === "disabled") {
      return { label: "Run worker", onClick: onRunWorker };
    }
    if (!loopRunning) {
      return { label: "Wake loop", onClick: onWakeWorker };
    }
    if (handoffs.queued > 0 || handoffs.waitingHuman > 0) {
      return { label: "Run worker now", onClick: onRunWorker };
    }
    return { label: "Run worker", onClick: onRunWorker };
  })();
  const secondaryAction =
    primaryAction.label === "Wake loop"
      ? { label: "Run worker", onClick: onRunWorker }
      : { label: "Wake loop", onClick: onWakeWorker };

  return (
    <div className="px-1">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Agent handoffs</span>
            <span className="text-xs text-muted-foreground">· {active} open</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Worker {worker.enabled ? worker.state : "disabled"}</span>
            <span>·</span>
            <span>Loop {loopRunning ? "running" : "stopped"}</span>
            {worker.lastTickAt && (<><span>·</span><span>Tick {isoTimeAgo(worker.lastTickAt)}</span></>)}
            {heartbeat?.lastBeatAt && (<><span>·</span><span>Heartbeat {isoTimeAgo(heartbeat.lastBeatAt)}</span></>)}
            {wake?.lastWakeAt && (<><span>·</span><span>Wake {isoTimeAgo(wake.lastWakeAt)}</span></>)}
            {worker.lastError && <span className="text-warning">{worker.lastError}</span>}
          </div>
          {handoffs.error && (
            <div className="mt-1 text-xs text-warning">{handoffs.error}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
            <Button
              size="sm"
              onClick={primaryAction.onClick}
              disabled={busy}
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : primaryAction.label === "Wake loop" ? (
                <Play className="h-3.5 w-3.5" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {primaryAction.label}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={secondaryAction.onClick}
              disabled={busy}
            >
              {secondaryAction.label === "Wake loop" ? (
                <Play className="h-3.5 w-3.5" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {secondaryAction.label}
            </Button>
          </div>
        </div>
      <div className="space-y-3">
        {(handoffs.queued > 0 || handoffs.running > 0) && (
          <div className="grid grid-cols-3 gap-2">
            <MiniMetric label="Queued" value={handoffs.queued} />
            <MiniMetric label="Running" value={handoffs.running} />
            <MiniMetric label="Human" value={handoffs.waitingHuman} />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", workerHealthy ? "bg-success" : "bg-warning")} />
            {worker.enabled ? "auto-drain on" : "auto-drain off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", loopRunning ? "bg-success" : "bg-warning")} />
            wake loop {loopRunning ? "on" : "off"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", heartbeat?.enabled ? "bg-success" : "bg-warning")} />
            heartbeat {heartbeat?.intervalSeconds ?? "off"}s
          </span>
          {wake?.pending && <span className="text-warning">wake pending</span>}
        </div>
        <details className="group text-xs">
          <summary className="cursor-pointer list-none text-muted-foreground hover:text-foreground">
            <span className="group-open:hidden">Show drain history</span>
            <span className="hidden group-open:inline">Hide drain history</span>
          </summary>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
            <span>Last handoffs {worker.drained.handoffs}</span>
            <span>·</span>
            <span>Last admin {worker.drained.adminRuns}</span>
            <span>·</span>
            <span>Wakes {wake?.count ?? 0}</span>
            <span>·</span>
            <span>Handoff cap {worker.limits.handoffs}</span>
            <span>·</span>
            <span>Admin cap {worker.limits.adminRuns}</span>
          </div>
        </details>
        {handoffs.byAgent.some((a) => a.queued > 0 || a.running > 0) && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {handoffs.byAgent
              .filter((a) => a.queued > 0 || a.running > 0)
              .slice(0, 8)
              .map((agent) => (
                <span key={agent.agentId} className="text-warning">
                  {agent.agentId} {agent.queued + agent.running}/{agent.total}
                </span>
              ))}
          </div>
        )}
        <div className="space-y-0.5">
          {handoffs.recent.slice(0, 5).map((handoff) => (
            <div
              key={handoff.id}
              className="rounded-md px-1 py-1.5 hover:bg-muted"
            >
              <div className="flex items-center gap-2">
                <div className="min-w-0 truncate text-sm font-medium">
                  {handoff.title}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {handoff.status.replace("_", " ")}
                </span>
              </div>
              <div className="mt-0.5 truncate text-xs text-muted-foreground">
                {handoff.fromAgentId} → {handoff.toAgentId} · {isoTimeAgo(handoff.updatedAt)}
              </div>
            </div>
          ))}
          {!handoffs.recent.length && (
            <div className="py-1 text-xs text-muted-foreground/80">No handoffs yet</div>
          )}
        </div>
      </div>
    </div>
  );
}

function SetupRunway({
  busyAction,
  onRestart,
  onStart,
  snapshot,
}: {
  busyAction: string | null;
  onRestart: () => void;
  onStart: () => void;
  snapshot: AgentHubSnapshot;
}) {
  const pendingPairings = snapshot.platforms.reduce(
    (total, platform) => total + platform.pending_pairings.length,
    0,
  );
  const configuredPlatforms = snapshot.platforms.filter((platform) => platform.configured).length;

  const items = [
    {
      icon: KeyRound,
      label: "Model auth",
      detail: snapshot.model.configured ? `${snapshot.model.provider} / ${snapshot.model.model}` : "Connect OpenAI Codex",
      state: snapshot.model.configured ? "ready" : "needs setup",
      to: "/env",
    },
    {
      icon: Terminal,
      label: "Gateway",
      detail: snapshot.gateway.running ? `Running${snapshot.gateway.pid ? ` as ${snapshot.gateway.pid}` : ""}` : "Start the local service",
      state: snapshot.gateway.running ? "online" : "offline",
      action: snapshot.gateway.running ? onRestart : onStart,
    },
    {
      icon: Users,
      label: "Messaging",
      detail: pendingPairings ? `${pendingPairings} pairing code${pendingPairings === 1 ? "" : "s"} waiting` : `${configuredPlatforms} connector${configuredPlatforms === 1 ? "" : "s"} configured`,
      state: pendingPairings ? "review" : configuredPlatforms ? "ready" : "blank",
      to: "/today",
    },
    {
      icon: Brain,
      label: "Memory",
      detail: snapshot.memory.embedding.enabled
        ? `${snapshot.memory.embedding.provider}:${snapshot.memory.embedding.model}`
        : "Turn on embeddings",
      state: snapshot.memory.embedding.enabled ? "ready" : "optional",
      to: "/memory",
    },
  ];

  return (
    <div className="px-1">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-sm font-medium">Setup runway</span>
        <Link
          to="/config"
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          Full settings
        </Link>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => {
          const Icon = item.icon;
          const content = (
            <>
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0 text-primary" />
                  <span className="truncate text-sm font-semibold text-foreground">{item.label}</span>
                </div>
                <span className={cn(
                  "inline-flex items-center gap-1.5 text-xs",
                  item.state === "ready" || item.state === "online"
                    ? "text-muted-foreground"
                    : item.state === "review" || item.state === "needs setup"
                      ? "text-warning"
                      : "text-muted-foreground"
                )}>
                  <span className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    item.state === "ready" || item.state === "online"
                      ? "bg-success"
                      : item.state === "review" || item.state === "needs setup"
                        ? "bg-warning"
                        : "bg-border"
                  )} />
                  {item.state}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">{item.detail}</p>
            </>
          );

          if (item.action) {
            return (
              <button
                key={item.label}
                type="button"
                onClick={item.action}
                disabled={busyAction !== null}
                className="p-2 text-left transition-colors hover:bg-muted disabled:opacity-60 rounded-md"
              >
                {content}
              </button>
            );
          }

          return (
            <Link
              key={item.label}
              to={item.to ?? "/config"}
              className="p-2 transition-colors hover:bg-muted rounded-md"
            >
              {content}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default function AgentHubPage() {
  const [snapshot, setSnapshot] = useState<AgentHubSnapshot | null>(null);
  const [envVars, setEnvVars] = useState<Record<string, EnvVarInfo> | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [savingTelegram, setSavingTelegram] = useState(false);
  const [savingAgentId, setSavingAgentId] = useState<string | null>(null);
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramHome, setTelegramHome] = useState("");
  const [telegramLanes, setTelegramLanes] = useState<Record<string, string>>({});
  const [telegramAgentTokens, setTelegramAgentTokens] = useState<Record<string, string>>({});
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();
  const hydrationTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    if (hydrationTimerRef.current) {
      window.clearTimeout(hydrationTimerRef.current);
      hydrationTimerRef.current = null;
    }
    const envVarsPromise = api
      .getEnvVars()
      .then((nextEnvVars) => {
        if (mountedRef.current) setEnvVars(nextEnvVars);
      })
      .catch(() => null);
    try {
      const nextSnapshot = await api.getAgentHub({
        lite: true,
        includeSkills: true,
        includeToolsets: true,
      });
      if (mountedRef.current) {
        setSnapshot(nextSnapshot);
        hydrationTimerRef.current = window.setTimeout(() => {
          void api
            .getAgentHub({ includeMemoryGraph: true })
            .then((fullSnapshot) => {
              if (mountedRef.current) setSnapshot(fullSnapshot);
            })
            .catch(() => null);
        }, 900);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent Hub failed", "error");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
    void envVarsPromise;
  }, [showToast]);

  useEffect(() => {
    mountedRef.current = true;
    load();
    return () => {
      mountedRef.current = false;
      if (hydrationTimerRef.current) {
        window.clearTimeout(hydrationTimerRef.current);
        hydrationTimerRef.current = null;
      }
    };
  }, [load]);

  useLayoutEffect(() => {
    setAfterTitle(
      snapshot ? (
        <span className="text-xs text-muted-foreground">
          {snapshot.gateway.running ? "Gateway online" : "Gateway offline"}
        </span>
      ) : null,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={load} disabled={loading}>
        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [load, loading, setAfterTitle, setEnd, snapshot]);

  const executiveAgent = useMemo(
    () =>
      snapshot?.agents.find((agent) => agent.id === "executive-assistant") ??
      snapshot?.agents[0] ??
      null,
    [snapshot],
  );
  const activeAgents = snapshot?.agents.filter((agent) => agent.enabled) ?? [];
  const liveSessions = snapshot?.sessions.recent.filter((session) => session.is_active) ?? [];
  const availableSkills = useMemo<SkillEntry[]>(
    () => snapshot?.skills.available ?? [],
    [snapshot?.skills.available],
  );
  const availableToolsets = useMemo<ToolsetEntry[]>(
    () =>
      (snapshot?.toolsets.known ?? []).map((toolset) => ({
        name: toolset.name,
        label: toolset.label,
        description: toolset.description,
      })),
    [snapshot?.toolsets.known],
  );
  const availablePlatforms = useMemo<string[]>(
    () => snapshot?.platforms.map((platform) => platform.name) ?? [],
    [snapshot?.platforms],
  );
  const telegramPlatform = snapshot?.platforms.find(
    (platform) => platform.name.toLowerCase() === "telegram",
  );
  const telegramTokenConfigured = Boolean(
    telegramPlatform?.token_configured ||
      envVars?.TELEGRAM_BOT_TOKEN?.is_set ||
      envVars?.[EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY]?.is_set,
  );
  const telegramHasChanges = Boolean(
    telegramToken.trim() ||
      telegramHome.trim() ||
      (snapshot?.agents ?? []).some((agent) => {
        const field = telegramFieldForAgent(agent.id, agent.name);
        return Boolean((telegramAgentTokens[field.tokenKey] ?? "").trim() || (telegramLanes[field.key] ?? "").trim());
      }),
  );

  const runAction = async (name: "start" | "restart") => {
    setBusyAction(name);
    try {
      const result = name === "start" ? await api.startGateway() : await api.restartGateway();
      showToast(`${result.name} started as PID ${result.pid}`, "success");
      setTimeout(load, 1200);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Gateway action failed", "error");
    } finally {
      setBusyAction(null);
    }
  };

  const runAgentWorker = async () => {
    setHandoffBusy(true);
    try {
      const result = await api.runAgentWorkerTick();
      showToast(
        `Worker launched ${result.drained.handoffs} handoff${result.drained.handoffs === 1 ? "" : "s"} and ${result.drained.adminRuns} admin run${result.drained.adminRuns === 1 ? "" : "s"}`,
        "success",
      );
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const wakeAgentWorker = async () => {
    setHandoffBusy(true);
    try {
      await api.wakeAgentWorker();
      showToast("Worker wake queued. Gateway loop will drain it.", "success");
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Agent worker wake failed", "error");
    } finally {
      setHandoffBusy(false);
    }
  };

  const saveTelegramConfig = async () => {
    const entries = new Map<string, string>();
    const executiveField = telegramFieldForAgent("executive-assistant", "Executive Assistant");
    const telegramTokenValue = telegramToken.trim();
    const telegramHomeValue = telegramHome.trim();
    const typedExecutiveToken = (telegramAgentTokens[executiveField.tokenKey] ?? "").trim();
    const typedExecutiveHome = (telegramLanes[executiveField.key] ?? "").trim();
    const executiveTokenCandidate = typedExecutiveToken || telegramTokenValue;
    for (const agent of snapshot?.agents ?? []) {
      if (agent.id === "executive-assistant") continue;
      const field = telegramFieldForAgent(agent.id, agent.name);
      const tokenValue = (telegramAgentTokens[field.tokenKey] ?? "").trim();
      if (
        tokenValue &&
        ((telegramTokenValue && tokenValue === telegramTokenValue) ||
          (executiveTokenCandidate && tokenValue === executiveTokenCandidate))
      ) {
        showToast(`${agent.name} needs its own BotFather token; it cannot reuse Executive.`, "error");
        return;
      }
    }
    if (telegramTokenValue) {
      entries.set("TELEGRAM_BOT_TOKEN", telegramTokenValue);
      if (!typedExecutiveToken) {
        entries.set(EXECUTIVE_TELEGRAM_BOT_TOKEN_KEY, telegramTokenValue);
      }
    }
    if (telegramHomeValue) {
      if (looksLikeTelegramBotToken(telegramHomeValue)) {
        showToast("Home channel expects a chat/topic ID, not a bot token.", "error");
        return;
      }
      entries.set("TELEGRAM_HOME_CHANNEL", telegramHomeValue);
      if (!typedExecutiveHome) {
        entries.set(EXECUTIVE_TELEGRAM_CHANNEL_KEY, telegramHomeValue);
      }
    }
    for (const agent of snapshot?.agents ?? []) {
      const field = telegramFieldForAgent(agent.id, agent.name);
      const tokenValue = (telegramAgentTokens[field.tokenKey] ?? "").trim();
      if (tokenValue) {
        entries.set(field.tokenKey, tokenValue);
      }
      const value = (telegramLanes[field.key] ?? "").trim();
      if (value) {
        if (looksLikeTelegramBotToken(value)) {
          showToast(`${agent.name}: paste the bot token into Bot token, not Chat/topic ID.`, "error");
          return;
        }
        entries.set(field.key, value);
      }
    }
    if (!entries.size) return;

    setSavingTelegram(true);
    try {
      for (const [key, value] of entries.entries()) {
        await api.setEnvVar(key, value);
      }
      setTelegramToken("");
      setTelegramHome("");
      setTelegramLanes({});
      setTelegramAgentTokens({});
      await load();
      showToast("Telegram settings saved. Restart gateway to apply.", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Telegram save failed", "error");
    } finally {
      setSavingTelegram(false);
    }
  };

  const saveAgentConfig = useCallback(
    async (agentId: string, patch: AgentEditPatch) => {
      setSavingAgentId(agentId);
      try {
        await api.updateAgent(agentId, patch);
        await load();
        showToast("Agent saved. Restart gateway to apply changes.", "success");
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Agent save failed", "error");
      } finally {
        setSavingAgentId(null);
      }
    },
    [load, showToast],
  );

  if (loading && !snapshot) {
    return (
      <FullWindowAurora
        label="Agent Hub · loading"
        title="Spinning up your agents"
        subtitle="Pulling agent configs, memory snapshots, and connector status."
      />
    );
  }

  if (!snapshot) {
    return (
      <FullWindowAurora
        label="Agent Hub"
        title="Agent Hub unavailable"
        subtitle="The local gateway didn't respond. Check the system panel in the sidebar and try Restart Gateway."
      />
    );
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="px-1">
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div className="min-w-0">
              <div className="text-xs font-medium text-muted-foreground">Main agent</div>
              <h1 className="mt-1 truncate text-2xl font-semibold leading-tight text-foreground sm:text-3xl">
                {executiveAgent?.name ?? "Executive Assistant"}
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                {executiveAgent?.description ||
                  executiveAgent?.role ||
                  "Primary operator and orchestration agent for the local Elevate workspace."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={() => runAction("start")}
                disabled={busyAction !== null}
                aria-label={snapshot.gateway.running ? "Restart gateway" : "Start gateway"}
              >
                {busyAction === "start" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                Start gateway
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => runAction("restart")}
                disabled={busyAction !== null}
                aria-label="Restart gateway"
              >
                {busyAction === "restart" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCw className="h-3.5 w-3.5" />
                )}
                Restart
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MiniMetric label="Agent team" value={activeAgents.length} />
            <MiniMetric label="Live chats" value={liveSessions.length} />
            <MiniMetric label="Open handoffs" value={snapshot.handoffs.open} />
            <MiniMetric label="Skills" value={`${snapshot.skills.enabled}/${snapshot.skills.total}`} />
          </div>
        </div>
      </section>

      <SetupRunway
        busyAction={busyAction}
        onRestart={() => void runAction("restart")}
        onStart={() => void runAction("start")}
        snapshot={snapshot}
      />

      <div className="flex flex-col gap-6">
        <div>
          <div className="mb-3 flex items-center gap-2 px-1">
            <span className="text-sm font-medium">Agent orchestration</span>
            <span aria-hidden="true" className="text-xs text-muted-foreground">·</span>
            <span className="text-xs text-muted-foreground">{activeAgents.length} enabled</span>
          </div>
            <div className="space-y-3">
              <TelegramGatewayControls
                envVars={envVars}
                hasChanges={telegramHasChanges}
                home={telegramHome}
                onHomeChange={setTelegramHome}
                onRestart={() => void runAction("restart")}
                onSave={() => void saveTelegramConfig()}
                onTokenChange={setTelegramToken}
                saving={savingTelegram}
                token={telegramToken}
                tokenConfigured={telegramTokenConfigured}
              />
              <div className="grid gap-3 md:grid-cols-2">
                {snapshot.agents.map((agent) => {
                  const telegramField = telegramFieldForAgent(agent.id, agent.name);
                  return (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      availableSkills={availableSkills}
                      availableToolsets={availableToolsets}
                      availablePlatforms={availablePlatforms}
                      savingConfig={savingAgentId === agent.id}
                      onConfigSave={(patch) => saveAgentConfig(agent.id, patch)}
                      telegramBotTokenPlaceholder={
                        telegramField
                          ? envPlaceholder(envVars, telegramField.tokenKey, `${agent.name} bot token`)
                          : undefined
                      }
                      telegramBotTokenValue={
                        telegramField ? (telegramAgentTokens[telegramField.tokenKey] ?? "") : undefined
                      }
                      telegramLanePlaceholder={
                        telegramField
                          ? envPlaceholder(envVars, telegramField.key, "Chat ID or topic ID")
                          : undefined
                      }
                      telegramLaneValue={telegramField ? (telegramLanes[telegramField.key] ?? "") : undefined}
                      onTelegramBotTokenChange={
                        telegramField
                          ? (value) =>
                              setTelegramAgentTokens((prev) => ({
                                ...prev,
                                [telegramField.tokenKey]: value,
                              }))
                          : undefined
                      }
                      onTelegramLaneChange={
                        telegramField
                          ? (value) =>
                              setTelegramLanes((prev) => ({ ...prev, [telegramField.key]: value }))
                          : undefined
                      }
                      onTelegramLaneSave={() => void saveTelegramConfig()}
                      savingTelegram={savingTelegram}
                    />
                  );
                })}
              </div>
            </div>
          </div>

        <HandoffBusCard
          busy={handoffBusy}
          handoffs={snapshot.handoffs}
          onRunWorker={() => void runAgentWorker()}
          onWakeWorker={() => void wakeAgentWorker()}
          worker={snapshot.agentWorker}
        />

        <details className="group px-1">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <span className="font-medium">System status</span>
            <span className="text-xs text-muted-foreground/80 group-open:hidden">
              · show
            </span>
            <span className="hidden text-xs text-muted-foreground/80 group-open:inline">
              · hide
            </span>
          </summary>
          <div className="mt-3">
            <HarnessCard harness={snapshot.harness} />
          </div>
        </details>

        <div className="px-1">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-sm font-medium">Access</span>
            <span aria-hidden="true" className="text-xs text-muted-foreground">·</span>
            <span className="text-xs text-muted-foreground">{snapshot.access.label}</span>
          </div>
          <div className="flex items-center gap-x-3 overflow-x-auto whitespace-nowrap text-xs [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {Object.entries(snapshot.access.entitlements).map(([name, entitlement]) => (
              <span key={name} className="inline-flex shrink-0 items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    entitlement.status === "active" ? "bg-success" : "bg-border",
                  )}
                />
                <span className="text-muted-foreground">{name}</span>
              </span>
            ))}
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">{snapshot.config_path}</div>
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        Snapshot {timeAgo(snapshot.generated_at)} / {snapshot.elevate_home}
      </div>
    </div>
  );
}

```

---
## `src/pages/CronPage.tsx`
```tsx
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  CalendarDays,
  Check,
  ChevronRight,
  Clock,
  MessageSquare,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  Send,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CronJob } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@/hooks/useToast";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/* ------------------------------------------------------------------ */
/*  Schedule helpers (unchanged from previous version)                 */
/* ------------------------------------------------------------------ */

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

function formatRelative(iso?: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = d.getTime() - Date.now();
  const abs = Math.abs(diff);
  const m = Math.round(abs / 60000);
  if (m < 1) return diff > 0 ? "moments away" : "just now";
  if (m < 60) return diff > 0 ? `in ${m}m` : `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return diff > 0 ? `in ${h}h` : `${h}h ago`;
  const days = Math.round(h / 24);
  return diff > 0 ? `in ${days}d` : `${days}d ago`;
}

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  enabled: "success",
  scheduled: "success",
  paused: "warning",
  error: "destructive",
  completed: "destructive",
};

type ScheduleMode =
  | "daily"
  | "weekdays"
  | "weekly"
  | "biweekly"
  | "monthly"
  | "custom";

const SCHEDULE_OPTIONS: Array<{ label: string; value: ScheduleMode }> = [
  { label: "Daily", value: "daily" },
  { label: "Weekdays", value: "weekdays" },
  { label: "Weekly", value: "weekly" },
  { label: "Every 2 weeks", value: "biweekly" },
  { label: "Monthly", value: "monthly" },
  { label: "Custom", value: "custom" },
];

const WEEKDAYS = [
  { anchor: "Monday", cron: "1", label: "Monday", value: "monday" },
  { anchor: "Tuesday", cron: "2", label: "Tuesday", value: "tuesday" },
  { anchor: "Wednesday", cron: "3", label: "Wednesday", value: "wednesday" },
  { anchor: "Thursday", cron: "4", label: "Thursday", value: "thursday" },
  { anchor: "Friday", cron: "5", label: "Friday", value: "friday" },
  { anchor: "Saturday", cron: "6", label: "Saturday", value: "saturday" },
  { anchor: "Sunday", cron: "0", label: "Sunday", value: "sunday" },
];

const MONTH_DAYS = Array.from({ length: 31 }, (_, index) => {
  const value = String(index + 1);
  return { label: value, value };
});

function timeParts(time: string): { hour: string; minute: string } {
  const [hour = "9", minute = "0"] = time.split(":");
  return {
    hour: String(Math.max(0, Math.min(23, Number(hour) || 0))),
    minute: String(Math.max(0, Math.min(59, Number(minute) || 0))),
  };
}

function buildSchedule({
  customSchedule,
  dayOfMonth,
  dayOfWeek,
  mode,
  time,
}: {
  customSchedule: string;
  dayOfMonth: string;
  dayOfWeek: string;
  mode: ScheduleMode;
  time: string;
}): { description: string; expression: string; helper: string } {
  if (mode === "custom") {
    return {
      description: "Custom schedule",
      expression: customSchedule.trim(),
      helper: "Use cron, intervals like every 2h, or a one-time timestamp.",
    };
  }

  const { hour, minute } = timeParts(time);
  const weekday = WEEKDAYS.find((day) => day.value === dayOfWeek) ?? WEEKDAYS[0];
  const safeMonthDay = String(Math.max(1, Math.min(31, Number(dayOfMonth) || 1)));

  if (mode === "daily") {
    return {
      description: `Daily at ${time}`,
      expression: `${minute} ${hour} * * *`,
      helper: "Runs once every day at the selected time.",
    };
  }

  if (mode === "weekdays") {
    return {
      description: `Weekdays at ${time}`,
      expression: `${minute} ${hour} * * 1-5`,
      helper: "Runs Monday through Friday at the selected time.",
    };
  }

  if (mode === "weekly") {
    return {
      description: `Every ${weekday.label} at ${time}`,
      expression: `${minute} ${hour} * * ${weekday.cron}`,
      helper: "Runs once per week on the selected day.",
    };
  }

  if (mode === "biweekly") {
    return {
      description: `Every other ${weekday.label} at ${time}`,
      expression: `every 2w on ${weekday.anchor} at ${time}`,
      helper:
        "Anchors the first run to the next selected weekday and repeats every 14 days.",
    };
  }

  return {
    description: `Monthly on day ${safeMonthDay} at ${time}`,
    expression: `${minute} ${hour} ${safeMonthDay} * *`,
    helper: "Runs once per month on the selected calendar day.",
  };
}

function inferScheduleMode(expr: string): {
  mode: ScheduleMode;
  time: string;
  dayOfWeek: string;
  dayOfMonth: string;
  customSchedule: string;
} {
  const fallback = {
    mode: "custom" as ScheduleMode,
    time: "09:00",
    dayOfWeek: "monday",
    dayOfMonth: "1",
    customSchedule: expr,
  };
  if (!expr) return fallback;
  const trimmed = expr.trim();
  const biweeklyMatch = trimmed.match(
    /^every\s+2w\s+on\s+(\w+)\s+at\s+(\d{1,2}):(\d{2})$/i,
  );
  if (biweeklyMatch) {
    const anchor = biweeklyMatch[1].toLowerCase();
    const weekday = WEEKDAYS.find((day) => day.value === anchor) ?? WEEKDAYS[0];
    return {
      mode: "biweekly",
      time: `${biweeklyMatch[2].padStart(2, "0")}:${biweeklyMatch[3]}`,
      dayOfWeek: weekday.value,
      dayOfMonth: "1",
      customSchedule: trimmed,
    };
  }
  const cronMatch = trimmed.match(/^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/);
  if (!cronMatch) return fallback;
  const [, minute, hour, dom, month, dow] = cronMatch;
  const minuteNum = Number(minute);
  const hourNum = Number(hour);
  if (
    !Number.isFinite(minuteNum) ||
    minuteNum < 0 ||
    minuteNum > 59 ||
    !Number.isFinite(hourNum) ||
    hourNum < 0 ||
    hourNum > 23 ||
    month !== "*"
  ) {
    return fallback;
  }
  const time = `${String(hourNum).padStart(2, "0")}:${String(minuteNum).padStart(2, "0")}`;
  if (dom === "*" && dow === "*") {
    return { ...fallback, mode: "daily", time };
  }
  if (dom === "*" && dow === "1-5") {
    return { ...fallback, mode: "weekdays", time };
  }
  if (dom === "*") {
    const weekday = WEEKDAYS.find((day) => day.cron === dow);
    if (weekday) {
      return { ...fallback, mode: "weekly", time, dayOfWeek: weekday.value };
    }
  }
  if (dow === "*") {
    const day = Number(dom);
    if (Number.isFinite(day) && day >= 1 && day <= 31) {
      return { ...fallback, mode: "monthly", time, dayOfMonth: String(day) };
    }
  }
  return fallback;
}

function ScheduleFields({
  customSchedule,
  dayOfMonth,
  dayOfWeek,
  idPrefix,
  scheduleMode,
  setCustomSchedule,
  setDayOfMonth,
  setDayOfWeek,
  setScheduleMode,
  setTime,
  time,
}: {
  customSchedule: string;
  dayOfMonth: string;
  dayOfWeek: string;
  idPrefix: string;
  scheduleMode: ScheduleMode;
  setCustomSchedule: (v: string) => void;
  setDayOfMonth: (v: string) => void;
  setDayOfWeek: (v: string) => void;
  setScheduleMode: (v: ScheduleMode) => void;
  setTime: (v: string) => void;
  time: string;
}) {
  const { t } = useI18n();
  const schedule = useMemo(
    () =>
      buildSchedule({
        customSchedule,
        dayOfMonth,
        dayOfWeek,
        mode: scheduleMode,
        time,
      }),
    [customSchedule, dayOfMonth, dayOfWeek, scheduleMode, time],
  );
  return (
    <div className="grid gap-3 rounded-md border border-border bg-card p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <Label htmlFor={`${idPrefix}-schedule-mode`}>{t.cron.schedule}</Label>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
            <CalendarDays className="h-3.5 w-3.5" />
            <span>{schedule.description}</span>
          </div>
        </div>
        <Segmented
          className="flex flex-wrap justify-start rounded-md bg-card p-1"
          onChange={(value) => setScheduleMode(value)}
          options={SCHEDULE_OPTIONS}
          size="sm"
          value={scheduleMode}
        />
      </div>

      {scheduleMode === "custom" ? (
        <div className="grid gap-2">
          <Label htmlFor={`${idPrefix}-schedule`}>
            {t.cron.schedulePlaceholder}
          </Label>
          <Input
            id={`${idPrefix}-schedule`}
            placeholder="0 9 * * *"
            value={customSchedule}
            onChange={(e) => setCustomSchedule(e.target.value)}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="grid gap-2">
            <Label htmlFor={`${idPrefix}-time`}>Time</Label>
            <Input
              id={`${idPrefix}-time`}
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value || "09:00")}
            />
          </div>

          {(scheduleMode === "weekly" || scheduleMode === "biweekly") && (
            <div className="grid gap-2">
              <Label htmlFor={`${idPrefix}-weekday`}>Day</Label>
              <Select
                id={`${idPrefix}-weekday`}
                value={dayOfWeek}
                onValueChange={setDayOfWeek}
              >
                {WEEKDAYS.map((day) => (
                  <SelectOption key={day.value} value={day.value}>
                    {day.label}
                  </SelectOption>
                ))}
              </Select>
            </div>
          )}

          {scheduleMode === "monthly" && (
            <div className="grid gap-2">
              <Label htmlFor={`${idPrefix}-month-day`}>Day of month</Label>
              <Select
                id={`${idPrefix}-month-day`}
                value={dayOfMonth}
                onValueChange={setDayOfMonth}
              >
                {MONTH_DAYS.map((day) => (
                  <SelectOption key={day.value} value={day.value}>
                    {day.label}
                  </SelectOption>
                ))}
              </Select>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-col gap-2 rounded-md bg-card px-3 py-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>{schedule.helper}</span>
        <code className="w-fit rounded-lg bg-foreground/10 px-2 py-1 font-mono text-[0.72rem] text-foreground">
          {schedule.expression || "schedule required"}
        </code>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Inline edit form                                                   */
/* ------------------------------------------------------------------ */

function EditJobForm({
  job,
  onCancel,
  onSaved,
}: {
  job: CronJob;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const initial = useMemo(
    () =>
      inferScheduleMode(
        (job.schedule?.expr as string) || job.schedule_display || "",
      ),
    [job.id, job.schedule_display],
  );
  const [name, setName] = useState(job.name ?? "");
  const [prompt, setPrompt] = useState(job.prompt ?? "");
  const [deliver, setDeliver] = useState(job.deliver ?? "local");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>(initial.mode);
  const [time, setTime] = useState(initial.time);
  const [dayOfWeek, setDayOfWeek] = useState(initial.dayOfWeek);
  const [dayOfMonth, setDayOfMonth] = useState(initial.dayOfMonth);
  const [customSchedule, setCustomSchedule] = useState(initial.customSchedule);
  const [saving, setSaving] = useState(false);
  const schedule = useMemo(
    () =>
      buildSchedule({
        customSchedule,
        dayOfMonth,
        dayOfWeek,
        mode: scheduleMode,
        time,
      }),
    [customSchedule, dayOfMonth, dayOfWeek, scheduleMode, time],
  );

  const handleSave = async () => {
    if (!prompt.trim() || !schedule.expression.trim()) {
      showToast(`${t.cron.prompt} & ${t.cron.schedule} required`, "error");
      return;
    }
    setSaving(true);
    try {
      await api.updateCronJob(job.id, {
        name: name.trim(),
        prompt: prompt.trim(),
        schedule: schedule.expression.trim(),
        deliver,
      });
      showToast(`Saved "${name.trim() || prompt.trim().slice(0, 30)}"`, "success");
      onSaved();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor={`edit-${job.id}-name`}>{t.cron.nameOptional}</Label>
        <Input
          id={`edit-${job.id}-name`}
          placeholder={t.cron.namePlaceholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor={`edit-${job.id}-prompt`}>{t.cron.prompt}</Label>
        <textarea
          id={`edit-${job.id}-prompt`}
          className="flex min-h-[140px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>
      <ScheduleFields
        customSchedule={customSchedule}
        dayOfMonth={dayOfMonth}
        dayOfWeek={dayOfWeek}
        idPrefix={`edit-${job.id}`}
        scheduleMode={scheduleMode}
        setCustomSchedule={setCustomSchedule}
        setDayOfMonth={setDayOfMonth}
        setDayOfWeek={setDayOfWeek}
        setScheduleMode={setScheduleMode}
        setTime={setTime}
        time={time}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="grid gap-2">
          <Label htmlFor={`edit-${job.id}-deliver`}>{t.cron.deliverTo}</Label>
          <Select
            id={`edit-${job.id}-deliver`}
            value={deliver}
            onValueChange={(v) => setDeliver(v)}
          >
            <SelectOption value="local">{t.cron.delivery.local}</SelectOption>
            <SelectOption value="telegram">
              {t.cron.delivery.telegram}
            </SelectOption>
            <SelectOption value="discord">
              {t.cron.delivery.discord}
            </SelectOption>
            <SelectOption value="slack">{t.cron.delivery.slack}</SelectOption>
            <SelectOption value="email">{t.cron.delivery.email}</SelectOption>
          </Select>
        </div>
        <div className="flex items-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            <X className="h-3.5 w-3.5" />
            {t.common.cancel}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            <Check className="h-3.5 w-3.5" />
            {saving ? t.common.saving : t.common.save}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Create new job form                                                */
/* ------------------------------------------------------------------ */

function NewJobForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [prompt, setPrompt] = useState("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("daily");
  const [time, setTime] = useState("09:00");
  const [dayOfWeek, setDayOfWeek] = useState("monday");
  const [dayOfMonth, setDayOfMonth] = useState("1");
  const [customSchedule, setCustomSchedule] = useState("0 9 * * *");
  const [name, setName] = useState("");
  const [deliver, setDeliver] = useState("local");
  const [creating, setCreating] = useState(false);

  const schedule = useMemo(
    () =>
      buildSchedule({
        customSchedule,
        dayOfMonth,
        dayOfWeek,
        mode: scheduleMode,
        time,
      }),
    [customSchedule, dayOfMonth, dayOfWeek, scheduleMode, time],
  );

  const handleCreate = async () => {
    if (!prompt.trim() || !schedule.expression.trim()) {
      showToast(`${t.cron.prompt} & ${t.cron.schedule} required`, "error");
      return;
    }
    setCreating(true);
    try {
      await api.createCronJob({
        prompt: prompt.trim(),
        schedule: schedule.expression.trim(),
        name: name.trim() || undefined,
        deliver,
      });
      showToast(t.common.create + " ✓", "success");
      onCreated();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="cron-name">{t.cron.nameOptional}</Label>
        <Input
          id="cron-name"
          placeholder={t.cron.namePlaceholder}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="cron-prompt">{t.cron.prompt}</Label>
        <textarea
          id="cron-prompt"
          className="flex min-h-[120px] w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder={t.cron.promptPlaceholder}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>

      <ScheduleFields
        customSchedule={customSchedule}
        dayOfMonth={dayOfMonth}
        dayOfWeek={dayOfWeek}
        idPrefix="cron"
        scheduleMode={scheduleMode}
        setCustomSchedule={setCustomSchedule}
        setDayOfMonth={setDayOfMonth}
        setDayOfWeek={setDayOfWeek}
        setScheduleMode={setScheduleMode}
        setTime={setTime}
        time={time}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="grid gap-2">
          <Label htmlFor="cron-deliver">{t.cron.deliverTo}</Label>
          <Select
            id="cron-deliver"
            value={deliver}
            onValueChange={(v) => setDeliver(v)}
          >
            <SelectOption value="local">{t.cron.delivery.local}</SelectOption>
            <SelectOption value="telegram">
              {t.cron.delivery.telegram}
            </SelectOption>
            <SelectOption value="discord">
              {t.cron.delivery.discord}
            </SelectOption>
            <SelectOption value="slack">{t.cron.delivery.slack}</SelectOption>
            <SelectOption value="email">{t.cron.delivery.email}</SelectOption>
          </Select>
        </div>
        <div className="flex items-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={creating}>
            <X className="h-3.5 w-3.5" />
            {t.common.cancel}
          </Button>
          <Button onClick={handleCreate} disabled={creating}>
            <Plus className="h-3.5 w-3.5" />
            {creating ? t.common.creating : t.common.create}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Left rail: job row                                                 */
/* ------------------------------------------------------------------ */

function JobRailRow({
  job,
  selected,
  onSelect,
}: {
  job: CronJob;
  selected: boolean;
  onSelect: () => void;
}) {
  const isPaused = job.state === "paused";
  const isError = job.state === "error";
  const title = job.name || job.prompt.slice(0, 60);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group w-full rounded-md px-2.5 py-2 text-left transition-colors ${
        selected
          ? "bg-primary/10 text-foreground"
          : "hover:bg-foreground/[0.04] text-foreground/90"
      }`}
    >
      <div className="flex items-start gap-2">
        <span
          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
            isError
              ? "bg-destructive"
              : isPaused
                ? "bg-warning"
                : "bg-success"
          }`}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div
            className={`truncate text-[12px] font-medium leading-tight ${
              isPaused ? "text-muted-foreground" : ""
            }`}
          >
            {title}
            {job.prompt.length > 60 && !job.name ? "…" : ""}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground/80">
            <Clock className="h-2.5 w-2.5" />
            <span className="truncate">{job.schedule_display}</span>
          </div>
        </div>
        {isError && (
          <AlertCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
        )}
      </div>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Right detail pane                                                  */
/* ------------------------------------------------------------------ */

function JobDetail({
  job,
  isEditing,
  onEditToggle,
  onPauseResume,
  onTrigger,
  onDelete,
  onSaved,
  onCancelEdit,
}: {
  job: CronJob;
  isEditing: boolean;
  onEditToggle: () => void;
  onPauseResume: () => void;
  onTrigger: () => void;
  onDelete: () => void;
  onSaved: () => void;
  onCancelEdit: () => void;
}) {
  const { t } = useI18n();
  const isPaused = job.state === "paused";

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
        <div className="flex items-start gap-3 px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-medium">
                {job.name || job.prompt.slice(0, 60)}
                {!job.name && job.prompt.length > 60 ? "…" : ""}
              </h2>
              <Badge variant={STATUS_VARIANT[job.state] ?? "secondary"}>
                {job.state}
              </Badge>
              {job.deliver && job.deliver !== "local" && (
                <Badge variant="outline">{job.deliver}</Badge>
              )}
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <CalendarDays className="h-3 w-3" />
              <span className="font-mono">{job.schedule_display}</span>
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              title={isEditing ? t.common.cancel : "Edit"}
              aria-label={isEditing ? t.common.cancel : "Edit"}
              onClick={onEditToggle}
            >
              {isEditing ? (
                <X className="h-4 w-4" />
              ) : (
                <Pencil className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title={isPaused ? t.cron.resume : t.cron.pause}
              aria-label={isPaused ? t.cron.resume : t.cron.pause}
              onClick={onPauseResume}
            >
              {isPaused ? (
                <Play className="h-4 w-4 text-success" />
              ) : (
                <Pause className="h-4 w-4 text-warning" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title={t.cron.triggerNow}
              aria-label={t.cron.triggerNow}
              onClick={onTrigger}
            >
              <Zap className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              title={t.common.delete}
              aria-label={t.common.delete}
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 px-5 py-5">
        {isEditing ? (
          <EditJobForm
            job={job}
            onCancel={onCancelEdit}
            onSaved={onSaved}
          />
        ) : (
          <>
            {/* Meta grid */}
            <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <MetaCell
                icon={<Clock className="h-3 w-3" />}
                label={t.cron.last}
                value={formatTime(job.last_run_at)}
                hint={
                  job.last_run_at ? formatRelative(job.last_run_at) : undefined
                }
              />
              <MetaCell
                icon={<CalendarDays className="h-3 w-3" />}
                label={t.cron.next}
                value={formatTime(job.next_run_at)}
                hint={
                  job.next_run_at ? formatRelative(job.next_run_at) : undefined
                }
              />
              <MetaCell
                icon={<Send className="h-3 w-3" />}
                label={t.cron.deliverTo}
                value={job.deliver || "local"}
              />
              {job.agent && (
                <MetaCell
                  icon={<MessageSquare className="h-3 w-3" />}
                  label="Agent"
                  value={job.agent}
                />
              )}
            </div>

            {job.last_error && (
              <div className="mb-5 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="min-w-0 break-words">{job.last_error}</div>
              </div>
            )}

            {job.last_summary && !job.last_error && (
              <section className="mb-5">
                <div className="mb-2 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                  <MessageSquare className="h-3 w-3" />
                  Last run summary
                </div>
                <div className="whitespace-pre-wrap rounded-md border border-border bg-card/50 px-3 py-3 text-[12.5px] leading-relaxed text-foreground/90">
                  {job.last_summary}
                </div>
              </section>
            )}

            {/* Prompt */}
            <section>
              <div className="mb-2 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                <MessageSquare className="h-3 w-3" />
                {t.cron.prompt}
              </div>
              <pre className="whitespace-pre-wrap rounded-md border border-border bg-card/50 px-3 py-3 text-[12.5px] leading-relaxed text-foreground/90 font-sans">
                {job.prompt}
              </pre>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function MetaCell({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card/40 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground/70">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-1 truncate text-[12.5px] text-foreground">
        {value}
      </div>
      {hint && (
        <div className="text-[10px] text-muted-foreground/70">{hint}</div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function CronPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [attention, setAttention] = useState<import("../lib/api-types").CronAttention | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const editParam = searchParams.get("edit");
  const [selectedId, setSelectedId] = useState<string | null>(editParam);
  const [editingId, setEditingId] = useState<string | null>(editParam);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  /* ---- Sync selected/editing with ?edit= deep link ---- */
  useEffect(() => {
    if (editParam) {
      setSelectedId(editParam);
      setEditingId(editParam);
    }
  }, [editParam]);

  const closeEditor = useCallback(() => {
    setEditingId(null);
    if (editParam) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("edit");
          return next;
        },
        { replace: true },
      );
    }
  }, [editParam, setSearchParams]);

  /* ---- Load jobs ---- */
  const loadJobs = useCallback(() => {
    api
      .getCronJobs()
      .then((next) => {
        setJobs(next);
        // Auto-select first job if nothing selected
        if (next.length > 0 && !selectedId) {
          setSelectedId(next[0].id);
        }
      })
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
  }, [selectedId, showToast, t.common.loading]);

  useEffect(() => {
    loadJobs();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") loadJobs();
    }, 15_000);
    return () => window.clearInterval(interval);
  }, [loadJobs]);

  /* ---- Load attention rollup ---- */
  const loadAttention = useCallback(() => {
    api
      .getCronAttention()
      .then(setAttention)
      .catch(() => {
        /* silent; banner just won't show */
      });
  }, []);

  useEffect(() => {
    loadAttention();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") loadAttention();
    }, 30_000);
    return () => window.clearInterval(interval);
  }, [loadAttention]);

  /* ---- Filter ---- */
  const lowerSearch = search.trim().toLowerCase();
  const filteredJobs = useMemo(() => {
    if (!lowerSearch) return jobs;
    return jobs.filter(
      (job) =>
        (job.name ?? "").toLowerCase().includes(lowerSearch) ||
        job.prompt.toLowerCase().includes(lowerSearch) ||
        job.schedule_display.toLowerCase().includes(lowerSearch),
    );
  }, [jobs, lowerSearch]);

  /* ---- Group jobs by status for rail sections ---- */
  const activeJobs = useMemo(
    () => filteredJobs.filter((j) => j.state !== "paused" && j.state !== "completed"),
    [filteredJobs],
  );
  const pausedJobs = useMemo(
    () => filteredJobs.filter((j) => j.state === "paused"),
    [filteredJobs],
  );

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedId) ?? null,
    [jobs, selectedId],
  );

  /* ---- Page header (count + search + new) ---- */
  const enabledCount = jobs.filter((j) => j.state !== "paused").length;

  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      setEnd(null);
      return;
    }
    setAfterTitle(
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {enabledCount}/{jobs.length} active
      </span>,
    );
    setEnd(
      <div className="flex items-center gap-2">
        <div className="relative w-full min-w-0 sm:max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="h-8 pl-8 pr-7 text-xs"
            placeholder={t.common.search}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearch("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <Button
          size="sm"
          variant={showCreate ? "outline" : "default"}
          onClick={() => {
            setShowCreate((v) => !v);
            if (!showCreate) {
              setEditingId(null);
            }
          }}
        >
          {showCreate ? (
            <>
              <X className="h-3.5 w-3.5" />
              {t.common.cancel}
            </>
          ) : (
            <>
              <Plus className="h-3.5 w-3.5" />
              {t.cron.newJob}
            </>
          )}
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    enabledCount,
    jobs.length,
    loading,
    search,
    setAfterTitle,
    setEnd,
    showCreate,
    t,
  ]);

  /* ---- Actions ---- */
  const handlePauseResume = async (job: CronJob) => {
    try {
      const isPaused = job.state === "paused";
      if (isPaused) {
        await api.resumeCronJob(job.id);
        showToast(
          `${t.cron.resume}: "${job.name || job.prompt.slice(0, 30)}"`,
          "success",
        );
      } else {
        await api.pauseCronJob(job.id);
        showToast(
          `${t.cron.pause}: "${job.name || job.prompt.slice(0, 30)}"`,
          "success",
        );
      }
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleTrigger = async (job: CronJob) => {
    try {
      await api.triggerCronJob(job.id);
      showToast(
        `${t.cron.triggerNow}: "${job.name || job.prompt.slice(0, 30)}"`,
        "success",
      );
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const jobDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        const job = jobs.find((j) => j.id === id);
        try {
          await api.deleteCronJob(id);
          showToast(
            `${t.common.delete}: "${job?.name || (job?.prompt ?? "").slice(0, 30) || id}"`,
            "success",
          );
          // If deleted the selected one, clear or move to next
          setSelectedId((prev) => {
            if (prev !== id) return prev;
            const remaining = jobs.filter((j) => j.id !== id);
            return remaining[0]?.id ?? null;
          });
          loadJobs();
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          throw e;
        }
      },
      [jobs, loadJobs, showToast, t.common.delete, t.status.error],
    ),
  });

  /* ---- Loading ---- */
  if (loading) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        {t.common.loading}
      </p>
    );
  }

  const pendingJob = jobDelete.pendingId
    ? jobs.find((j) => j.id === jobDelete.pendingId)
    : null;

  return (
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={jobDelete.isOpen}
        onCancel={jobDelete.cancel}
        onConfirm={jobDelete.confirm}
        title={t.cron.confirmDeleteTitle}
        description={
          pendingJob
            ? `"${pendingJob.name || pendingJob.prompt.slice(0, 40)}" — ${t.cron.confirmDeleteMessage}`
            : t.cron.confirmDeleteMessage
        }
        loading={jobDelete.isDeleting}
      />

      {attention && attention.total > 0 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/[0.06] px-4 py-3 text-xs">
          <div className="mb-2 flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
            <AlertCircle className="h-3.5 w-3.5" />
            <span>Needs attention ({attention.total})</span>
          </div>
          <div className="flex flex-col gap-1.5 text-foreground/85">
            {attention.pending_drafts > 0 && (
              <div>
                <span className="font-medium">{attention.pending_drafts}</span>{" "}
                {attention.pending_drafts === 1 ? "outreach draft" : "outreach drafts"} waiting on review
              </div>
            )}
            {attention.errored_jobs.map((j) => (
              <button
                key={`err-${j.id}`}
                type="button"
                onClick={() => {
                  setSelectedId(j.id);
                  setShowCreate(false);
                }}
                className="text-left underline-offset-2 hover:underline"
              >
                <span className="text-destructive">Error</span>{" "}
                <span className="font-medium">{j.name || j.id}</span>
                {j.last_error ? <span className="text-muted-foreground"> — {j.last_error}</span> : null}
              </button>
            ))}
            {attention.stale_jobs.map((j) => (
              <button
                key={`stale-${j.id}`}
                type="button"
                onClick={() => {
                  setSelectedId(j.id);
                  setShowCreate(false);
                }}
                className="text-left underline-offset-2 hover:underline"
              >
                <span className="text-amber-700 dark:text-amber-400">Stale</span>{" "}
                <span className="font-medium">{j.name || j.id}</span>
                <span className="text-muted-foreground"> — no run in {j.hours_since}h</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ============ Two-pane shell ============ */}
      <div className="grid min-h-[calc(100vh-12rem)] grid-cols-1 gap-0 rounded-md border border-border bg-card md:grid-cols-[280px_minmax(0,1fr)]">
        {/* ---- Left rail ---- */}
        <aside
          aria-label={t.cron.scheduledJobs}
          className="flex flex-col border-b border-border md:border-b-0 md:border-r"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-normal text-muted-foreground">
              <Clock className="h-3 w-3" />
              <span>{t.cron.scheduledJobs}</span>
              <span className="text-muted-foreground/60">({jobs.length})</span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-1 py-2">
            {/* Create entry */}
            <button
              type="button"
              onClick={() => {
                setShowCreate(true);
                setEditingId(null);
              }}
              className={`mb-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] transition-colors ${
                showCreate
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground"
              }`}
            >
              <Plus className="h-3.5 w-3.5" />
              <span>{t.cron.newJob}</span>
            </button>

            <JobRailSection
              label="Active"
              items={activeJobs}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setShowCreate(false);
              }}
              defaultOpen
            />
            <JobRailSection
              label="Paused"
              items={pausedJobs}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setShowCreate(false);
              }}
              defaultOpen={pausedJobs.length > 0 && activeJobs.length === 0}
            />

            {filteredJobs.length === 0 && (
              <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
                {lowerSearch ? "No jobs match your search." : t.cron.noJobs}
              </p>
            )}
          </div>
        </aside>

        {/* ---- Right pane ---- */}
        <section className="flex min-w-0 flex-col">
          {showCreate ? (
            <div className="flex flex-1 flex-col overflow-y-auto">
              <div className="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
                <div className="flex items-start gap-3 px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <h2 className="flex items-center gap-2 text-base font-medium">
                      <Plus className="h-4 w-4" />
                      {t.cron.newJob}
                    </h2>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Schedule a recurring agent run.
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t.common.cancel}
                    onClick={() => setShowCreate(false)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="px-5 py-5">
                <NewJobForm
                  onCancel={() => setShowCreate(false)}
                  onCreated={() => {
                    setShowCreate(false);
                    loadJobs();
                  }}
                />
              </div>
            </div>
          ) : selectedJob ? (
            <JobDetail
              job={selectedJob}
              isEditing={editingId === selectedJob.id}
              onEditToggle={() => {
                if (editingId === selectedJob.id) {
                  closeEditor();
                } else {
                  setEditingId(selectedJob.id);
                }
              }}
              onPauseResume={() => handlePauseResume(selectedJob)}
              onTrigger={() => handleTrigger(selectedJob)}
              onDelete={() => jobDelete.requestDelete(selectedJob.id)}
              onSaved={() => {
                closeEditor();
                loadJobs();
              }}
              onCancelEdit={closeEditor}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 py-12">
              <p className="text-xs text-muted-foreground">
                {jobs.length === 0
                  ? "No cron jobs yet. Use + New cron job to create one."
                  : "Select a job from the rail to view its details."}
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Left rail section (Active / Paused)                                */
/* ------------------------------------------------------------------ */

function JobRailSection({
  label,
  items,
  selectedId,
  onSelect,
  defaultOpen,
}: {
  label: string;
  items: CronJob[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (defaultOpen) setOpen(true);
  }, [defaultOpen]);

  if (items.length === 0) return null;

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-[10px] font-medium tracking-wide text-muted-foreground/70 hover:text-foreground transition-colors"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="uppercase">{label}</span>
        <span className="text-muted-foreground/40">({items.length})</span>
      </button>
      {open && (
        <ul className="mt-0.5 space-y-px">
          {items.map((job) => (
            <li key={job.id}>
              <JobRailRow
                job={job}
                selected={selectedId === job.id}
                onSelect={() => onSelect(job.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

```

---
## `src/pages/SkillsPage.tsx`
```tsx
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import {
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  Code2,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  Megaphone,
  MoreVertical,
  Package,
  Paintbrush,
  Route,
  Search,
  Sparkles,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SkillInfo, SkillTreeNode } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Markdown } from "@/components/Markdown";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/* ------------------------------------------------------------------ */
/*  Workflow flow cards (kept compact above the tree)                  */
/* ------------------------------------------------------------------ */

const REAL_ESTATE_WORKFLOWS = [
  {
    key: "leads",
    icon: Users,
    label: "Leads",
    names: [
      "outreach-lanes",
      "real-estate-first-touch-outreach-run",
      "lead-scorer",
      "property-lookup",
      "gmail-doc-router",
    ],
  },
  {
    key: "admin",
    icon: BriefcaseBusiness,
    label: "Admin",
    names: [
      "admin-agent",
      "cma",
      "listing-build",
      "seller-update",
      "seller-package",
      "offer-review",
      "deal-matcher",
      "subject-removal",
      "signing-package",
      "closing-admin",
      "skyslope-sync",
      "mlc",
      "webforms",
      "photo-cleanup",
    ],
  },
  {
    key: "social-media",
    icon: Paintbrush,
    label: "Social Media",
    names: ["social-content-engine"],
  },
  {
    key: "ads",
    icon: Megaphone,
    label: "Ads",
    names: ["marketing"],
  },
] as const;

const REAL_ESTATE_SKILL_NAMES = new Set([
  "admin-agent",
  "admin-result-writer",
  "closing-admin",
  "cma",
  "deal-matcher",
  "digisign",
  "gmail-doc-router",
  "listing-build",
  "marketing",
  "marketing-landing",
  "mlc",
  "offer-review",
  "outreach",
  "outreach-lanes",
  "photo-cleanup",
  "real-estate-first-touch-outreach-run",
  "relisting",
  "seller-package",
  "seller-update",
  "seller-updates",
  "signing-package",
  "skyslope-listing-creation",
  "skyslope-sync",
  "subject-removal",
  "webforms",
  "xposure-pcs-pipeline",
]);

const REAL_ESTATE_KEYWORDS = [
  "cma",
  "deal",
  "digisign",
  "listing",
  "lofty",
  "mlc",
  "offer",
  "outreach",
  "realtor",
  "seller",
  "signing",
  "skyslope",
  "subject-removal",
  "webforms",
  "xposure",
];

interface SkillGroupDefinition {
  key: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

const SKILL_GROUPS: SkillGroupDefinition[] = [
  {
    key: "real-estate",
    label: "Real estate skills",
    description: "Forms, signatures, listings, leads, outreach, and MLS workflows.",
    icon: BriefcaseBusiness,
  },
  {
    key: "marketing-ads",
    label: "Marketing & ads",
    description: "Campaigns, ad audits, social posts, and growth workflows.",
    icon: Megaphone,
  },
  {
    key: "creative-media",
    label: "Creative & media",
    description: "Design, images, video, presentation, and content production.",
    icon: Paintbrush,
  },
  {
    key: "productivity-docs",
    label: "Productivity & documents",
    description: "Documents, PDFs, email, notes, and everyday work utilities.",
    icon: FileText,
  },
  {
    key: "research-data",
    label: "Research & data",
    description: "Research, data science, ML, and analysis helpers.",
    icon: Search,
  },
  {
    key: "engineering-automation",
    label: "Engineering & automation",
    description: "Coding, GitHub, agents, MCP, DevOps, and automation helpers.",
    icon: Code2,
  },
  {
    key: "other",
    label: "Other skills",
    description: "Installed skills that do not declare a clearer purpose yet.",
    icon: Package,
  },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fileIcon(name: string) {
  if (name === "SKILL.md") return Sparkles;
  if (name.endsWith(".md")) return FileText;
  return FileText;
}

function normalizeSkillCategory(category: string | null | undefined): string {
  return (category || "uncategorized").trim().toLowerCase();
}

function isRealEstateSkill(skill: SkillInfo): boolean {
  const name = skill.name.toLowerCase();
  const category = normalizeSkillCategory(skill.category);
  return (
    category === "real-estate" ||
    category === "real-estate-admin" ||
    REAL_ESTATE_SKILL_NAMES.has(name) ||
    REAL_ESTATE_KEYWORDS.some((keyword) => name.includes(keyword))
  );
}

function skillGroupKey(skill: SkillInfo): string {
  if (isRealEstateSkill(skill)) return "real-estate";

  const category = normalizeSkillCategory(skill.category);
  if (["ads", "direct-response", "social-media"].includes(category)) {
    return "marketing-ads";
  }
  if (["creative", "media", "gaming"].includes(category)) {
    return "creative-media";
  }
  if (["email", "note-taking", "productivity", "smart-home"].includes(category)) {
    return "productivity-docs";
  }
  if (["data", "data-science", "mlops", "red-teaming", "research"].includes(category)) {
    return "research-data";
  }
  if (["apple", "autonomous-ai-agents", "devops", "github", "mcp", "software-development"].includes(category)) {
    return "engineering-automation";
  }
  return "other";
}

function groupSkillsByPurpose(skills: SkillInfo[]) {
  const grouped = new Map(SKILL_GROUPS.map((group) => [group.key, [] as SkillInfo[]]));
  for (const skill of skills) {
    const key = skillGroupKey(skill);
    const bucket = grouped.get(key) ?? grouped.get("other");
    bucket?.push(skill);
  }
  return SKILL_GROUPS.map((definition) => ({
    definition,
    items: (grouped.get(definition.key) ?? []).sort((a, b) => a.name.localeCompare(b.name)),
  })).filter((group) => group.items.length > 0);
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string>("SKILL.md");
  const [trees, setTrees] = useState<Record<string, SkillTreeNode[]>>({});
  const [loadingTree, setLoadingTree] = useState<string | null>(null);
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [fileContent, setFileContent] = useState<string>("");
  const [fileLoading, setFileLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"render" | "raw">("render");
  const [togglingSkills, setTogglingSkills] = useState<Set<string>>(new Set());
  const [showWorkflows, setShowWorkflows] = useState(false);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  /* ---- Initial load ---- */
  useEffect(() => {
    api
      .getSkills()
      .then((s) => {
        setSkills(s);
        if (s.length > 0 && !selectedSkill) {
          const first = [...s].sort((a, b) => a.name.localeCompare(b.name))[0];
          if (first) {
            setSelectedSkill(first.name);
            setExpandedSkills(new Set([first.name]));
          }
        }
      })
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---- Lazy-load the tree for a skill ---- */
  const loadTree = useCallback(
    async (name: string) => {
      if (trees[name]) return;
      setLoadingTree(name);
      try {
        const res = await api.getSkillTree(name);
        setTrees((prev) => ({ ...prev, [name]: res.tree || [] }));
      } catch {
        setTrees((prev) => ({ ...prev, [name]: [] }));
      } finally {
        setLoadingTree((current) => (current === name ? null : current));
      }
    },
    [trees],
  );

  /* ---- Load file content for the currently selected leaf ---- */
  useEffect(() => {
    if (!selectedSkill) {
      setFileContent("");
      return;
    }
    setFileLoading(true);
    api
      .getSkillFile(selectedSkill, selectedPath)
      .then((res) => {
        if (res.binary) {
          setFileContent(`*(binary file — ${res.size ?? 0} bytes)*`);
        } else if (res.error) {
          setFileContent(`*${res.error}*`);
        } else {
          setFileContent(res.content ?? "");
        }
      })
      .catch(() => setFileContent("*Failed to load file*"))
      .finally(() => setFileLoading(false));
  }, [selectedSkill, selectedPath]);

  /* ---- When a skill is expanded for the first time, pull its tree ---- */
  useEffect(() => {
    if (selectedSkill && !trees[selectedSkill]) {
      loadTree(selectedSkill);
    }
  }, [selectedSkill, trees, loadTree]);

  /* ---- Toggle skill enable/disable ---- */
  const handleToggleSkill = async (skill: SkillInfo) => {
    setTogglingSkills((prev) => new Set(prev).add(skill.name));
    try {
      await api.toggleSkill(skill.name, !skill.enabled);
      setSkills((prev) =>
        prev.map((s) =>
          s.name === skill.name ? { ...s, enabled: !s.enabled } : s,
        ),
      );
      showToast(
        `${skill.name} ${skill.enabled ? t.common.disabled : t.common.enabled}`,
        "success",
      );
    } catch {
      showToast(`${t.common.failedToToggle} ${skill.name}`, "error");
    } finally {
      setTogglingSkills((prev) => {
        const next = new Set(prev);
        next.delete(skill.name);
        return next;
      });
    }
  };

  /* ---- Derived data ---- */
  const lowerSearch = search.trim().toLowerCase();
  const isSearching = lowerSearch.length > 0;

  const filteredSkills = useMemo(() => {
    if (!isSearching) return skills;
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(lowerSearch) ||
        s.description.toLowerCase().includes(lowerSearch) ||
        (s.category ?? "").toLowerCase().includes(lowerSearch),
    );
  }, [skills, isSearching, lowerSearch]);

  const skillGroups = useMemo(
    () => groupSkillsByPurpose(filteredSkills),
    [filteredSkills],
  );

  const skillsByName = useMemo(
    () => new Map(skills.map((skill) => [skill.name, skill])),
    [skills],
  );
  const enabledCount = skills.filter((s) => s.enabled).length;
  const activeSkill = selectedSkill ? skillsByName.get(selectedSkill) : null;

  /* ---- Page header ---- */
  useLayoutEffect(() => {
    if (loading) {
      setAfterTitle(null);
      setEnd(null);
      return;
    }
    setAfterTitle(
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {t.skills.enabledOf
          .replace("{enabled}", String(enabledCount))
          .replace("{total}", String(skills.length))}
      </span>,
    );
    setEnd(
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShowWorkflows((v) => !v)}
          className={`hidden sm:inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] transition-colors ${
            showWorkflows
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border bg-card text-muted-foreground hover:text-foreground"
          }`}
        >
          <Route className="h-3 w-3" />
          Flows
        </button>
        <div className="relative w-full min-w-0 sm:max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            className="h-8 pl-8 pr-7 text-xs"
            placeholder={t.common.search}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearch("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    enabledCount,
    loading,
    search,
    setAfterTitle,
    setEnd,
    showWorkflows,
    skills.length,
    t,
  ]);

  /* ---- Helpers ---- */
  const handleSelectSkill = (name: string, path = "SKILL.md") => {
    setSelectedSkill(name);
    setSelectedPath(path);
    setExpandedSkills((prev) => {
      const next = new Set(prev);
      next.add(name);
      return next;
    });
    if (!trees[name]) loadTree(name);
  };

  const toggleSkillExpansion = (name: string) => {
    setExpandedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
        if (!trees[name]) loadTree(name);
      }
      return next;
    });
  };

  const toggleFolder = (skillName: string, path: string) => {
    const key = `${skillName}::${path}`;
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  /* ---- Loading ---- */
  if (loading) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">
        Loading skills…
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      {showWorkflows && (
        <section className="rounded-md border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <Route className="h-3.5 w-3.5 text-primary" />
              Real estate workflows
            </div>
            <Badge variant="outline">
              {enabledCount}/{skills.length} enabled
            </Badge>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {REAL_ESTATE_WORKFLOWS.map((workflow) => (
              <WorkflowFlowCard
                key={workflow.key}
                workflow={workflow}
                skillsByName={skillsByName}
                togglingSkills={togglingSkills}
                onToggle={handleToggleSkill}
              />
            ))}
          </div>
        </section>
      )}

      {/* ============ Two-pane shell ============ */}
      <div className="grid min-h-[calc(100vh-12rem)] grid-cols-1 gap-0 rounded-md border border-border bg-card md:grid-cols-[280px_minmax(0,1fr)]">
        {/* ---- Left tree rail ---- */}
        <aside
          aria-label={t.skills.title}
          className="flex flex-col border-b border-border md:border-b-0 md:border-r"
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium tracking-normal text-muted-foreground">
              <Package className="h-3 w-3" />
              <span>{t.skills.title}</span>
              <span className="text-muted-foreground/60">
                ({skills.length})
              </span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-1 py-2">
            {skillGroups.map(({ definition, items }) => (
              <TreeSection
                key={definition.key}
                definition={definition}
                items={items}
                trees={trees}
                loadingTree={loadingTree}
                expandedSkills={expandedSkills}
                expandedFolders={expandedFolders}
                selectedSkill={selectedSkill}
                selectedPath={selectedPath}
                togglingSkills={togglingSkills}
                onSelectSkill={handleSelectSkill}
                onToggleExpand={toggleSkillExpansion}
                onToggleFolder={toggleFolder}
                onToggleEnable={handleToggleSkill}
                isSearching={isSearching}
                defaultOpen={definition.key === "real-estate"}
              />
            ))}

            {filteredSkills.length === 0 && (
              <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
                {isSearching ? t.skills.noSkillsMatch : t.skills.noSkills}
              </p>
            )}
          </div>
        </aside>

        {/* ---- Right detail pane ---- */}
        <section className="flex min-w-0 flex-col">
          {activeSkill ? (
            <SkillDetail
              skill={activeSkill}
              filePath={selectedPath}
              fileContent={fileContent}
              fileLoading={fileLoading}
              viewMode={viewMode}
              setViewMode={setViewMode}
              toggling={togglingSkills.has(activeSkill.name)}
              onToggleEnable={() => handleToggleSkill(activeSkill)}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 py-12">
              <p className="text-xs text-muted-foreground">
                Select a skill from the rail to view its contents.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Left rail: a section (Personal / Built-in)                         */
/* ------------------------------------------------------------------ */

interface TreeSectionProps {
  definition: SkillGroupDefinition;
  items: SkillInfo[];
  trees: Record<string, SkillTreeNode[]>;
  loadingTree: string | null;
  expandedSkills: Set<string>;
  expandedFolders: Set<string>;
  selectedSkill: string | null;
  selectedPath: string;
  togglingSkills: Set<string>;
  onSelectSkill: (name: string, path?: string) => void;
  onToggleExpand: (name: string) => void;
  onToggleFolder: (skillName: string, path: string) => void;
  onToggleEnable: (skill: SkillInfo) => void;
  isSearching: boolean;
  defaultOpen: boolean;
}

function TreeSection(props: TreeSectionProps) {
  const {
    definition,
    items,
    trees,
    loadingTree,
    expandedSkills,
    expandedFolders,
    selectedSkill,
    selectedPath,
    togglingSkills,
    onSelectSkill,
    onToggleExpand,
    onToggleFolder,
    onToggleEnable,
    isSearching,
    defaultOpen,
  } = props;
  const [open, setOpen] = useState(defaultOpen || isSearching);
  const Icon = definition.icon;
  const enabledCount = items.filter((skill) => skill.enabled).length;

  useEffect(() => {
    if (isSearching) setOpen(true);
  }, [isSearching]);

  if (items.length === 0) return null;

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted-foreground/80 transition-colors hover:bg-foreground/5 hover:text-foreground"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <Icon className="h-3.5 w-3.5 shrink-0 text-primary/80" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[11px] font-semibold text-foreground">
            {definition.label}
          </span>
          <span className="block truncate text-[9.5px] leading-4 text-muted-foreground/65">
            {definition.description}
          </span>
        </span>
        <span className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[9.5px] tabular-nums text-muted-foreground">
          {enabledCount}/{items.length}
        </span>
      </button>
      {open && (
        <ul className="mt-0.5 space-y-px">
          {items.map((skill) => {
            const isExpanded = expandedSkills.has(skill.name);
            const tree = trees[skill.name];
            const isSelected = selectedSkill === skill.name;
            const isLoadingTree = loadingTree === skill.name;
            return (
              <li key={skill.name}>
                <SkillRailRow
                  skill={skill}
                  selected={isSelected && selectedPath === "SKILL.md"}
                  expanded={isExpanded}
                  toggling={togglingSkills.has(skill.name)}
                  onSelect={() => onSelectSkill(skill.name, "SKILL.md")}
                  onToggleExpand={() => onToggleExpand(skill.name)}
                  onToggleEnable={() => onToggleEnable(skill)}
                />
                {isExpanded && (
                  <div className="ml-6 mt-0.5 mb-1 border-l border-border/60 pl-2">
                    {isLoadingTree && !tree && (
                      <div className="py-1 text-[10px] text-muted-foreground">
                        Loading…
                      </div>
                    )}
                    {tree && tree.length === 0 && (
                      <div className="py-1 text-[10px] text-muted-foreground/70">
                        No files
                      </div>
                    )}
                    {tree && tree.length > 0 && (
                      <FileTreeList
                        nodes={tree}
                        skillName={skill.name}
                        expandedFolders={expandedFolders}
                        selectedSkill={selectedSkill}
                        selectedPath={selectedPath}
                        onSelectFile={(path) => onSelectSkill(skill.name, path)}
                        onToggleFolder={(path) =>
                          onToggleFolder(skill.name, path)
                        }
                      />
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function SkillRailRow({
  skill,
  selected,
  expanded,
  toggling,
  onSelect,
  onToggleExpand,
  onToggleEnable,
}: {
  skill: SkillInfo;
  selected: boolean;
  expanded: boolean;
  toggling: boolean;
  onSelect: () => void;
  onToggleExpand: () => void;
  onToggleEnable: () => void;
}) {
  return (
    <div
      className={`group flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-left transition-colors ${
        selected
          ? "bg-foreground/10 text-foreground"
          : "text-foreground/85 hover:bg-foreground/5"
      }`}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        aria-expanded={expanded}
        aria-label={expanded ? `Collapse ${skill.name}` : `Expand ${skill.name}`}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground/70 transition-colors hover:bg-foreground/10 hover:text-foreground"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </button>
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-1.5 rounded-sm py-0.5 text-left"
      >
        <Sparkles
          className={`h-3 w-3 shrink-0 ${
            skill.enabled ? "text-primary" : "text-muted-foreground/50"
          }`}
        />
        <span
          className={`min-w-0 flex-1 truncate text-[12px] ${
            skill.enabled
              ? "text-foreground"
              : "text-muted-foreground line-through decoration-muted-foreground/40"
          }`}
        >
          {skill.name}
        </span>
      </button>
      <Switch
        checked={skill.enabled}
        disabled={toggling}
        onCheckedChange={() => onToggleEnable()}
        className="h-4 w-7 [&>span]:h-3 [&>span]:w-3"
      />
    </div>
  );
}

function FileTreeList({
  nodes,
  skillName,
  expandedFolders,
  selectedSkill,
  selectedPath,
  onSelectFile,
  onToggleFolder,
}: {
  nodes: SkillTreeNode[];
  skillName: string;
  expandedFolders: Set<string>;
  selectedSkill: string | null;
  selectedPath: string;
  onSelectFile: (path: string) => void;
  onToggleFolder: (path: string) => void;
}) {
  return (
    <ul className="space-y-px">
      {nodes.map((node) => {
        if (node.type === "dir") {
          const key = `${skillName}::${node.path}`;
          const open = expandedFolders.has(key);
          return (
            <li key={node.path}>
              <button
                type="button"
                onClick={() => onToggleFolder(node.path)}
                className="group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-foreground/80 hover:bg-foreground/5"
              >
                {open ? (
                  <FolderOpen className="h-3 w-3 shrink-0 text-muted-foreground" />
                ) : (
                  <Folder className="h-3 w-3 shrink-0 text-muted-foreground" />
                )}
                <span className="truncate text-[11.5px]">{node.name}</span>
                <ChevronRight
                  className={`ml-auto h-3 w-3 text-muted-foreground/60 transition-transform ${
                    open ? "rotate-90" : ""
                  }`}
                />
              </button>
              {open && node.children && node.children.length > 0 && (
                <div className="ml-3 mt-0.5 border-l border-border/40 pl-2">
                  <FileTreeList
                    nodes={node.children}
                    skillName={skillName}
                    expandedFolders={expandedFolders}
                    selectedSkill={selectedSkill}
                    selectedPath={selectedPath}
                    onSelectFile={onSelectFile}
                    onToggleFolder={onToggleFolder}
                  />
                </div>
              )}
            </li>
          );
        }

        const Icon = fileIcon(node.name);
        const isSelected =
          selectedSkill === skillName && selectedPath === node.path;
        const isSkillMd = node.name === "SKILL.md";
        return (
          <li key={node.path}>
            <button
              type="button"
              onClick={() => onSelectFile(node.path)}
              className={`group flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors ${
                isSelected
                  ? "bg-foreground/10 text-foreground"
                  : "text-foreground/75 hover:bg-foreground/5"
              }`}
            >
              <Icon
                className={`h-3 w-3 shrink-0 ${
                  isSkillMd ? "text-primary" : "text-muted-foreground"
                }`}
              />
              <span className="truncate text-[11.5px]">{node.name}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/*  Right pane: skill detail + markdown preview                        */
/* ------------------------------------------------------------------ */

function SkillDetail({
  skill,
  filePath,
  fileContent,
  fileLoading,
  viewMode,
  setViewMode,
  toggling,
  onToggleEnable,
}: {
  skill: SkillInfo;
  filePath: string;
  fileContent: string;
  fileLoading: boolean;
  viewMode: "render" | "raw";
  setViewMode: (v: "render" | "raw") => void;
  toggling: boolean;
  onToggleEnable: () => void;
}) {
  const trigger = useMemo(() => {
    return skill.enabled ? "Slash command + auto" : "Disabled";
  }, [skill.enabled]);

  const addedBy = skill.category || "Local";

  return (
    <div className="flex flex-1 flex-col">
      {/* Header */}
      <header className="flex items-start justify-between gap-4 border-b border-border px-5 pb-3 pt-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-semibold text-foreground">
              {skill.name}
            </h2>
            {!skill.enabled && (
              <Badge variant="outline" className="text-[10px]">
                Disabled
              </Badge>
            )}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[11px] sm:max-w-md">
            <span className="text-muted-foreground">Added by</span>
            <span className="text-muted-foreground">Trigger</span>
            <span className="font-mono-ui text-foreground">{addedBy}</span>
            <span className="font-mono-ui text-foreground">{trigger}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            checked={skill.enabled}
            onCheckedChange={onToggleEnable}
            disabled={toggling}
          />
          <button
            type="button"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
            aria-label="More"
          >
            <MoreVertical className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Description block */}
      <div className="border-b border-border px-5 py-3">
        <div className="text-[11px] font-medium text-muted-foreground">
          Description
        </div>
        <p className="mt-1 text-xs leading-relaxed text-foreground/85">
          {skill.description || "No description provided."}
        </p>
      </div>

      {/* Path crumb + render/raw toggle */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-2">
        <div className="flex items-center gap-1.5 text-[11px] font-mono-ui text-muted-foreground">
          <FileText className="h-3 w-3" />
          <span>{filePath}</span>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-border bg-card p-0.5">
          <button
            type="button"
            onClick={() => setViewMode("render")}
            className={`flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] transition-colors ${
              viewMode === "render"
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Render markdown"
          >
            <Eye className="h-3 w-3" />
          </button>
          <button
            type="button"
            onClick={() => setViewMode("raw")}
            className={`flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] transition-colors ${
              viewMode === "raw"
                ? "bg-foreground/10 text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Show raw"
          >
            <Code2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {fileLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : viewMode === "render" ? (
          <div className="rounded-md border border-border bg-card/40 p-4">
            <Markdown content={stripFrontmatter(fileContent)} />
          </div>
        ) : (
          <pre className="rounded-md border border-border bg-card/60 p-4 text-xs font-mono leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
            {fileContent}
          </pre>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Workflow flow card (compact)                                       */
/* ------------------------------------------------------------------ */

function WorkflowFlowCard({
  workflow,
  skillsByName,
  togglingSkills,
  onToggle,
}: {
  workflow: (typeof REAL_ESTATE_WORKFLOWS)[number];
  skillsByName: Map<string, SkillInfo>;
  togglingSkills: Set<string>;
  onToggle: (skill: SkillInfo) => void;
}) {
  const Icon = workflow.icon;
  const present = workflow.names
    .map((name) => skillsByName.get(name))
    .filter((skill): skill is SkillInfo => Boolean(skill));
  const missing = workflow.names.filter((name) => !skillsByName.has(name));
  const enabled = present.filter((skill) => skill.enabled).length;

  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-primary" />
          <div className="truncate text-sm font-semibold text-foreground">
            {workflow.label}
          </div>
        </div>
        <Badge variant={missing.length ? "warning" : "success"}>
          {present.length}/{workflow.names.length}
        </Badge>
      </div>
      <div className="mt-3 space-y-1.5">
        {present.map((skill) => (
          <div
            key={skill.name}
            className="flex items-center justify-between gap-2 rounded-md bg-card px-2.5 py-1.5"
          >
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-foreground">
                {skill.name}
              </div>
              <div className="mt-0.5 flex items-center gap-1 text-[0.65rem] text-muted-foreground">
                {skill.enabled && (
                  <CheckCircle2 className="h-3 w-3 text-success" />
                )}
                {skill.enabled ? "Enabled" : "Disabled"}
              </div>
            </div>
            <Switch
              checked={skill.enabled}
              disabled={togglingSkills.has(skill.name)}
              onCheckedChange={() => onToggle(skill)}
            />
          </div>
        ))}
        {missing.map((name) => (
          <div
            key={name}
            className="rounded-md border border-dashed border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground"
          >
            {name} missing
          </div>
        ))}
      </div>
      <div className="mt-3 text-[0.68rem] leading-4 text-muted-foreground">
        {enabled} enabled in this workflow.
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Utilities                                                          */
/* ------------------------------------------------------------------ */

function stripFrontmatter(text: string): string {
  if (!text.startsWith("---")) return text;
  const end = text.indexOf("\n---", 3);
  if (end === -1) return text;
  return text.slice(end + 4).replace(/^\s*\n/, "");
}

```

---
## `src/pages/ConfigPage.tsx`
```tsx
import { useCallback, useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import {
  ChevronLeft,
  Code,
  Download,
  FormInput,
  Menu,
  RotateCcw,
  RefreshCw,
  Save,
  Search,
  Upload,
  X,
  Settings2,
  Settings,
  Bot,
  Monitor,
  Palette,
  Users,
  Brain,
  Package,
  Lock,
  Globe,
  Mic,
  Volume2,
  Ear,
  ClipboardList,
  MessageCircle,
  Wrench,
  FileQuestion,
  Network,
  ShieldCheck,
  Copy,
  KeyRound,
  Plug,
  ExternalLink,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Loader2,
  Puzzle,
  Play,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  api,
  type ComposioConnectedAccount,
  type ComposioStatus,
  type ComposioToolkit,
  type CrmIntegrationForm,
  type IntegrationSettingsResponse,
  type IntegrationTestResponse,
  type SourceConnectorsResponse,
  type SourceConnectorStatus,
} from "@/lib/api";
import { getNestedValue, setNestedValue } from "@/lib/nested";
import { CRM_PRESETS, applyPreset, findPresetForForm, type CrmPreset } from "@/lib/crmPresets";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { AutoField } from "@/components/AutoField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const CATEGORY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  general: Settings,
  agent: Bot,
  agent_hub: Users,
  platforms: Network,
  terminal: Monitor,
  display: Palette,
  delegation: Users,
  memory: Brain,
  access: ShieldCheck,
  plugins: Package,
  compression: Package,
  security: Lock,
  browser: Globe,
  voice: Mic,
  tts: Volume2,
  stt: Ear,
  logging: ClipboardList,
  discord: MessageCircle,
  auxiliary: Wrench,
};

function CategoryIcon({ category, className }: { category: string; className?: string }) {
  const Icon = CATEGORY_ICONS[category] ?? FileQuestion;
  return <Icon className={className ?? "h-4 w-4"} />;
}

const ADVANCED_CATEGORIES = new Set([
  "auxiliary",
  "browser",
  "compression",
  "discord",
  "logging",
  "security",
  "stt",
  "terminal",
  "tts",
  "voice",
]);

const SETUP_STEPS = [
  {
    label: "1. Connect the model",
    description: "Give Elevate its own OpenAI Codex session so the Hub can start chats without fighting the Codex app.",
    command: "elevate auth add openai-codex",
  },
  {
    label: "2. Pair Telegram",
    description: "Approve a pairing code from the bot so messages route into the local gateway.",
    command: "elevate pairing approve telegram <CODE>",
  },
  {
    label: "3. Restart local gateway",
    description: "Reload config, connectors, agents, skills, and memory settings after setup changes.",
    command: "elevate gateway restart",
  },
] as const;

function connectorRecordTotal(connector: SourceConnectorStatus): number {
  return Object.values(connector.recordCounts).reduce((total, value) => total + value, 0);
}

function connectorVariant(state: SourceConnectorStatus["state"]): "success" | "warning" | "outline" {
  if (state === "connected" || state === "import_only") return "success";
  if (state === "blocked" || state === "error" || state === "needs_operator") return "warning";
  return "outline";
}

function connectorSetupCopy(connector: SourceConnectorStatus): string {
  // Server-side blueprint description is the source of truth. Fall back to a
  // generic line only if the backend didn't ship one (older API).
  if (connector.description && connector.description.trim()) {
    return connector.description;
  }
  return connector.sourceExists
    ? "Connector files exist. Run sync to refresh."
    : "Initialize this source to create the connector files.";
}

const TOOLKIT_PAGE_SIZE = 24;

function toolkitLogo(tk: ComposioToolkit | undefined): string | undefined {
  if (!tk) return undefined;
  return tk.meta?.logo ?? tk.logo;
}

function toolkitDescription(tk: ComposioToolkit | undefined): string | undefined {
  if (!tk) return undefined;
  return tk.meta?.description ?? tk.description;
}

function toolkitCategoryLabels(tk: ComposioToolkit): string[] {
  const out = new Set<string>();
  for (const c of tk.meta?.categories ?? []) {
    const name = (c?.name ?? c?.id ?? "").toString().trim();
    if (name) out.add(name.toLowerCase());
  }
  for (const c of tk.categories ?? []) {
    const name = (c?.name ?? c?.slug ?? c?.id ?? "").toString().trim();
    if (name) out.add(name.toLowerCase());
  }
  return [...out];
}

function ComposioPanel() {
  const [status, setStatus] = useState<ComposioStatus | null>(null);
  const [connections, setConnections] = useState<ComposioConnectedAccount[]>([]);
  const [toolkits, setToolkits] = useState<ComposioToolkit[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyInput, setKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [connectingSlug, setConnectingSlug] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [toolkitQuery, setToolkitQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [visibleCount, setVisibleCount] = useState<number>(TOOLKIT_PAGE_SIZE);
  const [customAuthState, setCustomAuthState] = useState<{
    slug: string;
    name: string;
    authScheme?: string;
    authGuideUrl?: string | null;
    required: Array<{ name: string; displayName?: string; description?: string; type?: string; required?: boolean }>;
    optional: Array<{ name: string; displayName?: string; description?: string; type?: string; default?: string }>;
    values: Record<string, string>;
    submitting: boolean;
    error: string | null;
  } | null>(null);

  const refresh = useCallback(async (fresh = false) => {
    setLoading(true);
    try {
      const s = await api.getComposioStatus();
      setStatus(s);
      if (s.valid) {
        const [conns, tks] = await Promise.all([
          api.getComposioConnections(fresh),
          api.getComposioToolkits(),
        ]);
        const conData = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
        setConnections(Array.isArray(conData) ? conData : conData.items ?? []);
        const tkData = (tks.data as { items?: ComposioToolkit[] } | ComposioToolkit[]) ?? [];
        setToolkits(Array.isArray(tkData) ? tkData : tkData.items ?? []);
      } else {
        setConnections([]);
        setToolkits([]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // After Connect opens the Composio OAuth tab in a new window, the user
  // completes the flow there and switches back. Refresh on focus so the
  // newly-linked account shows up without making them hit Refresh.
  useEffect(() => {
    const onFocus = () => {
      if (status?.valid) void refresh(true);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh, status?.valid]);

  useEffect(() => {
    if (!customAuthState) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !customAuthState.submitting) {
        setCustomAuthState(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [customAuthState]);

  const saveKey = async () => {
    if (!keyInput.trim()) return;
    setSavingKey(true);
    setKeyError(null);
    try {
      const next = await api.setComposioKey(keyInput.trim());
      setStatus(next);
      if (!next.valid) {
        setKeyError(next.error ?? "Key saved but Composio rejected it.");
      } else {
        setKeyInput("");
      }
      await refresh(true);
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(false);
    }
  };

  const clearKey = async () => {
    setSavingKey(true);
    setKeyError(null);
    try {
      const next = await api.clearComposioKey();
      setStatus(next);
      setConnections([]);
      setToolkits([]);
    } finally {
      setSavingKey(false);
    }
  };

  const connect = async (slug: string) => {
    setConnectingSlug(slug);
    setKeyError(null);
    try {
      const result = await api.initiateComposioConnection({ toolkitSlug: slug });
      const url = result.data?.redirect_url ?? result.data?.redirect_uri;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
        return;
      }
      // Composio returned no managed creds for this toolkit — fetch its
      // schema and open the custom-credentials modal so the user can paste
      // their own client_id / client_secret.
      const errMsg = (result.error || "") + " " + JSON.stringify((result as unknown as Record<string, unknown>).raw ?? "");
      const needsCustom =
        /Default auth config not found/i.test(errMsg) ||
        /Auth_Config_DefaultAuthConfigNotFound/i.test(errMsg) ||
        /use_custom_auth/i.test(errMsg);
      if (needsCustom) {
        const details = await api.getComposioToolkitDetails(slug);
        const tk = (details as unknown as { name?: string; slug?: string; auth_config_details?: unknown[] }) ?? {};
        // The /toolkits/{slug} payload comes back un-wrapped (no {ok,data})
        // in the `data` field via _request(); but our typed wrapper still
        // returns ComposioApiResult. Pull the underlying body either way.
        const body = (details.data ?? details) as unknown as {
          name?: string;
          slug?: string;
          auth_config_details?: Array<{
            name?: string;
            mode?: string;
            fields?: { auth_config_creation?: { required?: unknown[]; optional?: unknown[] } };
          }>;
          auth_guide_url?: string | null;
        };
        const scheme = body.auth_config_details?.[0];
        const required = (scheme?.fields?.auth_config_creation?.required ?? []) as Array<{
          name: string; displayName?: string; description?: string; type?: string; required?: boolean;
        }>;
        const optional = (scheme?.fields?.auth_config_creation?.optional ?? []) as Array<{
          name: string; displayName?: string; description?: string; type?: string; default?: string;
        }>;
        setCustomAuthState({
          slug,
          name: body.name || tk.name || slug,
          authScheme: scheme?.mode,
          authGuideUrl: body.auth_guide_url || null,
          required,
          optional,
          values: Object.fromEntries(
            [...required.map((f) => [f.name, ""]), ...optional.map((f) => [f.name, f.default ?? ""])],
          ) as Record<string, string>,
          submitting: false,
          error: null,
        });
        return;
      }
      if (result.error) {
        setKeyError(result.error);
      } else {
        setKeyError(
          `Composio didn't return an OAuth URL for ${slug}. Try Refresh, then click Add another again.`,
        );
      }
    } finally {
      setConnectingSlug(null);
    }
  };

  const submitCustomAuth = async () => {
    if (!customAuthState) return;
    const missing = customAuthState.required.filter((f) => !(customAuthState.values[f.name] || "").trim());
    if (missing.length > 0) {
      setCustomAuthState({
        ...customAuthState,
        error: `Required: ${missing.map((m) => m.displayName || m.name).join(", ")}`,
      });
      return;
    }
    setCustomAuthState({ ...customAuthState, submitting: true, error: null });
    try {
      const creds: Record<string, string> = {};
      for (const f of [...customAuthState.required, ...customAuthState.optional]) {
        const v = customAuthState.values[f.name];
        if (v && v.trim()) creds[f.name] = v.trim();
      }
      const result = await api.createComposioCustomAuth({
        toolkitSlug: customAuthState.slug,
        credentials: creds,
        authScheme: customAuthState.authScheme,
      });
      const url = result.data?.redirect_url ?? result.data?.redirect_uri;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
        setCustomAuthState(null);
        await refresh(true);
      } else {
        setCustomAuthState({
          ...customAuthState,
          submitting: false,
          error: result.error || "Composio returned no redirect URL.",
        });
      }
    } catch (err) {
      setCustomAuthState({
        ...customAuthState,
        submitting: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const disconnect = async (id: string) => {
    if (!id) return;
    setConnectingSlug(id);
    try {
      await api.deleteComposioConnection(id);
      await refresh(true);
    } finally {
      setConnectingSlug(null);
    }
  };

  const statusBadge = (() => {
    if (!status) return <Badge variant="outline">checking...</Badge>;
    if (!status.hasKey) return <Badge variant="outline">not configured</Badge>;
    if (status.valid) return <Badge variant="success">connected</Badge>;
    return <Badge variant="warning">key invalid</Badge>;
  })();

  const connectedSlugs = new Set(
    connections.map((c) => c.toolkit?.slug).filter(Boolean) as string[],
  );

  const allCategories = useMemo(() => {
    const set = new Set<string>();
    for (const tk of toolkits) for (const c of toolkitCategoryLabels(tk)) set.add(c);
    return [...set].sort();
  }, [toolkits]);

  const filteredToolkits = useMemo(() => {
    const q = toolkitQuery.trim().toLowerCase();
    return toolkits.filter((tk) => {
      const slug = String(tk.slug ?? "").toLowerCase();
      const name = String(tk.name ?? "").toLowerCase();
      const desc = String(toolkitDescription(tk) ?? "").toLowerCase();
      if (q && !slug.includes(q) && !name.includes(q) && !desc.includes(q)) return false;
      if (categoryFilter !== "all") {
        const cats = toolkitCategoryLabels(tk);
        if (!cats.includes(categoryFilter)) return false;
      }
      return true;
    });
  }, [toolkits, toolkitQuery, categoryFilter]);

  useEffect(() => {
    setVisibleCount(TOOLKIT_PAGE_SIZE);
  }, [toolkitQuery, categoryFilter]);

  const visibleToolkits = filteredToolkits.slice(0, visibleCount);

  return (
    <section id="composio" className="scroll-mt-24 space-y-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-foreground">Composio</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            One auth hub for messaging (Gmail, Twilio, WhatsApp) and social (Instagram, X, LinkedIn). Add your API key, then connect each app.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {statusBadge}
          <Button variant="outline" size="sm" onClick={() => void refresh(true)} disabled={loading}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </header>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
          <KeyRound className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          API key
        </label>
        {status?.hasKey ? (
          <div className="flex flex-wrap items-center gap-2">
            <code className="flex-1 truncate rounded-md border border-border bg-transparent px-2 py-1.5 text-xs">
              {status.valid ? "key configured" : "key configured (invalid)"}
            </code>
            <Button variant="outline" size="sm" onClick={() => void clearKey()} disabled={savingKey}>
              <Trash2 className="h-3.5 w-3.5" />
              Remove
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="password"
              placeholder="ck_..."
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              className="min-w-[16rem] flex-1"
            />
            <Button size="sm" onClick={() => void saveKey()} disabled={savingKey || !keyInput.trim()}>
              {savingKey ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              Save
            </Button>
          </div>
        )}
        {keyError && (
          <div className="flex items-start gap-1.5 text-xs text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{keyError}</span>
          </div>
        )}
        {status && status.hasKey && !status.valid && !keyError && (
          <div className="flex items-start gap-1.5 text-xs text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{status.error ?? "Composio rejected the key. Rotate it at composio.dev and re-save."}</span>
          </div>
        )}
        <p className="text-xs leading-5 text-muted-foreground">
          Get a key at{" "}
          <a
            href="https://app.composio.dev/developers"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline-offset-4 hover:underline"
          >
            composio.dev/developers
            <ExternalLink className="ml-1 inline h-3 w-3" aria-hidden="true" />
          </a>
          . Stored in your local .env, never sent anywhere except Composio.
        </p>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-medium text-foreground">
          Connected accounts <span className="text-muted-foreground">({connections.length})</span>
        </h3>
        {!status?.valid ? (
          <div className="flex items-start gap-2 text-sm text-muted-foreground">
            <CircleSlash className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            Add a working API key to see your connected accounts.
          </div>
        ) : connections.length === 0 ? (
          <p className="text-sm text-muted-foreground">No accounts connected yet. Pick one below to start.</p>
        ) : (
          <ul className="divide-y divide-border/50 border-y border-border/50">
            {connections.map((conn, idx) => (
              <li
                key={String(conn.id ?? idx)}
                className="flex items-center gap-3 py-2.5"
              >
                {(conn.toolkit?.meta?.logo ?? conn.toolkit?.logo) ? (
                  <img
                    src={conn.toolkit?.meta?.logo ?? conn.toolkit?.logo}
                    alt=""
                    className="h-7 w-7 rounded-md object-contain"
                  />
                ) : (
                  <div className="flex h-7 w-7 items-center justify-center">
                    <Plug className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-foreground">
                      {conn.toolkit?.name ?? conn.toolkit?.slug ?? "Unknown app"}
                    </span>
                    {conn.status === "ACTIVE" && (
                      <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-label="Active" />
                    )}
                  </div>
                  {conn.user_id && (
                    <div className="truncate text-xs text-muted-foreground">{conn.user_id}</div>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Disconnect ${conn.toolkit?.name ?? "account"}`}
                  onClick={() => void disconnect(String(conn.id ?? ""))}
                  disabled={connectingSlug === String(conn.id ?? "")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {status?.valid && (
        <div>
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="text-sm font-medium text-foreground">
              Available apps <span className="text-muted-foreground">({filteredToolkits.length}
              {filteredToolkits.length !== toolkits.length ? ` of ${toolkits.length}` : ""})</span>
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input
                  type="search"
                  placeholder="Search apps..."
                  aria-label="Search Composio apps"
                  value={toolkitQuery}
                  onChange={(e) => setToolkitQuery(e.target.value)}
                  className="h-8 w-44 pl-7 text-xs"
                />
              </div>
              {allCategories.length > 0 && (
                <select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  aria-label="Filter by category"
                  className="h-8 rounded-md border border-border bg-transparent px-2 text-xs text-foreground"
                >
                  <option value="all">All categories</option>
                  {allCategories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
          {filteredToolkits.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {toolkits.length === 0 ? "No toolkits returned by Composio." : "No apps match that filter."}
            </p>
          ) : (
            <div className="grid gap-1.5 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-8">
              {visibleToolkits.map((tk) => {
                const slug = String(tk.slug ?? "");
                const isConnected = connectedSlugs.has(slug);
                const logo = toolkitLogo(tk);
                const desc = toolkitDescription(tk);
                return (
                  <button
                    key={slug}
                    type="button"
                    onClick={() => void connect(slug)}
                    disabled={connectingSlug === slug}
                    aria-label={isConnected ? `Add another ${tk.name ?? slug} connection` : `Connect ${tk.name ?? slug}`}
                    title={desc ? `${tk.name ?? slug} — ${desc}` : tk.name ?? slug}
                    className="group flex min-h-[44px] flex-col items-center gap-1.5 rounded-md border border-border bg-transparent p-3 text-center transition-colors hover:border-ring hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60"
                  >
                    {logo ? (
                      <img
                        src={logo}
                        alt=""
                        className="h-9 w-9 rounded-md object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-9 w-9 items-center justify-center rounded-md">
                        <Plug className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                      </div>
                    )}
                    <span className="w-full truncate text-xs font-medium text-foreground">
                      {tk.name ?? slug}
                    </span>
                    <span className="text-[0.68rem] text-muted-foreground group-hover:text-foreground">
                      {connectingSlug === slug ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                      ) : isConnected ? (
                        "Add another"
                      ) : (
                        "Connect"
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
            {visibleCount < filteredToolkits.length && (
              <div className="mt-3 flex items-center justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setVisibleCount((n) => n + TOOLKIT_PAGE_SIZE)}
                >
                  Load {Math.min(TOOLKIT_PAGE_SIZE, filteredToolkits.length - visibleCount)} more
                </Button>
              </div>
            )}
            {filteredToolkits.length > 0 && visibleCount >= filteredToolkits.length && (
              <p className="mt-2 text-xs text-muted-foreground">
                Showing all {filteredToolkits.length}{filteredToolkits.length !== toolkits.length ? ` of ${toolkits.length}` : ""} apps.
              </p>
            )}
          </div>
        )}
      {customAuthState && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-background/95 p-4"
          onClick={() => !customAuthState.submitting && setCustomAuthState(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="composio-auth-title"
            className="relative w-full max-w-lg overflow-hidden rounded-lg border border-border bg-card"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-border px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div id="composio-auth-title" className="text-base font-semibold">{customAuthState.name}</div>
                  <div className="text-xs text-muted-foreground">
                    This connection requires custom OAuth credentials.
                  </div>
                </div>
                <button
                  type="button"
                  aria-label="Close dialog"
                  onClick={() => !customAuthState.submitting && setCustomAuthState(null)}
                  className="-mr-2 flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              {customAuthState.authGuideUrl && (
                <a
                  href={customAuthState.authGuideUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-block text-xs text-primary hover:underline"
                >
                  View auth setup guide ↗
                </a>
              )}
            </div>
            <div className="space-y-4 px-5 py-4 max-h-[60vh] overflow-y-auto">
              {[...customAuthState.required, ...customAuthState.optional].map((field) => {
                const isOptional = !customAuthState.required.find((r) => r.name === field.name);
                const isSecret = /secret|password|token|key/i.test(field.name);
                return (
                  <div key={field.name} className="space-y-1">
                    <label className="flex items-center gap-1.5 text-sm font-medium">
                      {field.displayName || field.name}
                      {!isOptional && <span className="text-destructive">*</span>}
                      {isOptional && (
                        <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                      )}
                    </label>
                    {field.description && (
                      <div className="text-xs text-muted-foreground">{field.description}</div>
                    )}
                    <input
                      type={isSecret ? "password" : "text"}
                      value={customAuthState.values[field.name] || ""}
                      onChange={(e) =>
                        setCustomAuthState({
                          ...customAuthState,
                          values: { ...customAuthState.values, [field.name]: e.target.value },
                          error: null,
                        })
                      }
                      placeholder={field.displayName || field.name}
                      className="w-full rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-ring"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </div>
                );
              })}
              {customAuthState.error && (
                <div className="rounded-md border border-border bg-card px-3 py-2 text-xs text-destructive">
                  {customAuthState.error}
                </div>
              )}
            </div>
            <div className="border-t border-border px-5 py-3">
              <Button
                onClick={submitCustomAuth}
                disabled={customAuthState.submitting}
                className="w-full"
              >
                {customAuthState.submitting ? "Creating..." : "Create Auth Config & Connect"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function SourceConnectorSettingsPanel() {
  const navigate = useNavigate();
  const [data, setData] = useState<SourceConnectorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [runningPromptId, setRunningPromptId] = useState<string | null>(null);
  const [runResults, setRunResults] = useState<Record<string, { kind: string; message: string }>>({});
  const [composioAccounts, setComposioAccounts] = useState<ComposioConnectedAccount[]>([]);
  const [composioReady, setComposioReady] = useState<boolean>(false);
  const [fbPages, setFbPages] = useState<Array<{
    id: string;
    name: string;
    selected: boolean;
  }>>([]);
  const [fbPickerOpen, setFbPickerOpen] = useState(false);
  const [fbPickerLoading, setFbPickerLoading] = useState(false);
  const [fbPickerSaving, setFbPickerSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.getSourceConnectors());
    } finally {
      setLoading(false);
    }
  }, []);

  const loadComposio = useCallback(async () => {
    try {
      const status = await api.getComposioStatus();
      if (!status.valid) {
        setComposioReady(false);
        setComposioAccounts([]);
        return;
      }
      setComposioReady(true);
      const conns = await api.getComposioConnections();
      const body = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
      setComposioAccounts(Array.isArray(body) ? body : body.items ?? []);
    } catch {
      // Composio key not set yet — leave empty, the source row still works.
    }
  }, []);

  const loadFbPages = useCallback(async () => {
    setFbPickerLoading(true);
    try {
      const resp = await api.getComposioFacebookPages();
      if (resp.ok) {
        setFbPages(resp.pages.map(p => ({ id: p.id, name: p.name, selected: p.selected })));
      }
    } catch {
      // Composio not connected or no FB account — picker stays empty.
    } finally {
      setFbPickerLoading(false);
    }
  }, []);

  const toggleFbPage = async (pageId: string) => {
    const next = fbPages.map(p => p.id === pageId ? { ...p, selected: !p.selected } : p);
    setFbPages(next);
    setFbPickerSaving(true);
    try {
      const ids = next.filter(p => p.selected).map(p => p.id);
      await api.setComposioFacebookPages(ids);
    } finally {
      setFbPickerSaving(false);
    }
  };

  const hasFacebookAccount = composioAccounts.some(
    a => (a.toolkit?.slug ?? "").toLowerCase() === "facebook",
  );
  const fbSelectedCount = fbPages.filter(p => p.selected).length;

  const promptForConnector = async (connector: SourceConnectorStatus): Promise<string> => {
    const existing = (connector.prompt || "").trim();
    if (existing) return existing;
    const resp = await api.getSourceConnectorPrompt(connector.id);
    return (resp.prompt || "").trim();
  };

  useEffect(() => {
    void load();
    void loadComposio();
  }, [load, loadComposio]);

  useEffect(() => {
    if (hasFacebookAccount) {
      void loadFbPages();
    } else {
      setFbPages([]);
    }
  }, [hasFacebookAccount, loadFbPages]);

  const runPrompt = async (connector: SourceConnectorStatus) => {
    const opensChat = connector.runMode === "agent_session" || !connector.wired;
    setRunningPromptId(connector.id);
    setRunResults((prev) => {
      const next = { ...prev };
      delete next[connector.id];
      return next;
    });
    try {
      // Server-inline connectors can safely complete inside the API request.
      // Browser-driven MLS scrapers need a visible PTY-backed chat session so
      // the operator can watch MFA, browser steps, and terminal output.
      if (!opensChat) {
        try {
          const resp = await api.runSourceConnectorPrompt(connector.id);
          const outcome = resp.run?.outcome;
          setRunResults((prev) => ({
            ...prev,
            [connector.id]: {
              kind: outcome?.kind ?? "ok",
              message: outcome?.message ?? "Sync finished.",
            },
          }));
        } catch (err) {
          setRunResults((prev) => ({
            ...prev,
            [connector.id]: {
              kind: "error",
              message: err instanceof Error ? err.message : "Sync failed.",
            },
          }));
        } finally {
          void load();
        }
        return;
      }
      const prompt = await promptForConnector(connector);
      if (!prompt) return;
      const ts = String(Date.now());
      const seedTitle = connector.runMode === "agent_session" ? "Run source connector" : "Source connector";
      const seedText = `${seedTitle}: ${connector.label} (${connector.id})\n\n${prompt}`;
      try {
        window.sessionStorage.setItem(`elevate:chat-seed:${ts}`, seedText);
      } catch {
        // sessionStorage disabled — fall back to navigating without seed; the
        // user can still paste from clipboard via the secondary button.
      }
      navigate(`/chat?new=${ts}&seed=${ts}`);
    } finally {
      setRunningPromptId(null);
    }
  };

  const copyPromptText = async (connector: SourceConnectorStatus) => {
    try {
      await navigator.clipboard.writeText(await promptForConnector(connector));
    } catch {
      // clipboard not available — silently skip; primary path is run.
    }
  };

  const connectors = data?.connectors ?? [];
  const ready = connectors.filter((connector) => connector.state === "connected" || connector.state === "import_only").length;

  return (
    <section id="connectors" className="scroll-mt-24 space-y-5">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Network className="h-4 w-4 text-primary" aria-hidden="true" />
            Source connectors
          </h2>
          <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
            Where Elevate pulls its data from. Grouped by purpose: messages & inbox, CRM, MLS / buyer intelligence, social, and back-office. Each connector self-describes what it does.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{ready}/{connectors.length || 12} ready</Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
            aria-label="Refresh source connectors"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Refresh
          </Button>
        </div>
      </header>

      <div className="text-sm leading-6 text-muted-foreground">
        <div className="font-medium text-foreground">Source root</div>
        <code className="mt-1 block break-all bg-transparent p-0 font-mono text-xs">
          {data?.sourceRoot ?? "Loading source root..."}
        </code>
      </div>

      {(() => {
        const categories = data?.categories ?? [];
        const fallback = { id: "other", label: "Other", description: "" };
        const groups = new Map<string, SourceConnectorStatus[]>();
        for (const c of connectors) {
          const key = c.category || fallback.id;
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key)!.push(c);
        }
        const ordered = [
          ...categories.filter((c) => groups.has(c.id)),
          ...[...groups.keys()]
            .filter((id) => !categories.some((c) => c.id === id))
            .map((id) => ({ ...fallback, id, label: id })),
        ];
        return ordered.map((cat) => {
          const rows = groups.get(cat.id) ?? [];
          if (!rows.length) return null;
          const readyInCat = rows.filter((r) => r.state === "connected" || r.state === "import_only").length;
          return (
            <section key={cat.id} className="space-y-3">
              <div className="flex flex-col gap-1 border-t border-border/50 pt-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-foreground">{cat.label}</h3>
                  <Badge variant="outline" className="text-[10px]">{readyInCat}/{rows.length}</Badge>
                </div>
                {cat.description && (
                  <p className="max-w-prose text-xs leading-5 text-muted-foreground">{cat.description}</p>
                )}
              </div>
              <ul className="divide-y divide-border/50">
                {rows.map((connector) => (
                  <li key={connector.id} className="py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">{connector.label}</span>
                  <Badge variant={connectorVariant(connector.state)}>{connector.state.replace(/_/g, " ")}</Badge>
                </div>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {connectorSetupCopy(connector)}
                </p>
              </div>
              <Badge variant="outline">{connectorRecordTotal(connector)} records</Badge>
            </div>
            {connector.nextOperatorStep && (
              <div className="mt-3 text-sm leading-6 text-muted-foreground">
                {connector.nextOperatorStep}
              </div>
            )}
            {connector.initializeBehavior === "composio_social_setup" && (
              <div className="mt-3 text-sm">
                {!composioReady ? (
                  <div className="text-muted-foreground">
                    Add your Composio API key in the Composio panel to connect social accounts.
                  </div>
                ) : composioAccounts.length === 0 ? (
                  <div className="text-muted-foreground">
                    No social accounts connected yet. Add one from the Composio panel below.
                  </div>
                ) : (
                  <>
                    <div className="mb-1.5 text-xs text-muted-foreground">
                      Social accounts ({composioAccounts.length})
                    </div>
                    <ul className="flex flex-wrap gap-1.5">
                      {composioAccounts.map((acc, idx) => {
                        const logo = acc.toolkit?.meta?.logo ?? acc.toolkit?.logo;
                        const name = acc.toolkit?.name ?? acc.toolkit?.slug ?? "Unknown";
                        return (
                          <li
                            key={String(acc.id ?? idx)}
                            className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-2 py-0.5"
                            title={acc.user_id ? `${name} • ${acc.user_id}` : name}
                          >
                            {logo ? (
                              <img src={logo} alt="" className="h-3.5 w-3.5 rounded-sm object-contain" />
                            ) : (
                              <Plug className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
                            )}
                            <span className="text-xs text-foreground">{name}</span>
                            {acc.status === "ACTIVE" && (
                              <CheckCircle2 className="h-3 w-3 text-success" aria-hidden="true" />
                            )}
                          </li>
                        );
                      })}
                    </ul>
                    {hasFacebookAccount && (
                      <div className="mt-3 border-t border-border/40 pt-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs font-medium text-foreground">
                            Facebook pages on /leads
                          </div>
                          <button
                            type="button"
                            className="text-xs text-primary hover:underline"
                            onClick={() => {
                              setFbPickerOpen((v) => !v);
                              if (!fbPickerOpen) void loadFbPages();
                            }}
                            aria-expanded={fbPickerOpen}
                          >
                            {fbPickerOpen ? "Done" : "Edit"}
                          </button>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {fbPickerLoading
                            ? "Loading pages..."
                            : fbPages.length === 0
                              ? "No pages found on this Facebook account."
                              : `${fbSelectedCount} of ${fbPages.length} pages will sync to the leads board. The Composio MCP stays connected to all of them.`}
                          {fbPickerSaving && <span className="ml-1 italic">Saving...</span>}
                        </div>
                        {fbPickerOpen && fbPages.length > 0 && (
                          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                            {fbPages.map((p) => (
                              <li key={p.id}>
                                <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-xs text-foreground hover:bg-foreground/[0.04]">
                                  <input
                                    type="checkbox"
                                    checked={p.selected}
                                    onChange={() => void toggleFbPage(p.id)}
                                    className="h-3.5 w-3.5"
                                  />
                                  <span className="truncate">{p.name}</span>
                                </label>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
            {runResults[connector.id] && (
              <div
                className={
                  "mt-3 rounded-md border px-3 py-2 text-xs leading-5 " +
                  (runResults[connector.id].kind === "error"
                    ? "border-destructive/40 bg-destructive/5 text-destructive"
                    : runResults[connector.id].kind === "needs_operator"
                      ? "border-warning/40 bg-warning/5 text-foreground"
                      : "border-success/40 bg-success/5 text-foreground")
                }
              >
                {runResults[connector.id].message}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <Badge variant="outline">{connector.ownerAgent}</Badge>
              {connector.connectionType && <Badge variant="outline">{connector.connectionType}</Badge>}
              {(() => {
                const opensChat = connector.runMode === "agent_session" || !connector.wired;
                const busy = runningPromptId === connector.id;
                const idleLabel = opensChat
                  ? (connector.runMode === "agent_session" ? "Open run session" : "Open setup chat")
                  : "Run sync";
                const busyLabel = opensChat
                  ? (connector.runMode === "agent_session" ? "Opening session…" : "Opening chat…")
                  : "Running…";
                return (
              <Button
                variant="default"
                size="sm"
                className="ml-auto"
                onClick={() => void runPrompt(connector)}
                disabled={busy}
                aria-label={opensChat ? `Open chat session for ${connector.label}` : `Run sync for ${connector.label}`}
              >
                <Play className="h-3.5 w-3.5" aria-hidden="true" />
                {busy ? busyLabel : idleLabel}
              </Button>
                );
              })()}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void copyPromptText(connector)}
                aria-label={`Copy setup prompt text for ${connector.label}`}
                title="Copy prompt text"
              >
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            </div>
          </li>
                ))}
              </ul>
            </section>
          );
        });
      })()}
      {loading && !connectors.length && (
        <div className="py-6 text-sm text-muted-foreground">Loading connector blueprints...</div>
      )}
    </section>
  );
}

function CrmIntegrationSettingsPanel() {
  const [data, setData] = useState<IntegrationSettingsResponse | null>(null);
  const [form, setForm] = useState<CrmIntegrationForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<IntegrationTestResponse | null>(null);
  const [mode, setMode] = useState<"picker" | "preset" | "custom">("picker");
  const [selectedPreset, setSelectedPreset] = useState<CrmPreset | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getIntegrations();
      setData(next);
      const initialForm = { ...next.crm, apiKey: "" };
      setForm(initialForm);
      const matchingPreset = findPresetForForm(initialForm);
      if (matchingPreset) {
        setSelectedPreset(matchingPreset);
        setMode("preset");
      } else if (initialForm.provider || initialForm.baseUrl) {
        setMode("custom");
      } else {
        setMode("picker");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const connectedPresetSlug = useMemo(() => {
    if (!data?.crm.hasApiKey) return null;
    const matching = findPresetForForm(data.crm);
    return matching?.slug ?? null;
  }, [data]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = (next: Partial<CrmIntegrationForm>) => {
    setForm((current) => current ? { ...current, ...next } : current);
  };

  const patchNested = <K extends "dbColumns" | "endpoints">(
    key: K,
    field: keyof CrmIntegrationForm[K],
    value: string,
  ) => {
    setForm((current) =>
      current
        ? { ...current, [key]: { ...current[key], [field]: value } }
        : current,
    );
  };

  const choosePreset = (preset: CrmPreset) => {
    setSelectedPreset(preset);
    setForm((current) => applyPreset(preset, current));
    setMode("preset");
    setTestResult(null);
    setShowAdvanced(false);
  };

  const chooseCustom = () => {
    setSelectedPreset(null);
    setMode("custom");
    setTestResult(null);
  };

  const backToPicker = () => {
    setMode("picker");
    setTestResult(null);
    setShowAdvanced(false);
  };

  const save = async () => {
    if (!form) return;
    setSaving(true);
    setTestResult(null);
    try {
      const next = await api.saveIntegrations(form);
      setData(next);
      const nextForm = { ...next.crm, apiKey: "" };
      setForm(nextForm);
      const matchingPreset = findPresetForForm(nextForm);
      if (matchingPreset) {
        setSelectedPreset(matchingPreset);
        setMode("preset");
      }
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    if (!form) return;
    setTesting(true);
    try {
      setTestResult(await api.testIntegration(form));
    } finally {
      setTesting(false);
    }
  };

  const canSave = form && (form.apiKey || form.hasApiKey) && (form.baseUrl || mode === "custom");

  return (
    <section className="space-y-5">
      <header>
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <KeyRound className="h-4 w-4 text-primary" aria-hidden="true" />
          Connect your CRM
        </h2>
        <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
          Pick your CRM, paste your API key, and we handle the rest. Lofty, Follow Up Boss, Sierra, BoldTrail and Brivity are pre-wired.
        </p>
      </header>
      <div className="space-y-4">
        {loading || !form ? (
          <div className="py-6 text-sm text-muted-foreground">Loading CRM settings...</div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {CRM_PRESETS.map((preset) => {
                const isSelected = mode === "preset" && selectedPreset?.slug === preset.slug;
                const isConnected = connectedPresetSlug === preset.slug;
                return (
                  <button
                    key={preset.slug}
                    type="button"
                    onClick={() => choosePreset(preset)}
                    aria-pressed={isSelected}
                    title={`${preset.label} — ${preset.description}`}
                    className={`group flex min-h-[44px] flex-col items-center gap-2 rounded-md border bg-transparent p-3 text-center transition-colors hover:border-ring hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${isSelected ? "border-primary" : "border-border/60"}`}
                  >
                    <div className="relative">
                      <img
                        src={preset.logo}
                        alt=""
                        width={40}
                        height={40}
                        loading="lazy"
                        decoding="async"
                        className="h-10 w-10 rounded-md object-contain p-1"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                          const fallback = e.currentTarget.nextElementSibling as HTMLElement | null;
                          if (fallback) fallback.style.display = "flex";
                        }}
                      />
                      <div className="hidden h-10 w-10 items-center justify-center rounded-md">
                        <Plug className="h-4 w-4 text-foreground/70" />
                      </div>
                      {isConnected && (
                        <CheckCircle2 className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full bg-card text-success" />
                      )}
                    </div>
                    <span className="w-full truncate text-xs font-medium text-foreground">{preset.label}</span>
                    <span
                      className={`mt-0.5 text-[0.7rem] ${isConnected ? "text-success" : "text-muted-foreground group-hover:text-foreground"}`}
                    >
                      {isConnected ? "Connected" : "Connect"}
                    </span>
                  </button>
                );
              })}
              <button
                type="button"
                onClick={chooseCustom}
                aria-pressed={mode === "custom"}
                title="Other — wire up any REST CRM"
                className={`group flex min-h-[44px] flex-col items-center gap-2 rounded-md border bg-transparent p-3 text-center transition-colors hover:border-ring hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${mode === "custom" ? "border-primary" : "border-border/60"}`}
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-md">
                  <Settings2 className="h-4 w-4 text-foreground/70" />
                </div>
                <span className="w-full truncate text-xs font-medium text-foreground">Other / Custom</span>
                <span className="mt-0.5 text-[0.7rem] text-muted-foreground group-hover:text-foreground">Wire up</span>
              </button>
            </div>

            {mode === "preset" && selectedPreset && (
              <div className="space-y-4 border-t border-border/50 pt-4">
                <div className="flex items-center gap-3">
                  <img
                    src={selectedPreset.logo}
                    alt=""
                    width={32}
                    height={32}
                    className="h-8 w-8 rounded-md object-contain p-1"
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                  <span className="text-base font-semibold text-foreground">{selectedPreset.label}</span>
                </div>
                {selectedPreset.notice && (
                  <div className="rounded-md border border-border bg-card px-3 py-2 text-sm leading-6 text-warning">
                    <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5 align-text-bottom" aria-hidden="true" />
                    {selectedPreset.notice}
                  </div>
                )}
                <div className="space-y-1.5">
                  <label className="text-sm font-medium text-foreground" htmlFor="crm-preset-api-key">
                    {selectedPreset.keyLabel}
                  </label>
                  <Input
                    id="crm-preset-api-key"
                    type="password"
                    value={form.apiKey ?? ""}
                    placeholder={form.hasApiKey ? `Saved · ${form.apiKeyPreview ?? "•••"}` : "Paste your API key"}
                    onChange={(e) => patch({ apiKey: e.target.value })}
                  />
                  <a
                    href={selectedPreset.helpUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                    Where do I find this? — {selectedPreset.helpText}
                  </a>
                </div>
                {testResult && (
                  <div className={`rounded-md border border-border bg-card px-3 py-2 text-sm ${testResult.success ? "text-success" : "text-warning"}`} role="status">
                    {testResult.message ?? testResult.error ?? "Test finished"}
                  </div>
                )}
                <div className="flex flex-wrap justify-between gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowAdvanced((v) => !v)}
                    aria-expanded={showAdvanced}
                  >
                    {showAdvanced ? "Hide advanced" : "Show advanced"}
                  </Button>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => void test()} disabled={testing || !canSave}>
                      {testing ? "Testing" : "Test connection"}
                    </Button>
                    <Button size="sm" onClick={() => void save()} disabled={saving || !canSave}>
                      {saving ? "Saving" : "Connect"}
                    </Button>
                  </div>
                </div>
                {showAdvanced && (
                  <div className="space-y-3 border-t border-border/40 pt-3">
                    <div className="text-xs text-muted-foreground">Advanced — pre-wired by preset</div>
                    <div className="grid gap-2 md:grid-cols-3">
                      <Input value={form.baseUrl} placeholder="base URL" onChange={(e) => patch({ baseUrl: e.target.value })} aria-label="Base URL" />
                      <Input value={form.authHeader} placeholder="header" onChange={(e) => patch({ authHeader: e.target.value })} aria-label="Auth header" />
                      <Input value={form.authPrefix} placeholder="prefix" onChange={(e) => patch({ authPrefix: e.target.value })} aria-label="Auth prefix" />
                      <Input value={form.endpoints.leads} placeholder="leads endpoint" onChange={(e) => patchNested("endpoints", "leads", e.target.value)} aria-label="Leads endpoint" />
                      <Input value={form.endpoints.lead} placeholder="lead endpoint" onChange={(e) => patchNested("endpoints", "lead", e.target.value)} aria-label="Lead endpoint" />
                      <Input value={form.endpoints.notes} placeholder="notes endpoint" onChange={(e) => patchNested("endpoints", "notes", e.target.value)} aria-label="Notes endpoint" />
                    </div>
                  </div>
                )}
              </div>
            )}
            {mode === "custom" && (
              <div className="space-y-4 border-t border-border/50 pt-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Settings2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    <span className="text-base font-semibold text-foreground">Custom CRM</span>
                  </div>
                  <Button variant="ghost" size="sm" onClick={backToPicker}>
                    Change CRM
                  </Button>
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <Input value={form.provider} placeholder="provider" onChange={(e) => patch({ provider: e.target.value })} aria-label="Provider" />
                  <Input value={form.label} placeholder="label" onChange={(e) => patch({ label: e.target.value })} aria-label="Label" />
                  <Input value={form.baseUrl} placeholder="https://api.example.com" onChange={(e) => patch({ baseUrl: e.target.value })} aria-label="Base URL" />
                  <Input value={form.apiKeyEnv} placeholder="CRM_API_KEY" onChange={(e) => patch({ apiKeyEnv: e.target.value })} aria-label="API key env var name" />
                  <Input value={form.apiKey ?? ""} type="password" placeholder={form.hasApiKey ? `API key ${form.apiKeyPreview ?? "saved"}` : "API key"} onChange={(e) => patch({ apiKey: e.target.value })} aria-label="API key" />
                  <Input value={form.authType} placeholder="header or query" onChange={(e) => patch({ authType: e.target.value })} aria-label="Auth type" />
                  <Input value={form.authHeader} placeholder="Authorization" onChange={(e) => patch({ authHeader: e.target.value })} aria-label="Auth header" />
                  <Input value={form.authPrefix} placeholder="Bearer " onChange={(e) => patch({ authPrefix: e.target.value })} aria-label="Auth prefix" />
                  <Input value={form.authQueryParam} placeholder="api_key" onChange={(e) => patch({ authQueryParam: e.target.value })} aria-label="Auth query param" />
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  <Input value={form.endpoints.leads} placeholder="/v1/leads" onChange={(e) => patchNested("endpoints", "leads", e.target.value)} aria-label="Leads endpoint" />
                  <Input value={form.endpoints.lead} placeholder="/v1/leads/:id" onChange={(e) => patchNested("endpoints", "lead", e.target.value)} aria-label="Lead endpoint" />
                  <Input value={form.endpoints.notes} placeholder="/v1/leads/:id/notes" onChange={(e) => patchNested("endpoints", "notes", e.target.value)} aria-label="Notes endpoint" />
                  <Input value={form.dbColumns.leadId} placeholder="crm_lead_id" onChange={(e) => patchNested("dbColumns", "leadId", e.target.value)} aria-label="Lead ID column" />
                  <Input value={form.dbColumns.stage} placeholder="crm_stage" onChange={(e) => patchNested("dbColumns", "stage", e.target.value)} aria-label="Stage column" />
                  <Input value={form.dbColumns.tags} placeholder="crm_tags" onChange={(e) => patchNested("dbColumns", "tags", e.target.value)} aria-label="Tags column" />
                </div>
                <div className="text-xs leading-6 text-muted-foreground">
                  <div>Config: <code className="bg-transparent p-0 font-mono">{data?.configPath}</code></div>
                  <div>Secrets: <code className="bg-transparent p-0 font-mono">{data?.secretsPath}</code></div>
                </div>
                {testResult && (
                  <div className={`rounded-md border border-border bg-card px-3 py-2 text-sm ${testResult.success ? "text-success" : "text-warning"}`} role="status">
                    {testResult.message ?? testResult.error ?? "Test finished"}
                  </div>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="outline" size="sm" onClick={() => void test()} disabled={testing}>
                    {testing ? "Testing" : "Test"}
                  </Button>
                  <Button size="sm" onClick={() => void save()} disabled={saving}>
                    {saving ? "Saving" : "Save CRM"}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

interface ChannelsPanelProps {
  config: Record<string, unknown> | null;
  setConfig: (next: Record<string, unknown>) => void;
}

function ChannelsPanel({ config, setConfig }: ChannelsPanelProps) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [envVars, setEnvVars] = useState<Record<string, { is_set: boolean; redacted_value: string | null }>>({});
  const [connectors, setConnectors] = useState<SourceConnectorsResponse | null>(null);
  const [composioAccounts, setComposioAccounts] = useState<ComposioConnectedAccount[]>([]);
  const [botTokenInput, setBotTokenInput] = useState("");
  const [savingBotToken, setSavingBotToken] = useState(false);
  const [channelEdits, setChannelEdits] = useState<Record<string, string>>({});
  const [savingChannel, setSavingChannel] = useState<string | null>(null);
  const [savingWhatsapp, setSavingWhatsapp] = useState(false);

  const reload = useCallback(async () => {
    try {
      const env = await api.getEnvVars();
      setEnvVars(env as unknown as Record<string, { is_set: boolean; redacted_value: string | null }>);
    } catch {
      // env endpoint failing is non-fatal; UI degrades to "not configured"
    }
    try {
      setConnectors(await api.getSourceConnectors());
    } catch { /* ignore */ }
    try {
      const status = await api.getComposioStatus();
      if (status.valid) {
        const conns = await api.getComposioConnections();
        const body = (conns.data as { items?: ComposioConnectedAccount[] } | ComposioConnectedAccount[]) ?? [];
        setComposioAccounts(Array.isArray(body) ? body : body.items ?? []);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const agents = useMemo(() => {
    const hub = (config?.["agent_hub"] as Record<string, unknown> | undefined) ?? {};
    const list = (hub["agents"] as Array<Record<string, unknown>> | undefined) ?? [];
    return list.map((agent) => {
      const meta = (agent.metadata as Record<string, unknown> | undefined) ?? {};
      return {
        id: String(agent.id ?? ""),
        name: String(agent.name ?? agent.id ?? ""),
        enabled: Boolean(agent.enabled),
        tokenEnv: String(meta.telegram_bot_token_env ?? ""),
        channelEnv: String(meta.telegram_target_env ?? ""),
      };
    });
  }, [config]);

  const botTokenSet = Boolean(envVars["TELEGRAM_BOT_TOKEN"]?.is_set);
  const botTokenPreview = envVars["TELEGRAM_BOT_TOKEN"]?.redacted_value ?? "";

  const saveBotToken = async () => {
    if (!botTokenInput.trim()) return;
    setSavingBotToken(true);
    try {
      await api.setEnvVar("TELEGRAM_BOT_TOKEN", botTokenInput.trim());
      setBotTokenInput("");
      await reload();
      showToast("Telegram bot token saved", "success");
    } catch (err) {
      showToast(`Failed to save token: ${String(err)}`, "error");
    } finally {
      setSavingBotToken(false);
    }
  };

  const saveChannelFor = async (key: string) => {
    const value = (channelEdits[key] ?? "").trim();
    setSavingChannel(key);
    try {
      if (!value) {
        await api.deleteEnvVar(key);
      } else {
        await api.setEnvVar(key, value);
      }
      setChannelEdits((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      await reload();
      showToast("Channel saved", "success");
    } catch (err) {
      showToast(`Failed: ${String(err)}`, "error");
    } finally {
      setSavingChannel(null);
    }
  };

  const startSetupChat = (label: string, prompt: string) => {
    const ts = String(Date.now());
    const seedText = `${label}\n\n${prompt}`;
    try { window.sessionStorage.setItem(`elevate:chat-seed:${ts}`, seedText); } catch { /* ignore */ }
    navigate(`/chat?new=${ts}&seed=${ts}`);
  };

  const sourceConnectorPrompt = async (sourceId: string, fallback: string): Promise<string> => {
    try {
      const resp = await api.getSourceConnectorPrompt(sourceId);
      const prompt = (resp.prompt || "").trim();
      return prompt || fallback;
    } catch {
      return fallback;
    }
  };

  const appleConnector = connectors?.connectors?.find((c) => c.id === "apple-messages");
  const appleConnected = appleConnector?.state === "connected" || appleConnector?.state === "import_only";

  const whatsappAccount = composioAccounts.find(
    (a) => (a.toolkit?.slug ?? "").toLowerCase().includes("whatsapp"),
  );
  const imessageAccount = composioAccounts.find(
    (a) => (a.toolkit?.slug ?? "").toLowerCase().includes("imessage"),
  );

  const whatsappCfg = (config?.["whatsapp"] as Record<string, unknown> | undefined) ?? {};
  const whatsappPrefix = String(whatsappCfg["reply_prefix"] ?? "");
  const [whatsappPrefixInput, setWhatsappPrefixInput] = useState<string | null>(null);
  const effectivePrefix = whatsappPrefixInput ?? whatsappPrefix;

  const saveWhatsappPrefix = async () => {
    if (!config) return;
    setSavingWhatsapp(true);
    try {
      const next = { ...config } as Record<string, unknown>;
      const wa = { ...(next.whatsapp as Record<string, unknown> | undefined ?? {}) };
      if (effectivePrefix === "") {
        delete wa.reply_prefix;
      } else {
        wa.reply_prefix = effectivePrefix;
      }
      next.whatsapp = wa;
      await api.saveConfig(next);
      setConfig(next);
      setWhatsappPrefixInput(null);
      showToast("WhatsApp settings saved", "success");
    } catch (err) {
      showToast(`Failed: ${String(err)}`, "error");
    } finally {
      setSavingWhatsapp(false);
    }
  };

  return (
    <section className="space-y-8">
      <header>
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <MessageCircle className="h-4 w-4 text-primary" aria-hidden="true" />
          Channels
        </h2>
        <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
          Where messages flow in and out. Set tokens, route agents to channels, and configure send/receive for Telegram, iMessage, and WhatsApp.
        </p>
      </header>

      {/* Telegram */}
      <div className="rounded-lg border border-border/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Telegram</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Inbound DMs, channel chats, and per-agent routing.</p>
          </div>
          <Badge variant={botTokenSet ? "success" : "outline"}>
            {botTokenSet ? "Bot token set" : "No bot token"}
          </Badge>
        </div>

        <div className="mt-3">
          <label className="block text-xs font-medium text-foreground/80">Bot token</label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            From <span className="font-mono">@BotFather</span>. Stored as <span className="font-mono">TELEGRAM_BOT_TOKEN</span> in your env.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Input
              type="password"
              autoComplete="off"
              placeholder={botTokenSet ? botTokenPreview || "•••••••• (currently set)" : "123456789:ABCdef..."}
              value={botTokenInput}
              onChange={(e) => setBotTokenInput(e.target.value)}
              className="h-8 text-sm"
            />
            <Button size="sm" onClick={() => void saveBotToken()} disabled={savingBotToken || !botTokenInput.trim()}>
              {savingBotToken ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>

        <div className="mt-4">
          <div className="text-xs font-medium text-foreground/80">Per-agent channel routing</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            One chat/topic per agent. Paste a Telegram chat ID (negative for groups) or run <span className="font-mono">/elevate pair</span> in the chat.
          </p>
          <div className="mt-2 divide-y divide-border/40 rounded-md border border-border/40">
            {agents.length === 0 && (
              <div className="px-3 py-2 text-xs text-muted-foreground/80">No agents configured.</div>
            )}
            {agents.map((agent) => {
              const currentPreview = envVars[agent.channelEnv]?.redacted_value ?? "";
              const currentSet = Boolean(envVars[agent.channelEnv]?.is_set);
              const editing = channelEdits[agent.channelEnv] !== undefined;
              const inputValue = editing ? channelEdits[agent.channelEnv] : "";
              return (
                <div key={agent.id} className="flex items-center gap-2 px-3 py-2">
                  <div className="min-w-[8rem] flex-shrink-0">
                    <div className="text-sm font-medium text-foreground">{agent.name}</div>
                    {!agent.enabled && <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70">disabled</span>}
                  </div>
                  <Input
                    className="h-7 flex-1 text-xs font-mono"
                    placeholder={currentSet ? currentPreview || "(set)" : "-1001234567890"}
                    value={inputValue}
                    onChange={(e) => setChannelEdits((p) => ({ ...p, [agent.channelEnv]: e.target.value }))}
                  />
                  {editing ? (
                    <Button
                      size="sm"
                      variant="default"
                      onClick={() => void saveChannelFor(agent.channelEnv)}
                      disabled={savingChannel === agent.channelEnv}
                    >
                      {savingChannel === agent.channelEnv ? "…" : "Save"}
                    </Button>
                  ) : currentSet ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setChannelEdits((p) => ({ ...p, [agent.channelEnv]: "" }))}
                    >
                      Change
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setChannelEdits((p) => ({ ...p, [agent.channelEnv]: "" }))}
                    >
                      Set
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              startSetupChat(
                "Channel setup: Telegram",
                "Help me wire up Telegram for Elevate. I want to test that my bot can receive messages, route to the right agent (executive-assistant by default), and send replies back. Walk me through pairing and verify with a test message.",
              )
            }
          >
            <Play className="h-3.5 w-3.5" />
            Setup chat
          </Button>
          <Link
            to="/env"
            className="inline-flex h-8 items-center gap-2 rounded-sm border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <KeyRound className="h-3.5 w-3.5" />
            All Telegram env vars
          </Link>
        </div>
      </div>

      {/* iMessage */}
      <div className="rounded-lg border border-border/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">iMessage</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Mac Messages: read history, contacts, conversation context. Sending uses Apple Messages or a Composio bridge.</p>
          </div>
          <Badge variant={appleConnected ? "success" : "outline"}>
            {appleConnected ? "Connected" : (appleConnector?.state ?? "Not set up")}
          </Badge>
        </div>

        <div className="mt-3 space-y-2 text-xs">
          <div className="flex items-center justify-between gap-3 rounded-md border border-border/40 px-3 py-2">
            <div>
              <div className="font-medium text-foreground">Receive (read Messages DB)</div>
              <div className="text-muted-foreground/80">Local sync from <span className="font-mono">~/Library/Messages/chat.db</span></div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void (async () => {
                const prompt = await sourceConnectorPrompt(
                  appleConnector?.id || "apple-messages",
                  "Help me wire iMessage so Elevate can read my Mac Messages history into the local message index. Walk me through Full Disk Access for the Elevate binary and run a first sync.",
                );
                startSetupChat(
                  "Channel setup: iMessage receive",
                  prompt,
                );
              })()}
            >
              <Play className="h-3.5 w-3.5" />
              Setup chat
            </Button>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-md border border-border/40 px-3 py-2">
            <div>
              <div className="font-medium text-foreground">Send</div>
              <div className="text-muted-foreground/80">
                {imessageAccount ? "Composio iMessage account connected" : "Native AppleScript send (built-in) or connect Composio for cloud sending"}
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                startSetupChat(
                  "Channel setup: iMessage send",
                  "Set up iMessage sending. My default is AppleScript on this Mac (so Messages.app needs to be running and signed in). Walk me through verifying it works with a test send to one of my contacts. If I should use Composio instead, tell me when.",
                )
              }
            >
              <Play className="h-3.5 w-3.5" />
              Setup chat
            </Button>
          </div>
        </div>
      </div>

      {/* WhatsApp */}
      <div className="rounded-lg border border-border/60 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">WhatsApp</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">Inbound and outbound WhatsApp via Composio (WhatsApp Business / Cloud API).</p>
          </div>
          <Badge variant={whatsappAccount ? "success" : "outline"}>
            {whatsappAccount ? "Connected" : "Not connected"}
          </Badge>
        </div>

        <div className="mt-3">
          <label className="block text-xs font-medium text-foreground/80">Reply prefix</label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Prepended to every outgoing WhatsApp message. Default is &quot;▲ *Elevate*&quot;. Empty string disables it.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Input
              className="h-8 text-sm font-mono"
              placeholder="▲ *Elevate*"
              value={effectivePrefix}
              onChange={(e) => setWhatsappPrefixInput(e.target.value)}
            />
            <Button
              size="sm"
              onClick={() => void saveWhatsappPrefix()}
              disabled={savingWhatsapp || whatsappPrefixInput === null}
            >
              {savingWhatsapp ? "…" : "Save"}
            </Button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              startSetupChat(
                "Channel setup: WhatsApp",
                "Help me wire WhatsApp send/receive for Elevate via Composio. I want one connected number that can receive messages into Elevate and send replies. Walk me through what I need (Business account, phone number, webhook) and verify with a test message.",
              )
            }
          >
            <Play className="h-3.5 w-3.5" />
            Setup chat
          </Button>
          <Link
            to="/settings#composio"
            className="inline-flex h-8 items-center gap-2 rounded-sm border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Plug className="h-3.5 w-3.5" />
            Composio integrations
          </Link>
        </div>
      </div>
    </section>
  );
}

interface MemoryPanelProps {
  config: Record<string, unknown> | null;
  setConfig: (next: Record<string, unknown>) => void;
}

function MemoryPanel({ config, setConfig }: MemoryPanelProps) {
  const { showToast } = useToast();
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (config) setDraft(structuredClone(config));
  }, [config]);

  if (!draft) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const get = (path: string): unknown => getNestedValue(draft, path);
  const set = (path: string, value: unknown) => setDraft(setNestedValue(draft, path, value) as Record<string, unknown>);

  const dirty = JSON.stringify(draft) !== JSON.stringify(config);

  const save = async () => {
    setSaving(true);
    try {
      await api.saveConfig(draft);
      setConfig(draft);
      showToast("Memory settings saved", "success");
    } catch (err) {
      showToast(`Failed: ${String(err)}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const memoryEnabled = Boolean(get("memory.memory_enabled"));
  const userProfileEnabled = Boolean(get("memory.user_profile_enabled"));
  const provider = String(get("memory.provider") ?? "");
  const memoryCharLimit = Number(get("memory.memory_char_limit") ?? 2200);
  const userCharLimit = Number(get("memory.user_char_limit") ?? 1375);

  const autoExtract = Boolean(get("plugins.elevate-memory-store.auto_extract"));
  const turnJournal = Boolean(get("plugins.elevate-memory-store.turn_journal_enabled"));
  const dailyOrganize = Boolean(get("plugins.elevate-memory-store.daily_organize_enabled"));
  const graphRecall = Boolean(get("plugins.elevate-memory-store.graph_recall_enabled"));
  const recentRecall = Boolean(get("plugins.elevate-memory-store.recent_recall_enabled"));
  const embeddingEnabled = Boolean(get("plugins.elevate-memory-store.embedding_enabled"));

  return (
    <section className="space-y-6">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Brain className="h-4 w-4 text-primary" aria-hidden="true" />
            Memory
          </h2>
          <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
            What Elevate remembers between sessions. Curated memory is injected into the system prompt; the memory store is the durable backing index.
          </p>
        </div>
        <Button size="sm" onClick={() => void save()} disabled={saving || !dirty}>
          <Save className="h-3.5 w-3.5" />
          {saving ? "Saving…" : "Save"}
        </Button>
      </header>

      <div className="rounded-lg border border-border/60 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Curated memory (injected into prompt)</h3>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Enable curated memory</span>
          <Switch checked={memoryEnabled} onCheckedChange={(v) => set("memory.memory_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Include user profile</span>
          <Switch checked={userProfileEnabled} onCheckedChange={(v) => set("memory.user_profile_enabled", v)} />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted-foreground">Memory char limit</label>
            <Input
              type="number"
              className="mt-1 h-8 text-sm"
              value={memoryCharLimit}
              onChange={(e) => set("memory.memory_char_limit", Number(e.target.value) || 0)}
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground">User profile char limit</label>
            <Input
              type="number"
              className="mt-1 h-8 text-sm"
              value={userCharLimit}
              onChange={(e) => set("memory.user_char_limit", Number(e.target.value) || 0)}
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-muted-foreground">External provider</label>
          <select
            className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-sm"
            value={provider}
            onChange={(e) => set("memory.provider", e.target.value)}
          >
            <option value="">Built-in only</option>
            <option value="openviking">OpenViking</option>
            <option value="mem0">Mem0</option>
            <option value="hindsight">Hindsight</option>
            <option value="holographic">Holographic</option>
            <option value="retaindb">RetainDB</option>
            <option value="byterover">Byterover</option>
          </select>
        </div>
      </div>

      <div className="rounded-lg border border-border/60 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Memory store (durable index)</h3>
        <p className="text-xs text-muted-foreground">
          Local SQLite-backed memory store at <span className="font-mono">$ELEVATE_HOME/memory_store.db</span>.
        </p>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Auto-extract facts from each turn</span>
          <Switch checked={autoExtract} onCheckedChange={(v) => set("plugins.elevate-memory-store.auto_extract", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Turn-by-turn journal</span>
          <Switch checked={turnJournal} onCheckedChange={(v) => set("plugins.elevate-memory-store.turn_journal_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Daily organize (compress + cluster)</span>
          <Switch checked={dailyOrganize} onCheckedChange={(v) => set("plugins.elevate-memory-store.daily_organize_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Recent recall (last few turns)</span>
          <Switch checked={recentRecall} onCheckedChange={(v) => set("plugins.elevate-memory-store.recent_recall_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Graph recall (concept neighbors)</span>
          <Switch checked={graphRecall} onCheckedChange={(v) => set("plugins.elevate-memory-store.graph_recall_enabled", v)} />
        </label>

        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-foreground/90">Embedding-based recall</span>
          <Switch checked={embeddingEnabled} onCheckedChange={(v) => set("plugins.elevate-memory-store.embedding_enabled", v)} />
        </label>
      </div>
    </section>
  );
}

interface PluginsPanelProps {
  config: Record<string, unknown>;
  setConfig: (next: Record<string, unknown>) => void;
}

function PluginsPanel({ config, setConfig }: PluginsPanelProps) {
  const [discovered, setDiscovered] = useState<Array<{
    name: string;
    label: string;
    description: string;
    version: string;
    source: string;
  }> | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const plugins = await api.getPlugins();
      setDiscovered(
        plugins.map((p) => ({
          name: p.name,
          label: p.label || p.name,
          description: p.description || "",
          version: p.version || "0.0.0",
          source: p.source || "user",
        })),
      );
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load plugins");
      setDiscovered([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRescan = useCallback(async () => {
    setRescanning(true);
    try {
      await api.rescanPlugins();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rescan failed");
    } finally {
      setRescanning(false);
    }
  }, [load]);

  const enabled = useMemo(() => {
    const raw = getNestedValue(config, "plugins.enabled");
    return Array.isArray(raw) ? (raw as string[]) : [];
  }, [config]);
  const disabled = useMemo(() => {
    const raw = getNestedValue(config, "plugins.disabled");
    return Array.isArray(raw) ? (raw as string[]) : [];
  }, [config]);

  const togglePlugin = (name: string, on: boolean) => {
    const nextEnabled = on
      ? [...new Set([...enabled, name])]
      : enabled.filter((n) => n !== name);
    const nextDisabled = on
      ? disabled.filter((n) => n !== name)
      : disabled;
    let next = setNestedValue(config, "plugins.enabled", nextEnabled);
    next = setNestedValue(next, "plugins.disabled", nextDisabled);
    setConfig(next);
  };

  const discoveredNames = new Set((discovered ?? []).map((p) => p.name));
  const orphanEnabled = enabled.filter((n) => !discoveredNames.has(n));

  return (
    <section className="space-y-5">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Puzzle className="h-4 w-4 text-primary" aria-hidden="true" />
            Installed plugins
          </h2>
          <p className="mt-1 max-w-prose text-sm leading-6 text-muted-foreground">
            Plugins live in <code className="bg-transparent p-0 font-mono text-xs">~/.elevate/plugins/</code> and bundled directories. Toggle one on to load it next time the agent starts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {discovered ? `${discovered.length} discovered` : "Loading..."}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleRescan()}
            disabled={rescanning}
            aria-label="Rescan plugins"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${rescanning ? "animate-spin" : ""}`} aria-hidden="true" />
            Rescan
          </Button>
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-border bg-card px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {discovered === null ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading plugins…</p>
      ) : discovered.length === 0 ? (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          No plugins discovered. Drop a plugin directory under <code className="bg-transparent p-0 font-mono text-xs">~/.elevate/plugins/</code> and click Rescan.
        </p>
      ) : (
        <ul className="divide-y divide-border/50 border-y border-border/50">
          {discovered.map((plugin) => {
            const isOn = enabled.includes(plugin.name);
            return (
              <li key={plugin.name} className="py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">{plugin.label}</span>
                      <Badge variant="outline" className="text-[0.7rem]">
                        {plugin.source}
                      </Badge>
                      <span className="font-mono text-[0.7rem] text-foreground/60">v{plugin.version}</span>
                    </div>
                    {plugin.description && (
                      <p className="mt-1 text-sm leading-6 text-foreground/80">
                        {plugin.description}
                      </p>
                    )}
                    <code className="mt-1 block bg-transparent p-0 font-mono text-[0.7rem] text-foreground/55">
                      {plugin.name}
                    </code>
                  </div>
                  <div className="shrink-0 pt-0.5">
                    <Switch
                      checked={isOn}
                      onCheckedChange={(v) => togglePlugin(plugin.name, v)}
                      aria-label={`${isOn ? "Disable" : "Enable"} ${plugin.label}`}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {orphanEnabled.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
            Enabled but not found
          </div>
          <p className="text-xs leading-6 text-foreground/70">
            These plugin names are in your config but no matching directory was discovered. Remove them or install the plugin.
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {orphanEnabled.map((name) => (
              <li
                key={name}
                className="inline-flex items-center gap-1.5 rounded-md border border-border/50 px-2 py-1 text-xs"
              >
                <code className="bg-transparent p-0 font-mono">{name}</code>
                <button
                  type="button"
                  onClick={() => togglePlugin(name, false)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={`Remove ${name} from enabled list`}
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ConfigPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [yamlMode, setYamlMode] = useState(false);
  const [yamlText, setYamlText] = useState("");
  const [yamlLoading, setYamlLoading] = useState(false);
  const [yamlSaving, setYamlSaving] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>("");
  const [activePane, setActivePane] = useState<"config" | "channels" | "memory" | "composio" | "connectors" | "crm" | "setup">("channels");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { toast, showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();
  const { setEnd } = usePageHeader();
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace("#", "");
    if (!id) return;
    // Map hash to its containing pane so deep-links from outside (e.g.
    // /config#connectors from the leads onboarding card) actually reveal
    // the pane that hosts the section before scroll-into-view tries to
    // resolve the anchor.
    const PANE_BY_HASH: Record<string, typeof activePane> = {
      channels: "channels",
      memory: "memory",
      connectors: "connectors",
      composio: "composio",
      crm: "crm",
      setup: "setup",
    };
    const targetPane = PANE_BY_HASH[id];
    if (targetPane && targetPane !== activePane) {
      setActivePane(targetPane);
    }
    const tryScroll = (attempt = 0) => {
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (attempt < 10) window.setTimeout(() => tryScroll(attempt + 1), 100);
    };
    tryScroll();
  }, [location.hash, activePane]);

  useLayoutEffect(() => {
    setEnd(null);
    return () => setEnd(null);
  }, [setEnd]);

  function prettyCategoryName(cat: string): string {
    const key = cat as keyof typeof t.config.categories;
    if (t.config.categories[key]) return t.config.categories[key];
    return cat.charAt(0).toUpperCase() + cat.slice(1);
  }

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => {});
    api
      .getSchema()
      .then((resp) => {
        setSchema(resp.fields as Record<string, Record<string, unknown>>);
        setCategoryOrder(resp.category_order ?? []);
      })
      .catch(() => {});
    api.getDefaults().then(setDefaults).catch(() => {});
  }, []);

  // Load YAML when switching to YAML mode
  useEffect(() => {
    if (yamlMode) {
      setYamlLoading(true);
      api
        .getConfigRaw()
        .then((resp) => setYamlText(resp.yaml))
        .catch(() => showToast(t.config.failedToLoadRaw, "error"))
        .finally(() => setYamlLoading(false));
    }
  }, [yamlMode]);

  /* ---- Categories ---- */
  const categories = useMemo(() => {
    if (!schema) return [];
    const allCats = [...new Set(Object.values(schema).map((s) => String(s.category ?? "general")))];
    const ordered = categoryOrder.filter((c) => allCats.includes(c));
    const extra = allCats.filter((c) => !categoryOrder.includes(c)).sort();
    return [...ordered, ...extra];
  }, [schema, categoryOrder]);

  const visibleCategories = useMemo(
    () =>
      showAdvanced
        ? categories
        : categories.filter((category) => !ADVANCED_CATEGORIES.has(category)),
    [categories, showAdvanced],
  );

  useEffect(() => {
    if (!visibleCategories.length) return;
    if (!activeCategory || !visibleCategories.includes(activeCategory)) {
      setActiveCategory(visibleCategories[0]);
    }
  }, [activeCategory, visibleCategories]);

  /* ---- Search ---- */
  const isSearching = searchQuery.trim().length > 0;
  const lowerSearch = searchQuery.toLowerCase();

  const searchMatchedFields = useMemo(() => {
    if (!isSearching || !schema) return [];
    return Object.entries(schema).filter(([key, s]) => {
      const label = key.split(".").pop() ?? key;
      const humanLabel = label.replace(/_/g, " ");
      return (
        key.toLowerCase().includes(lowerSearch) ||
        humanLabel.toLowerCase().includes(lowerSearch) ||
        String(s.category ?? "").toLowerCase().includes(lowerSearch) ||
        String(s.description ?? "").toLowerCase().includes(lowerSearch)
      );
    });
  }, [isSearching, lowerSearch, schema]);

  /* ---- Active tab fields ---- */
  const activeFields = useMemo(() => {
    if (!schema || isSearching) return [];
    return Object.entries(schema).filter(([key, s]) => {
      if (String(s.category ?? "general") !== activeCategory) return false;
      // The PluginsPanel replaces the raw enabled/disabled list inputs.
      if (activeCategory === "plugins" && (key === "plugins.enabled" || key === "plugins.disabled")) {
        return false;
      }
      return true;
    });
  }, [schema, activeCategory, isSearching]);

  /* ---- Handlers ---- */
  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.saveConfig(config);
      showToast(t.config.configSaved, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleYamlSave = async () => {
    setYamlSaving(true);
    try {
      await api.saveConfigRaw(yamlText);
      showToast(t.config.yamlConfigSaved, "success");
      api.getConfig().then(setConfig).catch(() => {});
    } catch (e) {
      showToast(`${t.config.failedToSaveYaml}: ${e}`, "error");
    } finally {
      setYamlSaving(false);
    }
  };

  const handleReset = () => {
    if (defaults) setConfig(structuredClone(defaults));
  };

  const handleExport = () => {
    if (!config) return;
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "elevate-config.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const text = String(reader.result ?? "");
        const fileName = file.name.toLowerCase();
        if (fileName.endsWith(".yaml") || fileName.endsWith(".yml")) {
          setYamlText(text);
          setYamlMode(true);
          showToast("YAML imported — review and save", "success");
        } else {
          const imported = JSON.parse(text);
          setConfig(imported);
          setYamlMode(false);
          showToast(`${t.config.configImported}. Click Save to write it.`, "success");
        }
      } catch {
        showToast(t.config.invalidJson, "error");
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    };
    reader.readAsText(file);
  };

  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      setCopiedCommand(command);
      showToast("Command copied", "success");
      window.setTimeout(() => setCopiedCommand(null), 1600);
    } catch {
      showToast("Could not copy command", "error");
    }
  };

  /* ---- Loading ---- */
  if (!config || !schema) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading config…</p>
    );
  }

  /* ---- Render field list (shared between search & normal) ---- */
  const renderFields = (fields: [string, Record<string, unknown>][], showCategory = false) => {
    let lastSection = "";
    let lastCat = "";
    return fields.map(([key, s]) => {
      const parts = key.split(".");
      const section = parts.length > 1 ? parts[0] : "";
      const cat = String(s.category ?? "general");
      const showCatBadge = showCategory && cat !== lastCat;
      const showSection = !showCategory && section && section !== lastSection && section !== activeCategory;
      lastSection = section;
      lastCat = cat;

      return (
        <div key={key}>
          {showCatBadge && (
            <div className="mt-10 mb-2 first:mt-2">
              <div className="flex items-center gap-2">
                <CategoryIcon category={cat} className="h-4 w-4 text-muted-foreground" />
                <span className="text-base font-semibold text-foreground">
                  {prettyCategoryName(cat)}
                </span>
              </div>
            </div>
          )}
          {showSection && (
            <div className="mt-10 mb-2 first:mt-2">
              <span className="text-sm font-semibold text-foreground">
                {section.charAt(0).toUpperCase() + section.slice(1).replace(/_/g, " ")}
              </span>
            </div>
          )}
          <div className="py-6 first:pt-2">
            <AutoField
              schemaKey={key}
              schema={s}
              value={getNestedValue(config, key)}
              onChange={(v) => setConfig(setNestedValue(config, key, v))}
            />
          </div>
        </div>
      );
    });
  };

  const sidebarItems = [
    ...visibleCategories.map((cat) => ({
      id: cat,
      pane: "config" as const,
      label: prettyCategoryName(cat),
      icon: <CategoryIcon category={cat} className="h-4 w-4" />,
    })),
  ];

  const integrationItems = [
    { id: "channels", pane: "channels" as const, label: "Channels", icon: <MessageCircle className="h-4 w-4" /> },
    { id: "memory", pane: "memory" as const, label: "Memory", icon: <Brain className="h-4 w-4" /> },
    { id: "connectors", pane: "connectors" as const, label: "Sources", icon: <Network className="h-4 w-4" /> },
    { id: "crm", pane: "crm" as const, label: "CRM", icon: <Users className="h-4 w-4" /> },
    { id: "composio", pane: "composio" as const, label: "Composio", icon: <Plug className="h-4 w-4" /> },
    { id: "setup", pane: "setup" as const, label: "Setup commands", icon: <Wrench className="h-4 w-4" /> },
  ];

  const activeNavLabel =
    activePane === "config"
      ? prettyCategoryName(activeCategory) || "Settings"
      : integrationItems.find((i) => i.pane === activePane)?.label ?? "Settings";

  return (
    <div className="flex h-dvh flex-col justify-center md:flex-row md:pt-[3.25rem]">
      <Toast toast={toast} />
      <input ref={fileInputRef} type="file" accept=".json,.yaml,.yml" className="hidden" onChange={handleImport} />

      {/* Desktop drag-region spacer — matches chat title bar height so macOS
          traffic lights have breathing room and the page header doesn't crash
          into the very top of the window. */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-x-0 top-0 hidden h-[3.25rem] md:block"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      />

      {/* Mobile top bar */}
      <div className="flex items-center gap-2 border-b border-border/50 px-4 py-2 md:hidden">
        <Link
          to="/"
          aria-label="Back to app"
          className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
        </Link>
        <button
          type="button"
          aria-label="Open settings navigation"
          aria-expanded={mobileNavOpen}
          onClick={() => setMobileNavOpen(true)}
          className="flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-foreground transition-colors hover:bg-foreground/[0.06]"
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
          <span>{activeNavLabel}</span>
        </button>
      </div>

      {/* Mobile drawer scrim */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      <div className="flex h-full min-h-0 w-full flex-1 max-w-[1280px] mx-auto">
      {/* ---- Sidebar ---- */}
      <aside
        className={`
          ${mobileNavOpen ? "fixed inset-y-0 left-0 z-50 w-72 bg-background shadow-xl" : "hidden"}
          md:static md:z-auto md:block md:w-64 md:shadow-none md:bg-transparent
          shrink-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden
        `}
        aria-label="Settings navigation"
      >
        <div className="py-4">
          {/* Back + title (desktop) / Close (mobile drawer) */}
          <div className="flex items-center gap-2 px-4 pb-3">
            <Link
              to="/"
              aria-label="Back to app"
              className="hidden md:flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground hover:bg-foreground/[0.06]"
            >
              <ChevronLeft className="h-4 w-4" />
            </Link>
            <span className="text-sm font-semibold text-foreground">Settings</span>
            <button
              type="button"
              aria-label="Close navigation"
              onClick={() => setMobileNavOpen(false)}
              className="ml-auto flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground md:hidden"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Search */}
          <div className="px-3 pb-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              <Input
                className="h-9 pl-8 pr-9 text-sm"
                placeholder={t.common.search}
                aria-label="Search settings"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  aria-label="Clear search"
                  className="absolute right-1 top-1/2 -translate-y-1/2 flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                  onClick={() => setSearchQuery("")}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* Primary navigation */}
          <nav className="flex flex-col gap-0.5 px-2" aria-label="Settings">
            {integrationItems.map((item) => {
              const isActive = activePane === item.pane;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => {
                    setSearchQuery("");
                    setActivePane(item.pane);
                    setMobileNavOpen(false);
                  }}
                  className={`
                    flex min-h-[36px] items-center gap-2.5 rounded-md px-3 py-1.5 text-left text-sm
                    transition-colors
                    ${isActive
                      ? "bg-foreground/[0.08] text-foreground font-medium"
                      : "text-foreground/85 hover:text-foreground hover:bg-foreground/[0.04]"
                    }
                  `}
                >
                  <span className={isActive ? "text-foreground" : "text-foreground/70"} aria-hidden="true">{item.icon}</span>
                  <span className="flex-1 truncate">{item.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Advanced (schema-driven) categories — collapsed by default */}
          <div className="mx-3 my-3 border-t border-border/50" />
          <div className="px-3">
            <button
              type="button"
              aria-expanded={showAdvanced}
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex w-full min-h-[36px] items-center justify-between rounded-md px-3 py-1.5 text-sm text-muted-foreground/80 transition-colors hover:text-foreground hover:bg-foreground/[0.04]"
            >
              <span className="flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Advanced settings
              </span>
              <span className="text-xs">{showAdvanced ? "Hide" : "Show"}</span>
            </button>
          </div>

          {showAdvanced && (
            <nav className="mt-1 flex flex-col gap-0.5 px-2" aria-label="Advanced settings categories">
              {sidebarItems.map((item) => {
                const isActive = !isSearching && activePane === "config" && activeCategory === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => {
                      setSearchQuery("");
                      setActivePane("config");
                      setActiveCategory(item.id);
                      setMobileNavOpen(false);
                    }}
                    className={`
                      flex min-h-[32px] items-center gap-2.5 rounded-md px-3 py-1 text-left text-[13px]
                      transition-colors
                      ${isActive
                        ? "bg-foreground/[0.08] text-foreground font-medium"
                        : "text-foreground/75 hover:text-foreground hover:bg-foreground/[0.04]"
                      }
                    `}
                  >
                    <span className={isActive ? "text-foreground" : "text-foreground/60"} aria-hidden="true">{item.icon}</span>
                    <span className="flex-1 truncate">{item.label}</span>
                  </button>
                );
              })}
            </nav>
          )}
        </div>
      </aside>

      {/* ---- Content ---- */}
      <div className="flex-1 overflow-y-auto min-w-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="mx-auto max-w-4xl px-4 py-6 md:px-12 md:py-8">

          {/* ---- Channels pane ---- */}
          {activePane === "channels" && config && <ChannelsPanel config={config} setConfig={setConfig} />}

          {/* ---- Memory pane ---- */}
          {activePane === "memory" && config && <MemoryPanel config={config} setConfig={setConfig} />}

          {/* ---- Composio pane ---- */}
          {activePane === "composio" && <ComposioPanel />}

          {/* ---- Source connectors pane ---- */}
          {activePane === "connectors" && <SourceConnectorSettingsPanel />}

          {/* ---- CRM pane ---- */}
          {activePane === "crm" && <CrmIntegrationSettingsPanel />}

          {/* ---- Setup commands pane ---- */}
          {activePane === "setup" && (
            <div>
              <h2 className="text-lg font-semibold text-foreground">Setup commands</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Run these in your terminal to configure the agent runtime.
              </p>
              <div className="mt-6 space-y-4">
                {SETUP_STEPS.map((step) => (
                  <div key={step.label} className="border-b border-border/40 pb-4 last:border-0">
                    <div className="text-sm font-medium text-foreground">{step.label}</div>
                    <p className="mt-1 text-sm text-muted-foreground">{step.description}</p>
                    <button
                      type="button"
                      onClick={() => void copyCommand(step.command)}
                      className="mt-2 flex items-center gap-2 rounded-lg bg-foreground/[0.05] px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-foreground/[0.09] hover:text-foreground"
                    >
                      <code className="truncate bg-transparent p-0">{step.command}</code>
                      <Copy className="h-3.5 w-3.5 shrink-0" />
                    </button>
                    {copiedCommand === step.command && (
                      <div className="mt-1 text-[0.68rem] text-success">Copied</div>
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-8">
                <h3 className="text-sm font-semibold text-foreground">Import / Export</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Bring in an exported config, edit raw YAML, or manage API keys.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => fileInputRef.current?.click()}>
                    <Upload className="h-3.5 w-3.5" />
                    Import JSON/YAML
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleExport}>
                    <Download className="h-3.5 w-3.5" />
                    Export
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => { setYamlMode(true); setActivePane("config"); }}>
                    <Code className="h-3.5 w-3.5" />
                    Edit raw YAML
                  </Button>
                  <Link
                    to="/env"
                    className="inline-flex h-8 items-center gap-2 rounded-sm border border-border bg-card px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <KeyRound className="h-3.5 w-3.5" />
                    Keys and OAuth
                  </Link>
                </div>
              </div>
            </div>
          )}

          {/* ---- Config pane ---- */}
          {activePane === "config" && (
            <>
              {/* YAML mode */}
              {yamlMode ? (
                <div>
                  <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-foreground">{t.config.rawYaml}</h2>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setYamlMode(false)}>
                        <FormInput className="h-3.5 w-3.5" />
                        {t.common.form}
                      </Button>
                      <Button size="sm" onClick={handleYamlSave} disabled={yamlSaving}>
                        <Save className="h-3.5 w-3.5" />
                        {yamlSaving ? t.common.saving : t.common.save}
                      </Button>
                    </div>
                  </div>
                  <div className="mt-4 rounded-md border border-border overflow-hidden">
                    {yamlLoading ? (
                      <p className="px-3 py-3 text-xs text-muted-foreground/80">Loading YAML…</p>
                    ) : (
                      <textarea
                        className="flex min-h-[600px] w-full bg-transparent px-4 py-3 text-sm font-mono leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none"
                        value={yamlText}
                        onChange={(e) => setYamlText(e.target.value)}
                        spellCheck={false}
                      />
                    )}
                  </div>
                </div>
              ) : isSearching ? (
                /* Search results */
                <div>
                  <h2 className="text-lg font-semibold text-foreground">{t.config.searchResults}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {searchMatchedFields.length} {t.config.fields.replace("{s}", searchMatchedFields.length !== 1 ? "s" : "")} matching &ldquo;{searchQuery}&rdquo;
                  </p>
                  <div className="mt-4">
                    {searchMatchedFields.length === 0 ? (
                      <p className="px-1 py-1 text-xs text-muted-foreground/80">
                        {t.config.noFieldsMatch.replace("{query}", searchQuery)}
                      </p>
                    ) : (
                      renderFields(searchMatchedFields, true)
                    )}
                  </div>
                </div>
              ) : (
                /* Active category */
                <div>
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-foreground">{prettyCategoryName(activeCategory)}</h2>
                      <p className="mt-0.5 text-xs text-foreground/70">
                        {activeFields.length} settings
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="ghost" size="sm" onClick={handleReset} title={t.config.resetDefaults}>
                        <RotateCcw className="h-3.5 w-3.5" />
                      </Button>
                      <Button size="sm" onClick={handleSave} disabled={saving}>
                        <Save className="h-3.5 w-3.5" />
                        {saving ? t.common.saving : t.common.save}
                      </Button>
                    </div>
                  </div>
                  {activeCategory === "plugins" && (
                    <div className="mt-6">
                      <PluginsPanel config={config} setConfig={setConfig} />
                    </div>
                  )}
                  <div className="mt-4">
                    {renderFields(activeFields)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}

```

---
## `src/pages/AnalyticsPage.tsx`
```tsx
import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import {
  BarChart3,
  Brain,
  Cpu,
  Hash,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AnalyticsResponse, AnalyticsDailyEntry, AnalyticsModelEntry, AnalyticsSkillEntry } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useI18n } from "@/i18n";

const PERIODS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

const CHART_HEIGHT_PX = 160;

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatDate(day: string): string {
  try {
    const d = new Date(day + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return day;
  }
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function TokenBarChart({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
  if (daily.length === 0) return null;

  const maxTokens = Math.max(...daily.map((d) => d.input_tokens + d.output_tokens), 1);

  return (
    <Card role="region" aria-labelledby="analytics-daily-tokens">
      <CardHeader>
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-daily-tokens" className="text-base">{t.analytics.dailyTokenUsage}</CardTitle>
        </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <div className="h-2.5 w-2.5" style={{ background: "var(--midground)" }} />
            {t.analytics.input}
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2.5 w-2.5 bg-[var(--color-success)]" />
            {t.analytics.output}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-[2px]" style={{ height: CHART_HEIGHT_PX }}>
          {daily.map((d) => {
            const total = d.input_tokens + d.output_tokens;
            const inputH = Math.round((d.input_tokens / maxTokens) * CHART_HEIGHT_PX);
            const outputH = Math.round((d.output_tokens / maxTokens) * CHART_HEIGHT_PX);
            return (
              <div
                key={d.day}
                className="flex-1 min-w-0 group relative flex flex-col justify-end"
                style={{ height: CHART_HEIGHT_PX }}
              >
                {/* Tooltip */}
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10 pointer-events-none">
                  <div className="whitespace-nowrap rounded-md border border-border bg-card px-2.5 py-1.5 text-[10px] text-foreground">
                    <div className="font-medium">{formatDate(d.day)}</div>
                    <div>{t.analytics.input}: {formatTokens(d.input_tokens)}</div>
                    <div>{t.analytics.output}: {formatTokens(d.output_tokens)}</div>
                    <div>{t.analytics.total}: {formatTokens(total)}</div>
                  </div>
                </div>
                {/* Input bar */}
                <div
                  className="w-full"
                  style={{
                    backgroundColor: "color-mix(in srgb, var(--midground-base) 70%, transparent)",
                    height: Math.max(inputH, total > 0 ? 1 : 0),
                  }}
                />
                {/* Output bar */}
                <div
                  className="w-full bg-[var(--color-success)]/70"
                  style={{ height: Math.max(outputH, d.output_tokens > 0 ? 1 : 0) }}
                />
              </div>
            );
          })}
        </div>
        {/* X-axis labels */}
        <div className="flex justify-between mt-2 text-[10px] text-muted-foreground">
          <span>{daily.length > 0 ? formatDate(daily[0].day) : ""}</span>
          {daily.length > 2 && (
            <span>{formatDate(daily[Math.floor(daily.length / 2)].day)}</span>
          )}
          <span>{daily.length > 1 ? formatDate(daily[daily.length - 1].day) : ""}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function DailyTable({ daily }: { daily: AnalyticsDailyEntry[] }) {
  const { t } = useI18n();
  if (daily.length === 0) return null;

  const sorted = [...daily].reverse();

  return (
    <Card role="region" aria-labelledby="analytics-daily-breakdown">
      <CardHeader>
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-daily-breakdown" className="text-base">{t.analytics.dailyBreakdown}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs">
                <th className="text-left py-2 pr-4 font-medium">{t.analytics.date}</th>
                <th className="text-right py-2 px-4 font-medium">{t.sessions.title}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.input}</th>
                <th className="text-right py-2 pl-4 font-medium">{t.analytics.output}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((d) => {
                return (
                  <tr key={d.day} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                    <td className="py-2 pr-4 font-medium">{formatDate(d.day)}</td>
                    <td className="text-right py-2 px-4 text-muted-foreground">{d.sessions}</td>
                    <td className="text-right py-2 px-4">
                      <span style={{ color: "var(--midground)" }}>{formatTokens(d.input_tokens)}</span>
                    </td>
                    <td className="text-right py-2 pl-4">
                      <span className="text-[var(--color-success)]">{formatTokens(d.output_tokens)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function ModelTable({ models }: { models: AnalyticsModelEntry[] }) {
  const { t } = useI18n();
  if (models.length === 0) return null;

  const sorted = [...models].sort(
    (a, b) => b.input_tokens + b.output_tokens - (a.input_tokens + a.output_tokens),
  );

  return (
    <Card role="region" aria-labelledby="analytics-per-model">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-per-model" className="text-base">{t.analytics.perModelBreakdown}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs">
                <th className="text-left py-2 pr-4 font-medium">{t.analytics.model}</th>
                <th className="text-right py-2 px-4 font-medium">{t.sessions.title}</th>
                <th className="text-right py-2 pl-4 font-medium">{t.analytics.tokens}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((m) => (
                <tr key={m.model} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                  <td className="py-2 pr-4">
                    <span className="font-mono-ui text-xs">{m.model}</span>
                  </td>
                  <td className="text-right py-2 px-4 text-muted-foreground">{m.sessions}</td>
                  <td className="text-right py-2 pl-4">
                    <span style={{ color: "var(--midground)" }}>{formatTokens(m.input_tokens)}</span>
                    {" / "}
                    <span className="text-[var(--color-success)]">{formatTokens(m.output_tokens)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function SkillTable({ skills }: { skills: AnalyticsSkillEntry[] }) {
  const { t } = useI18n();
  if (skills.length === 0) return null;

  return (
    <Card role="region" aria-labelledby="analytics-top-skills">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-muted-foreground" />
          <CardTitle id="analytics-top-skills" className="text-base">{t.analytics.topSkills}</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-xs">
                <th className="text-left py-2 pr-4 font-medium">{t.analytics.skill}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.loads}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.edits}</th>
                <th className="text-right py-2 px-4 font-medium">{t.analytics.total}</th>
                <th className="text-right py-2 pl-4 font-medium">{t.analytics.lastUsed}</th>
              </tr>
            </thead>
            <tbody>
              {skills.map((skill) => (
                <tr key={skill.skill} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                  <td className="py-2 pr-4">
                    <span className="font-mono-ui text-xs">{skill.skill}</span>
                  </td>
                  <td className="text-right py-2 px-4 text-muted-foreground">{skill.view_count}</td>
                  <td className="text-right py-2 px-4 text-muted-foreground">{skill.manage_count}</td>
                  <td className="text-right py-2 px-4">{skill.total_count}</td>
                  <td className="text-right py-2 pl-4 text-muted-foreground">
                    {skill.last_used_at ? timeAgo(skill.last_used_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .getAnalytics(days)
      .then(setData)
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [days]);

  useLayoutEffect(() => {
    const periodLabel =
      PERIODS.find((p) => p.days === days)?.label ?? `${days}d`;
    setAfterTitle(
      <span className="flex items-center gap-2">
        {loading && (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        )}
        <Badge variant="secondary" className="text-[10px]">
          {periodLabel}
        </Badge>
      </span>,
    );
    setEnd(
      <div className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 sm:gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {PERIODS.map((p) => (
            <Button
              key={p.label}
              type="button"
              variant={days === p.days ? "default" : "outline"}
              size="sm"
              className="h-7 min-w-0 text-xs"
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
          className="h-7 text-xs"
        >
          <RefreshCw className="mr-1 h-3 w-3" />
          {t.common.refresh}
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [days, loading, load, setAfterTitle, setEnd, t.common.refresh]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      {loading && !data && (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          {t.common.loading}
        </p>
      )}

      {error && (
        <p className="px-1 py-1 text-xs text-destructive">{error}</p>
      )}

      {data && (
        <>
          {/* Summary cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <SummaryCard
              icon={Hash}
              label={t.analytics.totalTokens}
              value={formatTokens(data.totals.total_input + data.totals.total_output)}
              sub={t.analytics.inOut.replace("{input}", formatTokens(data.totals.total_input)).replace("{output}", formatTokens(data.totals.total_output))}
            />
            <SummaryCard
              icon={BarChart3}
              label={t.analytics.totalSessions}
              value={String(data.totals.total_sessions)}
              sub={`~${(data.totals.total_sessions / days).toFixed(1)}${t.analytics.perDayAvg}`}
            />
            <SummaryCard
              icon={TrendingUp}
              label={t.analytics.apiCalls}
              value={String(data.totals.total_api_calls ?? data.daily.reduce((sum, d) => sum + d.sessions, 0))}
              sub={t.analytics.acrossModels.replace("{count}", String(data.by_model.length))}
            />
          </div>

          {/* Bar chart */}
          <TokenBarChart daily={data.daily} />

          {/* Tables */}
          <DailyTable daily={data.daily} />
          <ModelTable models={data.by_model} />
          <SkillTable skills={data.skills.top_skills} />
        </>
      )}

      {data && data.daily.length === 0 && data.by_model.length === 0 && data.skills.top_skills.length === 0 && (
        <p className="px-1 py-1 text-xs text-muted-foreground/80">
          {t.analytics.noUsageData} {t.analytics.startSession}
        </p>
      )}
    </div>
  );
}

```

---
## `src/pages/LogsPage.tsx`
```tsx
import { useEffect, useLayoutEffect, useState, useCallback, useRef } from "react";
import { FileText, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { FilterGroup, Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";

const FILES = ["agent", "errors", "gateway"] as const;
const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"] as const;
const COMPONENTS = ["all", "gateway", "agent", "tools", "cli", "cron"] as const;
const LINE_COUNTS = [50, 100, 200, 500] as const;

function classifyLine(line: string): "error" | "warning" | "info" | "debug" {
  const upper = line.toUpperCase();
  if (
    upper.includes("ERROR") ||
    upper.includes("CRITICAL") ||
    upper.includes("FATAL")
  )
    return "error";
  if (upper.includes("WARNING") || upper.includes("WARN")) return "warning";
  if (upper.includes("DEBUG")) return "debug";
  return "info";
}

const LINE_COLORS: Record<string, string> = {
  error: "text-destructive",
  warning: "text-warning",
  info: "text-foreground",
  debug: "text-muted-foreground/60",
};

const toOptions = <T extends string>(values: readonly T[]) =>
  values.map((v) => ({ value: v, label: v }));

export default function LogsPage() {
  const [file, setFile] = useState<(typeof FILES)[number]>("agent");
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("ALL");
  const [component, setComponent] =
    useState<(typeof COMPONENTS)[number]>("all");
  const [lineCount, setLineCount] = useState<(typeof LINE_COUNTS)[number]>(100);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  const fetchLogs = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .getLogs({ file, lines: lineCount, level, component })
      .then((resp) => {
        setLines(resp.lines);
        setTimeout(() => {
          if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
          }
        }, 50);
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [file, lineCount, level, component]);

  useLayoutEffect(() => {
    setAfterTitle(
      <span className="flex items-center gap-2">
        {loading && (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        )}
        <Badge variant="secondary" className="text-[10px]">
          {file} · {level} · {component}
        </Badge>
      </span>,
    );
    setEnd(
      <div className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 sm:gap-3">
        <div className="flex items-center gap-2">
          <Switch
            checked={autoRefresh}
            onCheckedChange={setAutoRefresh}
            id="logs-auto-refresh"
          />
          <Label htmlFor="logs-auto-refresh" className="text-xs cursor-pointer">
            {t.logs.autoRefresh}
          </Label>
          {autoRefresh && (
            <Badge variant="success" className="text-[10px]">
              <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
              {t.common.live}
            </Badge>
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={fetchLogs}
          disabled={loading}
          className="h-7 text-xs"
        >
          <RefreshCw className="mr-1 h-3 w-3" />
          {t.common.refresh}
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    autoRefresh,
    component,
    file,
    level,
    loading,
    setAfterTitle,
    setEnd,
    t.common.live,
    t.common.refresh,
    t.logs.autoRefresh,
    fetchLogs,
  ]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchLogs]);

  return (
    <div className="flex flex-col gap-4">
      {/* ═══════════════ Filter toolbar ═══════════════ */}
      <div
        role="toolbar"
        aria-label={t.logs.title}
        className="flex flex-wrap items-center gap-x-6 gap-y-2"
      >
        <FilterGroup label={t.logs.file}>
          <Segmented value={file} onChange={setFile} options={toOptions(FILES)} />
        </FilterGroup>

        <FilterGroup label={t.logs.level}>
          <Segmented value={level} onChange={setLevel} options={toOptions(LEVELS)} />
        </FilterGroup>

        <FilterGroup label={t.logs.component}>
          <Segmented
            value={component}
            onChange={setComponent}
            options={toOptions(COMPONENTS)}
          />
        </FilterGroup>

        <FilterGroup label={t.logs.lines}>
          <Segmented
            value={String(lineCount)}
            onChange={(v) =>
              setLineCount(Number(v) as (typeof LINE_COUNTS)[number])
            }
            options={LINE_COUNTS.map((n) => ({
              value: String(n),
              label: String(n),
            }))}
          />
        </FilterGroup>
      </div>

      {/* ═══════════════ Log viewer ═══════════════ */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-sm flex items-center gap-2">
            <FileText className="h-4 w-4" />
            {file}.log
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {error && (
            <div className="bg-card border-b border-border px-4 py-2">
              <p className="text-xs text-destructive">{error}</p>
            </div>
          )}

          <div
            ref={scrollRef}
            className="p-4 font-mono-ui text-xs leading-5 overflow-auto min-h-[400px] max-h-[calc(100vh-220px)]"
          >
            {lines.length === 0 && !loading && (
              <p className="px-1 py-1 text-xs text-muted-foreground/80">
                {t.logs.noLogLines}
              </p>
            )}
            {lines.map((line, i) => {
              const cls = classifyLine(line);
              return (
                <div
                  key={i}
                  className={`${LINE_COLORS[cls]} hover:bg-secondary/20 px-1 -mx-1`}
                >
                  {line}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

```

---
## `src/pages/EnvPage.tsx`
```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Eye,
  EyeOff,
  ExternalLink,
  KeyRound,
  MessageSquare,
  Pencil,
  Save,
  Settings,
  Trash2,
  X,
  Zap,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { api } from "@/lib/api";
import type { EnvVarInfo } from "@/lib/api";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { Toast } from "@/components/Toast";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { useToast } from "@/hooks/useToast";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/i18n";

/* ------------------------------------------------------------------ */
/*  Provider grouping                                                  */
/* ------------------------------------------------------------------ */

/** Map env-var key prefixes to a human-friendly provider name + ordering. */
const PROVIDER_GROUPS: { prefix: string; name: string; priority: number }[] = [
  // Nous Portal first
  { prefix: "NOUS_",            name: "Nous Portal",       priority: 0 },
  // Then alphabetical by display name
  { prefix: "ANTHROPIC_",       name: "Anthropic",         priority: 1 },
  { prefix: "DASHSCOPE_",       name: "DashScope (Qwen)",  priority: 2 },
  { prefix: "ELEVATE_QWEN_",   name: "DashScope (Qwen)",  priority: 2 },
  { prefix: "DEEPSEEK_",        name: "DeepSeek",          priority: 3 },
  { prefix: "GOOGLE_",          name: "Gemini",            priority: 4 },
  { prefix: "GEMINI_",          name: "Gemini",            priority: 4 },
  { prefix: "GLM_",             name: "GLM / Z.AI",        priority: 5 },
  { prefix: "ZAI_",             name: "GLM / Z.AI",        priority: 5 },
  { prefix: "Z_AI_",            name: "GLM / Z.AI",        priority: 5 },
  { prefix: "HF_",              name: "Hugging Face",      priority: 6 },
  { prefix: "KIMI_",            name: "Kimi / Moonshot",   priority: 7 },
  { prefix: "MINIMAX_CN_",      name: "MiniMax (China)",   priority: 9 },
  { prefix: "MINIMAX_",         name: "MiniMax",           priority: 8 },
  { prefix: "OPENCODE_GO_",     name: "OpenCode Go",       priority: 10 },
  { prefix: "OPENCODE_ZEN_",    name: "OpenCode Zen",      priority: 11 },
  { prefix: "OPENROUTER_",      name: "OpenRouter",        priority: 12 },
  { prefix: "XIAOMI_",          name: "Xiaomi MiMo",       priority: 13 },
];

function getProviderGroup(key: string): string {
  for (const g of PROVIDER_GROUPS) {
    if (key.startsWith(g.prefix)) return g.name;
  }
  return "Other";
}

function getProviderPriority(groupName: string): number {
  const entry = PROVIDER_GROUPS.find((g) => g.name === groupName);
  return entry?.priority ?? 99;
}

interface ProviderGroup {
  name: string;
  priority: number;
  entries: [string, EnvVarInfo][];
  hasAnySet: boolean;
}

const CATEGORY_META_ICONS: Record<string, typeof KeyRound> = {
  provider: Zap,
  tool: KeyRound,
  messaging: MessageSquare,
  setting: Settings,
};

/* ------------------------------------------------------------------ */
/*  EnvVarRow — single key edit row                                    */
/* ------------------------------------------------------------------ */

function EnvVarRow({
  varKey,
  info,
  edits,
  setEdits,
  revealed,
  saving,
  onSave,
  onClear,
  onReveal,
  onCancelEdit,
  clearDialogOpen = false,
  compact = false,
}: {
  varKey: string;
  info: EnvVarInfo;
  edits: Record<string, string>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  revealed: Record<string, string>;
  saving: string | null;
  onSave: (key: string) => void;
  onClear: (key: string) => void;
  onReveal: (key: string) => void;
  onCancelEdit: (key: string) => void;
  clearDialogOpen?: boolean;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const isEditing = edits[varKey] !== undefined;
  const isRevealed = !!revealed[varKey];
  const displayValue = isRevealed ? revealed[varKey] : (info.redacted_value ?? "---");

  // Compact inline row for unset, non-editing keys (used inside provider groups)
  if (compact && !info.is_set && !isEditing) {
    return (
      <div className="flex items-center justify-between gap-3 py-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono-ui text-[0.7rem] text-muted-foreground">{varKey}</span>
          <span className="text-[0.65rem] text-muted-foreground/70 truncate hidden sm:block">{info.description}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {info.url && (
            <a href={info.url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-[0.65rem] text-primary hover:underline">
              {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
          <Button size="sm" variant="outline" className="h-6 text-[0.6rem] px-2"
            onClick={() => setEdits((prev) => ({ ...prev, [varKey]: "" }))}>
            <Pencil className="h-2.5 w-2.5" />
            {t.common.set}
          </Button>
        </div>
      </div>
    );
  }

  // Non-compact unset row
  if (!info.is_set && !isEditing) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-border px-4 py-2.5 opacity-60 transition-opacity hover:opacity-100">
        <div className="flex items-center gap-3 min-w-0">
          <Label className="font-mono-ui text-[0.7rem] text-muted-foreground">{varKey}</Label>
          <span className="text-[0.65rem] text-muted-foreground/60 truncate hidden sm:block">{info.description}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {info.url && (
            <a href={info.url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-[0.65rem] text-primary hover:underline">
              {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
          <Button size="sm" variant="outline" className="h-7 text-[0.6rem]"
            onClick={() => setEdits((prev) => ({ ...prev, [varKey]: "" }))}>
            <Pencil className="h-3 w-3" />
            {t.common.set}
          </Button>
        </div>
      </div>
    );
  }

  // Full expanded row for set keys or keys being edited
  return (
    <div className="grid gap-2 rounded-md border border-border p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Label className="font-mono-ui text-[0.7rem]">{varKey}</Label>
          <Badge variant={info.is_set ? "success" : "outline"}>
            {info.is_set ? t.common.set : t.env.notSet}
          </Badge>
        </div>
        {info.url && (
          <a href={info.url} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 text-[0.65rem] text-primary hover:underline">
            {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
          </a>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{info.description}</p>

      {info.tools.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {info.tools.map((tool) => (
            <Badge key={tool} variant="secondary" className="text-[0.6rem] py-0 px-1.5">{tool}</Badge>
          ))}
        </div>
      )}

      {!isEditing && (
        <div className="flex items-center gap-2">
          <div className={`flex-1 rounded-md border border-border px-3 py-2 font-mono-ui text-xs ${
            isRevealed ? "bg-background text-foreground select-all" : "bg-muted/30 text-muted-foreground"
          }`}>
            {info.is_set ? displayValue : "---"}
          </div>

          {info.is_set && (
            <Button size="sm" variant="ghost" onClick={() => onReveal(varKey)}
              title={isRevealed ? t.env.hideValue : t.env.showValue}
              aria-label={isRevealed ? `Hide ${varKey}` : `Reveal ${varKey}`}>
              {isRevealed
                ? <EyeOff className="h-4 w-4" />
                : <Eye className="h-4 w-4" />}
            </Button>
          )}

          <Button size="sm" variant="outline"
            onClick={() => setEdits((prev) => ({ ...prev, [varKey]: "" }))}>
            <Pencil className="h-3 w-3" />
            {info.is_set ? t.common.replace : t.common.set}
          </Button>

          {info.is_set && (
            <Button size="sm" variant="ghost"
              className="text-destructive hover:text-destructive hover:bg-muted"
              onClick={() => onClear(varKey)} disabled={saving === varKey || clearDialogOpen}>
              <Trash2 className="h-3 w-3" />
              {saving === varKey ? "..." : t.common.clear}
            </Button>
          )}
        </div>
      )}

      {isEditing && (
        <div className="flex items-center gap-2">
          <Input autoFocus type="text" value={edits[varKey]}
            onChange={(e) => setEdits((prev) => ({ ...prev, [varKey]: e.target.value }))}
            placeholder={info.is_set ? t.env.replaceCurrentValue.replace("{preview}", info.redacted_value ?? "---") : t.env.enterValue}
            className="flex-1 font-mono-ui text-xs" />
          <Button size="sm" onClick={() => onSave(varKey)}
            disabled={saving === varKey || !edits[varKey]}>
            <Save className="h-3 w-3" />
            {saving === varKey ? "..." : t.common.save}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onCancelEdit(varKey)}>
            <X className="h-3 w-3" /> {t.common.cancel}
          </Button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ProviderGroupCard — groups API key + base URL per provider         */
/* ------------------------------------------------------------------ */

function ProviderGroupCard({
  group,
  edits,
  setEdits,
  revealed,
  saving,
  onSave,
  onClear,
  onReveal,
  onCancelEdit,
  clearDialogOpen = false,
}: {
  group: ProviderGroup;
  edits: Record<string, string>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  revealed: Record<string, string>;
  saving: string | null;
  onSave: (key: string) => void;
  onClear: (key: string) => void;
  onReveal: (key: string) => void;
  onCancelEdit: (key: string) => void;
  clearDialogOpen?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useI18n();

  // Separate API keys from base URLs and other settings
  const apiKeys = group.entries.filter(([k]) => k.endsWith("_API_KEY") || k.endsWith("_TOKEN"));
  const baseUrls = group.entries.filter(([k]) => k.endsWith("_BASE_URL"));
  const other = group.entries.filter(([k]) => !k.endsWith("_API_KEY") && !k.endsWith("_TOKEN") && !k.endsWith("_BASE_URL"));
  const hasAnyConfigured = group.entries.some(([, info]) => info.is_set);
  const configuredCount = group.entries.filter(([, info]) => info.is_set).length;

  // Get a representative URL for "Get key" link
  const keyUrl = apiKeys.find(([, info]) => info.url)?.[1]?.url ?? null;

  return (
    <div className="overflow-hidden rounded-md border border-border bg-card">
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full cursor-pointer items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-muted"
      >
        <div className="flex items-center gap-3 min-w-0">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
          <span className="font-semibold text-sm tracking-wide">{group.name === "Other" ? t.common.other : group.name}</span>
          {hasAnyConfigured && (
            <Badge variant="success" className="text-[0.6rem]">
              {configuredCount} {t.common.set.toLowerCase()}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {keyUrl && (
            <a href={keyUrl} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-[0.65rem] text-primary hover:underline"
              onClick={(e) => e.stopPropagation()}>
              {t.env.getKey} <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
          <span className="text-[0.65rem] text-muted-foreground/60">
            {t.env.keysCount.replace("{count}", String(group.entries.length)).replace("{s}", group.entries.length !== 1 ? "s" : "")}
          </span>
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-border px-4 py-3 grid gap-2">
          {/* API keys first (most important) */}
          {apiKeys.map(([key, info]) => (
            <EnvVarRow
              key={key} varKey={key} info={info} compact
              edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
              onSave={onSave} onClear={onClear} onReveal={onReveal} onCancelEdit={onCancelEdit}
              clearDialogOpen={clearDialogOpen}
            />
          ))}
          {/* Base URLs (secondary) */}
          {baseUrls.map(([key, info]) => (
            <EnvVarRow
              key={key} varKey={key} info={info} compact
              edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
              onSave={onSave} onClear={onClear} onReveal={onReveal} onCancelEdit={onCancelEdit}
              clearDialogOpen={clearDialogOpen}
            />
          ))}
          {/* Anything else */}
          {other.map(([key, info]) => (
            <EnvVarRow
              key={key} varKey={key} info={info} compact
              edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
              onSave={onSave} onClear={onClear} onReveal={onReveal} onCancelEdit={onCancelEdit}
              clearDialogOpen={clearDialogOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main page                                                          */
/* ------------------------------------------------------------------ */

export default function EnvPage() {
  const [vars, setVars] = useState<Record<string, EnvVarInfo> | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(true); // Show all providers by default
  const { toast, showToast } = useToast();
  const { t } = useI18n();

  useEffect(() => {
    api.getEnvVars().then(setVars).catch(() => {});
  }, []);

  const handleSave = async (key: string) => {
    const value = edits[key];
    if (!value) return;
    setSaving(key);
    try {
      await api.setEnvVar(key, value);
      setVars((prev) =>
        prev
          ? {
              ...prev,
              [key]: { ...prev[key], is_set: true, redacted_value: value.slice(0, 4) + "..." + value.slice(-4) },
            }
          : prev,
      );
      setEdits((prev) => { const n = { ...prev }; delete n[key]; return n; });
      setRevealed((prev) => { const n = { ...prev }; delete n[key]; return n; });
      showToast(`${key} ${t.common.save.toLowerCase()}d`, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave} ${key}: ${e}`, "error");
    } finally {
      setSaving(null);
    }
  };

  const keyClear = useConfirmDelete({
    onDelete: useCallback(
      async (key: string) => {
        setSaving(key);
        try {
          await api.deleteEnvVar(key);
          setVars((prev) =>
            prev
              ? { ...prev, [key]: { ...prev[key], is_set: false, redacted_value: null } }
              : prev,
          );
          setEdits((prev) => { const n = { ...prev }; delete n[key]; return n; });
          setRevealed((prev) => { const n = { ...prev }; delete n[key]; return n; });
          showToast(`${key} ${t.common.removed}`, "success");
        } catch (e) {
          showToast(`${t.common.failedToRemove} ${key}: ${e}`, "error");
          throw e;
        } finally {
          setSaving(null);
        }
      },
      [showToast, t.common.removed, t.common.failedToRemove],
    ),
  });

  const handleReveal = async (key: string) => {
    if (revealed[key]) {
      setRevealed((prev) => { const n = { ...prev }; delete n[key]; return n; });
      return;
    }
    try {
      const resp = await api.revealEnvVar(key);
      setRevealed((prev) => ({ ...prev, [key]: resp.value }));
    } catch {
      showToast(`${t.common.failedToReveal} ${key}`, "error");
    }
  };

  const cancelEdit = (key: string) => {
    setEdits((prev) => { const n = { ...prev }; delete n[key]; return n; });
  };

  /* ---- Build provider groups ---- */
  const { providerGroups, nonProviderGrouped } = useMemo(() => {
    if (!vars) return { providerGroups: [], nonProviderGrouped: [] };

    const providerEntries = Object.entries(vars).filter(
      ([, info]) => info.category === "provider" && (showAdvanced || !info.advanced),
    );

    // Group by provider
    const groupMap = new Map<string, [string, EnvVarInfo][]>();
    for (const entry of providerEntries) {
      const groupName = getProviderGroup(entry[0]);
      if (!groupMap.has(groupName)) groupMap.set(groupName, []);
      groupMap.get(groupName)!.push(entry);
    }

    const groups: ProviderGroup[] = Array.from(groupMap.entries())
      .map(([name, entries]) => ({
        name,
        priority: getProviderPriority(name),
        entries,
        hasAnySet: entries.some(([, info]) => info.is_set),
      }))
      .sort((a, b) => a.priority - b.priority);

    // Non-provider categories — use translated labels
    const CATEGORY_META_LABELS: Record<string, string> = {
      tool: t.app.nav.keys,
      messaging: t.common.messaging,
      setting: t.app.nav.config,
    };
    const otherCategories = ["tool", "messaging", "setting"];
    const nonProvider = otherCategories.map((cat) => {
      const entries = Object.entries(vars).filter(
        ([, info]) => info.category === cat && (showAdvanced || !info.advanced),
      );
      const setEntries = entries.filter(([, info]) => info.is_set);
      const unsetEntries = entries.filter(([, info]) => !info.is_set);
      return {
        label: CATEGORY_META_LABELS[cat] ?? cat,
        icon: CATEGORY_META_ICONS[cat] ?? KeyRound,
        category: cat,
        setEntries,
        unsetEntries,
        totalEntries: entries.length,
      };
    });

    return { providerGroups: groups, nonProviderGrouped: nonProvider };
  }, [vars, showAdvanced, t]);

  if (!vars) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">{t.common.loading}</p>
    );
  }

  const totalProviders = providerGroups.length;
  const configuredProviders = providerGroups.filter((g) => g.hasAnySet).length;

  const pendingClearKey = keyClear.pendingId;
  const pendingKeyDescription =
    pendingClearKey && vars
      ? vars[pendingClearKey]?.description
      : undefined;

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={keyClear.isOpen}
        onCancel={keyClear.cancel}
        onConfirm={keyClear.confirm}
        title={t.env.confirmClearTitle}
        description={
          pendingClearKey
            ? `${pendingClearKey}${pendingKeyDescription ? ` — ${pendingKeyDescription}` : ""}. ${t.env.confirmClearMessage}`
            : t.env.confirmClearMessage
        }
        loading={keyClear.isDeleting}
      />

      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">
            {t.env.description} <code>~/.elevate/.env</code>
          </p>
          <p className="text-[0.7rem] text-muted-foreground/70">
            {t.env.changesNote}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setShowAdvanced(!showAdvanced)}>
          {showAdvanced ? t.env.hideAdvanced : t.env.showAdvanced}
        </Button>
      </div>

      {/* ═══════════════ OAuth Logins ══ */}
      <OAuthProvidersCard
        onError={(msg) => showToast(msg, "error")}
        onSuccess={(msg) => showToast(msg, "success")}
      />

      {/* ═══════════════ LLM Providers (grouped) ═══════════════ */}
      <Card>
        <CardHeader className="border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">{t.env.llmProviders}</CardTitle>
          </div>
          <CardDescription>
            {t.env.providersConfigured.replace("{configured}", String(configuredProviders)).replace("{total}", String(totalProviders))}
          </CardDescription>
        </CardHeader>

        <CardContent className="grid gap-0 p-0">
          {providerGroups.map((group) => (
            <ProviderGroupCard
              key={group.name}
              group={group}
              edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
              onSave={handleSave} onClear={keyClear.requestDelete} onReveal={handleReveal} onCancelEdit={cancelEdit}
              clearDialogOpen={keyClear.isOpen}
            />
          ))}
        </CardContent>
      </Card>

      {/* ═══════════════ Other categories (flat) ═══════════════ */}
      {nonProviderGrouped.map(({ label, icon: Icon, setEntries, unsetEntries, totalEntries, category }) => {
        if (totalEntries === 0) return null;

        return (
          <Card key={category}>
            <CardHeader className="border-b border-border bg-card">
              <div className="flex items-center gap-2">
                <Icon className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">{label}</CardTitle>
              </div>
              <CardDescription>
                {setEntries.length} {t.common.of} {totalEntries} {t.common.configured}
              </CardDescription>
            </CardHeader>

            <CardContent className="grid gap-3 pt-4">
              {setEntries.map(([key, info]) => (
                <EnvVarRow
                  key={key} varKey={key} info={info}
                  edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
                  onSave={handleSave} onClear={keyClear.requestDelete} onReveal={handleReveal} onCancelEdit={cancelEdit}
                  clearDialogOpen={keyClear.isOpen}
                />
              ))}

              {unsetEntries.length > 0 && (
                <CollapsibleUnset
                  category={category}
                  unsetEntries={unsetEntries}
                  edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
                  onSave={handleSave} onClear={keyClear.requestDelete} onReveal={handleReveal} onCancelEdit={cancelEdit}
                  clearDialogOpen={keyClear.isOpen}
                />
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  CollapsibleUnset — for non-provider categories                     */
/* ------------------------------------------------------------------ */

function CollapsibleUnset({
  category: _category,
  unsetEntries,
  edits,
  setEdits,
  revealed,
  saving,
  onSave,
  onClear,
  onReveal,
  onCancelEdit,
  clearDialogOpen = false,
}: {
  category: string;
  unsetEntries: [string, EnvVarInfo][];
  edits: Record<string, string>;
  setEdits: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  revealed: Record<string, string>;
  saving: string | null;
  onSave: (key: string) => void;
  onClear: (key: string) => void;
  onReveal: (key: string) => void;
  onCancelEdit: (key: string) => void;
  clearDialogOpen?: boolean;
}) {
  void _category;
  const [collapsed, setCollapsed] = useState(true);
  const { t } = useI18n();

  return (
    <>
      <button
        type="button"
        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer pt-1"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed
          ? <ChevronRight className="h-3 w-3" />
          : <ChevronDown className="h-3 w-3" />}
        <span>{t.env.notConfigured.replace("{count}", String(unsetEntries.length))}</span>
      </button>

      {!collapsed && unsetEntries.map(([key, info]) => (
        <EnvVarRow
          key={key} varKey={key} info={info}
          edits={edits} setEdits={setEdits} revealed={revealed} saving={saving}
          onSave={onSave} onClear={onClear} onReveal={onReveal} onCancelEdit={onCancelEdit}
          clearDialogOpen={clearDialogOpen}
        />
      ))}
    </>
  );
}

```

---
## `src/pages/ProjectPage.tsx`
```tsx
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  Bot,
  Brain,
  CheckCircle2,
  Clock,
  Database,
  Folder,
  KeyRound,
  RefreshCw,
  Settings,
  Terminal,
  Wrench,
} from "lucide-react";
import { api, type AgentHubSnapshot, type StatusResponse } from "@/lib/api";
import { cn, isoTimeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

function stateVariant(value: boolean | string | null | undefined): "success" | "warning" | "outline" {
  if (value === true || value === "running" || value === "connected" || value === "active") {
    return "success";
  }
  if (value === "starting" || value === "pending") return "warning";
  return "outline";
}

function MiniStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Folder;
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-[0.68rem] font-medium">
          {label}
        </span>
      </div>
      <div className="mt-1 truncate text-lg font-semibold text-foreground">{value}</div>
    </div>
  );
}

function PathRow({ icon: Icon, label, value }: { icon: typeof Folder; label: string; value: string }) {
  return (
    <div className="grid gap-1 px-3 py-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <code className="min-w-0 break-all text-xs text-foreground/90">{value || "-"}</code>
    </div>
  );
}

export default function ProjectPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [hub, setHub] = useState<AgentHubSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStatus, nextHub] = await Promise.all([
        api.getStatus(),
        api.getAgentHub({
          includeMemoryGraph: false,
          includeSessionTotal: false,
          includeOrchestration: false,
          includeHarness: false,
        }),
      ]);
      setStatus(nextStatus);
      setHub(nextHub);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Project failed to load", "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  useLayoutEffect(() => {
    setAfterTitle(
      status ? (
        <span className="text-xs text-muted-foreground">
          {status.gateway_running ? "Gateway online" : "Gateway offline"}
        </span>
      ) : null,
    );
    setEnd(
      <Button variant="outline" size="sm" onClick={load} disabled={loading}>
        <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        Refresh
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [load, loading, setAfterTitle, setEnd, status]);

  const connectedPlatforms = useMemo(
    () => hub?.platforms.filter((platform) => platform.configured) ?? [],
    [hub],
  );
  const enabledAgents = hub?.agents.filter((agent) => agent.enabled) ?? [];
  const embeddingLabel =
    hub?.memory.embedding.enabled
      ? `${hub.memory.embedding.provider}:${hub.memory.embedding.model}`
      : "off";

  if (loading && !status && !hub) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading project…</p>
    );
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="overflow-hidden rounded-md border border-border bg-card">
        <div className="grid gap-4 p-4 sm:p-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={stateVariant(status?.gateway_running)}>
                {status?.gateway_running ? "Gateway online" : "Gateway offline"}
              </Badge>
              <Badge variant={stateVariant(status?.gateway_state)}>
                {status?.gateway_state ?? "unknown"}
              </Badge>
              <Badge variant={status?.config_version === status?.latest_config_version ? "success" : "warning"}>
                config {status?.config_version ?? "-"} / {status?.latest_config_version ?? "-"}
              </Badge>
              <Badge variant="outline">v{status?.version ?? "-"}</Badge>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MiniStat icon={Bot} label="Agents" value={enabledAgents.length} />
              <MiniStat icon={Terminal} label="Platforms" value={connectedPlatforms.length} />
              <MiniStat icon={Brain} label="Memory" value={embeddingLabel} />
              <MiniStat icon={Clock} label="Sessions" value={hub?.sessions.active ?? status?.active_sessions ?? 0} />
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Local Project</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <PathRow icon={Folder} label="Code" value={status?.project_root ?? ""} />
                <PathRow icon={Settings} label="Config" value={status?.config_path ?? ""} />
                <PathRow icon={KeyRound} label="Secrets" value={status?.env_path ?? ""} />
                <PathRow icon={Database} label="Memory DB" value={hub?.memory.db_path ?? ""} />
                <PathRow icon={Folder} label="Data" value={status?.elevate_home ?? ""} />
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Runtime</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Model</span>
                  <span className="truncate text-right">{hub?.model.model || "not set"}</span>
                </div>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Provider</span>
                  <span className="truncate text-right">{hub?.model.provider || "-"}</span>
                </div>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Gateway PID</span>
                  <span>{status?.gateway_pid ?? "-"}</span>
                </div>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">Updated</span>
                  <span>{status?.gateway_updated_at ? isoTimeAgo(status.gateway_updated_at) : "-"}</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Project Surface</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <MiniStat icon={Wrench} label="Tools" value={hub?.toolsets.enabled.length ?? 0} />
                  <MiniStat icon={CheckCircle2} label="Skills" value={hub?.skills.enabled ?? 0} />
                  <MiniStat icon={Database} label="Facts" value={hub?.memory.facts ?? 0} />
                  <MiniStat icon={Brain} label="Vectors" value={hub?.memory.embeddings ?? 0} />
                </div>
                <div className="flex flex-wrap gap-1">
                  {(connectedPlatforms.length ? connectedPlatforms : hub?.platforms.slice(0, 3) ?? []).map((platform) => (
                    <Badge key={platform.name} variant={platform.configured ? "success" : "outline"}>
                      {platform.name}
                    </Badge>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1">
                  {enabledAgents.slice(0, 5).map((agent) => (
                    <Badge key={agent.id} variant="outline">
                      {agent.name}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>
    </div>
  );
}

```

---
## `src/pages/DocsPage.tsx`
```tsx
import { useLayoutEffect } from "react";
import { ExternalLink } from "lucide-react";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const ELEVATE_DOCS_URL = "https://github.com/Dartagnan98/elevate-agent#readme";

export default function DocsPage() {
  const { t } = useI18n();
  const { setEnd } = usePageHeader();

  useLayoutEffect(() => {
    setEnd(
      <a
        href={ELEVATE_DOCS_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          buttonVariants({ variant: "outline", size: "sm" }),
          "h-7 text-xs",
        )}
      >
        <ExternalLink className="mr-1.5 h-3 w-3" />
        {t.app.openDocumentation}
      </a>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t]);

  return (
    <div
      className={cn(
        "flex min-h-0 w-full min-w-0 flex-1 flex-col",
        "pt-1 sm:pt-2",
      )}
    >
      <iframe
        title={t.app.nav.documentation}
        src={ELEVATE_DOCS_URL}
        className={cn(
          "min-h-0 w-full min-w-0 flex-1",
          "rounded-lg border border-current/20",
          "bg-background",
        )}
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        referrerPolicy="no-referrer-when-downgrade"
      />
    </div>
  );
}

```

---
## `src/pages/DesktopSetupPage.tsx`
```tsx
import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  ChevronRight,
  CheckCircle2,
  CircleAlert,
  Clock,
  Database,
  FileText,
  FolderOpen,
  KeyRound,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  RotateCw,
  Settings,
  ShieldCheck,
  Sparkles,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import { LoginCard } from "@/components/LoginCard";
import type {
  AccessStatusResponse,
  AdminSetupSnapshot,
  AgentHubAgent,
  AgentHubSnapshot,
  ComposioStatus,
  HarnessSnapshot,
  OAuthProvidersResponse,
  PackOnboardingItem,
  PackOnboardingPack,
  PackOnboardingSnapshot,
  SourceConnectorsResponse,
  StatusResponse,
  UpdateStatusResponse,
} from "@/lib/api";
import { cn, isoTimeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { usePageHeader } from "@/contexts/usePageHeader";

type ReadinessTone = "success" | "warning" | "outline" | "destructive";

interface LoadState {
  access: AccessStatusResponse | null;
  adminSetup: AdminSetupSnapshot | null;
  composio: ComposioStatus | null;
  connectors: SourceConnectorsResponse | null;
  harness: HarnessSnapshot | null;
  hub: AgentHubSnapshot | null;
  oauth: OAuthProvidersResponse | null;
  packOnboarding: PackOnboardingSnapshot | null;
  status: StatusResponse | null;
  updateStatus: UpdateStatusResponse | null;
}

const EMPTY_STATE: LoadState = {
  access: null,
  adminSetup: null,
  composio: null,
  connectors: null,
  harness: null,
  hub: null,
  oauth: null,
  packOnboarding: null,
  status: null,
  updateStatus: null,
};

const REQUIRED_AGENT_IDS = new Set(["executive-assistant", "admin"]);

const PACK_ACCENT: Record<string, string> = {
  elevate_core: "Basic",
  real_estate_admin: "Admin",
  real_estate_sales: "Leads",
  real_estate_marketing: "Marketing",
  real_estate_cma: "CMA",
};

const PACK_CREDENTIAL_FIELDS: Record<string, Array<{ key: string; label: string; password?: boolean }>> = {
  elevate_core: [
    { key: "OPENAI_API_KEY", label: "OpenAI API key", password: true },
    { key: "OPENAI_EMBEDDING_MODEL", label: "Embedding model" },
    { key: "OPENROUTER_API_KEY", label: "OpenRouter API key", password: true },
    { key: "ANTHROPIC_API_KEY", label: "Anthropic API key", password: true },
    { key: "GOOGLE_API_KEY", label: "Google/Gemini API key", password: true },
    { key: "TELEGRAM_BOT_TOKEN", label: "Executive Assistant Telegram bot token", password: true },
    { key: "TELEGRAM_ALLOWED_USERS", label: "Allowed Telegram user IDs" },
    { key: "BROWSER_USE_PROVIDER", label: "Browser-use provider" },
    { key: "BROWSER_USE_API_KEY", label: "Browser-use API key", password: true },
    { key: "COMPOSIO_API_KEY", label: "Composio API key", password: true },
    { key: "ELEVATE_UPDATE_CHANNEL", label: "Update channel" },
  ],
  real_estate_admin: [
    { key: "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN", label: "Admin Telegram bot token", password: true },
    { key: "ELEVATE_AGENT_ADMIN_TELEGRAM_CHANNEL", label: "Admin Telegram chat or topic ID" },
    { key: "MLS_LOGIN_URL", label: "MLS login URL" },
    { key: "MLS_USERNAME", label: "MLS username or credential ref" },
    { key: "SKYSLOPE_USERNAME", label: "Compliance username or credential ref" },
    { key: "SHOWINGTIME_USERNAME", label: "Showing platform username or credential ref" },
    { key: "PHOTO_SOURCE_ROOT", label: "Photo source folder" },
  ],
  real_estate_sales: [
    { key: "CRM_API_KEY", label: "CRM API key", password: true },
    { key: "LOFTY_API_KEY", label: "Lofty API key", password: true },
    { key: "GMAIL_CLIENT_ID", label: "Email/OAuth client ID" },
    { key: "TWILIO_ACCOUNT_SID", label: "SMS account SID" },
    { key: "MLS_USERNAME", label: "Buyer search credential ref" },
  ],
  real_estate_marketing: [
    { key: "GMAIL_CLIENT_ID", label: "Email/OAuth client ID" },
    { key: "AYRSHARE_API_KEY", label: "Social scheduler key", password: true },
    { key: "GOOGLE_DRIVE_ACCOUNT", label: "Asset storage account/ref" },
    { key: "MARKETING_ASSET_ROOT", label: "Marketing asset folder" },
    { key: "PHOTO_SOURCE_ROOT", label: "Approved listing media folder" },
  ],
  real_estate_cma: [
    { key: "MLS_LOGIN_URL", label: "MLS/CMA login URL" },
    { key: "MLS_USERNAME", label: "MLS credential ref" },
    { key: "CLOUD_CMA_API_KEY", label: "Cloud CMA API key", password: true },
    { key: "CMA_TEMPLATE_PATH", label: "CMA template path" },
    { key: "CMA_OUTPUT_ROOT", label: "CMA output folder" },
  ],
};

const ADMIN_MIRROR_PACK_ID = "real_estate_admin";
const BASIC_PACK_ID = "elevate_core";

function badgeTone(ready: boolean, warning = false): ReadinessTone {
  if (ready) return "success";
  if (warning) return "warning";
  return "outline";
}

function statusCopy(ready: boolean, label: string, fallback = "Needs setup") {
  return ready ? label : fallback;
}

function formatTime(value: string | null | undefined) {
  return value ? isoTimeAgo(value) : "Never";
}

function DetailRow({
  icon: Icon,
  label,
  value,
  tone = "outline",
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  tone?: ReadinessTone;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2">
      <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <Badge variant={tone} className="max-w-[64%] truncate">
        {value}
      </Badge>
    </div>
  );
}

function SetupLink({
  children,
  to,
}: {
  children: ReactNode;
  to: string;
}) {
  return (
    <Link to={to} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "shrink-0")}>
      {children}
    </Link>
  );
}

function ReadinessCard({
  action,
  children,
  description,
  icon: Icon,
  status,
  title,
  tone,
}: {
  action?: ReactNode;
  children: ReactNode;
  description: string;
  icon: LucideIcon;
  status: string;
  title: string;
  tone: ReadinessTone;
}) {
  return (
    <Card className="min-h-[17rem] bg-card">
      <CardHeader className="gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
              <Icon className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
          </div>
          <Badge variant={tone}>{status}</Badge>
        </div>
        {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
      </CardHeader>
      <CardContent className="space-y-2">{children}</CardContent>
    </Card>
  );
}

function RunwayStep({
  description,
  icon: Icon,
  label,
  tone,
}: {
  description: string;
  icon: LucideIcon;
  label: string;
  tone: ReadinessTone;
}) {
  const StatusIcon = tone === "success" ? CheckCircle2 : tone === "warning" ? AlertTriangle : CircleAlert;
  return (
    <div className="flex items-start gap-3 rounded-md border border-border bg-card px-3 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-border bg-card">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <div className="truncate text-sm font-medium text-foreground">{label}</div>
          <StatusIcon
            className={cn(
              "h-4 w-4 shrink-0",
              tone === "success" && "text-success",
              tone === "warning" && "text-warning",
              tone !== "success" && tone !== "warning" && "text-muted-foreground",
            )}
          />
        </div>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function AgentLaneRow({ agent }: { agent: AgentHubAgent }) {
  const lane = agent.telegramLane;
  const ready = Boolean(lane?.tokenConfigured && lane?.targetConfigured && !lane?.duplicateSharedBot);
  const warn = Boolean(lane?.duplicateSharedBot || lane?.usesSharedBot);
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">{agent.name}</div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{agent.id}</div>
        </div>
        <Badge variant={badgeTone(ready, warn)}>
          {ready ? "Separate lane" : warn ? "Shared lane" : "Needs lane"}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant={lane?.tokenConfigured ? "success" : "outline"}>bot token</Badge>
        <Badge variant={lane?.targetConfigured ? "success" : "outline"}>chat target</Badge>
        {lane?.topicConfigured ? <Badge variant="success">topic</Badge> : null}
      </div>
    </div>
  );
}

function safeHarness(value: AgentHubSnapshot["harness"] | HarnessSnapshot | null | undefined): HarnessSnapshot | null {
  if (!value || !("orchestration" in value)) return null;
  return value;
}

function packTone(pack: PackOnboardingPack): ReadinessTone {
  if (!pack.unlocked) return "outline";
  if (pack.complete) return "success";
  if (pack.completedRequiredCount > 0) return "warning";
  return "outline";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function providerSeed(item: PackOnboardingItem): string {
  const value = recordValue(item.value);
  return String(item.provider || value.provider || "");
}

function PackUnlockOnboarding({
  adminSetup,
  notify,
  onSaved,
  snapshot,
}: {
  adminSetup: AdminSetupSnapshot | null;
  notify: (message: string, type: "success" | "error") => void;
  onSaved: () => Promise<void>;
  snapshot: PackOnboardingSnapshot | null;
}) {
  const packs = snapshot?.packs ?? [];
  const activePacks = packs.filter((pack) => pack.unlocked);
  const defaultPackId =
    activePacks.find((pack) => pack.launchRequired)?.packId ??
    activePacks.find((pack) => pack.packId === BASIC_PACK_ID)?.packId ??
    activePacks.find((pack) => pack.packId === ADMIN_MIRROR_PACK_ID)?.packId ??
    activePacks[0]?.packId ??
    packs[0]?.packId ??
    ADMIN_MIRROR_PACK_ID;
  const [selectedPackId, setSelectedPackId] = useState(defaultPackId);
  const [step, setStep] = useState<"celebrate" | "providers" | "credentials">("celebrate");
  const [saving, setSaving] = useState(false);
  const [providerValues, setProviderValues] = useState<Record<string, string>>({});
  const [notesValues, setNotesValues] = useState<Record<string, string>>({});
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [savedPulse, setSavedPulse] = useState(false);

  const selectedPack = packs.find((pack) => pack.packId === selectedPackId) ?? packs[0] ?? null;
  const credentialFields = selectedPack ? PACK_CREDENTIAL_FIELDS[selectedPack.packId] ?? [] : [];
  const visibleItems = selectedPack?.items ?? [];

  useEffect(() => {
    setSelectedPackId(defaultPackId);
  }, [defaultPackId]);

  useEffect(() => {
    if (!selectedPack) return;
    const nextProviders: Record<string, string> = {};
    const nextNotes: Record<string, string> = {};
    for (const item of selectedPack.items) {
      nextProviders[item.key] = providerSeed(item);
      nextNotes[item.key] = item.notes ?? "";
    }
    setProviderValues(nextProviders);
    setNotesValues(nextNotes);
    setEnvValues({});
    setStep("celebrate");
  }, [selectedPack?.packId, selectedPack?.updatedAt]);

  if (!snapshot || !selectedPack) {
    return null;
  }

  const unlockedTitle =
    selectedPack.packId === BASIC_PACK_ID
      ? "Congratulations on installing Elevate Basic"
      : selectedPack.unlocked
        ? `Congratulations on unlocking ${selectedPack.label}`
        : `${selectedPack.label} is locked`;
  const activeLabel = PACK_ACCENT[selectedPack.packId] ?? selectedPack.label;

  async function savePack() {
    if (!selectedPack) return;
    setSaving(true);
    setSavedPulse(false);
    try {
      const itemUpdates = visibleItems.map((item) => {
        const provider = providerValues[item.key]?.trim() ?? "";
        const notes = notesValues[item.key]?.trim() ?? "";
        return {
          key: item.key,
          status: provider || notes ? "configured" as const : "missing" as const,
          provider: provider || null,
          notes: notes || null,
          value: {
            provider: provider || null,
            envKeys: item.envKeys,
            source: "desktop_setup",
          },
        };
      });
      for (const [key, value] of Object.entries(envValues)) {
        if (!value.trim()) continue;
        await api.setEnvVar(key, value.trim());
      }
      await api.updatePackOnboarding(selectedPack.packId, { items: itemUpdates });
      if (selectedPack.packId === ADMIN_MIRROR_PACK_ID) {
        await api.updateAdminSetup({ items: itemUpdates });
        await api.verifyAdminSetup().catch(() => undefined);
      }
      await onSaved();
      setSavedPulse(true);
      setTimeout(() => setSavedPulse(false), 900);
      notify(`${selectedPack.label} onboarding saved.`, "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Pack onboarding save failed", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="pack-unlock-shell overflow-hidden rounded-md border border-border bg-card">
      <div className="grid gap-0 xl:grid-cols-[21rem_minmax(0,1fr)]">
        <div className="border-b border-border/60 p-4 xl:border-b-0 xl:border-r">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-medium text-muted-foreground">Unlocked pack onboarding</div>
              <div className="text-lg font-semibold text-foreground">
                {snapshot.completedActiveCount}/{snapshot.activeCount} ready
              </div>
            </div>
            <Sparkles className="h-4 w-4 text-primary" />
          </div>
          <div className="space-y-2">
            {packs.map((pack, index) => {
              const selected = pack.packId === selectedPack.packId;
              return (
                <button
                  key={pack.packId}
                  type="button"
                  className={cn(
                    "pack-unlock-card group w-full rounded-md border px-3 py-3 text-left transition-colors",
                    selected
                      ? "border-primary bg-muted text-foreground"
                      : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
                    !pack.unlocked && "opacity-60",
                  )}
                  style={{ animationDelay: `${index * 70}ms` }}
                  onClick={() => {
                    setSelectedPackId(pack.packId);
                    setStep("celebrate");
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-semibold">{pack.label}</span>
                        {!pack.unlocked ? <LockKeyhole className="h-3.5 w-3.5" /> : null}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">
                        {pack.unlocked ? `${pack.completedRequiredCount}/${pack.requiredCount} fields ready` : "Unlock to configure"}
                      </div>
                    </div>
                    <Badge variant={packTone(pack)}>{pack.unlocked ? `${pack.completionPct}%` : "locked"}</Badge>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-w-0 p-4">
          <div className="relative overflow-hidden rounded-sm border border-border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <Badge variant={selectedPack.unlocked ? "success" : "outline"}>{activeLabel}</Badge>
                <h3 className="mt-3 text-2xl font-semibold tracking-normal text-foreground">{unlockedTitle}</h3>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  {selectedPack.packId === BASIC_PACK_ID
                    ? "Connect the model, memory, messaging, browser-use, and update settings that every Elevate install needs before paid packs start."
                    : selectedPack.unlocked
                      ? "Connect the providers and credential references this pack needs. Elevate stores the workflow contract in SQLite and saves secrets or account refs into the local .env file."
                      : "This pack stays hidden from production users until their license unlocks it."}
                </p>
              </div>
              <div className={cn("pack-unlock-check flex h-12 w-12 items-center justify-center rounded-sm border", savedPulse && "is-saved")}>
                <Sparkles className="h-5 w-5 text-primary" />
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              {(["celebrate", "providers", "credentials"] as const).map((name, index) => (
                <button
                  key={name}
                  type="button"
                  className={cn(
                    "inline-flex min-h-9 items-center gap-2 rounded-sm border px-3 text-xs font-medium transition-colors",
                    step === name
                      ? "border-primary bg-muted text-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                  onClick={() => setStep(name)}
                  disabled={!selectedPack.unlocked}
                >
                  <span>{index + 1}</span>
                  {name === "celebrate" ? "Unlock" : name === "providers" ? "Providers" : "Credentials"}
                </button>
              ))}
            </div>

            {step === "celebrate" ? (
              <div className="pack-step-enter mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
                <div className="rounded-md border border-border bg-card p-4">
                  <div className="text-sm font-semibold text-foreground">Before this pack can run</div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {selectedPack.items.slice(0, 6).map((item) => (
                      <div key={item.key} className="rounded-md border border-border bg-card px-3 py-2">
                        <div className="truncate text-xs font-medium text-foreground">{item.label}</div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">{item.status}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col justify-between rounded-md border border-border bg-card p-4">
                  <div>
                    <div className="text-sm font-semibold text-foreground">Next form</div>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      Start with provider names, then add credential refs or keys. Nothing launches until the setup gate is ready.
                    </p>
                  </div>
                  <Button
                    className="mt-4 w-full"
                    disabled={!selectedPack.unlocked}
                    onClick={() => setStep("providers")}
                  >
                    Start setup
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "providers" ? (
              <div className="pack-step-enter mt-5 space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  {visibleItems.map((item) => (
                    <label key={item.key} className="rounded-md border border-border bg-card p-3">
                      <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                      <Input
                        className="mt-2"
                        value={providerValues[item.key] ?? ""}
                        placeholder="Provider, account, or credential ref"
                        onChange={(event) =>
                          setProviderValues((prev) => ({ ...prev, [item.key]: event.target.value }))
                        }
                      />
                      <Input
                        className="mt-2"
                        value={notesValues[item.key] ?? ""}
                        placeholder="Notes for this workflow"
                        onChange={(event) =>
                          setNotesValues((prev) => ({ ...prev, [item.key]: event.target.value }))
                        }
                      />
                    </label>
                  ))}
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button variant="outline" onClick={() => setStep("celebrate")}>Back</Button>
                  <Button onClick={() => setStep("credentials")}>
                    Continue
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ) : null}

            {step === "credentials" ? (
              <div className="pack-step-enter mt-5 space-y-3">
                <div className="rounded-md border border-border bg-card p-3 text-xs leading-5 text-muted-foreground">
                  Values entered here are saved through the dashboard env endpoint into the local Elevate `.env`. Use API keys,
                  tokens, account IDs, or credential refs. Avoid raw passwords unless the local operator explicitly wants that.
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {credentialFields.map((field) => (
                    <label key={field.key} className="rounded-md border border-border bg-card p-3">
                      <span className="text-xs font-medium text-muted-foreground">{field.label}</span>
                      <Input
                        className="mt-2 font-mono-ui text-xs"
                        type={field.password ? "password" : "text"}
                        value={envValues[field.key] ?? ""}
                        placeholder={field.key}
                        onChange={(event) =>
                          setEnvValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                        }
                      />
                    </label>
                  ))}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs text-muted-foreground">
                    {adminSetup?.memory?.synced ? "Admin memory is synced." : "Memory sync will update after save."}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => setStep("providers")}>Back</Button>
                    <Button disabled={saving} onClick={() => void savePack()}>
                      {saving ? "Saving..." : "Save onboarding"}
                    </Button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function DesktopSetupPage() {
  const [state, setState] = useState<LoadState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);
  const [actionName, setActionName] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const { toast, showToast } = useToast();
  const { setAfterTitle, setEnd } = usePageHeader();

  const load = useCallback(async () => {
    setLoading(true);
    const [statusResult, accessResult, hubResult] = await Promise.allSettled([
      api.getStatus(),
      api.getAccessStatus(),
      api.getAgentHub({ lite: true }),
    ]);

    setState((prev) => ({
      ...prev,
      access: accessResult.status === "fulfilled" ? accessResult.value : prev.access,
      hub: hubResult.status === "fulfilled" ? hubResult.value : prev.hub,
      status: statusResult.status === "fulfilled" ? statusResult.value : prev.status,
    }));
    if (statusResult.status === "rejected" && hubResult.status === "rejected") {
      const reason = statusResult.reason instanceof Error ? statusResult.reason.message : "Desktop setup failed to load";
      showToast(reason, "error");
    }
    setLoading(false);
    setUpdatedAt(new Date());

    const [
      adminSetupResult,
      packOnboardingResult,
      oauthResult,
      connectorsResult,
      composioResult,
      harnessResult,
      updateStatusResult,
    ] = await Promise.allSettled([
      api.getAdminSetup(),
      api.getPackOnboarding(),
      api.getOAuthProviders(),
      api.getSourceConnectors(),
      api.getComposioStatus(),
      api.getHarness(),
      api.getUpdateStatus(),
    ]);

    setState((prev) => ({
      ...prev,
      adminSetup: adminSetupResult.status === "fulfilled" ? adminSetupResult.value : prev.adminSetup,
      composio: composioResult.status === "fulfilled" ? composioResult.value : prev.composio,
      connectors: connectorsResult.status === "fulfilled" ? connectorsResult.value : prev.connectors,
      harness: harnessResult.status === "fulfilled" ? harnessResult.value : prev.harness,
      oauth: oauthResult.status === "fulfilled" ? oauthResult.value : prev.oauth,
      packOnboarding: packOnboardingResult.status === "fulfilled" ? packOnboardingResult.value : prev.packOnboarding,
      updateStatus: updateStatusResult.status === "fulfilled" ? updateStatusResult.value : prev.updateStatus,
    }));
    setUpdatedAt(new Date());
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const runAction = useCallback(
    async (name: "restart" | "update" | "verify" | "complete") => {
      setActionName(name);
      try {
        if (name === "restart") {
          await api.restartGateway();
          showToast("Gateway restart queued.", "success");
        } else if (name === "update") {
          await api.updateElevate();
          showToast("Update queued. Watch Logs for progress.", "success");
        } else if (name === "verify") {
          const next = await api.verifyAdminSetup();
          setState((prev) => ({ ...prev, adminSetup: next }));
          showToast("Admin setup verified.", "success");
        } else {
          const next = await api.completeAdminSetup();
          setState((prev) => ({ ...prev, adminSetup: next }));
          showToast("Admin setup marked complete.", "success");
        }
        await load();
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Action failed", "error");
      } finally {
        setActionName(null);
      }
    },
    [load, showToast],
  );

  const requiredAgents = useMemo(
    () => state.hub?.agents.filter((agent) => REQUIRED_AGENT_IDS.has(agent.id)) ?? [],
    [state.hub],
  );
  const separateLaneCount = requiredAgents.filter(
    (agent) =>
      agent.telegramLane?.tokenConfigured &&
      agent.telegramLane?.targetConfigured &&
      !agent.telegramLane?.duplicateSharedBot,
  ).length;
  const lanesReady = requiredAgents.length >= REQUIRED_AGENT_IDS.size && separateLaneCount === requiredAgents.length;

  const oauthConnected = state.oauth?.providers.filter((provider) => provider.status.logged_in).length ?? 0;
  const sourceConnected = state.connectors?.connectors.filter((connector) => connector.connected).length ?? 0;
  const composioReady = Boolean(state.composio?.configured && state.composio.valid);
  const accountReady = composioReady || oauthConnected > 0 || sourceConnected > 0;

  const setup = state.adminSetup;
  const setupReady = Boolean(setup?.canStartAdmin || setup?.complete);
  const setupWarning = Boolean(setup && !setupReady && setup.completedRequiredCount > 0);
  const packSetupReady = Boolean(state.packOnboarding?.complete);
  const packSetupWarning = Boolean(
    state.packOnboarding && !packSetupReady && state.packOnboarding.completedActiveCount > 0,
  );
  const gatewayReady = Boolean(state.status?.gateway_running && state.hub?.gateway.running);
  const worker = state.hub?.agentWorker;
  const workerReady = Boolean(worker?.enabled && worker.state !== "error" && worker.state !== "disabled");
  const runtimeReady = gatewayReady && workerReady;
  const harness = safeHarness(state.harness ?? state.hub?.harness ?? null);
  const reliabilityReady = Boolean(harness || state.hub?.cron.total || state.hub?.memory.db_exists);
  const updatesAvailable = Boolean(state.updateStatus?.available && state.updateStatus.behind);

  const readySections = [packSetupReady, setupReady, runtimeReady, lanesReady, accountReady, reliabilityReady].filter(Boolean).length;
  const totalSections = 6;
  const overallReady = readySections === totalSections;

  useLayoutEffect(() => {
    setAfterTitle(
      <Badge variant={overallReady ? "success" : readySections >= 3 ? "warning" : "outline"}>
        {readySections}/{totalSections} ready
      </Badge>,
    );
    setEnd(
      <div className="flex items-center gap-2">
        {updatedAt ? (
          <span className="hidden text-xs text-muted-foreground sm:inline">Updated {updatedAt.toLocaleTimeString()}</span>
        ) : null}
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [load, loading, overallReady, readySections, setAfterTitle, setEnd, updatedAt]);

  const handleAuthChange = useCallback(
    (authenticated: boolean) => {
      if (authenticated) void load();
    },
    [load],
  );

  if (loading && !state.status && !state.hub) {
    return (
      <p className="px-1 py-1 text-xs text-muted-foreground/80">Loading desktop setup…</p>
    );
  }

  return (
    <div className="normal-case flex flex-col gap-5 pb-4 tracking-normal">
      <Toast toast={toast} />

      <section className="grid gap-4 xl:grid-cols-2">
        <LoginCard onAuthChange={handleAuthChange} />
      </section>

      <section className="overflow-hidden rounded-md border border-border bg-card">
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={overallReady ? "success" : "warning"}>
                {overallReady ? "Production runway ready" : "Setup runway"}
              </Badge>
              <Badge variant={gatewayReady ? "success" : "outline"}>
                {state.status?.gateway_running ? "gateway online" : "gateway offline"}
              </Badge>
              <Badge variant={workerReady ? "success" : "outline"}>worker {worker?.state ?? "unknown"}</Badge>
              <Badge variant={lanesReady ? "success" : "warning"}>{separateLaneCount}/2 Telegram lanes</Badge>
              <Badge variant={updatesAvailable ? "warning" : "outline"}>
                {updatesAvailable ? `${state.updateStatus?.behind} updates available` : "up to date"}
              </Badge>
              <Badge variant={packSetupReady ? "success" : packSetupWarning ? "warning" : "outline"}>
                {state.packOnboarding?.activeCount ?? 0} packs active
              </Badge>
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-normal text-foreground sm:text-3xl">
              Desktop setup
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              One place to see whether this local Elevate install is actually ready to run for a realtor: runtime,
              separate agent inboxes, connected accounts, admin setup, and the logs needed to debug handoffs.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName)}
                onClick={() => void runAction("restart")}
              >
                <RotateCw className={cn("h-3.5 w-3.5", actionName === "restart" && "animate-spin")} />
                Restart gateway
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName)}
                onClick={() => void runAction("update")}
              >
                <RefreshCw className={cn("h-3.5 w-3.5", actionName === "update" && "animate-spin")} />
                {updatesAvailable ? "Updates available" : "Update"}
              </Button>
              <SetupLink to="/logs">
                <FileText className="h-3.5 w-3.5" />
                Logs
              </SetupLink>
              <SetupLink to="/project">
                <FolderOpen className="h-3.5 w-3.5" />
                Local files
              </SetupLink>
            </div>
          </div>

          <div className="grid gap-2">
            <RunwayStep
              icon={Sparkles}
              label="Unlocked pack onboarding"
              tone={packSetupReady ? "success" : packSetupWarning ? "warning" : "outline"}
              description={`${state.packOnboarding?.completedActiveCount ?? 0}/${state.packOnboarding?.activeCount ?? 0} active packs ready.`}
            />
            <RunwayStep
              icon={ShieldCheck}
              label="Admin setup"
              tone={setupReady ? "success" : setupWarning ? "warning" : "outline"}
              description={
                setup
                  ? `${setup.completedRequiredCount}/${setup.requiredCount} required setup items complete.`
                  : "Admin onboarding snapshot is not available yet."
              }
            />
            <RunwayStep
              icon={Terminal}
              label="Runtime loop"
              tone={runtimeReady ? "success" : gatewayReady ? "warning" : "outline"}
              description={`Gateway ${state.status?.gateway_state ?? "unknown"}; worker ${worker?.state ?? "unknown"}.`}
            />
            <RunwayStep
              icon={MessageSquare}
              label="Agent Telegram lanes"
              tone={lanesReady ? "success" : separateLaneCount > 0 ? "warning" : "outline"}
              description="Executive Assistant and Admin need separate bot tokens and chat targets."
            />
            <RunwayStep
              icon={KeyRound}
              label="Connected accounts"
              tone={accountReady ? "success" : "outline"}
              description={`${oauthConnected} OAuth, ${sourceConnected} source connector, Composio ${
                composioReady ? "ready" : "not ready"
              }.`}
            />
          </div>
        </div>
      </section>

      <PackUnlockOnboarding
        adminSetup={state.adminSetup}
        notify={showToast}
        snapshot={state.packOnboarding}
        onSaved={load}
      />

      <section className="grid gap-4 xl:grid-cols-2">
        <ReadinessCard
          icon={ShieldCheck}
          title="Realtor profile and admin launch"
          description="The source-of-truth setup gate before Admin starts moving files."
          status={statusCopy(setupReady, "Ready", setupWarning ? "Partial" : "Needs setup")}
          tone={badgeTone(setupReady, setupWarning)}
          action={
            <>
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName)}
                onClick={() => void runAction("verify")}
              >
                <CheckCircle2 className={cn("h-3.5 w-3.5", actionName === "verify" && "animate-pulse")} />
                Verify
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={Boolean(actionName) || !setup || Boolean(setup.missingRequiredKeys.length)}
                onClick={() => void runAction("complete")}
              >
                Complete setup
              </Button>
              <SetupLink to="/admin">Open Admin</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={Settings}
            label="Province"
            value={setup?.profile.province || "Not set"}
            tone={setup?.profile.province ? "success" : "outline"}
          />
          <DetailRow
            icon={Activity}
            label="Market"
            value={setup?.profile.market || "Not set"}
            tone={setup?.profile.market ? "success" : "outline"}
          />
          <DetailRow
            icon={Database}
            label="Required items"
            value={`${setup?.completedRequiredCount ?? 0}/${setup?.requiredCount ?? 0}`}
            tone={setupReady ? "success" : setupWarning ? "warning" : "outline"}
          />
          <div className="rounded-md border border-border bg-card px-3 py-2">
            <div className="text-xs font-medium text-muted-foreground">Missing launch items</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {setup?.missingRequiredKeys.length ? (
                setup.missingRequiredKeys.slice(0, 8).map((key) => (
                  <Badge key={key} variant="warning">
                    {key.replace(/_/g, " ")}
                  </Badge>
                ))
              ) : (
                <Badge variant="success">none</Badge>
              )}
            </div>
          </div>
        </ReadinessCard>

        <ReadinessCard
          icon={Terminal}
          title="Backend mode and wake loop"
          description="The local API, gateway, and handoff worker that keep agents alive."
          status={statusCopy(runtimeReady, "Running", gatewayReady ? "Worker check" : "Offline")}
          tone={badgeTone(runtimeReady, gatewayReady)}
          action={
            <>
              <SetupLink to="/hub">Agent Hub</SetupLink>
              <SetupLink to="/cron">Automations</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={Terminal}
            label="Gateway"
            value={state.status?.gateway_state || "unknown"}
            tone={gatewayReady ? "success" : "outline"}
          />
          <DetailRow
            icon={Bot}
            label="Agent worker"
            value={worker?.state || "unknown"}
            tone={workerReady ? "success" : "outline"}
          />
          <DetailRow
            icon={Clock}
            label="Heartbeat"
            value={worker?.heartbeat?.enabled ? `next ${formatTime(worker.heartbeat.nextBeatAt)}` : "off"}
            tone={worker?.heartbeat?.enabled ? "success" : "outline"}
          />
          <DetailRow
            icon={Activity}
            label="Open handoffs"
            value={state.hub?.handoffs.open ?? 0}
            tone={(state.hub?.handoffs.failed ?? 0) > 0 ? "warning" : "success"}
          />
        </ReadinessCard>

        <ReadinessCard
          icon={MessageSquare}
          title="Agent communication lanes"
          description="Separate inboxes keep Admin from replying as the Executive Assistant."
          status={statusCopy(lanesReady, "Separated", separateLaneCount > 0 ? "Partial" : "Needs lanes")}
          tone={badgeTone(lanesReady, separateLaneCount > 0)}
          action={<SetupLink to="/hub">Configure lanes</SetupLink>}
        >
          {requiredAgents.length ? (
            requiredAgents.map((agent) => <AgentLaneRow key={agent.id} agent={agent} />)
          ) : (
            <div className="rounded-md border border-border bg-card px-3 py-3 text-sm text-muted-foreground">
              Agent Hub did not return the Executive Assistant/Admin agent definitions.
            </div>
          )}
        </ReadinessCard>

        <ReadinessCard
          icon={KeyRound}
          title="Connected accounts"
          description="Composio, OAuth, and source connectors that skills use during real workflows."
          status={statusCopy(accountReady, "Connected", "Needs accounts")}
          tone={badgeTone(accountReady)}
          action={
            <>
              <SetupLink to="/config">Connections</SetupLink>
              <SetupLink to="/env">Keys</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={KeyRound}
            label="Composio"
            value={composioReady ? "ready" : state.composio?.configured ? "check failed" : "not configured"}
            tone={composioReady ? "success" : state.composio?.configured ? "warning" : "outline"}
          />
          <DetailRow
            icon={ShieldCheck}
            label="OAuth providers"
            value={`${oauthConnected}/${state.oauth?.providers.length ?? 0}`}
            tone={oauthConnected > 0 ? "success" : "outline"}
          />
          <DetailRow
            icon={Database}
            label="Source connectors"
            value={`${sourceConnected}/${state.connectors?.connectors.length ?? 0}`}
            tone={sourceConnected > 0 ? "success" : "outline"}
          />
          <DetailRow
            icon={Bot}
            label="Configured platforms"
            value={state.hub?.platforms.filter((platform) => platform.configured).length ?? 0}
            tone={(state.hub?.platforms.filter((platform) => platform.configured).length ?? 0) > 0 ? "success" : "outline"}
          />
        </ReadinessCard>

        <ReadinessCard
          icon={Database}
          title="Memory, runs, and recovery"
          description="The durability layer for handoffs, callbacks, traces, and source-of-truth state."
          status={statusCopy(reliabilityReady, "Visible", "Needs checks")}
          tone={badgeTone(reliabilityReady)}
          action={
            <>
              <SetupLink to="/memory">Memory</SetupLink>
              <SetupLink to="/logs">Logs</SetupLink>
              <SetupLink to="/tasks">Tasks</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={Database}
            label="Memory database"
            value={state.hub?.memory.db_exists ? "present" : "missing"}
            tone={state.hub?.memory.db_exists ? "success" : "outline"}
          />
          <DetailRow
            icon={Activity}
            label="Cron jobs"
            value={`${state.hub?.cron.enabled ?? 0}/${state.hub?.cron.total ?? 0}`}
            tone={(state.hub?.cron.enabled ?? 0) > 0 ? "success" : "outline"}
          />
          <DetailRow
            icon={ShieldCheck}
            label="Harness"
            value={harness ? `${harness.orchestration.total_agents} agents` : "not visible"}
            tone={harness ? "success" : "outline"}
          />
          <DetailRow
            icon={Clock}
            label="Last worker tick"
            value={formatTime(worker?.lastTickAt)}
            tone={worker?.lastTickAt ? "success" : "outline"}
          />
        </ReadinessCard>

        <ReadinessCard
          icon={FolderOpen}
          title="Diagnostics and support"
          description="The desktop support surface: where to inspect state before touching a live deal."
          status="Available"
          tone="success"
          action={
            <>
              <SetupLink to="/project">Project</SetupLink>
              <SetupLink to="/analytics">Analytics</SetupLink>
            </>
          }
        >
          <DetailRow
            icon={FolderOpen}
            label="Project root"
            value={state.status?.project_root ? "visible" : "unknown"}
            tone={state.status?.project_root ? "success" : "outline"}
          />
          <DetailRow
            icon={Settings}
            label="Config"
            value={state.status?.config_version ?? "unknown"}
            tone={
              state.status && state.status.config_version === state.status.latest_config_version
                ? "success"
                : "warning"
            }
          />
          <DetailRow
            icon={KeyRound}
            label="Secrets file"
            value={state.status?.env_path ? "visible" : "unknown"}
            tone={state.status?.env_path ? "success" : "outline"}
          />
          <DetailRow
            icon={FileText}
            label="Release"
            value={state.status?.version ? `v${state.status.version}` : "unknown"}
            tone="outline"
          />
        </ReadinessCard>
      </section>
    </div>
  );
}

```

---
## `src/components/agent-hub/AgentConfigEditor.tsx`
```tsx
import { useEffect, useMemo, useState } from "react";
import { Loader2, Save, Settings, MessageSquare } from "lucide-react";
import type { AgentHubAgent } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

export type AgentEditPatch = {
  enabled?: boolean;
  prompt?: string;
  description?: string;
  skills?: string[];
  toolsets?: string[];
  platforms?: string[];
};

export type SkillEntry = { name: string; category: string; description: string };
export type ToolsetEntry = { name: string; label: string; description: string };

export function arraysEqual(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const sortedA = [...a].sort();
  const sortedB = [...b].sort();
  return sortedA.every((value, index) => value === sortedB[index]);
}

export function MultiSelectGrid({
  options,
  selected,
  onToggle,
  empty,
  searchable = false,
  getLabel,
  getDescription,
  getCategory,
}: {
  options: Array<{ name: string }>;
  selected: string[];
  onToggle: (name: string) => void;
  empty: string;
  searchable?: boolean;
  getLabel?: (name: string) => string;
  getDescription?: (name: string) => string;
  getCategory?: (name: string) => string;
}) {
  const [query, setQuery] = useState("");
  const selectedSet = new Set(selected);

  const annotated = useMemo(
    () =>
      options.map((option) => ({
        name: option.name,
        label: getLabel?.(option.name) ?? option.name,
        description: getDescription?.(option.name) ?? "",
        category: getCategory?.(option.name) ?? "",
      })),
    [options, getLabel, getDescription, getCategory],
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return annotated;
    return annotated.filter(
      (entry) =>
        entry.name.toLowerCase().includes(needle) ||
        entry.label.toLowerCase().includes(needle) ||
        entry.description.toLowerCase().includes(needle) ||
        entry.category.toLowerCase().includes(needle),
    );
  }, [annotated, query]);

  if (options.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-background/40 px-2.5 py-3 text-xs text-muted-foreground">
        {empty}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {searchable && options.length > 6 && (
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`Search ${options.length} options`}
          className="h-7 text-xs"
        />
      )}
      <div className="grid max-h-56 gap-1 overflow-y-auto pr-1 sm:grid-cols-2">
        {filtered.length === 0 ? (
          <div className="col-span-full px-1 py-2 text-xs text-muted-foreground">
            No matches for "{query}"
          </div>
        ) : (
          filtered.map((entry) => {
            const isOn = selectedSet.has(entry.name);
            return (
              <label
                key={entry.name}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-md border px-2 py-1.5 text-xs transition-colors",
                  isOn
                    ? "border-primary/40 bg-primary/5 text-foreground"
                    : "border-border/60 bg-background/40 text-muted-foreground hover:text-foreground",
                )}
                title={entry.description || entry.label}
              >
                <input
                  type="checkbox"
                  checked={isOn}
                  onChange={() => onToggle(entry.name)}
                  className="mt-0.5 h-3 w-3 cursor-pointer accent-[--color-primary]"
                />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-medium">{entry.label}</span>
                  {entry.category && (
                    <span className="truncate text-[0.65rem] uppercase tracking-wide text-muted-foreground/70">
                      {entry.category}
                    </span>
                  )}
                </span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

export function AgentConfigEditor({
  agent,
  availableSkills,
  availableToolsets,
  availablePlatforms,
  saving,
  onSave,
}: {
  agent: AgentHubAgent;
  availableSkills: SkillEntry[];
  availableToolsets: ToolsetEntry[];
  availablePlatforms: string[];
  saving: boolean;
  onSave: (patch: AgentEditPatch) => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(agent.enabled);
  const [description, setDescription] = useState(agent.description ?? "");
  const [prompt, setPrompt] = useState<string>("");
  const [promptLoaded, setPromptLoaded] = useState(false);
  const [skills, setSkills] = useState<string[]>(agent.skills);
  const [toolsets, setToolsets] = useState<string[]>(agent.toolsets);
  const [platforms, setPlatforms] = useState<string[]>(agent.platforms);

  useEffect(() => {
    setEnabled(agent.enabled);
    setDescription(agent.description ?? "");
    setSkills(agent.skills);
    setToolsets(agent.toolsets);
    setPlatforms(agent.platforms);
    setPromptLoaded(false);
    setPrompt("");
  }, [
    agent.id,
    agent.enabled,
    agent.description,
    agent.skills,
    agent.toolsets,
    agent.platforms,
  ]);

  const togglePlatform = (name: string) =>
    setPlatforms((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );
  const toggleSkill = (name: string) =>
    setSkills((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );
  const toggleToolset = (name: string) =>
    setToolsets((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name],
    );

  const dirty =
    enabled !== agent.enabled ||
    description !== (agent.description ?? "") ||
    (promptLoaded && prompt !== "") ||
    !arraysEqual(skills, agent.skills) ||
    !arraysEqual(toolsets, agent.toolsets) ||
    !arraysEqual(platforms, agent.platforms);

  const handleSave = () => {
    const patch: AgentEditPatch = {};
    if (enabled !== agent.enabled) patch.enabled = enabled;
    if (description !== (agent.description ?? "")) patch.description = description;
    if (promptLoaded && prompt.trim()) patch.prompt = prompt;
    if (!arraysEqual(skills, agent.skills)) patch.skills = skills;
    if (!arraysEqual(toolsets, agent.toolsets)) patch.toolsets = toolsets;
    if (!arraysEqual(platforms, agent.platforms)) patch.platforms = platforms;
    if (Object.keys(patch).length === 0) return;
    void onSave(patch);
  };

  const skillOptions = useMemo(() => availableSkills.map((s) => ({ name: s.name })), [availableSkills]);
  const toolsetOptions = useMemo(
    () => availableToolsets.map((t) => ({ name: t.name })),
    [availableToolsets],
  );
  const platformOptions = useMemo(
    () => availablePlatforms.map((name) => ({ name })),
    [availablePlatforms],
  );

  const skillDescription = (name: string) =>
    availableSkills.find((s) => s.name === name)?.description ?? "";
  const skillCategory = (name: string) =>
    availableSkills.find((s) => s.name === name)?.category ?? "";
  const toolsetLabel = (name: string) =>
    availableToolsets.find((t) => t.name === name)?.label ?? name;
  const toolsetDescription = (name: string) =>
    availableToolsets.find((t) => t.name === name)?.description ?? "";

  return (
    <details className="group/config rounded-md border border-border/60 bg-background/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        <span className="flex items-center gap-2">
          <Settings className="h-3.5 w-3.5" />
          <span>Configure</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {agent.skills.length} skills · {agent.toolsets.length} tools
        </span>
      </summary>
      <div className="grid gap-3 px-2.5 pb-3 pt-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col">
            <span className="text-xs font-medium text-foreground">Enabled</span>
            <span className="text-xs text-muted-foreground">
              Disabled agents won't take work or handoffs.
            </span>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          <span>Description</span>
          <Input
            value={description}
            placeholder="One-line role description"
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>

        <div className="grid gap-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">System prompt / rules</span>
            <span className="text-xs text-muted-foreground">
              {agent.has_prompt ? "Custom prompt set" : "Using default"}
            </span>
          </div>
          {promptLoaded ? (
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={5}
              className="w-full resize-y rounded-md border border-border bg-background px-2.5 py-1.5 text-xs leading-5 text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/70"
              placeholder="Define this agent's responsibilities, voice, and handoff rules…"
            />
          ) : (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setPromptLoaded(true);
                setPrompt("");
              }}
            >
              Edit prompt
            </Button>
          )}
          {promptLoaded && (
            <span className="text-xs text-muted-foreground">
              Leave empty to keep the existing prompt. Anything typed here replaces it.
            </span>
          )}
        </div>

        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Platforms ({platforms.length})
          </span>
          <MultiSelectGrid
            options={platformOptions}
            selected={platforms}
            onToggle={togglePlatform}
            empty="No platforms available"
          />
        </div>

        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Skills ({skills.length} of {availableSkills.length})
          </span>
          <MultiSelectGrid
            options={skillOptions}
            selected={skills}
            onToggle={toggleSkill}
            empty={
              availableSkills.length === 0
                ? "Loading installed skills…"
                : "No skills installed yet."
            }
            searchable
            getDescription={skillDescription}
            getCategory={skillCategory}
          />
        </div>

        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted-foreground">
            Toolsets ({toolsets.length} of {availableToolsets.length})
          </span>
          <MultiSelectGrid
            options={toolsetOptions}
            selected={toolsets}
            onToggle={toggleToolset}
            empty={
              availableToolsets.length === 0
                ? "Loading toolsets…"
                : "No toolsets registered."
            }
            searchable
            getLabel={toolsetLabel}
            getDescription={toolsetDescription}
          />
        </div>

        <div className="flex justify-end">
          <Button size="sm" onClick={handleSave} disabled={!dirty || saving}>
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save changes
          </Button>
        </div>
      </div>
    </details>
  );
}

// Per-agent Telegram lane editor. Each Agent Hub agent can have its own bot
// token + chat target, completely separate from the primary Elevate bot.
export function AgentTelegramLaneEditor({
  agent,
  tokenValue,
  laneValue,
  tokenPlaceholder,
  lanePlaceholder,
  onTokenChange,
  onLaneChange,
  onSave,
  saving,
}: {
  agent: AgentHubAgent;
  tokenValue: string;
  laneValue: string;
  tokenPlaceholder?: string;
  lanePlaceholder?: string;
  onTokenChange: (value: string) => void;
  onLaneChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
}) {
  const lane = agent.telegramLane;
  const ready = Boolean(lane?.configured);
  const changed = Boolean(tokenValue.trim() || laneValue.trim());
  const state = ready
    ? "Configured"
    : lane?.duplicateSharedBot
      ? "Duplicate bot token"
      : lane?.usesSharedBot
        ? "Needs own bot token"
        : lane?.tokenConfigured
          ? "Missing chat target"
          : lane?.targetConfigured
            ? "Missing bot token"
            : "Missing bot token and chat target";
  const detail = lane
    ? `${lane.tokenEnv || "agent token env"} + ${lane.targetEnv || "agent chat env"}`
    : "No Telegram lane required";

  return (
    <details className="group/telegram rounded-md border border-border/60 bg-background/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
        <span className="flex items-center gap-2">
          <MessageSquare className="h-3.5 w-3.5" />
          <span>Telegram lane</span>
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1.5",
            ready ? "text-muted-foreground" : "text-warning",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              ready ? "bg-success" : "bg-warning",
            )}
          />
          {state}
        </span>
      </summary>
      <div className="grid gap-2 px-2.5 pb-2.5 pt-1">
        {!ready && (
          <p className="text-[0.72rem] leading-5 text-muted-foreground">
            Both fields required. Get a bot token from @BotFather, then paste your chat ID (or chat:topic) from the agent's Telegram conversation.
          </p>
        )}
        <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Bot token</span>
            <Input
              autoComplete="new-password"
              type="password"
              value={tokenValue}
              placeholder={tokenPlaceholder ?? "BotFather token"}
              onChange={(event) => onTokenChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && changed) {
                  event.preventDefault();
                  onSave();
                }
              }}
            />
          </label>
          <label className="grid gap-1 text-xs font-medium text-muted-foreground">
            <span>Chat/topic ID</span>
            <Input
              value={laneValue}
              placeholder={lanePlaceholder ?? "Chat ID or chat:topic"}
              onChange={(event) => onLaneChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && changed) {
                  event.preventDefault();
                  onSave();
                }
              }}
            />
          </label>
          <Button
            size="sm"
            variant="outline"
            onClick={onSave}
            disabled={saving || !changed}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Save
          </Button>
        </div>
        {lane && (
          <div className="min-w-0 truncate text-xs text-muted-foreground">
            {detail}
          </div>
        )}
        {lane?.duplicateSharedBot && (
          <div className="text-xs leading-5 text-warning">
            This agent is using the Executive bot token. Create a separate BotFather token for this agent.
          </div>
        )}
      </div>
    </details>
  );
}

```
