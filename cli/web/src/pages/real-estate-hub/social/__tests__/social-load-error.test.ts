import { describe, expect, it } from "vitest";

import { socialIdeaQueueStatus, socialLoadErrorFromResults } from "../index";

describe("social load errors", () => {
  it("surfaces partial source failures", () => {
    const error = socialLoadErrorFromResults([
      { status: "fulfilled", value: {} },
      { status: "rejected", reason: new Error("ideas down") },
      { status: "fulfilled", value: {} },
    ]);

    expect(error).toBe("1 social source failed: ideas down");
  });

  it("keeps the original full-failure message", () => {
    const error = socialLoadErrorFromResults([
      { status: "rejected", reason: new Error("snapshot down") },
      { status: "rejected", reason: new Error("ideas down") },
    ]);

    expect(error).toBe("snapshot down");
  });

  it("loads the approval queue through the backend default bucket", () => {
    expect(socialIdeaQueueStatus()).toBeUndefined();
  });
});
