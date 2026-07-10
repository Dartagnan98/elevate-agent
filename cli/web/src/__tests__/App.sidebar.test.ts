import { describe, expect, it, vi } from "vitest";

vi.mock("@nous-research/ui/ui/components/selection-switcher", () => ({
  SelectionSwitcher: () => null,
}));
vi.mock("@nous-research/ui/ui/components/typography/index", () => ({
  Typography: () => null,
}));

import { __appTestables } from "../App";

describe("sidebar session loading", () => {
  it("coalesces overlapping refreshes", async () => {
    let finish!: () => void;
    const run = vi.fn(
      () => new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const inFlight = { current: null as Promise<void> | null };

    const first = __appTestables.coalesceInFlight(inFlight, run);
    const second = __appTestables.coalesceInFlight(inFlight, run);

    expect(first).toBe(second);
    expect(run).toHaveBeenCalledTimes(1);
    finish();
    await first;

    const third = __appTestables.coalesceInFlight(inFlight, run);
    expect(run).toHaveBeenCalledTimes(2);
    finish();
    await third;
  });
});
