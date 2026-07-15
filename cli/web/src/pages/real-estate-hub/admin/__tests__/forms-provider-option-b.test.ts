import fs from "node:fs";
import { describe, expect, it } from "vitest";
import type { AdminSetupSnapshot } from "@/lib/api";
import {
  adminFormsProviderCardModel,
  canClaimAdminSetupReady,
  resolveAdminSetupShellState,
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
      createdAt: "2026-07-15T00:00:00Z",
      updatedAt: "2026-07-15T00:00:00Z",
    },
    items: [],
    readiness: [],
    complete: false,
    launchRequired: true,
    canStartAdmin: false,
    requiredCount: 1,
    completedRequiredCount: 0,
    missingRequiredKeys: ["forms_provider"],
    completionPct: 0,
    ...overrides,
  };
}

describe("Realtor Beta forms-provider Option B UI", () => {
  it("shows a disabled, truthful forms connector card for a fresh Beta user", () => {
    const setup = setupSnapshot({
      capabilities: {
        formsProvider: {
          available: false,
          reason: "live_forms_provider_not_verified",
          message: "Live forms-provider access has not been verified.",
        },
      },
      items: [
        {
          key: "forms_provider",
          category: "providers",
          label: "Forms provider",
          required: true,
          status: "missing",
          provider: null,
          sortOrder: 1,
          updatedAt: "2026-07-15T00:00:00Z",
        },
      ],
    });

    const card = adminFormsProviderCardModel(setup);

    expect(card).toMatchObject({
      exactBeta: true,
      visible: true,
      available: false,
      provider: "",
      title: "Forms provider",
      statusLabel: "provider needed",
      buttonLabel: "Connect & verify",
      buttonDisabled: true,
    });
    expect(card.disabledReason).toContain("not available in this Beta build");
  });

  it("lets global Admin onboarding finish while document drafting stays visibly paused", () => {
    const setup = setupSnapshot({
      profile: {
        ...setupSnapshot().profile,
        formsProvider: "WEBForms",
      },
      items: [
        {
          key: "forms_provider",
          category: "providers",
          label: "Forms provider",
          required: true,
          status: "configured",
          provider: "WEBForms",
          value: { provider: "WEBForms" },
          sortOrder: 1,
          updatedAt: "2026-07-15T00:00:00Z",
        },
      ],
      readiness: [
        {
          key: "forms_provider",
          label: "Forms provider",
          status: "configured",
          provider: "WEBForms",
          ready: true,
          state: "ready",
          detail: "Provider named for global setup.",
          action: "Use provider manually until live access is verified.",
          hasValue: true,
        },
      ],
      complete: true,
      launchRequired: false,
      canStartAdmin: true,
      requiredCount: 1,
      completedRequiredCount: 1,
      missingRequiredKeys: [],
      completionPct: 100,
      capabilities: {
        formsProvider: {
          available: false,
          reason: "live_forms_provider_not_verified",
          message: "Live forms-provider access has not been verified.",
        },
      },
    });

    expect(canClaimAdminSetupReady(setup)).toBe(true);
    expect(
      resolveAdminSetupShellState({
        loading: false,
        error: null,
        setup,
        forceOnboarding: false,
      }),
    ).toBe("ready");
    expect(adminFormsProviderCardModel(setup)).toMatchObject({
      visible: true,
      provider: "WEBForms",
      statusLabel: "document drafting paused",
      buttonDisabled: true,
    });
  });

  it("hides the Beta warning after verification and leaves Stable unchanged", () => {
    const verified = setupSnapshot({
      capabilities: { formsProvider: { available: true } },
    });
    expect(adminFormsProviderCardModel(verified)).toMatchObject({
      exactBeta: true,
      visible: false,
      available: true,
      statusLabel: "verified",
      buttonDisabled: false,
    });

    const stable = setupSnapshot({
      profile: { ...setupSnapshot().profile, formsProvider: "WEBForms" },
      capabilities: undefined,
    });
    expect(adminFormsProviderCardModel(stable)).toMatchObject({
      exactBeta: false,
      visible: false,
      provider: "WEBForms",
    });
  });

  it("wires the provider-only card without exposing a half-wired secret path", () => {
    const page = fs.readFileSync(new URL("../index.tsx", import.meta.url), "utf8");
    const shell = fs.readFileSync(new URL("../AdminDesignShell.tsx", import.meta.url), "utf8");
    const setupSource = fs.readFileSync(
      new URL("../../admin-setup.ts", import.meta.url),
      "utf8",
    );

    expect(page).not.toContain("formsLoginUrl");
    expect(page).not.toContain("formsLoginEmail");
    expect(page).not.toContain("formsLoginPassword");
    expect(page).not.toContain("save its login details");
    expect(setupSource).not.toContain("playbooks.forms");
    expect(setupSource).not.toContain("browserPlaybooks.forms");
    expect(page).toContain('kind: "forms-provider"');
    expect(page).toContain('label: "Connect & verify"');
    expect(page).toContain("disabledReason");
    expect(shell).toContain("Admin is ready. Document drafting is paused.");
    expect(shell).toContain("MLC and CPS tasks will wait for manual completion");
  });
});
