import { describe, expect, it } from "vitest";

import { ErrorBoundary } from "../ErrorBoundary";

describe("ErrorBoundary", () => {
  it("derives error state from a thrown error (renders fallback instead of white-screening)", () => {
    const state = ErrorBoundary.getDerivedStateFromError(new Error("boom"));
    expect(state.error).toBeInstanceOf(Error);
    expect(state.error?.message).toBe("boom");
  });

  it("carries an empty error state by default (renders children when nothing threw)", () => {
    // Fresh instances start clean → children render, not the fallback.
    const instance = new ErrorBoundary({ children: null });
    expect(instance.state.error).toBeNull();
  });
});
