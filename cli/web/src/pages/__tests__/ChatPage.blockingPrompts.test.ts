import { describe, expect, it } from "vitest";

import {
  advanceBlockingPrompt,
  blockingPromptIdentity,
  emptyBlockingPromptQueue,
  enqueueBlockingPrompt,
} from "../../lib/blockingPromptQueue";

describe("ChatPage blocking prompt queue", () => {
  it("keeps every blocking prompt type in arrival order without overwrites", () => {
    const approval = {
      command: "rm -rf /tmp/example",
      description: "dangerous command",
      requestId: "approval-1",
      type: "approval" as const,
    };
    const clarify = {
      question: "Which client?",
      requestId: "clarify-1",
      type: "clarify" as const,
    };
    const sudo = { requestId: "sudo-1", type: "sudo" as const };
    const secret = {
      envVar: "CRM_API_KEY",
      requestId: "secret-1",
      type: "secret" as const,
    };

    let state = emptyBlockingPromptQueue<
      typeof approval | typeof clarify | typeof sudo | typeof secret
    >();
    for (const prompt of [approval, clarify, sudo, secret]) {
      state = enqueueBlockingPrompt(state, prompt);
    }

    expect(state.active).toEqual(approval);
    expect(state.queued).toEqual([clarify, sudo, secret]);

    state = advanceBlockingPrompt(state, blockingPromptIdentity(approval));
    expect(state.active).toEqual(clarify);
    expect(state.queued).toEqual([sudo, secret]);
  });

  it("deduplicates by type and request identity", () => {
    const prompt = {
      question: "Choose one",
      requestId: "request-1",
      type: "clarify" as const,
    };
    const first = enqueueBlockingPrompt(emptyBlockingPromptQueue(), prompt);

    expect(enqueueBlockingPrompt(first, { ...prompt })).toBe(first);
  });

  it("does not advance when a stale response targets another visible prompt", () => {
    const visible = {
      command: "danger",
      description: "approval",
      requestId: "current",
      type: "approval" as const,
    };
    const later = {
      envVar: "CRM_API_KEY",
      requestId: "later",
      type: "secret" as const,
    };
    const initial = emptyBlockingPromptQueue<typeof visible | typeof later>();
    const state = enqueueBlockingPrompt(
      enqueueBlockingPrompt(initial, visible),
      later,
    );

    expect(advanceBlockingPrompt(state, "approval:stale")).toBe(state);
    expect(state.active).toEqual(visible);
    expect(state.queued).toEqual([later]);
  });
});
