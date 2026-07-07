import { describe, expect, it } from "vitest";

import { pruneTranscriptIndex } from "../transcriptCacheIndex";

describe("pruneTranscriptIndex", () => {
  it("keeps everything under the cap and evicts nothing", () => {
    const { keep, evict } = pruneTranscriptIndex({ a: 1, b: 2 }, "c", 3, 24);
    expect(evict).toEqual([]);
    expect(keep.map(([id]) => id).sort()).toEqual(["a", "b", "c"]);
  });

  it("evicts the oldest beyond the cap", () => {
    const index = { old: 1, mid: 2, newer: 3 };
    const { keep, evict } = pruneTranscriptIndex(index, "newest", 4, 3);
    expect(keep).toHaveLength(3);
    expect(evict).toEqual(["old"]); // lowest timestamp dropped
  });

  it("never evicts the session being written (it is newest)", () => {
    const index: Record<string, number> = {};
    for (let i = 0; i < 30; i += 1) index[`s${i}`] = i; // all older
    const { keep, evict } = pruneTranscriptIndex(index, "current", 999, 24);
    expect(keep.map(([id]) => id)).toContain("current");
    expect(evict).not.toContain("current");
    expect(keep).toHaveLength(24);
  });

  it("updates the timestamp of an already-indexed session", () => {
    const { keep } = pruneTranscriptIndex({ a: 1, current: 2 }, "current", 500, 24);
    expect(Object.fromEntries(keep).current).toBe(500);
  });
});
