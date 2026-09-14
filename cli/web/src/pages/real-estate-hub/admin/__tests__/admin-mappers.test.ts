import { describe, expect, it } from "vitest";

import type { AdminDeal } from "@/lib/api-types";
import { adminDealToBuyerDeal, adminDealToDeal } from "../admin-mappers";

function adminDeal(overrides: Partial<AdminDeal> = {}): AdminDeal {
  return {
    id: "deal-1",
    title: "Test deal",
    side: "listing",
    currentStage: 2,
    status: "active",
    province: "BC",
    primaryContactId: null,
    loftyContactId: null,
    listingAddress: "123 Main St",
    extraToggles: {},
    createdAt: "2026-06-18T00:00:00+00:00",
    updatedAt: "2026-06-18T00:00:00+00:00",
    stageEnteredAt: "2026-06-18T00:00:00+00:00",
    closedAt: null,
    signingAuthority: null,
    fintracFormType: null,
    listingTrack: null,
    propertySubtype: null,
    estateStatus: null,
    transactionType: null,
    listingType: null,
    pep: null,
    tenanted: null,
    poaSigning: null,
    corporate: null,
    hasSuite: null,
    multipleOffers: null,
    familyMember: null,
    dualRep: null,
    unrepresentedOtherSide: null,
    lockbox: null,
    delayedOffer: null,
    saleOfBuyersProperty: null,
    scorecard: {
      progress: "1/3",
      completedChecklist: 1,
      totalChecklist: 3,
      canAdvance: false,
      blocked: true,
      missingCount: 2,
      activeRunCount: 2,
      runningRunCount: 2,
      waitingHumanCount: 0,
      activeRunLabel: "Listing Intake: Collect MLC info",
      activeRunStatus: "running",
    },
    ...overrides,
  };
}

describe("admin deal mappers", () => {
  it("carries live action-run state onto listing cards", () => {
    const mapped = adminDealToDeal(adminDeal());

    expect(mapped.activeRunCount).toBe(2);
    expect(mapped.runningRunCount).toBe(2);
    expect(mapped.activeRunLabel).toBe("Listing Intake: Collect MLC info");
    expect(mapped.activeRunStatus).toBe("running");
  });

  it("carries live action-run state onto buyer cards", () => {
    const mapped = adminDealToBuyerDeal(adminDeal({ side: "buyer" }));

    expect(mapped.activeRunCount).toBe(2);
    expect(mapped.runningRunCount).toBe(2);
    expect(mapped.activeRunLabel).toBe("Listing Intake: Collect MLC info");
    expect(mapped.activeRunStatus).toBe("running");
  });
});
