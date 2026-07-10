import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "../ChatPage";

type QueuedInput = Parameters<
  typeof __chatPageTestables.queueAfterConnectionReset
>[0][number];

function queued(id: string): QueuedInput {
  return {
    agentId: "executive-assistant",
    createdAt: 1,
    id,
    routedText: "hello",
    status: "queued",
    text: "hello",
  };
}

describe("chat prompt queue", () => {
  it("keeps a draft queue across a reconnect", () => {
    const current = [queued("queued-1")];

    expect(
      __chatPageTestables.queueAfterConnectionReset(current, [], true),
    ).toBe(current);
  });

  it("removes a queued prompt only after delivery is acknowledged", () => {
    const current = [queued("queued-1"), queued("queued-2")];

    expect(
      __chatPageTestables.settleQueuedDelivery(current, "queued-1", false),
    ).toBe(current);
    expect(
      __chatPageTestables.settleQueuedDelivery(current, "queued-1", true),
    ).toEqual([current[1]]);
  });
});
