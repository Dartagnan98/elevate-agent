import { describe, expect, it } from "vitest";

import { __adminBoardTestables } from "../components/admin-board";

const {
  DEAL_DRAG_MIME,
  dealDragId,
  phaseStageNumber,
  shouldDropDeal,
} = __adminBoardTestables;

type TestDeal = Parameters<typeof shouldDropDeal>[1];

function deal(overrides: Partial<NonNullable<TestDeal>>): NonNullable<TestDeal> {
  return {
    id: "deal",
    stage: 0,
    phase: "pre-cma",
    addr: "123 Main",
    line2: "123 Main",
    badge: "Pre-CMA",
    next: "next",
    ...overrides,
  };
}

describe("AdminBoard drag-and-drop rules", () => {
  it("parses pipeline stage labels into backend stage numbers", () => {
    expect(phaseStageNumber({ id: "cma", stage: "S1", name: "CMA", next: "next" })).toBe(1);
    expect(phaseStageNumber({ id: "closed", stage: "S10", name: "Closed", next: "next" })).toBe(10);
    expect(phaseStageNumber({ id: "bad", stage: "not-a-stage", name: "Bad", next: "next" })).toBeNull();
  });

  it("prefers the custom drag payload and falls back to text/plain", () => {
    const transfer = {
      getData: (kind: string) => (kind === DEAL_DRAG_MIME ? "deal-custom" : "deal-plain"),
    } as unknown as DataTransfer;
    expect(dealDragId(transfer, "fallback")).toBe("deal-custom");

    const plainTransfer = {
      getData: (kind: string) => (kind === "text/plain" ? "deal-plain" : ""),
    } as unknown as DataTransfer;
    expect(dealDragId(plainTransfer, "fallback")).toBe("deal-plain");

    const emptyTransfer = { getData: () => "" } as unknown as DataTransfer;
    expect(dealDragId(emptyTransfer, "fallback")).toBe("fallback");
  });

  it("only sends normal forward drops through the next clear phase gate", () => {
    const clearStageOne = deal({ id: "deal-1", stage: 1, canAdvance: true });
    expect(shouldDropDeal([], clearStageOne, 2)).toBe(true);
    expect(shouldDropDeal([], clearStageOne, 3)).toBe(false);
  });

  it("blocks same-column and blocked-gate forward drops but allows rewinds", () => {
    const blockedStageTwo = deal({ id: "deal-2", stage: 2, canAdvance: false });
    expect(shouldDropDeal([deal({ id: "deal-2" })], blockedStageTwo, 2)).toBe(false);
    expect(shouldDropDeal([], blockedStageTwo, 2)).toBe(false);
    expect(shouldDropDeal([], blockedStageTwo, 3)).toBe(false);
    expect(shouldDropDeal([], blockedStageTwo, 1)).toBe(true);
  });
});
