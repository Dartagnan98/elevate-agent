import type { AdminDeal } from "@/lib/api-types";
import type { Deal, BuyerDeal } from "./admin-data";

const LISTING_STAGE_TO_PHASE: Record<number, string> = {
  0: "pre-cma",
  1: "cma",
  2: "intake",
  3: "skyslope",
  4: "go",
  5: "live",
  6: "live",
  7: "offer",
  8: "conditions",
  9: "closing",
  10: "closed",
};

const LISTING_STAGE_BADGE: Record<number, string> = {
  0: "Pre-CMA",
  1: "CMA / Evaluation",
  2: "Listing Intake",
  3: "SkySlope & Matrix Prep",
  4: "Marketing Go",
  5: "Listing Live / Marketing",
  6: "Listing Live / Marketing",
  7: "Accepted Offer",
  8: "Condition Removal",
  9: "Closing",
  10: "Closed",
};

const BUYER_STAGE_TO_PHASE: Record<number, string> = {
  0: "intake",
  1: "search",
  2: "tours",
  3: "followup",
  4: "offer",
  5: "accepted",
  6: "conditions",
  7: "removed",
  8: "closing",
  9: "possession",
  10: "buyer-closed",
};

const BUYER_STAGE_BADGE: Record<number, string> = {
  0: "Intake",
  1: "Search Setup",
  2: "Tours",
  3: "Follow-Up",
  4: "Offer Prep",
  5: "Accepted",
  6: "Conditions",
  7: "Conditions Removed",
  8: "Closing",
  9: "Possession",
  10: "Closed",
};

const LISTING_STAGE_NEXT: Record<number, string> = {
  0: "Pre-CMA Google Form filled",
  1: "CMA PDF complete",
  2: "Listing docs ready",
  3: "SkySlope/Matrix prep complete",
  4: "Marketing Go package ready",
  5: "Just listed blast sent",
  6: "Flodesk mailout sent",
  7: "Accepted-offer dates verified",
  8: "Condition removal / waiver sent",
  9: "Closing package complete",
  10: "File closed + nurture queued",
};

const BUYER_STAGE_NEXT: Record<number, string> = {
  0: "Profile + budget conversation",
  1: "MLS criteria saved",
  2: "Showing notes complete",
  3: "Follow-up complete",
  4: "Offer package ready",
  5: "Accepted-offer checked",
  6: "Conditions tracked",
  7: "Conditions removed",
  8: "Closing checklist complete",
  9: "Possession follow-up queued",
  10: "File archived",
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
    phase,
    addr,
    line2,
    badge,
    next,
    price,
    mls: d.mlsNumber ?? undefined,
    primary: pinned,
    top25Note: note,
  };
}

export function adminDealToBuyerDeal(d: AdminDeal): BuyerDeal {
  const stage = clampStage(d.currentStage ?? 0);
  const phase = BUYER_STAGE_TO_PHASE[stage] ?? "intake";
  const badge = BUYER_STAGE_BADGE[stage] ?? "Intake";
  const next = BUYER_STAGE_NEXT[stage] ?? "—";
  const title = d.title || "Buyer";
  const note = top25Note(d);
  return {
    id: d.id,
    side: "buyer",
    phase,
    addr: `${title} — buyer track`,
    line2: note ? `Looking: ${note}` : d.listingAddress || (d.province ? `Looking: ${d.province}` : "—"),
    badge,
    progress: "0/3",
    next,
    primary: d.extraToggles?.pinnedTop25 === true || d.extraToggles?.top25 === true,
    top25Note: note,
  };
}
