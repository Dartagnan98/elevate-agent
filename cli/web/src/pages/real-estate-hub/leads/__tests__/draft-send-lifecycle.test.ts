import { describe, expect, it } from "vitest";

import {
  acceptedDispatchLabel,
  DRAFT_SEND_POLL_TIMEOUT_MS,
  draftApprovalBlockedReason,
  initialDraftSendLifecycleState,
  pollExactDraftSendStatus,
  retrySendOutcomeLabel,
} from "../draft-send-lifecycle";

describe("exact approved-draft send lifecycle", () => {
  it("starts with an explicit processing state", () => {
    expect(DRAFT_SEND_POLL_TIMEOUT_MS).toBe(95_000);
    expect(initialDraftSendLifecycleState()).toMatchObject({
      phase: "pending",
      status: "approving",
    });
    expect(initialDraftSendLifecycleState().message).toContain("processing");
  });

  it("fails approval closed without exact identity or a provider-backed transport", () => {
    expect(draftApprovalBlockedReason({
      sourceId: "apple-messages",
      threadId: "",
      taskId: "task-1",
      channel: "sms",
    })).toContain("exact source, thread, and task identifiers");
    expect(draftApprovalBlockedReason({
      sourceId: "email",
      threadId: "thread-1",
      taskId: "task-1",
      channel: "gmail",
    })).toContain("transport unavailable");
    expect(draftApprovalBlockedReason({
      sourceId: "apple-messages",
      threadId: "thread-1",
      taskId: "task-1",
      channel: "Apple Messages",
    })).toBeNull();
  });

  it("polls one exact draft through queued and sending to terminal sent", async () => {
    const statuses = ["queued", "sending", "sent"];
    const progress: Array<string | null> = [];
    let now = 0;
    let calls = 0;

    const result = await pollExactDraftSendStatus(
      async () => {
        const status = statuses[calls++] ?? "sent";
        return {
          queued: true,
          queueId: "send-1",
          status,
          providerMessageId: status === "sent" ? "provider-1" : null,
        };
      },
      {
        intervalMs: 5,
        timeoutMs: 20,
        now: () => now,
        sleep: async (milliseconds) => { now += milliseconds; },
        onProgress: (state) => progress.push(state.status),
      },
    );

    expect(calls).toBe(3);
    expect(progress).toEqual(["queued", "sending"]);
    expect(result).toMatchObject({ phase: "sent", status: "sent", message: "Dispatch accepted." });
  });

  it("retries a transient lookup failure inside the same overall deadline", async () => {
    let now = 0;
    let calls = 0;
    const progress: Array<string | null> = [];
    const result = await pollExactDraftSendStatus(
      async () => {
        calls += 1;
        if (calls === 1) throw new Error("temporary timeout");
        if (calls === 2) return { queued: true, queueId: "send-1", status: "sending" };
        return { queued: true, queueId: "send-1", status: "sent", providerMessageId: "provider-1" };
      },
      {
        intervalMs: 5,
        timeoutMs: 20,
        now: () => now,
        sleep: async (milliseconds) => { now += milliseconds; },
        onProgress: (state) => progress.push(state.status),
      },
    );

    expect(calls).toBe(3);
    expect(progress).toEqual(["checking", "sending"]);
    expect(result.phase).toBe("sent");
  });

  it("ends repeated lookup failures as explicit unknown at the same deadline", async () => {
    let now = 0;
    let calls = 0;
    const result = await pollExactDraftSendStatus(
      async () => {
        calls += 1;
        throw new Error("status service unavailable");
      },
      {
        intervalMs: 5,
        timeoutMs: 10,
        now: () => now,
        sleep: async (milliseconds) => { now += milliseconds; },
      },
    );

    expect(calls).toBe(2);
    expect(result.phase).toBe("unknown");
    expect(result.message).toContain("remained unavailable");
  });

  it("stops a non-terminal exact lookup at the bounded timeout", async () => {
    let now = 0;
    let calls = 0;
    const result = await pollExactDraftSendStatus(
      async () => {
        calls += 1;
        return { queued: true, queueId: "send-1", status: "retrying" };
      },
      {
        intervalMs: 5,
        timeoutMs: 10,
        now: () => now,
        sleep: async (milliseconds) => { now += milliseconds; },
      },
    );

    expect(calls).toBe(2);
    expect(result).toMatchObject({ phase: "timeout", status: "retrying" });
    expect(result.message).toContain("timed out");
  });

  it("reports terminal failure and missing exact records without guessing", async () => {
    await expect(pollExactDraftSendStatus(async () => ({
      queued: true,
      status: "failed",
      lastError: "provider rejected recipient",
    }))).resolves.toMatchObject({
      phase: "failed",
      message: "Send failed — provider rejected recipient.",
    });

    await expect(pollExactDraftSendStatus(async () => ({
      queued: false,
      status: null,
    }))).resolves.toMatchObject({
      phase: "unknown",
    });
  });

  it("uses truthful dispatch labels for real and sandbox retry outcomes", () => {
    expect(acceptedDispatchLabel("provider-1")).toBe("Dispatch accepted");
    expect(acceptedDispatchLabel("stub-sms-1")).toBe("Simulated — not sent");
    expect(retrySendOutcomeLabel({ status: "sent", providerMessageId: "provider-1" })).toBe("Dispatch accepted");
    expect(retrySendOutcomeLabel({ status: "sent", providerMessageId: "stub-sms-1" })).toBe("Simulated — not sent");
  });
});
