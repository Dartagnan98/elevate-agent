import { Markdown } from "@/components/Markdown";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import { ToolCall, type ToolEntry } from "@/components/ToolCall";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";
import {
  GatewayClient,
  type ConnectionState,
  type GatewayEvent,
} from "@/lib/gatewayClient";
import { executeSlash } from "@/lib/slashExec";
import { cn } from "@/lib/utils";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  FileCode2,
  FileText,
  Loader2,
  MessageSquare,
  PanelRight,
  RotateCcw,
  Send,
  Settings2,
  ShieldAlert,
  Square,
  User,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";

interface SessionInfo {
  config_warning?: string;
  credential_warning?: string;
  cwd?: string;
  model?: string;
  provider?: string;
}

interface GatewayTranscriptMessage {
  context?: string;
  name?: string;
  role: "assistant" | "system" | "tool" | "user";
  text?: string;
}

interface SessionCreateResponse {
  info?: SessionInfo;
  session_id: string;
}

interface SessionResumeResponse extends SessionCreateResponse {
  messages?: GatewayTranscriptMessage[];
  resumed?: string;
}

type ChatRole = "assistant" | "system" | "tool" | "user";

interface ChatMessage {
  content: string;
  createdAt: number;
  id: string;
  role: ChatRole;
  status?: "streaming" | "complete" | "error" | "interrupted";
  title?: string;
  warning?: string;
}

type ArtifactKind = "diff" | "file" | "output";

interface ArtifactEntry {
  content?: string;
  createdAt: number;
  detail?: string;
  id: string;
  kind: ArtifactKind;
  key: string;
  path?: string;
  source?: string;
  status?: "error" | "ok";
  title: string;
}

type PendingPrompt =
  | {
      choices?: string[] | null;
      question: string;
      requestId: string;
      type: "clarify";
    }
  | {
      command: string;
      description: string;
      type: "approval";
    }
  | {
      requestId: string;
      type: "sudo";
    }
  | {
      envVar?: string;
      prompt?: string;
      requestId: string;
      type: "secret";
    };

const ARTIFACT_LIMIT = 32;
const TOOL_LIMIT = 24;

const STATE_LABEL: Record<ConnectionState, string> = {
  closed: "closed",
  connecting: "connecting",
  error: "error",
  idle: "idle",
  open: "live",
};

const STATE_TONE: Record<ConnectionState, string> = {
  closed: "bg-muted text-muted-foreground",
  connecting: "bg-primary/10 text-primary",
  error: "bg-destructive/10 text-destructive",
  idle: "bg-muted text-muted-foreground",
  open: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
};

function id(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function normalizeTranscript(messages?: GatewayTranscriptMessage[]): ChatMessage[] {
  return (messages ?? [])
    .filter((m) => m.text || m.context)
    .map((m, index) => ({
      content: String(m.text ?? m.context ?? ""),
      createdAt: Date.now() - Math.max(0, (messages?.length ?? 0) - index),
      id: id(`history-${index}`),
      role: m.role,
      status: "complete" as const,
      title: m.name,
    }));
}

function eventText(ev: GatewayEvent): string {
  const payload = ev.payload;
  if (!payload || typeof payload !== "object") return "";
  const raw = (payload as Record<string, unknown>).text;
  return typeof raw === "string" ? raw : "";
}

function eventString(ev: GatewayEvent, key: string): string {
  const payload = ev.payload;
  if (!payload || typeof payload !== "object") return "";
  const raw = (payload as Record<string, unknown>)[key];
  return typeof raw === "string" ? raw : "";
}

function modelLabel(info: SessionInfo): string {
  const model = info.model || "model";
  return model.split("/").slice(-1)[0] || model;
}

function nowLabel(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function compactToolPayload(payload: unknown) {
  return (payload && typeof payload === "object"
    ? payload
    : {}) as Record<string, unknown>;
}

function fileName(path: string): string {
  return path.replace(/\\/g, "/").split("/").filter(Boolean).pop() || path;
}

function artifactKey(entry: Omit<ArtifactEntry, "createdAt" | "id" | "key">) {
  return [
    entry.kind,
    entry.path ?? "",
    entry.source ?? "",
    entry.title,
    (entry.content ?? "").slice(0, 120),
  ].join(":");
}

function makeArtifact(
  entry: Omit<ArtifactEntry, "createdAt" | "id" | "key">,
): ArtifactEntry {
  const key = artifactKey(entry);

  return {
    ...entry,
    createdAt: Date.now(),
    id: id(`artifact-${entry.kind}`),
    key,
  };
}

function extractPathsFromText(text: string): string[] {
  const matches = text.match(
    /(?:~|\/)[A-Za-z0-9._~+\-/ ]+\.(?:csv|docx|gif|html|jpeg|jpg|json|log|md|pdf|png|pptx|svg|txt|webp|xlsx|ya?ml|zip)\b/g,
  );
  return Array.from(new Set(matches ?? [])).slice(0, 12);
}

function artifactsFromText(text: string, source: string): ArtifactEntry[] {
  return extractPathsFromText(text).map((path) =>
    makeArtifact({
      detail: path,
      kind: "file",
      path,
      source,
      title: fileName(path),
    }),
  );
}

function artifactsFromToolComplete(
  payload: Record<string, unknown>,
): ArtifactEntry[] {
  const toolName = String(payload.name ?? "tool");
  const artifacts: ArtifactEntry[] = [];
  const inlineDiff =
    typeof payload.inline_diff === "string" ? payload.inline_diff : "";
  const summary = typeof payload.summary === "string" ? payload.summary : "";

  if (inlineDiff) {
    artifacts.push(
      makeArtifact({
        content: inlineDiff,
        detail: toolName,
        kind: "diff",
        source: toolName,
        title: `${toolName} changes`,
      }),
    );
    artifacts.push(...artifactsFromText(inlineDiff, toolName));
  }

  if (summary) {
    artifacts.push(...artifactsFromText(summary, toolName));
  }

  return artifacts;
}

function artifactsFromSubagentEvent(
  payload: Record<string, unknown>,
): ArtifactEntry[] {
  const artifacts: ArtifactEntry[] = [];
  const source = String(payload.goal || payload.subagent_id || "agent");
  const filesWritten = Array.isArray(payload.files_written)
    ? payload.files_written.map(String)
    : [];
  const outputTail = Array.isArray(payload.output_tail)
    ? payload.output_tail
    : [];
  const summary = typeof payload.summary === "string" ? payload.summary : "";

  for (const path of filesWritten) {
    artifacts.push(
      makeArtifact({
        detail: path,
        kind: "file",
        path,
        source,
        title: fileName(path),
      }),
    );
  }

  outputTail.forEach((raw, index) => {
    const item = compactToolPayload(raw);
    const preview = typeof item.preview === "string" ? item.preview : "";
    const tool = String(item.tool ?? "tool");
    if (!preview) return;
    artifacts.push(
      makeArtifact({
        content: preview,
        detail: source,
        kind: "output",
        source: tool,
        status: item.is_error ? "error" : "ok",
        title: `${tool} output ${index + 1}`,
      }),
    );
    artifacts.push(...artifactsFromText(preview, tool));
  });

  if (summary) {
    artifacts.push(...artifactsFromText(summary, source));
  }

  return artifacts;
}

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const resumeId = searchParams.get("resume");
  const [version, setVersion] = useState(0);
  const gw = useMemo(() => new GatewayClient(), [version]);

  const [state, setState] = useState<ConnectionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const activeSessionRef = useRef<string | null>(null);
  const currentAssistantRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const [info, setInfo] = useState<SessionInfo>({});
  const [artifacts, setArtifacts] = useState<ArtifactEntry[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState("Connecting...");
  const [banner, setBanner] = useState<string | null>(() =>
    typeof window !== "undefined" && !window.__ELEVATE_SESSION_TOKEN__
      ? "Session token unavailable. Open this page through `elevate dashboard`, not directly."
      : null,
  );
  const [pendingPrompt, setPendingPrompt] = useState<PendingPrompt | null>(null);
  const [promptValue, setPromptValue] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const [mobilePanelOpen, setMobilePanelOpen] = useState(false);
  const [portalRoot] = useState<HTMLElement | null>(() =>
    typeof document !== "undefined" ? document.body : null,
  );
  const [narrow, setNarrow] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(max-width: 1023px)").matches
      : false,
  );
  const { setEnd } = usePageHeader();

  const appendMessage = useCallback(
    (role: ChatRole, content: string, extras: Partial<ChatMessage> = {}) => {
      const message: ChatMessage = {
        content,
        createdAt: Date.now(),
        id: id(role),
        role,
        ...extras,
      };
      setMessages((prev) => [...prev, message]);
      return message.id;
    },
    [],
  );

  const ensureAssistant = useCallback(() => {
    if (currentAssistantRef.current) return currentAssistantRef.current;
    const messageId = id("assistant");
    currentAssistantRef.current = messageId;
    setMessages((prev) => [
      ...prev,
      {
        content: "",
        createdAt: Date.now(),
        id: messageId,
        role: "assistant",
        status: "streaming",
      },
    ]);
    return messageId;
  }, []);

  const updateAssistant = useCallback(
    (updater: (message: ChatMessage) => ChatMessage) => {
      const messageId = ensureAssistant();
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? updater(m) : m)),
      );
    },
    [ensureAssistant],
  );

  const addArtifacts = useCallback((entries: ArtifactEntry[]) => {
    if (!entries.length) return;

    setArtifacts((prev) => {
      const seen = new Set(prev.map((entry) => entry.key));
      const next = [...prev];

      for (const entry of entries) {
        if (seen.has(entry.key)) continue;
        seen.add(entry.key);
        next.push(entry);
      }

      return next.slice(-ARTIFACT_LIMIT);
    });
  }, []);

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1023px)");
    const sync = () => setNarrow(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!mobilePanelOpen) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setMobilePanelOpen(false);
    };
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
    };
  }, [mobilePanelOpen]);

  useEffect(() => {
    if (!narrow) {
      setEnd(null);
      return;
    }

    setEnd(
      <button
        type="button"
        onClick={() => setMobilePanelOpen(true)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded border border-current/20 px-2 py-1",
          "text-[0.65rem] font-medium normal-case text-midground/80",
          "hover:bg-midground/5 hover:text-midground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground",
        )}
      >
        <PanelRight className="h-3 w-3" />
        Activity
      </button>,
    );

    return () => setEnd(null);
  }, [narrow, setEnd]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, tools, pendingPrompt]);

  useEffect(() => {
    let cancelled = false;
    const unsubs: Array<() => void> = [];

    activeSessionRef.current = null;
    currentAssistantRef.current = null;
    setSessionId(null);
    setInfo({});
    setArtifacts([]);
    setTools([]);
    setPendingPrompt(null);
    setPromptValue("");
    setBusy(false);
    setBanner(null);
    setStatusText("Connecting...");

    const accepts = (ev: GatewayEvent) => {
      const active = activeSessionRef.current;
      return !active || !ev.session_id || ev.session_id === active;
    };

    const trackTool = (ev: GatewayEvent) => {
      if (!accepts(ev)) return;
      const payload = compactToolPayload(ev.payload);

      if (ev.type === "tool.start") {
        const toolId = String(payload.tool_id ?? "");
        if (!toolId) return;

        setTools((prev) =>
          [
            ...prev,
            {
              context:
                typeof payload.context === "string" ? payload.context : "",
              id: id(`tool-${toolId}`),
              kind: "tool" as const,
              name: String(payload.name ?? "tool"),
              startedAt: Date.now(),
              status: "running" as const,
              tool_id: toolId,
            },
          ].slice(-TOOL_LIMIT),
        );
        return;
      }

      if (ev.type === "tool.progress") {
        const name = String(payload.name ?? "");
        const preview = String(payload.preview ?? "");
        if (!name || !preview) return;

        setTools((prev) =>
          prev.map((tool) =>
            tool.status === "running" && tool.name === name
              ? { ...tool, preview }
              : tool,
          ),
        );
        return;
      }

      if (ev.type === "tool.complete") {
        const toolId = String(payload.tool_id ?? "");
        if (!toolId) return;

        setTools((prev) =>
          prev.map((tool) =>
            tool.tool_id === toolId
              ? {
                  ...tool,
                  completedAt: Date.now(),
                  error:
                    typeof payload.error === "string"
                      ? payload.error
                      : undefined,
                  inline_diff:
                    typeof payload.inline_diff === "string"
                      ? payload.inline_diff
                      : undefined,
                  status: payload.error ? "error" : "done",
                  summary:
                    typeof payload.summary === "string"
                      ? payload.summary
                      : undefined,
                }
              : tool,
          ),
        );
        addArtifacts(artifactsFromToolComplete(payload));
      }
    };

    const trackSubagentArtifacts = (ev: GatewayEvent) => {
      if (!accepts(ev)) return;
      addArtifacts(artifactsFromSubagentEvent(compactToolPayload(ev.payload)));
    };

    unsubs.push(gw.onState(setState));
    unsubs.push(
      gw.on<SessionInfo>("session.info", (ev) => {
        if (!accepts(ev)) return;
        if (ev.session_id) {
          activeSessionRef.current = ev.session_id;
          setSessionId(ev.session_id);
        }
        if (ev.payload) {
          setInfo((prev) => ({ ...prev, ...ev.payload }));
          setBanner(ev.payload.credential_warning ?? ev.payload.config_warning ?? null);
        }
        setStatusText("Ready");
      }),
    );
    unsubs.push(
      gw.on("message.start", (ev) => {
        if (!accepts(ev)) return;
        currentAssistantRef.current = null;
        ensureAssistant();
        setBusy(true);
        setStatusText("Thinking...");
      }),
    );
    unsubs.push(
      gw.on("message.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (!text) return;
        updateAssistant((message) => ({
          ...message,
          content: message.content + text,
          status: "streaming",
        }));
      }),
    );
    unsubs.push(
      gw.on("message.complete", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        const status = eventString(ev, "status") || "complete";
        const warning = eventString(ev, "warning");

        updateAssistant((message) => ({
          ...message,
          content: text || message.content,
          status: status === "interrupted" ? "interrupted" : "complete",
          warning: warning || undefined,
        }));
        if (text) {
          addArtifacts(artifactsFromText(text, "assistant"));
        }
        currentAssistantRef.current = null;
        setBusy(false);
        setStatusText(status === "interrupted" ? "Interrupted" : "Ready");
      }),
    );
    unsubs.push(
      gw.on("status.update", (ev) => {
        if (!accepts(ev)) return;
        const text = eventString(ev, "text");
        if (text) setStatusText(text);
      }),
    );
    unsubs.push(
      gw.on("thinking.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) setStatusText(text);
      }),
    );
    unsubs.push(
      gw.on("reasoning.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) setStatusText(text);
      }),
    );
    unsubs.push(gw.on("tool.start", trackTool));
    unsubs.push(gw.on("tool.progress", trackTool));
    unsubs.push(gw.on("tool.complete", trackTool));
    unsubs.push(gw.on("subagent.complete", trackSubagentArtifacts));
    unsubs.push(
      gw.on("tool.generating", (ev) => {
        if (!accepts(ev)) return;
        const name = eventString(ev, "name");
        if (name) setStatusText(`Preparing ${name}`);
      }),
    );
    unsubs.push(
      gw.on("clarify.request", (ev) => {
        if (!accepts(ev)) return;
        const payload = compactToolPayload(ev.payload);
        setPendingPrompt({
          choices: Array.isArray(payload.choices)
            ? payload.choices.map(String)
            : null,
          question: String(payload.question ?? "Clarify"),
          requestId: String(payload.request_id ?? ""),
          type: "clarify",
        });
        setPromptValue("");
        setStatusText("Waiting for input");
      }),
    );
    unsubs.push(
      gw.on("approval.request", (ev) => {
        if (!accepts(ev)) return;
        const payload = compactToolPayload(ev.payload);
        setPendingPrompt({
          command: String(payload.command ?? ""),
          description: String(payload.description ?? "Approval needed"),
          type: "approval",
        });
        setStatusText("Approval needed");
      }),
    );
    unsubs.push(
      gw.on("sudo.request", (ev) => {
        if (!accepts(ev)) return;
        setPendingPrompt({
          requestId: eventString(ev, "request_id"),
          type: "sudo",
        });
        setPromptValue("");
        setStatusText("Password needed");
      }),
    );
    unsubs.push(
      gw.on("secret.request", (ev) => {
        if (!accepts(ev)) return;
        setPendingPrompt({
          envVar: eventString(ev, "env_var"),
          prompt: eventString(ev, "prompt"),
          requestId: eventString(ev, "request_id"),
          type: "secret",
        });
        setPromptValue("");
        setStatusText("Secret needed");
      }),
    );
    unsubs.push(
      gw.on("background.complete", (ev) => {
        if (!accepts(ev)) return;
        appendMessage("system", eventText(ev) || "Background task complete");
      }),
    );
    unsubs.push(
      gw.on("btw.complete", (ev) => {
        if (!accepts(ev)) return;
        appendMessage("system", eventText(ev) || "Background task complete");
      }),
    );
    unsubs.push(
      gw.on("error", (ev) => {
        if (!accepts(ev)) return;
        const message = eventString(ev, "message") || "Gateway error";
        setBanner(message);
        appendMessage("system", message, { status: "error" });
        setBusy(false);
        setStatusText("Error");
      }),
    );

    gw.connect()
      .then(async () => {
        if (cancelled) return;
        const created = resumeId
          ? await gw.request<SessionResumeResponse>("session.resume", {
              cols: 100,
              session_id: resumeId,
            })
          : await gw.request<SessionCreateResponse>("session.create", {
              cols: 100,
            });

        if (cancelled) return;
        activeSessionRef.current = created.session_id;
        setSessionId(created.session_id);
        setInfo(created.info ?? {});
        if (created.info?.credential_warning || created.info?.config_warning) {
          setBanner(
            created.info.credential_warning ?? created.info.config_warning ?? null,
          );
        }
        if ("messages" in created) {
          const resumed = created as Partial<SessionResumeResponse>;
          setMessages(
            normalizeTranscript(
              Array.isArray(resumed.messages) ? resumed.messages : undefined,
            ),
          );
        } else {
          setMessages([]);
        }
        setStatusText("Ready");
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setBanner(error.message);
        setStatusText("Connection failed");
      });

    return () => {
      cancelled = true;
      unsubs.forEach((unsub) => unsub());
      gw.close();
    };
  }, [
    addArtifacts,
    appendMessage,
    ensureAssistant,
    gw,
    resumeId,
    updateAssistant,
  ]);

  const submitPrompt = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !sessionId) return;

      appendMessage("user", trimmed);
      setInput("");
      setBanner(null);

      if (trimmed.startsWith("/")) {
        await executeSlash({
          callbacks: {
            send: submitPrompt,
            sys: (body) => appendMessage("system", body),
          },
          command: trimmed,
          gw,
          sessionId,
        });
        return;
      }

      if (busy) {
        try {
          await gw.request("session.steer", {
            session_id: sessionId,
            text: trimmed,
          });
          appendMessage("system", "Added to the running turn.");
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          appendMessage("system", message, { status: "error" });
        }
        return;
      }

      setBusy(true);
      setStatusText("Sending...");
      try {
        await gw.request("prompt.submit", {
          session_id: sessionId,
          text: trimmed,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        appendMessage("system", message, { status: "error" });
        setBusy(false);
        setStatusText("Error");
      }
    },
    [appendMessage, busy, gw, sessionId],
  );

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitPrompt(input);
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitPrompt(input);
    }
  };

  const reconnect = () => {
    setVersion((value) => value + 1);
  };

  const interrupt = async () => {
    if (!sessionId) return;
    setStatusText("Interrupting...");
    try {
      await gw.request("session.interrupt", { session_id: sessionId });
      setBusy(false);
      setStatusText("Interrupted");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendMessage("system", message, { status: "error" });
    }
  };

  const respondToPrompt = async (value: string) => {
    if (!pendingPrompt) return;

    try {
      if (pendingPrompt.type === "approval") {
        await gw.request("approval.respond", {
          choice: value,
          session_id: sessionId,
        });
      } else {
        const method =
          pendingPrompt.type === "clarify"
            ? "clarify.respond"
            : pendingPrompt.type === "sudo"
              ? "sudo.respond"
              : "secret.respond";
        const key =
          pendingPrompt.type === "clarify"
            ? "answer"
            : pendingPrompt.type === "sudo"
              ? "password"
              : "value";
        await gw.request(method, {
          [key]: value,
          request_id: pendingPrompt.requestId,
        });
      }
      setPendingPrompt(null);
      setPromptValue("");
      setStatusText("Running...");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendMessage("system", message, { status: "error" });
    }
  };

  const canSend = !!input.trim() && state === "open" && !!sessionId;
  const canPickModel = state === "open" && !!sessionId;
  const activity = (
    <ActivityPanel
      artifacts={artifacts}
      banner={banner}
      busy={busy}
      canPickModel={canPickModel}
      gw={gw}
      info={info}
      modelOpen={modelOpen}
      onCloseModel={() => setModelOpen(false)}
      onModelSubmit={(slashCommand) => {
        if (!sessionId) return;
        void executeSlash({
          callbacks: {
            send: submitPrompt,
            sys: (body) => appendMessage("system", body),
          },
          command: slashCommand,
          gw,
          sessionId,
        });
        setModelOpen(false);
      }}
      onOpenModel={() => setModelOpen(true)}
      onReconnect={reconnect}
      sessionId={sessionId}
      state={state}
      statusText={statusText}
      tools={tools}
    />
  );

  const mobileActivityPortal =
    narrow &&
    portalRoot &&
    createPortal(
      <>
        {mobilePanelOpen && (
          <button
            aria-label="Close activity"
            className="fixed inset-0 z-[55] bg-black/55 backdrop-blur-sm"
            onClick={() => setMobilePanelOpen(false)}
            type="button"
          />
        )}
        <aside
          className={cn(
            "fixed right-0 top-0 z-[60] flex h-dvh w-[min(24rem,86vw)] flex-col",
            "border-l border-border bg-background-base p-3 normal-case shadow-2xl",
            mobilePanelOpen ? "translate-x-0" : "translate-x-full",
            "transition-transform duration-200 ease-out",
          )}
        >
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold">Activity</div>
            <Button
              aria-label="Close activity"
              onClick={() => setMobilePanelOpen(false)}
              size="sm"
              variant="ghost"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          {activity}
        </aside>
      </>,
      portalRoot,
    );

  return (
    <div className="flex min-h-[calc(100vh-7rem)] flex-col normal-case">
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="flex min-h-0 flex-col rounded-lg border border-border bg-card/80 shadow-sm">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-primary" />
                <h1 className="truncate text-base font-semibold">
                  Elevate Agent
                </h1>
                <Badge className={STATE_TONE[state]}>
                  {STATE_LABEL[state]}
                </Badge>
              </div>
              <p className="mt-1 truncate text-xs text-muted-foreground">
                {resumeId ? `Resumed ${resumeId}` : "New chat"} ·{" "}
                {modelLabel(info)}
              </p>
            </div>

            <div className="flex items-center gap-2">
              {busy && (
                <Button
                  onClick={() => void interrupt()}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  <Square className="mr-1.5 h-3.5 w-3.5" />
                  Stop
                </Button>
              )}
              <Button
                onClick={reconnect}
                size="sm"
                type="button"
                variant="outline"
              >
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                Restart
              </Button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {messages.length === 0 ? (
              <EmptyState state={state} />
            ) : (
              <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
                {messages.map((message) => (
                  <MessageRow key={message.id} message={message} />
                ))}
                {pendingPrompt && (
                  <PendingPromptCard
                    pendingPrompt={pendingPrompt}
                    promptValue={promptValue}
                    setPromptValue={setPromptValue}
                    onRespond={(value) => void respondToPrompt(value)}
                  />
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <form
            className="border-t border-border bg-background-base/60 p-3"
            onSubmit={onSubmit}
          >
            <div className="mx-auto flex max-w-4xl items-end gap-2">
              <div className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 focus-within:ring-1 focus-within:ring-primary">
                <textarea
                  ref={inputRef}
                  aria-label="Message Elevate Agent"
                  className="max-h-40 min-h-12 w-full resize-none bg-transparent text-sm leading-6 text-foreground outline-none placeholder:text-muted-foreground"
                  disabled={state !== "open" || !sessionId}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={onComposerKeyDown}
                  placeholder={
                    state === "open" && sessionId
                      ? "Message Elevate Agent..."
                      : "Connecting..."
                  }
                  rows={2}
                  value={input}
                />
                <div className="flex items-center justify-between gap-2 text-[0.68rem] text-muted-foreground">
                  <span className="truncate">{statusText}</span>
                  <span>{sessionId ?? "session pending"}</span>
                </div>
              </div>
              <Button
                aria-label="Send message"
                disabled={!canSend}
                size="icon"
                type="submit"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </form>
        </section>

        <aside className="hidden min-h-0 lg:block">
          <div className="sticky top-4 h-[calc(100vh-9rem)]">{activity}</div>
        </aside>
      </div>
      {mobileActivityPortal}
    </div>
  );
}

function EmptyState({ state }: { state: ConnectionState }) {
  return (
    <div className="mx-auto flex min-h-[28rem] max-w-xl flex-col items-center justify-center text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        {state === "connecting" ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Bot className="h-5 w-5" />
        )}
      </div>
      <h2 className="text-xl font-semibold">Elevate Agent</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
        Executive Assistant is ready.
      </p>
    </div>
  );
}

function MessageRow({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  const tone =
    message.role === "system"
      ? "border-warning/25 bg-warning/5"
      : message.role === "tool"
        ? "border-primary/20 bg-primary/[0.04]"
        : isUser
          ? "border-primary/20 bg-primary/10"
          : "border-border bg-background";

  return (
    <article
      className={cn(
        "flex gap-3",
        isUser ? "flex-row-reverse text-right" : "text-left",
      )}
    >
      <div
        className={cn(
          "mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={cn("min-w-0 max-w-[78ch] flex-1", isUser && "flex justify-end")}>
        <div
          className={cn(
            "inline-block max-w-full rounded-lg border px-3 py-2 text-sm leading-6 shadow-sm",
            tone,
          )}
        >
          <div
            className={cn(
              "mb-1 flex items-center gap-2 text-[0.68rem] text-muted-foreground",
              isUser && "justify-end",
            )}
          >
            <span className="font-medium">
              {isUser
                ? "You"
                : isAssistant
                  ? "Executive Assistant"
                  : message.title || message.role}
            </span>
            <span>{nowLabel(message.createdAt)}</span>
            {message.status === "streaming" && (
              <Loader2 className="h-3 w-3 animate-spin" />
            )}
            {message.status === "interrupted" && (
              <Badge variant="secondary" className="text-[0.6rem]">
                interrupted
              </Badge>
            )}
          </div>
          {message.role === "assistant" ? (
            message.content ? (
              <Markdown content={message.content} />
            ) : (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Thinking...
              </div>
            )
          ) : (
            <div className="whitespace-pre-wrap break-words text-foreground">
              {message.content}
            </div>
          )}
          {message.warning && (
            <div className="mt-2 rounded-md border border-warning/30 bg-warning/10 px-2 py-1 text-xs text-warning">
              {message.warning}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function PendingPromptCard({
  onRespond,
  pendingPrompt,
  promptValue,
  setPromptValue,
}: {
  onRespond(value: string): void;
  pendingPrompt: PendingPrompt;
  promptValue: string;
  setPromptValue(value: string): void;
}) {
  if (pendingPrompt.type === "approval") {
    return (
      <Card className="border-warning/30 bg-warning/5 p-3">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Approval needed</div>
            <p className="mt-1 text-sm text-muted-foreground">
              {pendingPrompt.description}
            </p>
            {pendingPrompt.command && (
              <pre className="mt-2 max-h-28 overflow-auto rounded-md bg-background px-2 py-1.5 text-xs">
                {pendingPrompt.command}
              </pre>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => onRespond("once")}>
                Allow Once
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onRespond("session")}
              >
                Allow Session
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onRespond("always")}
              >
                Always
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => onRespond("deny")}
              >
                Deny
              </Button>
            </div>
          </div>
        </div>
      </Card>
    );
  }

  const choices = pendingPrompt.type === "clarify" ? pendingPrompt.choices : null;
  const title =
    pendingPrompt.type === "clarify"
      ? pendingPrompt.question
      : pendingPrompt.type === "sudo"
        ? "Sudo password"
        : pendingPrompt.prompt || `Secret${pendingPrompt.envVar ? `: ${pendingPrompt.envVar}` : ""}`;

  return (
    <Card className="border-primary/25 bg-primary/[0.04] p-3">
      <div className="mb-2 text-sm font-semibold">{title}</div>
      {choices?.length ? (
        <div className="flex flex-wrap gap-2">
          {choices.map((choice) => (
            <Button key={choice} size="sm" onClick={() => onRespond(choice)}>
              {choice}
            </Button>
          ))}
        </div>
      ) : (
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onRespond(promptValue);
          }}
        >
          <input
            autoFocus
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-primary"
            onChange={(event) => setPromptValue(event.target.value)}
            type={pendingPrompt.type === "sudo" ? "password" : "text"}
            value={promptValue}
          />
          <Button type="submit">Send</Button>
        </form>
      )}
    </Card>
  );
}

function ArtifactCard({ artifact }: { artifact: ArtifactEntry }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const Icon = artifact.kind === "diff" ? FileCode2 : FileText;
  const copyText = artifact.path ?? artifact.content ?? artifact.detail ?? artifact.title;

  const copy = () => {
    navigator.clipboard
      .writeText(copyText)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {});
  };

  return (
    <div
      className={cn(
        "rounded-md border bg-background/60 px-2 py-2 text-xs",
        artifact.status === "error" && "border-destructive/35 bg-destructive/[0.04]",
      )}
    >
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />

        <button
          className="min-w-0 flex-1 text-left"
          onClick={() => artifact.content && setOpen((value) => !value)}
          type="button"
        >
          <div className="truncate font-medium text-foreground">
            {artifact.title}
          </div>
          <div className="mt-0.5 truncate text-[0.68rem] text-muted-foreground">
            {artifact.detail || artifact.source || artifact.kind}
          </div>
        </button>

        <button
          aria-label="Copy artifact"
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
          onClick={copy}
          type="button"
        >
          {copied ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <Clipboard className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {open && artifact.content && (
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-muted/40 p-2 text-[0.68rem] leading-4 whitespace-pre-wrap">
          {artifact.content}
        </pre>
      )}
    </div>
  );
}

function ActivityPanel({
  artifacts,
  banner,
  busy,
  canPickModel,
  gw,
  info,
  modelOpen,
  onCloseModel,
  onModelSubmit,
  onOpenModel,
  onReconnect,
  sessionId,
  state,
  statusText,
  tools,
}: {
  artifacts: ArtifactEntry[];
  banner: string | null;
  busy: boolean;
  canPickModel: boolean;
  gw: GatewayClient;
  info: SessionInfo;
  modelOpen: boolean;
  onCloseModel(): void;
  onModelSubmit(slashCommand: string): void;
  onOpenModel(): void;
  onReconnect(): void;
  sessionId: string | null;
  state: ConnectionState;
  statusText: string;
  tools: ToolEntry[];
}) {
  const [toolsOpen, setToolsOpen] = useState(true);
  const [artifactsOpen, setArtifactsOpen] = useState(true);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 normal-case">
      <Card className="p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Model
            </div>
            <button
              className="mt-0.5 flex max-w-full items-center gap-1 truncate text-left text-sm font-medium hover:underline disabled:cursor-not-allowed disabled:opacity-60 disabled:no-underline"
              disabled={!canPickModel}
              onClick={onOpenModel}
              type="button"
            >
              <span className="truncate">{modelLabel(info)}</span>
              {canPickModel && <ChevronDown className="h-3 w-3 shrink-0" />}
            </button>
          </div>
          <Badge className={STATE_TONE[state]}>{STATE_LABEL[state]}</Badge>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
          )}
          <span className="min-w-0 truncate">{statusText}</span>
        </div>
      </Card>

      {banner && (
        <Card className="border-destructive/35 bg-destructive/[0.04] p-3">
          <div className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="break-words">{banner}</div>
              <Button
                className="mt-2"
                onClick={onReconnect}
                size="sm"
                variant="outline"
              >
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                Reconnect
              </Button>
            </div>
          </div>
        </Card>
      )}

      <Card className="flex max-h-64 min-h-0 flex-col p-2">
        <button
          className="flex items-center justify-between gap-2 px-1 pb-2 text-left text-xs uppercase tracking-wide text-muted-foreground"
          onClick={() => setArtifactsOpen((open) => !open)}
          type="button"
        >
          <span className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            Artifacts
          </span>
          <Badge variant="secondary" className="text-[0.6rem]">
            {artifacts.length}
          </Badge>
        </button>

        {artifactsOpen && (
          <div className="flex min-h-0 flex-col gap-1.5 overflow-y-auto pr-1">
            {artifacts.length === 0 ? (
              <div className="px-2 py-5 text-center text-xs text-muted-foreground">
                No artifacts yet
              </div>
            ) : (
              artifacts
                .slice()
                .reverse()
                .map((artifact) => (
                  <ArtifactCard key={artifact.id} artifact={artifact} />
                ))
            )}
          </div>
        )}
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col p-2">
        <button
          className="flex items-center justify-between gap-2 px-1 pb-2 text-left text-xs uppercase tracking-wide text-muted-foreground"
          onClick={() => setToolsOpen((open) => !open)}
          type="button"
        >
          <span className="flex items-center gap-1.5">
            <Settings2 className="h-3.5 w-3.5" />
            Tools
          </span>
          <Badge variant="secondary" className="text-[0.6rem]">
            {tools.length}
          </Badge>
        </button>

        {toolsOpen && (
          <div className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
            {tools.length === 0 ? (
              <div className="px-2 py-6 text-center text-xs text-muted-foreground">
                No tool calls yet
              </div>
            ) : (
              tools.map((tool) => <ToolCall key={tool.id} tool={tool} />)
            )}
          </div>
        )}
      </Card>

      {modelOpen && canPickModel && sessionId && (
        <ModelPickerDialog
          gw={gw}
          onClose={onCloseModel}
          onSubmit={onModelSubmit}
          sessionId={sessionId}
        />
      )}
    </div>
  );
}
