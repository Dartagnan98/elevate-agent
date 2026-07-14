import { describe, expect, it, vi } from "vitest";
import type { AdminSetupSnapshot } from "@/lib/api";
import type { AdminSetupDraft } from "@/pages/real-estate-hub/admin-setup";
import {
  adminOnboardingExitDelay,
  adminOnboardingSeedingStepState,
  canClaimAdminSetupReady,
  missingAdminOnboardingFields,
  provinceGuideAvailability,
  resolveAdminSetupShellState,
  runAdminOnboardingSeedWithTimeout,
  saveBeforeAdminOnboardingAdvance,
  unresolvedAdminSetupReadiness,
} from "../admin-onboarding-state";

function setupSnapshot(overrides: Partial<AdminSetupSnapshot> = {}): AdminSetupSnapshot {
  return {
    profile: {
      id: "default",
      country: "CA",
      province: "BC",
      boardMemberships: [],
      regionalMemory: {},
      approvalPolicy: {},
      createdAt: "2026-07-13T00:00:00Z",
      updatedAt: "2026-07-13T00:00:00Z",
    },
    items: [],
    readiness: [],
    complete: false,
    launchRequired: true,
    canStartAdmin: false,
    requiredCount: 1,
    completedRequiredCount: 0,
    missingRequiredKeys: [],
    completionPct: 0,
    ...overrides,
  };
}

describe("Admin onboarding behavior", () => {
  it("reports required blank fields while allowing optional blanks", () => {
    const draft = {
      realtorLegalName: "",
      teamName: "",
    } as AdminSetupDraft;
    const missing = missingAdminOnboardingFields(
      [
        { key: "realtorLegalName", label: "Realtor legal name" },
        { key: "teamName", label: "Team / PREC", optional: true },
      ],
      draft,
    );

    expect(missing.map((field) => field.key)).toEqual(["realtorLegalName"]);
  });

  it("uses missing required keys when readiness is absent or contradictory", () => {
    const setup = setupSnapshot({
      items: [
        {
          key: "browser_workflows",
          category: "providers",
          label: "Browser-use portal playbooks",
          required: true,
          status: "configured",
          sortOrder: 1,
          updatedAt: "2026-07-13T00:00:00Z",
        },
      ],
      readiness: [
        {
          key: "browser_workflows",
          label: "Browser-use portal playbooks",
          status: "configured",
          ready: true,
          state: "ready",
          detail: "Ready",
          action: "No action needed.",
          hasValue: true,
        },
      ],
      missingRequiredKeys: ["browser_workflows"],
    });

    expect(unresolvedAdminSetupReadiness(setup).map((item) => item.key)).toEqual([
      "browser_workflows",
    ]);
    expect(canClaimAdminSetupReady(setup)).toBe(false);
  });

  it("claims ready only from a complete snapshot with no unresolved readiness", () => {
    const ready = setupSnapshot({
      complete: true,
      launchRequired: false,
      canStartAdmin: true,
      requiredCount: 1,
      completedRequiredCount: 1,
      missingRequiredKeys: [],
      completionPct: 100,
      readiness: [
        {
          key: "jurisdiction",
          label: "Province package",
          status: "configured",
          ready: true,
          state: "ready",
          detail: "Ready",
          action: "No action needed.",
          hasValue: true,
        },
      ],
    });

    expect(canClaimAdminSetupReady(ready)).toBe(true);
    expect(canClaimAdminSetupReady({ ...ready, complete: false })).toBe(false);
    expect(canClaimAdminSetupReady({ ...ready, canStartAdmin: false })).toBe(false);
    expect(canClaimAdminSetupReady({ ...ready, launchRequired: true })).toBe(false);
    expect(canClaimAdminSetupReady({ ...ready, readiness: [] })).toBe(false);
  });

  it("never resolves the Admin shell to the board while setup is loading or unavailable", () => {
    const ready = setupSnapshot({
      complete: true,
      launchRequired: false,
      canStartAdmin: true,
      completedRequiredCount: 1,
      readiness: [
        {
          key: "jurisdiction",
          label: "Province package",
          status: "configured",
          ready: true,
          state: "ready",
          detail: "Ready",
          action: "No action needed.",
          hasValue: true,
        },
      ],
    });
    expect(
      resolveAdminSetupShellState({ loading: true, error: null, setup: ready, forceOnboarding: false }),
    ).toBe("loading");
    expect(
      resolveAdminSetupShellState({ loading: false, error: "offline", setup: null, forceOnboarding: false }),
    ).toBe("error");
    expect(
      resolveAdminSetupShellState({ loading: false, error: null, setup: null, forceOnboarding: false }),
    ).toBe("error");
    expect(
      resolveAdminSetupShellState({ loading: false, error: null, setup: ready, forceOnboarding: false }),
    ).toBe("ready");
  });

  it("keeps a contradictory complete snapshot in onboarding until readiness is true", () => {
    const contradictory = setupSnapshot({
      complete: true,
      canStartAdmin: true,
      missingRequiredKeys: ["forms_provider"],
      readiness: [
        {
          key: "forms_provider",
          label: "Forms provider",
          status: "configured",
          ready: false,
          state: "needs_verification",
          detail: "A saved provider has not been verified.",
          action: "Run Verify connections.",
          hasValue: true,
        },
      ],
    });

    expect(
      resolveAdminSetupShellState({
        loading: false,
        error: null,
        setup: contradictory,
        forceOnboarding: false,
      }),
    ).toBe("onboarding");
  });

  it("distinguishes a guide lookup failure from verified no-guide coverage", () => {
    const base = { province: "BC", coverage: [], loading: false };
    expect(provinceGuideAvailability({ ...base, error: "offline" })).toBe("error");
    expect(provinceGuideAvailability({ ...base, error: null })).toBe("unavailable");
    expect(provinceGuideAvailability({ ...base, loading: true, error: null })).toBe("loading");
  });

  it("times out a stuck setup check without marking any steps done", async () => {
    vi.useFakeTimers();
    try {
      let resolveSeed!: (value: { missing: boolean; error: string | null }) => void;
      const seedRequest = new Promise<{ missing: boolean; error: string | null }>((resolve) => {
        resolveSeed = resolve;
      });
      const outcomePromise = runAdminOnboardingSeedWithTimeout(
        () => seedRequest,
        1_000,
      );

      await vi.advanceTimersByTimeAsync(1_000);
      const outcome = await outcomePromise;

      expect(outcome.kind).toBe("error");
      expect(adminOnboardingSeedingStepState({ kind: "running" }, 0)).toBe("active");
      expect(adminOnboardingSeedingStepState({ kind: "running" }, 1)).toBe("pending");
      expect(adminOnboardingSeedingStepState(outcome, 0)).toBe("pending");
      resolveSeed({ missing: false, error: null });
      await Promise.resolve();
    } finally {
      vi.useRealTimers();
    }
  });

  it("maps real setup results to complete, missing, and error outcomes", async () => {
    await expect(
      runAdminOnboardingSeedWithTimeout(async () => ({ missing: false, error: null }), 100),
    ).resolves.toEqual({ kind: "complete" });
    await expect(
      runAdminOnboardingSeedWithTimeout(async () => ({ missing: true, error: null }), 100),
    ).resolves.toEqual({ kind: "missing" });
    await expect(
      runAdminOnboardingSeedWithTimeout(async () => ({ missing: true, error: "verify failed" }), 100),
    ).resolves.toEqual({ kind: "error", message: "verify failed" });
  });

  it("does not advance after a failed save", async () => {
    const advance = vi.fn();
    await expect(
      saveBeforeAdminOnboardingAdvance(async () => false, advance),
    ).resolves.toBe(false);
    expect(advance).not.toHaveBeenCalled();

    await expect(
      saveBeforeAdminOnboardingAdvance(async () => true, advance),
    ).resolves.toBe(true);
    expect(advance).toHaveBeenCalledOnce();
  });

  it("skips transition delay for reduced motion and keeps a fallback otherwise", () => {
    expect(adminOnboardingExitDelay(true)).toBe(0);
    expect(adminOnboardingExitDelay(false)).toBeGreaterThan(0);
  });
});
