import { describe, expect, it } from "vitest";

import { __chatPageTestables } from "@/pages/ChatPage";

// FIX 1.4: shouldKeepTranscriptMessage must drop the compaction-internal
// scaffolding rows that the REST path hides server-side but the
// gateway-resume path does not. Without the client-side filter these render
// as user bubbles after a compaction (cold resume / reopened run / second
// surface). Tested against the REAL exported function (added to
// __chatPageTestables in this fix), not a copy.
const { shouldKeepTranscriptMessage } = __chatPageTestables;

describe("shouldKeepTranscriptMessage — FIX 1.4 compaction-internal filter", () => {
  const internalPrefixes = [
    "[CONTEXT COMPACTION",
    "[Your latest Plan panel plan was preserved",
    "[Your active task list was preserved",
    "[RECENT AUTONOMOUS ACTIVITY",
  ];

  it.each(internalPrefixes)(
    'drops role="user" rows starting with %j',
    (prefix) => {
      // bare prefix
      expect(shouldKeepTranscriptMessage("user", prefix)).toBe(false);
      // prefix with trailing content (real rows carry a payload after it)
      expect(
        shouldKeepTranscriptMessage("user", `${prefix}] ...payload...`),
      ).toBe(false);
      // leading whitespace must still be matched (function trims first)
      expect(shouldKeepTranscriptMessage("user", `  \n${prefix}`)).toBe(false);
    },
  );

  it("keeps a normal user message", () => {
    expect(
      shouldKeepTranscriptMessage("user", "Hey, can you pull the Q4 numbers?"),
    ).toBe(true);
  });

  it('drops every role="tool" message', () => {
    expect(shouldKeepTranscriptMessage("tool", "tool output here")).toBe(false);
    // even an otherwise-normal-looking string is dropped when role is tool
    expect(
      shouldKeepTranscriptMessage("tool", "Hey, can you pull the Q4 numbers?"),
    ).toBe(false);
  });

  it("drops empty and whitespace-only content", () => {
    expect(shouldKeepTranscriptMessage("user", "")).toBe(false);
    expect(shouldKeepTranscriptMessage("user", "   ")).toBe(false);
    expect(shouldKeepTranscriptMessage("user", " \n\t ")).toBe(false);
  });

  it("does NOT over-match a normal message that merely contains a bracket", () => {
    // brackets that are NOT one of the internal prefixes must pass through
    expect(
      shouldKeepTranscriptMessage("user", "I think option [A] is better"),
    ).toBe(true);
    expect(
      shouldKeepTranscriptMessage(
        "user",
        "see the note [CONTEXT] below for details",
      ),
    ).toBe(true);
    // contains the prefix text but not at the start — must not be dropped
    expect(
      shouldKeepTranscriptMessage(
        "user",
        "the log said [RECENT AUTONOMOUS ACTIVITY] mid-sentence",
      ),
    ).toBe(true);
  });
});
