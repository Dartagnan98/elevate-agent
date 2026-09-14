import fs from "node:fs";
import { describe, expect, it } from "vitest";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("onboarding UI recovery wiring", () => {
  it("keeps agent onboarding load, save, complete, and reset failures visible", () => {
    const page = source("../index.tsx");
    const wizard = source("../wizard.tsx");

    expect(page).toContain('errorMessage(err, "Could not load agent setup")');
    expect(page).toContain("onClick={() => void refresh()}");
    expect(page).toMatch(/>\s*Retry\s*</);
    expect(page).toContain("api.resetAgentSetup()");
    expect(page).toContain('errorMessage(err, "Could not re-open onboarding")');
    expect(page).toContain('errorMessage(err, "Save failed")');
    expect(page).toContain('errorMessage(err, "Could not complete setup")');
    expect(wizard).toContain('errorMessage(err, "Could not complete onboarding")');
  });

  it("keeps leads onboarding load, connector, save, and complete recovery paths visible", () => {
    const page = source("../../RealEstateHubPages.tsx");
    const onboarding = source("../../real-estate-hub/leads/onboarding.tsx");
    const onboardingState = source("../../real-estate-hub/leads/onboarding-state.ts");
    const onboardingWizard = source("../../real-estate-hub/leads/onboarding-wizard.tsx");
    const onboardingConnectorStep = source("../../real-estate-hub/leads/onboarding-connector-step.tsx");
    const api = source("../../../lib/api.ts");

    expect(page).toContain("Could not load leads setup");
    expect(page).toContain("onClick={() => void leadsSetup.refresh()}");
    expect(page).toMatch(/>\s*Retry\s*</);
    expect(onboarding).toContain("api.getSourceConnectors()");
    expect(onboarding).toContain("// best-effort — leave previous list in place");
    expect(onboardingState).toContain('errorMessage(err, "Could not load leads setup")');
    expect(onboarding).toContain('errorMessage(err, "Save failed")');
    expect(onboarding).toContain('errorMessage(err, "Could not complete setup")');
    expect(onboardingWizard).toContain("const [copyStatus");
    expect(onboardingWizard).toContain("await navigator.clipboard.writeText(prompt)");
    expect(onboardingWizard).toContain("Could not copy prompt.");
    expect(onboardingConnectorStep).toContain("{copyStatus[connector.id].message}");
    expect(api).toContain("resetLeadsSetup");
  });
});
