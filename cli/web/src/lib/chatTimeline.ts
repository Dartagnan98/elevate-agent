export type ChatTimelineRole = "assistant" | "system" | "tool" | "user";

export interface ChatTimelineMessage {
  attachments?: unknown[];
  completedAt?: number;
  content: string;
  createdAt: number;
  id: string;
  role: ChatTimelineRole;
  status?: "streaming" | "complete" | "error" | "interrupted";
  tools?: unknown[];
  traces?: unknown[];
  tokenCount?: number;
  sessionKey?: string;
}

export function parseObjectPayload(text: string): Record<string, unknown> | null {
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

export function isRawToolPayload(text: string): boolean {
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

export function shouldKeepTranscriptMessage(
  role: ChatTimelineRole,
  content: string,
): boolean {
  const clean = content.trim();
  if (!clean) return false;
  if (role === "tool") return false;
  if (role !== "user" && isRawToolPayload(clean)) return false;
  if (clean.startsWith("[CONTEXT COMPACTION")) return false;
  if (clean.startsWith("[Your latest Plan panel plan was preserved")) return false;
  if (clean.startsWith("[Your active task list was preserved")) return false;
  if (clean.startsWith("[RECENT AUTONOMOUS ACTIVITY")) return false;
  if (role === "system") {
    if (/^⚡\s*loaded skill:/i.test(clean)) return false;
    if (/^session busy\b/i.test(clean)) return false;
  }
  if (role === "user") {
    if (/^\[SYSTEM:/.test(clean)) {
      if (/^\[SYSTEM: (?:The user |The ")/.test(clean)) return true;
      return false;
    }
    if (clean.startsWith("[System note:")) return false;
    if (clean.startsWith("You've reached the maximum number of tool-calling iterations")) {
      return false;
    }
    if (clean.startsWith("[Elevation Hub interface context]")) return false;
    if (clean.startsWith("User follow-up received while you were already working:")) {
      return false;
    }
    if (clean.startsWith("[Delegated task result")) return false;
  }
  return true;
}

const OUT_OF_ORDER_TURN_WINDOW_MS = 30_000;

function isConversationalRole(role: ChatTimelineRole): boolean {
  return role === "assistant" || role === "user";
}

export function previousConversationalMessage<T extends ChatTimelineMessage>(
  messages: T[],
  beforeIndex: number,
): T | null {
  for (let i = beforeIndex - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (isConversationalRole(message.role)) return message;
  }
  return null;
}

function shouldSwapOutOfOrderTurn<T extends ChatTimelineMessage>(
  messages: T[],
  assistantIndex: number,
): boolean {
  const assistant = messages[assistantIndex];
  const user = messages[assistantIndex + 1];
  if (!assistant || !user) return false;
  if (assistant.role !== "assistant" || user.role !== "user") return false;
  if (assistant.status === "streaming") return false;
  if (
    !shouldKeepTranscriptMessage(assistant.role, assistant.content) ||
    !shouldKeepTranscriptMessage(user.role, user.content)
  ) {
    return false;
  }

  const previous = previousConversationalMessage(messages, assistantIndex);
  if (previous?.role === "user") return false;

  const assistantAt = assistant.createdAt;
  const userAt = user.createdAt;
  if (
    typeof assistantAt === "number" &&
    typeof userAt === "number" &&
    Number.isFinite(assistantAt) &&
    Number.isFinite(userAt)
  ) {
    return Math.abs(assistantAt - userAt) <= OUT_OF_ORDER_TURN_WINDOW_MS;
  }
  return true;
}

export function repairOutOfOrderUserTurns<T extends ChatTimelineMessage>(
  messages: T[],
): T[] {
  if (messages.length < 2) return messages;
  let out: T[] | null = null;
  const list = () => out ?? messages;

  for (let i = 0; i < list().length - 1; i += 1) {
    if (!shouldSwapOutOfOrderTurn(list(), i)) continue;
    out = list().slice();
    const assistant = out[i];
    out[i] = out[i + 1];
    out[i + 1] = assistant;
    if (i > 0) i -= 2;
  }

  if (out) {
    blankTrace("repaired out-of-order user turn", {
      count: messages.length,
    });
  }
  return out ?? messages;
}

function messageFingerprint(m: ChatTimelineMessage): string {
  const c = (m.content ?? "").trim().replace(/\s+/g, " ").slice(0, 200);
  return `${m.role}:${c}`;
}

function hasCompletedAssistantBeforeNextUser<T extends ChatTimelineMessage>(
  messages: T[],
  afterIndex: number,
): boolean {
  for (let i = afterIndex + 1; i < messages.length; i += 1) {
    const message = messages[i];
    if (message.role === "user") return false;
    if (
      message.role === "assistant" &&
      message.status !== "streaming" &&
      shouldKeepTranscriptMessage(message.role, message.content)
    ) {
      return true;
    }
  }
  return false;
}

function dropCompletedStreamingPlaceholders<T extends ChatTimelineMessage>(
  messages: T[],
  serverMessages: T[],
): T[] {
  if (hasPendingTurn(serverMessages)) return messages;
  let changed = false;
  const next = messages.filter((message, index) => {
    if (message.role !== "assistant" || message.status !== "streaming") {
      return true;
    }
    const previous = previousConversationalMessage(messages, index);
    if (previous?.role !== "user") return true;
    if (!hasCompletedAssistantBeforeNextUser(messages, index)) return true;
    changed = true;
    return false;
  });
  return changed ? next : messages;
}

export function mergeServerWithCache<T extends ChatTimelineMessage>(
  serverMessages: T[],
  cached: T[] | null,
  serverAuthoritative = false,
): T[] {
  if (!cached?.length) return repairOutOfOrderUserTurns(serverMessages);
  const fp = messageFingerprint;
  const serverFingerprints = new Set(serverMessages.map(fp));

  const cachedByFp = new Map<string, T[]>();
  for (const msg of cached) {
    const key = fp(msg);
    const queue = cachedByFp.get(key) ?? [];
    queue.push(msg);
    cachedByFp.set(key, queue);
  }
  const enriched = serverMessages.map((msg): T => {
    const match = cachedByFp.get(fp(msg))?.shift();
    let next = msg;
    if (
      match &&
      (match.content?.length ?? 0) > (next.content?.length ?? 0)
    ) {
      next = { ...next, content: match.content } as T;
    }
    if (
      msg.role === "user" &&
      !msg.attachments?.length &&
      match?.attachments?.length
    ) {
      next = { ...next, attachments: match.attachments } as T;
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
        typeof match.tokenCount === "number" ||
        typeof match.completedAt === "number")
    ) {
      return {
        ...next,
        createdAt:
          typeof match.createdAt === "number" ? match.createdAt : next.createdAt,
        completedAt: match.completedAt,
        tools: match.tools,
        traces: match.traces,
        tokenCount: match.tokenCount,
      } as T;
    }
    return next;
  });

  if (serverAuthoritative) {
    const tail: T[] = [];
    for (let i = cached.length - 1; i >= 0; i--) {
      if (serverFingerprints.has(fp(cached[i]))) break;
      tail.unshift(cached[i]);
    }
    const merged = tail.length ? [...enriched, ...tail] : enriched;
    if (merged.length < 2) return merged;
    const repaired = dropCompletedStreamingPlaceholders(
      repairOutOfOrderUserTurns(merged),
      serverMessages,
    );
    blankTraceIfDropped(cached, repaired, fp, serverMessages.length);
    return repaired;
  }

  const enrichedByFp = new Map<string, T[]>();
  for (const m of enriched) {
    const key = fp(m);
    const queue = enrichedByFp.get(key) ?? [];
    queue.push(m);
    enrichedByFp.set(key, queue);
  }
  const remainingEnriched = new Set(enriched);
  const out: T[] = [];
  for (const cm of cached) {
    const key = fp(cm);
    const serverMatch = enrichedByFp.get(key)?.shift();
    if (serverMatch) {
      remainingEnriched.delete(serverMatch);
      out.push(serverMatch);
    } else {
      out.push(cm);
    }
  }
  for (const sm of enriched) {
    if (!remainingEnriched.has(sm)) continue;
    const at = typeof sm.createdAt === "number" ? sm.createdAt : Number.POSITIVE_INFINITY;
    let idx = out.length;
    while (idx > 0) {
      const prev = out[idx - 1];
      const prevAt = typeof prev.createdAt === "number" ? prev.createdAt : 0;
      if (prevAt <= at) break;
      idx--;
    }
    out.splice(idx, 0, sm);
  }
  const repaired = dropCompletedStreamingPlaceholders(
    repairOutOfOrderUserTurns(out),
    serverMessages,
  );
  blankTraceIfDropped(cached, repaired, fp, serverMessages.length);
  return repaired;
}

const RECONCILE_RECENT_MS = 120_000;

export function reconcileWithServerTruth<T extends ChatTimelineMessage>(
  merged: T[],
  serverMessages: T[],
  ownedSessionIds: Set<string>,
  currentAssistantId: string | null,
): T[] {
  if (!merged.length || !serverMessages.length) return merged;
  const counts = new Map<string, number>();
  for (const sm of serverMessages) {
    if (sm.role !== "user" && sm.role !== "assistant") continue;
    const key = messageFingerprint(sm);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const now = Date.now();
  const keep = new Array<boolean>(merged.length).fill(true);
  for (let i = merged.length - 1; i >= 0; i--) {
    const m = merged[i];
    if (m.role !== "user" && m.role !== "assistant") continue;
    if (m.status === "streaming" || (currentAssistantId && m.id === currentAssistantId)) {
      continue;
    }
    const key = messageFingerprint(m);
    const remaining = counts.get(key) ?? 0;
    if (remaining > 0) {
      counts.set(key, remaining - 1);
      continue;
    }
    if (m.sessionKey) {
      keep[i] = ownedSessionIds.has(m.sessionKey);
      continue;
    }
    keep[i] = now - (m.createdAt ?? 0) < RECONCILE_RECENT_MS;
  }
  if (keep.every(Boolean)) return merged;
  const out = merged.filter((_, i) => keep[i]);
  blankTrace("reconciled transcript against server truth", {
    droppedCount: merged.length - out.length,
    mergedLen: merged.length,
    serverLen: serverMessages.length,
  });
  return out;
}

export function dropForeignMessages<T extends ChatTimelineMessage>(
  messages: T[],
  ownedSessionIds: Set<string>,
): T[] {
  if (!messages.length || !ownedSessionIds.size) return messages;
  const out = messages.filter(
    (m) => !m.sessionKey || ownedSessionIds.has(m.sessionKey),
  );
  return out.length === messages.length ? messages : out;
}

export function blankTrace(message: string, data: Record<string, unknown>): void {
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

function blankTraceIfDropped(
  cached: ChatTimelineMessage[] | null,
  out: ChatTimelineMessage[],
  fp: (m: ChatTimelineMessage) => string,
  serverLen: number,
): void {
  try {
    const big = (m: ChatTimelineMessage) =>
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

export function hasPendingTurn(messages: ChatTimelineMessage[]): boolean {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant") return msg.status === "streaming";
    if (msg.role === "user") return true;
  }
  return false;
}

export function markStreamingTurnsInterrupted<T extends ChatTimelineMessage>(
  messages: T[],
  completedAt = Date.now(),
): T[] {
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
