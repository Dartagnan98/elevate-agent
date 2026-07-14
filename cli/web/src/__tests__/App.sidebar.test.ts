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

  it("never calls a recently idle session Done", () => {
    const status = __appTestables.sessionStatusPresentation({
      lastActive: 1_000,
      nowMs: 1_001_000,
      unread: false,
    });

    expect(status).toEqual({ label: "Idle", tone: "idle" });
    expect(status.label).not.toBe("Done");
  });
});

describe("Realtor reporting route", () => {
  const lockedPacks = {
    realEstateSales: false,
    realEstateMarketing: false,
    realEstateAdmin: false,
    realEstateCma: false,
    realEstateAny: false,
  };

  it("preloads the reporting bundle and gates it with the sales pack", () => {
    expect(__appTestables.routePreloaders["/reporting"]).toBeTypeOf("function");

    const locked = __appTestables.buildAccessControlledBuiltinRoutes(false, lockedPacks);
    expect(locked["/reporting"]).toBe(locked["/leads"]);

    const enabled = __appTestables.buildAccessControlledBuiltinRoutes(false, {
      ...lockedPacks,
      realEstateSales: true,
      realEstateAny: true,
    });
    expect(enabled["/reporting"]).not.toBe(enabled["/leads"]);
    expect(enabled["/reporting"]).not.toBe(locked["/reporting"]);
  });
});
