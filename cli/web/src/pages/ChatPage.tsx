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
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clipboard,
  Command,
  ExternalLink,
  FileCode2,
  FileText,
  Folder,
  GitBranch,
  PanelRightOpen,
  Loader2,
  Mic,
  MicOff,
  Plug,
  Send,
  Shield,
  ShieldAlert,
  Sparkles,
  SquareTerminal,
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
  persisted_session_id?: string;
  resumed?: string;
  session_id: string;
}

interface SessionResumeResponse extends SessionCreateResponse {
  messages?: GatewayTranscriptMessage[];
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
  routedText: string;
  status: "queued" | "error";
  text: string;
}

interface ActivityTrace {
  createdAt: number;
  id: string;
  kind: "reasoning" | "status" | "thinking";
  text: string;
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

const SESSION_MESSAGE_CACHE = new Map<string, ChatMessage[]>();
const MAX_CACHED_TRANSCRIPTS = 24;

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
  return clean.length > 420 && /^[{\[]/.test(clean);
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

function rememberTranscript(sessionId: string, messages: ChatMessage[]): void {
  if (!sessionId) return;
  SESSION_MESSAGE_CACHE.delete(sessionId);
  SESSION_MESSAGE_CACHE.set(sessionId, messages);
  while (SESSION_MESSAGE_CACHE.size > MAX_CACHED_TRANSCRIPTS) {
    const oldest = SESSION_MESSAGE_CACHE.keys().next().value;
    if (!oldest) break;
    SESSION_MESSAGE_CACHE.delete(oldest);
  }
}

function replaceUrlWithResume(sessionId: string): void {
  if (typeof window === "undefined" || !sessionId) return;
  const url = new URL(window.location.href);
  if (!url.pathname.endsWith("/chat")) return;
  if (url.searchParams.get("resume") === sessionId) return;
  url.searchParams.delete("new");
  url.searchParams.set("resume", sessionId);
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}?${url.searchParams.toString()}`,
  );
}

type ProgressState = "done" | "error" | "running";

interface ProgressSummary {
  detail?: string;
  details: string[];
  id: string;
  label: string;
  status: ProgressState;
}

interface ActivityTimelineItem {
  createdAt: number;
  detail?: string;
  details: string[];
  id: string;
  kind: "artifact" | "status" | "tool";
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

function firstTimestamp(tools: ToolEntry[], fallback = Date.now()): number {
  const starts = tools.map((tool) => tool.startedAt).filter(Boolean);
  return starts.length ? Math.min(...starts) : fallback;
}

function activityClauseText(tools: ToolEntry[]): string {
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

  const explored = [
    groups.read.length ? plural(groups.read.length, "file") : "",
    groups.search.length ? plural(groups.search.length, "search", "searches") : "",
  ].filter(Boolean);
  const clauses = [
    explored.length ? `explored ${explored.join(", ")}` : "",
    groups.run.length ? `ran ${plural(groups.run.length, "command")}` : "",
    groups.edit.length ? `edited ${plural(groups.edit.length, "file")}` : "",
    groups.other.length ? `used ${plural(groups.other.length, "tool action")}` : "",
  ].filter(Boolean);

  if (!clauses.length) return "";
  const text = clauses.join(", ");
  return text[0].toUpperCase() + text.slice(1);
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
    clean === "done"
  );
}

function buildActivityTimeline({
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
}): ActivityTimelineItem[] {
  const items: ActivityTimelineItem[] = [];

  for (const trace of activityTrace) {
    const label = displayStatusText(trace.text).trim();
    if (!label || isGenericActivityText(label)) continue;
    items.push({
      createdAt: trace.createdAt,
      details: [],
      id: trace.id,
      kind: "status",
      label,
      status: busy ? "running" : "done",
    });
  }

  if (tools.length) {
    const sortedTools = [...tools].sort((a, b) => a.startedAt - b.startedAt);
    items.push({
      createdAt: firstTimestamp(sortedTools),
      detail: "Click to inspect the work behind this step",
      details: detailsFor(sortedTools).slice(-8),
      id: "tool-rollup",
      kind: "tool",
      label: activityClauseText(sortedTools) || `Used ${plural(sortedTools.length, "tool action")}`,
      status: summaryStatus(sortedTools),
    });
  }

  if (artifacts.length) {
    items.push({
      createdAt: Math.max(...artifacts.map((artifact) => artifact.createdAt).filter(Boolean)),
      detail: "Files, diffs, previews, and outputs",
      details: artifacts.slice(-6).map((artifact) =>
        compactLine(artifact.detail || artifact.path || artifact.source, artifact.title),
      ),
      id: "artifact-rollup",
      kind: "artifact",
      label: `Prepared ${plural(artifacts.length, "artifact")}`,
      status: "done",
    });
  }

  if (!items.length) {
    const label = displayStatusText(statusText || "Working...") || "Working on the request";
    items.push({
      createdAt: Date.now(),
      details: [],
      id: "current-work",
      kind: "status",
      label,
      status: busy ? "running" : "done",
    });
  }

  return items
    .sort((a, b) => a.createdAt - b.createdAt)
    .filter((item, index, sorted) => {
      const previous = sorted[index - 1];
      return !(previous && previous.kind === item.kind && previous.label === item.label);
    })
    .slice(-8);
}

function isTerminalTool(tool: ToolEntry): boolean {
  const haystack = `${tool.name} ${tool.context ?? ""} ${tool.preview ?? ""}`.toLowerCase();
  return toolKind(tool) === "run" || /\b(terminal|bash|shell|exec|command)\b/.test(haystack);
}

function isSubagentTool(tool: ToolEntry): boolean {
  const haystack = `${tool.name} ${tool.context ?? ""} ${tool.preview ?? ""}`.toLowerCase();
  return /\b(subagent|sub-agent|delegate|delegation|agent)\b/.test(haystack);
}

function runningWorkTitle(tools: ToolEntry[], subagents: SubagentEntry[], busy: boolean): string {
  const runningTools = tools.filter((tool) => tool.status === "running");
  const terminals = runningTools.filter(isTerminalTool);
  const activeSubagents = subagents.filter((subagent) => subagent.status === "running");
  const otherTools = runningTools.filter(
    (tool) => !isTerminalTool(tool) && !isSubagentTool(tool),
  );

  const parts = [
    terminals.length ? plural(terminals.length, "terminal") : "",
    activeSubagents.length ? plural(activeSubagents.length, "subagent") : "",
    otherTools.length ? plural(otherTools.length, "tool") : "",
  ].filter(Boolean);

  return parts.length ? `Running ${parts.join(" · ")}` : busy ? "Agent working" : "Ready";
}

function runningToolLine(tool: ToolEntry): string {
  return compactLine(tool.preview || tool.context || tool.name, tool.name).slice(0, 130);
}

function runningSubagentLine(subagent: SubagentEntry): string {
  return compactLine(
    subagent.preview || subagent.goal || subagent.subagent_id,
    subagent.model || "subagent",
  ).slice(0, 130);
}

function buildProgressSummaries({
  artifacts,
  busy,
  statusText,
  tools,
}: {
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

  const summaries: ProgressSummary[] = [];
  const current = displayStatusText(statusText || "Working...");
  if (busy && tools.length === 0) {
    summaries.push({
      detail: "One active turn",
      details: current ? [current] : [],
      id: "current",
      label: current || "Working on the request",
      status: "running",
    });
  }

  if (groups.read.length || groups.search.length) {
    const parts = [
      groups.read.length ? plural(groups.read.length, "file") : "",
      groups.search.length ? plural(groups.search.length, "search", "searches") : "",
    ].filter(Boolean);
    summaries.push({
      detail: "Code and context inspection",
      details: detailsFor([...groups.read, ...groups.search]),
      id: "explore",
      label: `Checked ${parts.join(", ") || plural(groups.read.length + groups.search.length, "item")}`,
      status: summaryStatus([...groups.read, ...groups.search]),
    });
  }

  if (groups.edit.length) {
    summaries.push({
      detail: "Changed files",
      details: detailsFor(groups.edit),
      id: "edit",
      label: `Edited ${plural(groups.edit.length, "file")}`,
      status: summaryStatus(groups.edit),
    });
  }

  if (groups.run.length) {
    summaries.push({
      detail: "Commands and checks",
      details: detailsFor(groups.run),
      id: "run",
      label: `Ran ${plural(groups.run.length, "command")}`,
      status: summaryStatus(groups.run),
    });
  }

  if (groups.other.length) {
    summaries.push({
      detail: "Other tool work",
      details: detailsFor(groups.other),
      id: "other",
      label: `Used ${plural(groups.other.length, "tool action")}`,
      status: summaryStatus(groups.other),
    });
  }

  if (artifacts.length) {
    summaries.push({
      detail: "Files, diffs, previews, and outputs",
      details: artifacts.slice(-8).map((artifact) =>
        compactLine(artifact.detail || artifact.path || artifact.source, artifact.title),
      ),
      id: "artifacts",
      label: `Prepared ${plural(artifacts.length, "artifact")}`,
      status: "done",
    });
  }

  if (!summaries.length) {
    summaries.push({
      detail: "Waiting for the next request",
      details: [],
      id: "ready",
      label: "Ready",
      status: "done",
    });
  }

  return summaries.slice(0, 5);
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
}: {
  artifacts: ArtifactEntry[];
  info: SessionInfo;
  sessionId: string | null;
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
  const gw = useMemo(
    () => new GatewayClient(),
    [newChatId, resumeId, version],
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

  const [info, setInfo] = useState<SessionInfo>({});
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactEntry[]>([]);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactEntry | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tools, setTools] = useState<ToolEntry[]>([]);
  const [subagents, setSubagents] = useState<SubagentEntry[]>([]);
  const [activityTrace, setActivityTrace] = useState<ActivityTrace[]>([]);
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

  const openArtifactPreview = useCallback((artifact: ArtifactEntry) => {
    setPreviewArtifact(artifact);
  }, []);

  const addActivityTrace = useCallback(
    (kind: ActivityTrace["kind"], text: string) => {
      const clean = displayStatusText(text).trim();
      if (!clean) return;
      if ((kind === "thinking" || kind === "reasoning") && isGenericActivityText(clean)) {
        return;
      }

      setActivityTrace((prev) => {
        const last = prev[prev.length - 1];
        if (last?.kind === kind && last.text === clean) return prev;
        return [
          ...prev,
          {
            createdAt: Date.now(),
            id: id(`activity-${kind}`),
            kind,
            text: clean,
          },
        ].slice(-24);
      });
    },
    [],
  );

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
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, tools, pendingPrompt]);

  useEffect(() => {
    const persisted = persistedSessionIdRef.current;
    if (persisted && messages.length) {
      rememberTranscript(persisted, messages);
    }
  }, [messages]);

  useEffect(() => {
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
    setTools([]);
    setSubagents([]);
    setActivityTrace([]);
    setQueuedInputs([]);
    setPendingPrompt(null);
    setPromptValue("");
    setBusy(false);
    setBanner(null);
    setResumeFallback(false);
    setStatusText(resumeId ? "Loading chat..." : "Connecting...");

    if (resumeId) {
      const cached = SESSION_MESSAGE_CACHE.get(resumeId);
      if (cached) {
        historyHydratedRef.current = true;
        setMessages(cached);
        setStatusText("Connecting live session...");
      }

      void api.getSessionMessages(resumeId)
        .then((response) => {
          if (cancelled) return;
          const hydrated = normalizeStoredTranscript(response.messages);
          historyHydratedRef.current = true;
          rememberTranscript(response.session_id || resumeId, hydrated);
          rememberTranscript(resumeId, hydrated);
          setMessages(hydrated);
          setStatusText("Connecting live session...");
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
        addArtifacts(artifactsFromSubagentEvent(payload));
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
        setActivityTrace([]);
        setSubagents((prev) => prev.filter((subagent) => subagent.status === "running").slice(-8));
        ensureAssistant();
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
          setStatusText("Working...");
        }
      }),
    );
    unsubs.push(
      gw.on("reasoning.delta", (ev) => {
        if (!accepts(ev)) return;
        const text = eventText(ev);
        if (text) {
          setStatusText("Working...");
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
        if (!resumeId && persistedSessionIdRef.current) {
          replaceUrlWithResume(persistedSessionIdRef.current);
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
            setMessages(hydrated);
            if (persistedSessionIdRef.current) {
              rememberTranscript(persistedSessionIdRef.current, hydrated);
            }
          }
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
    addActivityTrace,
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

  const submitGatewayPrompt = useCallback(
    async (text: string, routedText: string, status = "Sending...") => {
      if (!sessionId) return;

      appendMessage("user", text);
      setBusy(true);
      setStatusText(status);

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
    [appendMessage, gw, sessionId],
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

  const submitPrompt = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !sessionId) return;

      setInput("");
      setComposerScrollTop(0);
      setBanner(null);
      setAgentMenuOpen(false);

      if (trimmed.startsWith("/")) {
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
    [appendMessage, busy, gw, selectedAgent, sessionId, submitGatewayPrompt],
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
  const visibleMessages = useMemo(
    () =>
      messages.filter((message) =>
        shouldKeepTranscriptMessage(message.role, message.content),
      ),
    [messages],
  );
  const chatTitle = useMemo(
    () => deriveChatTitle(visibleMessages, resumeId, resumeFallback),
    [resumeFallback, resumeId, visibleMessages],
  );
  const activity = (
    <ActivityPanel
      artifacts={artifacts}
      banner={banner}
      busy={busy}
      info={info}
      onOpenArtifact={openArtifactPreview}
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
            "fixed right-4 top-4 z-[60] flex h-[52dvh] max-h-[32rem] min-h-[22rem] w-[min(24rem,calc(100vw-2rem))] flex-col",
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

  const mobilePreviewPortal =
    narrow &&
    previewArtifact &&
    portalRoot &&
    createPortal(
      <>
        <button
          aria-label="Close artifact preview"
          className="fixed inset-0 z-[65] bg-black/60 backdrop-blur-sm"
          onClick={() => setPreviewArtifact(null)}
          type="button"
        />
        <aside className="fixed inset-x-3 bottom-3 top-3 z-[70]">
          <ArtifactPreviewPane
            artifact={previewArtifact}
            onClose={() => setPreviewArtifact(null)}
          />
        </aside>
      </>,
      portalRoot,
    );

  return (
    <div className="elevate-chat-shell relative -m-4 flex h-full min-h-0 flex-col overflow-hidden bg-[var(--chat-bg)] text-[var(--chat-text)] normal-case sm:-m-6">
      <div className="relative flex min-h-0 flex-1">
        <section
          className={cn(
            "flex min-h-0 flex-1 flex-col",
            previewArtifact ? "xl:pr-[34rem] 2xl:pr-[42rem]" : "xl:pr-[23rem]",
          )}
        >
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-5 sm:px-6">
            {visibleMessages.length === 0 ? (
              <EmptyState state={state} />
            ) : (
              <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-5 pb-6">
                <ChatTitleLine
                  chatTitle={chatTitle}
                />
                {visibleMessages.map((message, index) => (
                  <MessageRow
                    key={message.id}
                    activityText={
                      message.role === "assistant" &&
                      message.status === "streaming" &&
                      index === visibleMessages.length - 1
                        ? statusText
                        : undefined
                    }
                    message={message}
                  />
                ))}
                <ChatActivityDigest
                  activityTrace={activityTrace}
                  artifacts={artifacts}
                  busy={busy}
                  statusText={statusText}
                  tools={tools}
                />
                <ChatArtifactShelf
                  artifacts={artifacts}
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
            className="bg-[linear-gradient(180deg,transparent,var(--chat-bg)_18%)] px-4 pb-5 pt-3 sm:px-6"
            onSubmit={onSubmit}
          >
            <div className="mx-auto max-w-[48rem]">
              <RunningWorkStrip
                busy={busy}
                onInterrupt={interruptCurrentTurn}
                subagents={subagents}
                tools={tools}
              />
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
            "pointer-events-none absolute right-5 top-5 hidden xl:block",
            previewArtifact
              ? "h-[calc(100%-2.5rem)] min-h-[30rem] w-[40rem] max-w-[calc(100vw-2.5rem)]"
              : "h-[52vh] max-h-[34rem] min-h-[22rem] w-[21.5rem]",
          )}
        >
          <div className="pointer-events-auto h-full">
            {previewArtifact ? (
              <ArtifactPreviewPane
                artifact={previewArtifact}
                onClose={() => setPreviewArtifact(null)}
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
          className="fixed right-4 top-4 z-40 rounded-full bg-[var(--chat-surface)] px-3 py-1.5 text-xs font-medium text-[var(--chat-muted-strong)] shadow-[0_12px_38px_rgba(0,0,0,0.18),inset_0_0_0_1px_var(--chat-border)]"
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

function ChatTitleLine({
  chatTitle,
}: {
  chatTitle: string;
}) {
  return (
    <div className="mb-1 min-w-0 text-xs text-[var(--chat-muted)]">
      <div className="truncate text-sm font-semibold text-[var(--chat-text)]">
        {chatTitle}
      </div>
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

function RunningWorkStrip({
  busy,
  onInterrupt,
  subagents,
  tools,
}: {
  busy: boolean;
  onInterrupt(): void;
  subagents: SubagentEntry[];
  tools: ToolEntry[];
}) {
  const [open, setOpen] = useState(false);
  const runningTools = tools.filter((tool) => tool.status === "running");
  const runningSubagents = subagents.filter((subagent) => subagent.status === "running");
  const visible = runningTools.length > 0 || runningSubagents.length > 0;
  if (!visible) return null;

  const terminalTools = runningTools.filter(isTerminalTool);
  const otherTools = runningTools.filter((tool) => !isTerminalTool(tool));
  const title = runningWorkTitle(runningTools, runningSubagents, busy);
  const rows = [
    ...terminalTools.map((tool) => ({
      detail: runningToolLine(tool),
      icon: SquareTerminal,
      id: tool.id,
      label: tool.name,
      tone: "terminal" as const,
    })),
    ...runningSubagents.map((subagent) => ({
      detail: runningSubagentLine(subagent),
      icon: Bot,
      id: subagent.id,
      label: subagent.goal || "Subagent",
      tone: "agent" as const,
    })),
    ...otherTools.map((tool) => ({
      detail: runningToolLine(tool),
      icon: Wrench,
      id: tool.id,
      label: tool.name,
      tone: "tool" as const,
    })),
  ].slice(0, 6);

  return (
    <div className="mb-2 overflow-hidden rounded-[1.35rem] bg-[var(--chat-surface)] shadow-[0_18px_58px_rgba(0,0,0,0.18),inset_0_0_0_1px_var(--chat-border-strong)]">
      <div className="flex min-h-11 items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left text-[0.86rem] text-[var(--chat-muted-strong)] transition-colors hover:text-[var(--chat-text)]"
        >
          <SquareTerminal className="h-4 w-4 shrink-0 opacity-75" />
          <span className="min-w-0 truncate font-medium">{title}</span>
          {runningSubagents.length > 0 && (
            <span className="hidden shrink-0 rounded-full bg-[var(--chat-surface-soft)] px-2 py-0.5 text-[0.66rem] text-[var(--chat-muted)] sm:inline-flex">
              {plural(runningSubagents.length, "subagent")}
            </span>
          )}
        </button>

        <button
          aria-label="Stop running work"
          type="button"
          onClick={onInterrupt}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]"
          title="Stop the current response"
        >
          <span className="h-2.5 w-2.5 rounded-[0.18rem] bg-current" />
        </button>

        <button
          aria-label={open ? "Hide running work details" : "Show running work details"}
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-soft)] hover:text-[var(--chat-text)]"
        >
          <ChevronDown
            className={cn("h-4 w-4 transition-transform", open && "rotate-180")}
          />
        </button>
      </div>

      {open && rows.length > 0 && (
        <div className="border-t border-[var(--chat-border)] px-3 pb-2 pt-1.5">
          <div className="space-y-1">
            {rows.map((row) => {
              const Icon = row.icon;
              return (
                <div
                  key={row.id}
                  className="flex min-h-7 items-center gap-2 rounded-xl px-2 py-1 text-[0.76rem] text-[var(--chat-muted-strong)]"
                >
                  <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
                  <span className="shrink-0 font-medium">{row.label}</span>
                  <span className="min-w-0 flex-1 truncate text-[var(--chat-muted)]">
                    {row.detail}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
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
              <span className="absolute left-0 top-[0.12rem] inline-flex max-w-[min(24rem,calc(100vw-4rem))] items-center gap-1.5 rounded-full bg-[var(--chat-surface-soft)] px-1.5 py-0.5 text-[0.82rem] font-medium leading-5 text-[var(--chat-text)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
                <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--chat-accent)]" />
                <span className="min-w-0 truncate">{segment.label}</span>
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

      <div className="ml-auto flex min-w-0 items-center">
        <button
          aria-label={busy ? "Interrupt response" : "Send message"}
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all",
            busy
              ? "bg-[var(--chat-text)] text-[var(--chat-bg)] shadow-[0_8px_22px_rgba(0,0,0,0.22)] hover:scale-[1.02]"
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
  activityText,
  message,
}: {
  activityText?: string;
  message: ChatMessage;
}) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  if (
    message.role === "tool" ||
    (message.role !== "user" && isRawToolPayload(message.content))
  ) {
    return null;
  }
  if (isAssistant && !message.content.trim()) {
    return null;
  }

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

function ChatActivityDigest({
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
}) {
  const [open, setOpen] = useState(false);
  const timeline = useMemo(
    () => buildActivityTimeline({ activityTrace, artifacts, busy, statusText, tools }),
    [activityTrace, artifacts, busy, statusText, tools],
  );
  const show = busy || tools.length > 0 || activityTrace.length > 0;
  if (!show) return null;

  const start = activityStartedAt(tools, activityTrace);
  const end = busy ? Date.now() : activityFinishedAt(tools);
  const duration = formatDuration(end - start);
  const visibleTimeline = open ? timeline : timeline.slice(-4);

  return (
    <section className="border-t border-[var(--chat-border)] pt-4 text-[var(--chat-muted)]">
      <button
        className="flex items-center gap-2 text-sm text-[var(--chat-muted-strong)] transition-colors hover:text-[var(--chat-text)]"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span>{busy ? "Working" : "Worked"} for {duration}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      <div className="mt-3 space-y-3">
        {visibleTimeline.map((item) => (
          <ActivityTimelineRow key={item.id} item={item} />
        ))}
      </div>
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
  const [copied, setCopied] = useState(false);
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
    <div className="max-w-[38rem] rounded-2xl bg-[var(--chat-surface)] p-3 shadow-[inset_0_0_0_1px_var(--chat-border)]">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--chat-surface-soft)] text-[var(--chat-accent)]">
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
          className="rounded-full border border-[var(--chat-border-strong)] px-3 py-1 text-xs text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={() => onOpenArtifact(artifact)}
          type="button"
        >
          Open
        </button>
        <button
          className="rounded-full border border-[var(--chat-border-strong)] px-3 py-1 text-xs text-[var(--chat-muted-strong)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={copy}
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
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
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

  const copy = () => {
    navigator.clipboard
      .writeText(copyText)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {});
  };

  const openExternal = () => {
    if (!blobUrl) return;
    window.open(blobUrl, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[1.65rem] bg-[var(--chat-surface)] text-[var(--chat-text)] shadow-[0_32px_90px_rgba(0,0,0,0.26),inset_0_0_0_1px_var(--chat-border)] ring-1 ring-white/[0.025]">
      <header className="flex shrink-0 items-start gap-3 px-4 pb-3 pt-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[var(--chat-surface-soft)] text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
          <FileText className="h-4.5 w-4.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[0.95rem] font-semibold leading-5">
              {artifact.title}
            </h2>
            <span className="shrink-0 rounded-full bg-[var(--chat-surface-strong)] px-2 py-0.5 text-[0.65rem] text-[var(--chat-muted)]">
              {fileExtension(pathForKind).replace(".", "").toUpperCase() || artifact.kind}
            </span>
          </div>
          <p className="mt-1 truncate text-[0.72rem] leading-4 text-[var(--chat-muted)]">
            {artifact.path || artifact.detail || artifact.source || "Artifact preview"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            className="h-8 rounded-full px-2.5 text-xs"
            disabled={!blobUrl}
            onClick={openExternal}
            size="sm"
            type="button"
            variant="outline"
          >
            <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
            Open
          </Button>
          <Button
            className="h-8 rounded-full px-2.5 text-xs"
            onClick={copy}
            size="sm"
            type="button"
            variant="outline"
          >
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button
            aria-label="Close preview"
            className="h-8 w-8 rounded-full p-0"
            onClick={onClose}
            size="sm"
            type="button"
            variant="ghost"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 border-t border-[var(--chat-border)] bg-[var(--chat-surface-soft)]">
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--chat-muted)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Opening local preview...
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-6">
            <div className="max-w-sm rounded-2xl bg-[color-mix(in_srgb,var(--chat-danger)_10%,var(--chat-bg))] p-4 text-sm text-[var(--chat-danger)] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--chat-danger)_34%,transparent)]">
              <div className="font-semibold">Could not preview this file</div>
              <div className="mt-1 break-words text-xs opacity-90">{error}</div>
            </div>
          </div>
        ) : kind === "pdf" && blobUrl ? (
          <iframe
            className="h-full w-full bg-[var(--chat-bg)]"
            src={blobUrl}
            title={artifact.title}
          />
        ) : kind === "html" && blobUrl ? (
          <iframe
            className="h-full w-full bg-white"
            sandbox=""
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
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--chat-surface)] text-[var(--chat-accent)] shadow-[inset_0_0_0_1px_var(--chat-border)]">
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
                <Button onClick={copy} size="sm" type="button" variant="outline">
                  {copied ? "Copied" : "Copy path"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ArtifactCard({
  artifact,
  onOpenArtifact,
}: {
  artifact: ArtifactEntry;
  onOpenArtifact(artifact: ArtifactEntry): void;
}) {
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
          onClick={() => {
            if (artifact.path) {
              onOpenArtifact(artifact);
            } else if (artifact.content) {
              setOpen((value) => !value);
            }
          }}
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
          aria-label="Open artifact preview"
          className="rounded-md p-1 text-[var(--chat-muted)] transition-colors hover:bg-[var(--chat-surface-strong)] hover:text-[var(--chat-text)]"
          onClick={() => onOpenArtifact(artifact)}
          type="button"
        >
          <PanelRightOpen className="h-3.5 w-3.5" />
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

function ProgressSummaryList({ summaries }: { summaries: ProgressSummary[] }) {
  return (
    <div className="space-y-1.5">
      {summaries.map((summary) => (
        <ProgressSummaryRow key={summary.id} summary={summary} />
      ))}
    </div>
  );
}

function ActivityTimelineRow({ item }: { item: ActivityTimelineItem }) {
  const [open, setOpen] = useState(false);
  const hasDetails = item.details.length > 0;
  const failed = item.status === "error";
  const running = item.status === "running";
  const Icon = running
    ? Loader2
    : item.kind === "artifact"
      ? FileText
      : item.kind === "tool"
        ? SquareTerminal
        : CheckCircle2;

  return (
    <div className="max-w-[46rem] text-sm leading-6">
      <button
        aria-expanded={open}
        className={cn(
          "group flex w-full items-start gap-2.5 rounded-xl py-1.5 text-left transition-colors",
          hasDetails && "hover:text-[var(--chat-text)]",
        )}
        disabled={!hasDetails}
        onClick={() => hasDetails && setOpen((value) => !value)}
        type="button"
      >
        <span
          className={cn(
            "mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full",
            failed
              ? "bg-[color-mix(in_srgb,var(--chat-danger)_18%,var(--chat-bg))] text-[var(--chat-danger)]"
              : running
                ? "text-[var(--chat-muted-strong)]"
                : "bg-[var(--chat-muted-strong)] text-[var(--chat-bg)]",
          )}
        >
          <Icon className={cn("h-2.5 w-2.5", running && "animate-spin")} />
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              "block text-[var(--chat-muted-strong)]",
              running && item.kind === "status" && "elevate-thinking-shimmer rounded-lg px-2 py-1",
            )}
          >
            {item.label}
          </span>
          {item.detail && (
            <span className="mt-0.5 block truncate text-xs text-[var(--chat-muted)]">
              {item.detail}
            </span>
          )}
        </span>
        {hasDetails && (
          <ChevronDown
            className={cn(
              "mt-1.5 h-3.5 w-3.5 shrink-0 text-[var(--chat-muted)] transition-transform group-hover:text-[var(--chat-muted-strong)]",
              open && "rotate-180",
            )}
          />
        )}
      </button>
      {open && hasDetails && (
        <div className="ml-6 mt-1.5 space-y-1 text-xs leading-5 text-[var(--chat-muted)]">
          {item.details.map((detail, index) => (
            <div key={`${item.id}-${index}`} className="truncate">
              {detail}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ProgressSummaryRow({ summary }: { summary: ProgressSummary }) {
  const [open, setOpen] = useState(false);
  const hasDetails = summary.details.length > 0;
  const complete = summary.status === "done";
  const failed = summary.status === "error";

  return (
    <div className="rounded-xl px-1 py-1 text-sm leading-5">
      <button
        aria-expanded={open}
        className="flex w-full items-start gap-2 text-left"
        disabled={!hasDetails}
        onClick={() => hasDetails && setOpen((value) => !value)}
        type="button"
      >
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
        {summary.status === "running" ? (
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
        ) : (
          <CheckCircle2 className="h-2.5 w-2.5" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[var(--chat-muted-strong)]">{summary.label}</div>
        {summary.detail && (
          <div className="mt-0.5 truncate text-xs text-[var(--chat-muted)]">
            {summary.detail}
          </div>
        )}
      </div>
      {hasDetails && (
        <ChevronDown
          className={cn(
            "mt-1 h-3.5 w-3.5 shrink-0 text-[var(--chat-muted)] transition-transform",
            open && "rotate-180",
          )}
        />
      )}
      </button>
      {open && hasDetails && (
        <div className="ml-6 mt-1.5 space-y-1 text-xs leading-5 text-[var(--chat-muted)]">
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
  artifacts,
  banner,
  busy,
  info,
  onOpenArtifact,
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
  onOpenArtifact(artifact: ArtifactEntry): void;
  onReconnect(): void;
  sessionId: string | null;
  state: ConnectionState;
  statusText: string;
  tools: ToolEntry[];
}) {
  const sources = useMemo(
    () => buildSourceEntries({ artifacts, info, sessionId }),
    [artifacts, info, sessionId],
  );
  const progress = useMemo(
    () => buildProgressSummaries({ artifacts, busy, statusText, tools }),
    [artifacts, busy, statusText, tools],
  );

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
        <section className="space-y-2">
          <PortalSectionHeader
            count={progress.length}
            label="Progress"
            meta={busy ? "working" : "summary"}
          />
          <ProgressSummaryList summaries={progress} />
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
                <ArtifactCard
                  key={artifact.id}
                  artifact={artifact}
                  onOpenArtifact={onOpenArtifact}
                />
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
