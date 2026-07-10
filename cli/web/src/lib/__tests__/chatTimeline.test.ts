import { describe, expect, it } from "vitest";

import {
  mergeServerWithCache,
  settledChatStatusText,
  type ChatTimelineMessage,
} from "../chatTimeline";

function message(overrides: Partial<ChatTimelineMessage>): ChatTimelineMessage {
  return {
    content: "",
    createdAt: 1,
    id: "message-1",
    role: "assistant",
    status: "complete",
    ...overrides,
  };
}

describe("chat timeline merge", () => {
  it("keeps a live placeholder while the server still has a pending turn", () => {
    const server = [
      message({ content: "Still working?", createdAt: 1_000, id: "u1", role: "user" }),
    ];
    const cached = [
      message({ content: "Still working?", createdAt: 1_000, id: "cached-u1", role: "user" }),
      message({ content: "", createdAt: 1_010, id: "assistant-live", role: "assistant", status: "streaming" }),
    ];

    const merged = mergeServerWithCache(server, cached, false);

    expect(merged.map((item) => item.id)).toEqual(["u1", "assistant-live"]);
  });

  it("does not let a server refresh erase a cached terminal failure", () => {
    const server = [message({ content: "The request failed.", id: "server-a1" })];
    const cached = [
      message({ content: "The request failed.", id: "cached-a1", status: "error" }),
    ];

    expect(mergeServerWithCache(server, cached)[0].status).toBe("error");
  });
});

describe("settled chat status", () => {
  it("never reports Ready for a failed, interrupted, or unanswered turn", () => {
    expect(settledChatStatusText([message({ status: "error" })])).toBe("Error");
    expect(settledChatStatusText([message({ status: "interrupted" })])).toBe(
      "Interrupted",
    );
    expect(
      settledChatStatusText([
        message({ content: "Please finish this", role: "user", status: "complete" }),
      ]),
    ).toBe("Interrupted");
  });
});
