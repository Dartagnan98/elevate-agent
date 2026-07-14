import type { SourceInboxDraftSendStatusResponse } from "@/lib/api-types";

export const DRAFT_SEND_POLL_INTERVAL_MS = 750;
export const DRAFT_SEND_POLL_TIMEOUT_MS = 95_000;

export type DraftSendLifecyclePhase = "pending" | "sent" | "failed" | "timeout" | "unknown";

export interface DraftSendLifecycleState {
  phase: DraftSendLifecyclePhase;
  status: string | null;
  message: string;
  queueId?: string;
  providerMessageId?: string | null;
  lastError?: string | null;
}

export interface DraftSendLifecycleNotice extends DraftSendLifecycleState {
  draftId: string;
  draftName: string;
  updatedAt: number;
}

const REGISTERED_TRANSPORT_ALIASES = new Set([
  "sms",
  "text",
  "apple_messages",
  "imessage",
  "messages",
]);

export function hasRegisteredDraftTransport(channel: string | null | undefined): boolean {
  const normalized = String(channel || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  return REGISTERED_TRANSPORT_ALIASES.has(normalized);
}

export function draftApprovalBlockedReason(draft: {
  sourceId?: string | null;
  threadId?: string | null;
  taskId?: string | null;
  channel?: string | null;
}): string | null {
  if (!draft.sourceId || !draft.threadId || !draft.taskId) {
    return "Approve unavailable: exact source, thread, and task identifiers are required.";
  }
  if (!hasRegisteredDraftTransport(draft.channel)) {
    return `${draft.channel || "Message"} transport unavailable: connect a provider-backed Messages/SMS transport before approval.`;
  }
  return null;
}

export function isSimulatedDispatch(providerMessageId: string | null | undefined): boolean {
  return String(providerMessageId || "").toLowerCase().startsWith("stub-");
}

export function acceptedDispatchLabel(providerMessageId: string | null | undefined): string {
  return isSimulatedDispatch(providerMessageId) ? "Simulated — not sent" : "Dispatch accepted";
}

export function retrySendOutcomeLabel(result: {
  status: string;
  lastError?: string | null;
  providerMessageId?: string | null;
}): string {
  const status = result.status.trim().toLowerCase();
  if (status === "sent") return acceptedDispatchLabel(result.providerMessageId);
  if (status === "retrying") {
    return `Retry scheduled${result.lastError ? ` — ${result.lastError}` : ""}`;
  }
  if (status === "failed") {
    return `Retry failed${result.lastError ? ` — ${result.lastError}` : ""}`;
  }
  return `Retry ${status || "started"}`;
}

export function initialDraftSendLifecycleState(): DraftSendLifecycleState {
  return {
    phase: "pending",
    status: "approving",
    message: "Approval is processing. Checking this draft's exact send status…",
  };
}

function stateFromSnapshot(snapshot: SourceInboxDraftSendStatusResponse): DraftSendLifecycleState {
  const status = String(snapshot.status || "").trim().toLowerCase();
  const base = {
    status: status || null,
    queueId: snapshot.queueId || snapshot.id,
    providerMessageId: snapshot.providerMessageId,
    lastError: snapshot.lastError,
  };

  if (!snapshot.queued || !status) {
    return {
      ...base,
      phase: "unknown",
      message: "Approval completed, but no exact send record was found. Refresh before trying again.",
    };
  }
  if (status === "sent") {
    return {
      ...base,
      phase: "sent",
      message: `${acceptedDispatchLabel(snapshot.providerMessageId)}.`,
    };
  }
  if (status === "failed") {
    return {
      ...base,
      phase: "failed",
      message: `Send failed${snapshot.lastError ? ` — ${snapshot.lastError}` : ""}.`,
    };
  }
  if (status === "queued" || status === "sending" || status === "retrying") {
    const message = status === "queued"
      ? "Approved. Send queued; checking exact status…"
      : status === "sending"
        ? "Approved. Dispatch processing; checking exact status…"
        : "Approved. Automatic retry pending; checking exact status…";
    return { ...base, phase: "pending", message };
  }
  return {
    ...base,
    phase: "unknown",
    message: `Exact send status is unknown (${status}). Refresh before trying again.`,
  };
}

type PollDraftSendOptions = {
  intervalMs?: number;
  timeoutMs?: number;
  now?: () => number;
  sleep?: (milliseconds: number) => Promise<void>;
  onProgress?: (state: DraftSendLifecycleState) => void;
};

const defaultSleep = (milliseconds: number) => new Promise<void>((resolve) => {
  globalThis.setTimeout(resolve, milliseconds);
});

export async function pollExactDraftSendStatus(
  lookup: (remainingMs: number) => Promise<SourceInboxDraftSendStatusResponse>,
  options: PollDraftSendOptions = {},
): Promise<DraftSendLifecycleState> {
  const intervalMs = Math.max(1, options.intervalMs ?? DRAFT_SEND_POLL_INTERVAL_MS);
  const timeoutMs = Math.max(1, options.timeoutMs ?? DRAFT_SEND_POLL_TIMEOUT_MS);
  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? defaultSleep;
  const startedAt = now();
  const maxAttempts = Math.ceil(timeoutMs / intervalMs) + 1;
  let attempts = 0;
  let lastPending: DraftSendLifecycleState | null = null;
  let lastLookupError: string | null = null;

  const timeoutState = (): DraftSendLifecycleState => {
    if (lastPending) {
      return {
        ...lastPending,
        phase: "timeout",
        message: "Exact send status timed out. Check Outbound History or Didn't Send before trying again.",
      };
    }
    return {
      phase: "unknown",
      status: null,
      message: `Exact send status remained unavailable${lastLookupError ? ` — ${lastLookupError}` : ""}. Refresh before trying again.`,
    };
  };

  while (true) {
    const elapsedBeforeLookup = Math.max(0, now() - startedAt);
    if (elapsedBeforeLookup >= timeoutMs || attempts >= maxAttempts) return timeoutState();
    attempts += 1;
    let snapshot: SourceInboxDraftSendStatusResponse;
    try {
      snapshot = await lookup(timeoutMs - elapsedBeforeLookup);
    } catch (error) {
      lastLookupError = error instanceof Error ? error.message : "status lookup failed";
      const elapsed = Math.max(0, now() - startedAt);
      if (elapsed >= timeoutMs || attempts >= maxAttempts) return timeoutState();
      const retryingState = lastPending ?? {
        phase: "pending" as const,
        status: "checking",
        message: `Exact status lookup is temporarily unavailable — ${lastLookupError}. Retrying…`,
      };
      options.onProgress?.(retryingState);
      await sleep(Math.min(intervalMs, timeoutMs - elapsed));
      continue;
    }

    const state = stateFromSnapshot(snapshot);
    if (state.phase !== "pending") return state;
    lastPending = state;
    lastLookupError = null;
    options.onProgress?.(state);

    const elapsed = Math.max(0, now() - startedAt);
    if (elapsed >= timeoutMs || attempts >= maxAttempts) {
      return timeoutState();
    }
    await sleep(Math.min(intervalMs, timeoutMs - elapsed));
  }
}
