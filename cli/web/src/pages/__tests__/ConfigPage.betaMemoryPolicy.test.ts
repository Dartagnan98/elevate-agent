import fs from "node:fs";
import { describe, expect, it } from "vitest";

import type { StatusResponse } from "@/lib/api";
import {
  isRealtorBetaStatus,
  resolveMemoryPolicyState,
} from "@/lib/beta-runtime";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("Realtor Beta memory settings", () => {
  it("activates only from exact lowercase server runtime truth", () => {
    expect(
      isRealtorBetaStatus({
        beta_runtime: { releaseChannel: "beta" },
      } as StatusResponse),
    ).toBe(true);
    expect(isRealtorBetaStatus(null)).toBe(false);
    expect(isRealtorBetaStatus({} as StatusResponse)).toBe(false);
    expect(
      isRealtorBetaStatus({
        beta_runtime: { releaseChannel: "Beta" },
      } as unknown as StatusResponse),
    ).toBe(false);
  });

  it("keeps controls closed on first render and status failure", () => {
    expect(resolveMemoryPolicyState(undefined)).toBe("loading");
    expect(resolveMemoryPolicyState(null)).toBe("unavailable");
    expect(
      resolveMemoryPolicyState({
        beta_runtime: { releaseChannel: "beta" },
      } as StatusResponse),
    ).toBe("beta");
    expect(resolveMemoryPolicyState({} as StatusResponse)).toBe("stable");
  });

  it("replaces external provider and embedding controls with local copy", () => {
    const page = source("../ConfigPage.tsx");

    expect(page).toContain("Local memory only");
    expect(page).toContain(
      "External memory services and embedding-based recall stay off.",
    );
    expect(page).toContain("{realtorBeta ? (");
    expect(page).toContain("{!realtorBeta && (");
    expect(page).toContain('memoryPolicyState === "loading"');
    expect(page).toContain('memoryPolicyState === "unavailable"');
    expect(page).toContain('realtorBeta={memoryPolicyState === "beta"}');
    expect(page).toContain("memory provider controls are paused");
  });
});
