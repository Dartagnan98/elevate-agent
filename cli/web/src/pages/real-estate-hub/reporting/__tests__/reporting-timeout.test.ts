import { describe, expect, it } from "vitest";

import { withReportingTimeout } from "../use-reporting-data";

describe("reporting request deadline", () => {
  it("turns a hung source into a bounded failure", async () => {
    await expect(withReportingTimeout(
      new Promise<never>(() => undefined),
      "Lead coverage",
      15,
    )).rejects.toThrow("Lead coverage timed out");
  });

  it("preserves a source result that settles before the deadline", async () => {
    await expect(withReportingTimeout(Promise.resolve("ready"), "Closed deals", 100)).resolves.toBe("ready");
  });
});
