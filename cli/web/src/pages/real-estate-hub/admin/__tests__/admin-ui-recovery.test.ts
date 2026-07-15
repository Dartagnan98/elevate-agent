import { describe, expect, it } from "vitest";
import fs from "node:fs";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("admin deal UI recovery wiring", () => {
  it("keeps fetch failures visible and preserves data during silent refreshes", () => {
    const hook = source("../use-admin-deals.ts");

    expect(hook).toContain('setError(errMsg(e, "Admin deals failed"))');
    expect(hook).toContain("if (!options?.keepData) setDeals([])");
    expect(hook).toContain("await load(undefined, { keepData: options?.silent })");
  });

  it("rolls back optimistic stage moves and surfaces move errors", () => {
    const hook = source("../use-admin-deals.ts");

    expect(hook).toContain("prevStage = d.currentStage");
    expect(hook).toContain("return { ...d, currentStage: toStage }");
    expect(hook).toContain("prevStage !== undefined ? { ...d, currentStage: prevStage } : d");
    expect(hook).toContain('setError(errMsg(e, "Move deal failed"))');
  });

  it("renders visible errors with a refresh path on the admin board", () => {
    const shell = source("../AdminDesignShell.tsx");
    const board = source("../components/admin-board.tsx");

    expect(shell).toContain("const visibleError = error ||");
    expect(shell).toContain("error={visibleError}");
    expect(shell).toContain("onRefresh={() => handleRefresh()}");
    expect(shell).toContain("onMoveDeal={moveDeal}");
    expect(board).toContain("{error ? (");
    expect(board).toContain('role="alert"');
    expect(board).toContain('aria-live="polite"');
    expect(board).toContain("{error}");
    expect(board).toContain('onClick={onRefresh}');
    expect(board).toContain('disabled={loading}');
    expect(board).toContain('loading ? "Retrying..." : "Retry"');
  });

  it("does not claim offer-kit success after a failed HTTP response", () => {
    const offerKit = source("../components/offer-kit-wizard.tsx");

    expect(offerKit).toContain("await runKitRequests");
    expect(offerKit).toContain("await requireKitResponse");
    expect(offerKit).toContain('role="alert"');
    expect(offerKit).toContain('aria-live="polite"');
    expect(offerKit).toContain("setBuiltMsg(\"\")");
  });

  it("excludes the local offer-kit generator from exact Realtor Beta", () => {
    const offerKit = source("../components/offer-kit-wizard.tsx");

    expect(offerKit).toContain("api.getAdminSetup()");
    expect(offerKit).toContain(
      'setup.capabilities?.formsProvider === undefined ? "stable" : "beta"',
    );
    expect(offerKit).toContain(
      'offerKitPolicy === "stable" ? StableStep4',
    );
    expect(offerKit).toContain("CPS creation is paused in this Beta");
    expect(offerKit).toContain("Elevate will not generate a CPS from local templates");
    expect(offerKit).toContain("Deal details saved · provider PDF required");
  });

  it("excludes local onboarding-form generation and stale outputs from Beta", () => {
    const onboarding = source("../components/onboarding-panel.tsx");

    expect(onboarding).toContain("api.getAdminSetup()");
    expect(onboarding).toContain(
      'setup.capabilities?.formsProvider === undefined ? "stable" : "beta"',
    );
    expect(onboarding).toContain('documentPolicy === "stable" ? (');
    expect(onboarding).toContain("Onboarding form generation is paused in this Beta");
    expect(onboarding).toContain(
      "Elevate will not open, regenerate, approve, or send stale local forms",
    );
    expect(onboarding).toContain("PROVIDER REQUIRED");
  });

  it("keeps the listing kit truthful while provider routes are unavailable", () => {
    const listingKit = source("../components/listing-kit-wizard.tsx");

    expect(listingKit).toContain("Document creation and signing are paused");
    expect(listingKit).toContain("Checklist saves automatically");
    expect(listingKit).not.toContain("/listing-kit/");
    expect(listingKit).not.toContain("/listing-kit-doc/");
    expect(listingKit).not.toContain("/listing-sign");
    expect(listingKit).not.toContain("/listing-pull-records");
    expect(listingKit).not.toContain("Build Listing Package");
  });
});
