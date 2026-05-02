import { Markdown } from "@/components/Markdown";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import {
  SlashPopover,
  type SlashPopoverHandle,
} from "@/components/SlashPopover";
import type { ToolEntry } from "@/components/ToolCall";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";
import { api, type AgentHubAgent } from "@/lib/api";
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
  ChevronUp,
  Clipboard,
  Command,
  FileCode2,
  FileText,
  Folder,
  GitBranch,
  Loader2,
  Mic,
  MicOff,
  PanelRight,
  Plug,
  RotateCcw,
  Send,
  Shield,
  ShieldAlert,
  Sparkles,
  Square,
  Wrench,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";

interface SessionInfo {
  config_warning?: string;
  credential_warning?: string;
  cwd?: string;
  model?: string;
  provider?: string;
}

interface BrowserSpeechRecognitionResult {
  transcript: string;
}

type BrowserSpeechRecognitionResultItem =
  ArrayLike<BrowserSpeechRecognitionResult> & { isFinal?: boolean };

interface BrowserSpeechRecognitionEvent {
  resultIndex: number;
  results: ArrayLike<BrowserSpeechRecognitionResultItem>;
}

interface BrowserSpeechRecognitionErrorEvent {
  error?: string;
}

interface BrowserSpeechRecognition {
  abort(): void;
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  start(): void;
  stop(): void;
}

interface BrowserSpeechRecognitionConstructor {
  new (): BrowserSpeechRecognition;
}

type SpeechWindow = Window & {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
};

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

interface SourceEntry {
  detail: string;
  id: string;
  kind: "artifact" | "model" | "session" | "tool";
  title: string;
}

interface QueuedInput {
  createdAt: number;
  id: string;
  status: "queued" | "error";
  text: string;
}

interface UsageInfo {
  calls?: number;
  cache_read?: number;
  cache_write?: number;
  context_max?: number;
  context_percent?: number;
  context_used?: number;
  input?: number;
  model?: string;
  output?: number;
  total?: number;
}

interface ComposerAgent {
  description?: string;
  enabled: boolean;
  id: string;
  name: string;
  role?: string;
  status?: string;
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

const DEFAULT_COMPOSER_AGENTS: ComposerAgent[] = [
  {
    description: "Main chat, routing, synthesis, and final response owner.",
    enabled: true,
    id: "executive-assistant",
    name: "Executive Assistant",
    role: "Primary operator",
    status: "ready",
  },
  {
    description: "Paperwork, scheduling, checklists, and transaction ops.",
    enabled: true,
    id: "admin",
    name: "Admin",
    role: "Operations support",
    status: "ready",
  },
  {
    description: "Lead follow-up, client touchpoints, and nurture messaging.",
    enabled: true,
    id: "outreach",
    name: "Outreach",
    role: "Relationship lane",
    status: "ready",
  },
  {
    description: "Campaigns, listing positioning, emails, and creative direction.",
    enabled: true,
    id: "marketing",
    name: "Marketing",
    role: "Campaign lane",
    status: "ready",
  },
];

const STATE_LABEL: Record<ConnectionState, string> = {
  closed: "closed",
  connecting: "connecting",
  error: "error",
  idle: "idle",
  open: "live",
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

function normalizeUsage(raw: unknown): UsageInfo | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const toNumber = (key: string) =>
    typeof item[key] === "number" && Number.isFinite(item[key])
      ? (item[key] as number)
      : undefined;

  return {
    calls: toNumber("calls"),
    cache_read: toNumber("cache_read"),
    cache_write: toNumber("cache_write"),
    context_max: toNumber("context_max"),
    context_percent: toNumber("context_percent"),
    context_used: toNumber("context_used"),
    input: toNumber("input"),
    model: typeof item.model === "string" ? item.model : undefined,
    output: toNumber("output"),
    total: toNumber("total"),
  };
}

function displayStatusText(text: string): string {
  const clean = text.trim();
  if (!clean) return "";

  const lower = clean.toLowerCase();
  if (lower.includes("pondering") || lower.includes("thinking")) {
    return "Thinking...";
  }
  if (lower.includes("formulating")) {
    return "Writing response...";
  }
  return clean;
}

function syntheticToolId(name: string): string {
  return `progress:${name || "tool"}`;
}

function composerAgentFromHub(agent: AgentHubAgent): ComposerAgent {
  return {
    description: agent.description,
    enabled: agent.enabled,
    id: agent.id,
    name: agent.name,
    role: agent.role,
    status: agent.status,
  };
}

function routePromptForAgent(text: string, agent: ComposerAgent): string {
  if (agent.id === "executive-assistant") return text;

  return [
    `[Elevate agent route: ${agent.name} (${agent.id})]`,
    "Use this specialist lane for the turn when useful, then return the answer in this chat.",
    `User request: ${text}`,
  ].join("\n");
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

function speechRecognitionConstructor() {
  if (typeof window === "undefined") return undefined;
  const speechWindow = window as SpeechWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
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

function buildSourceEntries({
  artifacts,
  info,
  sessionId,
  tools,
}: {
  artifacts: ArtifactEntry[];
  info: SessionInfo;
  sessionId: string | null;
  tools: ToolEntry[];
}): SourceEntry[] {
  const entries: SourceEntry[] = [];

  entries.push({
    detail: [info.provider, info.model].filter(Boolean).join(" / ") || "model pending",
    id: "model",
    kind: "model",
    title: "Model",
  });

  if (sessionId) {
    entries.push({
      detail: sessionId,
      id: "session",
      kind: "session",
      title: "Session",
    });
  }

  for (const tool of tools.slice(-8).reverse()) {
    entries.push({
      detail: tool.summary || tool.context || tool.preview || tool.status,
      id: `tool:${tool.id}`,
      kind: "tool",
      title: tool.name,
    });
  }

  for (const artifact of artifacts.slice(-8).reverse()) {
    entries.push({
      detail: artifact.detail || artifact.path || artifact.source || artifact.kind,
      id: `artifact:${artifact.id}`,
      kind: "artifact",
      title: artifact.title,
    });
  }

  return entries.slice(0, 14);
}

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const resumeId = searchParams.get("resume");
  const newChatId = searchParams.get("new");
  const [version, setVersion] = useState(0);
  const gw = useMemo(() => new GatewayClient(), [version]);

  const [state, setState] = useState<ConnectionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const activeSessionRef = useRef<string | null>(null);
  const currentAssistantRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const commandPopoverRef = useRef<SlashPopoverHandle | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const voiceBaseInputRef = useRef("");

  const [info, setInfo] = useState<SessionInfo>({});
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactEntry[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [input, setInput] = useState("");
  const [caretIndex, setCaretIndex] = useState(0);
  const [composerScrollTop, setComposerScrollTop] = useState(0);
  const [queuedInputs, setQueuedInputs] = useState<QueuedInput[]>([]);
  const [busy, setBusy] = useState(false);
  const [voiceListening, setVoiceListening] = useState(false);
  const [statusText, setStatusText] = useState("Connecting...");
  const [banner, setBanner] = useState<string | null>(() =>
    typeof window !== "undefined" && !window.__ELEVATE_SESSION_TOKEN__
      ? "Session token unavailable. Open this page through `elevate dashboard`, not directly."
      : null,
  );
  const [pendingPrompt, setPendingPrompt] = useState<PendingPrompt | null>(null);
  const [promptValue, setPromptValue] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const [composerAgents, setComposerAgents] = useState<ComposerAgent[]>(
    DEFAULT_COMPOSER_AGENTS,
  );
  const [selectedAgentId, setSelectedAgentId] = useState("executive-assistant");
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  const [mobilePanelOpen, setMobilePanelOpen] = useState(false);
  const [resumeFallback, setResumeFallback] = useState(false);
  const [portalRoot] = useState<HTMLElement | null>(() =>
    typeof document !== "undefined" ? document.body : null,
  );
  const [narrow, setNarrow] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(max-width: 1279px)").matches
      : false,
  );
  const { setEnd } = usePageHeader();

  const activeComposerAgents = useMemo(() => {
    const enabled = composerAgents.filter((agent) => agent.enabled);
    return enabled.length ? enabled : DEFAULT_COMPOSER_AGENTS;
  }, [composerAgents]);

  const selectedAgent = useMemo(
    () =>
      activeComposerAgents.find((agent) => agent.id === selectedAgentId) ??
      activeComposerAgents[0] ??
      DEFAULT_COMPOSER_AGENTS[0],
    [activeComposerAgents, selectedAgentId],
  );

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
    const mql = window.matchMedia("(max-width: 1279px)");
    const sync = () => setNarrow(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    let cancelled = false;

    api
      .getAgentHub()
      .then((snapshot) => {
        if (cancelled) return;
        const agents = snapshot.agents
          .map(composerAgentFromHub)
          .filter((agent) => agent.enabled);
        if (agents.length) {
          setComposerAgents(agents);
        }
      })
      .catch(() => {
        // Agent Hub metadata should never block the chat composer.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
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
    setUsage(null);
    setArtifacts([]);
    setTools([]);
    setQueuedInputs([]);
    setPendingPrompt(null);
    setPromptValue("");
    setBusy(false);
    setBanner(null);
    setResumeFallback(false);
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
        const name = String(payload.name ?? "tool");
        const context = typeof payload.context === "string" ? payload.context : "";

        setTools((prev) =>
          prev.some((tool) => tool.tool_id === toolId)
            ? prev.map((tool) =>
                tool.tool_id === toolId
                  ? {
                      ...tool,
                      context,
                      name,
                      status: "running" as const,
                    }
                  : tool,
              )
            : prev.some(
                  (tool) =>
                    tool.status === "running" &&
                    tool.name === name &&
                    tool.tool_id === syntheticToolId(name),
                )
              ? prev.map((tool) =>
                  tool.status === "running" &&
                  tool.name === name &&
                  tool.tool_id === syntheticToolId(name)
                    ? {
                        ...tool,
                        context,
                        name,
                        tool_id: toolId,
                      }
                    : tool,
                )
              : [
                  ...prev,
                  {
                    context,
                    id: id(`tool-${toolId}`),
                    kind: "tool" as const,
                    name,
                    startedAt: Date.now(),
                    status: "running" as const,
                    tool_id: toolId,
                  },
                ].slice(-TOOL_LIMIT),
        );
        setStatusText(`Running ${name}`);
        return;
      }

      if (ev.type === "tool.progress") {
        const name = String(payload.name ?? "");
        const preview = String(payload.preview ?? "");
        if (!name || !preview) return;

        setTools((prev) => {
          const hasRunning = prev.some(
            (tool) => tool.status === "running" && tool.name === name,
          );
          if (hasRunning) {
            return prev.map((tool) =>
              tool.status === "running" && tool.name === name
                ? { ...tool, preview }
                : tool,
            );
          }

          return [
            ...prev,
            {
              id: id(`tool-${name}`),
              kind: "tool" as const,
              name,
              preview,
              startedAt: Date.now(),
              status: "running" as const,
              tool_id: syntheticToolId(name),
            },
          ].slice(-TOOL_LIMIT);
        });
        setStatusText(`Running ${name}`);
        return;
      }

      if (ev.type === "tool.complete") {
        const toolId = String(payload.tool_id ?? "");
        const name = String(payload.name ?? "");
        if (!toolId && !name) return;

        setTools((prev) => {
          const hasToolId = toolId
            ? prev.some((tool) => tool.tool_id === toolId)
            : false;
          const fallbackIndex = !hasToolId && name
            ? prev.reduce(
                (match, tool, index) =>
                  tool.status === "running" && tool.name === name
                    ? index
                    : match,
                -1,
              )
            : -1;

          return prev.map((tool, index) =>
            (toolId && tool.tool_id === toolId) || index === fallbackIndex
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
          );
        });
        if (name) {
          setStatusText(payload.error ? `${name} failed` : `${name} complete`);
        }
        addArtifacts(artifactsFromToolComplete(payload));
      }
    };

    const trackSubagentArtifacts = (ev: GatewayEvent) => {
      if (!accepts(ev)) return;
      addArtifacts(artifactsFromSubagentEvent(compactToolPayload(ev.payload)));
    };

    const updateUsageFromPayload = (ev: GatewayEvent) => {
      const payload = compactToolPayload(ev.payload);
      const nextUsage = normalizeUsage(payload.usage);
      if (nextUsage) setUsage(nextUsage);
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
        setStatusText("Working...");
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
        updateUsageFromPayload(ev);
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
        setTools((prev) =>
          prev.map((tool) =>
            tool.status === "running" && tool.tool_id.startsWith("progress:")
              ? {
                  ...tool,
                  completedAt: Date.now(),
                  status: "done" as const,
                  summary: tool.preview ?? tool.summary,
                }
              : tool,
          ),
        );
        currentAssistantRef.current = null;
        setBusy(false);
        setQueuedInputs([]);
        setStatusText(status === "interrupted" ? "Interrupted" : "Ready");
      }),
    );
    unsubs.push(
      gw.on("status.update", (ev) => {
        if (!accepts(ev)) return;
        const text = eventString(ev, "text");
        if (text) setStatusText(displayStatusText(text));
      }),
    );
    unsubs.push(
      gw.on("thinking.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) setStatusText(displayStatusText(text));
      }),
    );
    unsubs.push(
      gw.on("reasoning.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) setStatusText(displayStatusText(text));
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
        if (!name) return;
        setStatusText(`Preparing ${name}`);
        setTools((prev) =>
          prev.some(
            (tool) =>
              tool.status === "running" &&
              tool.name === name &&
              tool.tool_id === syntheticToolId(name),
          )
            ? prev
            : [
                ...prev,
                {
                  id: id(`tool-${name}`),
                  kind: "tool" as const,
                  name,
                  preview: `Preparing ${name}`,
                  startedAt: Date.now(),
                  status: "running" as const,
                  tool_id: syntheticToolId(name),
                },
              ].slice(-TOOL_LIMIT),
        );
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
        setQueuedInputs([]);
        setStatusText("Error");
      }),
    );

    gw.connect()
      .then(async () => {
        if (cancelled) return;
        let resumeWarning: string | null = null;
        let created: SessionCreateResponse | SessionResumeResponse;

        if (resumeId) {
          try {
            created = await gw.request<SessionResumeResponse>("session.resume", {
              cols: 100,
              session_id: resumeId,
            }, 30_000);
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            resumeWarning = `Could not resume that session, so I started a fresh chat you can use now. ${message}`;
            setResumeFallback(true);
            created = await gw.request<SessionCreateResponse>("session.create", {
              cols: 100,
            });
          }
        } else {
          created = await gw.request<SessionCreateResponse>("session.create", {
            cols: 100,
          });
        }

        if (cancelled) return;
        activeSessionRef.current = created.session_id;
        setSessionId(created.session_id);
        setInfo(created.info ?? {});
        if (resumeWarning) {
          setBanner(resumeWarning);
        } else if (created.info?.credential_warning || created.info?.config_warning) {
          setBanner(
            created.info.credential_warning ?? created.info.config_warning ?? null,
          );
        }

        if (resumeWarning) {
          setMessages([
            {
              content: resumeWarning,
              createdAt: Date.now(),
              id: id("resume-fallback"),
              role: "system",
              status: "error",
            },
          ]);
        } else if ("messages" in created) {
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
    newChatId,
    resumeId,
    updateAssistant,
  ]);

  useEffect(() => {
    if (!sessionId || state !== "open") return;
    let cancelled = false;

    const refresh = async () => {
      try {
        const next = await gw.request<UsageInfo>(
          "session.usage",
          { session_id: sessionId },
          8_000,
        );
        if (!cancelled) setUsage(normalizeUsage(next));
      } catch {
        // Context usage is helpful, not critical to chat.
      }
    };

    void refresh();
    const timer = window.setInterval(refresh, busy ? 3_000 : 12_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [busy, gw, sessionId, state]);

  const selectComposerAgent = useCallback(
    (agent: ComposerAgent) => {
      setSelectedAgentId(agent.id);
      setAgentMenuOpen(false);
      setStatusText(
        agent.id === "executive-assistant"
          ? "Executive Assistant selected"
          : `Routing through ${agent.name}`,
      );
      window.requestAnimationFrame(() => inputRef.current?.focus());
    },
    [],
  );

  const applyComposerCompletion = useCallback(
    (nextInput: string, nextCaret: number) => {
      setInput(nextInput);
      setCaretIndex(nextCaret);
      setAgentMenuOpen(false);
      window.requestAnimationFrame(() => {
        const target = inputRef.current;
        if (!target) return;
        target.focus();
        target.setSelectionRange(nextCaret, nextCaret);
      });
    },
    [],
  );

  const submitPrompt = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !sessionId) return;

      appendMessage("user", trimmed);
      setInput("");
      setComposerScrollTop(0);
      setBanner(null);
      setAgentMenuOpen(false);

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

      const routedText = routePromptForAgent(trimmed, selectedAgent);

      if (busy) {
        const queued: QueuedInput = {
          createdAt: Date.now(),
          id: id("queued"),
          status: "queued",
          text: trimmed,
        };
        setQueuedInputs((prev) => [...prev, queued].slice(-5));
        setStatusText("Queued for current turn");
        try {
          await gw.request("session.steer", {
            session_id: sessionId,
            text: routedText,
          });
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          setQueuedInputs((prev) =>
            prev.map((item) =>
              item.id === queued.id ? { ...item, status: "error" } : item,
            ),
          );
          appendMessage("system", message, { status: "error" });
        }
        return;
      }

      setBusy(true);
      setStatusText("Sending...");
      try {
        await gw.request("prompt.submit", {
          session_id: sessionId,
          text: routedText,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        appendMessage("system", message, { status: "error" });
        setBusy(false);
        setStatusText("Error");
      }
    },
    [appendMessage, busy, gw, selectedAgent, sessionId],
  );

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitPrompt(input);
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (commandPopoverRef.current?.handleKey(event)) {
      return;
    }

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
      setQueuedInputs([]);
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

  const voiceSupported = Boolean(speechRecognitionConstructor());
  const toggleVoiceInput = useCallback(() => {
    const SpeechRecognition = speechRecognitionConstructor();
    if (!SpeechRecognition) {
      setBanner("Voice input is not available in this browser.");
      return;
    }

    if (voiceListening) {
      recognitionRef.current?.stop();
      setVoiceListening(false);
      setStatusText("Voice input stopped");
      inputRef.current?.focus();
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    voiceBaseInputRef.current = input.trimEnd();
    recognition.onresult = (event) => {
      const finalSegments: string[] = [];
      const interimSegments: string[] = [];
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result?.[0]?.transcript?.trim() ?? "";
        if (!transcript) continue;
        if (result.isFinal) finalSegments.push(transcript);
        else interimSegments.push(transcript);
      }

      const dictated = [...finalSegments, ...interimSegments].join(" ").trim();
      if (dictated) {
        const nextInput = [voiceBaseInputRef.current, dictated]
          .filter(Boolean)
          .join(" ");
        setInput(nextInput);
        setCaretIndex(nextInput.length);
        window.requestAnimationFrame(() => {
          const target = inputRef.current;
          if (!target) return;
          target.setSelectionRange(nextInput.length, nextInput.length);
        });
      }

      if (finalSegments.length) {
        setStatusText("Voice captured");
      } else if (interimSegments.length) {
        setStatusText(`Listening: ${interimSegments.join(" ")}`);
      }
    };
    recognition.onerror = (event) => {
      setBanner(`Voice input error: ${event.error ?? "unavailable"}`);
      setVoiceListening(false);
      recognitionRef.current = null;
    };
    recognition.onend = () => {
      setVoiceListening(false);
      recognitionRef.current = null;
      inputRef.current?.focus();
    };

    recognitionRef.current = recognition;
    setBanner(null);
    setVoiceListening(true);
    setStatusText("Listening...");
    recognition.start();
  }, [input, voiceListening]);

  const canSend = !!input.trim() && state === "open" && !!sessionId;
  const canPickModel = state === "open" && !!sessionId;
  const activity = (
    <ActivityPanel
      artifacts={artifacts}
      banner={banner}
      busy={busy}
      info={info}
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
            "fixed bottom-4 right-4 top-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col",
            "normal-case",
            mobilePanelOpen ? "translate-x-0" : "translate-x-[calc(100%+1rem)]",
            "transition-transform duration-200 ease-out",
          )}
        >
          <Button
            aria-label="Close activity"
            className="absolute right-3 top-3 z-10 h-8 w-8 rounded-full bg-[var(--chat-surface-strong)] p-0 text-[var(--chat-muted-strong)] shadow-sm hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
            onClick={() => setMobilePanelOpen(false)}
            size="sm"
            variant="ghost"
          >
            <X className="h-4 w-4" />
          </Button>
          {activity}
        </aside>
      </>,
      portalRoot,
    );

  return (
    <div className="elevate-chat-shell relative -m-4 flex min-h-[calc(100vh-4.5rem)] flex-col overflow-hidden bg-[var(--chat-bg)] text-[var(--chat-text)] normal-case sm:-m-6">
      <div className="relative flex min-h-0 flex-1">
        <section className="flex min-h-0 flex-1 flex-col xl:pr-[23rem]">
          <header className="mx-auto flex w-full max-w-[52rem] flex-wrap items-center justify-between gap-3 px-4 pb-4 pt-5 sm:px-6">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-sm font-semibold text-[var(--chat-text)]">
                  {resumeId && !resumeFallback ? "Resumed session" : "Elevate Agent"}
                </h1>
                <span className="h-1 w-1 rounded-full bg-[var(--chat-border-strong)]" />
                <span className="truncate text-xs text-[var(--chat-muted)]">
                  {modelLabel(info)}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-flex h-7 items-center rounded-full px-2.5 text-xs",
                  state === "open"
                    ? "bg-[color-mix(in_srgb,var(--chat-success)_18%,var(--chat-bg))] text-[var(--chat-success)]"
                    : "bg-[var(--chat-surface-strong)] text-[var(--chat-muted-strong)]",
                )}
              >
                {STATE_LABEL[state]}
              </span>
              {busy && (
                <button
                  className="inline-flex h-7 items-center gap-1.5 rounded-full border border-[var(--chat-border-strong)] px-2.5 text-xs text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)]"
                  onClick={() => void interrupt()}
                  type="button"
                >
                  <Square className="h-3 w-3" />
                  Stop
                </button>
              )}
              <button
                className="inline-flex h-7 items-center gap-1.5 rounded-full border border-[var(--chat-border-strong)] px-2.5 text-xs text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)]"
                onClick={reconnect}
                type="button"
              >
                <RotateCcw className="h-3 w-3" />
                Restart
              </button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-1 sm:px-6">
            {messages.length === 0 ? (
              <EmptyState state={state} />
            ) : (
              <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-5 pb-6">
                {messages.map((message, index) => (
                  <MessageRow
                    key={message.id}
                    activityText={
                      message.role === "assistant" &&
                      message.status === "streaming" &&
                      index === messages.length - 1
                        ? statusText
                        : undefined
                    }
                    message={message}
                  />
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
            className="bg-[linear-gradient(180deg,transparent,var(--chat-bg)_18%)] px-4 pb-5 pt-3 sm:px-6"
            onSubmit={onSubmit}
          >
            <div className="mx-auto max-w-[48rem]">
              <QueuedInputStrip queuedInputs={queuedInputs} />

              <div className="relative rounded-[1.45rem] bg-[var(--chat-surface)] p-2.5 shadow-[0_24px_80px_rgba(0,0,0,0.20),inset_0_0_0_1px_var(--chat-border-strong)] focus-within:shadow-[0_24px_80px_rgba(0,0,0,0.20),inset_0_0_0_1px_var(--chat-accent)]">
                <SlashPopover
                  ref={commandPopoverRef}
                  agents={activeComposerAgents}
                  caretIndex={caretIndex}
                  gw={gw}
                  input={input}
                  onApply={applyComposerCompletion}
                />

                <div className="relative min-h-14">
                  <ComposerRichInputLayer
                    input={input}
                    scrollTop={composerScrollTop}
                  />
                  <textarea
                    ref={inputRef}
                    aria-label="Message Elevate Agent"
                    className={cn(
                      "relative z-10 max-h-40 min-h-14 w-full resize-none bg-transparent px-2 pb-1 pt-1 text-sm leading-6 outline-none placeholder:text-[var(--chat-muted)]",
                      "caret-[var(--chat-text)] selection:bg-[var(--chat-accent-soft)]",
                      input
                        ? "text-transparent"
                        : "text-[var(--chat-text)]",
                    )}
                    disabled={state !== "open" || !sessionId}
                    onChange={(event) => {
                      setInput(event.target.value);
                      setCaretIndex(event.currentTarget.selectionStart ?? event.target.value.length);
                      setAgentMenuOpen(false);
                    }}
                    onClick={(event) =>
                      setCaretIndex(event.currentTarget.selectionStart ?? input.length)
                    }
                    onKeyDown={onComposerKeyDown}
                    onKeyUp={(event) =>
                      setCaretIndex(event.currentTarget.selectionStart ?? input.length)
                    }
                    onScroll={(event) =>
                      setComposerScrollTop(event.currentTarget.scrollTop)
                    }
                    onSelect={(event) =>
                      setCaretIndex(event.currentTarget.selectionStart ?? input.length)
                    }
                    placeholder={
                      state === "open" && sessionId
                        ? "Message Elevate Agent..."
                        : "Connecting..."
                    }
                    rows={2}
                    spellCheck
                    value={input}
                  />
                </div>

                <ComposerActionBar
                  agentMenuOpen={agentMenuOpen}
                  agents={activeComposerAgents}
                  busy={busy}
                  canPickModel={canPickModel}
                  canSend={canSend}
                  info={info}
                  onOpenModel={() => setModelOpen(true)}
                  onSelectAgent={selectComposerAgent}
                  onToggleAgentMenu={() => {
                    setAgentMenuOpen((open) => !open);
                  }}
                  onToggleVoice={toggleVoiceInput}
                  selectedAgent={selectedAgent}
                  state={state}
                  statusText={statusText}
                  usage={usage}
                  voiceListening={voiceListening}
                  voiceSupported={voiceSupported}
                />
              </div>
            </div>
          </form>
        </section>

        <aside className="pointer-events-none absolute bottom-5 right-5 top-5 hidden w-[21.5rem] xl:block">
          <div className="pointer-events-auto h-full">{activity}</div>
        </aside>
      </div>
      {mobileActivityPortal}
      {modelOpen && canPickModel && sessionId && (
        <ModelPickerDialog
          gw={gw}
          onClose={() => setModelOpen(false)}
          onSubmit={(slashCommand) => {
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
          sessionId={sessionId}
        />
      )}
    </div>
  );
}

function EmptyState({ state }: { state: ConnectionState }) {
  return (
    <div className="mx-auto flex min-h-[34rem] max-w-xl flex-col items-center justify-center text-center">
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-full bg-[var(--chat-surface)] text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border-strong)]">
        {state === "connecting" ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Bot className="h-5 w-5" />
        )}
      </div>
      <h2 className="text-xl font-semibold text-[var(--chat-text)]">
        Elevate Agent
      </h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-[var(--chat-muted)]">
        Executive Assistant is ready.
      </p>
    </div>
  );
}

function QueuedInputStrip({ queuedInputs }: { queuedInputs: QueuedInput[] }) {
  if (!queuedInputs.length) return null;

  return (
    <div className="mb-2 rounded-2xl bg-[var(--chat-surface-soft)] px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[0.68rem] text-[var(--chat-muted)]">
        <span className="font-medium text-[var(--chat-muted-strong)]">
          Queued follow-ups
        </span>
        <span>{queuedInputs.length}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {queuedInputs.map((item) => (
          <div
            key={item.id}
            className={cn(
              "flex items-start gap-2 rounded-xl px-2.5 py-1.5 text-xs",
              item.status === "error"
                ? "bg-[color-mix(in_srgb,var(--chat-danger)_14%,var(--chat-bg))] text-[var(--chat-danger)]"
                : "bg-[var(--chat-surface-strong)] text-[var(--chat-muted-strong)]",
            )}
          >
            <span
              className={cn(
                "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                item.status === "error"
                  ? "bg-[var(--chat-danger)]"
                  : "bg-[var(--chat-accent)]",
              )}
            />
            <span className="min-w-0 flex-1 truncate">{item.text}</span>
            <span className="shrink-0 text-[0.65rem] text-[var(--chat-muted)]">
              {item.status === "error" ? "error" : nowLabel(item.createdAt)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

type ComposerSegment =
  | { text: string; type: "text" }
  | { icon: LucideIcon; label: string; text: string; type: "token" };

function composerTokenIcon(token: string) {
  const normalized = token.toLowerCase();
  if (token.startsWith("/")) return Command;
  if (normalized.startsWith("@agent:")) return Bot;
  if (normalized.startsWith("@skill:")) return Sparkles;
  if (normalized.startsWith("@toolset:")) return Wrench;
  if (normalized.startsWith("@plugin:")) return Plug;
  if (normalized.startsWith("@folder:")) return Folder;
  if (normalized.startsWith("@file:")) return FileText;
  if (normalized.startsWith("@git:") || normalized === "@diff" || normalized === "@staged") {
    return GitBranch;
  }
  return FileText;
}

function composerTokenLabel(token: string): string {
  if (token.startsWith("/")) return token;
  const raw = token.replace(/^@[a-z]+:/i, "").replace(/^@/, "");
  const parts = raw.split(/[/-]/).filter(Boolean);
  return parts.slice(-2).join(" / ") || raw;
}

function parseComposerSegments(input: string): ComposerSegment[] {
  const tokenPattern =
    /(^|\s)(\/[a-z][\w-]*|@(agent|skill|toolset|plugin|file|folder|url|git):[^\s]+|@(diff|staged)\b)/gi;
  const segments: ComposerSegment[] = [];
  let cursor = 0;

  for (const match of input.matchAll(tokenPattern)) {
    const prefix = match[1] ?? "";
    const token = match[2];
    if (!token) continue;
    const index = (match.index ?? 0) + prefix.length;
    if (index > cursor) {
      segments.push({ text: input.slice(cursor, index), type: "text" });
    }
    segments.push({
      icon: composerTokenIcon(token),
      label: composerTokenLabel(token),
      text: token,
      type: "token",
    });
    cursor = index + token.length;
  }

  if (cursor < input.length) {
    segments.push({ text: input.slice(cursor), type: "text" });
  }

  return segments.length ? segments : [{ text: input, type: "text" }];
}

function ComposerRichInputLayer({
  input,
  scrollTop,
}: {
  input: string;
  scrollTop: number;
}) {
  const segments = useMemo(() => parseComposerSegments(input), [input]);

  if (!input) return null;

  return (
    <div className="pointer-events-none absolute inset-0 z-0 max-h-40 overflow-hidden px-2 pb-1 pt-1 text-sm leading-6 text-[var(--chat-text)]">
      <div
        className="whitespace-pre-wrap break-words"
        style={{ transform: `translateY(-${scrollTop}px)` }}
      >
        {segments.map((segment, index) => {
          if (segment.type === "text") {
            return <span key={`${index}-text`}>{segment.text}</span>;
          }

          const Icon = segment.icon;
          return (
            <span
              aria-label={segment.text}
              className="relative inline-block align-baseline text-transparent"
              key={`${index}-${segment.text}`}
            >
              {segment.text}
              <span className="absolute left-0 top-[0.12rem] inline-flex max-w-full items-center gap-1 rounded-full bg-[var(--chat-surface-soft)] px-1.5 py-0.5 text-[0.82rem] font-medium leading-5 text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
                <Icon className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{segment.label}</span>
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function ContextRing({ usage }: { usage: UsageInfo | null }) {
  const used = Math.max(0, Math.min(100, usage?.context_percent ?? 0));
  const left = usage?.context_percent === undefined ? null : Math.max(0, 100 - used);
  const circumference = 2 * Math.PI * 9;
  const stroke = left === null ? 0 : (left / 100) * circumference;
  const label = left === null ? "--" : `${Math.round(left)}%`;
  const detail =
    usage?.context_used && usage?.context_max
      ? `${Math.round(usage.context_used).toLocaleString()} / ${Math.round(usage.context_max).toLocaleString()} tokens used`
      : "Context usage pending";

  return (
    <span
      className="inline-flex h-7 items-center gap-1.5 rounded-full bg-[var(--chat-surface-soft)] px-2.5 text-[var(--chat-muted-strong)]"
      title={`Context left: ${label}. ${detail}`}
    >
      <svg
        aria-hidden="true"
        className="h-5 w-5 -rotate-90"
        viewBox="0 0 24 24"
      >
        <circle
          cx="12"
          cy="12"
          fill="none"
          r="9"
          stroke="var(--chat-border-strong)"
          strokeWidth="2.5"
        />
        <circle
          cx="12"
          cy="12"
          fill="none"
          r="9"
          stroke="var(--chat-accent)"
          strokeDasharray={`${stroke} ${circumference}`}
          strokeLinecap="round"
          strokeWidth="2.5"
        />
      </svg>
      <span className="text-[0.68rem]">{label}</span>
    </span>
  );
}

function ComposerActionBar({
  agentMenuOpen,
  agents,
  busy,
  canPickModel,
  canSend,
  info,
  onOpenModel,
  onSelectAgent,
  onToggleAgentMenu,
  onToggleVoice,
  selectedAgent,
  state,
  statusText,
  usage,
  voiceListening,
  voiceSupported,
}: {
  agentMenuOpen: boolean;
  agents: ComposerAgent[];
  busy: boolean;
  canPickModel: boolean;
  canSend: boolean;
  info: SessionInfo;
  onOpenModel(): void;
  onSelectAgent(agent: ComposerAgent): void;
  onToggleAgentMenu(): void;
  onToggleVoice(): void;
  selectedAgent: ComposerAgent;
  state: ConnectionState;
  statusText: string;
  usage: UsageInfo | null;
  voiceListening: boolean;
  voiceSupported: boolean;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[0.68rem] text-[var(--chat-muted)]">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <div className="relative">
          <button
            type="button"
            onClick={onToggleAgentMenu}
            className={cn(
              "inline-flex h-7 max-w-[12rem] items-center gap-1.5 rounded-full px-2.5",
              "bg-[var(--chat-surface-soft)] text-[var(--chat-muted-strong)] transition-colors",
              "hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]",
              agentMenuOpen &&
                "bg-[var(--chat-accent-soft)] text-[var(--chat-text)] shadow-[inset_0_0_0_1px_var(--chat-accent)]",
            )}
            title="Choose agent lane"
          >
            <Users className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{selectedAgent.name}</span>
            <ChevronUp className="h-3 w-3 shrink-0 opacity-70" />
          </button>

          {agentMenuOpen && (
            <div className="absolute bottom-[calc(100%+0.5rem)] left-0 z-30 w-[18rem] overflow-hidden rounded-2xl bg-[var(--chat-surface)] p-1.5 text-left shadow-[0_18px_54px_rgba(0,0,0,0.22),inset_0_0_0_1px_var(--chat-border-strong)]">
              {agents.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => onSelectAgent(agent)}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-xl px-2.5 py-2 text-left transition-colors",
                    selectedAgent.id === agent.id
                      ? "bg-[var(--chat-accent-soft)] text-[var(--chat-text)]"
                      : "text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]",
                  )}
                >
                  <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-semibold">
                      {agent.name}
                    </span>
                    <span className="mt-0.5 line-clamp-2 text-[0.68rem] leading-4 text-[var(--chat-muted)]">
                      {agent.role || agent.description || agent.status || "Agent lane"}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <span
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full px-2.5",
            "bg-[var(--chat-surface-soft)] text-[var(--chat-muted-strong)]",
          )}
          title="Tool access"
        >
          <Shield className="h-3 w-3" />
          Full access
        </span>

        <button
          type="button"
          onClick={onOpenModel}
          disabled={!canPickModel}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full px-2.5",
            "bg-[var(--chat-surface-soft)] text-[var(--chat-muted-strong)] transition-colors",
            "hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
          title="Change model"
        >
          <Bot className="h-3 w-3" />
          {modelLabel(info)}
          <ChevronDown className="h-3 w-3 opacity-70" />
        </button>

        <ContextRing usage={usage} />

        <button
          type="button"
          onClick={onToggleVoice}
          disabled={!voiceSupported}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full px-2.5",
            "bg-[var(--chat-surface-soft)] text-[var(--chat-muted-strong)] transition-colors",
            "hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]",
            "disabled:cursor-not-allowed disabled:opacity-45",
            voiceListening &&
              "bg-[var(--chat-accent-soft)] text-[var(--chat-text)] shadow-[inset_0_0_0_1px_var(--chat-accent)]",
          )}
          title={voiceSupported ? "Voice to text" : "Voice input unavailable"}
        >
          {voiceListening ? (
            <MicOff className="h-3 w-3" />
          ) : (
            <Mic className="h-3 w-3" />
          )}
          Voice
        </button>
      </div>

      <div className="ml-auto flex min-w-0 items-center gap-2">
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            state === "open" ? "bg-[var(--chat-success)]" : "bg-[var(--chat-muted)]",
          )}
        />
        <span className="max-w-[10rem] truncate">{statusText}</span>
        <button
          aria-label="Send message"
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
            canSend
              ? "bg-[var(--chat-text)] text-[var(--chat-bg)] hover:opacity-90"
              : "bg-[var(--chat-surface-strong)] text-[var(--chat-muted)]",
          )}
          disabled={!canSend}
          type="submit"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );
}

function MessageRow({
  activityText,
  message,
}: {
  activityText?: string;
  message: ChatMessage;
}) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  return (
    <article
      className={cn(
        "group flex w-full",
        isUser ? "flex-row-reverse text-right" : "text-left",
        isAssistant && "pt-3 first:pt-0",
      )}
    >
      <div
        className={cn(
          "min-w-0 flex-1",
          isUser && "flex justify-end",
          !isUser && "max-w-[74ch]",
        )}
      >
        <div
          className={cn(
            "max-w-full text-sm leading-7",
            isUser
              ? "inline-block rounded-2xl bg-[var(--chat-user)] px-3.5 py-2 text-[var(--chat-text)] shadow-sm"
              : message.role === "system"
                ? "rounded-lg border border-[color-mix(in_srgb,var(--chat-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_10%,var(--chat-bg))] px-3 py-2 text-[var(--chat-text)]"
                : "text-[var(--chat-text)]",
          )}
        >
          {message.role === "assistant" ? (
            message.content ? (
              <div className="chat-message-prose [&>div]:text-[var(--chat-text)] [&_a]:text-[var(--chat-accent)] [&_code]:bg-[var(--chat-surface-strong)] [&_code]:text-[var(--chat-text)] [&_pre]:border-[var(--chat-border-strong)] [&_pre]:bg-[var(--chat-surface-soft)]">
                <Markdown content={message.content} />
              </div>
            ) : (
              <div className="flex items-center gap-2 text-[var(--chat-muted)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {displayStatusText(activityText || "Working...")}
              </div>
            )
          ) : (
            <div className="whitespace-pre-wrap break-words">
              {message.content}
            </div>
          )}
          {message.warning && (
            <div className="mt-3 rounded-lg border border-[color-mix(in_srgb,var(--chat-warning)_40%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_12%,var(--chat-bg))] px-3 py-2 text-xs text-[var(--chat-text)]">
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
      <Card className="border-[color-mix(in_srgb,var(--chat-warning)_38%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_10%,var(--chat-bg))] p-3 text-[var(--chat-text)]">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--chat-warning)]" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Approval needed</div>
            <p className="mt-1 text-sm text-[var(--chat-muted-strong)]">
              {pendingPrompt.description}
            </p>
            {pendingPrompt.command && (
              <pre className="mt-2 max-h-28 overflow-auto rounded-lg bg-[var(--chat-surface-soft)] px-2 py-1.5 text-xs text-[var(--chat-muted-strong)]">
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
    <Card className="border-[var(--chat-border-strong)] bg-[var(--chat-surface)] p-3 text-[var(--chat-text)]">
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
            className="min-w-0 flex-1 rounded-lg border border-[var(--chat-border-strong)] bg-[var(--chat-surface-soft)] px-3 py-2 text-sm text-[var(--chat-text)] outline-none focus:ring-1 focus:ring-[var(--chat-accent)]"
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
        "rounded-xl bg-[var(--chat-surface-soft)] px-2.5 py-2.5 text-xs transition-colors hover:bg-[var(--chat-surface-strong)]",
        artifact.status === "error" &&
          "bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_40%,transparent)]",
      )}
    >
      <div className="flex items-start gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--chat-surface-soft)] text-[var(--chat-accent)]">
          <Icon className="h-3.5 w-3.5" />
        </div>

        <button
          className="min-w-0 flex-1 text-left"
          onClick={() => artifact.content && setOpen((value) => !value)}
          type="button"
        >
          <div className="truncate font-medium text-[var(--chat-text)]">
            {artifact.title}
          </div>
          <div className="mt-0.5 truncate text-[0.68rem] text-[var(--chat-muted)]">
            {artifact.detail || artifact.source || artifact.kind}
          </div>
        </button>

        <button
          aria-label="Copy artifact"
          className="rounded-md p-1 text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
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
        <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-[var(--chat-surface-soft)] p-2 text-[0.68rem] leading-4 text-[var(--chat-muted-strong)] whitespace-pre-wrap">
          {artifact.content}
        </pre>
      )}
    </div>
  );
}

function ProgressItem({ tool }: { tool: ToolEntry }) {
  const complete = tool.status === "done";
  const failed = tool.status === "error";

  return (
    <div className="flex gap-2 text-sm leading-5">
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
          failed
            ? "bg-[color-mix(in_srgb,var(--chat-danger)_18%,var(--chat-bg))] text-[var(--chat-danger)]"
            : complete
              ? "bg-[var(--chat-muted-strong)] text-[var(--chat-bg)]"
              : "bg-[var(--chat-surface-strong)] text-[var(--chat-muted-strong)]",
        )}
      >
        {tool.status === "running" ? (
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
        ) : (
          <CheckCircle2 className="h-2.5 w-2.5" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[var(--chat-muted-strong)]">{tool.name}</div>
        {(tool.summary || tool.context || tool.preview || tool.error) && (
          <div className="mt-0.5 line-clamp-2 text-xs text-[var(--chat-muted)]">
            {tool.error || tool.summary || tool.preview || tool.context}
          </div>
        )}
      </div>
    </div>
  );
}

function ActivityPanel({
  artifacts,
  banner,
  busy,
  info,
  onReconnect,
  sessionId,
  state,
  statusText,
  tools,
}: {
  artifacts: ArtifactEntry[];
  banner: string | null;
  busy: boolean;
  info: SessionInfo;
  onReconnect(): void;
  sessionId: string | null;
  state: ConnectionState;
  statusText: string;
  tools: ToolEntry[];
}) {
  const sources = useMemo(
    () => buildSourceEntries({ artifacts, info, sessionId, tools }),
    [artifacts, info, sessionId, tools],
  );
  const runningTools = tools.filter((tool) => tool.status === "running").length;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[1.65rem] bg-[var(--chat-surface)] normal-case shadow-[0_32px_90px_rgba(0,0,0,0.24),inset_0_0_0_1px_var(--chat-border)] ring-1 ring-white/[0.025] backdrop-blur-xl">
      <header className="shrink-0 px-3.5 pb-2.5 pt-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  state === "open"
                    ? "bg-[var(--chat-success)] shadow-[0_0_18px_color-mix(in_srgb,var(--chat-success)_55%,transparent)]"
                    : "bg-[var(--chat-muted)]",
                )}
              />
              <h2 className="truncate text-[0.9rem] font-semibold leading-5 text-[var(--chat-text)]">
                Activity Portal
              </h2>
            </div>
            <p className="mt-1 truncate text-[0.72rem] leading-4 text-[var(--chat-muted)]">
              Progress, artifacts, and sources
            </p>
          </div>

          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-[0.68rem] font-medium",
              state === "open"
                ? "bg-[color-mix(in_srgb,var(--chat-success)_16%,var(--chat-bg))] text-[var(--chat-success)]"
                : "bg-[var(--chat-surface-strong)] text-[var(--chat-muted)]",
            )}
          >
            {STATE_LABEL[state]}
          </span>
        </div>
      </header>

      {banner && (
        <section className="mx-3 mb-3 rounded-2xl bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-3 shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_38%,transparent)]">
          <div className="flex items-start gap-2 text-sm text-[var(--chat-danger)]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="break-words">{banner}</div>
              <button
                className="mt-2 rounded-full bg-[color-mix(in_srgb,var(--chat-danger)_12%,var(--chat-bg))] px-2.5 py-1 text-xs transition-colors hover:bg-[color-mix(in_srgb,var(--chat-danger)_15%,var(--chat-bg))]"
                onClick={onReconnect}
                type="button"
              >
                Reconnect
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-2.5 py-2.5">
        <section className="rounded-2xl bg-[var(--chat-surface-soft)] p-3">
          <div className="flex gap-2 text-sm leading-5">
            <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--chat-muted-strong)] text-[var(--chat-bg)]">
              {busy ? (
                <Loader2 className="h-2.5 w-2.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-2.5 w-2.5" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[var(--chat-muted-strong)]">
                {statusText}
              </div>
              <div className="mt-0.5 truncate text-xs text-[var(--chat-muted)]">
                {modelLabel(info)}
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-2">
          <PortalSectionHeader
            count={tools.length}
            label="Tasks"
            meta={busy ? `${runningTools || 1} running` : "idle"}
          />
          {tools.length === 0 ? (
            <PortalEmpty>
              {busy
                ? "Waiting for the first tool event..."
                : "Tool activity will appear here"}
            </PortalEmpty>
          ) : (
            tools
              .slice()
              .reverse()
              .map((tool) => <ProgressItem key={tool.id} tool={tool} />)
          )}
        </section>

        <section className="space-y-2">
          <PortalSectionHeader
            count={artifacts.length}
            label="Artifacts"
            meta="files and outputs"
          />
          {artifacts.length === 0 ? (
            <PortalEmpty>Files, diffs, and outputs will land here</PortalEmpty>
          ) : (
            artifacts
              .slice()
              .reverse()
              .map((artifact) => (
                <ArtifactCard key={artifact.id} artifact={artifact} />
              ))
          )}
        </section>

        <section className="space-y-2">
          <PortalSectionHeader
            count={sources.length}
            label="Sources"
            meta="model and session"
          />
          {sources.map((source) => (
            <SourceCard key={source.id} source={source} />
          ))}
        </section>
      </div>
    </div>
  );
}

function PortalSectionHeader({
  count,
  label,
  meta,
}: {
  count: number;
  label: string;
  meta: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 px-1">
      <div className="flex items-center gap-2">
        <span className="text-[0.72rem] font-semibold text-[var(--chat-muted-strong)]">
          {label}
        </span>
        <span className="rounded-full bg-[var(--chat-surface-soft)] px-1.5 py-0.5 text-[0.6rem] text-[var(--chat-muted)]">
          {count}
        </span>
      </div>
      <span className="truncate text-[0.65rem] text-[var(--chat-muted)]">
        {meta}
      </span>
    </div>
  );
}

function PortalEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl bg-[var(--chat-surface-soft)] px-3 py-5 text-center text-xs text-[var(--chat-muted)]">
      {children}
    </div>
  );
}

function SourceCard({ source }: { source: SourceEntry }) {
  const Icon =
    source.kind === "model"
      ? Bot
      : source.kind === "session"
        ? Shield
        : source.kind === "tool"
          ? CheckCircle2
          : FileText;

  return (
    <div className="rounded-2xl bg-[var(--chat-surface-soft)] px-3 py-2.5">
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-[var(--chat-surface-strong)] text-[var(--chat-muted-strong)]">
          <Icon className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-[var(--chat-text)]">
            {source.title}
          </div>
          <div className="mt-0.5 line-clamp-2 text-xs leading-4 text-[var(--chat-muted)]">
            {source.detail || source.kind}
          </div>
        </div>
      </div>
    </div>
  );
}
