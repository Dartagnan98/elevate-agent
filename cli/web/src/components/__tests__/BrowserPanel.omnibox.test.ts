import { describe, expect, it } from "vitest";

import source from "../ChatSidePanels.tsx?raw";

describe("browser panel omnibox wiring", () => {
  it("renders an aria listbox wired to the address combobox", () => {
    expect(source).toContain('role="combobox"');
    expect(source).toContain('aria-autocomplete="list"');
    expect(source).toContain('role="listbox"');
    expect(source).toContain('role="option"');
    expect(source).toMatch(/aria-selected=\{index === activeIndex\}/);
    expect(source).toMatch(/aria-activedescendant=\{\s*dropdownVisible \? `\$\{listboxId\}-option-\$\{activeIndex\}` : undefined\s*\}/);
  });

  it("supports keyboard up/down + Enter + Escape on the address bar", () => {
    expect(source).toContain('event.key === "ArrowDown"');
    expect(source).toContain('event.key === "ArrowUp"');
    expect(source).toContain('event.key === "Escape"');
    expect(source).toMatch(/event\.key === "Enter"[\s\S]{0,300}navigateTo\(chosen \? chosen\.url : browserTarget\(address\)\)/);
  });

  it("suppresses the platform autofill dropdown on the address input", () => {
    const inputBlock = source.slice(
      source.indexOf('aria-label="Browser address"') - 600,
      source.indexOf('aria-label="Browser address"') + 600,
    );
    expect(inputBlock).toContain('autoComplete="off"');
    expect(inputBlock).toContain('data-browser-address="true"');
  });

  it("builds navigation targets through the shared omnibox module only", () => {
    expect(source).toContain('from "@/lib/omnibox"');
    // The inline google.com/search fallback (bot-wall trigger for bare words
    // like "youtube") must stay deleted from the component.
    expect(source).not.toContain("google.com/search");
  });

  it("records only real pane navigations into suggestion history", () => {
    expect(source).toContain("recordVisit");
    expect(source).toContain("retitleVisit");
    expect(source).toContain("BROWSER_HISTORY_STORAGE_KEY");
    expect(source).toMatch(/if \(tab\.loading \|\| !\/\^https\?:\\\/\\\/\/i\.test\(tab\.url\)\) continue;/);
  });

  it("hides the native WebContentsView while the dropdown is open", () => {
    expect(source).toMatch(/if \(!bridge \|\| !dropdownVisible\) return;[\s\S]{0,120}setVisible\(false\)/);
  });
});
