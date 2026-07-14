import { describe, expect, it } from "vitest";

import { flagsForPath } from "../use-hub-data";

describe("hub data route flags", () => {
  it("loads cron workflow data for direct social media visits", () => {
    expect(flagsForPath("/social-media").includeWorkflowData).toBe(true);
  });

  it("loads the Leads source inbox without waiting for unrelated hub requests", () => {
    const flags = flagsForPath("/leads");

    expect(flags.includeSourceInbox).toBe(true);
    expect(flags.includeWorkflowData).toBe(false);
    expect(flags.includeStatus).toBe(false);
    expect(flags.includeAgentHub).toBe(false);
    expect(flags.includeAdminTaskData).toBe(false);
  });
});
