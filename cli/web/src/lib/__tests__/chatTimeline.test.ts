import { describe, expect, it } from "vitest";

import {
  mergeServerWithCache,
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
});
