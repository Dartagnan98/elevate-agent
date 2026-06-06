import { Markdown } from "@/components/Markdown";
import { ModelPickerDialog } from "@/components/ModelPickerDialog";
import {
  SlashPopover,
  type SlashPopoverHandle,
} from "@/components/SlashPopover";
import type { ToolEntry } from "@/components/ToolCall";
import {
  ArtifactsPanel,
  BackgroundTasksPanel,
  type BackgroundTaskItem,
  EmptyPreviewPanel,
  FilesPanel,
  PlanPanel,
  SidePanelSelector,
  type SidePanelMode,
} from "@/components/ChatSidePanels";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type AgentHubAgent,
  type AnalyticsResponse,
  type SessionMessage as StoredSessionMessage,
  type WorkspaceGitStatus,
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
  Clock,
  Command,
  CornerDownLeft,
  ExternalLink,
  Eye,
  FileCode2,
  FilePen,
  FileText,
  Folder,
  GitBranch,
  Film,
  Image as ImageIcon,
  Loader2,
  Mic,
  MoreHorizontal,
  PanelLeftOpen,
  Paperclip,
  Pin,
  Plug,
  Search,
  Shield,
  ShieldAlert,
  Sparkles,
  Square,
  SquareTerminal,
  Wrench,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import {
  memo,
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
  UIEvent as ReactUIEvent,
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

type StartAnalyticsRange = "all" | "30d" | "7d";

/** A selectable microphone input device. */
interface MicDevice {
  deviceId: string;
  label: string;
}

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
  completedAt?: number;
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
  agentId: string;
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
    const write = () => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(write).catch(() => {
        if (fallbackCopyText(text)) write();
      });
      return;
    }
    if (fallbackCopyText(text)) write();
  }, []);
  return { copied, copy };
}

function fallbackCopyText(text: string): boolean {
  if (typeof document === "undefined") return false;
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
}

const ARTIFACT_LIMIT = 32;
const TOOL_LIMIT = 24;
const PREVIEW_PANEL_MIN_WIDTH = 340;
const PREVIEW_PANEL_CHAT_MIN_WIDTH = 260;

const ARTIFACT_DISMISS_STORAGE_PREFIX = "elevate.chat.artifacts.dismissed.v1:";
const MESSAGE_PIN_STORAGE_KEY = "elevate.chat.messagePins.v1";
const PREVIEW_AUTO_OPEN_DISABLED_STORAGE_PREFIX =
  "elevate.chat.previewAutoOpenDisabled.v1:";
const WORKSPACE_STATUS_STORAGE_KEY = "elevate.chat.workspaceStatus.v1";
const WORKSPACE_STATUS_CACHE_MAX_AGE_MS = 10 * 60 * 1000;

function readCachedWorkspaceStatus(): WorkspaceGitStatus | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(WORKSPACE_STATUS_STORAGE_KEY);
    if (!raw) return null;
    const status = JSON.parse(raw) as WorkspaceGitStatus;
    const checkedAtMs = Number(status.checked_at || 0) * 1000;
    if (!checkedAtMs || Date.now() - checkedAtMs > WORKSPACE_STATUS_CACHE_MAX_AGE_MS) {
      return null;
    }
    return status;
  } catch {
    return null;
  }
}

function writeCachedWorkspaceStatus(status: WorkspaceGitStatus): void {
  if (typeof window === "undefined" || !status.ok) return;
  try {
    window.localStorage.setItem(WORKSPACE_STATUS_STORAGE_KEY, JSON.stringify(status));
  } catch {
    // Non-critical cache for perceived-load speed only.
  }
}

function readPinnedMessageIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(MESSAGE_PIN_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

function writePinnedMessageId(messageId: string, pinned: boolean): void {
  if (typeof window === "undefined") return;
  const ids = readPinnedMessageIds();
  if (pinned) ids.add(messageId);
  else ids.delete(messageId);
  try {
    window.localStorage.setItem(MESSAGE_PIN_STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    // Pinning is a UI convenience; storage failure should not interrupt chat.
  }
}

function readDismissedArtifactKeys(sessionId: string | null | undefined): Set<string> {
  if (typeof window === "undefined" || !sessionId) return new Set();
  try {
    const raw = window.localStorage.getItem(`${ARTIFACT_DISMISS_STORAGE_PREFIX}${sessionId}`);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return new Set(parsed.filter((entry): entry is string => typeof entry === "string"));
  } catch {
    // Ignore malformed local cache.
  }
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
  } catch {
    // Ignore storage quota/private-mode failures.
  }
}

function readPreviewAutoOpenDisabled(sessionId: string | null | undefined): boolean {
  if (typeof window === "undefined" || !sessionId) return false;
  try {
    return window.localStorage.getItem(
      `${PREVIEW_AUTO_OPEN_DISABLED_STORAGE_PREFIX}${sessionId}`,
    ) === "1";
  } catch {
    // Ignore storage/private-mode failures.
  }
  return false;
}

function writePreviewAutoOpenDisabled(
  sessionId: string | null | undefined,
  disabled: boolean,
): void {
  if (typeof window === "undefined" || !sessionId) return;
  try {
    const key = `${PREVIEW_AUTO_OPEN_DISABLED_STORAGE_PREFIX}${sessionId}`;
    if (disabled) {
      window.localStorage.setItem(key, "1");
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Preview close persistence is best-effort.
  }
}

// Artifacts (PDFs, files, outputs) are captured live from tool.complete
// events — which carry full filesystem paths. The persisted transcript
// drops tool messages entirely (shouldKeepTranscriptMessage), so on a
// reload or session switch those paths are gone and the right-side panel
// re-derives nothing from the remaining prose (which often shows only
// bare filenames). Cache the captured artifacts per session so the panel
// survives a reattach instead of going empty.
const ARTIFACT_STORAGE_PREFIX = "elevate.chat.artifacts.v1:";

function readSessionArtifacts(sessionId: string | null | undefined): ArtifactEntry[] {
  if (typeof window === "undefined" || !sessionId) return [];
  try {
    const raw = window.localStorage.getItem(`${ARTIFACT_STORAGE_PREFIX}${sessionId}`);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter(
        (entry): entry is ArtifactEntry =>
          !!entry && typeof entry === "object" &&
          typeof entry.key === "string" && typeof entry.title === "string",
      );
    }
  } catch {
    // Ignore malformed local cache.
  }
  return [];
}

function writeSessionArtifacts(
  sessionId: string | null | undefined,
  artifacts: ArtifactEntry[],
): void {
  if (typeof window === "undefined" || !sessionId) return;
  try {
    if (artifacts.length === 0) {
      window.localStorage.removeItem(`${ARTIFACT_STORAGE_PREFIX}${sessionId}`);
      return;
    }
    window.localStorage.setItem(
      `${ARTIFACT_STORAGE_PREFIX}${sessionId}`,
      JSON.stringify(artifacts.slice(-40)),
    );
  } catch {
    // Ignore storage quota/private-mode failures.
  }
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
  } catch {
    // Ignore malformed local storage.
  }
  return clampPreviewPanelWidth(window.innerWidth * 0.5);
}

// User-resizable chat column width. Returns null when the user hasn't dragged it
// (the responsive default min(1750px,95vw) applies); a number once they have.
const CHAT_WIDTH_MIN = 340;
const CHAT_WIDTH_MAX = 1000;
function clampChatWidth(width: number): number {
  if (typeof window === "undefined") return Math.round(width);
  const max = Math.min(CHAT_WIDTH_MAX, Math.round(window.innerWidth * 0.96));
  return Math.round(Math.min(max, Math.max(CHAT_WIDTH_MIN, width)));
}
function defaultChatWidth(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = localStorage.getItem("elevate-chat-width");
    if (stored) {
      const n = parseInt(stored, 10);
      if (Number.isFinite(n) && n > 0) return clampChatWidth(n);
    }
  } catch {
    // Ignore malformed local storage.
  }
  return null;
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

/* Claude-style tool permission modes. Surfaced in the composer action bar
   and persisted server-side via `config.set permission_mode`. acceptEdits
   and plan currently fall back to manual approvals on the gateway until
   dedicated agent-runtime support lands — the selector still presents them
   so the UX is in place. */
interface PermissionMode {
  id: "default" | "acceptEdits" | "plan" | "bypassPermissions";
  label: string;
  short: string;
  description: string;
  icon: LucideIcon;
  tone: string;
}

const PERMISSION_MODES: PermissionMode[] = [
  {
    id: "default",
    label: "Ask first",
    short: "Ask first",
    description: "Prompt for approval before every risky action.",
    icon: Shield,
    tone: "var(--chat-muted-strong)",
  },
  {
    id: "acceptEdits",
    label: "Accept edits",
    short: "Accept edits",
    description: "Auto-accept file edits, still ask for everything else.",
    icon: FilePen,
    tone: "var(--chat-muted-strong)",
  },
  {
    id: "plan",
    label: "Plan mode",
    short: "Plan mode",
    description: "Read-only — no commands run, planning pass only.",
    icon: Eye,
    tone: "var(--chat-muted-strong)",
  },
  {
    id: "bypassPermissions",
    label: "Bypass permissions",
    short: "Bypass perms",
    description: "Never ask — run every action without approval.",
    icon: ShieldAlert,
    tone: "var(--chat-accent)",
  },
];

const DEFAULT_PERMISSION_MODE = PERMISSION_MODES[0];

function resolvePermissionMode(id: string | undefined | null): PermissionMode {
  return (
    PERMISSION_MODES.find((mode) => mode.id === id) ?? DEFAULT_PERMISSION_MODE
  );
}

const STATE_LABEL: Record<ConnectionState, string> = {
  closed: "closed",
  connecting: "connecting",
  error: "error",
  idle: "idle",
  open: "live",
};

const SESSION_MESSAGE_CACHE = new Map<string, ChatMessage[]>();
const SESSION_MESSAGE_STORAGE_KEY = "elevate.chat.messageCache.v1";
const ACTIVE_TURN_STORAGE_KEY = "elevate.chat.activeTurnCache.v1";
const MAX_CACHED_TRANSCRIPTS = 24;
const MAX_ACTIVE_TURN_SNAPSHOTS = 12;
const MAX_STORED_TRANSCRIPT_MESSAGES = 160;
const MAX_STORED_TRANSCRIPT_CHARS = 220_000;
const MAX_STORED_MESSAGE_CHARS = 16_000;
const ACTIVE_TURN_MAX_AGE_MS = 12 * 60 * 60 * 1000;
let SHARED_CHAT_GATEWAY: GatewayClient | null = null;
let SHARED_CHAT_GATEWAY_VERSION = 0;

interface StoredTranscriptCacheEntry {
  messages: ChatMessage[];
  updatedAt: number;
}

type StoredTranscriptCache = Record<string, StoredTranscriptCacheEntry>;

interface ActiveTurnSnapshot {
  message: ChatMessage;
  tools: ToolEntry[];
  traces: ActivityTrace[];
  updatedAt: number;
}

type ActiveTurnCache = Record<string, ActiveTurnSnapshot>;

function getSharedChatGateway(version: number): GatewayClient {
  if (!SHARED_CHAT_GATEWAY || SHARED_CHAT_GATEWAY_VERSION !== version) {
    SHARED_CHAT_GATEWAY?.close();
    SHARED_CHAT_GATEWAY = new GatewayClient();
    SHARED_CHAT_GATEWAY_VERSION = version;
    // Debug affordance, OFF by default (prod-safe): set
    //   localStorage.__elevate_expose_gw = "1"
    // then reload to expose the live chat gateway on window for event-
    // injection testing (e.g. verifying the compaction banner end-to-end).
    if (typeof window !== "undefined") {
      try {
        if (window.localStorage?.getItem("__elevate_expose_gw") === "1") {
          (window as unknown as { __elevateChatGateway?: GatewayClient }).__elevateChatGateway =
            SHARED_CHAT_GATEWAY;
        }
      } catch {
        /* localStorage unavailable — ignore */
      }
    }
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
  if (clean.startsWith("[CONTEXT COMPACTION")) return false;
  if (role === "system") {
    if (/^⚡\s*loaded skill:/i.test(clean)) return false;
    if (/^session busy\b/i.test(clean)) return false;
  }
  if (role === "user") {
    if (/^\[SYSTEM:/.test(clean)) {
      // Skill invocations pass through — collapseSkillInvocation handles them
      if (/^\[SYSTEM: (?:The user |The ")/.test(clean)) return true;
      return false;
    }
    if (clean.startsWith("[System note:")) return false;
    if (clean.startsWith("You've reached the maximum number of tool-calling iterations")) return false;
    if (clean.startsWith("[Elevation Hub interface context]")) return false;
    if (clean.startsWith("User follow-up received while you were already working:")) return false;
  }
  return true;
}

function hasActivitySnapshot(message: Partial<ChatMessage>): boolean {
  return (
    message.role === "assistant" &&
    (message.status === "streaming" ||
      !!message.tools?.length ||
      !!message.traces?.length ||
      typeof message.tokenCount === "number")
  );
}

function shouldCacheTranscriptMessage(message: ChatMessage): boolean {
  return (
    shouldKeepTranscriptMessage(message.role, message.content) ||
    hasActivitySnapshot(message)
  );
}

// A skill slash command (/cma-audit) injects the entire SKILL.md as the
// user turn so the model has full context. That payload must never render
// verbatim in the transcript. The first line of the turn is always the
// activation note built by agent/skill_commands.py:_build_skill_message —
// detect it and collapse the whole turn to the `/command` chip the user
// actually typed. Display-only: the model still has the full turn in
// gateway history.
const SKILL_INVOCATION_RE =
  /^\[SYSTEM: (?:The user (?:has invoked|launched this CLI session with) the "([^"]+)" skill|The "([^"]+)" skill is auto-loaded)/;

function collapseSkillInvocation(role: ChatRole, content: string): string {
  if (role !== "user") return content;
  const match = content.match(SKILL_INVOCATION_RE);
  if (!match) return content;
  return `/${match[1] || match[2]}`;
}

function normalizeTranscript(messages?: GatewayTranscriptMessage[]): ChatMessage[] {
  return (messages ?? [])
    .filter((m) =>
      shouldKeepTranscriptMessage(m.role, String(m.text ?? m.context ?? "")),
    )
    .map((m, index) => ({
      content: collapseSkillInvocation(
        m.role,
        String(m.text ?? m.context ?? ""),
      ),
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

function eventMillis(ev: GatewayEvent, fallback = Date.now()): number {
  if (typeof ev.ts === "number") {
    return timestampMillis(ev.ts, fallback);
  }
  return timestampMillis(compactToolPayload(ev.payload).ts, fallback);
}

function normalizeStoredTranscript(messages?: StoredSessionMessage[]): ChatMessage[] {
  const list = messages ?? [];
  const total = list.length;

  // Pair each tool call with its result message (for summary + completion time).
  const toolResults = new Map<string, StoredSessionMessage>();
  list.forEach((m) => {
    if (m.role === "tool" && m.tool_call_id) toolResults.set(m.tool_call_id, m);
  });

  const cut = (v?: string | null): string | undefined =>
    typeof v === "string" ? (v.length > 300 ? `${v.slice(0, 300)}…` : v) : undefined;

  const out: ChatMessage[] = [];
  // Buffer tool calls (incl. those on empty-content assistant turns that the
  // transcript filter drops) and attach them to the next kept assistant turn —
  // so the tool-call dropdown rebuilds from the saved record and shows even
  // when the localStorage snapshot is gone (cache wipe / fresh install).
  let pendingTools: ToolEntry[] = [];

  list.forEach((m, index) => {
    const createdAt = timestampMillis(
      m.timestamp,
      Date.now() - Math.max(0, total - index),
    );

    if (m.role === "assistant" && m.tool_calls?.length) {
      m.tool_calls.forEach((call, ci) => {
        const result = call.id ? toolResults.get(call.id) : undefined;
        pendingTools.push({
          kind: "tool",
          id: call.id || `stored-${index}-${ci}`,
          tool_id: call.id || "",
          name: call.function?.name || result?.tool_name || "tool",
          context: cut(call.function?.arguments),
          summary: cut(typeof result?.content === "string" ? result.content : null),
          status: "done",
          startedAt: createdAt,
          completedAt: result ? timestampMillis(result.timestamp, createdAt) : createdAt,
        });
      });
    }

    if (
      !shouldKeepTranscriptMessage(
        m.role,
        typeof m.content === "string" ? m.content : "",
      )
    ) {
      return; // dropped (tool results, empty turns) — tool calls already buffered
    }

    const messageId = id(`stored-${index}`);
    const chat: ChatMessage = {
      content: collapseSkillInvocation(
        m.role,
        typeof m.content === "string" ? m.content : "",
      ),
      createdAt,
      id: messageId,
      role: m.role,
      status: "complete" as const,
      title: m.tool_name,
    };
    // Surface the persisted per-turn token count on the assistant turn so the
    // usage badge rebuilds from the saved record (survives cache wipe / fresh
    // install), not just from the live streaming snapshot.
    if (m.role === "assistant" && typeof m.token_count === "number") {
      chat.tokenCount = m.token_count;
    }
    if (m.role === "assistant" && pendingTools.length) {
      chat.tools = pendingTools.map((t) => ({ ...t, messageId }));
      pendingTools = [];
    }
    out.push(chat);
  });

  // Trailing tool calls with no assistant turn after them → attach to the last
  // assistant message so they aren't lost.
  if (pendingTools.length) {
    for (let i = out.length - 1; i >= 0; i -= 1) {
      if (out[i].role === "assistant") {
        const mid = out[i].id;
        out[i] = {
          ...out[i],
          tools: [
            ...(out[i].tools ?? []),
            ...pendingTools.map((t) => ({ ...t, messageId: mid })),
          ],
        };
        break;
      }
    }
  }

  return out;
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
    const tools = Array.isArray(entry.tools) ? entry.tools : undefined;
    const traces = Array.isArray(entry.traces) ? entry.traces : undefined;
    const hasCachedActivity =
      role === "assistant" &&
      (entry.status === "streaming" ||
        !!tools?.length ||
        !!traces?.length ||
        typeof entry.tokenCount === "number");
    if (
      role !== "assistant" &&
      role !== "system" &&
      role !== "tool" &&
      role !== "user"
    ) {
      return;
    }
    if (!shouldKeepTranscriptMessage(role, content) && !hasCachedActivity) return;
    normalized.push({
      content: collapseSkillInvocation(role, content),
      completedAt:
        typeof entry.completedAt === "number" && Number.isFinite(entry.completedAt)
          ? timestampMillis(entry.completedAt, Date.now() - index)
          : undefined,
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
      tools,
      traces,
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

function readActiveTurnCache(): ActiveTurnCache {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(ACTIVE_TURN_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as ActiveTurnCache
      : {};
  } catch {
    return {};
  }
}

function normalizeActiveTurnSnapshot(raw: unknown): ActiveTurnSnapshot | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const entry = raw as Partial<ActiveTurnSnapshot>;
  const updatedAt =
    typeof entry.updatedAt === "number" && Number.isFinite(entry.updatedAt)
      ? entry.updatedAt
      : 0;
  if (!updatedAt || Date.now() - updatedAt > ACTIVE_TURN_MAX_AGE_MS) return null;

  const message = normalizeCachedTranscript([entry.message])?.[0];
  if (!message || message.role !== "assistant") return null;

  const messageId = message.id;
  const tools = (Array.isArray(entry.tools) ? entry.tools : [])
    .filter((tool): tool is ToolEntry =>
      !!tool &&
      typeof tool === "object" &&
      typeof tool.name === "string" &&
      typeof tool.tool_id === "string",
    )
    .slice(-TOOL_LIMIT)
    .map((tool) => ({ ...tool, messageId: tool.messageId ?? messageId }));
  const traces = (Array.isArray(entry.traces) ? entry.traces : [])
    .filter((trace): trace is ActivityTrace =>
      !!trace &&
      typeof trace === "object" &&
      typeof trace.id === "string" &&
      typeof trace.text === "string" &&
      (trace.kind === "reasoning" ||
        trace.kind === "status" ||
        trace.kind === "thinking"),
    )
    .slice(-80)
    .map((trace) => ({ ...trace, messageId: trace.messageId ?? messageId }));

  return {
    message: {
      ...message,
      status: "streaming",
      tools: tools.length ? tools : message.tools,
      traces: traces.length ? traces : message.traces,
    },
    tools,
    traces,
    updatedAt,
  };
}

function readActiveTurnSnapshot(sessionId: string | null | undefined): ActiveTurnSnapshot | null {
  if (!sessionId) return null;
  return normalizeActiveTurnSnapshot(readActiveTurnCache()[sessionId]);
}

function writeActiveTurnSnapshot(
  sessionId: string | null | undefined,
  message: ChatMessage,
  tools: ToolEntry[],
  traces: ActivityTrace[],
): void {
  if (typeof window === "undefined" || !sessionId || message.role !== "assistant") return;
  const messageId = message.id;
  const turnTools = tools
    .filter((tool) => !tool.messageId || tool.messageId === messageId)
    .map((tool) => ({ ...tool, messageId }));
  const turnTraces = traces
    .filter((trace) => !trace.messageId || trace.messageId === messageId)
    .map((trace) => ({ ...trace, messageId }));
  const snapshot: ActiveTurnSnapshot = {
    message: {
      ...message,
      completedAt: undefined,
      status: "streaming",
      tools: slimToolsForStorage(turnTools),
      traces: slimTracesForStorage(turnTraces),
    },
    tools: slimToolsForStorage(turnTools) ?? [],
    traces: slimTracesForStorage(turnTraces) ?? [],
    updatedAt: Date.now(),
  };

  const cache = readActiveTurnCache();
  cache[sessionId] = snapshot;
  const entries = Object.entries(cache)
    .filter(([, entry]) => normalizeActiveTurnSnapshot(entry) !== null)
    .sort(([, a], [, b]) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, MAX_ACTIVE_TURN_SNAPSHOTS);
  try {
    window.localStorage.setItem(
      ACTIVE_TURN_STORAGE_KEY,
      JSON.stringify(Object.fromEntries(entries)),
    );
  } catch {
    // Active-turn restore is best-effort. The server replay remains canonical.
  }
}

function clearActiveTurnSnapshot(sessionId: string | null | undefined): void {
  if (typeof window === "undefined" || !sessionId) return;
  const cache = readActiveTurnCache();
  if (!(sessionId in cache)) return;
  delete cache[sessionId];
  try {
    if (Object.keys(cache).length) {
      window.localStorage.setItem(ACTIVE_TURN_STORAGE_KEY, JSON.stringify(cache));
    } else {
      window.localStorage.removeItem(ACTIVE_TURN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures.
  }
}

function activeAssistantMessage(messages: ChatMessage[], preferredId?: string | null): ChatMessage | null {
  if (preferredId) {
    const preferred = messages.find(
      (message) =>
        message.id === preferredId &&
        message.role === "assistant" &&
        message.status === "streaming",
    );
    if (preferred) return preferred;
  }
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role === "assistant" && message.status === "streaming") {
      return message;
    }
  }
  return null;
}

function mergeActiveTurnSnapshot(
  messages: ChatMessage[],
  snapshot: ActiveTurnSnapshot | null,
): ChatMessage[] {
  if (!snapshot) return messages;
  const active = snapshot.message;
  const mergedActive: ChatMessage = {
    ...active,
    status: "streaming",
    tools: snapshot.tools.length ? snapshot.tools : active.tools,
    traces: snapshot.traces.length ? snapshot.traces : active.traces,
  };

  const exactIndex = messages.findIndex((message) => message.id === active.id);
  if (exactIndex >= 0) {
    const next = messages.slice();
    const existing = next[exactIndex];
    next[exactIndex] = {
      ...existing,
      ...mergedActive,
      content: mergedActive.content || existing.content,
      createdAt: Math.min(existing.createdAt, mergedActive.createdAt),
      status: "streaming",
      tools: mergedActive.tools ?? existing.tools,
      traces: mergedActive.traces ?? existing.traces,
    };
    return next;
  }

  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "assistant" || message.status !== "streaming") continue;
    const next = messages.slice();
    next[i] = {
      ...message,
      ...mergedActive,
      content: mergedActive.content || message.content,
      createdAt: Math.min(message.createdAt, mergedActive.createdAt),
      status: "streaming",
      tools: mergedActive.tools ?? message.tools,
      traces: mergedActive.traces ?? message.traces,
    };
    return next;
  }

  return [...messages, mergedActive];
}

function trimTranscriptForStorage(messages: ChatMessage[]): ChatMessage[] {
  let used = 0;
  const trimmed: ChatMessage[] = [];
  for (const message of messages.slice(-MAX_STORED_TRANSCRIPT_MESSAGES).reverse()) {
    if (!shouldCacheTranscriptMessage(message)) continue;
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
    } catch {
      // Cache persistence is best-effort.
    }
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
  const cacheableMessages = messages.filter(shouldCacheTranscriptMessage);
  if (!cacheableMessages.length) return;
  SESSION_MESSAGE_CACHE.delete(sessionId);
  SESSION_MESSAGE_CACHE.set(sessionId, cacheableMessages);
  while (SESSION_MESSAGE_CACHE.size > MAX_CACHED_TRANSCRIPTS) {
    const oldest = SESSION_MESSAGE_CACHE.keys().next().value;
    if (!oldest) break;
    SESSION_MESSAGE_CACHE.delete(oldest);
  }
  writeStoredTranscript(sessionId, cacheableMessages);
}

function attachLiveActivitySnapshots(
  messages: ChatMessage[],
  tools: ToolEntry[],
  traces: ActivityTrace[],
): ChatMessage[] {
  if (!messages.length || (!tools.length && !traces.length)) return messages;

  const toolsByMessage = new Map<string, ToolEntry[]>();
  for (const tool of tools) {
    if (!tool.messageId) continue;
    const list = toolsByMessage.get(tool.messageId) ?? [];
    list.push(tool);
    toolsByMessage.set(tool.messageId, list);
  }

  const tracesByMessage = new Map<string, ActivityTrace[]>();
  for (const trace of traces) {
    if (!trace.messageId) continue;
    const list = tracesByMessage.get(trace.messageId) ?? [];
    list.push(trace);
    tracesByMessage.set(trace.messageId, list);
  }

  if (!toolsByMessage.size && !tracesByMessage.size) return messages;

  let changed = false;
  const next = messages.map((message) => {
    if (message.role !== "assistant") return message;
    const messageTools = toolsByMessage.get(message.id);
    const messageTraces = tracesByMessage.get(message.id);
    if (!messageTools?.length && !messageTraces?.length) return message;
    changed = true;
    return {
      ...message,
      tools: messageTools?.length ? messageTools : message.tools,
      traces: messageTraces?.length ? messageTraces : message.traces,
    };
  });

  return changed ? next : messages;
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
  // Fingerprint is whitespace-normalized: live-cached content vs
  // server-rehydrated content can diverge by trailing newlines or
  // doubled whitespace, and a raw slice(0,200) makes those two
  // versions of the same message hash differently — which then sends
  // the cached copy down the tail-walk path and renders the Q+A
  // doubled in the chat panel.
  const fp = (m: ChatMessage) => {
    const c = (m.content ?? "").trim().replace(/\s+/g, " ").slice(0, 200);
    return `${m.role}:${c}`;
  };
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
      typeof next.completedAt === "number" ||
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
        completedAt: match.completedAt,
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

  // Safety net: even with the normalized fingerprint, dedupe the final
  // array by fingerprint. If two messages still collide (e.g. the same
  // assistant turn lives in both server and tail because of an
  // unforeseen format quirk), keep the first (server/enriched) copy and
  // drop the second so the chat panel never renders a Q+A twice.
  const merged = tail.length ? [...enriched, ...tail] : enriched;
  if (merged.length < 2) return merged;
  const seen = new Set<string>();
  const out: ChatMessage[] = [];
  for (const m of merged) {
    const key = fp(m);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(m);
  }
  blankTraceIfDropped(cached, out, fp, serverMessages.length);
  return out;
}

// Debug tracer: forwarded to the gateway (debug.trace -> blank-trace.log) and
// the console. Set window.__elevateBlankTraceSink from the component.
function blankTrace(message: string, data: Record<string, unknown>): void {
  try {
    // eslint-disable-next-line no-console
    console.error("[BLANK-TRACE]", message, data);
    (window as unknown as {
      __elevateBlankTraceSink?: (m: string, d: Record<string, unknown>) => void;
    }).__elevateBlankTraceSink?.(message, data);
  } catch {
    /* tracing must never break the app */
  }
}

// Flags when a substantial assistant message present in `cached` is absent from
// the merge output `out` — i.e. the merge erased a rendered answer.
function blankTraceIfDropped(
  cached: ChatMessage[] | null,
  out: ChatMessage[],
  fp: (m: ChatMessage) => string,
  serverLen: number,
): void {
  try {
    const big = (m: ChatMessage) =>
      m.role === "assistant" && (m.content ?? "").replace(/\s+/g, "").length > 80;
    const outFps = new Set(out.map(fp));
    const dropped = (cached ?? []).filter((m) => big(m) && !outFps.has(fp(m)));
    if (dropped.length) {
      blankTrace("merge dropped a rendered assistant answer", {
        serverLen,
        cachedLen: (cached ?? []).length,
        outLen: out.length,
        droppedLens: dropped.map((m) => (m.content ?? "").length),
        stack: new Error().stack?.split("\n").slice(2, 7).join(" | "),
      });
    }
  } catch {
    /* never break merge */
  }
}

// Detect whether the cached transcript ends with a user message that has no
// following assistant reply — the telltale sign that a turn was in flight
// when the user refreshed.
function hasPendingTurn(messages: ChatMessage[]): boolean {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant") return msg.status === "streaming";
    if (msg.role === "user") return true;
  }
  return false;
}

function markStreamingTurnsInterrupted(
  messages: ChatMessage[],
  completedAt = Date.now(),
): ChatMessage[] {
  let changed = false;
  const next = messages.map((message) => {
    if (message.role !== "assistant" || message.status !== "streaming") {
      return message;
    }
    changed = true;
    return {
      ...message,
      completedAt: message.completedAt ?? completedAt,
      status: "interrupted" as const,
    };
  });
  return changed ? next : messages;
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
      agentId: typeof e.agentId === "string" ? e.agentId : "",
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
  } catch {
    // Queue persistence is best-effort.
  }
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

const ROTATING_VERBS = [
  "checking",
  "planning",
  "reading",
  "reasoning",
  "reviewing",
  "verifying",
];

function isGenericActivityText(text: string): boolean {
  const clean = displayStatusText(text).trim().toLowerCase();
  if (clean === "") return true;
  if (
    clean === "working..." ||
    clean === "thinking..." ||
    clean === "reasoning..." ||
    clean === "running..." ||
    clean === "ready" ||
    clean === "done"
  ) {
    return true;
  }
  // Transient watchdog heartbeats — fine on the live status line, but
  // they should never pile up as permanent rows in the Activity panel.
  if (clean.startsWith("sending request") || clean.startsWith("still working")) {
    return true;
  }
  // "ruminating", "ruminating...", "ruminating." — same story.
  const stripped = clean.replace(/[.…!?]+$/, "").trim();
  if (ROTATING_VERBS.includes(stripped)) return true;
  return false;
}

// Transient-noise check for REASONING traces. Unlike isGenericActivityText it
// does NOT run displayStatusText, which collapses any text containing
// "thinking"/"reasoning"/"computing"/"pondering" into "Working..." — that
// shreds real reasoning prose (which constantly uses those words) into
// sentence-start fragments. This only drops true noise: empties, fixed status
// strings, heartbeats, rotating verbs, and lone single-word status pills
// ("mulling…", "synthesizing…", "deliberating…"). Real reasoning is prose, so
// it always has multiple words and survives.
function isTransientStatus(text: string): boolean {
  const clean = text.replace(/\s+/g, " ").trim().toLowerCase();
  if (!clean) return true;
  if (
    clean === "working..." ||
    clean === "thinking..." ||
    clean === "reasoning..." ||
    clean === "running..." ||
    clean === "ready" ||
    clean === "done"
  ) {
    return true;
  }
  if (clean.startsWith("sending request") || clean.startsWith("still working")) {
    return true;
  }
  const stripped = clean.replace(/[.…!?]+$/, "").trim();
  if (ROTATING_VERBS.includes(stripped)) return true;
  // A single status word ("mulling…", "synthesizing…") — but only when it
  // stands alone as a whole trace (real reasoning is multi-word prose).
  if (/^\p{L}+$/u.test(stripped) && stripped.length <= 24) return true;
  // Same, but with a leading kaomoji/emoticon ("(｡•́‿•̀｡) reasoning…",
  // "(͡° ͜ʖ ͡°) synthesizing…", "٩(๑˃̵ᴗ˂̵)۶ reasoning…"). The decoration has no
  // ASCII letters, so stripping leading non-letters lands on the lone status
  // verb. Real prose starts with a word, so the strip stops immediately and it
  // stays multi-word — never matched here.
  const deco = stripped.replace(/^[^a-z]+/i, "").trim();
  if (deco !== stripped && /^[a-z]+$/i.test(deco) && deco.length <= 24) return true;
  return false;
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
  busy,
  statusText,
  tools,
}: {
  // artifacts intentionally no longer surfaced in the Activity card
  artifacts?: ArtifactEntry[];
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

  // NOTE: We intentionally do NOT mirror activityTrace items as standalone
  // rows here. Those traces are heartbeats from the agent loop ("ruminating",
  // "mulling", etc.) — they belong on the single live rotating pill at the
  // bottom of the panel, not stacked as a timeline.

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

  // Artifacts are intentionally NOT surfaced in the Activity card anymore —
  // no "Prepare outputs / N ARTIFACTS" section. (Removed per request.)

  real.sort((a, b) => (a.at ?? 0) - (b.at ?? 0));

  // The live "current" line and the pending checklist always sit at the
  // bottom — they are what's happening right now and what's still to come.
  const tail: ProgressSummary[] = [];
  // Always show exactly ONE live pill while busy. The label here is just a
  // fallback — the row renderer swaps in <RotatingPhrase /> for id="current",
  // so this string is never actually displayed.
  if (busy) {
    const currentLabel = progressIntentLabel(statusText || "") || "Working";
    if (
      !real.some(
        (item) => item.label.toLowerCase() === currentLabel.toLowerCase(),
      )
    ) {
      addProgressSummary(tail, {
        details: [],
        id: "current",
        label: currentLabel,
        status: "running",
      });
    }
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

function formatCompactNumber(value: number | null | undefined): string {
  const n = Math.max(0, Number(value ?? 0));
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}K`;
  return n.toLocaleString();
}

function formatPersonName(email: string | null | undefined): string {
  if (!email) return "there";
  const raw = email.split("@")[0]?.split(/[._-]/)[0] || "";
  if (!raw) return "there";
  return raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
}

function dayKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

const DAY_MS = 86_400_000;

function parseAnalyticsDay(key: string): Date {
  return new Date(`${key}T12:00:00`);
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function formatAnalyticsDay(key: string): string {
  return parseAnalyticsDay(key).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatAnalyticsDayShort(key: string): string {
  return parseAnalyticsDay(key).toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });
}

function analyticsRangeLabel(range: StartAnalyticsRange): string {
  if (range === "7d") return "Last 7 days";
  if (range === "30d") return "Last 30 days";
  return "All time";
}

function dailyTokenTotal(day: AnalyticsResponse["daily"][number]): number {
  return Math.max(
    0,
    (day.input_tokens ?? 0) +
      (day.output_tokens ?? 0) +
      (day.cache_read_tokens ?? 0) +
      (day.reasoning_tokens ?? 0),
  );
}

function activeDayCount(analytics: AnalyticsResponse | null): number {
  if (!analytics) return 0;
  return analytics.daily.filter((day) => day.sessions > 0 || day.input_tokens + day.output_tokens > 0).length;
}

function longestActivityStreak(analytics: AnalyticsResponse | null): number {
  if (!analytics) return 0;
  const active = new Set(
    analytics.daily
      .filter((day) => day.sessions > 0 || day.input_tokens + day.output_tokens > 0)
      .map((day) => day.day),
  );
  let best = 0;
  let current = 0;
  for (const day of analytics.daily) {
    if (active.has(day.day)) {
      current += 1;
      best = Math.max(best, current);
    } else {
      current = 0;
    }
  }
  return best;
}

function currentActivityStreak(analytics: AnalyticsResponse | null): number {
  if (!analytics) return 0;
  const active = new Set(
    analytics.daily
      .filter((day) => day.sessions > 0 || day.input_tokens + day.output_tokens > 0)
      .map((day) => day.day),
  );
  let count = 0;
  const cursor = new Date();
  for (let i = 0; i < 365; i += 1) {
    const key = dayKey(cursor);
    if (!active.has(key)) break;
    count += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  return count;
}

function favoriteModel(analytics: AnalyticsResponse | null): string {
  const model = analytics?.by_model?.[0]?.model;
  if (!model) return "pending";
  return model.split("/").slice(-1)[0] || model;
}

function usageHeatmapDays(
  analytics: AnalyticsResponse | null,
  range: StartAnalyticsRange,
): Array<{
  apiCalls: number;
  key: string;
  level: number;
  sessions: number;
  tip: string;
  tokens: number;
}> {
  const byDay = new Map(
    (analytics?.daily ?? []).map((day) => [day.day, day]),
  );
  const maxTokens = Math.max(1, ...Array.from(byDay.values()).map(dailyTokenTotal));
  const days: Array<{
    apiCalls: number;
    key: string;
    level: number;
    sessions: number;
    tip: string;
    tokens: number;
  }> = [];
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const sortedDays = analytics?.daily ?? [];
  let count = range === "7d" ? 7 : range === "30d" ? 30 : 30;
  let cursor = addDays(today, -(count - 1));
  if (range === "all" && sortedDays.length > 0) {
    const first = parseAnalyticsDay(sortedDays[0].day);
    const last = parseAnalyticsDay(sortedDays[sortedDays.length - 1].day);
    const totalDays = Math.max(1, Math.round((last.getTime() - first.getTime()) / DAY_MS) + 1);
    count = Math.min(91, totalDays);
    cursor = addDays(last, -(count - 1));
  }
  const rangeText = analyticsRangeLabel(range).toLowerCase();
  for (let i = 0; i < count; i += 1) {
    const key = dayKey(cursor);
    const entry = byDay.get(key);
    const tokens = entry ? dailyTokenTotal(entry) : 0;
    const sessions = entry?.sessions ?? 0;
    const apiCalls = entry?.api_calls ?? 0;
    const level = tokens === 0 ? 0 : Math.max(1, Math.min(5, Math.ceil((tokens / maxTokens) * 5)));
    const tip = [
      `${formatAnalyticsDay(key)} · ${rangeText}`,
      `${formatCompactNumber(tokens)} tokens`,
      `${formatCompactNumber(sessions)} sessions · ${formatCompactNumber(apiCalls)} calls`,
    ].join("\n");
    days.push({ apiCalls, key, level, sessions, tip, tokens });
    cursor = addDays(cursor, 1);
  }
  return days;
}

function heatmapWindowLabel(
  analytics: AnalyticsResponse | null,
  range: StartAnalyticsRange,
  days: Array<{ key: string }>,
): string {
  if (!analytics || days.length === 0) return `${analyticsRangeLabel(range)} · loading`;
  const first = days[0].key;
  const last = days[days.length - 1].key;
  const visibleRange = `${formatAnalyticsDayShort(first)}-${formatAnalyticsDayShort(last)}`;
  if (range !== "all") return `${analyticsRangeLabel(range)} · ${visibleRange}`;
  const dataFirst = analytics.daily[0]?.day;
  const dataLast = analytics.daily[analytics.daily.length - 1]?.day;
  if (!dataFirst || !dataLast) return `All time · ${visibleRange}`;
  if (dataFirst !== first) {
    return `All time · ${formatAnalyticsDayShort(dataFirst)}-${formatAnalyticsDayShort(dataLast)} · heatmap recent ${days.length}d`;
  }
  return `All time · ${formatAnalyticsDayShort(dataFirst)}-${formatAnalyticsDayShort(dataLast)}`;
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
  "[Elevation Hub interface context]",
  "The user is typing inside Elevation Agent Hub web chat.",
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

function routePromptForAgent(text: string): string {
  // The active agent lane is now applied server-side via the agent_id
  // param on prompt.submit, so the prompt itself only carries the Hub
  // interface context. No per-agent prompt prefix is injected here.
  return [HUB_INTERFACE_CONTEXT, `User request: ${text}`].join("\n\n");
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

/** Whether this runtime can capture the microphone via MediaRecorder.
 *
 * The Electron webview does not support the Web Speech API, so voice input
 * is done by recording the mic locally and shipping the audio to the gateway
 * for server-side transcription. */
function voiceCaptureSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    typeof window.MediaRecorder === "function"
  );
}

/** Best MediaRecorder container the current browser can encode. */
function pickAudioMimeType(): string {
  if (typeof window === "undefined" || typeof window.MediaRecorder !== "function") {
    return "";
  }
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const type of candidates) {
    if (window.MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
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

// Natural-language "make a plan" detection — when the user asks for a plan we
// auto-switch the session into plan mode (flip the pill) so the agent researches
// read-only and presents a plan, no manual toggle needed.
function looksLikePlanRequest(text: string): boolean {
  const t = text.toLowerCase().trim();
  if (/^plan\b/.test(t)) return true;
  if (
    /\b(make|create|draft|write|build|outline|propose|sketch|prepare|put together|come up with|give me|lay out|map out|work out)\s+(me\s+)?(a|an|the|your|out)?\s*plan\b/.test(
      t,
    )
  )
    return true;
  if (/\bplan\s+(out\b|how\b|for\s+how\b|this\b|it\b|the\s+(steps|approach|rollout|build|work|project))/.test(t))
    return true;
  if (/\b(a|the|your)\s+plan\b[\s\S]*\b(before|first|for\s+approval|to\s+review)\b/.test(t))
    return true;
  return false;
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

// Set once per full page load (app launch / reload). Lets us force a fresh
// draft chat on startup without interfering with later in-app navigation
// (sidebar clicks to resume a chat happen after this has already fired).
let forcedNewChatThisLoad = false;

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const resumeId = searchParams.get("resume");
  const newChatId = searchParams.get("new");
  const seedKey = searchParams.get("seed");
  const draftChat = Boolean(newChatId && !resumeId && !seedKey);
  const seededRef = useRef(false);
  // Auto-resume gate. When the user lands on /chat with no ?resume= and no
  // ?new=, we look up the most-recent TUI session and redirect with
  // ?resume=<id> instead of minting a fresh session. The bootstrap effect
  // waits on this gate so it doesn't mint a session before the redirect
  // lands. Initialized to true when the URL already disambiguates (resume
  // or new) — no probe needed there.
  const [autoResumeDecided, setAutoResumeDecided] = useState(
    // On the very first mount of a fresh page load, keep the gate closed so the
    // startup effect can force a new draft chat (even if the URL still carries a
    // ?resume= from before the reload). After that, the URL disambiguates.
    () => (forcedNewChatThisLoad ? Boolean(resumeId || newChatId) : false),
  );
  const [version, setVersion] = useState(0);
  // The chat key (resume/new/seed) that the currently-displayed messages were
  // loaded under. Used to tell a same-chat re-run (reconnect / liveness
  // watchdog -> version bump) apart from genuinely entering a different chat,
  // so the connect effect never wipes a conversation it just rendered.
  const renderedChatKeyRef = useRef<string | null>(null);
  // True for a short window after a liveness-watchdog / manual reconnect bumps
  // `version`. A reconnect re-runs the connect effect to RESTORE the in-flight
  // turn, so any populated-list -> empty during that window is the spurious
  // wipe (the render-then-vanish blank) and is blocked in the setter below.
  const reconnectRunRef = useRef(false);
  // Compaction guard. Context compaction rotates the session_id mid-turn (the
  // continuation session's stored transcript is the COMPRESSED/shorter list —
  // for the model, not the screen). The connect-effect re-runs under the new
  // resumeId and can wipe the displayed transcript to empty (a real LIST WIPE
  // with a live session id, so the fresh-mount guard misses it). This window
  // opens when "Compacting context…" fires and stays open a few seconds past
  // resume to cover the rotation re-hydrate; the wrapped setter blocks any
  // populated-list -> empty wipe while it's open. See docs/freeze-diagnosis.md.
  const compactionGuardRef = useRef(false);
  const compactionGuardTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  // Mint guard. When a draft chat's first message mints a real session,
  // pinCreatedSessionInUrl rewrites the URL to ?resume=<mintedId>, which re-runs
  // the connect effect under the new id — and that re-run can wipe the just-sent
  // user message + streaming reply to empty before renderedChatKeyRef catches up
  // to the minted id (a real LIST WIPE with a live session id, prevCount ~2).
  // Open while the mint settles; the wrapped setter blocks populated -> empty.
  const mintGuardRef = useRef(false);
  const mintGuardTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The invariant behind every blank fix: a populated transcript clears to
  // empty ONLY for a deliberate new chat (URL carries ?new=). Synced during
  // render (not an effect) so it is correct before the connect effect or any
  // event handler runs in the same commit. The wrapped setter below blocks any
  // populated -> empty wipe whenever this is false — covering resume re-hydrate,
  // draft->session mint, compaction rotation, and reconnect re-runs in one rule.
  const newChatPresentRef = useRef(false);
  newChatPresentRef.current = Boolean(newChatId);
  const gw = useMemo(
    () => getSharedChatGateway(version),
    [version],
  );

  const [state, setState] = useState<ConnectionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const activeSessionRef = useRef<string | null>(null);
  const currentAssistantRef = useRef<string | null>(null);
  const stoppedAssistantIdsRef = useRef<Set<string>>(new Set());
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const commandPopoverRef = useRef<SlashPopoverHandle | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const voiceBaseInputRef = useRef("");
  const createSessionPromiseRef = useRef<Promise<string | null> | null>(null);
  // Bumped whenever the user cancels a transcription. A capture in flight
  // compares its epoch on completion and discards a stale result so a
  // late-arriving server response can't overwrite the composer or re-lock
  // the mic after the user already bailed out.
  const transcribeEpochRef = useRef(0);
  const queueDispatchRef = useRef(false);
  const historyHydratedRef = useRef(false);
  const persistedSessionIdRef = useRef<string | null>(null);
  // Session id we minted ourselves this launch and pinned into the URL as
  // ?resume=. It is NOT a user resume: it has no saved REST transcript yet
  // (so getSessionMessages 404s) and should read as "New chat", not "Resumed".
  const mintedSessionIdRef = useRef<string | null>(null);
  const chatStickToBottomRef = useRef(true);
  const pendingInitialBottomScrollRef = useRef(true);
  const scrollSessionKeyRef = useRef<string | null>(null);
  // Live mirrors of tools/activityTrace so the message.complete handler
  // can snapshot the finished turn without a stale-closure read.
  const toolsRef = useRef<ToolEntry[]>([]);
  const activityTraceRef = useRef<ActivityTrace[]>([]);
  const lastToolActivityAtRef = useRef(0);
  // Cumulative session usage mirror + the output-token baseline captured
  // at message.start, so message.complete can diff out this turn's tokens.
  const usageRef = useRef<UsageInfo | null>(null);
  const turnOutputBaselineRef = useRef<number | null>(null);

  const [info, setInfo] = useState<SessionInfo>({});
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [startAnalytics, setStartAnalytics] = useState<AnalyticsResponse | null>(null);
  const [startAnalyticsLoading, setStartAnalyticsLoading] = useState(false);
  const [startRange, setStartRange] = useState<StartAnalyticsRange>("all");
  const [startView, setStartView] = useState<"overview" | "models">("overview");
  const [userName, setUserName] = useState("there");
  const [artifacts, setArtifacts] = useState<ArtifactEntry[]>([]);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactEntry | null>(null);
  const dismissedArtifactsRef = useRef<Set<string>>(new Set());
  const previewAutoOpenDisabledRef = useRef(false);
  // Side-panel mode for the right aside. "preview" still uses previewArtifact
  // as the WHICH; plan/tasks/files are derived/fetched panels.
  const [sidePanel, setSidePanel] = useState<SidePanelMode>("none");
  const [planRefreshSignal, setPlanRefreshSignal] = useState(0);
  // True once the agent has presented a plan (present_plan tool) this turn —
  // gates the "Approve & run" bar so it never shows before a plan exists.
  const [planReadyForApproval, setPlanReadyForApproval] = useState(false);
  const planAutoOpenDisabledRef = useRef(false);
  const lastTodoSigRef = useRef<string>("");
  const [previewPanelWidth, setPreviewPanelWidth] = useState(defaultPreviewPanelWidth);
  const [chatWidth, setChatWidth] = useState<number | null>(defaultChatWidth);
  const [messages, setMessagesRaw] = useState<ChatMessage[]>([]);
  // Wrap the setter so ANY call that wipes a populated list to empty is caught
  // with its call stack. This is how we pin the exact eraser of the blank bug
  // (a reconnect/watchdog re-run clearing the conversation) regardless of which
  // setMessages site does it.
  const setMessages = useCallback(
    (updater: Parameters<typeof setMessagesRaw>[0]) => {
      setMessagesRaw((prev) => {
        const next =
          typeof updater === "function"
            ? (updater as (p: ChatMessage[]) => ChatMessage[])(prev)
            : updater;
        if (prev.length >= 2 && (next?.length ?? 0) === 0) {
          // INVARIANT: a populated transcript clears to empty ONLY for a
          // deliberate new chat (URL carries ?new=). Every other populated ->
          // empty transition is the spurious render-then-vanish blank — resume
          // re-hydrate, draft->session mint, compaction session rotation,
          // reconnect/liveness-watchdog re-run. Block them all and keep what's
          // on screen; the next hydrate under the correct id repopulates from
          // cache/DB. This one rule replaced four per-window guards that each
          // only caught a single trigger.
          if (!newChatPresentRef.current) {
            blankTrace("blocked spurious list wipe", {
              prevCount: prev.length,
              reconnect: reconnectRunRef.current,
              compaction: compactionGuardRef.current,
              mint: mintGuardRef.current,
            });
            return prev;
          }
          // Deliberate new chat — allow the intentional clear.
          blankTrace("list cleared for new chat", { prevCount: prev.length });
        }
        return next;
      });
    },
    [],
  );
  const [tools, setTools] = useState<ToolEntry[]>([]);
  // Subagent lifecycle (start/complete) — surfaced in the Background tasks panel
  // with goal/model/status/tool-count detail.
  const [subagents, setSubagents] = useState<SubagentEntry[]>([]);
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
  const [voiceTranscribing, setVoiceTranscribing] = useState(false);
  const [voiceMenuOpen, setVoiceMenuOpen] = useState(false);
  const [micDevices, setMicDevices] = useState<MicDevice[]>([]);
  const [selectedMicId, setSelectedMicId] = useState<string>("");
  const [statusText, setStatusText] = useState("Connecting...");
  // True only during the blocking context-compaction summary call. The agent
  // emits a "Compacting context…" lifecycle status, then the turn stalls for
  // ~24-36s with nothing to stream — without a visible indicator the chat
  // looks frozen. Set on that status; cleared by the first resume signal
  // (delta/thinking/tool) and a !busy safety net below.
  const [compacting, setCompacting] = useState(false);
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
  const [permissionModeId, setPermissionModeId] = useState<string>("default");
  const [permissionMenuOpen, setPermissionMenuOpen] = useState(false);
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

  const handleEditMessage = useCallback((message: ChatMessage) => {
    const text = message.content.trimEnd();
    if (!text) return;
    setInput(text);
    setCaretIndex(text.length);
    window.requestAnimationFrame(() => {
      const inputEl = inputRef.current;
      inputEl?.focus();
      inputEl?.setSelectionRange(text.length, text.length);
    });
  }, []);

  const artifactStateSessionId = useCallback(
    () => persistedSessionIdRef.current ?? resumeId ?? sessionId,
    [resumeId, sessionId],
  );

  // The agent lane is fixed for the life of a chat: it is applied on the
  // first turn and stays in force. Once the chat has a user message the
  // switcher locks so it always reflects which agent is actually running.
  const agentLocked = useMemo(
    () => messages.some((message) => message.role === "user"),
    [messages],
  );

  const appendMessage = useCallback(
    (role: ChatRole, content: string, extras: Partial<ChatMessage> = {}) => {
      const candidate: Partial<ChatMessage> = { role, content, ...extras };
      if (!shouldKeepTranscriptMessage(role, content) && !hasActivitySnapshot(candidate)) {
        return "";
      }
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

  const ensureAssistant = useCallback((createdAt?: number) => {
    const startedAt = timestampMillis(createdAt, Date.now());
    if (currentAssistantRef.current) {
      const messageId = currentAssistantRef.current;
      if (createdAt !== undefined) {
        setMessages((prev) => {
          let changed = false;
          const next = prev.map((message) => {
            if (message.id !== messageId || startedAt >= message.createdAt) {
              return message;
            }
            changed = true;
            return { ...message, createdAt: startedAt };
          });
          return changed ? next : prev;
        });
      }
      return messageId;
    }
    const messageId = id("assistant");
    currentAssistantRef.current = messageId;
    setMessages((prev) => [
      ...prev,
      {
        content: "",
        createdAt: startedAt,
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
      setMessages((prev) => {
        const index = prev.findIndex((message) => message.id === messageId);
        if (index === -1) return prev;
        const current = prev[index];
        const nextMessage = updater(current);
        if (nextMessage === current) return prev;
        const next = prev.slice();
        next[index] = nextMessage;
        return next;
      });
    },
    [ensureAssistant],
  );

  const pendingAssistantDeltaRef = useRef("");
  const assistantDeltaFlushTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const clearPendingAssistantDelta = useCallback(() => {
    if (assistantDeltaFlushTimerRef.current) {
      window.clearTimeout(assistantDeltaFlushTimerRef.current);
      assistantDeltaFlushTimerRef.current = null;
    }
    pendingAssistantDeltaRef.current = "";
  }, []);
  const flushAssistantDelta = useCallback(() => {
    if (assistantDeltaFlushTimerRef.current) {
      window.clearTimeout(assistantDeltaFlushTimerRef.current);
      assistantDeltaFlushTimerRef.current = null;
    }
    const delta = pendingAssistantDeltaRef.current;
    if (!delta) return;
    pendingAssistantDeltaRef.current = "";
    updateAssistant((message) => ({
      ...message,
      content: message.content + delta,
      status: "streaming",
    }));
  }, [updateAssistant]);

  const enqueueAssistantDelta = useCallback(
    (text: string) => {
      pendingAssistantDeltaRef.current += text;
      if (assistantDeltaFlushTimerRef.current) return;
      assistantDeltaFlushTimerRef.current = window.setTimeout(flushAssistantDelta, 50);
    },
    [flushAssistantDelta],
  );

  useEffect(
    () => () => clearPendingAssistantDelta(),
    [clearPendingAssistantDelta],
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

    if (
      previewCandidate &&
      !previewAutoOpenDisabledRef.current &&
      !dismissedArtifactsRef.current.has(artifactDismissKey(previewCandidate))
    ) {
      // Keep the latest artifact loaded as the preview's content, but do NOT
      // auto-open the right panel — artifacts no longer take over the right
      // side. They live in the Artifacts tab (the button); tap one to open it
      // here in Preview.
      setPreviewArtifact(previewCandidate);
    }
  }, []);

  // Persist the artifacts panel per session. Tool messages (which carry
  // the full file paths) are stripped from the saved transcript, so on
  // reattach the panel can only be rebuilt from this localStorage copy.
  // Skip empty writes: artifacts only ever grow within a session, so the
  // only time the array is empty is the reattach reset (setArtifacts([]))
  // — writing that would wipe a still-valid cache before the restore runs.
  useEffect(() => {
    if (!artifacts.length) return;
    const id = persistedSessionIdRef.current ?? sessionId;
    if (!id) return;
    writeSessionArtifacts(id, artifacts);
  }, [artifacts, sessionId]);

  const dismissPreviewArtifact = useCallback(() => {
    const storageId = artifactStateSessionId();
    previewAutoOpenDisabledRef.current = true;
    writePreviewAutoOpenDisabled(storageId, true);
    setPreviewArtifact((current) => {
      if (current) {
        dismissedArtifactsRef.current.add(artifactDismissKey(current));
        // Persist under the stable persisted-session id, NOT the ephemeral
        // gateway session_id. session.resume mints a fresh session_id on
        // every reattach, so a dismissal written under sessionId would be
        // read back under resumeId (the persisted id) and never match —
        // which is why the panel kept reopening on leave/return.
        writeDismissedArtifactKeys(
          storageId,
          dismissedArtifactsRef.current,
        );
      }
      return null;
    });
    setSidePanel("none");
  }, [artifactStateSessionId]);

  const hydrateArtifactsFromMessages = useCallback(
    (nextMessages: ChatMessage[]) => {
      addArtifacts(artifactsFromMessages(nextMessages));
    },
    [addArtifacts],
  );

  const openArtifactPreview = useCallback(
    (artifact: ArtifactEntry) => {
      const storageId = artifactStateSessionId();
      previewAutoOpenDisabledRef.current = false;
      writePreviewAutoOpenDisabled(storageId, false);
      const dKey = artifactDismissKey(artifact);
      if (dismissedArtifactsRef.current.has(dKey)) {
        dismissedArtifactsRef.current.delete(dKey);
        writeDismissedArtifactKeys(
          storageId,
          dismissedArtifactsRef.current,
        );
      }
      // Open EVEN. Auto-population shouldn't let the preview take over the chat
      // (or vice versa) — start at a balanced 50/50 of the CHAT SHELL (the area
      // between the sidebar and the right border), NOT the whole window (which
      // includes the sidebar and would make the preview bigger than half).
      const shellEl = document.querySelector<HTMLElement>(".elevate-chat-shell");
      const shellWidth = shellEl?.clientWidth || window.innerWidth;
      setPreviewPanelWidth(clampPreviewPanelWidth(Math.round(shellWidth * 0.5)));
      setPreviewArtifact(artifact);
      setSidePanel("preview");
    },
    [artifactStateSessionId],
  );

  // Open a non-preview side panel (plan/tasks/files). These are compact
  // fixed-width breakdowns, so there's no 50/50 width to set (preview owns the
  // resizable width).
  const openSidePanel = useCallback((mode: SidePanelMode) => {
    if (mode === "none") {
      setSidePanel("none");
      return;
    }
    if (mode === "plan") planAutoOpenDisabledRef.current = false;
    setSidePanel(mode);
  }, []);

  // The approval bar only belongs while plan mode is on; clear it on exit.
  useEffect(() => {
    if (permissionModeId !== "plan") setPlanReadyForApproval(false);
  }, [permissionModeId]);

  const closeSidePanel = useCallback(() => {
    setSidePanel((current) => {
      if (current === "plan") planAutoOpenDisabledRef.current = true;
      return "none";
    });
  }, []);

  const handleSelectPanel = useCallback(
    (mode: SidePanelMode) => {
      // Selecting the active panel toggles it closed.
      if (mode === sidePanel) {
        if (mode === "preview") dismissPreviewArtifact();
        else closeSidePanel();
        return;
      }
      // Preview always opens — it shows a "No preview" state when there's no
      // current artifact, rather than being a dead menu row.
      if (mode === "preview") {
        setSidePanel("preview");
        return;
      }
      openSidePanel(mode);
    },
    [sidePanel, dismissPreviewArtifact, closeSidePanel, openSidePanel],
  );

  const openFileInPreview = useCallback(
    (path: string, name: string) => {
      openArtifactPreview({
        content: undefined,
        createdAt: Date.now(),
        id: `file:${path}`,
        key: `file:${path}`,
        kind: "file",
        path,
        source: "Files",
        title: name,
      });
    },
    [openArtifactPreview],
  );

  const startPreviewResize = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (sidePanel === "none") return;
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
        try {
          localStorage.setItem("elevate-preview-width", String(clampPreviewPanelWidth(finalWidth)));
        } catch {
          // Preview width persistence is best-effort.
        }
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", stopResize);
        window.removeEventListener("pointercancel", stopResize);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", stopResize);
      window.addEventListener("pointercancel", stopResize);
    },
    [sidePanel, previewPanelWidth],
  );

  // Drag-to-resize the chat column itself (works with or without a side panel).
  // The column is centered, so dragging the right edge changes BOTH sides.
  const startChatResize = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const target = event.currentTarget;
      const pointerId = event.pointerId;
      const startX = event.clientX;
      const shell = target.closest(".elevate-chat-shell") as HTMLElement | null;
      const col = target.closest("[data-chat-col]") as HTMLElement | null;
      const startWidth = col
        ? Math.round(col.getBoundingClientRect().width)
        : clampChatWidth(chatWidth ?? 1000);
      target.setPointerCapture(pointerId);

      const onPointerMove = (moveEvent: PointerEvent) => {
        const delta = (moveEvent.clientX - startX) * 2;
        const clamped = clampChatWidth(startWidth + delta);
        if (shell) shell.style.setProperty("--chat-layout-width-user", `${clamped}px`);
      };

      const stopResize = () => {
        if (target.hasPointerCapture(pointerId)) target.releasePointerCapture(pointerId);
        const finalWidth = shell
          ? parseInt(
              shell.style.getPropertyValue("--chat-layout-width-user") || String(startWidth),
              10,
            )
          : startWidth;
        const c = clampChatWidth(finalWidth);
        setChatWidth(c);
        try {
          localStorage.setItem("elevate-chat-width", String(c));
        } catch {
          // best-effort persistence
        }
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", stopResize);
        window.removeEventListener("pointercancel", stopResize);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", stopResize);
      window.addEventListener("pointercancel", stopResize);
    },
    [chatWidth],
  );

  // Auto-open the Plan panel when the agent presents a plan (present_plan) or
  // writes a todo list, unless the user dismissed it. The tool stream is just
  // the trigger; PlanPanel refetches the untruncated plan/list from the API.
  // A present_plan also arms the "Approve & run" bar.
  useEffect(() => {
    let latest: ToolEntry | undefined;
    let isPlan = false;
    for (let i = tools.length - 1; i >= 0; i--) {
      if (tools[i].name === "present_plan" || tools[i].name === "todo") {
        latest = tools[i];
        isPlan = tools[i].name === "present_plan";
        break;
      }
    }
    if (!latest) return;
    const sig = `${latest.id}:${latest.status}:${latest.completedAt ?? ""}`;
    if (sig === lastTodoSigRef.current) return;
    lastTodoSigRef.current = sig;
    setPlanRefreshSignal((value) => value + 1);
    if (isPlan && latest.status !== "error") setPlanReadyForApproval(true);
    if (!planAutoOpenDisabledRef.current && sidePanel === "none") {
      openSidePanel("plan");
    }
  }, [tools, sidePanel, openSidePanel]);

  const addActivityTrace = useCallback(
    (kind: ActivityTrace["kind"], text: string, createdAt?: number) => {
      const isReasoning = kind === "thinking" || kind === "reasoning";
      // Reasoning content keeps its RAW text: displayStatusText collapses any
      // chunk mentioning "thinking"/"reasoning"/"computing" into "Working...",
      // which (combined with the filter below) shreds real reasoning into
      // sentence-start fragments. And we do NOT filter reasoning per-delta —
      // deltas are sentence fragments, so judging each as "generic" is wrong.
      // Transient pills are dropped later, at the whole-trace level.
      const clean = isReasoning
        ? text // raw token-stream text — tokens carry their own spacing and are
                // appended verbatim below. Collapsing \s+ and trimming here is what
                // shredded words into "embell ishment" / "Let 's" / "non -manager".
        : displayStatusText(text).trim();
      if (!clean) return;
      if (kind === "status" && isGenericActivityText(clean)) {
        return;
      }

      const messageId = currentAssistantRef.current ?? undefined;
      const at = timestampMillis(createdAt, Date.now());
      const toolBoundaryAt = lastToolActivityAtRef.current;
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
          last.messageId === messageId &&
          last.createdAt >= toolBoundaryAt
        ) {
          // Append the token stream verbatim — its own whitespace IS the
          // formatting. (Previously joined with a " " separator, which inserted
          // spaces mid-word: "non -manager", "SQL -like", "over doing".)
          const merged = (last.text + clean).slice(-2000);
          const next = prev.slice(0, -1);
          next.push({ ...last, text: merged });
          return next;
        }
        return [
          ...prev,
          {
            createdAt: at,
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
    // Dismissals are persisted under the STABLE persisted-session id, not the
    // ephemeral gateway session_id (session.resume mints a fresh one on every
    // reattach). Reading under sessionId here would clobber the ref with an
    // empty set the moment the gateway connects — which is why a closed
    // preview reopened on leave/return. Read under the same key the write uses.
    const storageId = artifactStateSessionId();
    dismissedArtifactsRef.current = readDismissedArtifactKeys(storageId);
    previewAutoOpenDisabledRef.current =
      readPreviewAutoOpenDisabled(storageId);
  }, [artifactStateSessionId, sessionId]);

  useEffect(() => {
    const sync = () => {
      setPreviewPanelWidth((width) => clampPreviewPanelWidth(width));
    };
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);

  useEffect(() => {
    if (sidePanel === "none") return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (sidePanel === "preview") dismissPreviewArtifact();
        else closeSidePanel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidePanel, dismissPreviewArtifact, closeSidePanel]);

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
      try {
        mediaRecorderRef.current?.stop();
      } catch {
        // recorder already inactive
      }
      mediaRecorderRef.current = null;
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
      audioChunksRef.current = [];
    };
  }, []);

  // Enumerate microphones for the device picker. Labels are only populated
  // once the user has granted mic permission at least once, so we also
  // refresh after a successful capture and on the OS devicechange event.
  useEffect(() => {
    if (typeof navigator?.mediaDevices?.enumerateDevices !== "function") return;
    let cancelled = false;

    const refreshDevices = async () => {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        if (cancelled) return;
        const mics = devices
          .filter((device) => device.kind === "audioinput")
          .map((device, index) => ({
            deviceId: device.deviceId,
            label: device.label || `Microphone ${index + 1}`,
          }));
        setMicDevices(mics);
        setSelectedMicId((current) => {
          if (current && mics.some((mic) => mic.deviceId === current)) {
            return current;
          }
          return mics[0]?.deviceId ?? "";
        });
      } catch {
        // enumeration unavailable — picker stays empty, default mic still works
      }
    };

    void refreshDevices();
    navigator.mediaDevices.addEventListener?.("devicechange", refreshDevices);
    return () => {
      cancelled = true;
      navigator.mediaDevices.removeEventListener?.("devicechange", refreshDevices);
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

  useLayoutEffect(() => {
    const key = resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
    if (scrollSessionKeyRef.current === key) return;
    scrollSessionKeyRef.current = key;
    chatStickToBottomRef.current = true;
    pendingInitialBottomScrollRef.current = true;
  }, [newChatId, resumeId, seedKey]);

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
    let cancelled = false;
    api
      .getLicenseStatus()
      .then((license) => {
        if (!cancelled) setUserName(formatPersonName(license.email));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const days = startRange === "7d" ? 7 : startRange === "30d" ? 30 : 0;
    setStartAnalyticsLoading(true);
    api
      .getAnalytics(days)
      .then((analytics) => {
        if (!cancelled) setStartAnalytics(analytics);
      })
      .catch(() => {
        if (!cancelled) setStartAnalytics(null);
      })
      .finally(() => {
        if (!cancelled) setStartAnalyticsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [startRange]);

  // Debug: forward [BLANK-TRACE] events to the gateway (-> ~/.elevate/logs/
  // blank-trace.log) so a vanished-answer render bug can be diagnosed without
  // opening devtools.
  useEffect(() => {
    (
      window as unknown as {
        __elevateBlankTraceSink?: (m: string, d: Record<string, unknown>) => void;
      }
    ).__elevateBlankTraceSink = (m, d) => {
      try {
        void gw.request("debug.trace", {
          session_id: sessionId ?? "",
          payload: { msg: m, ...d },
        });
      } catch {
        /* best effort */
      }
    };
    return () => {
      (
        window as unknown as { __elevateBlankTraceSink?: unknown }
      ).__elevateBlankTraceSink = undefined;
    };
  }, [gw, sessionId]);

  // Debug: catch the moment a rendered assistant answer disappears from the
  // on-screen list (the "render then vanish" bug). Reports what it was and how
  // many messages were in the list before/after.
  const prevMessagesForTraceRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    const prev = prevMessagesForTraceRef.current;
    prevMessagesForTraceRef.current = messages;
    try {
      // Content fingerprint: an id remap (cache `stored-N` id -> server id for
      // the SAME answer, which happens on every resume) must NOT count as a
      // vanish. We only care that the rendered CONTENT survives, not which id
      // carries it. Without this, ~every resume logs false "vanished" events
      // (listBefore == listAfter) that drown out the real-blank signal.
      const cfp = (m: ChatMessage) =>
        `${m.role}:${(m.content ?? "").replace(/\s+/g, " ").trim().slice(0, 160)}`;
      const nowContent = new Set(messages.map(cfp));
      for (const pm of prev) {
        if (pm.role !== "assistant") continue;
        const prevLen = (pm.content ?? "").replace(/\s+/g, "").length;
        if (prevLen <= 80) continue;
        if (nowContent.has(cfp(pm))) continue; // content preserved (id remap) -> not a vanish
        const now = messages.find((m) => m.id === pm.id);
        const nowLen = now ? (now.content ?? "").replace(/\s+/g, "").length : -1;
        if (nowLen === -1 || nowLen < prevLen * 0.5) {
          blankTrace("rendered assistant answer vanished from list", {
            id: pm.id,
            wasChars: (pm.content ?? "").length,
            nowChars: now ? (now.content ?? "").length : "REMOVED",
            listBefore: prev.length,
            listAfter: messages.length,
          });
        }
      }
    } catch {
      /* never break render */
    }
  }, [messages]);

  // Persist the transcript + active-turn snapshot — THROTTLED. Both do a full
  // JSON.stringify of the (growing) transcript + a localStorage write; running
  // them on every streamed delta and tool event jammed the main thread during
  // tool-heavy turns and froze the renderer (the chat would "stop showing
  // what's happening" while the agent kept working underneath). Throttle to at
  // most once / 1.5s while a turn streams, and persist immediately the moment
  // it goes idle so the final state is never lost. Each run reads the current
  // messages/tools (no stale closure); idle-flush + the ~50ms delta cadence
  // keep persistence within ~1.5s of live.
  const lastPersistAtRef = useRef(0);
  useEffect(() => {
    const persisted = persistedSessionIdRef.current;
    if (!persisted) return;
    const PERSIST_THROTTLE_MS = 1500;
    if (busy && Date.now() - lastPersistAtRef.current < PERSIST_THROTTLE_MS) return;
    lastPersistAtRef.current = Date.now();
    if (messages.length) {
      rememberTranscript(
        persisted,
        attachLiveActivitySnapshots(messages, tools, activityTrace),
      );
    }
    const active = activeAssistantMessage(messages, currentAssistantRef.current);
    if (active) {
      writeActiveTurnSnapshot(persisted, active, tools, activityTrace);
    } else if (!busy) {
      clearActiveTurnSnapshot(persisted);
    }
  }, [activityTrace, busy, messages, sessionId, tools]);

  // Drive the compaction guard off the `compacting` lifecycle state. Open it
  // the moment compaction starts; once compaction ends (the model resumes),
  // hold the guard open a few more seconds so the session-rotation re-hydrate
  // that follows can't wipe the displayed transcript to empty. The wrapped
  // setMessages blocks any populated-list -> empty wipe while this is open.
  useEffect(() => {
    if (compacting) {
      compactionGuardRef.current = true;
      if (compactionGuardTimerRef.current) {
        clearTimeout(compactionGuardTimerRef.current);
        compactionGuardTimerRef.current = null;
      }
    } else if (compactionGuardRef.current) {
      if (compactionGuardTimerRef.current) {
        clearTimeout(compactionGuardTimerRef.current);
      }
      compactionGuardTimerRef.current = setTimeout(() => {
        compactionGuardRef.current = false;
        compactionGuardTimerRef.current = null;
      }, 5000);
    }
  }, [compacting]);

  // Safety net: the compaction banner must never outlive an active turn. The
  // resume-signal clears (delta/thinking/tool) cover the normal path; this
  // catches the rest (errors, stop, interrupt, disconnect) so a stale
  // "Compacting…" banner can't get stuck on screen.
  useEffect(() => {
    if (!busy && compacting) setCompacting(false);
  }, [busy, compacting]);

  useEffect(() => {
    const persisted = persistedSessionIdRef.current ?? sessionId;
    if (!persisted) return;
    writeQueue(persisted, queuedInputs);
  }, [queuedInputs, sessionId]);

  // Startup behavior: on every full page load (app launch / reload) open a
  // fresh draft chat — ready to type — instead of reopening the last session.
  // It mints no row (a draft only persists once you send) and the sidebar still
  // lets you reopen prior chats by hand. The module-level guard fires this once
  // per page load, so client-side navigations (sidebar clicks -> ?resume=) are
  // untouched.
  useEffect(() => {
    if (autoResumeDecided) return;
    if (!forcedNewChatThisLoad) {
      // First load of this page → force a fresh draft chat (drop any resume).
      forcedNewChatThisLoad = true;
      if (!newChatId) {
        const next = new URLSearchParams();
        next.set("new", String(Date.now()));
        setSearchParams(next, { replace: true });
      }
      setAutoResumeDecided(true);
      return;
    }
    // A later bare /chat (no resume / no new): just release the gate so the
    // bootstrap mints a fresh session instead of auto-resuming.
    setAutoResumeDecided(true);
  }, [autoResumeDecided, newChatId, searchParams, setSearchParams]);

  useEffect(() => {
    if (!autoResumeDecided) return;
    let cancelled = false;
    const unsubs: Array<() => void> = [];

    clearPendingAssistantDelta();
    activeSessionRef.current = null;
    currentAssistantRef.current = null;
    historyHydratedRef.current = false;
    persistedSessionIdRef.current = resumeId;
    setSessionId(null);
    setInfo({});
    setUsage(null);
    setArtifacts([]);
    setPreviewArtifact(null);
    const activeTurnSnapshot = resumeId ? readActiveTurnSnapshot(resumeId) : null;
    dismissedArtifactsRef.current = readDismissedArtifactKeys(resumeId);
    previewAutoOpenDisabledRef.current =
      readPreviewAutoOpenDisabled(resumeId);
    if (activeTurnSnapshot) {
      currentAssistantRef.current = activeTurnSnapshot.message.id;
    }
    setTools(activeTurnSnapshot?.tools ?? []);
    setSubagents([]);
    setActivityTrace(activeTurnSnapshot?.traces ?? []);
    lastToolActivityAtRef.current = 0;
    setQueuedInputs(resumeId ? restoreQueue(resumeId) : []);
    setPendingPrompt(null);
    setPromptValue("");
    setBusy(false);
    setBanner(null);
    setResumeFallback(false);
    setStatusText(resumeId ? "Loading chat..." : draftChat ? "Ready" : "Connecting...");

    if (resumeId) {
      // Restore the artifacts captured during earlier turns of this
      // session. Tool messages (which carry the full file paths) are
      // stripped from the persisted transcript, so without this the
      // right-side panel re-derives nothing and goes empty on reattach.
      const cachedArtifacts = readSessionArtifacts(resumeId);
      if (cachedArtifacts.length) setArtifacts(cachedArtifacts);

      const cached = restoreTranscript(resumeId);
      const restoredCached = mergeActiveTurnSnapshot(cached ?? [], activeTurnSnapshot);
      if (restoredCached.length) {
        historyHydratedRef.current = true;
        renderedChatKeyRef.current =
          resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
        setMessages(restoredCached);
        hydrateArtifactsFromMessages(restoredCached);
        if (activeTurnSnapshot || hasPendingTurn(restoredCached)) {
          setBusy(true);
          setStatusText("Resuming work...");
        } else {
          setStatusText("Ready");
        }
      }

      // A freshly minted + pinned session (mintedSessionIdRef) has no saved
      // REST transcript yet — skip the hydrate so its expected 404 never
      // surfaces as a "could not load saved messages" error.
      if (resumeId === mintedSessionIdRef.current) {
        historyHydratedRef.current = true;
      } else void api.getSessionMessages(resumeId)
        .then((response) => {
          if (cancelled) return;
          const hydrated = normalizeStoredTranscript(response.messages);
          const latestActiveSnapshot = readActiveTurnSnapshot(resumeId);
          historyHydratedRef.current = true;
          setMessages((prev) => {
            // Merge against the current UI state, not only the cache captured
            // before gateway replay. Otherwise a slow DB hydrate can erase the
            // in-flight assistant turn that session.resume just replayed.
            const base = prev.length ? prev : restoredCached;
            const merged = mergeActiveTurnSnapshot(
              mergeServerWithCache(hydrated, base),
              latestActiveSnapshot,
            );
            rememberTranscript(response.session_id || resumeId, merged);
            rememberTranscript(resumeId, merged);
            hydrateArtifactsFromMessages(merged);
            // Cold-load path (no warm cache): the IF-branch above only set
            // renderedChatKeyRef when restoredCached was non-empty. A chat
            // hydrated purely from the DB fetch would otherwise render with
            // renderedChatKeyRef still null, leaving the fresh-mount guard in
            // the connect else-branch unable to recognize this as a real chat
            // -> a transient-null re-run would wipe it. Stamp the key here too.
            if (merged.length) {
              renderedChatKeyRef.current =
                resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
            }
            if (!latestActiveSnapshot && !hasPendingTurn(merged)) {
              // Cache heuristic flagged this as pending (last msg = user
              // with no assistant follow-up) so busy was set true above. The
              // merged transcript confirms no live-looking turn remains —
              // clear busy unless gateway resume later proves the turn is
              // still running.
              setBusy(false);
              setStatusText("Ready");
            } else {
              setBusy(true);
              setStatusText("Resuming work...");
            }
            return merged;
          });
        })
        .catch((error: Error) => {
          if (cancelled || restoredCached.length) return;
          setBanner(`Could not load saved messages yet: ${error.message}`);
        });
    } else {
      persistedSessionIdRef.current = null;
      const _chatKey = resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
      setMessages((prev) => {
        // A reconnect / liveness-watchdog re-run for THIS same chat must not
        // wipe the conversation it already rendered. Only blank when the chat
        // key actually changed (genuinely a different chat).
        if (
          prev.length &&
          (renderedChatKeyRef.current === _chatKey ||
            (mintedSessionIdRef.current != null &&
              mintedSessionIdRef.current === resumeId))
        ) {
          blankTrace("blocked same-chat list wipe (connect else)", {
            count: prev.length,
            chatKey: _chatKey,
          });
          return prev;
        }
        // Fresh-mount transient-null race (the open gap from 1.1.2->1.1.8).
        // On app relaunch / page reload the connect effect can re-run with
        // resumeId momentarily null BEFORE the cache restore settles. With
        // every URL param null, _chatKey collapses to "__fresh_chat__" while
        // renderedChatKeyRef still points at the real chat we just rendered,
        // so the same-chat guard above misses and we'd wipe a live transcript.
        // A deliberate new chat ALWAYS carries ?new= (App.tsx startNewChat +
        // hub/config seeds), so _chatKey is never "__fresh_chat__" there.
        // Keep what's on screen; the next run with the real resumeId re-hydrates.
        if (
          prev.length >= 2 &&
          _chatKey === "__fresh_chat__" &&
          renderedChatKeyRef.current != null &&
          renderedChatKeyRef.current !== "__fresh_chat__"
        ) {
          blankTrace("blocked fresh-mount transient-null wipe (connect else)", {
            count: prev.length,
            renderedKey: renderedChatKeyRef.current,
          });
          return prev;
        }
        renderedChatKeyRef.current = _chatKey;
        return [];
      });
    }

    const accepts = (ev: GatewayEvent) => {
      const active = activeSessionRef.current;
      const eventSessionId =
        typeof ev.session_id === "string" && ev.session_id.trim()
          ? ev.session_id
          : null;
      // A draft/new chat intentionally has no session yet. Treat that as
      // "accept none" for session events, not "accept everything"; otherwise
      // a still-streaming old chat can paint into the fresh view.
      return Boolean(active && eventSessionId && eventSessionId === active);
    };

    const trackTool = (ev: GatewayEvent) => {
      if (!accepts(ev)) return;
      const payload = compactToolPayload(ev.payload);
      const at = eventMillis(ev);
      lastToolActivityAtRef.current = Math.max(lastToolActivityAtRef.current, at);
      // Any tool event means the model resumed after compaction.
      setCompacting(false);

      if (ev.type === "tool.start") {
        const toolId = String(payload.tool_id ?? "");
        if (!toolId) return;
        const name = String(payload.name ?? "tool");
        const context = typeof payload.context === "string" ? payload.context : "";
        const startedAt = timestampMillis(payload.started_at, at);
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
                      startedAt: Math.min(tool.startedAt || startedAt, startedAt),
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
                        startedAt: Math.min(tool.startedAt || startedAt, startedAt),
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
                    startedAt,
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
        const startedAt = timestampMillis(payload.started_at, at);
        const turnMessageId = currentAssistantRef.current ?? undefined;

        setTools((prev) => {
          const hasRunning = prev.some(
            (tool) => tool.status === "running" && tool.name === name,
	          );
	          if (hasRunning) {
	            return prev.map((tool) =>
	              tool.status === "running" && tool.name === name
	                ? {
	                    ...tool,
	                    messageId: tool.messageId ?? turnMessageId,
	                    preview,
	                    startedAt: Math.min(tool.startedAt || startedAt, startedAt),
	                  }
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
              startedAt,
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
        const completedAt = timestampMillis(payload.completed_at, at);

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
                  completedAt,
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
      const now = eventMillis(ev);

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
        const at = eventMillis(ev);
        lastToolActivityAtRef.current = 0;
        setSubagents((prev) => prev.filter((subagent) => subagent.status === "running").slice(-8));
        ensureAssistant(at);
        // Snapshot cumulative output tokens so message.complete can diff
        // out exactly this turn's count.
        turnOutputBaselineRef.current = usageRef.current?.output ?? null;
        setBusy(true);
        setCompacting(false);
        setStatusText("Working...");
        addActivityTrace("status", "Working...", at);
      }),
    );
    unsubs.push(
      gw.on("message.delta", (ev) => {
        if (!accepts(ev)) return;
        const activeAssistantId = currentAssistantRef.current;
        if (
          activeAssistantId &&
          stoppedAssistantIdsRef.current.has(activeAssistantId)
        ) {
          return;
        }
        const text = eventText(ev);
        if (!text) return;
        setCompacting(false);
        ensureAssistant(eventMillis(ev));
        enqueueAssistantDelta(text);
      }),
    );
    unsubs.push(
      gw.on("message.complete", (ev) => {
        if (!accepts(ev)) return;
        const at = eventMillis(ev);
        updateUsageFromPayload(ev);
        const text = eventText(ev);
        const status = eventString(ev, "status") || "complete";
        const warning = eventString(ev, "warning");
        const messageId = currentAssistantRef.current ?? ensureAssistant(at);
        const stopForced = stoppedAssistantIdsRef.current.has(messageId);
        flushAssistantDelta();

        // The agent just finished a turn — if the user asked it to change
        // anything (add a card, update a template, move a deal, edit an
        // automation, update memory), the change is already written
        // server-side. Broadcast one app-wide signal so EVERY data view
        // re-fetches immediately, instead of waiting on each page's poll or an
        // app restart. Data hooks subscribe via useRefreshOnAgentTurn(); each
        // listener only fires while its page is mounted. Background
        // (cron/heartbeat) changes still ride the per-page poll as a fallback.
        if (typeof window !== "undefined") {
          window.dispatchEvent(new Event("elevate:agent-turn-complete"));
        }

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
                  completedAt: tool.completedAt ?? at,
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
            completedAt: at,
            status:
              stopForced || status === "interrupted" ? "interrupted" : "complete",
            warning: warning || undefined,
            tools: turnTools.length ? turnTools : message.tools,
            traces: turnTraces.length ? turnTraces : message.traces,
            tokenCount: realTurnOutput ?? (estimatedTurnTokens || undefined),
          };
        });
        stoppedAssistantIdsRef.current.delete(messageId);
        if (text) {
          addArtifacts(artifactsFromText(text, "assistant", messageId));
        }
        clearActiveTurnSnapshot(persistedSessionIdRef.current ?? ev.session_id);
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
                  completedAt: at,
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
          const at = eventMillis(ev);
          setStatusText(displayStatusText(text));
          addActivityTrace("status", text, at);
          // Compaction is the one status that maps to a long blocking stall.
          // Latch the banner on; resume signals (below) clear it.
          if (/compacting context/i.test(text)) setCompacting(true);
        }
      }),
    );
    unsubs.push(
      gw.on("thinking.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) {
          const at = eventMillis(ev);
          setCompacting(false);
          setStatusText("Thinking...");
          ensureAssistant(at);
          addActivityTrace("thinking", text, at);
        }
      }),
    );
    unsubs.push(
      gw.on("reasoning.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) {
          const at = eventMillis(ev);
          setCompacting(false);
          setStatusText("Reasoning...");
          ensureAssistant(at);
          addActivityTrace("reasoning", text, at);
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
        const at = eventMillis(ev);
        lastToolActivityAtRef.current = Math.max(lastToolActivityAtRef.current, at);
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
                  startedAt: at,
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
        const at = eventMillis(ev);
        const message = eventString(ev, "message") || "Gateway error";
        setBanner(message);
        appendMessage("system", message, { createdAt: at, status: "error" });
        setBusy(false);
        setQueuedInputs([]);
        clearActiveTurnSnapshot(persistedSessionIdRef.current ?? ev.session_id);
        setSubagents((prev) =>
          prev.map((subagent) =>
            subagent.status === "running"
              ? { ...subagent, completedAt: at, status: "error" }
              : subagent,
          ),
        );
        setStatusText("Error");
      }),
    );

    gw.connect()
      .then(async () => {
        if (cancelled) return;
        if (draftChat) {
          setStatusText("Ready");
          return;
        }
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
        // Pin a freshly-created (?new=) chat to its persisted id by
        // rewriting the URL to ?resume=<id>. Re-entering the route later
        // (browser back, tab switch, sidebar) then reattaches to the live
        // gateway session instead of minting a new one — which is what
        // made an in-progress turn's "Working" state vanish on return.
        // The transcript no longer accumulates across visits: it is keyed
        // by persisted id and de-duped by historyHydratedRef +
        // mergeServerWithCache, so the old auto-rewrite hazard is gone.
        {
          const pinnedId = persistedSessionIdRef.current;
          if (pinnedId && !resumeId) {
            // This resume id is one we just minted, not a user resume. Record
            // it so the re-run triggered by this URL change skips the REST
            // transcript fetch (nothing saved yet) and the title stays "New chat".
            mintedSessionIdRef.current = pinnedId;
            // Keep the rendered-chat-key in sync with the minted identity so
            // the connect-effect guards recognize the post-mint re-run as the
            // SAME conversation and don't wipe what's on screen.
            renderedChatKeyRef.current = pinnedId;
            setSearchParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                next.delete("new");
                next.set("resume", pinnedId);
                return next;
              },
              { replace: true },
            );
          }
        }
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
            const _chatKey = resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
            setMessages((prev) => {
              if (
                merged.length === 0 &&
                prev.length &&
                (renderedChatKeyRef.current === _chatKey ||
                  (mintedSessionIdRef.current != null &&
                    mintedSessionIdRef.current === resumeId))
              ) {
                blankTrace("blocked same-chat empty-merge wipe", {
                  count: prev.length,
                  chatKey: _chatKey,
                });
                return prev;
              }
              // Fresh-mount transient-null race: an empty server merge during a
              // bare-/chat re-run must not wipe a live transcript we already
              // rendered for a real chat. Deliberate new chats carry ?new=.
              if (
                merged.length === 0 &&
                prev.length >= 2 &&
                _chatKey === "__fresh_chat__" &&
                renderedChatKeyRef.current != null &&
                renderedChatKeyRef.current !== "__fresh_chat__"
              ) {
                blankTrace("blocked fresh-mount transient-null wipe (empty-merge)", {
                  count: prev.length,
                  renderedKey: renderedChatKeyRef.current,
                });
                return prev;
              }
              // Same-chat partial-drop guard. `merged` is built from the
              // localStorage cache (`restoreTranscript`), which can lag the live
              // `prev` — a turn that just rendered may not be cached yet.
              // Returning the shorter `merged` raw vanishes those rendered
              // answers (listBefore > listAfter, the 4->2 render-then-vanish).
              // For the SAME chat, recover prev's content through the same
              // fingerprint merge (prev as the cache) so nothing on screen is
              // lost; a genuine chat switch (different key) still replaces.
              if (
                prev.length &&
                merged.length < prev.length &&
                (renderedChatKeyRef.current === _chatKey ||
                  (mintedSessionIdRef.current != null &&
                    mintedSessionIdRef.current === resumeId))
              ) {
                blankTrace("recovered same-chat partial drop (resume merge)", {
                  prevLen: prev.length,
                  mergedLen: merged.length,
                  chatKey: _chatKey,
                });
                renderedChatKeyRef.current = _chatKey;
                return mergeServerWithCache(merged, prev);
              }
              renderedChatKeyRef.current = _chatKey;
              return merged;
            });
            hydrateArtifactsFromMessages(merged);
            if (persistedSessionIdRef.current) {
              rememberTranscript(persistedSessionIdRef.current, merged);
            }
          }
        } else if (!resumeId && !historyHydratedRef.current) {
          const _chatKey = resumeId ?? newChatId ?? seedKey ?? "__fresh_chat__";
          setMessages((prev) => {
            if (
          prev.length &&
          (renderedChatKeyRef.current === _chatKey ||
            (mintedSessionIdRef.current != null &&
              mintedSessionIdRef.current === resumeId))
        ) {
              blankTrace("blocked same-chat list wipe (fresh branch)", {
                count: prev.length,
                chatKey: _chatKey,
              });
              return prev;
            }
            // Fresh-mount transient-null race (same as the connect else-branch).
            // A bare-/chat re-run that minted no real chat key must not wipe a
            // live transcript. Deliberate new chats carry ?new=, so _chatKey is
            // never "__fresh_chat__" there.
            if (
              prev.length >= 2 &&
              _chatKey === "__fresh_chat__" &&
              renderedChatKeyRef.current != null &&
              renderedChatKeyRef.current !== "__fresh_chat__"
            ) {
              blankTrace("blocked fresh-mount transient-null wipe (fresh branch)", {
                count: prev.length,
                renderedKey: renderedChatKeyRef.current,
              });
              return prev;
            }
            renderedChatKeyRef.current = _chatKey;
            return [];
          });
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
          stillRunning &&
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
          // Adopt orphaned replay state. When the ring has rotated this
          // turn's message.start frame out, the replayed reasoning/tool
          // deltas above ran while currentAssistantRef was still null, so
          // they were tagged with messageId === undefined and never group
          // onto the resumed assistant turn — the digest renders empty
          // ("Working" with nothing under it). Re-tag every untagged trace
          // and tool onto the assistant message we just ensured so the
          // breakdown + live token meter render on reattach.
          const adoptId = currentAssistantRef.current;
          if (adoptId) {
            setActivityTrace((prev) =>
              prev.some((trace) => !trace.messageId)
                ? prev.map((trace) =>
                    trace.messageId ? trace : { ...trace, messageId: adoptId },
                  )
                : prev,
            );
            setTools((prev) =>
              prev.some((tool) => !tool.messageId)
                ? prev.map((tool) =>
                    tool.messageId ? tool : { ...tool, messageId: adoptId },
                  )
                : prev,
            );
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
                ts: rt.started_at,
                payload: {
                  tool_id: rt.tool_id,
                  name: rt.name,
                  context: rt.context ?? "",
                  started_at: rt.started_at,
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
          currentAssistantRef.current = null;
          setTools([]);
          setActivityTrace([]);
          setMessages((prev) => markStreamingTurnsInterrupted(prev));
          clearActiveTurnSnapshot(persistedSessionIdRef.current ?? resumeId);
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
      clearPendingAssistantDelta();
      activeSessionRef.current = null;
      currentAssistantRef.current = null;
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
    clearPendingAssistantDelta,
    enqueueAssistantDelta,
    ensureAssistant,
    flushAssistantDelta,
    gw,
    hydrateArtifactsFromMessages,
    newChatId,
    draftChat,
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

  // Load the effective Claude-style permission mode for this session once
  // the gateway is up. The mode is session-scoped (composer picker), so it
  // is re-fetched whenever the gateway session id changes.
  useEffect(() => {
    if (state !== "open" || !sessionId) return;
    let cancelled = false;
    gw
      .request<{ value?: string }>(
        "config.get",
        { key: "permission_mode", session_id: sessionId },
        8_000,
      )
      .then((res) => {
        if (!cancelled && res?.value) setPermissionModeId(res.value);
      })
      .catch(() => {
        /* permission mode is non-critical to chat */
      });
    return () => {
      cancelled = true;
    };
  }, [gw, state, sessionId]);

  const selectPermissionMode = useCallback(
    (mode: PermissionMode) => {
      setPermissionMenuOpen(false);
      setPermissionModeId((previous) => {
        if (previous === mode.id) return previous;
        void gw
          .request(
            "config.set",
            { key: "permission_mode", value: mode.id, session_id: sessionId },
            8_000,
          )
          .catch((error: Error) => {
            setPermissionModeId(previous);
            setStatusText(
              `Could not change permission mode: ${error.message}`,
            );
          });
        return mode.id;
      });
      setStatusText(`Permission mode: ${mode.label}`);
      window.requestAnimationFrame(() => inputRef.current?.focus());
    },
    [gw, sessionId],
  );

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

  const pinCreatedSessionInUrl = useCallback(() => {
    const pinnedId = persistedSessionIdRef.current;
    if (!pinnedId || resumeId) return;
    // Open the mint guard: the URL rewrite below re-runs the connect effect
    // under the minted id, which can wipe the live transcript before
    // renderedChatKeyRef catches up. Hold the guard a few seconds so the
    // wrapped setter blocks that populated -> empty wipe while it settles.
    mintGuardRef.current = true;
    if (mintGuardTimerRef.current) clearTimeout(mintGuardTimerRef.current);
    mintGuardTimerRef.current = setTimeout(() => {
      mintGuardRef.current = false;
      mintGuardTimerRef.current = null;
    }, 4000);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("new");
        next.delete("seed");
        next.set("resume", pinnedId);
        return next;
      },
      { replace: true },
    );
  }, [resumeId, setSearchParams]);

  const createSessionForSend = useCallback(async (): Promise<string | null> => {
    if (sessionId && state === "open") return sessionId;
    if (createSessionPromiseRef.current) return createSessionPromiseRef.current;

    const promise = (async () => {
      try {
        setStatusText("Starting chat...");
        await gw.connect();
        const created = await gw.request<SessionCreateResponse>("session.create", {
          cols: 100,
        });
        activeSessionRef.current = created.session_id;
        persistedSessionIdRef.current =
          created.persisted_session_id ?? null;
        setSessionId(created.session_id);
        setInfo(created.info ?? {});
        if (created.info?.credential_warning || created.info?.config_warning) {
          setBanner(
            created.info.credential_warning ?? created.info.config_warning ?? null,
          );
        }
        setStatusText("Ready");
        return created.session_id;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setBanner(`Could not start chat: ${message}`);
        setStatusText("Connection failed");
        return null;
      }
    })().finally(() => {
      createSessionPromiseRef.current = null;
    });

    createSessionPromiseRef.current = promise;
    return promise;
  }, [gw, sessionId, state]);

  const submitGatewayPrompt = useCallback(
    async (
      text: string,
      routedText: string,
      agentId: string,
      status = "Sending...",
      targetSessionId?: string,
      skipUserMessage = false,
    ) => {
      const effectiveSessionId = targetSessionId ?? sessionId;
      if (!effectiveSessionId) return;

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
      // When the caller already showed the user bubble optimistically (the
      // new-chat cold-start path), don't append it a second time.
      if (!skipUserMessage) {
        appendMessage(
          "user",
          text,
          messageAttachments.length ? { attachments: messageAttachments } : {},
        );
      }
      setBusy(true);
      setStatusText(status);

      try {
        for (const att of readyAttachments) {
          if (!att.path) continue;
          try {
            await gw.request("file.attach", {
              session_id: effectiveSessionId,
              path: att.path,
            });
          } catch (attachError) {
            const m = attachError instanceof Error ? attachError.message : String(attachError);
            appendMessage("system", `Failed to attach ${att.name}: ${m}`, { status: "error" });
          }
        }

        const payload: Record<string, unknown> = {
          session_id: effectiveSessionId,
          text: routedText,
        };
        if (routedText !== text) {
          payload.persist_user_message = text;
        }
        if (agentId) {
          payload.agent_id = agentId;
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

  // Skill slash commands (/cma-audit) load the full SKILL.md into the model's
  // context. The user already sees the `/command` bubble they typed, so the
  // payload stays hidden. If a turn is running, deliver it through steer so it
  // augments the live session instead of bouncing as "session busy".
  const submitSkillInvocation = useCallback(
    async (payload: string, commandName?: string, args?: string) => {
      if (!sessionId || state !== "open") return;
      const visibleCommand = commandName
        ? `/${commandName}${(args ?? "").trim() ? ` ${(args ?? "").trim()}` : ""}`
        : undefined;
      const steerSkillPayload = async () => {
        const response = await gw.request("session.steer", {
          session_id: sessionId,
          text: payload,
        });
        const status =
          response && typeof response === "object" && "status" in response
            ? String((response as Record<string, unknown>).status)
            : "queued";
        setStatusText(status === "rejected" ? "Steer rejected" : "Skill steered");
      };
      setStatusText(busy ? "Steering skill..." : "Loading skill...");
      try {
        if (busy) {
          await steerSkillPayload();
          return;
        }
        setBusy(true);
        const req: Record<string, unknown> = {
          session_id: sessionId,
          text: payload,
        };
        // Persist the command WITH its arguments so the reloaded transcript
        // shows what was actually asked. A bare `/${commandName}` collapses
        // every invocation into an identical chip — distinct runs become
        // indistinguishable duplicates after a refresh or session switch.
        if (visibleCommand) req.persist_user_message = visibleCommand;
        if (selectedAgent.id) req.agent_id = selectedAgent.id;
        await gw.request("prompt.submit", req);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (!busy && /^session busy\b/i.test(message)) {
          try {
            await steerSkillPayload();
            setBusy(true);
          } catch (steerError) {
            const steerMessage =
              steerError instanceof Error ? steerError.message : String(steerError);
            setBanner(`Skill steer failed: ${steerMessage}`);
            setStatusText("Steer failed");
          }
          return;
        }
        if (busy) {
          setBanner(`Skill steer failed: ${message}`);
          setStatusText("Steer failed");
          return;
        }
        appendMessage("system", message, { status: "error" });
        setBusy(false);
        setStatusText("Error");
      }
    },
    [appendMessage, busy, gw, selectedAgent, sessionId, state],
  );

  const interruptCurrentTurn = useCallback(() => {
    if (!sessionId || state !== "open") return;

    const activeAssistantId =
      currentAssistantRef.current ??
      [...messages]
        .reverse()
        .find((message) => message.role === "assistant" && message.status === "streaming")
        ?.id ??
      null;
    if (activeAssistantId) {
      stoppedAssistantIdsRef.current.add(activeAssistantId);
      currentAssistantRef.current = activeAssistantId;
      const stoppedAt = Date.now();
      setMessages((prev) => {
        const next = prev.map((message) =>
          message.id === activeAssistantId && message.status === "streaming"
            ? {
                ...message,
                completedAt: message.completedAt ?? stoppedAt,
                status: "interrupted" as const,
              }
            : message,
        );
        const persisted = persistedSessionIdRef.current ?? sessionId;
        if (persisted) {
          rememberTranscript(persisted, attachLiveActivitySnapshots(next, [], []));
        }
        return next;
      });
    } else {
      const stoppedAt = Date.now();
      setMessages((prev) => {
        const next = markStreamingTurnsInterrupted(prev, stoppedAt);
        const persisted = persistedSessionIdRef.current ?? sessionId;
        if (persisted && next !== prev) {
          rememberTranscript(persisted, attachLiveActivitySnapshots(next, [], []));
        }
        return next;
      });
    }
    setQueuedInputs([]);
    setTools([]);
    setActivityTrace([]);
    clearActiveTurnSnapshot(persistedSessionIdRef.current ?? sessionId);
    setSubagents((prev) =>
      prev.map((subagent) =>
        subagent.status === "running"
          ? { ...subagent, completedAt: Date.now(), status: "error" }
          : subagent,
      ),
    );
    setBusy(false);
    setStatusText("Stopping...");
    void gw
      .request("session.stop", { session_id: sessionId })
      .then(() => {
        setStatusText("Stopped");
      })
      .catch((error) => {
        void gw
          .request("session.interrupt", { session_id: sessionId })
          .then(() => {
            setStatusText("Interrupted");
          })
          .catch((interruptError) => {
            const message =
              interruptError instanceof Error
                ? interruptError.message
                : String(interruptError);
            const stopMessage = error instanceof Error ? error.message : String(error);
            setBanner(`Stop failed: ${stopMessage}; interrupt failed: ${message}`);
          });
      });
  }, [gw, messages, sessionId, state]);

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
      next.agentId,
      "Sending queued follow-up...",
    ).finally(() => {
      queueDispatchRef.current = false;
    });
  }, [busy, queuedInputs, sessionId, state, submitGatewayPrompt]);

  const hasReadyAttachment = attachments.some(
    (item) => item.status === "ready" && !!item.path,
  );

  // The textarea auto-grows via an inline style.height set on every
  // keystroke. Programmatic clears (sending a message, switching to a new
  // chat) don't fire onChange, so without this the box stays stuck at the
  // last multi-line height — placeholder pinned to the top of a tall box.
  useEffect(() => {
    if (input === "" && inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  }, [input]);

  const submitPrompt = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      // An attachment-only message (image with no caption) is a valid send.
      if (!trimmed && !hasReadyAttachment) return;

      // Tell the sidebar this chat just became active so it floats to the top
      // immediately, without waiting for the next poll. (Pairs with the
      // agent-turn-complete event fired on message.complete.)
      window.dispatchEvent(
        new CustomEvent("elevate:agent-turn-start", { detail: { sessionId } }),
      );

      setInput("");
      composerScrollTopRef.current = 0;
      if (richLayerRef.current) richLayerRef.current.style.transform = "translateY(0px)";
      setBanner(null);
      setAgentMenuOpen(false);
      // Sending a message (refine or execute) retires the current plan-ready
      // bar until the agent presents a fresh plan.
      setPlanReadyForApproval(false);

      const historyArtifacts = artifacts.length ? [] : artifactsFromMessages(messages);
      const availableArtifacts = artifacts.length ? artifacts : historyArtifacts;
      const previewTarget = bestSidePreviewArtifact(availableArtifacts);
      if (previewTarget && isOpenPreviewIntent(trimmed)) {
        if (historyArtifacts.length) {
          addArtifacts(historyArtifacts);
        }
        openArtifactPreview(previewTarget);
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
        let targetSessionId = sessionId;
        if (!targetSessionId && draftChat) {
          targetSessionId = await createSessionForSend();
        }
        if (!targetSessionId || (state !== "open" && !draftChat)) {
          setInput(trimmed);
          setStatusText("Connecting...");
          return;
        }
        appendMessage("user", trimmed);
        await executeSlash({
          callbacks: {
            send: submitPrompt,
            sendSkill: submitSkillInvocation,
            sys: (body) => appendMessage("system", body),
          },
          command: trimmed,
          gw,
          sessionId: targetSessionId,
        });
        pinCreatedSessionInUrl();
        return;
      }

      const routedText = routePromptForAgent(trimmed);
      let targetSessionId = sessionId;

      // New-chat cold start: creating the session takes a few seconds. Show the
      // user bubble + thinking animation INSTANTLY (before awaiting the session)
      // instead of leaving a dead, empty screen until the agent spins up. Only
      // for the no-attachment case so the attachment chips still render via the
      // normal append path.
      const needsSession = !targetSessionId && draftChat;
      const optimistic = needsSession && !hasReadyAttachment && !!trimmed;
      if (optimistic) {
        appendMessage("user", trimmed);
        setBusy(true);
        setStatusText("Thinking...");
      }

      if (needsSession) {
        targetSessionId = await createSessionForSend();
      }

      if (!targetSessionId || (state !== "open" && !draftChat)) {
        if (optimistic) setBusy(false);
        const queued: QueuedInput = {
          agentId: selectedAgent.id,
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
          agentId: selectedAgent.id,
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

      // Natural-language plan request → auto-enter plan mode for this turn so
      // the agent researches read-only and presents a plan. Persist it before
      // the agent runs so the backend turn sees the mode; flips the pill too.
      if (permissionModeId !== "plan" && looksLikePlanRequest(trimmed)) {
        try {
          await gw.request(
            "config.set",
            { key: "permission_mode", value: "plan", session_id: targetSessionId },
            8_000,
          );
          setPermissionModeId("plan");
          planAutoOpenDisabledRef.current = false;
          setStatusText("Plan mode — drafting a plan for your approval");
        } catch {
          /* non-fatal: fall through and run normally */
        }
      }

      await submitGatewayPrompt(
        trimmed,
        routedText,
        selectedAgent.id,
        "Sending...",
        targetSessionId,
        optimistic,
      );
      pinCreatedSessionInUrl();
    },
    [addArtifacts, appendMessage, artifacts, busy, createSessionForSend, draftChat, gw, hasReadyAttachment, messages, openArtifactPreview, permissionModeId, pinCreatedSessionInUrl, selectedAgent, sessionId, state, submitGatewayPrompt, submitSkillInvocation],
  );

  // Claude-Code-style plan approval: leave plan mode and immediately execute the
  // presented plan in one click (no manual /run, no "send 'go'").
  const approvePlanAndRun = useCallback(async () => {
    try {
      await gw.request(
        "config.set",
        { key: "permission_mode", value: "default", session_id: sessionId },
        8_000,
      );
    } catch {
      /* non-fatal: the execute message below still flips behavior */
    }
    setPermissionModeId("default");
    await submitPrompt("Approved — execute the plan now.");
  }, [gw, sessionId, submitPrompt]);

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
    } catch {
      // Seed cleanup is best-effort.
    }
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
    reconnectRunRef.current = true;
    window.setTimeout(() => {
      reconnectRunRef.current = false;
    }, 6000);
    setVersion((value) => value + 1);
  };

  // --- Stream liveness watchdog + mid-turn auto-reconnect -----------------
  // The agent loop runs server-side independently of the websocket. If the
  // socket silently stalls (frames stop arriving while it stays "open") or
  // drops mid-turn, the UI would otherwise sit dark forever while the turn
  // keeps running on the server. Detect that and bump `version`, which
  // re-runs the connect effect -> session.resume: it replays the server-side
  // ring buffer and restores running tools (the exact proven path used when
  // reattaching to a still-running session). Conservative by design: only
  // armed during an active turn, fires at most once per window, and a
  // spurious reconnect is harmless (resume just re-syncs).
  const lastFrameAtRef = useRef(Date.now());
  const stallReconnectAtRef = useRef(0);

  useEffect(() => {
    // Mark stream activity on every inbound frame.
    return gw.onAny(() => {
      lastFrameAtRef.current = Date.now();
    });
  }, [gw]);

  useEffect(() => {
    if (!busy) return;
    const STALL_MS = 45_000;
    const timer = window.setInterval(() => {
      const now = Date.now();
      if (now - stallReconnectAtRef.current < STALL_MS) return; // cooldown
      const droppedMidTurn = state === "closed" || state === "error";
      const stalledMidTurn =
        state === "open" && now - lastFrameAtRef.current > STALL_MS;
      if (droppedMidTurn || stalledMidTurn) {
        stallReconnectAtRef.current = now;
        lastFrameAtRef.current = now;
        reconnectRunRef.current = true;
        window.setTimeout(() => {
          reconnectRunRef.current = false;
        }, 6000);
        setVersion((value) => value + 1); // reconnect -> session.resume
      }
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [busy, state]);

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
      // "no pending ... request" (gateway error 4009) means the request the
      // agent was waiting on is already gone — the run finished, was
      // interrupted, or the gateway restarted out from under it. The prompt
      // box can never be answered, so dismiss it instead of leaving a dead
      // form on screen that re-errors on every Send.
      if (/no pending .* request/i.test(message)) {
        setPendingPrompt(null);
        setPromptValue("");
        setStatusText("Question expired");
        return;
      }
      appendMessage("system", message, { status: "error" });
    }
  };

  const voiceSupported = voiceCaptureSupported();

  // Ship a recorded mic blob to the gateway for server-side transcription
  // and append the returned text to the composer input.
  const transcribeRecording = useCallback(
    async (blob: Blob, mimeType: string) => {
      if (!blob.size) {
        setStatusText("No audio captured");
        return;
      }
      const epoch = ++transcribeEpochRef.current;
      const stale = () => transcribeEpochRef.current !== epoch;
      setVoiceTranscribing(true);
      setStatusText("Transcribing...");
      try {
        const base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onerror = () => reject(reader.error ?? new Error("read failed"));
          reader.onload = () => {
            const result = String(reader.result ?? "");
            const comma = result.indexOf(",");
            resolve(comma >= 0 ? result.slice(comma + 1) : result);
          };
          reader.readAsDataURL(blob);
        });

        // 45s cap, not the 120s default: a short voice clip should never
        // hold the mic hostage for two minutes if the server stalls.
        const response = await gw.request<{ text?: string }>(
          "voice.transcribe",
          {
            audio: base64,
            mime: (mimeType || blob.type || "audio/webm").split(";")[0],
          },
          45_000,
        );

        // User hit the mic again to cancel while this was in flight —
        // drop the result instead of clobbering the composer.
        if (stale()) return;

        const dictated = (response?.text ?? "").trim();
        if (!dictated) {
          setStatusText("No speech detected");
          return;
        }

        const nextInput = [voiceBaseInputRef.current.trimEnd(), dictated]
          .filter(Boolean)
          .join(" ");
        setInput(nextInput);
        setCaretIndex(nextInput.length);
        setStatusText("Voice captured");
        window.requestAnimationFrame(() => {
          const target = inputRef.current;
          if (!target) return;
          target.focus();
          target.setSelectionRange(nextInput.length, nextInput.length);
        });
      } catch (error) {
        if (stale()) return;
        const message = error instanceof Error ? error.message : String(error);
        setBanner(`Voice transcription failed: ${message}`);
        setStatusText("Voice input failed");
      } finally {
        // Only the still-current attempt clears the flag. A canceled
        // attempt already cleared it; clearing again here would be
        // harmless, but skipping it keeps the canceled path unambiguous.
        if (!stale()) setVoiceTranscribing(false);
      }
    },
    [gw],
  );

  const toggleVoiceInput = useCallback(async () => {
    // Don't pre-gate on a synchronous capability probe — it can read as
    // unsupported even when getUserMedia/MediaRecorder actually work in
    // this Electron build. Just attempt the capture; the try/catch below
    // surfaces a precise banner if an API really is missing.
    if (typeof navigator?.mediaDevices?.getUserMedia !== "function") {
      setBanner(
        "Microphone capture isn't available here. Make sure the app has mic access in System Settings.",
      );
      return;
    }

    // Stop an in-progress recording — onstop fires transcription.
    if (voiceListening) {
      try {
        mediaRecorderRef.current?.stop();
      } catch {
        // already stopped
      }
      setVoiceListening(false);
      return;
    }

    // Clicking the mic while it's transcribing cancels the attempt.
    // Bumping the epoch makes the in-flight transcribeRecording discard
    // its result, and clearing the flag here unlocks the button
    // immediately instead of leaving it spinning until the RPC settles.
    if (voiceTranscribing) {
      transcribeEpochRef.current += 1;
      setVoiceTranscribing(false);
      setStatusText("Voice input canceled");
      return;
    }

    voiceBaseInputRef.current = input;
    setBanner(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedMicId
          ? { deviceId: { exact: selectedMicId } }
          : true,
      });
      mediaStreamRef.current = stream;

      const mimeType = pickAudioMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const chunks = audioChunksRef.current;
        audioChunksRef.current = [];
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
        mediaRecorderRef.current = null;
        setVoiceListening(false);
        const blob = new Blob(chunks, {
          type: recorder.mimeType || mimeType || "audio/webm",
        });
        void transcribeRecording(blob, recorder.mimeType || mimeType);
      };
      recorder.onerror = () => {
        setBanner("Voice recording error.");
        setVoiceListening(false);
      };

      recorder.start();
      setVoiceListening(true);
      setStatusText("Listening... click the mic to stop");
    } catch (error) {
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
      const name = error instanceof Error ? error.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setBanner("Microphone access was denied. Allow mic access to use voice input.");
      } else if (name === "NotFoundError") {
        setBanner("No microphone was found.");
      } else {
        const message = error instanceof Error ? error.message : String(error);
        setBanner(`Could not start the microphone: ${message}`);
      }
      setVoiceListening(false);
    }
  }, [input, selectedMicId, transcribeRecording, voiceListening, voiceTranscribing]);

  const selectMicDevice = useCallback((deviceId: string) => {
    setSelectedMicId(deviceId);
    setVoiceMenuOpen(false);
  }, []);

  const canSend =
    (!!input.trim() || hasReadyAttachment) &&
    (state === "open" ? !!(sessionId || draftChat) : state !== "error" && state !== "closed");
  const canPickModel = state === "open" && !!sessionId;
  const traceMessageIds = useMemo(() => {
    const ids = new Set<string>();
    for (const trace of activityTrace) {
      if (trace.messageId) ids.add(trace.messageId);
    }
    return ids;
  }, [activityTrace]);
  const toolMessageIds = useMemo(() => {
    const ids = new Set<string>();
    for (const tool of tools) {
      if (tool.messageId) ids.add(tool.messageId);
    }
    return ids;
  }, [tools]);
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
        if (traceMessageIds.has(message.id)) return true;
        if (toolMessageIds.has(message.id)) return true;
        // Resumed turn: tools/traces live on the message snapshot, not
        // in the live state arrays.
        return Boolean(message.tools?.length || message.traces?.length);
      }),
    [messages, toolMessageIds, traceMessageIds],
  );
  const latestVisibleMessage = visibleMessages[visibleMessages.length - 1] ?? null;
  const latestVisibleMessageId = latestVisibleMessage?.id ?? "";
  const latestVisibleMessageContentLength = latestVisibleMessage?.content.length ?? 0;

  const handleChatScroll = useCallback((event: ReactUIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    chatStickToBottomRef.current = distanceFromBottom < 160;
  }, []);

  useLayoutEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;

    const force = pendingInitialBottomScrollRef.current;
    if (!force && !chatStickToBottomRef.current) return;

    const scrollToBottom = () => {
      el.scrollTop = el.scrollHeight;
    };

    scrollToBottom();
    pendingInitialBottomScrollRef.current = false;

    if (!force) return;

    const frame = window.requestAnimationFrame(scrollToBottom);
    const shortDelay = window.setTimeout(scrollToBottom, 0);
    const layoutDelay = window.setTimeout(scrollToBottom, 80);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(shortDelay);
      window.clearTimeout(layoutDelay);
    };
  }, [
    activityTrace.length,
    artifacts.length,
    latestVisibleMessageContentLength,
    latestVisibleMessageId,
    pendingPrompt,
    tools.length,
    visibleMessages.length,
  ]);
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
  // Unified background-task list for the panel: rich subagent lifecycle entries
  // (goal/model/tool-count) plus any background-coordination tool runs not
  // already represented by a subagent. Newest first.
  const backgroundTasks = useMemo<BackgroundTaskItem[]>(() => {
    const items: BackgroundTaskItem[] = [];
    for (const s of subagents) {
      items.push({
        id: s.id,
        kind: "subagent",
        label: s.goal || "Subagent",
        status: s.status,
        detail: s.preview,
        model: s.model,
        toolCount: s.toolCount,
        startedAt: s.startedAt,
        completedAt: s.completedAt,
      });
    }
    const haveSubagents = subagents.length > 0;
    for (const t of tools) {
      const isDelegate = t.name === "delegate" || t.name === "delegate_task";
      const isMixture = t.name === "mixture_of_agents";
      const isHandoff = t.name === "agent_handoff";
      // delegate_* is already covered by the subagent lifecycle when present;
      // only fall back to the tool row if no subagent entries exist.
      if (isMixture || isHandoff || (isDelegate && !haveSubagents)) {
        items.push({
          id: t.id,
          kind: isMixture ? "mixture" : isHandoff ? "handoff" : "subagent",
          label: isMixture
            ? "Mixture of agents"
            : isHandoff
              ? "Handoff"
              : t.context || "Subagent",
          status: t.status,
          detail: t.context || t.summary,
          startedAt: t.startedAt,
          completedAt: t.completedAt,
        });
      }
    }
    return items.sort((a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0));
  }, [subagents, tools]);
  const runningBackgroundTasks = useMemo(
    () => backgroundTasks.filter((task) => task.status === "running").length,
    [backgroundTasks],
  );
  // Pop the Background tasks panel open when a task first starts running — but
  // only if nothing else is already taking the side panel, so it never steals
  // a Preview/Plan the user is looking at.
  const prevRunningTasksRef = useRef(0);
  useEffect(() => {
    const prev = prevRunningTasksRef.current;
    prevRunningTasksRef.current = runningBackgroundTasks;
    if (runningBackgroundTasks > prev && prev === 0 && sidePanel === "none") {
      setSidePanel("tasks");
    }
  }, [runningBackgroundTasks, sidePanel]);
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
    // A self-minted+pinned id is a fresh chat, not a user resume — pass null
    // so an empty transcript reads "New chat", never "Resumed chat".
    () =>
      deriveChatTitle(
        visibleMessages,
        resumeId === mintedSessionIdRef.current ? null : resumeId,
        resumeFallback,
      ),
    [resumeFallback, resumeId, visibleMessages],
  );
  const [folderLabel, setFolderLabel] = useState<string | undefined>(undefined);
  const [workspaceStatus, setWorkspaceStatus] = useState<WorkspaceGitStatus | null>(() =>
    readCachedWorkspaceStatus(),
  );
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const previousWorkspaceBusyRef = useRef(false);

  const refreshWorkspaceStatus = useCallback(
    async (quiet = false, force = false) => {
      setWorkspaceLoading(true);
      try {
        const status = await api.getWorkspaceGitStatus({
          force,
          sessionId: persistedSessionIdRef.current ?? resumeId ?? sessionId,
          workingDirectory: info.cwd ?? null,
        });
        setWorkspaceStatus(status);
        writeCachedWorkspaceStatus(status);
        if (!quiet && status.error) {
          setBanner(`Workspace status unavailable: ${status.error}`);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (!quiet) setBanner(`Workspace status unavailable: ${message}`);
      } finally {
        setWorkspaceLoading(false);
      }
    },
    [info.cwd, resumeId, sessionId],
  );

  useEffect(() => {
    void refreshWorkspaceStatus(true);
  }, [refreshWorkspaceStatus]);

  useEffect(() => {
    if (previousWorkspaceBusyRef.current && !busy) {
      void refreshWorkspaceStatus(true);
    }
    previousWorkspaceBusyRef.current = busy;
  }, [busy, refreshWorkspaceStatus]);

  const openWorkspaceFolder = useCallback(async () => {
    try {
      const response = await api.openWorkspace(
        workspaceStatus?.working_directory || info.cwd || workspaceStatus?.path,
      );
      setBanner(`Opened ${response.path}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setBanner(`Could not open workspace: ${message}`);
    }
  }, [info.cwd, workspaceStatus?.path, workspaceStatus?.working_directory]);

  const openWorkspacePullRequest = useCallback(() => {
    if (!workspaceStatus?.pr_url) {
      setBanner("No pull request link is available for this branch.");
      return;
    }
    window.open(workspaceStatus.pr_url, "_blank", "noopener,noreferrer");
    setBanner("Opened pull request compare page.");
  }, [workspaceStatus?.pr_url]);

  const reviewWorkspaceChanges = useCallback(() => {
    const repo = workspaceStatus?.repo_name || folderLabel || "this repo";
    const workspace = workspaceStatus?.display_name || folderLabel || repo;
    const path = workspaceStatus?.working_directory || info.cwd || workspaceStatus?.path || "";
    const scope =
      workspaceStatus?.diff_scope === "session"
        ? "this chat's changes"
        : "the current repo changes";
    void submitPrompt(
      [
        `Review ${scope} in ${workspace} before I create a PR.`,
        path ? `Working folder: ${path}` : "",
        workspaceStatus?.repo_path ? `PR target repo: ${workspaceStatus.repo_path}` : "",
        "Look for bugs, risky changes, missing tests, and anything that should be cleaned up before pushing.",
        "Report findings only. Do not modify files unless I ask.",
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }, [
    folderLabel,
    info.cwd,
    submitPrompt,
    workspaceStatus?.diff_scope,
    workspaceStatus?.display_name,
    workspaceStatus?.path,
    workspaceStatus?.repo_name,
    workspaceStatus?.repo_path,
    workspaceStatus?.working_directory,
  ]);

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
        <span className="flex shrink-0 items-center gap-1.5 text-[13.5px] leading-6 text-[var(--fg-faint)]">
          <span>{folderLabel}</span>
          <span className="text-[var(--fg-dim)]">/</span>
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
          className="inline-flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--fg-faint)] transition-colors hover:bg-[color-mix(in_srgb,var(--fg)_6%,transparent)] hover:text-[var(--fg)]"
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
  // The right panel is open for ANY side-panel mode. Preview included — it
  // shows a "No preview" state when there's no artifact rather than being a
  // dead menu row.
  const wideOpen = sidePanel !== "none";
  // Preview shows file content, so it earns the big resizable 50/50. Plan /
  // Files / Background tasks are just breakdowns (lists) — they get a compact
  // fixed width and no resize handle.
  const isPreviewPanel = sidePanel === "preview";
  const previewPanelLayoutStyle = {
    // Every side panel (Preview / Plan / Files / Tasks / Artifacts) shares the
    // same drag-resizable width var, so they're all resizable, not just Preview.
    "--preview-panel-width": previewPanelWidthPx,
    ...(chatWidth ? { "--chat-layout-width-user": `${chatWidth}px` } : {}),
  } as CSSProperties;
  // Plan/Files data is keyed by the PERSISTED session id (where the message
  // history lives), not the live gateway sessionId — on resume the latter is a
  // freshly minted id with no history yet. This is the same id artifacts and
  // dismissals key on.
  const dataSessionId = artifactStateSessionId();
  const renderSidePanel = () => {
    switch (sidePanel) {
      case "preview":
        return previewArtifact ? (
          <ArtifactPreviewPane artifact={previewArtifact} onClose={dismissPreviewArtifact} />
        ) : (
          <EmptyPreviewPanel onClose={dismissPreviewArtifact} />
        );
      case "artifacts":
        return (
          <ArtifactsPanel
            artifacts={artifacts}
            onOpen={openArtifactPreview}
            onClose={closeSidePanel}
          />
        );
      case "plan":
        return (
          <PlanPanel
            sessionId={dataSessionId ?? ""}
            refreshSignal={planRefreshSignal}
            onClose={closeSidePanel}
          />
        );
      case "tasks":
        return <BackgroundTasksPanel tasks={backgroundTasks} onClose={closeSidePanel} />;
      case "files":
        return (
          <FilesPanel
            sessionId={dataSessionId ?? ""}
            onOpenFile={openFileInPreview}
            onClose={closeSidePanel}
          />
        );
      default:
        return null;
    }
  };
  const activity = (
    <ActivityPanel
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

  // Floating mobile Activity panel removed per request — the triggers are gone
  // so it can never open; kept mounted off-screen only to avoid a large
  // unused-symbol cascade. Never visible to the user.
  const mobileActivityPortal =
    narrow &&
    portalRoot &&
    mobilePanelOpen &&
    createPortal(
      <>
        <button
          aria-label="Close activity"
          className="fixed inset-0 z-[55] bg-black/55 backdrop-blur-sm"
          onClick={() => setMobilePanelOpen(false)}
          type="button"
        />
        <aside
          className={cn(
            "fixed right-4 top-4 z-[60] flex h-[52dvh] max-h-[32rem] min-h-[22rem] w-[min(24rem,calc(100vw-2rem))] flex-col",
            "normal-case translate-x-0 transition-transform duration-200 ease-out",
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
    wideOpen &&
    portalRoot &&
    createPortal(
      <>
        <button
          aria-label="Close panel"
          className="fixed inset-0 z-[65] bg-black/60 backdrop-blur-sm"
          onClick={sidePanel === "preview" ? dismissPreviewArtifact : closeSidePanel}
          type="button"
        />
        <aside className="fixed inset-x-3 bottom-3 top-3 z-[70] animate-in fade-in slide-in-from-bottom-4 duration-200">
          {renderSidePanel()}
        </aside>
      </>,
      portalRoot,
    );

  return (
    <div
      className="elevate-chat-shell relative flex h-full min-h-0 flex-col overflow-hidden bg-[var(--chat-bg)] text-[var(--chat-text)] normal-case"
      style={previewPanelLayoutStyle}
    >
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <section
          className={cn(
            // min-w-0 is critical: without it a flex child defaults to
            // min-width:auto and its content (long lines, composer, file-path
            // chips) pushes the column past the app's right edge, overflowing the
            // shell and clipping the preview. min-w-0 lets it shrink to fit.
            "flex min-h-0 min-w-0 flex-1 flex-col",
            isPreviewPanel && "lg:basis-1/2",
          )}
        >
          <div
            className="chat-top relative"
            style={{ WebkitAppRegion: "drag" } as CSSProperties}
          >
            {sidebarCollapsed && onShowSidebar ? (
              <button
                type="button"
                onClick={onShowSidebar}
                aria-label="Show sidebar"
                style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
                className="icon-btn absolute left-[18px] top-1/2 -translate-y-1/2"
              >
                <PanelLeftOpen className="h-3.5 w-3.5" />
              </button>
            ) : null}
            <div
              className="breadcrumb flex-1"
              style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
            >
              <SquareTerminal className="shrink-0 text-[var(--fg-faint)]" />
              {folderLabel ? (
                <span className="contents">
                  <span className="crumb">{folderLabel}</span>
                  <span className="sep">/</span>
                </span>
              ) : null}
              <h1 className="here">
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
                  className="chev"
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
            <div
              className="toggle-rail"
              style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
            >
              <SidePanelSelector
                mode={sidePanel}
                onSelect={handleSelectPanel}
                runningTasks={runningBackgroundTasks}
              />
            </div>
          </div>
          <div ref={chatScrollRef} className="chat-scroll" onScroll={handleChatScroll}>
            {visibleMessages.length === 0 ? (
              <EmptyState
                analytics={startAnalytics}
                loading={startAnalyticsLoading}
                onRangeChange={setStartRange}
                onViewChange={setStartView}
                range={startRange}
                state={state}
                userName={userName}
                view={startView}
              />
            ) : (
              <div className="chat-inner w-full">
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
                    <MemoMessageRow
                      key={message.id}
                      activityTrace={turnTraces}
                      artifacts={turnArtifacts ?? []}
                      busy={isStreaming && busy}
                      compacting={isStreaming && compacting}
                      message={message}
                      onEditMessage={handleEditMessage}
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
                    onDismiss={() => {
                      setPendingPrompt(null);
                      setPromptValue("");
                    }}
                  />
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <form
            className="composer-wrap relative"
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
            <div className="relative mx-auto w-full max-w-[var(--chat-layout-width)]" data-chat-col>
              {/* Drag handle to resize the chat column width (persisted). Sits in
                  the right margin; large screens only. */}
              <button
                type="button"
                aria-label="Resize chat width"
                title="Drag to resize chat width"
                onPointerDown={startChatResize}
                style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
                className="group absolute -right-4 top-0 z-10 hidden h-full w-4 cursor-col-resize items-center justify-center lg:flex"
              >
                <span className="h-16 w-1 rounded-full bg-transparent" />
              </button>
              {permissionModeId === "plan" && !busy && planReadyForApproval && (
                  <div className="mb-2 flex items-center gap-3 rounded-[10px] border border-[color-mix(in_srgb,var(--chat-accent)_38%,transparent)] bg-[color-mix(in_srgb,var(--chat-accent)_8%,var(--chat-bg))] px-3 py-2">
                    <Eye className="h-4 w-4 shrink-0 text-[var(--chat-accent)]" />
                    <div className="min-w-0 flex-1 text-[12.5px] leading-snug text-[var(--chat-text)]">
                      <span className="font-medium">Plan ready.</span>{" "}
                      <span className="text-[var(--chat-muted-strong)]">
                        Reply to refine it, or approve to run.
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => void approvePlanAndRun()}
                      className="shrink-0 rounded-[7px] bg-[var(--chat-accent)] px-3 py-1.5 text-[12px] font-semibold text-[var(--chat-bg)] transition-opacity hover:opacity-90"
                    >
                      Approve &amp; run
                    </button>
                  </div>
                )}
              {queuedInputs.length ? (
                <QueuedInputStrip
                  busy={busy}
                  onRemove={removeQueuedInput}
                  onSteer={steerQueuedInput}
                  queuedInputs={queuedInputs}
                />
              ) : (
                <MemoComposerStageBar
                  folderLabel={folderLabel}
                  info={info}
                  loading={workspaceLoading}
                  onOpenPullRequest={openWorkspacePullRequest}
                  onOpenWorkspace={openWorkspaceFolder}
                  onRefresh={() => void refreshWorkspaceStatus(false, true)}
                  onReview={reviewWorkspaceChanges}
                  status={workspaceStatus}
                />
              )}

              <div className="composer relative">
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
                  onSubmit={(nextInput) => {
                    void submitPrompt(nextInput);
                  }}
                />

                <div className="flex min-w-0 flex-1 items-center gap-1">
                  <div className="composer-input-wrap min-h-[22px]">
                  <ComposerRichInputLayer
                    input={input}
                    layerRef={richLayerRef}
                  />
                  <textarea
                    ref={inputRef}
                    aria-autocomplete="list"
                    aria-controls="slash-popover-listbox"
                    aria-label="Message Elevation Agent"
                    className={cn(
                      "composer-input block",
                      "caret-[var(--chat-text)] selection:bg-[#5d5d5d] selection:text-white",
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
                        : "Message Elevation Agent..."
                    }
                    rows={1}
                    spellCheck
                    value={input}
                  />
                  </div>
                  <button
                    aria-label={busy ? "Interrupt response" : "Send message"}
                    className={cn(
                      "stop-btn",
                      busy
                        ? "text-[var(--chat-warning)]"
                        : canSend
                          ? "text-[var(--chat-muted-strong)]"
                          : "text-[var(--chat-muted)]",
                    )}
                    disabled={busy ? state !== "open" : !canSend}
                    onClick={busy ? interruptCurrentTurn : undefined}
                    title={busy ? "Stop the current response" : "Send message"}
                    type={busy ? "button" : "submit"}
                  >
                    {busy ? (
                      <Square className="fill-current" />
                    ) : (
                      <CornerDownLeft className="h-4 w-4 -translate-y-[1.5px]" />
                    )}
                  </button>
                </div>
              </div>

              <ComposerActionBar
                agentLocked={agentLocked}
                agentMenuOpen={agentMenuOpen}
                agents={activeComposerAgents}
                canPickModel={canPickModel}
                info={info}
                onAttach={onPaperclipClick}
                onOpenModel={() => setModelOpen(true)}
                onSelectAgent={selectComposerAgent}
                onToggleAgentMenu={() => {
                  setAgentMenuOpen((open) => !open);
                }}
                onToggleVoice={toggleVoiceInput}
                onToggleVoiceMenu={() => setVoiceMenuOpen((open) => !open)}
                onSelectMic={selectMicDevice}
                micDevices={micDevices}
                selectedMicId={selectedMicId}
                voiceMenuOpen={voiceMenuOpen}
                permissionMode={resolvePermissionMode(permissionModeId)}
                permissionMenuOpen={permissionMenuOpen}
                onTogglePermissionMenu={() =>
                  setPermissionMenuOpen((open) => !open)
                }
                onSelectPermissionMode={selectPermissionMode}
                selectedAgent={selectedAgent}
                usage={usage}
                voiceListening={voiceListening}
                voiceTranscribing={voiceTranscribing}
                voiceSupported={voiceSupported}
              />
            </div>
          </form>
        </section>

        <aside
          className={cn(
            "hidden min-h-0 shrink-0 lg:flex",
            wideOpen
              ? "flex-col pb-[var(--sidebar-gap)] pl-0 pr-[var(--sidebar-gap)] pt-[var(--sidebar-gap)]"
              // No activity card anymore — collapse the reserved column to zero
              // width so the chat reclaims the space when no panel is open.
              : "w-0 overflow-hidden",
          )}
          style={
            wideOpen ? { width: "var(--preview-panel-width)" } : undefined
          }
        >
          <div
            className={cn(
              "relative",
              wideOpen
                ? "min-h-0 flex-1"
                : "max-h-[calc(100dvh-2.5rem)] overflow-hidden",
            )}
          >
            {wideOpen && (
              <button
                aria-label="Resize panel"
                className="absolute -left-5 top-6 z-20 flex h-[calc(100%-3rem)] w-11 touch-none cursor-col-resize items-center justify-center rounded-full text-[var(--chat-muted)] transition hover:text-[var(--chat-text)]"
                onPointerDown={startPreviewResize}
                type="button"
              >
                <span className="h-12 w-1.5 rounded-full bg-transparent" />
              </button>
            )}
            {/* Activity card removed per request — the right area only shows a
                side panel (Preview / Artifacts / Files / Background tasks / Plan)
                when one is open; otherwise nothing. */}
            {wideOpen ? renderSidePanel() : null}
          </div>
        </aside>
      </div>
      {mobileActivityPortal}
      {mobilePreviewPortal}
      {modelOpen && canPickModel && sessionId && (
        <ModelPickerDialog
          gw={gw}
          onClose={() => setModelOpen(false)}
          onSubmit={(slashCommand) => {
            void executeSlash({
              callbacks: {
                send: submitPrompt,
                sendSkill: submitSkillInvocation,
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

function EmptyState({
  analytics,
  loading,
  onRangeChange,
  onViewChange,
  range,
  state,
  userName,
  view,
}: {
  analytics: AnalyticsResponse | null;
  loading: boolean;
  onRangeChange: (range: StartAnalyticsRange) => void;
  onViewChange: (view: "overview" | "models") => void;
  range: StartAnalyticsRange;
  state: ConnectionState;
  userName: string;
  view: "overview" | "models";
}) {
  const totalTokens =
    (analytics?.totals.total_input ?? 0) +
    (analytics?.totals.total_output ?? 0) +
    (analytics?.totals.total_cache_read ?? 0) +
    (analytics?.totals.total_reasoning ?? 0);
  const mostActiveDay = (analytics?.daily ?? []).reduce<AnalyticsResponse["daily"][number] | null>(
    (best, day) => {
      const tokens = day.input_tokens + day.output_tokens + day.reasoning_tokens;
      const bestTokens = best
        ? best.input_tokens + best.output_tokens + best.reasoning_tokens
        : -1;
      return tokens > bestTokens ? day : best;
    },
    null,
  );
  const metrics = [
    { label: "Sessions", value: formatCompactNumber(analytics?.totals.total_sessions) },
    { label: "Calls", value: formatCompactNumber(analytics?.totals.total_api_calls) },
    { label: "Total tokens", value: formatCompactNumber(totalTokens) },
    { label: "Active days", value: formatCompactNumber(activeDayCount(analytics)) },
    { label: "Current streak", value: `${currentActivityStreak(analytics)}d` },
    { label: "Longest streak", value: `${longestActivityStreak(analytics)}d` },
    {
      label: "Peak day",
      value: mostActiveDay
        ? new Date(`${mostActiveDay.day}T12:00:00`).toLocaleDateString([], {
            month: "short",
            day: "numeric",
          })
        : "pending",
    },
    { label: "Favorite model", value: favoriteModel(analytics) },
  ];
  const heatmapDays = usageHeatmapDays(analytics, range);
  const heatmapWindow = heatmapWindowLabel(analytics, range, heatmapDays);
  const modelRows = analytics?.by_model?.slice(0, 6) ?? [];

  return (
    <div className="chat-start">
      <div className="chat-start-title">
        <span className="chat-start-mark" aria-hidden="true">
          {state === "connecting" ? (
            <Loader2 className="h-5 w-5 animate-spin" />
          ) : (
            <Sparkles className="h-5 w-5" />
          )}
        </span>
        <h2>{`What's up next, ${userName}?`}</h2>
      </div>
      <section className="chat-start-card" aria-label="Usage overview">
        <div className="chat-start-toolbar">
          <div className="chat-start-tabs" role="tablist" aria-label="Start view">
            {(["overview", "models"] as const).map((item) => (
              <button
                key={item}
                aria-pressed={view === item}
                className={cn("chat-start-tab", view === item && "active")}
                onClick={() => onViewChange(item)}
                type="button"
              >
                {item === "overview" ? "Overview" : "Models"}
              </button>
            ))}
          </div>
          <div className="chat-start-tabs compact" aria-label="Usage range">
            {([
              ["all", "All"],
              ["30d", "30d"],
              ["7d", "7d"],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                aria-pressed={range === key}
                className={cn("chat-start-tab", range === key && "active")}
                onClick={() => onRangeChange(key)}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {view === "overview" ? (
          <>
            <div className="chat-start-window">{heatmapWindow}</div>
            <div className="chat-start-metrics">
              {metrics.map((metric) => (
                <div className="chat-start-metric" key={metric.label}>
                  <span>{metric.label}</span>
                  <strong>{loading ? "..." : metric.value}</strong>
                </div>
              ))}
            </div>
            <div className="chat-start-heatmap" aria-label="Recent activity">
              {heatmapDays.map((day) => (
                <span
                  aria-label={day.tip.replace(/\n/g, ", ")}
                  className={`chat-start-heat heat-${day.level}`}
                  data-tip={day.tip}
                  key={day.key}
                  tabIndex={0}
                  title={day.tip}
                />
              ))}
            </div>
            <p className="chat-start-note">
              {loading
                ? "Loading activity"
                : `${formatCompactNumber(totalTokens)} tokens in ${analyticsRangeLabel(range).toLowerCase()}.`}
            </p>
          </>
        ) : (
          <div className="chat-start-models">
            {modelRows.length ? (
              modelRows.map((model) => {
                const tokens = model.input_tokens + model.output_tokens;
                return (
                  <div className="chat-start-model" key={model.model}>
                    <span className="model-name">{model.model.split("/").slice(-1)[0] || model.model}</span>
                    <span>{formatCompactNumber(tokens)} tokens</span>
                    <span>{formatCompactNumber(model.sessions)} sessions</span>
                  </div>
                );
              })
            ) : (
              <div className="chat-start-empty-models">
                {loading ? "Loading models" : "No model activity yet"}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function ComposerStageBar({
  folderLabel,
  info,
  loading,
  onOpenPullRequest,
  onOpenWorkspace,
  onRefresh,
  onReview,
  status,
}: {
  folderLabel?: string;
  info: SessionInfo;
  loading: boolean;
  onOpenPullRequest(): void;
  onOpenWorkspace(): void;
  onRefresh(): void;
  onReview(): void;
  status: WorkspaceGitStatus | null;
}) {
  const cwdLabel = info.cwd
    ?.replace(/\/+$/, "")
    .split("/")
    .filter(Boolean)
    .pop();
  const repo = status?.repo_name || folderLabel || cwdLabel || "workspace";
  const workspace = status?.display_name || cwdLabel || repo;
  const branch = status?.branch || (info.cwd ? "local" : "workspace");
  const branchMeta = [
    status?.ahead ? `↑${status.ahead}` : "",
    status?.behind ? `↓${status.behind}` : "",
  ].filter(Boolean).join(" ");
  const changedFiles = status?.changed_files ?? 0;
  const insertions = status?.insertions ?? 0;
  const deletions = status?.deletions ?? 0;
  const hasChanges = Boolean(status?.dirty || changedFiles);
  const pathTitle = [
    status?.working_directory || info.cwd || status?.path || repo,
    status?.repo_path && status.repo_path !== (status.working_directory || info.cwd)
      ? `PR target: ${status.repo_path}`
      : "",
  ].filter(Boolean).join("\n");
  const branchTitle = [
    status?.upstream ? `Upstream: ${status.upstream}` : "Refresh branch status",
    status?.short_sha ? `Commit: ${status.short_sha}` : "",
    status?.error ? `Error: ${status.error}` : "",
  ].filter(Boolean).join("\n");
  const diffTitle =
    status?.diff_scope === "session"
      ? "This chat's changes since it opened"
      : "Current repo working tree changes";

  return (
    <div className="composer-stage">
      <button className="stage-link workspace" type="button" onClick={onOpenWorkspace} title={pathTitle}>
        <Folder aria-hidden="true" />
        <span className="repo">{workspace}</span>
      </button>
      <button className="stage-link" type="button" onClick={onRefresh} title={branchTitle}>
        <GitBranch aria-hidden="true" />
        <span className="branch">{branch}</span>
        {branchMeta ? <span className="branch-meta">{branchMeta}</span> : null}
      </button>
      <div className="stage-spacer" />
      <button
        className={cn("diff-stat", !hasChanges && "clean")}
        disabled={loading && !status}
        onClick={onReview}
        title={hasChanges ? diffTitle : `${diffTitle}: clean`}
        type="button"
      >
        {loading && !status ? (
          <span>checking</span>
        ) : hasChanges ? (
          <>
            <span className="add">+{insertions.toLocaleString()}</span>
            <span className="del">-{deletions.toLocaleString()}</span>
            <span className="files">{changedFiles.toLocaleString()} files</span>
          </>
        ) : (
          <span>clean</span>
        )}
      </button>
      <button
        className="stage-action"
        disabled={loading && !status}
        onClick={onReview}
        title="Ask Elevation to review these changes"
        type="button"
      >
        <Eye aria-hidden="true" />
        <span>Review</span>
      </button>
      <button
        className="stage-action pr"
        disabled={!status?.pr_url}
        onClick={onOpenPullRequest}
        title={status?.pr_url ? "Open GitHub compare page" : "PR link unavailable for this branch"}
        type="button"
      >
        <ExternalLink aria-hidden="true" />
        <span>Create PR</span>
      </button>
    </div>
  );
}

const MemoComposerStageBar = memo(ComposerStageBar);

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
    <>
      {queuedInputs.map((item) => (
        <div className="steer-bar" key={item.id} role="status">
          <span className="steer-tag">
            {item.status === "error" ? "ERROR" : "QUEUED"}
          </span>
          <span className="steer-text" title={item.text}>{item.text}</span>
          <span className="steer-hint">
            {item.status === "error" ? "not sent" : busy ? "waits for current turn" : nowLabel(item.createdAt)}
          </span>
          <div className="steer-actions">
            <button
              className="steer-btn cancel"
              type="button"
              onClick={() => onRemove(item.id)}
            >
              Cancel
            </button>
            {busy && item.status !== "error" ? (
              <button
                className="steer-btn steer"
                type="button"
                onClick={() => onSteer(item.id)}
              >
                Steer now
              </button>
            ) : null}
          </div>
        </div>
      ))}
    </>
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
              className="group relative h-16 w-16 overflow-hidden rounded-[7px] border border-[var(--chat-border)] bg-[var(--chat-surface-soft)]"
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
                className="absolute right-0.5 top-0.5 inline-flex h-4 w-4 items-center justify-center rounded-[5px] bg-[var(--chat-bg)]/80 text-[var(--chat-muted)] transition-colors hover:text-[var(--chat-text)]"
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
              "group flex items-center gap-1.5 rounded-[7px] px-2 py-1 text-[0.68rem]",
              isError
                ? "bg-[color-mix(in_srgb,var(--chat-danger)_14%,var(--chat-bg))] text-[var(--chat-danger)]"
                : "border border-[var(--chat-border)] bg-[var(--chat-surface-soft)] text-[var(--chat-muted-strong)]",
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
              className="inline-flex h-4 w-4 items-center justify-center rounded-[5px] text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-bg)] hover:text-[var(--chat-text)]"
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
    <div className="input-mirror">
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
              className="skill-token"
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

// (WorkingDots removed — the running indicator now lives on the sidebar chat
// row, not the composer footer.)

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
      className="inline-flex h-7 items-center gap-1.5 rounded-[7px] bg-[color-mix(in_srgb,var(--chat-text)_4%,transparent)] px-2.5 text-[var(--chat-muted-strong)]"
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

const composerMenuSurfaceClass =
  "absolute bottom-[calc(100%+6px)] left-0 z-30 overflow-hidden rounded-[10px] border border-[var(--chat-border-strong)] bg-[var(--chat-surface)] p-1 text-left shadow-[0_24px_60px_-16px_rgba(0,0,0,0.7),0_1px_0_rgba(255,255,255,0.03)_inset]";
const composerMenuLabelClass =
  "px-2.5 py-1.5 text-[11px] font-mono uppercase tracking-[0.08em] text-[var(--chat-muted)]";
function composerMenuItemClass(active: boolean) {
  return cn(
    "flex w-full items-start gap-2 rounded-[6px] px-2.5 py-2 text-left text-[12.5px] transition-colors",
    active
      ? "bg-[var(--chat-accent-soft)] text-[var(--chat-text)]"
      : "text-[var(--chat-muted-strong)] hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]",
  );
}

function ComposerActionBar({
  agentLocked,
  agentMenuOpen,
  agents,
  canPickModel,
  info,
  micDevices,
  onAttach,
  onOpenModel,
  onSelectAgent,
  onSelectMic,
  onToggleAgentMenu,
  onToggleVoice,
  onToggleVoiceMenu,
  permissionMode,
  permissionMenuOpen,
  onTogglePermissionMenu,
  onSelectPermissionMode,
  selectedAgent,
  selectedMicId,
  usage,
  voiceListening,
  voiceMenuOpen,
  voiceSupported,
  voiceTranscribing,
}: {
  agentLocked: boolean;
  agentMenuOpen: boolean;
  agents: ComposerAgent[];
  canPickModel: boolean;
  info: SessionInfo;
  micDevices: MicDevice[];
  onAttach(): void;
  onOpenModel(): void;
  onSelectAgent(agent: ComposerAgent): void;
  onSelectMic(deviceId: string): void;
  onToggleAgentMenu(): void;
  onToggleVoice(): void;
  onToggleVoiceMenu(): void;
  permissionMode: PermissionMode;
  permissionMenuOpen: boolean;
  onTogglePermissionMenu(): void;
  onSelectPermissionMode(mode: PermissionMode): void;
  selectedAgent: ComposerAgent;
  selectedMicId: string;
  usage: UsageInfo | null;
  voiceListening: boolean;
  voiceMenuOpen: boolean;
  voiceSupported: boolean;
  voiceTranscribing: boolean;
}) {
  return (
    <div className="composer-foot">
      <div className="flex min-w-0 items-center gap-1">
        {/* Only the agent picker row scrolls. The voice cluster stays a
            sibling OUTSIDE this overflow box — an upward-opening menu
            inside an overflow-x-auto container gets clipped to nothing
            (overflow-x:auto forces overflow-y to auto per CSS spec). */}
        <div className="flex min-w-0 items-center gap-1 overflow-x-auto scrollbar-none">
        <button
          type="button"
          onClick={onAttach}
          className="foot-btn icon-only"
          title="Attach files"
          aria-label="Attach files"
        >
          <Paperclip className="h-3.5 w-3.5" />
        </button>

        <div className="relative">
          <button
            type="button"
            onClick={onToggleAgentMenu}
            disabled={agentLocked}
            className={cn(
              "foot-btn max-w-[12rem]",
              agentMenuOpen && "text-[var(--chat-text)]",
              agentLocked && "cursor-default",
            )}
            title={
              agentLocked
                ? `Running as ${selectedAgent.name} — start a new chat to switch agents`
                : "Choose agent lane"
            }
          >
            <span className="truncate">{selectedAgent.name}</span>
            {!agentLocked && (
              <ChevronUp className="h-3 w-3 shrink-0 opacity-50" />
            )}
          </button>

          {agentMenuOpen && !agentLocked && (
            <>
              <div className="fixed inset-0 z-20" onClick={onToggleAgentMenu} />
              <div
                className={cn(composerMenuSurfaceClass, "w-[18rem]")}
                onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); onToggleAgentMenu(); } }}
                role="menu"
              >
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    role="menuitem"
                    onClick={() => onSelectAgent(agent)}
                    className={composerMenuItemClass(selectedAgent.id === agent.id)}
                  >
                    <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">
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

        </div>

        {/* Permission mode picker. Sits OUTSIDE the overflow box above so
            its upward-opening menu is not clipped (overflow-x:auto forces
            overflow-y to auto per CSS spec). */}
        <div className="relative flex shrink-0 items-center">
          <button
            type="button"
            onClick={onTogglePermissionMenu}
            className={cn(
              "foot-btn",
              permissionMenuOpen && "text-[var(--chat-text)]",
              permissionMode.id === "bypassPermissions" && "warn",
            )}
            title={`Permission mode: ${permissionMode.label}`}
            aria-label="Choose permission mode"
          >
            {permissionMode.id === "bypassPermissions" && <span className="pill-dot" />}
            <permissionMode.icon className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{permissionMode.short}</span>
            <ChevronUp className="h-3 w-3 shrink-0 opacity-50" />
          </button>

          {permissionMenuOpen && (
            <>
              <div
                className="fixed inset-0 z-20"
                onClick={onTogglePermissionMenu}
              />
              <div
                className={cn(composerMenuSurfaceClass, "w-[19rem]")}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    onTogglePermissionMenu();
                  }
                }}
                role="menu"
              >
                <div className={composerMenuLabelClass}>
                  Permission mode
                </div>
                {PERMISSION_MODES.map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    role="menuitem"
                    onClick={() => onSelectPermissionMode(mode)}
                    className={composerMenuItemClass(permissionMode.id === mode.id)}
                  >
                    <mode.icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">
                        {mode.label}
                      </span>
                      <span className="mt-0.5 line-clamp-2 text-[0.68rem] leading-4 text-[var(--chat-muted)]">
                        {mode.description}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="relative flex shrink-0 items-center">
          <button
            type="button"
            onClick={onToggleVoice}
            className={cn(
              "foot-btn icon-only",
              voiceListening && "recording",
            )}
            title={
              voiceTranscribing
                ? "Cancel transcription"
                : voiceListening
                  ? "Stop recording"
                  : voiceSupported
                    ? "Voice to text"
                    : "Voice to text (unavailable here)"
            }
            aria-label="Voice to text"
          >
            {voiceTranscribing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Mic className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={onToggleVoiceMenu}
            className={cn("foot-btn icon-only !w-5", voiceMenuOpen && "text-[var(--chat-text)]")}
            title="Select microphone"
            aria-label="Select microphone"
          >
            <ChevronUp className="h-3 w-3 opacity-60" />
          </button>

          {voiceMenuOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={onToggleVoiceMenu} />
              <div
                className={cn(composerMenuSurfaceClass, "w-[16rem]")}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.preventDefault();
                    onToggleVoiceMenu();
                  }
                }}
                role="menu"
              >
                <div className={composerMenuLabelClass}>
                  Microphone
                </div>
                {micDevices.length === 0 ? (
                  <div className="px-2.5 py-2 text-[0.68rem] text-[var(--chat-muted)]">
                    No microphones detected
                  </div>
                ) : (
                  micDevices.map((device) => (
                    <button
                      key={device.deviceId || device.label}
                      type="button"
                      role="menuitem"
                      onClick={() => onSelectMic(device.deviceId)}
                      className={composerMenuItemClass(selectedMicId === device.deviceId)}
                    >
                      <Mic className="h-3.5 w-3.5 shrink-0" />
                      <span className="min-w-0 flex-1 truncate">
                        {device.label}
                      </span>
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="foot-spacer" />

      <div className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={onOpenModel}
          disabled={!canPickModel}
          className="model-pill disabled:cursor-not-allowed disabled:opacity-50"
          title="Change model"
        >
          <span>{modelLabel(info)}</span>
        </button>
        <ContextRing usage={usage} />
      </div>
    </div>
  );
}

function MessageRow({
  activityTrace,
  artifacts,
  busy,
  compacting,
  message,
  onEditMessage,
  onOpenArtifact,
  tools,
  turnArtifacts,
}: {
  activityTrace?: ActivityTrace[];
  artifacts: ArtifactEntry[];
  busy?: boolean;
  compacting?: boolean;
  message: ChatMessage;
  onEditMessage?(message: ChatMessage): void;
  onOpenArtifact(artifact: ArtifactEntry): void;
  tools?: ToolEntry[];
  turnArtifacts?: ArtifactEntry[];
}) {
  const { copied, copy } = useCopyToClipboard();
  const [menuOpen, setMenuOpen] = useState(false);
  const [pinned, setPinned] = useState(() => readPinnedMessageIds().has(message.id));
  const menuRef = useRef<HTMLDivElement | null>(null);
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  useEffect(() => {
    setPinned(readPinnedMessageIds().has(message.id));
  }, [message.id]);

  useEffect(() => {
    if (!menuOpen) return;
    const closeIfOutside = (event: MouseEvent | PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

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
  const copyText = [
    message.content,
    ...(message.attachments ?? []).map((attachment) => attachment.name),
  ].filter(Boolean).join("\n");
  const messageTime = nowLabel(message.completedAt ?? message.createdAt);
  const latestArtifact = artifacts[artifacts.length - 1] ?? null;
  const togglePinned = () => {
    setPinned((current) => {
      const next = !current;
      writePinnedMessageId(message.id, next);
      return next;
    });
  };

  return (
    <article
      className={cn(
        "group flex w-full text-left",
        isUser && "justify-end",
        isAssistant && "pt-3 first:pt-0",
      )}
    >
      <div
        className={cn(
          // Match the responsive chat column width so messages grow/shrink with
          // the app window (Claude-like) instead of a fixed ~74ch.
          "min-w-0 flex-1 max-w-[var(--chat-layout-width)]",
          isUser && "flex flex-col items-end",
        )}
      >
        {showDigest ? (
          <ChatActivityDigest
            activityTrace={activityTrace ?? []}
            artifacts={turnArtifacts ?? []}
            busy={!!busy}
            compacting={!!compacting}
            completedAt={message.completedAt}
            liveTokens={liveTokens}
            startedAt={message.createdAt}
            tokenCount={message.tokenCount}
            tools={tools ?? []}
          />
        ) : null}
        <div
          className={cn(
            "max-w-full",
            isUser
              ? "user-msg inline-block"
              : message.role === "system"
                ? "rounded-[8px] border border-[color-mix(in_srgb,var(--chat-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_10%,var(--chat-bg))] px-3 py-2 text-[14px] leading-[1.55] text-[var(--chat-text)]"
                : "asst-msg",
            showDigest ? "mt-2" : null,
          )}
        >
          {message.role === "assistant" ? (
            message.content ? (
              <div className="chat-message-prose [&>div]:text-[var(--chat-text)] [&_a]:text-[var(--chat-accent)] [&_code]:bg-[color-mix(in_srgb,var(--fg)_5%,transparent)] [&_code]:text-[color-mix(in_srgb,var(--accent)_30%,var(--fg))] [&_pre]:border-[var(--border-soft)] [&_pre]:bg-[color-mix(in_srgb,#000_18%,var(--bg-2))]">
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
                          className="block overflow-hidden rounded-[7px] border border-[var(--chat-border-strong)] bg-[var(--chat-surface-soft)]"
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
                        className="inline-flex items-center gap-1.5 rounded-[7px] border border-[var(--chat-border-strong)] bg-[var(--chat-surface-soft)] px-2 py-1 text-[0.7rem] text-[var(--chat-muted)]"
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
          {(() => {
            // Tool/subagent execution outputs (browser_navigate, terminal, …)
            // belong in the Background tasks panel, not inline under the
            // message. Only surface durable file/document artifacts here.
            const inlineArtifacts = artifacts.filter(
              (a) => a.kind !== "output",
            );
            if (!inlineArtifacts.length) return null;
            return (
              <div className="mt-3 space-y-2">
                {inlineArtifacts.slice(-4).map((artifact) => (
                  <InlineArtifactCard
                    key={`message-artifact-${artifact.id}`}
                    artifact={artifact}
                    onOpenArtifact={onOpenArtifact}
                  />
                ))}
              </div>
            );
          })()}
        </div>
        {isUser ? (
          <div className="user-actions">
            <button
              className="icon-btn sm"
              onClick={() => copy(copyText)}
              title={copied ? "Copied" : "Copy"}
              type="button"
            >
              {copied ? <CheckCircle2 /> : <Clipboard />}
            </button>
            <button
              className="icon-btn sm"
              disabled={!message.content.trim()}
              onClick={() => onEditMessage?.(message)}
              title="Edit"
              type="button"
            >
              <FilePen />
            </button>
          </div>
        ) : isAssistant && message.content ? (
          <div className={cn("asst-actions", pinned && "pinned")}>
            <button
              className="icon-btn sm"
              onClick={() => copy(copyText)}
              title={copied ? "Copied" : "Copy"}
              type="button"
            >
              {copied ? <CheckCircle2 /> : <Clipboard />}
            </button>
            <button
              aria-pressed={pinned}
              className={cn("icon-btn sm", pinned && "message-action-active")}
              onClick={togglePinned}
              title={pinned ? "Unpin" : "Pin"}
              type="button"
            >
              <Pin />
            </button>
            <div className="message-action-wrap" ref={menuRef}>
              <button
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                className={cn("icon-btn sm", menuOpen && "message-action-active")}
                onClick={() => setMenuOpen((open) => !open)}
                title="More"
                type="button"
              >
                <MoreHorizontal />
              </button>
              {menuOpen && (
                <div className="message-actions-menu" role="menu">
                  <button
                    onClick={() => {
                      copy(copyText);
                      setMenuOpen(false);
                    }}
                    role="menuitem"
                    type="button"
                  >
                    Copy message
                  </button>
                  <button
                    onClick={() => {
                      togglePinned();
                      setMenuOpen(false);
                    }}
                    role="menuitem"
                    type="button"
                  >
                    {pinned ? "Unpin message" : "Pin message"}
                  </button>
                  <button
                    onClick={() => {
                      copy(message.id);
                      setMenuOpen(false);
                    }}
                    role="menuitem"
                    type="button"
                  >
                    Copy message ID
                  </button>
                  <button
                    disabled={!latestArtifact}
                    onClick={() => {
                      if (latestArtifact) onOpenArtifact(latestArtifact);
                      setMenuOpen(false);
                    }}
                    role="menuitem"
                    type="button"
                  >
                    Open latest artifact
                  </button>
                </div>
              )}
            </div>
            <span className="time">{messageTime}</span>
          </div>
        ) : null}
      </div>
    </article>
  );
}

const MemoMessageRow = memo(MessageRow);

/**
 * One row in the per-turn breakdown dropdown — either an individual tool
 * call or a reasoning/thinking step, interleaved chronologically.
 */
type ToolStep = {
  type: "tool";
  id: string;
  at: number;
  name: string;
  context: string;
  error?: string;
  inline_diff?: string;
  preview?: string;
  summary?: string;
  status: ToolEntry["status"];
  count: number;
};

type BreakdownStep =
  | ToolStep
  | { type: "trace"; id: string; at: number; text: string }
  | { type: "group"; id: string; at: number; tools: ToolStep[]; label: string };

type ToolCategory = "command" | "search" | "edit" | "read" | "skill" | "other";

function toolCategory(name: string): ToolCategory {
  const n = name.toLowerCase();
  if (/terminal|bash|shell|exec|command|process|^run/.test(n)) return "command";
  if (/search|grep|glob|find/.test(n)) return "search";
  if (/write|edit|patch/.test(n)) return "edit";
  if (/skill/.test(n)) return "skill";
  if (/read|cat|open|view|file/.test(n)) return "read";
  return "other";
}

// Pull the most label-worthy bit of a tool — a filename/skill/query — for the
// "Read App.tsx" style single-item summary.
function toolTarget(tool: ToolStep): string {
  const ctx = (tool.context || "").replace(/\s+/g, " ").trim();
  if (!ctx) return "";
  const firstToken = ctx.split(/\s+/)[0] ?? ctx;
  const base = firstToken.split("/").pop() || firstToken;
  return base.length > 36 ? `${base.slice(0, 36)}…` : base;
}

// Turn a raw tool identifier into a readable phrase, e.g.
// "delegate_task" → "Delegated a task", "mixture_of_agents" → "Mixture of agents".
const TOOL_NAME_LABELS: Record<string, string> = {
  delegate: "Delegated a task",
  delegate_task: "Delegated a task",
  mixture_of_agents: "Ran a mixture of agents",
  agent_handoff: "Handed off to an agent",
  subagent: "Ran a subagent",
};
function humanizeToolName(name: string): string {
  const key = name.toLowerCase();
  if (TOOL_NAME_LABELS[key]) return TOOL_NAME_LABELS[key];
  const words = name.replace(/[_-]+/g, " ").trim();
  if (!words) return "Ran a step";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Natural-language summary for a run of consecutive tool calls, e.g.
// "Ran 2 commands", "Read App.tsx", "Ran a command, read a file".
function describeToolGroup(tools: ToolStep[]): string {
  const order: ToolCategory[] = [];
  const byCat = new Map<ToolCategory, ToolStep[]>();
  for (const tool of tools) {
    const cat = toolCategory(tool.name);
    if (!byCat.has(cat)) {
      byCat.set(cat, []);
      order.push(cat);
    }
    byCat.get(cat)!.push(tool);
  }
  const phrase = (cat: ToolCategory, items: ToolStep[]): string => {
    const n = items.reduce((sum, t) => sum + Math.max(1, t.count), 0);
    const one = n === 1;
    const target = one ? toolTarget(items[0]) : "";
    switch (cat) {
      case "command": return one ? "ran a command" : `ran ${n} commands`;
      case "search": return one ? "ran a search" : `ran ${n} searches`;
      case "edit": return one ? (target ? `edited ${target}` : "edited a file") : `edited ${n} files`;
      case "read": return one ? (target ? `read ${target}` : "read a file") : `read ${n} files`;
      case "skill": return one ? (target ? `loaded ${target}` : "loaded a skill") : `loaded ${n} skills`;
      // For uncategorized tools, surface the actual tool name (e.g.
      // "delegate_task" → "Delegated a task") instead of a vague "ran a step".
      default: return one ? humanizeToolName(items[0].name) : `ran ${n} steps`;
    }
  };
  const parts = order.map((cat) => phrase(cat, byCat.get(cat)!));
  const joined = parts.join(", ");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

// Collapse runs of consecutive tool steps into a single labelled group, the
// way image-2 shows "Ran 2 commands" instead of a row per call. Reasoning
// (trace) steps break a run and stay on their own line.
function groupConsecutiveTools(steps: BreakdownStep[]): BreakdownStep[] {
  const out: BreakdownStep[] = [];
  let run: ToolStep[] = [];
  const flush = () => {
    if (!run.length) return;
    out.push({
      type: "group",
      id: `group-${run[0].id}`,
      at: run[0].at,
      tools: run,
      label: describeToolGroup(run),
    });
    run = [];
  };
  for (const step of steps) {
    if (step.type === "tool") {
      run.push(step);
      continue;
    }
    flush();
    out.push(step);
  }
  flush();
  return out;
}

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
      error: tool.error,
      inline_diff: tool.inline_diff,
      preview: tool.preview,
      summary: tool.summary,
      status: tool.status,
      count: 1,
    });
  }

  for (const trace of activityTrace) {
    if (trace.kind !== "reasoning" && trace.kind !== "thinking") continue;
    const text = compactLine(trace.text);
    if (!text) continue;
    // Drop transient single-word pills ("brainstorming", "Working...", etc.) —
    // they belong on the rotating header pill, not as permanent rows. Uses the
    // non-mangling check so real reasoning prose (which mentions "thinking"/
    // "reasoning") is kept intact.
    if (isTransientStatus(text)) continue;
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
      prev.error = step.error ?? prev.error;
      prev.inline_diff = step.inline_diff ?? prev.inline_diff;
      prev.preview = step.preview ?? prev.preview;
      prev.summary = step.summary ?? prev.summary;
      continue;
    }
    merged.push({ ...step });
  }
  return groupConsecutiveTools(merged);
}

// Reasoning summaries from gpt-5.5 / codex structure themselves with bold
// section headers, e.g. "**Querying ad performance** I need to gather data...
// **Creating ad script** I need to develop...". Each "**Header**" is a new
// reasoning layer, so we split the blob into one section per header (instead of
// one long run-on), and strip the ** markers so they never show as literal
// asterisks. A leading run before the first header becomes its own section.
type ReasoningSection = { header?: string; body: string };

function splitReasoningSections(text: string): ReasoningSection[] {
  const t = text.replace(/^\s+/, "");
  if (!t) return [];
  // Split on **Header** markers, capturing the header text (markers consumed).
  const parts = t.split(/\*\*\s*([^*\n]+?)\s*\*\*/g);
  const sections: ReasoningSection[] = [];
  const lead = (parts[0] || "").trim();
  if (lead) sections.push({ body: lead });
  for (let i = 1; i < parts.length; i += 2) {
    const header = (parts[i] || "").trim();
    const body = (parts[i + 1] || "").trim();
    if (header || body) sections.push({ header: header || undefined, body });
  }
  return sections.length ? sections : [{ body: t.trim() }];
}

// A single tool shown inside an expanded group — static, no chevron of its
// own (only the parent "Ran commands" group is expandable). The detail/output
// is shown inline.
function GroupToolDetail({ tool }: { tool: ToolStep }) {
  const Icon = breakdownToolIcon(tool.name);
  const body = [
    tool.context && `context\n${tool.context}`,
    tool.preview && `streaming\n${tool.preview}`,
    tool.summary && `result\n${tool.summary}`,
    tool.error && `error\n${tool.error}`,
    tool.inline_diff && `diff\n${tool.inline_diff}`,
  ]
    .filter(Boolean)
    .join("\n\n");
  return (
    <div className="py-0.5">
      <div className="tool-link cursor-default">
        <span className="chev" />
        <Icon
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-[var(--fg-faint)]",
            tool.status === "error" && "text-[var(--chat-danger)]",
            tool.status === "running" && "animate-pulse",
          )}
        />
        <span className="name">{tool.name}</span>
        {tool.context && <span className="target">· {truncatePreview(tool.context)}</span>}
        {tool.count > 1 && <span className="duration">×{tool.count}</span>}
      </div>
      {body && <div className="tool-body">{body}</div>}
    </div>
  );
}

/** A single tool/trace line inside the expanded breakdown. */
function BreakdownRow({ step }: { step: BreakdownStep }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);

  if (step.type === "trace") {
    // Render reasoning as full, always-visible messages — no "Thinking"
    // label, no collapse. Each "**Header**" section becomes its own message
    // (markers stripped) rather than one long run-on blob.
    const sections = splitReasoningSections(step.text);
    if (!sections.length) return null;
    return (
      <>
        {sections.map((s, i) => (
          <div key={`${step.id}-${i}`} className="reasoning-message">
            {s.header && <strong>{s.header}</strong>}
            {s.header && s.body ? "\n" : ""}
            {s.body}
          </div>
        ))}
      </>
    );
  }

  if (step.type === "group") {
    const running = step.tools.some((t) => t.status === "running");
    const errored = step.tools.some((t) => t.status === "error");
    const open = userOpen ?? errored;
    const Icon = breakdownToolIcon(step.tools[0]?.name ?? "");
    return (
      <div>
        <button
          aria-expanded={open}
          className={cn("tool-link", open && "open")}
          onClick={() => setUserOpen(!open)}
          type="button"
        >
          <ChevronDown className="chev" />
          <Icon
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-[var(--fg-faint)]",
              errored && "text-[var(--chat-danger)]",
              running && "animate-pulse",
            )}
          />
          <span className="name">{step.label}</span>
        </button>
        {open && (
          <div className="ml-4 border-l border-[var(--border-faint,rgba(255,255,255,0.08))] pl-2">
            {step.tools.map((t) => (
              <GroupToolDetail key={t.id} tool={t} />
            ))}
          </div>
        )}
      </div>
    );
  }

  // step.type === "tool"
  const toolBody = [
    step.context && `context\n${step.context}`,
    step.preview && `streaming\n${step.preview}`,
    step.summary && `result\n${step.summary}`,
    step.error && `error\n${step.error}`,
    step.inline_diff && `diff\n${step.inline_diff}`,
  ]
    .filter(Boolean)
    .join("\n\n");
  const hasBody = Boolean(toolBody);
  const open = userOpen ?? step.status === "error";
  const Icon = breakdownToolIcon(step.name);
  return (
    <div>
      <button
        aria-expanded={hasBody ? open : undefined}
        className={cn("tool-link", open && "open")}
        disabled={!hasBody}
        onClick={() => setUserOpen(!open)}
        type="button"
      >
        {hasBody ? <ChevronDown className="chev" /> : <span className="chev" />}
        <Icon
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-[var(--fg-faint)]",
            step.status === "error" && "text-[var(--chat-danger)]",
            step.status === "running" && "animate-pulse",
          )}
        />
        <span className="name">{step.name}</span>
        {step.context && (
          <span className="target">
            · {truncatePreview(step.context)}
          </span>
        )}
        {step.count > 1 && (
          <span className="duration">
            ×{step.count}
          </span>
        )}
      </button>
      {open && toolBody && <div className="tool-body">{toolBody}</div>}
    </div>
  );
}

/** A standalone, always-visible row for a memory save. */
function MemorySaveRow({ tool }: { tool: ToolEntry }) {
  const preview = truncatePreview(tool.summary || tool.context, 64);
  return (
    <div className="flex items-center gap-2 rounded-[6px] px-1 py-0.5 text-[12.5px] leading-5 text-[var(--chat-muted-strong)]">
      <Brain className="h-3.5 w-3.5 shrink-0 text-[var(--chat-muted-strong)] opacity-90" />
      <span className="min-w-0 flex-1 truncate">
        Saved to memory{preview ? `: ${preview}` : ""}
      </span>
    </div>
  );
}

// Rotating "thinking verb" for the live digest header. Cycles through the
// same 15 verbs the agent loop emits as heartbeats, capitalised, every
// ~2.4s while the turn is busy. Picks a fresh random index each tick so it
// doesn't feel mechanical.
function useRotatingVerb(busy: boolean): string {
  const [verb, setVerb] = useState(
    () => ROTATING_VERBS[Math.floor(Math.random() * ROTATING_VERBS.length)],
  );
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      setVerb((prev) => {
        if (ROTATING_VERBS.length <= 1) return prev;
        let next = prev;
        while (next === prev) {
          next = ROTATING_VERBS[Math.floor(Math.random() * ROTATING_VERBS.length)];
        }
        return next;
      });
    }, 2400);
    return () => window.clearInterval(timer);
  }, [busy]);
  return verb;
}

// Working/worked digest. While a turn streams, the header is the live
// meter: pulsing accent mark + a cycling thinking verb + elapsed + running
// token count, and the breakdown is expanded by default so reasoning (grey)
// and tool calls scroll in chronologically as they happen. Once the turn
// completes the same header collapses into "Worked for ..." with the real
// token count, and the breakdown defaults to collapsed.
function ChatActivityDigest({
  activityTrace,
  busy,
  compacting,
  completedAt,
  liveTokens,
  startedAt,
  tokenCount,
  tools,
}: {
  activityTrace: ActivityTrace[];
  artifacts: ArtifactEntry[];
  busy: boolean;
  compacting?: boolean;
  completedAt?: number;
  liveTokens?: number;
  startedAt?: number;
  tokenCount?: number;
  tools: ToolEntry[];
}) {
  // null = follow the default (expanded). The thinking/reasoning + tool
  // breakdown stays visible after the turn finishes, not just while busy — it
  // only collapses if the user explicitly toggles it shut.
  const [open, setOpen] = useState<boolean | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const rotatingVerb = useRotatingVerb(busy);

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
  const end = busy ? now : completedAt ?? activityFinishedAt(tools, start);
  const duration = formatDuration(Math.max(0, end - start));
  const expanded = open ?? true;
  const tokens = busy
    ? liveTokens ?? 0
    : typeof tokenCount === "number"
      ? tokenCount
      : 0;

  return (
    <section className="pt-1 text-[var(--fg-muted)]">
      {memoryTools.length > 0 && (
        <div className="mb-2.5 space-y-1">
          {memoryTools.map((tool) => (
            <MemorySaveRow key={tool.id} tool={tool} />
          ))}
        </div>
      )}

      <button
        className={cn("processing-bar max-w-full", expanded && "open")}
        onClick={() => setOpen(() => !expanded)}
        type="button"
      >
        {busy && (
          <span className="processing-glow">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
        )}
        <span className="processing-label min-w-0 truncate">
          {busy
            ? compacting
              ? "Compacting context"
              : `${rotatingVerb[0].toUpperCase()}${rotatingVerb.slice(1)}`
            : `Worked for ${duration}`}
        </span>
        <span className="processing-meta">
          {busy && (
            <>
              <span className="dot-sep">·</span>
              <span className="num">{duration}</span>
            </>
          )}
          {!busy && steps.length > 0 && (
            <>
              <span className="dot-sep">·</span>
              <span className="num">{plural(steps.length, "step")}</span>
            </>
          )}
          {(busy || tokens > 0) && (
            <>
              <span className="dot-sep">·</span>
              <span
                className="num"
                title="Tokens this turn generated (output). Not the same as context fill — that's the % ring."
              >
                {tokens.toLocaleString()} out
              </span>
            </>
          )}
        </span>
        {(busy || steps.length > 0) && (
          <ChevronDown
            className={cn(
              "processing-chev shrink-0",
              expanded && "open rotate-180",
            )}
          />
        )}
      </button>

      {expanded && steps.length > 0 && (
        <div className="processing-body mt-1.5 space-y-1">
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
  // Tool/subagent outputs live in the Background tasks panel, not the inline
  // shelf — only durable file/document artifacts surface here.
  const visible = artifacts
    .filter((a) => a.kind !== "output")
    .slice(-3)
    .reverse();
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
    <div className="max-w-[38rem] rounded-[8px] border border-[var(--chat-border)] bg-[var(--chat-surface)] px-2.5 py-2 shadow-[0_1px_0_rgba(255,255,255,0.025)_inset]">
      <div className="flex items-center gap-2">
        <FileText className="h-3.5 w-3.5 shrink-0 text-[var(--chat-muted-strong)]" />
        <button
          className="min-w-0 flex-1 text-left"
          onClick={() => onOpenArtifact(artifact)}
          type="button"
        >
          <div className="truncate text-[12.5px] font-medium leading-5 text-[var(--chat-text)]">
            {artifact.title}
          </div>
          <div className="truncate text-[11.5px] leading-4 text-[var(--chat-muted)]">
            {artifact.path || artifact.detail || artifact.source || "Artifact"}
          </div>
        </button>
        <button
          aria-label="Open artifact"
          className="inline-flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={() => onOpenArtifact(artifact)}
          title="Open"
          type="button"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </button>
        <button
          aria-label="Copy artifact"
          className="inline-flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={() => copy(copyText)}
          title={copied ? "Copied" : "Copy"}
          type="button"
        >
          {copied ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <Clipboard className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}

function PendingPromptCard({
  onRespond,
  onDismiss,
  pendingPrompt,
  promptValue,
  setPromptValue,
}: {
  onRespond(value: string): void;
  onDismiss(): void;
  pendingPrompt: PendingPrompt;
  promptValue: string;
  setPromptValue(value: string): void;
}) {
  if (pendingPrompt.type === "approval") {
    return (
      <Card className="rounded-[10px] border-[color-mix(in_srgb,var(--chat-warning)_38%,transparent)] bg-[color-mix(in_srgb,var(--chat-warning)_10%,var(--chat-bg))] p-3 text-[var(--chat-text)] shadow-[0_1px_0_rgba(255,255,255,0.025)_inset]">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--chat-warning)]" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Approval needed</div>
            <p className="mt-1 text-sm text-[var(--chat-muted-strong)]">
              {pendingPrompt.description}
            </p>
            {pendingPrompt.command && (
              <pre className="mt-2 max-h-28 overflow-auto rounded-[8px] bg-[var(--chat-surface-soft)] px-2 py-1.5 text-xs text-[var(--chat-muted-strong)]">
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
    <Card className="rounded-[10px] border-[var(--chat-border-strong)] bg-[var(--chat-surface)] p-3 text-[var(--chat-text)] shadow-[0_1px_0_rgba(255,255,255,0.025)_inset]">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="text-sm font-semibold">{title}</div>
        <button
          type="button"
          aria-label="Dismiss question"
          className="shrink-0 text-xs text-[var(--chat-text-muted)] hover:text-[var(--chat-text)]"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      </div>
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
            className="min-w-0 flex-1 rounded-[8px] border border-[var(--chat-border-strong)] bg-[var(--chat-surface-soft)] px-3 py-2 text-sm text-[var(--chat-text)] outline-none focus:ring-1 focus:ring-[var(--chat-accent)]"
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
    <div className="@container flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--chat-border)] bg-[var(--chat-surface)] text-[var(--chat-text)] shadow-[0_24px_60px_-20px_rgba(0,0,0,0.7),0_1px_0_rgba(255,255,255,0.04)_inset]">
      <header className="flex shrink-0 items-start gap-2 px-3 pb-3 pt-3 @[28rem]:gap-3 @[28rem]:px-4 @[28rem]:pt-4">
        <div className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-[8px] border border-[var(--chat-border)] bg-[var(--chat-surface-soft)] text-[var(--chat-accent)] @[24rem]:flex">
          <FileText className="h-4.5 w-4.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[0.95rem] font-semibold leading-5">
              {artifact.title}
            </h2>
            <span className="hidden shrink-0 rounded-[6px] bg-[var(--chat-surface-strong)] px-2 py-0.5 text-[11px] text-[var(--chat-muted)] @[22rem]:inline">
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
            className="hidden h-7 w-7 rounded-[7px] p-0 @[20rem]:inline-flex @[24rem]:h-8 @[24rem]:w-8"
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
            className="hidden h-7 w-7 rounded-[7px] p-0 @[20rem]:inline-flex @[24rem]:h-8 @[24rem]:w-8"
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
            className="h-7 w-7 rounded-[7px] p-0 @[24rem]:h-8 @[24rem]:w-8"
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

      {collapsed ? null : (
      <div className="min-h-0 flex-1 border-t border-[var(--chat-border)] bg-[var(--chat-surface-soft)]">
        {loading ? (
          <div className="flex h-full flex-col gap-3 p-6">
            <div className="h-4 w-2/3 animate-pulse rounded-[6px] bg-[var(--chat-border)]" />
            <div className="h-4 w-1/2 animate-pulse rounded-[6px] bg-[var(--chat-border)]" />
            <div className="mt-2 flex-1 animate-pulse rounded-[8px] bg-[var(--chat-border)]" />
          </div>
        ) : error && /\b404\b/.test(error) ? (
          // The file was referenced by a turn but is no longer on disk
          // (temp artifact cleaned up, moved, etc). A red alarm box
          // overstates it — show a quiet "gone" state instead.
          <div className="flex h-full items-center justify-center p-6">
            <div className="max-w-sm text-center text-[var(--chat-muted)]">
              <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-[8px] border border-[var(--chat-border)] bg-[var(--chat-surface)] text-[var(--chat-muted)]">
                <FileText className="h-5 w-5" />
              </div>
              <div className="mt-3 text-sm font-semibold text-[var(--chat-muted-strong)]">
                File no longer here
              </div>
              <p className="mt-1 text-xs leading-5">
                This file isn't on disk anymore — it was likely a temporary
                artifact that got cleaned up.
              </p>
            </div>
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-6">
            <div className="max-w-sm rounded-[8px] border border-[color-mix(in_srgb,var(--chat-danger)_34%,transparent)] bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-4 text-sm text-[var(--chat-danger)]">
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
          <pre className="h-full max-w-full overflow-x-hidden overflow-y-auto p-4 text-[0.76rem] leading-5 text-[var(--chat-muted-strong)] whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {textPreview}
          </pre>
        ) : (
          <div className="flex h-full items-center justify-center p-6">
            <div className="max-w-sm text-center">
              <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-[8px] border border-[var(--chat-border)] bg-[var(--chat-surface)] text-[var(--chat-accent)]">
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
  const [filesOpen, setFilesOpen] = useState(false);
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
    <section className="ap-artifacts">
      {grouped.length === 0 ? (
        <PortalEmpty>Files and outputs will land here</PortalEmpty>
      ) : (
        <>
          <button
            type="button"
            className={cn("ap-toggle", filesOpen && "open")}
            onClick={() => setFilesOpen((open) => !open)}
            title={
              hasDuplicates
                ? `${uniqueCount} unique · ${totalCount} total writes`
                : `${uniqueCount} file${uniqueCount === 1 ? "" : "s"}`
            }
          >
            <ChevronDown className="ap-toggle-chev" />
            <span>{uniqueCount} artifact{uniqueCount === 1 ? "" : "s"}</span>
          </button>
          {filesOpen && (
            <div className="ap-files">
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
        </>
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
    <div>
      <div
        className={cn(
          "ap-row file group",
          artifact.status === "error" &&
            "border border-[color-mix(in_srgb,var(--chat-danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))]",
        )}
      >
        <Icon />
        <button
          className="label border-0 bg-transparent p-0 text-left"
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
        <span
          className="time"
          aria-label={count > 1 ? `${count} writes to this file` : undefined}
        >
          {count > 1
            ? `×${count}`
            : artifact.detail?.split("·").pop()?.trim() || artifact.kind}
        </span>

        <button
          aria-label="Copy artifact"
          className="icon-btn sm opacity-0 group-hover:opacity-70"
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
        <pre className="ml-7 mb-1 mr-1 max-h-48 overflow-auto rounded-[7px] bg-[color-mix(in_srgb,var(--chat-surface-strong)_38%,transparent)] p-2 text-[11.5px] leading-4 text-[var(--chat-muted-strong)] whitespace-pre-wrap">
          {artifact.content}
        </pre>
      )}
    </div>
  );
}

// Short phrases that cycle on the live "current" pill while the agent is busy.
// Keep them plain: this is status chrome, not personality copy.
const ROTATING_PHRASES = [
  "Reading",
  "Checking",
  "Planning",
  "Running",
  "Reviewing",
  "Verifying",
  "Updating",
  "Connecting",
  "Preparing",
  "Processing",
];

function RotatingPhrase() {
  const [index, setIndex] = useState(() =>
    Math.floor(Math.random() * ROTATING_PHRASES.length),
  );
  useEffect(() => {
    const timer = setInterval(() => {
      setIndex((prev) => {
        // Avoid the same phrase twice in a row.
        let next = Math.floor(Math.random() * ROTATING_PHRASES.length);
        if (next === prev) next = (next + 1) % ROTATING_PHRASES.length;
        return next;
      });
    }, 2400);
    return () => clearInterval(timer);
  }, []);
  return <span>{ROTATING_PHRASES[index]}…</span>;
}

function ActivityPanel({
  artifacts,
  banner,
  busy,
  onOpenArtifact,
  onReconnect,
  state,
  statusText,
  tools,
}: {
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
    () => buildProgressSummaries({ artifacts, busy, statusText, tools }),
    [artifacts, busy, statusText, tools],
  );

  const hasProgress = progress.length > 0;

  return (
    <div className="ap-shell normal-case">
      {banner && (
        <section className="m-2 rounded-[8px] border border-[color-mix(in_srgb,var(--chat-danger)_35%,transparent)] bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-2.5">
          <div className="flex items-start gap-2 text-[12.5px] text-[var(--chat-danger)]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="break-words">{banner}</div>
              <button
                className="mt-2 rounded-[6px] bg-[color-mix(in_srgb,var(--chat-danger)_12%,var(--chat-bg))] px-2.5 py-1 text-[11.5px] transition-colors hover:bg-[color-mix(in_srgb,var(--chat-danger)_15%,var(--chat-bg))]"
                onClick={onReconnect}
                type="button"
              >
                Reconnect
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="ap-head">
        <div className="ap-title">
          <span>Activity</span>
          <span className="ap-live" title={state === "open" ? "Live" : STATE_LABEL[state]}>
            <span className="ap-live-dot" />
            {state === "open" ? "live" : STATE_LABEL[state]}
          </span>
        </div>
        <div className="ap-meta">
          <button className="icon-btn sm" title="Pin panel" type="button"><Pin /></button>
          <button className="icon-btn sm" title="More" type="button"><ChevronDown /></button>
        </div>
      </div>

      {hasProgress && (
        <div className="ap-feed">
          {progress.map((summary) => {
            const Icon =
              summary.status === "error"
                ? AlertCircle
                : summary.status === "running"
                  ? Loader2
                  : summary.status === "done"
                    ? CheckCircle2
                    : Clock;
            return (
              <div className="ap-row" key={summary.id}>
                <Icon className={cn(summary.status === "running" && "animate-spin")} />
                <span className="label">{summary.id === "current" ? <RotatingPhrase /> : summary.label}</span>
                <span className="time">{summary.status}</span>
              </div>
            );
          })}
        </div>
      )}

      <ArtifactsSection
        artifacts={artifacts}
        onOpenArtifact={onOpenArtifact}
      />
    </div>
  );
}

function PortalEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="ap-empty">
      {children}
    </div>
  );
}
