import { Markdown } from "@/components/Markdown";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import {
  SlashPopover,
  type SlashPopoverHandle,
} from "@/components/SlashPopover";
import type { ToolEntry } from "@/components/ToolCall";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type AgentHubAgent,
  type SessionMessage as StoredSessionMessage,
} from "@/lib/api";
import {
  GatewayClient,
  type ConnectionState,
  type GatewayEvent,
} from "@/lib/gatewayClient";
import { executeSlash } from "@/lib/slashExec";
import { cn } from "@/lib/utils";
import { usePageHeader } from "@/contexts/usePageHeader";
import {
  AlertCircle,
  Bot,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clipboard,
  Command,
  Dot,
  ExternalLink,
  FileCode2,
  FilePen,
  FileText,
  Folder,
  GitBranch,
  Film,
  Image as ImageIcon,
  Loader2,
  PanelLeftOpen,
  Paperclip,
  Pin,
  Plug,
  Search,
  Send,
  ShieldAlert,
  Sparkle,
  Sparkles,
  SquareTerminal,
  Wrench,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  CSSProperties,
  FormEvent,
  KeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
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
  agent_ready?: boolean;
  info?: SessionInfo;
  persisted_session_id?: string;
  resumed?: string;
  session_id: string;
}

interface ResumeRunningTool {
  tool_id: string;
  name: string;
  context?: string;
  started_at?: number;
}

interface SessionResumeResponse extends SessionCreateResponse {
  messages?: GatewayTranscriptMessage[];
  running?: boolean;
  replay_events?: GatewayEvent[];
  replay_seq?: number;
  /**
   * Snapshot of tools still executing on the gateway at resume time.
   * The event ring can rotate a long turn's tool.start frames out, so
   * this guarantees the running tool cards reattach regardless.
   */
  running_tools?: ResumeRunningTool[];
}

type ChatRole = "assistant" | "system" | "tool" | "user";

interface ChatMessageAttachment {
  name: string;
  size: number;
  mediaType: string;
  /** Downscaled JPEG data URL for inline image previews. */
  previewUrl?: string;
}

interface ChatMessage {
  attachments?: ChatMessageAttachment[];
  content: string;
  createdAt: number;
  id: string;
  role: ChatRole;
  status?: "streaming" | "complete" | "error" | "interrupted";
  title?: string;
  warning?: string;
  // Snapshotted at message.complete so the activity digest (tool
  // breakdown + memory rows) survives a session resume. Live turns
  // render from the `tools`/`activityTrace` state instead; these are
  // the fallback for turns rehydrated from cache/server.
  tools?: ToolEntry[];
  traces?: ActivityTrace[];
  // Output tokens for this turn, frozen at message.complete. Prefers the
  // real per-turn count from gateway usage; falls back to the live
  // estimate when usage deltas aren't available.
  tokenCount?: number;
}

type ArtifactKind = "diff" | "file" | "output";

interface ArtifactEntry {
  content?: string;
  createdAt: number;
  detail?: string;
  id: string;
  kind: ArtifactKind;
  key: string;
  messageId?: string;
  path?: string;
  source?: string;
  status?: "error" | "ok";
  title: string;
}

interface QueuedInput {
  createdAt: number;
  id: string;
  routedText: string;
  status: "queued" | "error";
  text: string;
}

interface ChatAttachment {
  id: string;
  name: string;
  size: number;
  mediaType: string;
  /** Absolute path on the gateway host once the upload lands. */
  path?: string;
  status: "uploading" | "ready" | "error";
  error?: string;
  /** Downscaled JPEG data URL for inline image previews. */
  previewUrl?: string;
}

const THUMBNAIL_MAX_PX = 360;

/**
 * Build a small JPEG data-URL thumbnail from an image File so the chat can
 * render an actual preview instead of a generic file chip. Returns null for
 * non-images or if the browser can't decode the file.
 */
function makeImageThumbnail(file: File): Promise<string | null> {
  if (!(file.type || "").toLowerCase().startsWith("image/")) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      try {
        const scale = Math.min(
          1,
          THUMBNAIL_MAX_PX / Math.max(img.width, img.height),
        );
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          resolve(null);
          return;
        }
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", 0.8));
      } catch {
        resolve(null);
      } finally {
        URL.revokeObjectURL(url);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    img.src = url;
  });
}

const ATTACHMENT_MAX_BYTES = 500 * 1024 * 1024;

function formatAttachmentSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentIconFor(mediaType: string, name: string): LucideIcon {
  const lower = (mediaType || "").toLowerCase();
  const ext = name.toLowerCase().split(".").pop() || "";
  if (lower.startsWith("image/")) return ImageIcon;
  if (lower.startsWith("video/")) return Film;
  if (lower.includes("pdf") || ext === "pdf") return FileText;
  if (ext === "csv" || ext === "tsv" || ext === "xlsx" || ext === "xls") {
    return FileText;
  }
  if (["js", "jsx", "ts", "tsx", "py", "rb", "go", "rs", "java", "c", "cpp", "sh", "json", "yaml", "yml", "toml"].includes(ext)) {
    return FileCode2;
  }
  return FileText;
}

interface ActivityTrace {
  createdAt: number;
  id: string;
  kind: "reasoning" | "status" | "thinking";
  text: string;
  messageId?: string;
}

interface SubagentEntry {
  completedAt?: number;
  goal: string;
  id: string;
  model?: string;
  preview?: string;
  startedAt: number;
  status: "running" | "done" | "error";
  subagent_id: string;
  toolCount?: number;
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

function useCopyToClipboard() {
  const [copied, setCopied] = useState(false);
  const copy = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }).catch(() => {});
  }, []);
  return { copied, copy };
}

const ARTIFACT_LIMIT = 32;
const TOOL_LIMIT = 24;
const PREVIEW_PANEL_MIN_WIDTH = 480;
const PREVIEW_PANEL_CHAT_MIN_WIDTH = 420;

const ARTIFACT_DISMISS_STORAGE_PREFIX = "elevate.chat.artifacts.dismissed.v1:";

function readDismissedArtifactKeys(sessionId: string | null | undefined): Set<string> {
  if (typeof window === "undefined" || !sessionId) return new Set();
  try {
    const raw = window.localStorage.getItem(`${ARTIFACT_DISMISS_STORAGE_PREFIX}${sessionId}`);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed.filter((entry): entry is string => typeof entry === "string"));
  } catch {}
  return new Set();
}

function writeDismissedArtifactKeys(sessionId: string | null | undefined, keys: Set<string>): void {
  if (typeof window === "undefined" || !sessionId) return;
  try {
    if (keys.size === 0) {
      window.localStorage.removeItem(`${ARTIFACT_DISMISS_STORAGE_PREFIX}${sessionId}`);
      return;
    }
    window.localStorage.setItem(
      `${ARTIFACT_DISMISS_STORAGE_PREFIX}${sessionId}`,
      JSON.stringify(Array.from(keys).slice(-64)),
    );
  } catch {}
}

function clampPreviewPanelWidth(width: number): number {
  if (typeof window === "undefined") return Math.round(width);
  const max = Math.max(
    PREVIEW_PANEL_MIN_WIDTH,
    window.innerWidth - PREVIEW_PANEL_CHAT_MIN_WIDTH,
  );
  const min = Math.min(PREVIEW_PANEL_MIN_WIDTH, max);
  return Math.round(Math.min(max, Math.max(min, width)));
}

function defaultPreviewPanelWidth(): number {
  if (typeof window === "undefined") return 720;
  try {
    const stored = localStorage.getItem("elevate-preview-width");
    if (stored) { const n = parseInt(stored, 10); if (Number.isFinite(n) && n > 0) return clampPreviewPanelWidth(n); }
  } catch {}
  return clampPreviewPanelWidth(window.innerWidth * 0.5);
}

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
    description: "Listings, deals, document process, nightly checks, and transaction ops.",
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
    description: "Future paid ads, listing campaigns, email campaigns, and creative briefs.",
    enabled: true,
    id: "ads",
    name: "Ads",
    role: "Paid campaign lane",
    status: "ready",
  },
  {
    description: "Organic posts, captions, hooks, and platform adaptation.",
    enabled: true,
    id: "social-media",
    name: "Social Media",
    role: "Content lane",
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

const SESSION_MESSAGE_CACHE = new Map<string, ChatMessage[]>();
const SESSION_MESSAGE_STORAGE_KEY = "elevate.chat.messageCache.v1";
const MAX_CACHED_TRANSCRIPTS = 24;
const MAX_STORED_TRANSCRIPT_MESSAGES = 160;
const MAX_STORED_TRANSCRIPT_CHARS = 220_000;
const MAX_STORED_MESSAGE_CHARS = 16_000;
let SHARED_CHAT_GATEWAY: GatewayClient | null = null;
let SHARED_CHAT_GATEWAY_VERSION = 0;

interface StoredTranscriptCacheEntry {
  messages: ChatMessage[];
  updatedAt: number;
}

type StoredTranscriptCache = Record<string, StoredTranscriptCacheEntry>;

function getSharedChatGateway(version: number): GatewayClient {
  if (!SHARED_CHAT_GATEWAY || SHARED_CHAT_GATEWAY_VERSION !== version) {
    SHARED_CHAT_GATEWAY?.close();
    SHARED_CHAT_GATEWAY = new GatewayClient();
    SHARED_CHAT_GATEWAY_VERSION = version;
  }
  return SHARED_CHAT_GATEWAY;
}

function id(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function parseObjectPayload(text: string): Record<string, unknown> | null {
  const clean = text.trim();
  if (!clean || (!clean.startsWith("{") && !clean.startsWith("["))) return null;
  try {
    const parsed = JSON.parse(clean);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function isRawToolPayload(text: string): boolean {
  const clean = text.trim();
  if (!clean) return false;
  const parsed = parseObjectPayload(clean);
  if (parsed) {
    return [
      "content",
      "duration_seconds",
      "error",
      "files",
      "is_binary",
      "matches",
      "output",
      "status",
      "tool_calls_made",
      "total_count",
      "total_lines",
    ].some((key) => key in parsed);
  }
  return clean.length > 420 && /^(?:\{|\[)/.test(clean);
}

function shouldKeepTranscriptMessage(role: ChatRole, content: string): boolean {
  const clean = content.trim();
  if (!clean) return false;
  if (role === "tool") return false;
  if (role !== "user" && isRawToolPayload(clean)) return false;
  return true;
}

function normalizeTranscript(messages?: GatewayTranscriptMessage[]): ChatMessage[] {
  return (messages ?? [])
    .filter((m) =>
      shouldKeepTranscriptMessage(m.role, String(m.text ?? m.context ?? "")),
    )
    .map((m, index) => ({
      content: String(m.text ?? m.context ?? ""),
      createdAt: Date.now() - Math.max(0, (messages?.length ?? 0) - index),
      id: id(`history-${index}`),
      role: m.role,
      status: "complete" as const,
      title: m.name,
    }));
}

function timestampMillis(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return fallback;
  }
  return value < 1_000_000_000_000 ? value * 1000 : value;
}

function normalizeStoredTranscript(messages?: StoredSessionMessage[]): ChatMessage[] {
  return (messages ?? [])
    .filter((m) =>
      shouldKeepTranscriptMessage(
        m.role,
        typeof m.content === "string" ? m.content : "",
      ),
    )
    .map((m, index) => ({
      content: String(m.content ?? ""),
      createdAt: timestampMillis(
        m.timestamp,
        Date.now() - Math.max(0, (messages?.length ?? 0) - index),
      ),
      id: id(`stored-${index}`),
      role: m.role,
      status: "complete" as const,
      title: m.tool_name,
    }));
}

function readStoredTranscriptCache(): StoredTranscriptCache {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(SESSION_MESSAGE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as StoredTranscriptCache
      : {};
  } catch {
    return {};
  }
}

function normalizeCachedTranscript(messages: unknown): ChatMessage[] | null {
  if (!Array.isArray(messages)) return null;
  const normalized: ChatMessage[] = [];
  messages.forEach((message, index) => {
    if (!message || typeof message !== "object") return;
    const entry = message as Partial<ChatMessage>;
    const role = entry.role;
    const content = typeof entry.content === "string" ? entry.content : "";
    if (
      role !== "assistant" &&
      role !== "system" &&
      role !== "tool" &&
      role !== "user"
    ) {
      return;
    }
    if (!shouldKeepTranscriptMessage(role, content)) return;
    normalized.push({
      content,
      createdAt: timestampMillis(entry.createdAt, Date.now() - index),
      id: typeof entry.id === "string" && entry.id ? entry.id : id(`cached-${index}`),
      role,
      status:
        entry.status === "error" ||
        entry.status === "interrupted" ||
        entry.status === "streaming"
          ? entry.status
          : "complete" as const,
      title: typeof entry.title === "string" ? entry.title : undefined,
      warning: typeof entry.warning === "string" ? entry.warning : undefined,
      tools: Array.isArray(entry.tools) ? entry.tools : undefined,
      traces: Array.isArray(entry.traces) ? entry.traces : undefined,
      tokenCount:
        typeof entry.tokenCount === "number" ? entry.tokenCount : undefined,
      attachments: Array.isArray(entry.attachments)
        ? entry.attachments
        : undefined,
    });
  });
  return normalized.length ? normalized : null;
}

// Slim a turn's tool snapshot before it goes into localStorage. The
// activity digest only needs name/context/summary/status to render —
// drop the heavy streaming preview + inline diff, truncate long args,
// and cap the count so a tool-heavy turn can't blow the cache budget.
function slimToolsForStorage(tools?: ToolEntry[]): ToolEntry[] | undefined {
  if (!tools?.length) return undefined;
  const cut = (value?: string) =>
    value && value.length > 300 ? `${value.slice(0, 300)}…` : value;
  return tools.slice(-60).map((tool) => ({
    kind: "tool",
    id: tool.id,
    tool_id: tool.tool_id,
    name: tool.name,
    context: cut(tool.context),
    summary: cut(tool.summary),
    status: tool.status,
    startedAt: tool.startedAt,
    completedAt: tool.completedAt,
    messageId: tool.messageId,
  }));
}

function slimTracesForStorage(
  traces?: ActivityTrace[],
): ActivityTrace[] | undefined {
  if (!traces?.length) return undefined;
  return traces.slice(-40).map((trace) => ({
    createdAt: trace.createdAt,
    id: trace.id,
    kind: trace.kind,
    messageId: trace.messageId,
    text: trace.text.length > 500 ? `${trace.text.slice(0, 500)}…` : trace.text,
  }));
}

function trimTranscriptForStorage(messages: ChatMessage[]): ChatMessage[] {
  let used = 0;
  const trimmed: ChatMessage[] = [];
  for (const message of messages.slice(-MAX_STORED_TRANSCRIPT_MESSAGES).reverse()) {
    if (message.status === "streaming") continue;
    const content =
      message.content.length > MAX_STORED_MESSAGE_CHARS
        ? `${message.content.slice(0, MAX_STORED_MESSAGE_CHARS)}\n\n[Cached preview trimmed. Full history reloads from disk.]`
        : message.content;
    const size = content.length + (message.title?.length ?? 0) + (message.warning?.length ?? 0);
    if (trimmed.length && used + size > MAX_STORED_TRANSCRIPT_CHARS) break;
    used += size;
    trimmed.push({
      ...message,
      content,
      status: message.status ?? "complete",
      tools: slimToolsForStorage(message.tools),
      traces: slimTracesForStorage(message.traces),
    });
  }
  return trimmed.reverse();
}

function writeStoredTranscript(sessionId: string, messages: ChatMessage[]): void {
  if (typeof window === "undefined" || !sessionId || !messages.length) return;
  const cache = readStoredTranscriptCache();
  cache[sessionId] = {
    messages: trimTranscriptForStorage(messages),
    updatedAt: Date.now(),
  };
  const entries = Object.entries(cache)
    .filter(([, entry]) => Array.isArray(entry?.messages) && entry.messages.length)
    .sort(([, a], [, b]) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, MAX_CACHED_TRANSCRIPTS);
  try {
    window.localStorage.setItem(
      SESSION_MESSAGE_STORAGE_KEY,
      JSON.stringify(Object.fromEntries(entries)),
    );
  } catch {
    try {
      const smaller = Object.fromEntries(entries.slice(0, Math.max(4, Math.floor(entries.length / 2))));
      window.localStorage.setItem(SESSION_MESSAGE_STORAGE_KEY, JSON.stringify(smaller));
    } catch {}
  }
}

function restoreTranscript(sessionId: string): ChatMessage[] | null {
  if (!sessionId) return null;
  const memory = SESSION_MESSAGE_CACHE.get(sessionId);
  if (memory?.length) return memory;
  const entry = readStoredTranscriptCache()[sessionId];
  const restored = normalizeCachedTranscript(entry?.messages);
  if (restored) {
    SESSION_MESSAGE_CACHE.set(sessionId, restored);
  }
  return restored;
}

function rememberTranscript(sessionId: string, messages: ChatMessage[]): void {
  if (!sessionId) return;
  const stableMessages = messages.filter((message) => message.status !== "streaming");
  if (!stableMessages.length) return;
  SESSION_MESSAGE_CACHE.delete(sessionId);
  SESSION_MESSAGE_CACHE.set(sessionId, stableMessages);
  while (SESSION_MESSAGE_CACHE.size > MAX_CACHED_TRANSCRIPTS) {
    const oldest = SESSION_MESSAGE_CACHE.keys().next().value;
    if (!oldest) break;
    SESSION_MESSAGE_CACHE.delete(oldest);
  }
  writeStoredTranscript(sessionId, stableMessages);
}

// Merge a fresh server transcript with whatever the client cached locally.
// The server persists messages only when a turn completes, so a refresh that
// happens mid-turn returns a transcript that's missing the user's just-sent
// message. Anything in the cache whose id isn't in the server response is
// almost certainly an in-flight message — keep it appended.
//
// Match by role+content fingerprint, not by id: server and client generate
// independent random IDs for the same logical message, so id-based matching
// incorrectly treats every cached message as "not on server" and appends the
// entire cache as a duplicate tail.
function mergeServerWithCache(
  serverMessages: ChatMessage[],
  cached: ChatMessage[] | null,
): ChatMessage[] {
  if (!cached?.length) return serverMessages;
  const fp = (m: ChatMessage) => `${m.role}:${m.content.slice(0, 200)}`;
  const serverFingerprints = new Set(serverMessages.map(fp));

  // The server transcript doesn't carry tool/trace/token snapshots.
  // Re-attach them from the cached counterpart so the activity digest
  // renders on resumed turns. Match on the same fingerprint the tail
  // logic uses.
  const cachedByFp = new Map<string, ChatMessage>();
  for (const msg of cached) cachedByFp.set(fp(msg), msg);
  const enriched = serverMessages.map((msg) => {
    const match = cachedByFp.get(fp(msg));
    let next = msg;
    // The server transcript never stores attachment metadata. Re-attach
    // it from the cache so a sent image still shows its chip on resume.
    if (
      msg.role === "user" &&
      !msg.attachments?.length &&
      match?.attachments?.length
    ) {
      next = { ...next, attachments: match.attachments };
    }
    const hasSnapshot =
      !!next.tools?.length ||
      !!next.traces?.length ||
      typeof next.tokenCount === "number";
    if (hasSnapshot) return next;
    if (
      match &&
      (match.tools?.length ||
        match.traces?.length ||
        typeof match.tokenCount === "number")
    ) {
      return {
        ...next,
        tools: match.tools,
        traces: match.traces,
        tokenCount: match.tokenCount,
      };
    }
    return next;
  });

  const tail: ChatMessage[] = [];
  for (let i = cached.length - 1; i >= 0; i--) {
    const msg = cached[i];
    if (serverFingerprints.has(fp(msg))) break;
    tail.unshift(msg);
  }
  return tail.length ? [...enriched, ...tail] : enriched;
}

// Detect whether the cached transcript ends with a user message that has no
// following assistant reply — the telltale sign that a turn was in flight
// when the user refreshed.
function hasPendingTurn(messages: ChatMessage[]): boolean {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant") return false;
    if (msg.role === "user") return true;
  }
  return false;
}

const QUEUE_STORAGE_KEY = "elevate.chat.queueCache.v1";
const MAX_STORED_QUEUE_SESSIONS = 12;

type StoredQueueCache = Record<string, { items: QueuedInput[]; updatedAt: number }>;

function readQueueCache(): StoredQueueCache {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(QUEUE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as StoredQueueCache)
      : {};
  } catch {
    return {};
  }
}

function normalizeStoredQueue(value: unknown): QueuedInput[] {
  if (!Array.isArray(value)) return [];
  const out: QueuedInput[] = [];
  value.forEach((entry, index) => {
    if (!entry || typeof entry !== "object") return;
    const e = entry as Partial<QueuedInput>;
    const text = typeof e.text === "string" ? e.text : "";
    const routedText = typeof e.routedText === "string" ? e.routedText : text;
    if (!text) return;
    out.push({
      createdAt: typeof e.createdAt === "number" ? e.createdAt : Date.now() - index,
      id: typeof e.id === "string" && e.id ? e.id : id(`queued-${index}`),
      routedText,
      status: e.status === "error" ? "error" : "queued",
      text,
    });
  });
  return out.slice(-5);
}

function restoreQueue(sessionId: string | null | undefined): QueuedInput[] {
  if (!sessionId) return [];
  const entry = readQueueCache()[sessionId];
  return normalizeStoredQueue(entry?.items);
}

function writeQueue(sessionId: string | null | undefined, items: QueuedInput[]): void {
  if (typeof window === "undefined" || !sessionId) return;
  const cache = readQueueCache();
  if (!items.length) {
    delete cache[sessionId];
  } else {
    cache[sessionId] = { items: items.slice(-5), updatedAt: Date.now() };
  }
  const entries = Object.entries(cache)
    .sort(([, a], [, b]) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, MAX_STORED_QUEUE_SESSIONS);
  try {
    window.localStorage.setItem(
      QUEUE_STORAGE_KEY,
      JSON.stringify(Object.fromEntries(entries)),
    );
  } catch {}
}



type ProgressState = "done" | "error" | "pending" | "running";

interface ProgressSummary {
  /** Event time used to sort the Activity panel chronologically. */
  at?: number;
  detail?: string;
  details: string[];
  id: string;
  label: string;
  status: ProgressState;
}

function plural(count: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralLabel}`;
}

function compactLine(value: string | undefined, fallback = ""): string {
  return (value || fallback).replace(/\s+/g, " ").trim();
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function summarizeRawToolPayload(text: string, fallback: string): string | null {
  const clean = text.trim();
  const parsed = parseObjectPayload(clean);

  if (parsed) {
    const totalCount = typeof parsed.total_count === "number" ? parsed.total_count : undefined;
    const files = Array.isArray(parsed.files) ? parsed.files.map(String) : [];
    if (totalCount !== undefined && files.length) {
      const keyFiles = files
        .filter((file) => /\.(pdf|html|md|json|txt|csv|xlsx|docx)$/i.test(file))
        .slice(0, 3)
        .map(fileName);
      return `Found ${plural(totalCount, "output file")} ${keyFiles.length ? `(${keyFiles.join(", ")})` : ""}`.trim();
    }

    const matches = Array.isArray(parsed.matches) ? parsed.matches : [];
    if (totalCount !== undefined && matches.length) {
      return `Found ${plural(totalCount, "match", "matches")}`;
    }

    const totalLines =
      typeof parsed.total_lines === "number" ? parsed.total_lines : undefined;
    const fileSize = typeof parsed.file_size === "number" ? parsed.file_size : undefined;
    if (typeof parsed.content === "string" && totalLines !== undefined) {
      return `Read ${plural(totalLines, "line")} ${fileSize ? `(${formatBytes(fileSize)})` : ""}`.trim();
    }

    const status = typeof parsed.status === "string" ? parsed.status : undefined;
    const calls =
      typeof parsed.tool_calls_made === "number"
        ? parsed.tool_calls_made
        : undefined;
    const duration =
      typeof parsed.duration_seconds === "number"
        ? `${parsed.duration_seconds.toFixed(1)}s`
        : undefined;
    if (status || calls !== undefined || duration) {
      return [
        status ? status[0].toUpperCase() + status.slice(1) : "Completed",
        calls !== undefined ? plural(calls, "tool call") : "",
        duration ? `in ${duration}` : "",
      ]
        .filter(Boolean)
        .join(" ");
    }

    if (typeof parsed.output === "string") {
      const lines = parsed.output.split("\n").filter((line) => line.trim());
      if (lines.length > 1) return `Collected ${plural(lines.length, "output line")}`;
      if (lines[0]) return compactLine(lines[0]).slice(0, 180);
    }
  }

  if (clean.length > 360 || clean.split("\n").length > 8) {
    return `${fallback} produced ${formatBytes(clean.length)} of output`;
  }

  return null;
}

function toolDetail(tool: ToolEntry): string {
  const raw = tool.summary || tool.preview || tool.context || tool.error || "";
  const summarized = summarizeRawToolPayload(raw, tool.name);
  return (summarized ?? compactLine(raw, tool.name)).slice(0, 180);
}

function toolKind(tool: ToolEntry): "edit" | "other" | "read" | "run" | "search" {
  const haystack = `${tool.name} ${tool.context ?? ""} ${tool.summary ?? ""} ${tool.preview ?? ""}`.toLowerCase();
  if (/\b(apply_patch|patch|edit|write|rename|delete|changed|modified)\b/.test(haystack)) {
    return "edit";
  }
  if (/\b(rg|grep|search|find|query)\b/.test(haystack)) return "search";
  if (/\b(read|cat|sed|nl|open|view|ls|file)\b/.test(haystack)) return "read";
  if (/\b(bash|shell|terminal|command|exec|npm|pnpm|yarn|git|python|node|curl|tmux|build|test)\b/.test(haystack)) {
    return "run";
  }
  return "other";
}

function summaryStatus(tools: ToolEntry[]): ProgressState {
  if (tools.some((tool) => tool.status === "error")) return "error";
  if (tools.some((tool) => tool.status === "running")) return "running";
  return "done";
}

function detailsFor(tools: ToolEntry[]): string[] {
  return tools.map((tool) => `${tool.name}: ${toolDetail(tool)}`).filter(Boolean).slice(-4);
}

function isGenericActivityText(text: string): boolean {
  const clean = displayStatusText(text).trim().toLowerCase();
  return (
    clean === "" ||
    clean === "working..." ||
    clean === "thinking..." ||
    clean === "reasoning..." ||
    clean === "running..." ||
    clean === "ready" ||
    clean === "done" ||
    // Transient watchdog heartbeats — fine on the live status line, but
    // they should never pile up as permanent rows in the Activity panel.
    clean.startsWith("sending request") ||
    clean.startsWith("still working")
  );
}

function progressIntentLabel(text: string): string {
  const clean = displayStatusText(text).trim();
  if (!clean || isGenericActivityText(clean)) return "";

  const lower = clean.toLowerCase();
  if (
    /^running\b/.test(lower) ||
    /^preparing\b/.test(lower) ||
    /\bcomplete$/.test(lower) ||
    /\bfailed$/.test(lower)
  ) {
    return "";
  }

  const firstSentence = clean.match(/^[^.!?]+[.!?]?/)?.[0] ?? clean;
  const label = firstSentence
    .replace(/^(?:i['’]m going to|i am going to|i['’]ll|i will)\s+/i, "")
    .replace(/^(?:now|next|then),?\s+/i, "")
    .replace(/^going to\s+/i, "")
    .replace(/\s+now\.?$/i, "")
    .trim();

  if (!label) return "";
  return `${label[0].toUpperCase()}${label.slice(1)}`.slice(0, 92);
}

function addProgressSummary(
  summaries: ProgressSummary[],
  summary: ProgressSummary,
): void {
  const normalized = summary.label.toLowerCase();
  if (summaries.some((item) => item.label.toLowerCase() === normalized)) return;
  summaries.push(summary);
}

function buildProgressSummaries({
  activityTrace,
  artifacts,
  busy,
  statusText,
  tools,
}: {
  activityTrace: ActivityTrace[];
  artifacts: ArtifactEntry[];
  busy: boolean;
  statusText: string;
  tools: ToolEntry[];
}): ProgressSummary[] {
  const groups = {
    edit: [] as ToolEntry[],
    other: [] as ToolEntry[],
    read: [] as ToolEntry[],
    run: [] as ToolEntry[],
    search: [] as ToolEntry[],
  };

  for (const tool of tools) {
    groups[toolKind(tool)].push(tool);
  }

  // Real (already-happened) items each carry an event timestamp so the
  // panel reads top-to-bottom in the order the turn actually ran —
  // reasoning and tool groups interleaved by time, not bucketed into a
  // fixed pipeline order.
  const real: ProgressSummary[] = [];

  const groupStart = (entries: ToolEntry[]): number => {
    const starts = entries.map((tool) => tool.startedAt || 0).filter(Boolean);
    return starts.length ? Math.min(...starts) : 0;
  };

  activityTrace
    .map((trace) => ({
      at: trace.createdAt || 0,
      id: trace.id,
      label: progressIntentLabel(trace.text),
    }))
    .filter((item) => item.label)
    .slice(-3)
    .forEach((item) => {
      addProgressSummary(real, {
        at: item.at,
        details: [],
        id: item.id,
        label: item.label,
        status: "done",
      });
    });

  const explore = [...groups.read, ...groups.search];
  if (explore.length) {
    addProgressSummary(real, {
      at: groupStart(explore),
      details: detailsFor(explore),
      id: "explore",
      label: "Review relevant context",
      status: summaryStatus(explore),
    });
  }

  if (groups.edit.length) {
    addProgressSummary(real, {
      at: groupStart(groups.edit),
      details: detailsFor(groups.edit),
      id: "edit",
      label: "Apply focused changes",
      status: summaryStatus(groups.edit),
    });
  }

  if (groups.run.length) {
    addProgressSummary(real, {
      at: groupStart(groups.run),
      details: detailsFor(groups.run),
      id: "run",
      label: "Verify the result",
      status: summaryStatus(groups.run),
    });
  }

  if (groups.other.length) {
    addProgressSummary(real, {
      at: groupStart(groups.other),
      details: detailsFor(groups.other),
      id: "other",
      label: "Use supporting tools",
      status: summaryStatus(groups.other),
    });
  }

  if (artifacts.length) {
    // Outputs land after the tools that produced them.
    const lastToolEnd = Math.max(
      0,
      ...tools.map((tool) => tool.completedAt ?? tool.startedAt ?? 0),
    );
    addProgressSummary(real, {
      at: lastToolEnd || Date.now(),
      details: artifacts.slice(-8).map((artifact) =>
        compactLine(artifact.detail || artifact.path || artifact.source, artifact.title),
      ),
      id: "artifacts",
      label: "Prepare outputs",
      status: "done",
    });
  }

  real.sort((a, b) => (a.at ?? 0) - (b.at ?? 0));

  // The live "current" line and the pending checklist always sit at the
  // bottom — they are what's happening right now and what's still to come.
  const tail: ProgressSummary[] = [];
  const current = progressIntentLabel(statusText || "Working...");
  if (
    busy &&
    current &&
    !real.some((item) => item.label.toLowerCase() === current.toLowerCase())
  ) {
    addProgressSummary(tail, {
      details: [],
      id: "current",
      label: current,
      status: "running",
    });
  }

  if (busy) {
    if (!groups.edit.length && tools.length > 0) {
      addProgressSummary(tail, {
        details: [],
        id: "pending-change",
        label: "Make the needed update",
        status: "pending",
      });
    }
    if (!groups.run.length) {
      addProgressSummary(tail, {
        details: [],
        id: "pending-verify",
        label: "Check that it works",
        status: "pending",
      });
    }
    addProgressSummary(tail, {
      details: [],
      id: "pending-wrap",
      label: "Report the result",
      status: "pending",
    });
  }

  const summaries = [...real, ...tail];
  if (!summaries.length) {
    return [{ details: [], id: "ready", label: "Ready", status: "done" }];
  }

  // Cap the list, but always keep the live tail (current + pending) — drop
  // the oldest real items first so the panel stays current.
  const MAX_ROWS = 6;
  if (summaries.length > MAX_ROWS) {
    const keepHead = Math.max(0, MAX_ROWS - tail.length);
    return [...real.slice(real.length - keepHead), ...tail];
  }
  return summaries;
}

function activityStartedAt(
  tools: ToolEntry[],
  traces: ActivityTrace[],
  fallback = Date.now(),
): number {
  const starts = [
    ...tools.map((tool) => tool.startedAt).filter(Boolean),
    ...traces.map((trace) => trace.createdAt).filter(Boolean),
  ];
  return starts.length ? Math.min(...starts) : fallback;
}

function activityFinishedAt(tools: ToolEntry[], fallback = Date.now()): number {
  const ends = tools.map((tool) => tool.completedAt ?? tool.startedAt).filter(Boolean);
  return ends.length ? Math.max(...ends) : fallback;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

// Rough live token estimate (~4 chars/token). Exact counts only arrive at
// message.complete; this keeps the live meter ticking on every delta.
function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
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
  const clean = text
    .trim()
    .replace(/^[^A-Za-z0-9/[{]+/, "")
    .replace(/\s+/g, " ");
  if (!clean) return "";

  const lower = clean.toLowerCase();
  if (
    lower.includes("computing") ||
    lower.includes("pondering") ||
    lower.includes("reasoning") ||
    lower.includes("thinking") ||
    /[•_]>|-■/.test(clean)
  ) {
    return "Working...";
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

const HUB_INTERFACE_CONTEXT = [
  "[Elevate Hub interface context]",
  "The user is typing inside Elevate Agent Hub web chat.",
  [
    "When the user asks to open, view, show, preview, or pull up a generated PDF,",
    "document, image, report, local artifact, 'it', 'this', or something on the",
    "side/right side, prefer the Hub's built-in artifact preview/side pane.",
  ].join(" "),
  [
    "Do not launch Chrome, Safari, desktop apps, localhost, or 127.0.0.1 just to",
    "display a local artifact from Hub chat.",
  ].join(" "),
  [
    "If the Hub UI already opened or can open the artifact, answer briefly with the",
    "artifact name or where it is available in the Hub preview.",
  ].join(" "),
].join("\n");

function routePromptForAgent(text: string, agent: ComposerAgent): string {
  const userRequest = `User request: ${text}`;

  if (agent.id === "executive-assistant") {
    return [HUB_INTERFACE_CONTEXT, userRequest].join("\n\n");
  }

  return [
    HUB_INTERFACE_CONTEXT,
    `[Elevate agent route: ${agent.name} (${agent.id})]`,
    "Use this specialist lane for the turn when useful, then return the answer in this chat.",
    userRequest,
  ].join("\n\n");
}

function nowLabel(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function deriveChatTitle(
  messages: ChatMessage[],
  resumeId: string | null,
  resumeFallback: boolean,
): string {
  if (resumeFallback) return "New chat";
  const firstUser = messages.find((message) => message.role === "user");
  const base = firstUser?.content.split("\n")[0].trim();
  if (base) return base.length > 54 ? `${base.slice(0, 51)}...` : base;
  return resumeId ? "Resumed chat" : "New chat";
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

function fileExtension(path: string): string {
  const name = fileName(path).toLowerCase();
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot) : "";
}

function previewKind(path: string, contentType: string): "html" | "image" | "office" | "pdf" | "text" | "unknown" {
  const ext = fileExtension(path);
  const type = contentType.toLowerCase();
  if (type.includes("pdf") || ext === ".pdf") return "pdf";
  if (type.startsWith("image/") || [".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"].includes(ext)) {
    return "image";
  }
  if (type.includes("html") || ext === ".html" || ext === ".htm") return "html";
  if (/^https?:\/\//i.test(path) && !ext) return "html";
  if (
    type.startsWith("text/") ||
    [".csv", ".json", ".log", ".md", ".txt", ".yaml", ".yml"].includes(ext)
  ) {
    return "text";
  }
  if ([".docx", ".pptx", ".xlsx"].includes(ext)) return "office";
  return "unknown";
}

function artifactKey(entry: Omit<ArtifactEntry, "createdAt" | "id" | "key">) {
  return [
    entry.kind,
    entry.messageId ?? "",
    entry.path ?? "",
    entry.source ?? "",
    entry.title,
    (entry.content ?? "").slice(0, 120),
  ].join(":");
}

// Stable identity for the "user dismissed this preview" set.  Unlike
// `artifactKey` this deliberately omits `messageId` and `source`: when a
// session is resumed the cached transcript and the server transcript can
// assign different message IDs to the same artifact, which would change
// `artifactKey` and make a previously-closed PDF pop back open.  The file
// path (or content for inline artifacts) is the durable identity.
function artifactDismissKey(
  entry: Pick<ArtifactEntry, "kind" | "path" | "title" | "content">,
): string {
  if (entry.path) return `${entry.kind}:path:${entry.path}`;
  return `${entry.kind}:inline:${entry.title}:${(entry.content ?? "").slice(0, 120)}`;
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
  return Array.from(new Set(matches ?? []))
    // Drop bare single-segment root paths like "/coming-soon.html".
    // Those are almost always web routes / URL paths the agent mentioned,
    // not real local files — the preview server 404s on them and the
    // artifact gets stuck open. Real local artifacts always live inside
    // a directory (/Users/.../x.html, /tmp/.../x.html, ~/dir/x.html).
    .filter((path) => !(path.startsWith("/") && path.indexOf("/", 1) === -1))
    .slice(0, 12);
}

function artifactsFromText(
  text: string,
  source: string,
  messageId?: string,
): ArtifactEntry[] {
  return extractPathsFromText(text).map((path) =>
    makeArtifact({
      detail: path,
      kind: "file",
      messageId,
      path,
      source,
      title: fileName(path),
    }),
  );
}

function artifactsFromMessages(messages: ChatMessage[]): ArtifactEntry[] {
  return messages.flatMap((message) => {
    if (!message.content.trim()) return [];
    return artifactsFromText(message.content, `${message.role} history`, message.id);
  });
}

function previewPriority(artifact: ArtifactEntry): number {
  if (!artifact.path) return -1;
  const ext = fileExtension(artifact.path);
  if (ext === ".pdf") return 100;
  if (ext === ".html" || ext === ".htm") return 90;
  if ([".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"].includes(ext)) return 80;
  if ([".md", ".txt"].includes(ext)) return 50;
  return -1;
}

function bestSidePreviewArtifact(artifacts: ArtifactEntry[]): ArtifactEntry | null {
  let best: ArtifactEntry | null = null;
  let bestScore = -1;

  for (const artifact of artifacts) {
    const score = previewPriority(artifact);
    if (score < 0) continue;
    if (
      !best ||
      score > bestScore ||
      (score === bestScore && artifact.createdAt > best.createdAt)
    ) {
      best = artifact;
      bestScore = score;
    }
  }

  return best;
}

function isOpenPreviewIntent(text: string): boolean {
  const lower = text.toLowerCase();
  const asksToOpen =
    /\b(open|show|preview|view|display)\b/.test(lower) ||
    /\b(pull|bring|pop)\s+(it|this|that|up)\b/.test(lower);
  if (!asksToOpen) return false;

  return /\b(it|this|that|pdf|document|doc|file|artifact|report|output|result|local|side\s*bar|sidebar|side\s*pane|right\s*side|preview\s*pane|hub)\b/.test(
    lower,
  );
}

function artifactsFromToolComplete(
  payload: Record<string, unknown>,
  messageId?: string,
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
        messageId,
        source: toolName,
        title: `${toolName} changes`,
      }),
    );
    artifacts.push(...artifactsFromText(inlineDiff, toolName, messageId));
  }

  if (summary) {
    artifacts.push(...artifactsFromText(summary, toolName, messageId));
  }

  return artifacts;
}

function artifactsFromSubagentEvent(
  payload: Record<string, unknown>,
  messageId?: string,
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
        messageId,
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
        messageId,
        source: tool,
        status: item.is_error ? "error" : "ok",
        title: `${tool} output ${index + 1}`,
      }),
    );
    artifacts.push(...artifactsFromText(preview, tool, messageId));
  });

  if (summary) {
    artifacts.push(...artifactsFromText(summary, source, messageId));
  }

  return artifacts;
}

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const resumeId = searchParams.get("resume");
  const newChatId = searchParams.get("new");
  const seedKey = searchParams.get("seed");
  const seededRef = useRef(false);
  // Auto-resume gate. When the user lands on /chat with no ?resume= and no
  // ?new=, we look up the most-recent TUI session and redirect with
  // ?resume=<id> instead of minting a fresh session. The bootstrap effect
  // waits on this gate so it doesn't mint a session before the redirect
  // lands. Initialized to true when the URL already disambiguates (resume
  // or new) — no probe needed there.
  const [autoResumeDecided, setAutoResumeDecided] = useState(
    Boolean(resumeId || newChatId),
  );
  const [version, setVersion] = useState(0);
  const gw = useMemo(
    () => getSharedChatGateway(version),
    [version],
  );

  const [state, setState] = useState<ConnectionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const activeSessionRef = useRef<string | null>(null);
  const currentAssistantRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const commandPopoverRef = useRef<SlashPopoverHandle | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const voiceBaseInputRef = useRef("");
  const queueDispatchRef = useRef(false);
  const historyHydratedRef = useRef(false);
  const persistedSessionIdRef = useRef<string | null>(null);
  // Live mirrors of tools/activityTrace so the message.complete handler
  // can snapshot the finished turn without a stale-closure read.
  const toolsRef = useRef<ToolEntry[]>([]);
  const activityTraceRef = useRef<ActivityTrace[]>([]);
  // Cumulative session usage mirror + the output-token baseline captured
  // at message.start, so message.complete can diff out this turn's tokens.
  const usageRef = useRef<UsageInfo | null>(null);
  const turnOutputBaselineRef = useRef<number | null>(null);

  const [info, setInfo] = useState<SessionInfo>({});
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactEntry[]>([]);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactEntry | null>(null);
  const dismissedArtifactsRef = useRef<Set<string>>(new Set());
  const [previewPanelWidth, setPreviewPanelWidth] = useState(defaultPreviewPanelWidth);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  // Subagent panel is no longer rendered (consolidated into the assistant
  // activity digest), but event handlers still call setSubagents so we
  // keep the setter alive without holding render state.
  const [, setSubagents] = useState<SubagentEntry[]>([]);
  const [activityTrace, setActivityTrace] = useState<ActivityTrace[]>([]);
  const [input, setInput] = useState("");
  const [caretIndex, setCaretIndex] = useState(0);
  const composerScrollTopRef = useRef(0);
  const richLayerRef = useRef<HTMLDivElement>(null);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const dragCounterRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
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
      ? window.matchMedia("(max-width: 1023px)").matches
      : false,
  );

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
    const previewCandidate = bestSidePreviewArtifact(entries);

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

    if (previewCandidate && !dismissedArtifactsRef.current.has(artifactDismissKey(previewCandidate))) {
      setPreviewArtifact(previewCandidate);
    }
  }, []);

  const dismissPreviewArtifact = useCallback(() => {
    setPreviewArtifact((current) => {
      if (current) {
        dismissedArtifactsRef.current.add(artifactDismissKey(current));
        writeDismissedArtifactKeys(sessionId, dismissedArtifactsRef.current);
      }
      return null;
    });
  }, [sessionId]);

  const hydrateArtifactsFromMessages = useCallback(
    (nextMessages: ChatMessage[]) => {
      addArtifacts(artifactsFromMessages(nextMessages));
    },
    [addArtifacts],
  );

  const openArtifactPreview = useCallback(
    (artifact: ArtifactEntry) => {
      const dKey = artifactDismissKey(artifact);
      if (dismissedArtifactsRef.current.has(dKey)) {
        dismissedArtifactsRef.current.delete(dKey);
        writeDismissedArtifactKeys(sessionId, dismissedArtifactsRef.current);
      }
      setPreviewArtifact(artifact);
    },
    [sessionId],
  );

  const startPreviewResize = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (!previewArtifact) return;
      event.preventDefault();

      const target = event.currentTarget;
      const pointerId = event.pointerId;
      const startX = event.clientX;
      const startWidth = previewPanelWidth;
      const shell = target.closest(".elevate-chat-shell") as HTMLElement | null;

      target.setPointerCapture(pointerId);

      const onPointerMove = (moveEvent: PointerEvent) => {
        const delta = startX - moveEvent.clientX;
        const clamped = clampPreviewPanelWidth(startWidth + delta);
        if (shell) shell.style.setProperty("--preview-panel-width", `${clamped}px`);
      };

      const stopResize = () => {
        if (target.hasPointerCapture(pointerId)) {
          target.releasePointerCapture(pointerId);
        }
        const finalWidth = shell
          ? parseInt(shell.style.getPropertyValue("--preview-panel-width") || String(startWidth), 10)
          : startWidth;
        setPreviewPanelWidth(clampPreviewPanelWidth(finalWidth));
        try { localStorage.setItem("elevate-preview-width", String(clampPreviewPanelWidth(finalWidth))); } catch {}
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", stopResize);
        window.removeEventListener("pointercancel", stopResize);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", stopResize);
      window.addEventListener("pointercancel", stopResize);
    },
    [previewArtifact, previewPanelWidth],
  );

  const addActivityTrace = useCallback(
    (kind: ActivityTrace["kind"], text: string) => {
      const clean = displayStatusText(text).trim();
      if (!clean) return;
      if (
        (kind === "thinking" || kind === "reasoning" || kind === "status") &&
        isGenericActivityText(clean)
      ) {
        return;
      }

      const messageId = currentAssistantRef.current ?? undefined;
      setActivityTrace((prev) => {
        const last = prev[prev.length - 1];
        if (last?.kind === kind && last.text === clean && last.messageId === messageId) {
          return prev;
        }
        // Streaming thinking/reasoning arrives as many small deltas
        // ("I", "Notice", "There's"...). Coalesce consecutive chunks
        // of the same kind + message into one rolling entry so the
        // Activity panel shows whole thoughts, not token fragments.
        if (
          (kind === "thinking" || kind === "reasoning") &&
          last?.kind === kind &&
          last.messageId === messageId
        ) {
          const sep = /[.!?…]$/.test(last.text) ? " " : last.text.endsWith(" ") || clean.startsWith(" ") ? "" : " ";
          const merged = (last.text + sep + clean).trim().slice(-2000);
          const next = prev.slice(0, -1);
          next.push({ ...last, text: merged });
          return next;
        }
        return [
          ...prev,
          {
            createdAt: Date.now(),
            id: id(`activity-${kind}`),
            kind,
            text: clean,
            messageId,
          },
        ].slice(-200);
      });
    },
    [],
  );

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1023px)");
    const sync = () => setNarrow(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    dismissedArtifactsRef.current = readDismissedArtifactKeys(sessionId);
  }, [sessionId]);

  useEffect(() => {
    const sync = () => {
      setPreviewPanelWidth((width) => clampPreviewPanelWidth(width));
    };
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  useEffect(() => {
    if (!previewArtifact) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); dismissPreviewArtifact(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previewArtifact, dismissPreviewArtifact]);

  useEffect(() => {
    let cancelled = false;

    api
      .getAgentHub({
        lite: true,
        includeMemoryGraph: false,
        includeOrchestration: false,
        includeSkills: false,
        includeToolsets: false,
        includeHarness: false,
      })
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
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, tools, pendingPrompt]);

  useEffect(() => {
    toolsRef.current = tools;
  }, [tools]);

  useEffect(() => {
    activityTraceRef.current = activityTrace;
  }, [activityTrace]);

  useEffect(() => {
    usageRef.current = usage;
  }, [usage]);

  useEffect(() => {
    const persisted = persistedSessionIdRef.current;
    if (persisted && messages.length) {
      rememberTranscript(persisted, messages);
    }
  }, [messages]);

  useEffect(() => {
    const persisted = persistedSessionIdRef.current ?? sessionId;
    if (!persisted) return;
    writeQueue(persisted, queuedInputs);
  }, [queuedInputs, sessionId]);

  // Auto-resume probe. When /chat mounts with neither ?resume= nor ?new=,
  // pull the most-recent active TUI session and redirect into it via
  // ?resume=<id>. If there is no recent candidate, release the gate so the
  // bootstrap effect below proceeds with a fresh session.create.
  // Lifecycle invariant: this effect runs at most once per mount.
  useEffect(() => {
    if (autoResumeDecided) return;
    let cancelled = false;
    void (async () => {
      try {
        const { sessions } = await api.getSessions(10, 0, {
          includeTotal: false,
        });
        if (cancelled) return;
        const now = Date.now() / 1000;
        // Pick the most-recent TUI session with at least one message
        // whose last activity was within the past 24h. Anything older
        // is stale enough that a fresh start is a better default.
        const recent = sessions.find((s) => {
          if (s.source !== "tui") return false;
          if ((s.message_count ?? 0) < 1) return false;
          const lastActive = s.last_active ?? s.started_at ?? 0;
          return now - lastActive < 86_400;
        });
        if (recent?.id) {
          // Redirect into the recent session instead of minting a new one.
          // The effect cleanup will fire and bootstrap will re-run with
          // resumeId set, taking the normal resume code path.
          const next = new URLSearchParams(searchParams);
          next.set("resume", recent.id);
          setSearchParams(next, { replace: true });
          return;
        }
      } catch {
        // Network/auth glitch — fall through and let bootstrap create a
        // fresh session.  The sidebar still lets the user open prior
        // chats by hand.
      }
      if (!cancelled) setAutoResumeDecided(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [autoResumeDecided, searchParams, setSearchParams]);

  useEffect(() => {
    if (!autoResumeDecided) return;
    let cancelled = false;
    const unsubs: Array<() => void> = [];

    activeSessionRef.current = null;
    currentAssistantRef.current = null;
    historyHydratedRef.current = false;
    persistedSessionIdRef.current = resumeId;
    setSessionId(null);
    setInfo({});
    setUsage(null);
    setArtifacts([]);
    setPreviewArtifact(null);
    dismissedArtifactsRef.current = readDismissedArtifactKeys(resumeId);
    setTools([]);
    setSubagents([]);
    setActivityTrace([]);
    setQueuedInputs(resumeId ? restoreQueue(resumeId) : []);
    setPendingPrompt(null);
    setPromptValue("");
    setBusy(false);
    setBanner(null);
    setResumeFallback(false);
    setStatusText(resumeId ? "Loading chat..." : "Connecting...");

    if (resumeId) {
      const cached = restoreTranscript(resumeId);
      if (cached) {
        historyHydratedRef.current = true;
        setMessages(cached);
        hydrateArtifactsFromMessages(cached);
        if (hasPendingTurn(cached)) {
          setBusy(true);
          setStatusText("Resuming work...");
        } else {
          setStatusText("Ready");
        }
      }

      void api.getSessionMessages(resumeId)
        .then((response) => {
          if (cancelled) return;
          const hydrated = normalizeStoredTranscript(response.messages);
          const merged = mergeServerWithCache(hydrated, cached);
          historyHydratedRef.current = true;
          rememberTranscript(response.session_id || resumeId, merged);
          rememberTranscript(resumeId, merged);
          setMessages(merged);
          hydrateArtifactsFromMessages(merged);
          if (!hasPendingTurn(merged)) {
            // Cache heuristic flagged this as pending (last msg = user
            // with no assistant follow-up) so busy was set true at
            // L1899. The server-side transcript confirms no pending
            // turn — clear busy too, otherwise the composer stays
            // locked behind a "Resuming work" mirage that the gateway
            // has no knowledge of.
            setBusy(false);
            setStatusText("Ready");
          }
        })
        .catch((error: Error) => {
          if (cancelled || cached) return;
          setBanner(`Could not load saved messages yet: ${error.message}`);
        });
    } else {
      persistedSessionIdRef.current = null;
      setMessages([]);
    }

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
        const turnMessageId = currentAssistantRef.current ?? undefined;

        setTools((prev) =>
          prev.some((tool) => tool.tool_id === toolId)
            ? prev.map((tool) =>
                tool.tool_id === toolId
                  ? {
                      ...tool,
                      context,
                      messageId: tool.messageId ?? turnMessageId,
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
                        messageId: tool.messageId ?? turnMessageId,
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
                    messageId: turnMessageId,
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
        const turnMessageId = currentAssistantRef.current ?? undefined;

        setTools((prev) => {
          const hasRunning = prev.some(
            (tool) => tool.status === "running" && tool.name === name,
          );
          if (hasRunning) {
            return prev.map((tool) =>
              tool.status === "running" && tool.name === name
                ? { ...tool, messageId: tool.messageId ?? turnMessageId, preview }
                : tool,
            );
          }

          return [
            ...prev,
            {
              id: id(`tool-${name}`),
              kind: "tool" as const,
              messageId: turnMessageId,
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
        addArtifacts(
          artifactsFromToolComplete(payload, currentAssistantRef.current ?? undefined),
        );
      }
    };

    const trackSubagent = (ev: GatewayEvent) => {
      if (!accepts(ev)) return;
      const payload = compactToolPayload(ev.payload);
      const goal = compactLine(
        String(payload.goal || payload.text || payload.summary || "Subagent"),
      );
      const subagentId = String(payload.subagent_id || goal || `subagent-${Date.now()}`);
      const preview = compactLine(
        String(payload.tool_preview || payload.text || payload.summary || ""),
      );
      const statusText = String(payload.status || "").toLowerCase();
      const nextStatus: SubagentEntry["status"] =
        ev.type === "subagent.complete"
          ? statusText.includes("error") || statusText.includes("fail")
            ? "error"
            : "done"
          : "running";
      const now = Date.now();

      setSubagents((prev) => {
        const existing = prev.find((subagent) => subagent.subagent_id === subagentId);
        if (existing) {
          return prev
            .map((subagent) =>
              subagent.subagent_id === subagentId
                ? {
                    ...subagent,
                    completedAt: nextStatus === "running" ? subagent.completedAt : now,
                    goal: goal || subagent.goal,
                    model: typeof payload.model === "string" ? payload.model : subagent.model,
                    preview: preview || subagent.preview,
                    status: nextStatus,
                    toolCount:
                      typeof payload.tool_count === "number"
                        ? payload.tool_count
                        : subagent.toolCount,
                  }
                : subagent,
            )
            .slice(-12);
        }

        return [
          ...prev,
          {
            completedAt: nextStatus === "running" ? undefined : now,
            goal: goal || "Subagent",
            id: id("subagent"),
            model: typeof payload.model === "string" ? payload.model : undefined,
            preview: preview || undefined,
            startedAt: now,
            status: nextStatus,
            subagent_id: subagentId,
            toolCount:
              typeof payload.tool_count === "number" ? payload.tool_count : undefined,
          },
        ].slice(-12);
      });

      if (ev.type === "subagent.complete") {
        addArtifacts(
          artifactsFromSubagentEvent(payload, currentAssistantRef.current ?? undefined),
        );
      }
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
        setSubagents((prev) => prev.filter((subagent) => subagent.status === "running").slice(-8));
        ensureAssistant();
        // Snapshot cumulative output tokens so message.complete can diff
        // out exactly this turn's count.
        turnOutputBaselineRef.current = usageRef.current?.output ?? null;
        setBusy(true);
        setStatusText("Working...");
        addActivityTrace("status", "Working...");
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
        const messageId = currentAssistantRef.current ?? ensureAssistant();

        // Snapshot the finished turn's tools + reasoning traces onto the
        // message so the activity digest survives a session resume. Any
        // tool still "running" at message.complete is coerced to "done"
        // (the turn is over — nothing is actually still executing).
        const turnTools = toolsRef.current
          .filter((tool) => tool.messageId === messageId)
          .map((tool) =>
            tool.status === "running"
              ? {
                  ...tool,
                  status: "done" as const,
                  completedAt: tool.completedAt ?? Date.now(),
                }
              : tool,
          );
        const turnTraces = activityTraceRef.current.filter(
          (trace) =>
            trace.messageId === messageId &&
            (trace.kind === "reasoning" || trace.kind === "thinking"),
        );
        // Freeze this turn's token count. Prefer the real per-turn output
        // (cumulative-now minus the baseline captured at message.start);
        // fall back to the live estimate when usage deltas aren't usable.
        const completeUsage = normalizeUsage(compactToolPayload(ev.payload).usage);
        const baseline = turnOutputBaselineRef.current;
        const realTurnOutput =
          completeUsage?.output != null &&
          baseline != null &&
          completeUsage.output >= baseline
            ? completeUsage.output - baseline
            : undefined;
        turnOutputBaselineRef.current = null;

        updateAssistant((message) => {
          const finalContent = text || message.content;
          const estimatedTurnTokens =
            estimateTokens(finalContent) +
            turnTraces.reduce(
              (sum, trace) => sum + estimateTokens(trace.text),
              0,
            );
          return {
            ...message,
            content: finalContent,
            status: status === "interrupted" ? "interrupted" : "complete",
            warning: warning || undefined,
            tools: turnTools.length ? turnTools : message.tools,
            traces: turnTraces.length ? turnTraces : message.traces,
            tokenCount: realTurnOutput ?? (estimatedTurnTokens || undefined),
          };
        });
        if (text) {
          addArtifacts(artifactsFromText(text, "assistant", messageId));
        }
        // The turn is over: its tools + reasoning are now snapshotted onto
        // the message above. Clear the live activity state so the side
        // Activity panel goes idle ("Ready") instead of leaving stale
        // "Analyzing." / "Sending request..." rows hanging after the reply.
        setTools([]);
        setActivityTrace([]);
        currentAssistantRef.current = null;
        setBusy(false);
        setSubagents((prev) =>
          prev.map((subagent) =>
            subagent.status === "running"
              ? {
                  ...subagent,
                  completedAt: Date.now(),
                  status: status === "interrupted" ? "error" : "done",
                }
              : subagent,
          ),
        );
        if (status === "interrupted") {
          setQueuedInputs([]);
        }
        setStatusText(status === "interrupted" ? "Interrupted" : "Ready");
      }),
    );
    unsubs.push(
      gw.on("status.update", (ev) => {
        if (!accepts(ev)) return;
        const text = eventString(ev, "text");
        if (text) {
          setStatusText(displayStatusText(text));
          addActivityTrace("status", text);
        }
      }),
    );
    unsubs.push(
      gw.on("thinking.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) {
          setStatusText("Thinking...");
          ensureAssistant();
          addActivityTrace("thinking", text);
        }
      }),
    );
    unsubs.push(
      gw.on("reasoning.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) {
          setStatusText("Reasoning...");
          ensureAssistant();
          addActivityTrace("reasoning", text);
        }
      }),
    );
    unsubs.push(gw.on("tool.start", trackTool));
    unsubs.push(gw.on("tool.progress", trackTool));
    unsubs.push(gw.on("tool.complete", trackTool));
    unsubs.push(gw.on("subagent.start", trackSubagent));
    unsubs.push(gw.on("subagent.progress", trackSubagent));
    unsubs.push(gw.on("subagent.tool", trackSubagent));
    unsubs.push(gw.on("subagent.complete", trackSubagent));
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
        setSubagents((prev) =>
          prev.map((subagent) =>
            subagent.status === "running"
              ? { ...subagent, completedAt: Date.now(), status: "error" }
              : subagent,
          ),
        );
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
              include_messages: false,
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
        persistedSessionIdRef.current =
          created.persisted_session_id ?? created.resumed ?? resumeId ?? null;
        // Don't auto-rewrite URL to ?resume= on fresh sessions.
        // Resume should only happen when the user explicitly picks a
        // session from the sidebar (which navigates with ?resume=).
        // Auto-rewrite caused confusing message accumulation across visits.
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
          if (!historyHydratedRef.current) {
            const hydrated = normalizeTranscript(
              Array.isArray(resumed.messages) ? resumed.messages : undefined,
            );
            const cached = resumeId ? restoreTranscript(resumeId) : null;
            const merged = mergeServerWithCache(hydrated, cached);
            setMessages(merged);
            hydrateArtifactsFromMessages(merged);
            if (persistedSessionIdRef.current) {
              rememberTranscript(persistedSessionIdRef.current, merged);
            }
          }
        } else if (!resumeId && !historyHydratedRef.current) {
          setMessages([]);
        }
        const stillRunning =
          "running" in created &&
          (created as SessionResumeResponse).running === true;

        // Replay events from the server-side ring buffer. The ring only
        // ever holds in-flight events — server-side, the ring is cleared
        // on message.complete, so a completed turn never replays. That
        // keeps reattach silent: the hydrated transcript is the visible
        // state, and replay only contributes the partial assistant turn
        // (message.start + deltas, tool.start cards) that's still mid-
        // flight. Listener closures filter on activeSessionRef so events
        // route to the right session.
        const resumed = created as SessionResumeResponse;
        if (
          Array.isArray(resumed.replay_events) &&
          resumed.replay_events.length > 0
        ) {
          gw.replayEvents(resumed.replay_events);
        }

        if (stillRunning) {
          // Mid-turn on the server side. Keep the spinner up; live
          // frames continue from where the replay left off. No status
          // banner — reattach should be visually identical to the
          // moment the user left, only forward progress should appear.
          setBusy(true);
          // replayEvents ran synchronously above, so currentAssistantRef
          // is set if the ring buffer still held this turn's message.start.
          // If it doesn't (ring rotated, or the turn started before the
          // reattach window), there's no streaming assistant message — so
          // the "Working" digest has nowhere to render. Mint a placeholder
          // so the live meter shows; message.complete will fill it in.
          if (!currentAssistantRef.current) {
            ensureAssistant();
          }
          // Restore the running tool cards. The event ring can rotate a
          // long turn's tool.start frames out, so replay alone is not
          // enough — the gateway also hands back a snapshot of every tool
          // still executing. Feed them through the same tool.start path;
          // trackTool dedupes on tool_id, so a tool whose start frame
          // survived in the ring is not doubled.
          if (
            Array.isArray(resumed.running_tools) &&
            resumed.running_tools.length > 0
          ) {
            gw.replayEvents(
              resumed.running_tools.map((rt) => ({
                type: "tool.start" as const,
                session_id: created.session_id,
                payload: {
                  tool_id: rt.tool_id,
                  name: rt.name,
                  context: rt.context ?? "",
                },
              })),
            );
          }
        } else {
          // Gateway confirms no live turn. The transcript may still end
          // on a user message (pendingAfterResume) because the agent
          // died mid-turn when the tab detached — but a pending-looking
          // turn that the gateway is NOT running is a dead turn, not a
          // resuming one. Clearing busy unconditionally here unlocks the
          // composer instead of leaving it stuck behind a permanent
          // "Resuming work" spinner the gateway will never finish.
          setBusy(false);
          setStatusText("Ready");
        }
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setBanner(error.message);
        setStatusText("Connection failed");
      });

    return () => {
      cancelled = true;
      unsubs.forEach((unsub) => unsub());
      // Route/tab changes must detach from the live session, not close it.
      // Closing here tears down the in-memory gateway session while a turn may
      // still be running, which makes work appear to stop and prevents reliable
      // reattachment by persisted session id.
    };
  }, [
    addActivityTrace,
    addArtifacts,
    appendMessage,
    autoResumeDecided,
    ensureAssistant,
    gw,
    hydrateArtifactsFromMessages,
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

  const removeAttachment = useCallback(
    (attachmentId: string) => {
      setAttachments((prev) => {
        const target = prev.find((item) => item.id === attachmentId);
        if (target?.path && sessionId) {
          void gw
            .request("attachments.clear", { session_id: sessionId, path: target.path })
            .catch(() => {});
        }
        return prev.filter((item) => item.id !== attachmentId);
      });
    },
    [gw, sessionId],
  );

  // Attachments are staged per session. Switching chats must drop any
  // pending chips — otherwise an image uploaded under session A keeps
  // showing (and would attach to the wrong session) over in session B.
  useEffect(() => {
    setAttachments([]);
  }, [sessionId]);

  const uploadAttachment = useCallback(
    (file: File) => {
      if (!sessionId) {
        setBanner("Connect to a session before attaching files.");
        return;
      }
      if (file.size > ATTACHMENT_MAX_BYTES) {
        setBanner(
          `${file.name}: ${formatAttachmentSize(file.size)} exceeds the 25 MB attachment cap.`,
        );
        return;
      }
      const localId = id("attach");
      const placeholder: ChatAttachment = {
        id: localId,
        name: file.name || "file",
        size: file.size,
        mediaType: file.type || "application/octet-stream",
        status: "uploading",
      };
      setAttachments((prev) => [...prev, placeholder]);

      void makeImageThumbnail(file).then((preview) => {
        if (!preview) return;
        setAttachments((prev) =>
          prev.map((item) =>
            item.id === localId ? { ...item, previewUrl: preview } : item,
          ),
        );
      });

      void api
        .uploadChatAttachment(sessionId, file)
        .then((response) => {
          setAttachments((prev) =>
            prev.map((item) =>
              item.id === localId
                ? {
                    ...item,
                    name: response.name || item.name,
                    size: response.size ?? item.size,
                    mediaType: response.media_type || item.mediaType,
                    path: response.path,
                    status: "ready" as const,
                  }
                : item,
            ),
          );
        })
        .catch((error) => {
          const message = error instanceof Error ? error.message : String(error);
          setAttachments((prev) =>
            prev.map((item) =>
              item.id === localId
                ? { ...item, status: "error" as const, error: message }
                : item,
            ),
          );
          setBanner(`Upload failed (${file.name}): ${message}`);
        });
    },
    [sessionId],
  );

  const uploadAttachments = useCallback(
    (files: FileList | File[]) => {
      const list = Array.from(files);
      list.forEach(uploadAttachment);
    },
    [uploadAttachment],
  );

  const onPaperclipClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onFileInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      if (event.target.files && event.target.files.length > 0) {
        uploadAttachments(event.target.files);
      }
      event.target.value = "";
    },
    [uploadAttachments],
  );

  const submitGatewayPrompt = useCallback(
    async (text: string, routedText: string, status = "Sending...") => {
      if (!sessionId) return;

      const readyAttachments = attachments.filter((item) => item.status === "ready" && item.path);
      const stillUploading = attachments.some((item) => item.status === "uploading");
      if (stillUploading) {
        setBanner("Wait for attachments to finish uploading before sending.");
        return;
      }

      const messageAttachments: ChatMessageAttachment[] = readyAttachments.map(
        (att) => ({
          name: att.name,
          size: att.size,
          mediaType: att.mediaType,
          previewUrl: att.previewUrl,
        }),
      );
      appendMessage(
        "user",
        text,
        messageAttachments.length ? { attachments: messageAttachments } : {},
      );
      setBusy(true);
      setStatusText(status);

      try {
        for (const att of readyAttachments) {
          if (!att.path) continue;
          try {
            await gw.request("file.attach", {
              session_id: sessionId,
              path: att.path,
            });
          } catch (attachError) {
            const m = attachError instanceof Error ? attachError.message : String(attachError);
            appendMessage("system", `Failed to attach ${att.name}: ${m}`, { status: "error" });
          }
        }

        const payload: Record<string, unknown> = {
          session_id: sessionId,
          text: routedText,
        };
        if (routedText !== text) {
          payload.persist_user_message = text;
        }

        await gw.request("prompt.submit", payload);
        setAttachments([]);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        appendMessage("system", message, { status: "error" });
        setBusy(false);
        setStatusText("Error");
      }
    },
    [appendMessage, attachments, gw, sessionId],
  );

  const interruptCurrentTurn = useCallback(() => {
    if (!sessionId || state !== "open") return;

    setQueuedInputs([]);
    setStatusText("Interrupting...");
    void gw
      .request("session.interrupt", { session_id: sessionId })
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        setBanner(`Interrupt failed: ${message}`);
      });
  }, [gw, sessionId, state]);

  const removeQueuedInput = useCallback((queuedId: string) => {
    setQueuedInputs((prev) => prev.filter((item) => item.id !== queuedId));
  }, []);

  const steerQueuedInput = useCallback(
    (queuedId: string) => {
      if (!sessionId || state !== "open") return;
      const item = queuedInputs.find((q) => q.id === queuedId);
      if (!item) return;
      const text = item.routedText || item.text;
      setQueuedInputs((prev) =>
        prev.map((q) => (q.id === queuedId ? { ...q, status: "queued" } : q)),
      );
      setStatusText("Steering current turn...");
      void gw
        .request("session.steer", { session_id: sessionId, text })
        .then((response) => {
          const status =
            response && typeof response === "object" && "status" in response
              ? String((response as Record<string, unknown>).status)
              : "queued";
          if (status === "rejected") {
            setQueuedInputs((prev) =>
              prev.map((q) =>
                q.id === queuedId ? { ...q, status: "error" } : q,
              ),
            );
            setStatusText("Steer rejected");
            return;
          }
          // Visually inject the steer mid-turn: finalize the assistant
          // chunk written so far, drop the steer in below it, then clear
          // the streaming ref so the agent's continued output starts a
          // fresh assistant message UNDER the steer — the conversation
          // reads in delivery order instead of the steer being stranded
          // at the bottom while text keeps growing above it.
          const priorAssistantId = currentAssistantRef.current;
          if (priorAssistantId) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === priorAssistantId && m.status === "streaming"
                  ? { ...m, status: "complete" }
                  : m,
              ),
            );
            currentAssistantRef.current = null;
          }
          appendMessage("user", item.text);
          setQueuedInputs((prev) => prev.filter((q) => q.id !== queuedId));
          setStatusText("Steer delivered");
        })
        .catch((error) => {
          const message = error instanceof Error ? error.message : String(error);
          setQueuedInputs((prev) =>
            prev.map((q) =>
              q.id === queuedId ? { ...q, status: "error" } : q,
            ),
          );
          setBanner(`Steer failed: ${message}`);
        });
    },
    [appendMessage, gw, queuedInputs, sessionId, state],
  );

  useEffect(() => {
    if (
      busy ||
      queueDispatchRef.current ||
      state !== "open" ||
      !sessionId ||
      queuedInputs.length === 0
    ) {
      return;
    }

    const next = queuedInputs.find((item) => item.status === "queued");
    if (!next) return;

    queueDispatchRef.current = true;
    setQueuedInputs((prev) => prev.filter((item) => item.id !== next.id));
    void submitGatewayPrompt(
      next.text,
      next.routedText,
      "Sending queued follow-up...",
    ).finally(() => {
      queueDispatchRef.current = false;
    });
  }, [busy, queuedInputs, sessionId, state, submitGatewayPrompt]);

  const hasReadyAttachment = attachments.some(
    (item) => item.status === "ready" && !!item.path,
  );

  const submitPrompt = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      // An attachment-only message (image with no caption) is a valid send.
      if (!trimmed && !hasReadyAttachment) return;

      setInput("");
      composerScrollTopRef.current = 0;
      if (richLayerRef.current) richLayerRef.current.style.transform = "translateY(0px)";
      setBanner(null);
      setAgentMenuOpen(false);

      const historyArtifacts = artifacts.length ? [] : artifactsFromMessages(messages);
      const availableArtifacts = artifacts.length ? artifacts : historyArtifacts;
      const previewTarget = bestSidePreviewArtifact(availableArtifacts);
      if (previewTarget && isOpenPreviewIntent(trimmed)) {
        if (historyArtifacts.length) {
          addArtifacts(historyArtifacts);
        }
        setPreviewArtifact(previewTarget);
        appendMessage("user", trimmed);
        appendMessage(
          "assistant",
          `Opened in the side preview: ${previewTarget.title}`,
          { status: "complete" },
        );
        setStatusText("Opened artifact preview");
        return;
      }

      if (trimmed.startsWith("/")) {
        if (!sessionId || state !== "open") {
          setInput(trimmed);
          setStatusText("Connecting...");
          return;
        }
        appendMessage("user", trimmed);
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

      if (!sessionId || state !== "open") {
        const queued: QueuedInput = {
          createdAt: Date.now(),
          id: id("queued"),
          routedText,
          status: "queued",
          text: trimmed,
        };
        setQueuedInputs((prev) => [...prev, queued].slice(-5));
        setStatusText("Queued until connected");
        return;
      }

      if (busy) {
        const queued: QueuedInput = {
          createdAt: Date.now(),
          id: id("queued"),
          routedText,
          status: "queued",
          text: trimmed,
        };
        setQueuedInputs((prev) => [...prev, queued].slice(-5));
        setStatusText("Queued follow-up");
        return;
      }

      await submitGatewayPrompt(trimmed, routedText);
    },
    [addArtifacts, appendMessage, artifacts, busy, gw, hasReadyAttachment, messages, selectedAgent, sessionId, state, submitGatewayPrompt],
  );

  useEffect(() => {
    if (seededRef.current) return;
    if (!seedKey || !sessionId || state !== "open" || busy) return;
    if (typeof window === "undefined") return;
    let raw: string | null = null;
    try {
      raw = window.sessionStorage.getItem(`elevate:chat-seed:${seedKey}`);
    } catch {
      raw = null;
    }
    if (!raw) return;
    seededRef.current = true;
    try {
      window.sessionStorage.removeItem(`elevate:chat-seed:${seedKey}`);
    } catch {}
    void submitPrompt(raw);
  }, [busy, seedKey, sessionId, state, submitPrompt]);

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

  const canSend =
    (!!input.trim() || hasReadyAttachment) &&
    (state === "open" ? !!sessionId : state !== "error" && state !== "closed");
  const canPickModel = state === "open" && !!sessionId;
  const visibleMessages = useMemo(
    () =>
      messages.filter((message) => {
        if (shouldKeepTranscriptMessage(message.role, message.content)) {
          return true;
        }
        // Keep an in-flight assistant turn visible even before any
        // text streams, so its activity digest ("Working for Xs" +
        // thinking/reasoning trace + tool cards) is on screen while
        // the model is actually reasoning — not just after it finishes.
        if (message.role !== "assistant") return false;
        if (message.status === "streaming") return true;
        const hasActivity = activityTrace.some(
          (trace) => trace.messageId === message.id,
        );
        if (hasActivity) return true;
        const hasTools = tools.some((tool) => tool.messageId === message.id);
        if (hasTools) return true;
        // Resumed turn: tools/traces live on the message snapshot, not
        // in the live state arrays.
        return Boolean(message.tools?.length || message.traces?.length);
      }),
    [activityTrace, messages, tools],
  );
  const artifactsByMessage = useMemo(() => {
    const grouped = new Map<string, ArtifactEntry[]>();
    for (const artifact of artifacts) {
      if (!artifact.messageId) continue;
      const next = grouped.get(artifact.messageId) ?? [];
      next.push(artifact);
      grouped.set(artifact.messageId, next);
    }
    return grouped;
  }, [artifacts]);
  const unanchoredArtifacts = useMemo(
    () => artifacts.filter((artifact) => !artifact.messageId),
    [artifacts],
  );
  const toolsByMessage = useMemo(() => {
    const grouped = new Map<string, ToolEntry[]>();
    for (const tool of tools) {
      if (!tool.messageId) continue;
      const next = grouped.get(tool.messageId) ?? [];
      next.push(tool);
      grouped.set(tool.messageId, next);
    }
    return grouped;
  }, [tools]);
  const tracesByMessage = useMemo(() => {
    const grouped = new Map<string, ActivityTrace[]>();
    for (const trace of activityTrace) {
      if (!trace.messageId) continue;
      const next = grouped.get(trace.messageId) ?? [];
      next.push(trace);
      grouped.set(trace.messageId, next);
    }
    return grouped;
  }, [activityTrace]);
  const chatTitle = useMemo(
    () => deriveChatTitle(visibleMessages, resumeId, resumeFallback),
    [resumeFallback, resumeId, visibleMessages],
  );
  const [folderLabel, setFolderLabel] = useState<string | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    api
      .getStatus()
      .then((status) => {
        if (cancelled) return;
        const root = status.project_root || status.elevate_home || "";
        const basename = root
          .replace(/\/+$/, "")
          .split("/")
          .filter(Boolean)
          .pop();
        if (basename) setFolderLabel(basename);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  const handleOpenChatMenu = useCallback(
    (anchor: { x: number; y: number }) => {
      if (typeof window === "undefined" || !sessionId) return;
      window.dispatchEvent(
        new CustomEvent("elevate:open-session-menu", {
          detail: { sessionId, x: anchor.x, y: anchor.y },
        }),
      );
    },
    [sessionId],
  );

  const { setTitle, setBeforeTitle, setEnd, sidebarCollapsed, onShowSidebar } = usePageHeader();
  useLayoutEffect(() => {
    setTitle(chatTitle);
    setBeforeTitle(
      folderLabel ? (
        <span className="flex shrink-0 items-center gap-1.5 text-[0.92rem] leading-6 text-muted-foreground">
          <span>{folderLabel}</span>
          <span className="opacity-60">/</span>
        </span>
      ) : null,
    );
    setEnd(
      sessionId ? (
        <button
          type="button"
          aria-label="Chat options"
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            handleOpenChatMenu({ x: rect.left, y: rect.bottom + 4 });
          }}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      ) : null,
    );
    return () => {
      setTitle(null);
      setBeforeTitle(null);
      setEnd(null);
    };
  }, [chatTitle, folderLabel, handleOpenChatMenu, sessionId, setBeforeTitle, setEnd, setTitle]);
  const previewPanelWidthPx = `${previewPanelWidth}px`;
  const previewPanelLayoutStyle = previewArtifact
    ? ({
        "--preview-panel-width": previewPanelWidthPx,
      } as CSSProperties)
    : undefined;
  const activity = (
    <ActivityPanel
      activityTrace={activityTrace}
      artifacts={artifacts}
      banner={banner}
      busy={busy}
      onOpenArtifact={openArtifactPreview}
      onReconnect={reconnect}
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
            "fixed right-4 top-4 z-[60] flex h-[52dvh] max-h-[32rem] min-h-[22rem] w-[min(24rem,calc(100vw-2rem))] flex-col",
            "normal-case",
            mobilePanelOpen ? "translate-x-0" : "translate-x-[calc(100%+1rem)]",
            "transition-transform duration-200 ease-out",
          )}
        >
          <Button
            aria-label="Close activity"
            className="absolute right-3 top-3 z-10 h-8 w-8 rounded-sm bg-[var(--chat-surface-strong)] p-0 text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
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

  const mobilePreviewPortal =
    narrow &&
    previewArtifact &&
    portalRoot &&
    createPortal(
      <>
        <button
          aria-label="Close artifact preview"
          className="fixed inset-0 z-[65] bg-black/60 backdrop-blur-sm"
          onClick={dismissPreviewArtifact}
          type="button"
        />
        <aside className="fixed inset-x-3 bottom-3 top-3 z-[70] animate-in fade-in slide-in-from-bottom-4 duration-200">
          <ArtifactPreviewPane
            artifact={previewArtifact}
            onClose={dismissPreviewArtifact}
          />
        </aside>
      </>,
      portalRoot,
    );

  return (
    <div
      className="elevate-chat-shell relative flex h-full min-h-0 flex-col overflow-hidden bg-[var(--chat-bg)] text-[var(--chat-text)] normal-case"
      style={previewPanelLayoutStyle}
    >
      <div className="flex min-h-0 flex-1">
        <section
          className={cn(
            "flex min-h-0 flex-1 flex-col",
            previewArtifact && "lg:basis-1/2",
          )}
        >
          <div
            className="relative h-11 shrink-0 px-4 sm:px-6 lg:mt-2"
            style={{ WebkitAppRegion: "drag" } as CSSProperties}
          >
            {sidebarCollapsed && onShowSidebar ? (
              <button
                type="button"
                onClick={onShowSidebar}
                aria-label="Show sidebar"
                style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
                className="absolute left-4 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)] sm:left-6"
              >
                <PanelLeftOpen className="h-3.5 w-3.5" />
              </button>
            ) : null}
            <div
              className="flex h-full w-full min-w-0 items-center gap-2 sm:gap-3"
              style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
            >
              {folderLabel ? (
                <span className="flex shrink-0 items-center gap-1.5 text-[0.92rem] leading-6 text-[var(--chat-muted)]">
                  <span>{folderLabel}</span>
                  <span className="opacity-60">/</span>
                </span>
              ) : null}
              <h1 className="min-w-0 truncate text-[0.95rem] font-semibold leading-6 tracking-[-0.005em] text-[var(--chat-text)]">
                {chatTitle}
              </h1>
              {sessionId ? (
                <button
                  type="button"
                  aria-label="Chat options"
                  onClick={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    handleOpenChatMenu({ x: rect.left, y: rect.bottom + 4 });
                  }}
                  className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-2 scrollbar-none sm:px-6 sm:pt-3">
            {visibleMessages.length === 0 ? (
              <EmptyState state={state} />
            ) : (
              <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-5 pb-6">
                {visibleMessages.map((message, index) => {
                  const isLatest = index === visibleMessages.length - 1;
                  const isAssistant = message.role === "assistant";
                  // Live state first; fall back to the snapshot stored on
                  // the message so resumed turns still show their digest.
                  const turnTools = isAssistant
                    ? toolsByMessage.get(message.id) ?? message.tools
                    : undefined;
                  const turnTraces = isAssistant
                    ? tracesByMessage.get(message.id) ?? message.traces
                    : undefined;
                  const turnArtifacts = isAssistant ? artifactsByMessage.get(message.id) : undefined;
                  const isStreaming = isAssistant && message.status === "streaming" && isLatest;
                  return (
                    <MessageRow
                      key={message.id}
                      activityTrace={turnTraces}
                      artifacts={turnArtifacts ?? []}
                      busy={isStreaming && busy}
                      message={message}
                      onOpenArtifact={openArtifactPreview}
                      tools={turnTools}
                      turnArtifacts={turnArtifacts}
                    />
                  );
                })}
                <ChatArtifactShelf
                  artifacts={unanchoredArtifacts}
                  onOpenArtifact={openArtifactPreview}
                />
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
            className="relative bg-[linear-gradient(180deg,transparent,var(--chat-bg)_18%)] px-4 pb-5 pt-3 sm:px-6"
            onSubmit={onSubmit}
            onDragEnter={(event) => {
              if (!event.dataTransfer?.types?.includes("Files")) return;
              event.preventDefault();
              dragCounterRef.current += 1;
              setDragOver(true);
            }}
            onDragOver={(event) => {
              if (!event.dataTransfer?.types?.includes("Files")) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
            }}
            onDragLeave={(event) => {
              if (!event.dataTransfer?.types?.includes("Files")) return;
              event.preventDefault();
              dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
              if (dragCounterRef.current === 0) setDragOver(false);
            }}
            onDrop={(event) => {
              if (!event.dataTransfer?.files?.length) return;
              event.preventDefault();
              dragCounterRef.current = 0;
              setDragOver(false);
              uploadAttachments(event.dataTransfer.files);
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              hidden
              onChange={onFileInputChange}
            />
            {dragOver && (
              <div className="pointer-events-none absolute inset-3 z-20 flex items-center justify-center rounded-lg border border-dashed border-[var(--chat-accent)] bg-[color-mix(in_srgb,var(--chat-accent)_12%,var(--chat-bg))] text-xs font-medium text-[var(--chat-accent)]">
                Drop to attach
              </div>
            )}
            <div className="mx-auto w-full max-w-[52rem]">
              <QueuedInputStrip
                busy={busy}
                onRemove={removeQueuedInput}
                onSteer={steerQueuedInput}
                queuedInputs={queuedInputs}
              />

              <div className="relative rounded-lg bg-[var(--chat-bg)] p-2.5 shadow-[inset_0_0_0_1px_var(--chat-border-strong)] focus-within:shadow-[inset_0_0_0_1px_var(--chat-accent)]">
                <AttachmentChipStrip
                  attachments={attachments}
                  onRemove={removeAttachment}
                />
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
                    layerRef={richLayerRef}
                  />
                  <textarea
                    ref={inputRef}
                    aria-autocomplete="list"
                    aria-controls="slash-popover-listbox"
                    aria-label="Message Elevate Agent"
                    className={cn(
                      "relative z-10 max-h-40 min-h-14 w-full resize-none bg-transparent px-2 pb-1 pt-1 text-sm leading-6 outline-none placeholder:text-[var(--chat-muted)]",
                      "caret-[var(--chat-text)] selection:bg-[var(--chat-accent-soft)]",
                      input
                        ? "text-transparent"
                        : "text-[var(--chat-text)]",
                    )}
                    disabled={state === "error"}
                    onChange={(event) => {
                      setInput(event.target.value);
                      setCaretIndex(event.currentTarget.selectionStart ?? event.target.value.length);
                      setAgentMenuOpen(false);
                      const el = event.currentTarget;
                      el.style.height = "auto";
                      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
                    }}
                    onClick={(event) =>
                      setCaretIndex(event.currentTarget.selectionStart ?? input.length)
                    }
                    onKeyDown={onComposerKeyDown}
                    onKeyUp={(event) =>
                      setCaretIndex(event.currentTarget.selectionStart ?? input.length)
                    }
                    onPaste={(event) => {
                      const items = event.clipboardData?.items;
                      if (!items || items.length === 0) return;
                      const files: File[] = [];
                      for (const item of items) {
                        if (item.kind === "file") {
                          const file = item.getAsFile();
                          if (file) files.push(file);
                        }
                      }
                      if (files.length > 0) {
                        event.preventDefault();
                        uploadAttachments(files);
                      }
                    }}
                    onScroll={(event) => {
                      const top = event.currentTarget.scrollTop;
                      composerScrollTopRef.current = top;
                      if (richLayerRef.current) richLayerRef.current.style.transform = `translateY(-${top}px)`;
                    }}
                    onSelect={(event) =>
                      setCaretIndex(event.currentTarget.selectionStart ?? input.length)
                    }
                    placeholder={
                      state === "error"
                        ? "Reconnect to continue..."
                        : "Message Elevate Agent..."
                    }
                    rows={1}
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
                  onAttach={onPaperclipClick}
                  onOpenModel={() => setModelOpen(true)}
                  onInterrupt={interruptCurrentTurn}
                  onSelectAgent={selectComposerAgent}
                  onToggleAgentMenu={() => {
                    setAgentMenuOpen((open) => !open);
                  }}
                  onToggleVoice={toggleVoiceInput}
                  selectedAgent={selectedAgent}
                  state={state}
                  usage={usage}
                  voiceListening={voiceListening}
                  voiceSupported={voiceSupported}
                />
              </div>
            </div>
          </form>
        </section>

        <aside
          className={cn(
            "hidden min-h-0 shrink-0 lg:flex",
            previewArtifact
              ? "flex-col pb-5 pl-0 pr-5 pt-2"
              : "w-[18rem] flex-col self-start pr-5 pt-[3.25rem]",
          )}
          style={
            previewArtifact
              ? { width: "min(var(--preview-panel-width), 50%)" }
              : undefined
          }
        >
          <div
            className={cn(
              "relative",
              previewArtifact
                ? "min-h-0 flex-1"
                : "max-h-[calc(100dvh-2.5rem)] overflow-hidden",
            )}
          >
            {previewArtifact && (
              <button
                aria-label="Resize artifact preview"
                className="absolute -left-5 top-6 z-20 flex h-[calc(100%-3rem)] w-11 touch-none cursor-col-resize items-center justify-center rounded-full text-[var(--chat-muted)] transition hover:text-[var(--chat-text)]"
                onPointerDown={startPreviewResize}
                type="button"
              >
                <span className="h-12 w-1.5 rounded-full bg-[color-mix(in_srgb,var(--chat-border)_78%,transparent)] shadow-[0_0_0_1px_color-mix(in_srgb,var(--chat-surface)_55%,transparent)] transition-all hover:w-2 hover:bg-[var(--chat-accent)]" />
              </button>
            )}
            {previewArtifact ? (
              <ArtifactPreviewPane
                artifact={previewArtifact}
                onClose={dismissPreviewArtifact}
              />
            ) : (
              activity
            )}
          </div>
        </aside>
      </div>
      {mobileActivityPortal}
      {mobilePreviewPortal}
      {narrow && !mobilePanelOpen && !previewArtifact && (
        <button
          className="fixed right-4 top-4 z-40 rounded-sm border border-[var(--chat-border)] bg-[var(--chat-surface)] px-3 py-1.5 text-xs font-medium text-[var(--chat-muted-strong)]"
          onClick={() => setMobilePanelOpen(true)}
          type="button"
        >
          Activity
        </button>
      )}
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
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-sm border border-[var(--chat-border-strong)] bg-[var(--chat-surface)] text-[var(--chat-accent)]">
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

function QueuedInputStrip({
  busy,
  onRemove,
  onSteer,
  queuedInputs,
}: {
  busy: boolean;
  onRemove: (id: string) => void;
  onSteer: (id: string) => void;
  queuedInputs: QueuedInput[];
}) {
  if (!queuedInputs.length) return null;

  return (
    <div className="mb-2 rounded-md bg-[var(--chat-surface-soft)] px-3 py-2">
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
              "group flex items-start gap-2 rounded-md px-2.5 py-1.5 text-xs",
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
            <div className="flex shrink-0 items-center gap-1">
              {busy && item.status !== "error" ? (
                <button
                  type="button"
                  onClick={() => onSteer(item.id)}
                  title="Steer current turn with this message"
                  className="rounded-full px-2 py-0.5 text-[0.65rem] font-medium text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-bg)] hover:text-[var(--chat-text)]"
                >
                  Steer
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => onRemove(item.id)}
                aria-label="Remove queued message"
                title="Remove from queue"
                className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-bg)] hover:text-[var(--chat-text)]"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AttachmentChipStrip({
  attachments,
  onRemove,
}: {
  attachments: ChatAttachment[];
  onRemove: (id: string) => void;
}) {
  if (!attachments.length) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {attachments.map((item) => {
        const Icon = attachmentIconFor(item.mediaType, item.name);
        const isError = item.status === "error";
        const isUploading = item.status === "uploading";

        if (item.previewUrl) {
          return (
            <div
              key={item.id}
              className="group relative h-16 w-16 overflow-hidden rounded-md border border-[var(--chat-border)] bg-[var(--chat-surface-soft)]"
              title={item.error || `${item.name} · ${formatAttachmentSize(item.size)}`}
            >
              <img
                src={item.previewUrl}
                alt={item.name}
                className={cn(
                  "h-full w-full object-cover",
                  (isUploading || isError) && "opacity-40",
                )}
              />
              {isUploading && (
                <span className="absolute inset-0 flex items-center justify-center text-[0.58rem] font-medium text-[var(--chat-text)]">
                  uploading...
                </span>
              )}
              {isError && (
                <span className="absolute inset-0 flex items-center justify-center text-[0.58rem] font-medium text-[var(--chat-danger)]">
                  failed
                </span>
              )}
              <button
                type="button"
                onClick={() => onRemove(item.id)}
                aria-label={`Remove ${item.name}`}
                className="absolute right-0.5 top-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-[var(--chat-bg)]/80 text-[var(--chat-muted)] transition-colors hover:text-[var(--chat-text)]"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </div>
          );
        }

        return (
          <div
            key={item.id}
            className={cn(
              "group flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.68rem]",
              isError
                ? "bg-[color-mix(in_srgb,var(--chat-danger)_14%,var(--chat-bg))] text-[var(--chat-danger)]"
                : "bg-[var(--chat-surface-soft)] text-[var(--chat-muted-strong)]",
            )}
            title={item.error || `${item.name} · ${formatAttachmentSize(item.size)}`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
            <span className="max-w-[14rem] truncate font-medium">{item.name}</span>
            <span className="text-[0.62rem] text-[var(--chat-muted)]">
              {isUploading ? "uploading..." : isError ? "failed" : formatAttachmentSize(item.size)}
            </span>
            <button
              type="button"
              onClick={() => onRemove(item.id)}
              aria-label={`Remove ${item.name}`}
              className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-bg)] hover:text-[var(--chat-text)]"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </div>
        );
      })}
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
  if (token.startsWith("/")) return token.slice(1) || "/";
  const raw = token.replace(/^@[a-z]+:/i, "").replace(/^@/, "");
  const parts = raw.split(/[/-]/).filter(Boolean);
  return parts.slice(-2).join(" / ") || raw;
}

function parseComposerSegments(input: string): ComposerSegment[] {
  const tokenPattern =
    /(^|\s)(\/[\w-]*|@(agent|skill|toolset|plugin|file|folder|url|git):[^\s]+|@(diff|staged)\b)/gi;
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
  layerRef,
}: {
  input: string;
  layerRef: React.RefObject<HTMLDivElement | null>;
}) {
  const segments = useMemo(() => parseComposerSegments(input), [input]);

  if (!input) return null;

  return (
    <div className="pointer-events-none absolute inset-0 z-0 max-h-40 overflow-hidden px-2 pb-1 pt-1 text-sm leading-6 text-[var(--chat-text)]">
      <div
        ref={layerRef}
        className="whitespace-pre-wrap break-words"
      >
        {segments.map((segment, index) => {
          if (segment.type === "text") {
            return <span key={`${index}-text`}>{segment.text}</span>;
          }

          // Render the token as inline accented text — exact same character
          // width as what the user typed in the textarea below, so the cursor
          // and line wrapping stay perfectly aligned.
          return (
            <span
              aria-label={segment.text}
              className="font-medium text-[var(--chat-accent)]"
              key={`${index}-${segment.text}`}
            >
              {segment.text}
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
      className="inline-flex h-7 items-center gap-1.5 rounded-sm bg-[var(--chat-surface-soft)] px-2.5 text-[var(--chat-muted-strong)]"
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
  onAttach,
  onOpenModel,
  onInterrupt,
  onSelectAgent,
  onToggleAgentMenu,
  onToggleVoice,
  selectedAgent,
  state,
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
  onAttach(): void;
  onOpenModel(): void;
  onInterrupt(): void;
  onSelectAgent(agent: ComposerAgent): void;
  onToggleAgentMenu(): void;
  onToggleVoice(): void;
  selectedAgent: ComposerAgent;
  state: ConnectionState;
  usage: UsageInfo | null;
  voiceListening: boolean;
  voiceSupported: boolean;
}) {
  return (
    <div className="mt-2 flex items-center justify-between gap-2 px-2 text-[0.68rem] text-[var(--chat-muted)]">
      <div className="flex min-w-0 items-center gap-1.5 overflow-x-auto scrollbar-none">
        <button
          type="button"
          onClick={onAttach}
          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]"
          title="Attach files"
          aria-label="Attach files"
        >
          <Paperclip className="h-3.5 w-3.5" />
        </button>

        <div className="relative">
          <button
            type="button"
            onClick={onToggleAgentMenu}
            className={cn(
              "inline-flex max-w-[12rem] items-center gap-1.5 text-[0.7rem]",
              "text-[var(--chat-muted-strong)] transition-colors",
              "hover:text-[var(--chat-text)]",
              agentMenuOpen && "text-[var(--chat-text)]",
            )}
            title="Choose agent lane"
          >
            <span className="truncate">{selectedAgent.name}</span>
            <ChevronUp className="h-3 w-3 shrink-0 opacity-50" />
          </button>

          {agentMenuOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={onToggleAgentMenu} />
              <div
                className="absolute bottom-[calc(100%+0.5rem)] left-0 z-30 w-[18rem] overflow-hidden rounded-md border border-[var(--chat-border-strong)] bg-[var(--chat-surface)] p-1.5 text-left"
                onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); onToggleAgentMenu(); } }}
                role="menu"
              >
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    role="menuitem"
                    onClick={() => onSelectAgent(agent)}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
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
            </>
          )}
        </div>

        <span
          className="text-[0.7rem] text-[var(--chat-muted-strong)]"
          title="Tool access"
        >
          Full access
        </span>

        <span aria-hidden className="text-[0.6rem] text-[var(--chat-muted)]">·</span>

        <button
          type="button"
          onClick={onOpenModel}
          disabled={!canPickModel}
          className={cn(
            "text-[0.7rem] text-[var(--chat-muted-strong)] transition-colors",
            "hover:text-[var(--chat-text)]",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
          title="Change model"
        >
          {modelLabel(info)}
        </button>

        <span aria-hidden className="text-[0.6rem] text-[var(--chat-muted)]">·</span>

        <ContextRing usage={usage} />

        <span aria-hidden className="text-[0.6rem] text-[var(--chat-muted)]">·</span>

        <button
          type="button"
          onClick={onToggleVoice}
          disabled={!voiceSupported}
          className={cn(
            "text-[0.7rem] text-[var(--chat-muted-strong)] transition-colors",
            "hover:text-[var(--chat-text)]",
            "disabled:cursor-not-allowed disabled:opacity-45",
            voiceListening && "text-[var(--chat-text)]",
          )}
          title={voiceSupported ? "Voice to text" : "Voice input unavailable"}
        >
          {voiceListening ? "Stop" : "Voice"}
        </button>
      </div>

      <div className="ml-auto flex min-w-0 items-center">
        <button
          aria-label={busy ? "Interrupt response" : "Send message"}
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-sm transition-all",
            busy
              ? "bg-[var(--chat-text)] text-[var(--chat-bg)]"
              : canSend
                ? "bg-[var(--chat-text)] text-[var(--chat-bg)] hover:opacity-90"
                : "bg-[var(--chat-surface-strong)] text-[var(--chat-muted)]",
          )}
          disabled={busy ? state !== "open" : !canSend}
          onClick={busy ? onInterrupt : undefined}
          title={busy ? "Stop the current response" : "Send message"}
          type={busy ? "button" : "submit"}
        >
          {busy ? (
            <span className="h-3 w-3 rounded-[0.22rem] bg-current" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );
}

function MessageRow({
  activityTrace,
  artifacts,
  busy,
  message,
  onOpenArtifact,
  tools,
  turnArtifacts,
}: {
  activityTrace?: ActivityTrace[];
  artifacts: ArtifactEntry[];
  busy?: boolean;
  message: ChatMessage;
  onOpenArtifact(artifact: ArtifactEntry): void;
  tools?: ToolEntry[];
  turnArtifacts?: ArtifactEntry[];
}) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  if (
    message.role === "tool" ||
    (message.role !== "user" && isRawToolPayload(message.content))
  ) {
    return null;
  }
  if (
    isAssistant &&
    !busy &&
    !message.content.trim() &&
    !(tools && tools.length) &&
    !(activityTrace && activityTrace.length)
  ) {
    return null;
  }

  // While the turn streams, estimate tokens from the visible assistant text
  // plus any reasoning/thinking traces so the live meter has something to
  // count. Exact usage replaces this at message.complete.
  const liveTokens =
    isAssistant && busy
      ? estimateTokens(message.content) +
        (activityTrace ?? []).reduce(
          (sum, trace) =>
            trace.kind === "reasoning" || trace.kind === "thinking"
              ? sum + estimateTokens(trace.text)
              : sum,
          0,
        )
      : 0;
  // Live turns show the digest from streaming state; completed turns show it
  // from the frozen per-turn snapshot (tokenCount is set at message.complete),
  // so it survives the live activity state being cleared after the turn.
  const showDigest =
    isAssistant &&
    (!!busy ||
      !!tools?.length ||
      !!activityTrace?.length ||
      typeof message.tokenCount === "number");

  return (
    <article
      className={cn(
        "group flex w-full text-left",
        isAssistant && "pt-3 first:pt-0",
      )}
    >
      <div
        className={cn(
          "min-w-0 flex-1 max-w-[74ch]",
          isUser && "flex flex-col items-end",
        )}
      >
        {showDigest ? (
          <ChatActivityDigest
            activityTrace={activityTrace ?? []}
            artifacts={turnArtifacts ?? []}
            busy={!!busy}
            liveTokens={liveTokens}
            startedAt={message.createdAt}
            tokenCount={message.tokenCount}
            tools={tools ?? []}
          />
        ) : null}
        <div
          className={cn(
            "max-w-full text-sm leading-7",
            isUser
              ? "inline-block rounded-md bg-[var(--chat-user)] px-3.5 py-2 text-[var(--chat-text)] shadow-sm"
              : message.role === "system"
                ? "rounded-lg border border-[color-mix(in_srgb,var(--chat-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_10%,var(--chat-bg))] px-3 py-2 text-[var(--chat-text)]"
                : "text-[var(--chat-text)]",
            showDigest ? "mt-2" : null,
          )}
        >
          {message.role === "assistant" ? (
            message.content ? (
              <div className="chat-message-prose [&>div]:text-[var(--chat-text)] [&_a]:text-[var(--chat-accent)] [&_code]:bg-[var(--chat-surface-strong)] [&_code]:text-[var(--chat-text)] [&_pre]:border-[var(--chat-border-strong)] [&_pre]:bg-[var(--chat-surface-soft)]">
                <Markdown content={message.content} />
              </div>
            ) : null
          ) : (
            <>
              {isUser && message.attachments && message.attachments.length > 0 ? (
                <div className="mb-2 flex flex-wrap justify-start gap-1.5">
                  {message.attachments.map((att, idx) => {
                    if (att.previewUrl) {
                      return (
                        <a
                          key={`${message.id}-att-${idx}`}
                          href={att.previewUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="block overflow-hidden rounded-md border border-[var(--chat-border-strong)] bg-[var(--chat-surface-soft)]"
                          title={`${att.name} · ${formatAttachmentSize(att.size)}`}
                        >
                          <img
                            src={att.previewUrl}
                            alt={att.name}
                            className="max-h-48 max-w-[16rem] object-contain"
                          />
                        </a>
                      );
                    }
                    const Icon = attachmentIconFor(att.mediaType, att.name);
                    return (
                      <span
                        key={`${message.id}-att-${idx}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--chat-border-strong)] bg-[var(--chat-surface-soft)] px-2 py-1 text-[0.7rem] text-[var(--chat-muted)]"
                        title={`${att.name} · ${formatAttachmentSize(att.size)}`}
                      >
                        <Icon className="h-3 w-3 shrink-0" />
                        <span className="max-w-[16ch] truncate">{att.name}</span>
                        <span className="opacity-60">{formatAttachmentSize(att.size)}</span>
                      </span>
                    );
                  })}
                </div>
              ) : null}
              {message.content ? (
                <div className="whitespace-pre-wrap break-words">
                  {message.content}
                </div>
              ) : null}
            </>
          )}
          {message.warning && (
            <div className="mt-3 rounded-lg border border-[color-mix(in_srgb,var(--chat-warning)_40%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_12%,var(--chat-bg))] px-3 py-2 text-xs text-[var(--chat-text)]">
              {message.warning}
            </div>
          )}
          {artifacts.length > 0 && (
            <div className="mt-3 space-y-2">
              {artifacts.slice(-4).map((artifact) => (
                <InlineArtifactCard
                  key={`message-artifact-${artifact.id}`}
                  artifact={artifact}
                  onOpenArtifact={onOpenArtifact}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

/**
 * One row in the per-turn breakdown dropdown — either an individual tool
 * call or a reasoning/thinking step, interleaved chronologically.
 */
type BreakdownStep =
  | {
      type: "tool";
      id: string;
      at: number;
      name: string;
      context: string;
      status: ToolEntry["status"];
      count: number;
    }
  | { type: "trace"; id: string; at: number; text: string };

/** Pick a lucide icon for a tool by substring-matching its name. */
function breakdownToolIcon(name: string): LucideIcon {
  const n = name.toLowerCase();
  if (/terminal|bash|shell|run|exec|command/.test(n)) return SquareTerminal;
  if (/search|grep|glob|find/.test(n)) return Search;
  if (/write|edit|patch/.test(n)) return FilePen;
  if (/read|cat|open|view/.test(n)) return FileText;
  if (/memory/.test(n)) return Brain;
  return Zap;
}

function truncatePreview(value: string | undefined, max = 48): string {
  const clean = (value ?? "").replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max)}…`;
}

/**
 * Build the chronological list of individual tool calls + reasoning steps
 * for the expanded breakdown. Memory tool calls are excluded — they get
 * their own standalone rows. Consecutive identical tool calls collapse
 * into one row with a `count`.
 */
function buildBreakdownSteps(
  tools: ToolEntry[],
  activityTrace: ActivityTrace[],
): BreakdownStep[] {
  const raw: BreakdownStep[] = [];

  for (const tool of tools) {
    if (tool.name.toLowerCase() === "memory") continue;
    raw.push({
      type: "tool",
      id: tool.id,
      at: tool.startedAt || 0,
      name: tool.name,
      context: tool.context ?? "",
      status: tool.status,
      count: 1,
    });
  }

  for (const trace of activityTrace) {
    if (trace.kind !== "reasoning" && trace.kind !== "thinking") continue;
    const text = compactLine(trace.text);
    if (!text) continue;
    raw.push({ type: "trace", id: trace.id, at: trace.createdAt || 0, text });
  }

  raw.sort((a, b) => a.at - b.at);

  // Collapse consecutive identical tool calls (same name + context).
  const merged: BreakdownStep[] = [];
  for (const step of raw) {
    const prev = merged[merged.length - 1];
    if (
      step.type === "tool" &&
      prev &&
      prev.type === "tool" &&
      prev.name === step.name &&
      prev.context === step.context
    ) {
      prev.count += 1;
      if (step.status === "error") prev.status = "error";
      else if (step.status === "running" && prev.status !== "error") {
        prev.status = "running";
      }
      continue;
    }
    merged.push({ ...step });
  }
  return merged;
}

/** A single tool/trace line inside the expanded breakdown. */
function BreakdownRow({ step }: { step: BreakdownStep }) {
  if (step.type === "trace") {
    // Reasoning/thinking is the agent narrating its work — show it in full,
    // wrapping, so the user can actually read the thought instead of a
    // one-line ellipsed sliver.
    return (
      <div className="flex items-start gap-2 text-xs leading-5 text-[var(--chat-muted)]">
        <Dot className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-70" />
        <span className="min-w-0 flex-1 whitespace-pre-wrap break-words italic opacity-90">
          {step.text}
        </span>
      </div>
    );
  }

  const Icon = breakdownToolIcon(step.name);
  return (
    <div className="flex items-center gap-2 text-xs leading-5 text-[var(--chat-muted)]">
      <Icon
        className={cn(
          "h-3.5 w-3.5 shrink-0",
          step.status === "error" && "text-[var(--chat-danger)]",
          step.status === "running" && "animate-pulse",
        )}
      />
      <span className="shrink-0 font-mono font-medium">{step.name}</span>
      {step.context && (
        <span className="min-w-0 flex-1 truncate font-mono opacity-80">
          {truncatePreview(step.context)}
        </span>
      )}
      {step.count > 1 && (
        <span className="shrink-0 text-[0.62rem] opacity-70">
          ×{step.count}
        </span>
      )}
    </div>
  );
}

/** A standalone, always-visible row for a memory save. */
function MemorySaveRow({ tool }: { tool: ToolEntry }) {
  const preview = truncatePreview(tool.summary || tool.context, 64);
  return (
    <div className="flex items-center gap-2 text-xs leading-5 text-[var(--chat-muted-strong)]">
      <Brain className="h-3.5 w-3.5 shrink-0 text-[var(--chat-muted-strong)] opacity-90" />
      <span className="min-w-0 flex-1 truncate">
        Saved to memory{preview ? `: ${preview}` : ""}
      </span>
    </div>
  );
}

// Working/worked digest. While a turn streams, the header is the live
// meter: pulsing accent mark + "Working" + elapsed + running token count,
// and the breakdown is expanded by default so reasoning (grey) and tool
// calls scroll in chronologically as they happen. Once the turn completes
// the same header collapses into "Worked for ..." with the real token
// count, and the breakdown defaults to collapsed.
function ChatActivityDigest({
  activityTrace,
  busy,
  liveTokens,
  startedAt,
  tokenCount,
  tools,
}: {
  activityTrace: ActivityTrace[];
  artifacts: ArtifactEntry[];
  busy: boolean;
  liveTokens?: number;
  startedAt?: number;
  tokenCount?: number;
  tools: ToolEntry[];
}) {
  // null = follow the default for the current state (open while busy,
  // collapsed when done). A real boolean = the user toggled it explicitly.
  const [open, setOpen] = useState<boolean | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const steps = useMemo(
    () => buildBreakdownSteps(tools, activityTrace),
    [tools, activityTrace],
  );
  const memoryTools = useMemo(
    () => tools.filter((tool) => tool.name.toLowerCase() === "memory"),
    [tools],
  );

  const show =
    busy ||
    tools.length > 0 ||
    activityTrace.length > 0 ||
    typeof tokenCount === "number";
  if (!show) return null;

  const start = startedAt ?? activityStartedAt(tools, activityTrace);
  const end = busy ? now : activityFinishedAt(tools);
  const duration = formatDuration(Math.max(0, end - start));
  const expanded = open ?? busy;
  const tokens = busy
    ? liveTokens ?? 0
    : typeof tokenCount === "number"
      ? tokenCount
      : 0;

  return (
    <section className="pt-1 text-[var(--chat-muted)]">
      {memoryTools.length > 0 && (
        <div className="mb-3 space-y-1.5">
          {memoryTools.map((tool) => (
            <MemorySaveRow key={tool.id} tool={tool} />
          ))}
        </div>
      )}

      <button
        className="flex items-center gap-2 text-sm text-[var(--chat-muted-strong)] transition-colors hover:text-[var(--chat-text)]"
        onClick={() => setOpen(() => !expanded)}
        type="button"
      >
        {busy && (
          <Sparkle className="h-4 w-4 shrink-0 animate-pulse fill-[var(--chat-accent)] text-[var(--chat-accent)]" />
        )}
        <span>
          {busy ? "Working" : "Worked for"} {duration}
          {!busy && steps.length > 0 && ` · ${plural(steps.length, "step")}`}
          {tokens > 0 ? ` · ${tokens.toLocaleString()} tokens` : ""}
        </span>
        {(busy || steps.length > 0) && (
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 transition-transform",
              expanded && "rotate-180",
            )}
          />
        )}
      </button>

      {expanded && (busy || steps.length > 0) && (
        <div className="mt-3 space-y-1.5">
          {steps.map((step) => (
            <BreakdownRow key={step.id} step={step} />
          ))}
        </div>
      )}
    </section>
  );
}

function ChatArtifactShelf({
  artifacts,
  onOpenArtifact,
}: {
  artifacts: ArtifactEntry[];
  onOpenArtifact(artifact: ArtifactEntry): void;
}) {
  const visible = artifacts.slice(-3).reverse();
  if (!visible.length) return null;

  return (
    <section className="space-y-2">
      {visible.map((artifact) => (
        <InlineArtifactCard
          key={`inline-${artifact.id}`}
          artifact={artifact}
          onOpenArtifact={onOpenArtifact}
        />
      ))}
    </section>
  );
}

function InlineArtifactCard({
  artifact,
  onOpenArtifact,
}: {
  artifact: ArtifactEntry;
  onOpenArtifact(artifact: ArtifactEntry): void;
}) {
  const { copied, copy } = useCopyToClipboard();
  const copyText = artifact.path ?? artifact.content ?? artifact.detail ?? artifact.title;

  return (
    <div className="max-w-[38rem] rounded-md bg-[var(--chat-surface)] p-3 shadow-[inset_0_0_0_1px_var(--chat-border)]">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--chat-surface-soft)] text-[var(--chat-accent)]">
          <FileText className="h-4 w-4" />
        </div>
        <button
          className="min-w-0 flex-1 text-left"
          onClick={() => onOpenArtifact(artifact)}
          type="button"
        >
          <div className="truncate text-sm font-semibold text-[var(--chat-text)]">
            {artifact.title}
          </div>
          <div className="truncate text-xs text-[var(--chat-muted)]">
            {artifact.path || artifact.detail || artifact.source || "Artifact"}
          </div>
        </button>
        <button
          className="rounded-sm border border-[var(--chat-border-strong)] px-3 py-1 text-xs text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={() => onOpenArtifact(artifact)}
          type="button"
        >
          Open
        </button>
        <button
          className="rounded-sm border border-[var(--chat-border-strong)] px-3 py-1 text-xs text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={() => copy(copyText)}
          type="button"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
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

function ArtifactPreviewPane({
  artifact,
  onClose,
}: {
  artifact: ArtifactEntry;
  onClose(): void;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [contentType, setContentType] = useState("");
  const { copied, copy } = useCopyToClipboard();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [textPreview, setTextPreview] = useState<string | null>(
    artifact.content ?? null,
  );
  const copyText = artifact.path ?? artifact.content ?? artifact.detail ?? artifact.title;
  const pathForKind = artifact.path ?? artifact.title;
  const kind = artifact.path ? previewKind(pathForKind, contentType) : "text";

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    setBlobUrl(null);
    setContentType("");
    setError(null);
    setTextPreview(artifact.content ?? null);

    if (!artifact.path) {
      setLoading(false);
      return () => {};
    }

    setLoading(true);
    void api
      .previewFile(artifact.path)
      .then(async (response) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(response.blob);
        const nextKind = previewKind(artifact.path ?? artifact.title, response.contentType);
        setBlobUrl(objectUrl);
        setContentType(response.contentType);
        if (nextKind === "text") {
          const text = await response.blob.text();
          if (!cancelled) setTextPreview(text.slice(0, 250_000));
        }
      })
      .catch((previewError: Error) => {
        if (!cancelled) setError(previewError.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifact]);

  const openExternal = () => {
    if (!blobUrl) return;
    window.open(blobUrl, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="@container flex h-full min-h-0 flex-col overflow-hidden rounded-md bg-[var(--chat-surface)] text-[var(--chat-text)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
      <header className="flex shrink-0 items-start gap-2 px-3 pb-3 pt-3 @[28rem]:gap-3 @[28rem]:px-4 @[28rem]:pt-4">
        <div className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[var(--chat-surface-soft)] text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border)] @[24rem]:flex">
          <FileText className="h-4.5 w-4.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[0.95rem] font-semibold leading-5">
              {artifact.title}
            </h2>
            <span className="hidden shrink-0 rounded-sm bg-[var(--chat-surface-strong)] px-2 py-0.5 text-[0.65rem] text-[var(--chat-muted)] @[22rem]:inline">
              {fileExtension(pathForKind).replace(".", "").toUpperCase() || artifact.kind}
            </span>
          </div>
          <p className="mt-1 truncate text-[0.72rem] leading-4 text-[var(--chat-muted)]">
            {artifact.path || artifact.detail || artifact.source || "Artifact preview"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            aria-label="Open preview externally"
            className="hidden h-7 w-7 rounded-sm p-0 @[20rem]:inline-flex @[24rem]:h-8 @[24rem]:w-8"
            disabled={!blobUrl}
            onClick={openExternal}
            size="sm"
            title="Open"
            type="button"
            variant="outline"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
          <Button
            aria-label="Copy artifact path"
            className="hidden h-7 w-7 rounded-sm p-0 @[20rem]:inline-flex @[24rem]:h-8 @[24rem]:w-8"
            onClick={() => copy(copyText)}
            size="sm"
            title={copied ? "Copied" : "Copy"}
            type="button"
            variant="outline"
          >
            {copied ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <Clipboard className="h-3.5 w-3.5" />
            )}
          </Button>
          <Button
            aria-label={collapsed ? "Expand preview" : "Collapse preview"}
            className="h-7 w-7 rounded-sm p-0 @[24rem]:h-8 @[24rem]:w-8"
            onClick={() => setCollapsed((value) => !value)}
            size="sm"
            title={collapsed ? "Expand" : "Collapse"}
            type="button"
            variant="ghost"
          >
            {collapsed ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronUp className="h-4 w-4" />
            )}
          </Button>
          <Button
            aria-label="Close preview"
            className="h-7 w-7 rounded-sm p-0 @[24rem]:h-8 @[24rem]:w-8"
            onClick={onClose}
            size="sm"
            type="button"
            variant="ghost"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {collapsed ? null : (
      <div className="min-h-0 flex-1 border-t border-[var(--chat-border)] bg-[var(--chat-surface-soft)]">
        {loading ? (
          <div className="flex h-full flex-col gap-3 p-6">
            <div className="h-4 w-2/3 animate-pulse rounded-lg bg-[var(--chat-border)]" />
            <div className="h-4 w-1/2 animate-pulse rounded-lg bg-[var(--chat-border)]" />
            <div className="mt-2 flex-1 animate-pulse rounded-md bg-[var(--chat-border)]" />
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-6">
            <div className="max-w-sm rounded-md bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-4 text-sm text-[var(--chat-danger)] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_34%,transparent)]">
              <div className="font-semibold">Could not preview this file</div>
              <div className="mt-1 break-words text-xs opacity-90">{error}</div>
            </div>
          </div>
        ) : kind === "pdf" && blobUrl ? (
          <div className="relative h-full w-full">
            <iframe
              className="absolute inset-0 h-full w-full bg-[var(--chat-bg)]"
              src={`${blobUrl}#navpanes=0&view=FitH`}
              title={artifact.title}
            />
            <noscript>
              <div className="flex h-full items-center justify-center p-6 text-sm text-[var(--chat-muted)]">
                PDF preview requires a browser with embedded PDF support.
              </div>
            </noscript>
          </div>
        ) : kind === "html" && blobUrl ? (
          <iframe
            className="h-full w-full bg-white"
            sandbox="allow-scripts allow-same-origin"
            src={blobUrl}
            title={artifact.title}
          />
        ) : kind === "image" && blobUrl ? (
          <div className="flex h-full items-center justify-center overflow-auto p-4">
            <img
              alt={artifact.title}
              className="max-h-full max-w-full object-contain"
              src={blobUrl}
            />
          </div>
        ) : kind === "text" && textPreview !== null ? (
          <pre className="h-full overflow-auto p-4 text-[0.76rem] leading-5 text-[var(--chat-muted-strong)] whitespace-pre-wrap">
            {textPreview}
          </pre>
        ) : (
          <div className="flex h-full items-center justify-center p-6">
            <div className="max-w-sm text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md bg-[var(--chat-surface)] text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
                <FileText className="h-5 w-5" />
              </div>
              <div className="mt-3 text-sm font-semibold">
                Preview prepared
              </div>
              <p className="mt-1 text-xs leading-5 text-[var(--chat-muted)]">
                This file type may need a native app. Use Open to launch the
                browser download/viewer, or copy the local path.
              </p>
              <div className="mt-4 flex justify-center gap-2">
                <Button
                  disabled={!blobUrl}
                  onClick={openExternal}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                  Open
                </Button>
                <Button onClick={() => copy(copyText)} size="sm" type="button" variant="outline">
                  {copied ? "Copied" : "Copy path"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  );
}

function ArtifactsSection({
  artifacts,
  onOpenArtifact,
}: {
  artifacts: ArtifactEntry[];
  onOpenArtifact(artifact: ArtifactEntry): void;
}) {
  const grouped = useMemo(() => {
    const byKey = new Map<string, { artifact: ArtifactEntry; count: number }>();
    for (const artifact of artifacts) {
      const dedupeKey = artifact.path || `${artifact.kind}:${artifact.title}`;
      const existing = byKey.get(dedupeKey);
      if (!existing) {
        byKey.set(dedupeKey, { artifact, count: 1 });
        continue;
      }
      existing.count += 1;
      if (artifact.createdAt >= existing.artifact.createdAt) {
        existing.artifact = artifact;
      }
    }
    return Array.from(byKey.values()).sort(
      (a, b) => b.artifact.createdAt - a.artifact.createdAt,
    );
  }, [artifacts]);

  const totalCount = artifacts.length;
  const uniqueCount = grouped.length;
  const hasDuplicates = totalCount > uniqueCount;

  return (
    <section className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="text-[0.82rem] font-medium leading-5 text-[var(--chat-muted-strong)]">
            Artifacts
          </span>
          {uniqueCount > 0 && (
            <span
              className="text-[0.66rem] text-[var(--chat-muted)]"
              title={
                hasDuplicates
                  ? `${uniqueCount} unique · ${totalCount} total writes`
                  : `${uniqueCount} file${uniqueCount === 1 ? "" : "s"}`
              }
            >
              {uniqueCount}
            </span>
          )}
        </div>
        <Pin className="h-3.5 w-3.5 shrink-0 rotate-45 text-[var(--chat-muted)] opacity-70" />
      </div>
      {grouped.length === 0 ? (
        <PortalEmpty>Files and outputs will land here</PortalEmpty>
      ) : (
        <div className="flex max-h-[36vh] flex-col gap-0.5 overflow-y-auto pr-0.5">
          {grouped.map(({ artifact, count }) => (
            <ArtifactCard
              key={artifact.id}
              artifact={artifact}
              count={count}
              onOpenArtifact={onOpenArtifact}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ArtifactCard({
  artifact,
  count = 1,
  onOpenArtifact,
}: {
  artifact: ArtifactEntry;
  count?: number;
  onOpenArtifact(artifact: ArtifactEntry): void;
}) {
  const [open, setOpen] = useState(false);
  const { copied, copy } = useCopyToClipboard();
  const Icon = artifact.kind === "diff" ? FileCode2 : FileText;
  const copyText = artifact.path ?? artifact.content ?? artifact.detail ?? artifact.title;
  const canPreview = Boolean(artifact.path);
  const canToggle = Boolean(artifact.content);

  return (
    <div
      className={cn(
        "group rounded-md text-xs transition-colors hover:bg-[color-mix(in_srgb,var(--chat-surface-strong)_45%,transparent)]",
        artifact.status === "error" &&
          "bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_35%,transparent)]",
      )}
    >
      <div className="flex items-center gap-2 px-1.5 py-1">
        <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--chat-muted-strong)]" />

        <button
          className="min-w-0 flex-1 truncate text-left text-[0.82rem] leading-5 text-[var(--chat-text)]"
          onClick={() => {
            if (canPreview) {
              onOpenArtifact(artifact);
            } else if (canToggle) {
              setOpen((value) => !value);
            }
          }}
          title={count > 1 ? `${artifact.title} · ${count} writes` : artifact.title}
          type="button"
        >
          {artifact.title}
        </button>
        {count > 1 && (
          <span
            className="shrink-0 text-[0.62rem] text-[var(--chat-muted)]"
            aria-label={`${count} writes to this file`}
          >
            ×{count}
          </span>
        )}

        <button
          aria-label="Copy artifact"
          className="rounded-md p-1 text-[var(--chat-muted)] opacity-0 transition hover:bg-[color-mix(in_srgb,var(--chat-surface-strong)_60%,transparent)] hover:text-[var(--chat-text)] group-hover:opacity-70"
          onClick={(event) => {
            event.stopPropagation();
            copy(copyText);
          }}
          type="button"
        >
          {copied ? (
            <CheckCircle2 className="h-3 w-3" />
          ) : (
            <Clipboard className="h-3 w-3" />
          )}
        </button>
      </div>

      {open && artifact.content && (
        <pre className="ml-7 mb-1 mr-1 max-h-48 overflow-auto rounded-md bg-[color-mix(in_srgb,var(--chat-surface-strong)_38%,transparent)] p-2 text-[0.68rem] leading-4 text-[var(--chat-muted-strong)] whitespace-pre-wrap">
          {artifact.content}
        </pre>
      )}
    </div>
  );
}

function ProgressSummaryList({ summaries }: { summaries: ProgressSummary[] }) {
  return (
    <div className="space-y-1">
      {summaries.map((summary) => (
        <ProgressSummaryRow key={summary.id} summary={summary} />
      ))}
    </div>
  );
}

function ProgressSummaryRow({ summary }: { summary: ProgressSummary }) {
  const [open, setOpen] = useState(false);
  const hasDetails = summary.details.length > 0;
  const complete = summary.status === "done";
  const failed = summary.status === "error";
  const running = summary.status === "running";

  return (
    <div className="text-sm leading-6">
      <button
        aria-expanded={open}
        className={cn(
          "group flex w-full items-start gap-3 rounded-md px-1 py-1.5 text-left transition-colors",
          hasDetails && "hover:bg-[color-mix(in_srgb,var(--chat-surface-strong)_45%,transparent)]",
        )}
        disabled={!hasDetails}
        onClick={() => hasDetails && setOpen((value) => !value)}
        type="button"
      >
        <span
          className={cn(
            "mt-1 flex h-[1.05rem] w-[1.05rem] shrink-0 items-center justify-center rounded-full border",
            failed
              ? "border-[color-mix(in_srgb,var(--chat-danger)_70%,transparent)] text-[var(--chat-danger)]"
              : complete
                ? "border-[color-mix(in_srgb,var(--chat-muted-strong)_70%,transparent)] text-[var(--chat-muted-strong)]"
                : running
                  ? "border-[color-mix(in_srgb,var(--chat-muted-strong)_65%,transparent)] text-[var(--chat-muted-strong)]"
                  : "border-[color-mix(in_srgb,var(--chat-muted)_72%,transparent)] text-transparent",
          )}
        >
          {running ? (
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
          ) : failed ? (
            <AlertCircle className="h-2.5 w-2.5" />
          ) : complete ? (
            <CheckCircle2 className="h-2.5 w-2.5" />
          ) : (
            <span className="sr-only">Pending</span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div
            className={cn(
              "text-[0.92rem] font-medium",
              summary.status === "pending"
                ? "text-[var(--chat-muted)]"
                : "text-[var(--chat-muted-strong)]",
            )}
          >
            {summary.label}
          </div>
          {summary.detail && (
            <div className="mt-0.5 truncate text-[0.76rem] text-[var(--chat-muted)]">
              {summary.detail}
            </div>
          )}
        </div>
        {hasDetails && (
          <ChevronDown
            className={cn(
              "mt-1.5 h-3.5 w-3.5 shrink-0 text-[var(--chat-muted)] opacity-70 transition group-hover:opacity-100",
              open && "rotate-180",
            )}
          />
        )}
      </button>
      {open && hasDetails && (
        <div className="ml-8 mt-1 space-y-1 pb-1 text-[0.74rem] leading-5 text-[var(--chat-muted)]">
          {summary.details.map((detail, index) => (
            <div key={`${summary.id}-${index}`} className="truncate">
              {detail}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ActivityPanel({
  activityTrace,
  artifacts,
  banner,
  busy,
  onOpenArtifact,
  onReconnect,
  state,
  statusText,
  tools,
}: {
  activityTrace: ActivityTrace[];
  artifacts: ArtifactEntry[];
  banner: string | null;
  busy: boolean;
  onOpenArtifact(artifact: ArtifactEntry): void;
  onReconnect(): void;
  state: ConnectionState;
  statusText: string;
  tools: ToolEntry[];
}) {
  const progress = useMemo(
    () => buildProgressSummaries({ activityTrace, artifacts, busy, statusText, tools }),
    [activityTrace, artifacts, busy, statusText, tools],
  );

  const hasProgress = progress.length > 0;

  return (
    <div className="flex max-h-full min-h-0 flex-col overflow-hidden rounded-lg border border-[color-mix(in_srgb,var(--chat-border)_72%,transparent)] bg-[color-mix(in_srgb,var(--chat-surface)_98%,var(--chat-bg))] p-3.5 normal-case">
      {banner && (
        <section className="mb-3 rounded-md bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-2.5 shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_35%,transparent)]">
          <div className="flex items-start gap-2 text-[0.8rem] text-[var(--chat-danger)]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="break-words">{banner}</div>
              <button
                className="mt-2 rounded-sm bg-[color-mix(in_srgb,var(--chat-danger)_12%,var(--chat-bg))] px-2.5 py-1 text-[0.7rem] transition-colors hover:bg-[color-mix(in_srgb,var(--chat-danger)_15%,var(--chat-bg))]"
                onClick={onReconnect}
                type="button"
              >
                Reconnect
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-0.5">
        <ArtifactsSection
          artifacts={artifacts}
          onOpenArtifact={onOpenArtifact}
        />

        {hasProgress && (
          <section className="space-y-1.5 border-t border-[color-mix(in_srgb,var(--chat-border)_48%,transparent)] pt-3">
            <div className="flex items-center gap-2 px-1">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  state === "open" ? "bg-[var(--chat-success)]" : "bg-[var(--chat-muted)]",
                )}
              />
              <span className="text-[0.82rem] font-medium leading-5 text-[var(--chat-muted-strong)]">
                Activity
              </span>
              <span className="ml-auto truncate text-[0.68rem] text-[var(--chat-muted)]">
                {state === "open" ? "live" : STATE_LABEL[state]}
              </span>
            </div>
            <ProgressSummaryList summaries={progress} />
          </section>
        )}
      </div>
    </div>
  );
}

function PortalEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="px-1 py-2 text-[0.78rem] leading-5 text-[var(--chat-muted)]">
      {children}
    </div>
  );
}
