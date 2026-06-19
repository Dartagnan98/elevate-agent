import fs from "node:fs";
import { describe, expect, it } from "vitest";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("Config source connector recovery UI", () => {
  it("renders backend recovery owner, kind, action, and error details", () => {
    const page = source("../ConfigPage.tsx");

    expect(page).toContain("connector.recoveryAction");
    expect(page).toContain('connector.recoverySeverity !== "none"');
    expect(page).toContain("Owner: {connector.recoveryOwner || connector.ownerAgent}");
    expect(page).toContain("connector.recoveryKind.replace");
    expect(page).toContain("Error: {connector.recoveryError}");
  });

  it("keeps connector prompt copy failures visible", () => {
    const page = source("../ConfigPage.tsx");

    expect(page).toContain("const [copyStatus");
    expect(page).toContain("await navigator.clipboard.writeText(prompt)");
    expect(page).toContain("Prompt copied.");
    expect(page).toContain("Could not copy prompt.");
    expect(page).toContain("{copyStatus[connector.id].message}");
  });
});
