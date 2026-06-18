import type { AdminDeal } from "@/lib/api-types";
import type { Deal, BuyerDeal } from "./admin-data";

const LISTING_STAGE_TO_PHASE: Record<number, string> = {
  0: "pre-cma",
  1: "cma",
  2: "intake",
  3: "skyslope",
  4: "go",
  5: "live",
  6: "offer",
  7: "conditions",
  8: "closed",
  9: "closed",
  10: "closed",
};

const LISTING_STAGE_BADGE: Record<number, string> = {
  0: "Pre-CMA",
  1: "CMA / Evaluation",
  2: "Listing Intake",
  3: "SkySlope & Matrix Prep",
  4: "Marketing Go",
  5: "Listing Live / Marketing",
  6: "Accepted Offer",
  7: "Condition Removal",
  8: "Closed",
  9: "Closed",
  10: "Closed",
};

const BUYER_STAGE_TO_PHASE: Record<number, string> = {
  0: "offer",
  1: "accepted",
  2: "conditions",
  3: "removed",
  4: "removed",
  5: "removed",
  6: "removed",
  7: "removed",
  8: "removed",
  9: "removed",
  10: "removed",
};

const BUYER_STAGE_BADGE: Record<number, string> = {
  0: "Offer Prep",
  1: "Accepted",
  2: "Condition Removal",
  3: "Subjects Off",
  4: "Subjects Off",
  5: "Subjects Off",
  6: "Subjects Off",
  7: "Subjects Off",
  8: "Subjects Off",
  9: "Subjects Off",
  10: "Subjects Off",
};

const LISTING_STAGE_NEXT: Record<number, string> = {
  0: "Pre-CMA Google Form filled",
  1: "CMA PDF complete",
  2: "Listing docs ready",
  3: "SkySlope/Matrix prep complete",
  4: "Marketing Go package ready",
  5: "Just listed blast sent",
  6: "Accepted-offer dates verified",
  7: "Condition removal / waiver sent",
  8: "File closed + nurture queued",
  9: "File closed + nurture queued",
  10: "File closed + nurture queued",
};

const BUYER_STAGE_NEXT: Record<number, string> = {
  0: "Offer package ready",
  1: "Accepted-offer checked",
  2: "Conditions tracked / removal pending",
  3: "File archive / nurture",
  4: "File archive / nurture",
  5: "File archive / nurture",
  6: "File archive / nurture",
  7: "File archive / nurture",
  8: "File archive / nurture",
  9: "File archive / nurture",
  10: "File archive / nurture",
};

function shortAddr(addr: string | null, fallback: string): string {
  const a = (addr || "").trim();
  if (!a) return fallback;
  return a.length > 44 ? a.slice(0, 42) + "…" : a;
}

function formatPrice(n: number | null | undefined): string | undefined {
  if (n == null) return undefined;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1000)}K`;
  return `$${n}`;
}

function stringToggle(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed || undefined;
}

function top25Note(d: AdminDeal): string | undefined {
  return (
    stringToggle(d.extraToggles?.top25Note) ??
    stringToggle(d.extraToggles?.lookingFor) ??
    stringToggle(d.extraToggles?.buyerCriteria) ??
    stringToggle(d.extraToggles?.profileCriteriaSummary)
  );
}

function clampStage(n: number): number {
  if (n < 0) return 0;
  if (n > 10) return 10;
  return Math.floor(n);
}

export function adminDealToDeal(d: AdminDeal): Deal {
  const stage = clampStage(d.currentStage ?? 0);
  const phase = LISTING_STAGE_TO_PHASE[stage] ?? "pre-cma";
  const badge = LISTING_STAGE_BADGE[stage] ?? "Pre-CMA";
  const next = LISTING_STAGE_NEXT[stage] ?? "—";
  const addr = shortAddr(d.listingAddress, d.title || "Untitled deal");
  const line2 = (d.listingAddress || d.title || "").trim() || (d.province ? `${d.province} deal` : "—");
  const price = formatPrice(d.listPrice);
  const pinned = d.extraToggles?.pinnedTop25 === true || d.extraToggles?.top25 === true;
  const note = top25Note(d);
  return {
    id: d.id,
    stage,
    phase,
    addr,
    line2,
    badge,
    next,
    price,
    mls: d.mlsNumber ?? undefined,
    primary: pinned,
    top25Note: note,
    progress: d.progress ?? d.scorecard?.progress ?? undefined,
    blocked: d.scorecard?.blocked ?? undefined,
    canAdvance: d.scorecard?.canAdvance ?? undefined,
    missingCount: d.scorecard?.missingCount ?? undefined,
    activeRunCount: d.scorecard?.activeRunCount ?? undefined,
    runningRunCount: d.scorecard?.runningRunCount ?? undefined,
    waitingHumanCount: d.scorecard?.waitingHumanCount ?? undefined,
    activeRunLabel: d.scorecard?.activeRunLabel ?? undefined,
    activeRunStatus: d.scorecard?.activeRunStatus ?? undefined,
  };
}

export function adminDealToBuyerDeal(d: AdminDeal): BuyerDeal {
  const stage = clampStage(d.currentStage ?? 0);
  const phase = BUYER_STAGE_TO_PHASE[stage] ?? "offer";
  const badge = BUYER_STAGE_BADGE[stage] ?? "Offer Prep";
  const next = BUYER_STAGE_NEXT[stage] ?? "—";
  const title = d.title || "Buyer";
  const note = top25Note(d);
  return {
    id: d.id,
    stage,
    side: "buyer",
    phase,
    addr: `${title} — buyer track`,
    line2: note ? `Looking: ${note}` : d.listingAddress || (d.province ? `Looking: ${d.province}` : "—"),
    badge,
    progress: d.progress ?? d.scorecard?.progress ?? undefined,
    blocked: d.scorecard?.blocked ?? undefined,
    canAdvance: d.scorecard?.canAdvance ?? undefined,
    missingCount: d.scorecard?.missingCount ?? undefined,
    activeRunCount: d.scorecard?.activeRunCount ?? undefined,
    runningRunCount: d.scorecard?.runningRunCount ?? undefined,
    waitingHumanCount: d.scorecard?.waitingHumanCount ?? undefined,
    activeRunLabel: d.scorecard?.activeRunLabel ?? undefined,
    activeRunStatus: d.scorecard?.activeRunStatus ?? undefined,
    next,
    primary: d.extraToggles?.pinnedTop25 === true || d.extraToggles?.top25 === true,
    top25Note: note,
  };
}
