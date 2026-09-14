import { describe, expect, it } from "vitest";

import { flagsForPath } from "../use-hub-data";

describe("hub data route flags", () => {
  it("loads cron workflow data for direct social media visits", () => {
    expect(flagsForPath("/social-media").includeWorkflowData).toBe(true);
  });
});
