import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(testDir, "../..");
const scanRoots = ["pages", "components"].map((dir) => path.join(srcRoot, dir));

function walkTsx(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (full.includes(`${path.sep}__tests__${path.sep}`)) return [];
    const st = statSync(full);
    if (st.isDirectory()) return walkTsx(full);
    return full.endsWith(".tsx") ? [full] : [];
  });
}

function read(relativePath: string): string {
  return readFileSync(path.join(srcRoot, relativePath), "utf8");
}

function lineNumber(source: string, index: number): number {
  return source.slice(0, index).split("\n").length;
}

function relative(file: string): string {
  return path.relative(srcRoot, file);
}

function hexVar(source: string, name: string): string {
  const match = source.match(new RegExp(`${name}:\\s*(#[0-9A-Fa-f]{6})`));
  expect(match).not.toBeNull();
  return match![1];
}

function contrastRatio(foreground: string, background: string): number {
  const luminance = (hex: string) => {
    const value = Number.parseInt(hex.slice(1), 16);
    const channels = [(value >> 16) & 255, (value >> 8) & 255, value & 255].map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.03928
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function windowAround(source: string, marker: string): string {
  const index = source.indexOf(marker);
  expect(index).toBeGreaterThanOrEqual(0);
  return source.slice(Math.max(0, index - 220), index + 420);
}

describe("icon-only control accessibility", () => {
  it.each([
    ["components/ui/modal.tsx", 'aria-label="Close modal"', "Close modal"],
    ["pages/ExperimentsPage.tsx", 'aria-label="Close dialog"', "Close dialog"],
    ["pages/real-estate-hub/admin-task-drawer.tsx", 'aria-label="Close task drawer"', "Close task drawer"],
    ["pages/real-estate-hub/thread-drawer.tsx", 'aria-label="Close thread drawer"', "Close thread drawer"],
    ["pages/real-estate-hub/leads/onboarding.tsx", 'aria-label="Cancel template edit"', "Cancel template edit"],
  ])("%s names critical icon-only close controls", (file, marker, label) => {
    const source = read(file);
    const block = windowAround(source, marker);

    expect(block).toContain(`aria-label="${label}"`);
    expect(block).toContain('aria-hidden="true"');
  });

  it.each([
    ["pages/real-estate-hub/admin/components/sidebar.tsx", 'aria-label="Collapse sidebar"'],
    ["pages/real-estate-hub/admin/components/sidebar.tsx", 'aria-label="Search"'],
    ["pages/ExperimentsPage.tsx", 'aria-label="Remove cycle"'],
    ["pages/real-estate-hub/social/board.tsx", 'aria-label="Refresh queue"'],
    ["pages/ChatPage.tsx", 'aria-label="Edit message"'],
    ["pages/ChatPage.tsx", 'aria-label={pinned ? "Unpin message" : "Pin message"}'],
    ["pages/ChatPage.tsx", 'aria-label="Open message actions"'],
    ["pages/CronPage.tsx", 'aria-label="Clear cron search"'],
    ["pages/SessionsPage.tsx", 'aria-label="Clear session search"'],
    ["pages/SkillsPage.tsx", 'aria-label="Clear skill search"'],
    ["pages/ExperimentsPage.tsx", "aria-label={`Remove goal ${i + 1}`}"],
    ["pages/HeartbeatPage.tsx", 'aria-label="Close heartbeat editor"'],
  ])("%s names additional icon-only controls", (file, marker) => {
    const source = read(file);
    const block = windowAround(source, marker);

    expect(block).toContain(marker);
    expect(block).toContain('aria-hidden="true"');
  });

  it("keeps embedded admin sidebar disabled controls visibly explained", () => {
    const source = read("pages/real-estate-hub/admin/components/sidebar.tsx");
    const styles = read("pages/real-estate-hub/admin/admin.css");

    expect(source).toContain("SIDEBAR_UNAVAILABLE_ID");
    expect(source).toContain('className="sidebar-unavailable-note"');
    expect(source).toContain("Embedded sidebar actions are unavailable here.");
    expect(source.match(/aria-describedby=\{SIDEBAR_UNAVAILABLE_ID\}/g)).toHaveLength(3);
    expect(source.match(/<UnavailableMenuRow/g)).toHaveLength(6);
    expect(source).not.toContain("disabled title=\"Unavailable in the embedded admin sidebar\"");
    expect(styles).toContain(".sidebar-unavailable-note");
    expect(styles).toContain(".user-menu-unavailable");
    expect(styles).toContain(".user-menu-row:disabled");
  });

  it("names both message copy icon buttons", () => {
    const source = read("pages/ChatPage.tsx");

    expect(source.match(/aria-label=\{copied \? "Copied message" : "Copy message"\}/g)).toHaveLength(2);
  });

  it("does not nest the OAuth provider docs link inside a button", () => {
    const source = read("components/OAuthProvidersCard.tsx");
    const docsLink = windowAround(source, "p.docs_url");

    expect(docsLink).toContain("aria-label={`Open ${p.name} docs`}");
    expect(docsLink).not.toMatch(/<a[\\s\\S]*<Button/);
  });

  it("keeps shared modal dialog semantics and focus recovery wired", () => {
    const source = read("components/ui/modal.tsx");

    expect(source).toContain('role="dialog"');
    expect(source).toContain('aria-modal="true"');
    expect(source).toContain("aria-labelledby={titleId}");
    expect(source).toContain("useDialogFocus");
    expect(source).toContain('initialFocusSelector: "[data-autofocus]"');
  });

  it("keeps shared dialog focus trapping and recovery wired", () => {
    const hook = read("components/ui/use-dialog-focus.ts");
    const confirm = read("components/ui/confirm-dialog.tsx");

    expect(hook).toContain('event.key !== "Tab"');
    expect(hook).toContain('event.key === "Escape"');
    expect(hook).toContain("document.body.style.overflow = \"hidden\"");
    expect(hook).toContain("prevActive?.focus?.()");
    expect(hook).toContain("last.focus()");
    expect(hook).toContain("first.focus()");
    expect(confirm).toContain("useDialogFocus");
    expect(confirm).toContain('initialFocusSelector: "[data-confirm]"');
  });

  it.each([
    ["components/ModelPickerDialog.tsx", 'initialFocusSelector: "input"'],
    ["components/OAuthLoginModal.tsx", 'initialFocusSelector: "[data-autofocus], input, button"'],
  ])("%s uses shared dialog focus management", (file, selector) => {
    const source = read(file);

    expect(source).toContain("useDialogFocus");
    expect(source).toContain(selector);
  });

  it("keeps dialog surfaces named with explicit modal state", () => {
    const failures: string[] = [];
    const dialogTag = /<[A-Za-z][^>]*role="dialog"[^>]*>/g;

    for (const file of scanRoots.flatMap(walkTsx)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(dialogTag)) {
        const tag = match[0];
        const hasName = /aria-label\s*=|aria-labelledby\s*=/.test(tag);
        const hasModalState = /aria-modal\s*=/.test(tag);
        if (!hasName || !hasModalState) {
          failures.push(`${relative(file)}:${lineNumber(source, match.index ?? 0)}`);
        }
      }
    }

    expect(failures).toEqual([]);
  });

  it("keeps shared Switch controls explicitly named", () => {
    const failures: string[] = [];

    for (const file of scanRoots.flatMap(walkTsx)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/<Switch\b[\s\S]*?\/>/g)) {
        const block = match[0];
        if (!/aria-label\s*=|aria-labelledby\s*=|title\s*=/.test(block)) {
          failures.push(`${relative(file)}:${lineNumber(source, match.index ?? 0)}`);
        }
      }
    }

    expect(failures).toEqual([]);
  });

  it("keeps browser-probed Skills and Social controls named and tappable", () => {
    const appCss = read("index.css");
    const hubData = read("pages/real-estate-hub/_shared/use-hub-data.tsx");
    const hubCss = read("pages/agent-hub.css");
    const skills = read("pages/SkillsPage.tsx");
    const socialBoard = read("pages/real-estate-hub/social/board.tsx");
    const socialCss = read("pages/real-estate-hub/social/social.css");
    const switchControl = read("components/ui/switch.tsx");

    expect(hubData).toContain('className="min-h-[40px]"');
    expect(skills).toContain('aria-label="Search skills"');
    expect(skills).toContain('className="min-h-[40px] pl-8 pr-7 text-xs"');
    expect(socialBoard).toContain('aria-label={"Show chart by " + g.noun}');
    expect(socialCss).toContain("min-width: 32px; min-height: 32px");
    expect(socialCss).toContain(".sm-root .sm-icon-btn {\n    appearance: none; width: 36px; height: 36px");
    expect(socialCss).toContain(".sm-root .sm-tab {\n    appearance: none; cursor: pointer;");
    expect(socialCss).toContain("min-height: 36px;");
    expect(socialCss).toContain("min-height: 36px; padding: 0 18px 0 0");
    expect(appCss).toContain("@media (max-width: 1023px)");
    expect(appCss).toContain('#root button:not([role="switch"]),');
    expect(appCss).toContain("#root a.hub-btn,");
    expect(appCss).toContain("#root a.td-card-link,");
    expect(appCss).toContain("#root input:not([type=\"hidden\"]),");
    expect(appCss).toContain("min-width: 36px;\n    min-height: 36px;");
    expect(hubCss).toContain("min-height: 36px;");
    expect(switchControl).toContain("h-[36px] w-[56px]");
    expect(switchControl).toContain("md:h-5 md:w-9");
    expect(appCss).toContain("#app-sidebar .nav-row,");
    expect(appCss).toContain("#app-sidebar .icon-btn {\n    width: 40px !important;\n    height: 40px !important;");
  });

  it("keeps browser-probed form controls explicitly named", () => {
    const adminBoard = read("pages/real-estate-hub/admin/components/admin-board.tsx");
    const agentHub = read("pages/AgentHubPage.tsx");
    const comms = read("pages/CommsPage.tsx");

    expect(adminBoard).toContain('aria-label="Search deals"');
    expect(agentHub).toContain('aria-label="Paste Telegram pairing code"');
    expect(agentHub).toContain('aria-label="Executive bot token"');
    expect(agentHub).toContain('aria-label="Executive chat or topic"');
    expect(comms).toContain('aria-label="Search messages"');
    expect(comms).toContain('aria-label="Filter channels"');
    expect(comms).toContain('aria-label="Handoff title"');
    expect(comms).toContain('aria-label="Handoff task details"');
    expect(comms).toContain('aria-label="Run handoff now"');
    expect(comms).toContain('aria-label="Show archived channels"');
  });

  it("keeps dark neutral text tokens above AA contrast on app surfaces", () => {
    const tokenFiles = [
      "index.css",
      "pages/agent-hub.css",
      "pages/real-estate-hub/admin/admin.css",
      "pages/real-estate-hub/leads/leads.css",
      "pages/real-estate-hub/social/social.css",
    ];

    for (const file of tokenFiles) {
      const source = read(file);
      for (const token of ["--fg-muted", "--fg-faint", "--fg-dim"]) {
        expect(contrastRatio(hexVar(source, token), "#202020"), `${file} ${token}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
