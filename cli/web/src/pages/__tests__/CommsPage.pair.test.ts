import { describe, expect, it } from "vitest";

import { normalizeCommsPair } from "../CommsPage";

describe("normalizeCommsPair", () => {
  it("canonicalizes valid pairs", () => {
    expect(normalizeCommsPair(" executive-assistant -- Admin ")).toBe(
      "admin--executive-assistant",
    );
  });

  it("rejects malformed pairs", () => {
    expect(normalizeCommsPair("executive-assistant")).toBeNull();
    expect(normalizeCommsPair("")).toBeNull();
    expect(normalizeCommsPair(null)).toBeNull();
  });

  it("rejects self pairs before they hit the API", () => {
    expect(normalizeCommsPair("executive-assistant--executive-assistant")).toBeNull();
  });
});
