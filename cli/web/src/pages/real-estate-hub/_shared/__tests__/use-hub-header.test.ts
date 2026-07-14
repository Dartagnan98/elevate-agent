import { describe, expect, it } from "vitest";

import { resolveHubHeaderRefreshBusy } from "../use-hub-data";

describe("hub header refresh ownership", () => {
  it("does not let unrelated hub loading disable a page-owned refresh", () => {
    expect(resolveHubHeaderRefreshBusy(
      { loading: true, refreshing: true },
      true,
      false,
    )).toBe(false);
  });

  it("uses the page-owned busy state when a custom refresh is supplied", () => {
    expect(resolveHubHeaderRefreshBusy(
      { loading: false, refreshing: false },
      true,
      true,
    )).toBe(true);
  });

  it("keeps default hub refreshes tied to hub loading", () => {
    expect(resolveHubHeaderRefreshBusy(
      { loading: true, refreshing: false },
      false,
    )).toBe(true);
  });
});
