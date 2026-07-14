import fs from "node:fs";
import { describe, expect, it } from "vitest";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("Realtor Beta onboarding memory policy", () => {
  it("uses runtime truth and pauses controls when status is unavailable", () => {
    const page = source("../index.tsx");

    expect(page).toContain("isRealtorBetaStatus(runtimeStatus)");
    expect(page).toContain("runtimeStatus === undefined");
    expect(page).toContain("runtimeStatus === null");
    expect(page).toContain("Onboarding controls are paused.");
    expect(page).toContain("realtorBeta={realtorBeta}");
  });

  it("replaces Supabase and embedding setup with local-only guidance", () => {
    const page = source("../index.tsx");
    const wizard = source("../wizard.tsx");

    expect(page).toContain("External memory services stay off in Realtor Beta.");
    expect(page).toContain("No embedding account or API key is needed.");
    expect(wizard).toContain("External embedding services stay off.");
    expect(wizard).toContain("No external memory account is needed.");
    expect(wizard).toContain("realtorBeta && step.id === \"memory\"");
  });
});
