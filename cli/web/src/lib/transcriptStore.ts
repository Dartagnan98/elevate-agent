/**
 * transcriptStore — the single owner of chat transcript state.
 *
 * Phase 3 of plans/chat-transcript-refactor.md. Replaces ChatPage's
 * useState<ChatMessage[]> + 15 ad-hoc writers + 12 "vanish guards" with one
 * external store where the invariant is structural:
 *
 *   A rendered message can never be removed or shrunk except by an explicit
 *   user action (clear) — merges are set-unions by stable message id.
 *
 * Identity comes from the gateway (wire `message_id`, persisted as
 * chat_messages.client_message_id). Pre-upgrade rows carry deterministic
 * `legacy.{session}.{ordinal}` ids — WEAK identity: they may be fingerprint-
 * matched against other weak-id messages to avoid duplicates. Strong (uuid)
 * ids never fingerprint-match.
 *
 * chatKey conventions:
 *   lineage_root_id                 — normal sessions (stable across compaction)
 *   `draft:{uuid}`                  — pre-create New Chat (rekeyed after create)
 *   `subagent:{sessionId}`          — read-only subagent drill-in views
 */

import { useSyncExternalStore } from "react";

import type { ToolEntry } from "@/components/ToolCall";

export type ChatRole = "assistant" | "system" | "tool" | "user";

export interface TranscriptAttachment {
  name: string;
  size: number;
  mediaType: string;
  previewUrl?: string;
}

export interface TranscriptTrace {
  createdAt: number;
  id: string;
  kind: "reasoning" | "status" | "thinking";
  text: string;
  messageId?: string;
}

export type TranscriptStatus = "streaming" | "complete" | "error" | "interrupted";

export interface TranscriptMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
  status?: TranscriptStatus;
  completedAt?: number;
  title?: string;
  warning?: string;
  // Client-owned metadata — never clobbered by hydrate.
  tools?: ToolEntry[];
  traces?: TranscriptTrace[];
  tokenCount?: number;
  attachments?: TranscriptAttachment[];
  /** Ordering key. Hydrated history < LIVE_SEQ_BASE; live appends above it. */
  seq: number;
  origin: "stream" | "hydrate" | "local";
  /** id missing on the wire or `legacy.*` — eligible for fingerprint match. */
  weakId: boolean;
}

export interface HydratedWireMessage {
  message_id?: string | null;
  role: ChatRole;
  content: string;
  createdAt?: number;
  status?: TranscriptStatus;
  completedAt?: number;
  title?: string;
  warning?: string;
  tools?: ToolEntry[];
  traces?: TranscriptTrace[];
  tokenCount?: number;
  attachments?: TranscriptAttachment[];
}

export type HydrateSource = "rest" | "resume" | "replay" | "cache";

export interface UnionReport {
  added: number;
  updated: number;
  shrinksDropped: number;
  weakMatches: number;
}

export interface TranscriptTelemetry {
  shrinksDropped: number;
  weakMatches: number;
  finalizeShrinks: number;
  clears: number;
}

const PATCHABLE_META = [
  "tools",
  "traces",
  "tokenCount",
  "attachments",
  "warning",
  "status",
  "completedAt",
  "title",
] as const;
type PatchableMetaKey = (typeof PATCHABLE_META)[number];
export type TranscriptMetaPatch = Partial<
  Pick<TranscriptMessage, PatchableMetaKey>
>;

/** Live appends always sort after hydrated history (server ordinals are
 * message indexes — far below this base). */
const LIVE_SEQ_BASE = 1_000_000;

// ─── localStorage write-through (messageCache.v2) ───────────────────────

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const V2_KEY = "elevate.chat.messageCache.v2";
const LEGACY_KEYS = [
  "elevate.chat.messageCache.v1",
  "elevate.chat.activeTurnCache.v1",
];
const MAX_CACHED_CHATS = 24;
const MAX_STORED_MESSAGES = 160;
const MAX_MESSAGE_CHARS = 16_000;
const MAX_CHAT_CHARS = 220_000;
const STALE_STREAMING_MS = 12 * 60 * 60 * 1000;
const WRITE_DEBOUNCE_MS = 500;

let storageOverride: StorageLike | null | undefined;

function storage(): StorageLike | null {
  if (storageOverride !== undefined) return storageOverride;
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    /* sandboxed iframe / SSR */
  }
  return null;
}

interface StoredChat {
  messages: TranscriptMessage[];
  updatedAt: number;
}

function readV2(): Record<string, StoredChat> {
  const s = storage();
  if (!s) return {};
  try {
    const raw = s.getItem(V2_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function trimForStorage(messages: TranscriptMessage[]): TranscriptMessage[] {
  const tail = messages.slice(-MAX_STORED_MESSAGES);
  let budget = MAX_CHAT_CHARS;
  const out: TranscriptMessage[] = [];
  // Walk newest-first so the most recent turns survive the budget.
  for (let i = tail.length - 1; i >= 0; i--) {
    const m = tail[i];
    let content = m.content ?? "";
    if (content.length > MAX_MESSAGE_CHARS) {
      content =
        content.slice(0, MAX_MESSAGE_CHARS) +
        "\n\n[Cached preview trimmed. Full history reloads from the server.]";
    }
    if (budget - content.length < 0) break;
    budget -= content.length;
    out.unshift({ ...m, content, traces: m.traces?.slice(-40) });
  }
  return out;
}

// ─── Store internals ────────────────────────────────────────────────────

interface ChatBucket {
  byId: Map<string, TranscriptMessage>;
  version: number;
  snapshot: readonly TranscriptMessage[] | null;
  liveSeq: number;
  hydrateSeq: number;
  listeners: Set<() => void>;
  restored: boolean;
}

const buckets = new Map<string, ChatBucket>();
const telemetry: TranscriptTelemetry = {
  shrinksDropped: 0,
  weakMatches: 0,
  finalizeShrinks: 0,
  clears: 0,
};

let legacyKeysPurged = false;
// The store stays PASSIVE until ChatPage activates it (transcriptStore feature
// flag ON). While passive it never purges the legacy v1 caches the old
// ChatPage path still reads — so flag-off boxes keep their warm-restore. Hooks
// can't be conditional, so `useTranscript` runs even when the flag is off; this
// gate is what makes that safe.
let storeActive = false;
const dirtyChats = new Set<string>();
let writeTimer: ReturnType<typeof setTimeout> | null = null;

/** ChatPage calls this once on mount when the transcriptStore flag is ON. */
export function activateStore(): void {
  storeActive = true;
}

function purgeLegacyKeysOnce(): void {
  if (legacyKeysPurged || !storeActive) return;
  legacyKeysPurged = true;
  const s = storage();
  if (!s) return;
  // Old caches carry random per-hydrate ids that would pollute identity;
  // the server hydrate refills the warm cache within one load.
  for (const key of LEGACY_KEYS) {
    try {
      s.removeItem(key);
    } catch {
      /* ignore */
    }
  }
}

function isWeakId(id: string | null | undefined): boolean {
  return !id || id.startsWith("legacy.");
}

function fingerprint(role: string, content: string): string {
  const c = (content ?? "").trim().replace(/\s+/g, " ").slice(0, 200);
  return `${role}:${c}`;
}

function bucket(chatKey: string): ChatBucket {
  purgeLegacyKeysOnce();
  let b = buckets.get(chatKey);
  if (!b) {
    b = {
      byId: new Map(),
      version: 0,
      snapshot: null,
      liveSeq: LIVE_SEQ_BASE,
      hydrateSeq: 0,
      listeners: new Set(),
      restored: false,
    };
    buckets.set(chatKey, b);
    restoreFromCache(chatKey, b);
  }
  return b;
}

function restoreFromCache(chatKey: string, b: ChatBucket): void {
  if (b.restored) return;
  b.restored = true;
  const entry = readV2()[chatKey];
  if (!entry || !Array.isArray(entry.messages) || !entry.messages.length) return;
  const stale = Date.now() - (entry.updatedAt || 0) > STALE_STREAMING_MS;
  for (const raw of entry.messages) {
    if (!raw || typeof raw !== "object" || !raw.id) continue;
    const msg: TranscriptMessage = {
      ...raw,
      origin: "hydrate",
      // A cached "streaming" message older than the staleness window is a
      // zombie from a crashed turn — mark it interrupted (folds in the old
      // activeTurnCache semantics).
      status: raw.status === "streaming" && stale ? "interrupted" : raw.status,
      weakId: isWeakId(raw.id),
    };
    b.byId.set(msg.id, msg);
    b.hydrateSeq = Math.max(b.hydrateSeq, msg.seq < LIVE_SEQ_BASE ? msg.seq + 1 : b.hydrateSeq);
    b.liveSeq = Math.max(b.liveSeq, msg.seq >= LIVE_SEQ_BASE ? msg.seq + 1 : b.liveSeq);
  }
}

function scheduleWrite(chatKey: string): void {
  dirtyChats.add(chatKey);
  if (writeTimer) return;
  writeTimer = setTimeout(flushWrites, WRITE_DEBOUNCE_MS);
}

function flushWrites(): void {
  writeTimer = null;
  const s = storage();
  const pending = Array.from(dirtyChats);
  dirtyChats.clear();
  if (!s || !pending.length) return;
  try {
    const all = readV2();
    for (const chatKey of pending) {
      const b = buckets.get(chatKey);
      if (!b) continue;
      all[chatKey] = {
        messages: trimForStorage(snapshotOf(chatKey) as TranscriptMessage[]),
        updatedAt: Date.now(),
      };
    }
    // Evict oldest chats beyond the cap.
    const keys = Object.keys(all);
    if (keys.length > MAX_CACHED_CHATS) {
      keys
        .sort((a, c) => (all[a].updatedAt || 0) - (all[c].updatedAt || 0))
        .slice(0, keys.length - MAX_CACHED_CHATS)
        .forEach((k) => delete all[k]);
    }
    s.setItem(V2_KEY, JSON.stringify(all));
  } catch {
    /* quota / serialization — cache is best-effort */
  }
}

function bump(chatKey: string, b: ChatBucket): void {
  b.version += 1;
  b.snapshot = null;
  scheduleWrite(chatKey);
  for (const cb of b.listeners) cb();
}

function snapshotOf(chatKey: string): readonly TranscriptMessage[] {
  const b = bucket(chatKey);
  if (!b.snapshot) {
    b.snapshot = Object.freeze(
      Array.from(b.byId.values()).sort(
        (a, c) => a.seq - c.seq || a.createdAt - c.createdAt,
      ),
    ) as readonly TranscriptMessage[];
  }
  return b.snapshot;
}

// ─── Public API ─────────────────────────────────────────────────────────

export function subscribe(chatKey: string, cb: () => void): () => void {
  const b = bucket(chatKey);
  b.listeners.add(cb);
  return () => b.listeners.delete(cb);
}

export function getSnapshot(chatKey: string): readonly TranscriptMessage[] {
  return snapshotOf(chatKey);
}

export function hasMessages(chatKey: string): boolean {
  return bucket(chatKey).byId.size > 0;
}

export function appendLocal(
  chatKey: string,
  msg: Omit<TranscriptMessage, "seq" | "origin" | "weakId">,
): void {
  const b = bucket(chatKey);
  if (b.byId.has(msg.id)) return; // idempotent
  b.byId.set(msg.id, {
    ...msg,
    seq: b.liveSeq++,
    origin: "local",
    weakId: isWeakId(msg.id),
  });
  bump(chatKey, b);
}

/**
 * Create-or-update a single message by id. Content grows monotonically (a
 * shorter incoming content is ignored unless `allowShrink`, e.g. finalize /
 * interrupt carrying authoritative final text). Metadata overwrites when
 * provided. This is the general per-message op the ChatPage compatibility shim
 * maps array-style updates onto — per-message upsert, NEVER whole-list replace
 * (the latter was the vanish bug). Returns true if anything changed.
 */
export function upsert(
  chatKey: string,
  msg: Omit<TranscriptMessage, "seq" | "origin" | "weakId"> &
    Partial<Pick<TranscriptMessage, "seq" | "origin" | "weakId">>,
  opts: { allowShrink?: boolean } = {},
): boolean {
  const b = bucket(chatKey);
  const existing = b.byId.get(msg.id);
  if (!existing) {
    b.byId.set(msg.id, {
      ...msg,
      seq: msg.seq ?? b.liveSeq++,
      origin: msg.origin ?? "local",
      weakId: msg.weakId ?? isWeakId(msg.id),
    });
    bump(chatKey, b);
    return true;
  }
  const next: TranscriptMessage = { ...existing };
  let changed = false;
  const incoming = msg.content ?? "";
  const grew = incoming.length > (existing.content?.length ?? 0);
  if (grew || (opts.allowShrink && incoming !== existing.content)) {
    next.content = incoming;
    changed = true;
  }
  for (const key of [
    "status",
    "completedAt",
    "tokenCount",
    "title",
    "warning",
    "tools",
    "traces",
    "attachments",
  ] as const) {
    const v = (msg as unknown as Record<string, unknown>)[key];
    if (v !== undefined && v !== (existing as unknown as Record<string, unknown>)[key]) {
      // Never demote a finished message back to streaming.
      if (
        key === "status" &&
        v === "streaming" &&
        existing.status &&
        existing.status !== "streaming"
      ) {
        continue;
      }
      (next as unknown as Record<string, unknown>)[key] = v;
      changed = true;
    }
  }
  if (changed) {
    b.byId.set(msg.id, next);
    bump(chatKey, b);
  }
  return changed;
}

export function beginAssistant(
  chatKey: string,
  messageId: string,
  createdAt: number = Date.now(),
): void {
  const b = bucket(chatKey);
  const existing = b.byId.get(messageId);
  if (existing) {
    // Replay tolerance: a duplicate start never resets rendered content,
    // and never demotes a finished message back to streaming.
    if (existing.status !== "streaming" && existing.status !== undefined) return;
    return;
  }
  b.byId.set(messageId, {
    id: messageId,
    role: "assistant",
    content: "",
    createdAt,
    status: "streaming",
    seq: b.liveSeq++,
    origin: "stream",
    weakId: false,
  });
  bump(chatKey, b);
}

export function appendDelta(
  chatKey: string,
  messageId: string,
  deltaText: string,
): void {
  if (!deltaText) return;
  const b = bucket(chatKey);
  let m = b.byId.get(messageId);
  if (!m) {
    // Unknown id implies begin (reconnect/replay tolerance).
    beginAssistant(chatKey, messageId);
    m = b.byId.get(messageId)!;
  }
  if (m.status === "complete" || m.status === "interrupted" || m.status === "error") {
    // A late delta for a finished message would corrupt final content.
    return;
  }
  b.byId.set(messageId, { ...m, content: m.content + deltaText });
  bump(chatKey, b);
}

export function finalize(
  chatKey: string,
  messageId: string,
  final: {
    content: string;
    status: Exclude<TranscriptStatus, "streaming">;
    completedAt: number;
    tokenCount?: number;
    warning?: string;
  },
): void {
  const b = bucket(chatKey);
  const m = b.byId.get(messageId);
  if (!m) {
    // complete without start (replay edge): create whole message.
    b.byId.set(messageId, {
      id: messageId,
      role: "assistant",
      content: final.content,
      createdAt: final.completedAt,
      status: final.status,
      completedAt: final.completedAt,
      tokenCount: final.tokenCount,
      warning: final.warning,
      seq: b.liveSeq++,
      origin: "stream",
      weakId: false,
    });
    bump(chatKey, b);
    return;
  }
  // finalize is authoritative (carries the gateway's full final_response) —
  // accept shorter content but count it: should be zero post-refactor.
  if ((final.content?.length ?? 0) < (m.content?.length ?? 0)) {
    telemetry.finalizeShrinks += 1;
  }
  b.byId.set(messageId, {
    ...m,
    content: final.content || m.content,
    status: final.status,
    completedAt: final.completedAt,
    tokenCount: final.tokenCount ?? m.tokenCount,
    warning: final.warning ?? m.warning,
  });
  bump(chatKey, b);
}

export function confirmLocalId(
  chatKey: string,
  localId: string,
  serverId: string,
): void {
  if (!serverId || localId === serverId) return;
  const b = bucket(chatKey);
  const m = b.byId.get(localId);
  if (!m || b.byId.has(serverId)) return;
  b.byId.delete(localId);
  b.byId.set(serverId, { ...m, id: serverId, weakId: isWeakId(serverId) });
  bump(chatKey, b);
}

export function patchMeta(
  chatKey: string,
  messageId: string,
  meta: TranscriptMetaPatch,
): void {
  const b = bucket(chatKey);
  const m = b.byId.get(messageId);
  if (!m) return;
  const next: TranscriptMessage = { ...m };
  for (const key of PATCHABLE_META) {
    if (key in meta && meta[key] !== undefined) {
      // status can never go back to streaming via a patch.
      if (key === "status" && meta.status === "streaming" && m.status !== "streaming") {
        continue;
      }
      (next as unknown as Record<string, unknown>)[key] = meta[key];
    }
  }
  b.byId.set(messageId, next);
  bump(chatKey, b);
}

export function unionHydrate(
  chatKey: string,
  msgs: HydratedWireMessage[],
  _source: HydrateSource,
): UnionReport {
  const report: UnionReport = {
    added: 0,
    updated: 0,
    shrinksDropped: 0,
    weakMatches: 0,
  };
  if (!Array.isArray(msgs) || !msgs.length) return report;
  const b = bucket(chatKey);
  // Weak-id fingerprint index over EXISTING weak messages (legacy ids only).
  const weakByFp = new Map<string, TranscriptMessage>();
  for (const m of b.byId.values()) {
    if (m.weakId) weakByFp.set(fingerprint(m.role, m.content), m);
  }
  let mutated = false;

  for (const wire of msgs) {
    if (!wire || typeof wire !== "object") continue;
    const wireId = wire.message_id || null;
    const weak = isWeakId(wireId);
    let target: TranscriptMessage | undefined = !weak
      ? b.byId.get(wireId!)
      : undefined;

    if (!target && weak) {
      // Fingerprint matching is allowed ONLY weak↔weak.
      const match = weakByFp.get(fingerprint(wire.role, wire.content));
      if (match) {
        target = match;
        report.weakMatches += 1;
        telemetry.weakMatches += 1;
        // Adopt the incoming id when the existing one is a placeholder
        // (`weak.*`) — a wire `legacy.*` id is at least as strong, and
        // future hydrates will then match it directly by id.
        if (wireId && target.id !== wireId && !b.byId.has(wireId)) {
          b.byId.delete(target.id);
          target = { ...target, id: wireId };
          b.byId.set(wireId, target);
          mutated = true;
        }
      }
    }

    if (target) {
      // UPDATE path: union never removes, never shrinks, never demotes,
      // never clobbers client-owned metadata.
      const next: TranscriptMessage = { ...target };
      let changed = false;
      const incoming = wire.content ?? "";
      if (incoming.length > (next.content?.length ?? 0)) {
        next.content = incoming;
        changed = true;
      } else if (incoming.length < (next.content?.length ?? 0) && incoming.length > 0) {
        report.shrinksDropped += 1;
        telemetry.shrinksDropped += 1;
      }
      if (
        wire.status &&
        wire.status !== "streaming" &&
        (next.status === "streaming" || next.status === undefined)
      ) {
        next.status = wire.status;
        changed = true;
      }
      for (const key of ["completedAt", "tokenCount", "title", "warning"] as const) {
        if (next[key] === undefined && wire[key] !== undefined) {
          (next as unknown as Record<string, unknown>)[key] = wire[key];
          changed = true;
        }
      }
      for (const key of ["tools", "traces", "attachments"] as const) {
        if ((next[key] === undefined || !next[key]?.length) && wire[key]?.length) {
          (next as unknown as Record<string, unknown>)[key] = wire[key];
          changed = true;
        }
      }
      if (changed) {
        b.byId.set(next.id, next);
        report.updated += 1;
        mutated = true;
      }
      continue;
    }

    // INSERT path.
    const id = wireId || `weak.${chatKey}.${b.hydrateSeq}`;
    if (b.byId.has(id)) continue;
    const inserted: TranscriptMessage = {
      id,
      role: wire.role,
      content: wire.content ?? "",
      createdAt: wire.createdAt ?? Date.now(),
      status: wire.status ?? "complete",
      completedAt: wire.completedAt,
      title: wire.title,
      warning: wire.warning,
      tools: wire.tools,
      traces: wire.traces,
      tokenCount: wire.tokenCount,
      attachments: wire.attachments,
      seq: b.hydrateSeq++,
      origin: "hydrate",
      weakId: weak,
    };
    b.byId.set(id, inserted);
    if (weak) weakByFp.set(fingerprint(inserted.role, inserted.content), inserted);
    report.added += 1;
    mutated = true;
  }

  if (mutated) bump(chatKey, b);
  return report;
}

export function rekey(oldKey: string, newKey: string): void {
  if (!oldKey || !newKey || oldKey === newKey) return;
  const old = buckets.get(oldKey);
  if (!old) return;
  const next = bucket(newKey);
  for (const [id, m] of old.byId) {
    if (!next.byId.has(id)) next.byId.set(id, m);
  }
  next.liveSeq = Math.max(next.liveSeq, old.liveSeq);
  next.hydrateSeq = Math.max(next.hydrateSeq, old.hydrateSeq);
  // Listeners keep watching the OLD key's subscription objects; the caller
  // re-subscribes via useTranscript(newKey) on the same render pass. Notify
  // both sides so any straggler re-reads.
  buckets.delete(oldKey);
  const s = storage();
  if (s) {
    try {
      const all = readV2();
      if (all[oldKey]) {
        delete all[oldKey];
        s.setItem(V2_KEY, JSON.stringify(all));
      }
    } catch {
      /* best-effort */
    }
  }
  bump(newKey, next);
  for (const cb of old.listeners) cb();
}

/** The ONLY remover. Wire exclusively to the explicit New Chat action. */
export function clear(chatKey: string): void {
  const b = buckets.get(chatKey);
  telemetry.clears += 1;
  if (b) {
    b.byId.clear();
    b.liveSeq = LIVE_SEQ_BASE;
    b.hydrateSeq = 0;
    bump(chatKey, b);
  }
  const s = storage();
  if (s) {
    try {
      const all = readV2();
      if (all[chatKey]) {
        delete all[chatKey];
        s.setItem(V2_KEY, JSON.stringify(all));
      }
    } catch {
      /* best-effort */
    }
  }
}

export function getTelemetry(): TranscriptTelemetry {
  return { ...telemetry };
}

export function useTranscript(chatKey: string): readonly TranscriptMessage[] {
  return useSyncExternalStore(
    (cb) => subscribe(chatKey, cb),
    () => getSnapshot(chatKey),
  );
}

// ─── Test hooks (no-ops in production code paths) ───────────────────────

export function _setStorageForTests(s: StorageLike | null): void {
  storageOverride = s;
  legacyKeysPurged = false;
  storeActive = false;
}

export function _setStoreActiveForTests(v: boolean): void {
  storeActive = v;
}

export function _resetForTests(): void {
  buckets.clear();
  dirtyChats.clear();
  if (writeTimer) {
    clearTimeout(writeTimer);
    writeTimer = null;
  }
  telemetry.shrinksDropped = 0;
  telemetry.weakMatches = 0;
  telemetry.finalizeShrinks = 0;
  telemetry.clears = 0;
}

export function _flushWritesForTests(): void {
  flushWrites();
}
