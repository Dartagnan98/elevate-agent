import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";
import { supabase } from "@/lib/supabase";

export const runtime = "nodejs";

const EVENT_RE = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$/;
const MAX_EVENTS = 200;

const SAFE_NUMERIC_KEYS = new Set([
  "api_calls",
  "attempt_count",
  "compaction_removed_messages",
  "compaction_saved_tokens",
  "context_limit",
  "context_tokens",
  "correction_count",
  "critical_item_count",
  "critical_ratio_bps",
  "duration_ms",
  "duration_seconds",
  "event_seq",
  "friction_count",
  "input_tokens",
  "low_yield_count",
  "message_count",
  "message_chars",
  "output_tokens",
  "reasoning_tokens",
  "reasoning_chars",
  "replay_count",
  "retry_count",
  "rendered_chars",
  "text_chars",
  "tool_count",
  "warning_chars",
]);

const SAFE_BOOL_KEYS = new Set([
  "abandoned",
  "attached",
  "child_replay_attached",
  "child_replay_running",
  "failed",
  "followup",
  "noop",
  "payload_truncated",
  "recovered",
  "running",
  "success",
]);

const SAFE_STATE_KEYS = new Set([
  "asset",
  "assistant_message_id",
  "backend_build",
  "child_session_id",
  "component",
  "end_reason",
  "error_class",
  "error_message",
  "friction_kind",
  "frontend_asset",
  "kind",
  "message_id",
  "model",
  "outcome",
  "parent_session_id",
  "provider",
  "reason",
  "request_id",
  "source",
  "stage",
  "status",
  "task_id",
  "tool_name",
  "turn_id",
  "user_message_id",
  "where",
]);

const FORBIDDEN_KEYS = new Set([
  "answer",
  "body",
  "content",
  "file_path",
  "html",
  "markdown",
  "message",
  "path",
  "pdf_text",
  "prompt",
  "raw",
  "reasoning",
  "stack",
  "text",
  "traceback",
  "url",
  "browser_snapshot",
  "snapshot",
  "screenshot",
  "selector",
  "page_title",
]);

const Envelope = z.object({
  event_id: z.string().min(1).max(128),
  event: z.string().min(1).max(96),
  ts: z.number().optional(),
  seq: z.number().optional(),
  severity: z.string().max(24).optional(),
  source: z.string().max(64).optional(),
  component: z.string().max(128).optional(),
  session_id: z.string().max(256).optional(),
  parent_session_id: z.string().max(256).optional(),
  child_session_id: z.string().max(256).optional(),
  task_id: z.string().max(256).optional(),
  turn_id: z.string().max(256).optional(),
  app_version: z.string().max(256).optional(),
  backend_build: z.string().max(256).optional(),
  payload: z.record(z.unknown()).optional(),
  redaction: z.record(z.unknown()).optional(),
});

const Body = z.object({
  events: z.array(Envelope).min(1).max(MAX_EVENTS),
});

function cleanEventName(value: string): string {
  const text = value.trim().toLowerCase();
  return EVENT_RE.test(text) ? text : "diagnostics.event";
}

function cleanString(value: unknown, maxLen = 512): string {
  const text = String(value ?? "").replace(/\0/g, "").slice(0, maxLen);
  return redactSensitive(text);
}

function redactSensitive(value: string): string {
  return value
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
    .replace(/\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b/g, "[redacted-secret]")
    .replace(
      /\b(token|password|secret|api[_-]?key)=([^\s&]+)/gi,
      "$1=[redacted-secret]",
    )
    .replace(/\/Users\/[^\s"'`]+/g, (match) => {
      const name = match.split("/").pop() || "path";
      return `[path:${name}]`;
    });
}

function sanitizePayload(payload: Record<string, unknown> | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!payload || typeof payload !== "object") return out;
  for (const [rawKey, value] of Object.entries(payload)) {
    const key = rawKey.toLowerCase().slice(0, 96);
    if (FORBIDDEN_KEYS.has(key)) continue;
    if (
      !SAFE_NUMERIC_KEYS.has(key) &&
      !SAFE_BOOL_KEYS.has(key) &&
      !SAFE_STATE_KEYS.has(key) &&
      !key.endsWith("_hash")
    ) {
      continue;
    }
    if (SAFE_NUMERIC_KEYS.has(key)) {
      if (typeof value === "number" && Number.isFinite(value)) out[key] = value;
      continue;
    }
    if (SAFE_BOOL_KEYS.has(key)) {
      if (typeof value === "boolean") out[key] = value;
      continue;
    }
    if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
      out[key] = typeof value === "string" ? cleanString(value) : value;
    }
  }
  return out;
}

function sanitizeRedaction(value: Record<string, unknown> | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  if (!value || typeof value !== "object") return out;
  for (const [rawKey, rawValue] of Object.entries(value)) {
    if (typeof rawValue !== "number" || !Number.isFinite(rawValue)) continue;
    const key = rawKey.toLowerCase().slice(0, 96);
    out[key] = Math.max(0, Math.floor(rawValue));
  }
  return out;
}

function clientTimestamp(ts: number | undefined): string | null {
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return null;
  const ms = ts > 10_000_000_000 ? ts : ts * 1000;
  const date = new Date(ms);
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

export async function POST(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const limited = await enforceLimits([
    { key: `diagnostics:ip:${clientIp(req)}`, max: 600, windowSeconds: 300 },
    { key: `diagnostics:license:${guard.claims.license_id}`, max: 300, windowSeconds: 300 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const rows = parsed.data.events.map((event) => ({
    event_id: event.event_id,
    user_id: guard.user.id,
    license_id: guard.claims.license_id,
    session_id: event.session_id || null,
    parent_session_id: event.parent_session_id || null,
    child_session_id: event.child_session_id || null,
    task_id: event.task_id || null,
    turn_id: event.turn_id || null,
    event: cleanEventName(event.event),
    severity: cleanString(event.severity || "info", 24) || "info",
    source: cleanString(event.source || "backend", 64) || "backend",
    component: cleanString(event.component || event.source || "unknown", 128) || "unknown",
    payload: sanitizePayload(event.payload),
    redaction: sanitizeRedaction(event.redaction),
    client_ts: clientTimestamp(event.ts),
    client_seq: typeof event.seq === "number" && Number.isFinite(event.seq) ? Math.trunc(event.seq) : null,
    app_version: event.app_version || null,
    backend_build: event.backend_build || null,
  }));

  const { error } = await supabase()
    .from("session_diagnostic_events")
    .upsert(rows, { onConflict: "event_id", ignoreDuplicates: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ accepted: rows.length });
}
