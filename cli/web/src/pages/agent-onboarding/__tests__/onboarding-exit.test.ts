import fs from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  AGENT_ONBOARDING_ROUTED_KEY,
  exitAgentOnboardingToChat,
} from "../onboarding-exit";

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("agent onboarding escape", () => {
  it("marks the session before replacing onboarding with a fresh Chat", () => {
    const calls: string[] = [];
    const storage = {
      setItem: vi.fn((key: string, value: string) => calls.push(`store:${key}:${value}`)),
    };
    const navigate = vi.fn((path: string, options?: { replace?: boolean }) => {
      calls.push(`navigate:${path}:${String(options?.replace)}`);
    });

    exitAgentOnboardingToChat(navigate, 1234, storage);

    expect(calls).toEqual([
      `store:${AGENT_ONBOARDING_ROUTED_KEY}:1`,
      "navigate:/chat?new=1234&seed=1234:true",
    ]);
  });

  it("still exits when session storage is unavailable", () => {
    const navigate = vi.fn();
    const storage = {
      setItem: () => {
        throw new Error("storage blocked");
      },
    };

    exitAgentOnboardingToChat(navigate, 55, storage);

    expect(navigate).toHaveBeenCalledWith("/chat?new=55&seed=55", { replace: true });
  });

  it("wires the mutation-free escape into both full-screen onboarding views", () => {
    const app = source("../../../App.tsx");
    const page = source("../index.tsx");
    const wizard = source("../wizard.tsx");

    expect(app).toContain("sessionStorage.getItem(AGENT_ONBOARDING_ROUTED_KEY)");
    expect(page.match(/onFinishLater=\{finishOnboardingLater\}/g)).toHaveLength(2);
    expect(wizard.match(/onClick=\{onFinishLater\}/g)).toHaveLength(2);
    expect(wizard).toMatch(/>\s*Continue to Chat\s*</);
    expect(wizard).toMatch(/>\s*Finish later\s*</);
    expect(wizard).not.toContain("~/.elevate/.env</code>");
    expect(wizard).not.toContain("This deletes the saved value from ~/.elevate/.env");
    expect(wizard).toContain("Saves to your current Elevate profile.");
    expect(wizard).toContain("Settings &gt; API keys");
  });
});
