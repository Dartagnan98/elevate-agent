import { describe, expect, it } from "vitest";

import { tailWindow } from "../tailWindow";

const seq = (n: number) => Array.from({ length: n }, (_, i) => i);

describe("tailWindow", () => {
  it("returns the whole list when shorter than the window", () => {
    const { items, hasEarlier } = tailWindow(seq(10), 60);
    expect(hasEarlier).toBe(false);
    expect(items).toEqual(seq(10));
  });

  it("returns the whole list at exactly the window size (no earlier)", () => {
    const { items, hasEarlier } = tailWindow(seq(60), 60);
    expect(hasEarlier).toBe(false);
    expect(items).toHaveLength(60);
  });

  it("keeps exactly the last N in order when longer, flagging earlier", () => {
    const { items, hasEarlier } = tailWindow(seq(110), 60);
    expect(hasEarlier).toBe(true);
    expect(items).toHaveLength(60);
    expect(items[0]).toBe(50); // 110 - 60
    expect(items[items.length - 1]).toBe(109); // true latest preserved
  });

  it("handles an empty list", () => {
    const { items, hasEarlier } = tailWindow([], 60);
    expect(hasEarlier).toBe(false);
    expect(items).toEqual([]);
  });
});
