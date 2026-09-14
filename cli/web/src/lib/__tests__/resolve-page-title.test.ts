import { describe, expect, it } from "vitest";

import { en } from "../../i18n/en";
import { resolvePageTitle } from "../resolve-page-title";

describe("resolvePageTitle", () => {
  it("labels mounted dashboard routes with their visible page names", () => {
    const expected: Record<string, string> = {
      "/today": "Today",
      "/leads": "Leads",
      "/admin": "Admin",
      "/social-media": "Social Media",
      "/cron": "Automations",
      "/overview": "Overview",
      "/hub": "Agent Hub",
      "/experiments": "Experiments",
      "/tasks": "Tasks",
      "/approvals": "Approvals",
      "/comms": "Comms",
      "/activity": "Activity",
      "/skills": "Skills",
      "/memory": "Memory graph",
      "/docs": "Documentation",
    };

    for (const [path, title] of Object.entries(expected)) {
      expect(resolvePageTitle(path, en, [])).toBe(title);
    }
  });

  it("still resolves plugin tabs from the provided plugin metadata", () => {
    expect(resolvePageTitle("/kanban", en, [{ path: "/kanban", label: "Kanban" }])).toBe(
      "Kanban",
    );
  });
});
