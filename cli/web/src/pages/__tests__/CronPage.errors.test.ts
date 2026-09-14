import { describe, expect, it } from "vitest";

import { cronAttentionErrorMessage, cronLoadErrorMessage } from "../CronPage";

describe("CronPage error messages", () => {
  it("surfaces real load failures", () => {
    expect(cronLoadErrorMessage(new Error("cron down"))).toBe(
      "Failed to load cron jobs: cron down",
    );
  });

  it("surfaces attention failures", () => {
    expect(cronAttentionErrorMessage(new Error("attention down"))).toBe(
      "Cron attention unavailable: attention down",
    );
  });
});
