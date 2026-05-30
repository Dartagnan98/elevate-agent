import type { AdminDeal } from "@/lib/api-types";

export interface AdminKpi {
  label: string;
  value: string;
  breakdown?: string;
  delta?: string;
  deltaTone?: "up" | "down" | "warn" | "";
}

function fmtMoney(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1_000)}K`;
  if (n > 0) return `$${n}`;
  return "$0";
}

function isActive(d: AdminDeal): boolean {
  const s = (d.status || "").toLowerCase();
  return s === "active" || s === "" || (s !== "closed" && s !== "archived");
}

function startOfYear(now: Date): Date {
  return new Date(now.getFullYear(), 0, 1);
}

function dealPrice(d: AdminDeal): number {
  return d.offerPrice || d.listPrice || 0;
}

function dealGci(d: AdminDeal): number {
  const pct = (d.commissionPct ?? 2.5) / 100;
  return dealPrice(d) * pct;
}

function closedDate(d: AdminDeal): string | null | undefined {
  return d.completedAt ?? d.closedAt;
}

function hasConditionsRemoved(d: AdminDeal): boolean {
  if (d.subjectsRemovedAt) return true;

  const stage = d.currentStage ?? 0;
  if (d.side === "buyer") return stage >= 3;

  return false;
}

export function computeAdminKpis(deals: AdminDeal[]): AdminKpi[] {
  const now = new Date();
  const yearStart = startOfYear(now);

  const active = deals.filter(isActive);
  const activeListing = active.filter(d => d.side === "listing");
  const activeBuyer = active.filter(d => d.side === "buyer");

  // 1. Pipeline value = sum of listPrice on active deals
  const pipelineListing = activeListing.reduce((s, d) => s + (d.listPrice || 0), 0);
  const pipelineBuyer = activeBuyer.reduce((s, d) => s + (d.offerPrice || d.listPrice || 0), 0);
  const pipelineTotal = pipelineListing + pipelineBuyer;

  // 2. GCI pending = active firm deals only. Conditional accepted offers stay out
  // until subjects/conditions are removed.
  const pendingClosing = active.filter(hasConditionsRemoved);
  const pendingGci = pendingClosing.reduce((s, d) => s + dealGci(d), 0);

  // 4. Active listings
  const listingCount = activeListing.length;
  const buyerCount = activeBuyer.length;

  // 5. In offer / conditions (listing stages 7-8, buyer stages 4-6)
  const inMotion = active.filter(d => {
    const s = d.currentStage ?? 0;
    if (d.side === "listing") return s === 7 || s === 8;
    return s >= 4 && s <= 6;
  });
  const inMotionListing = inMotion.filter(d => d.side === "listing").length;
  const inMotionBuyer = inMotion.filter(d => d.side === "buyer").length;

  // 6. Closed YTD financials
  const closedYtd = deals.filter(d => {
    const date = closedDate(d);
    if (!date) return false;
    return new Date(date) >= yearStart;
  });
  const closedYtdGci = closedYtd.reduce((s, d) => s + dealGci(d), 0);
  const closedYtdVolume = closedYtd.reduce((s, d) => s + dealPrice(d), 0);

  // 8. Upcoming key dates this week (offer / subject removal / completion / deposit)
  const weekFromNow = new Date(now.getTime() + 7 * 86_400_000);
  const upcomingDates = active.filter(d => {
    const candidates = [d.subjectRemovalDate, d.depositDueDate, d.completionDate, d.possessionDate].filter(Boolean);
    return candidates.some(s => {
      const dt = new Date(s as string);
      return dt >= now && dt <= weekFromNow;
    });
  });

  return [
    {
      label: "Pipeline value",
      value: fmtMoney(pipelineTotal),
      breakdown: `${listingCount} listing · ${buyerCount} buyer`,
      delta: pipelineListing > 0 ? `${fmtMoney(pipelineListing)} listing side` : undefined,
      deltaTone: "",
    },
    {
      label: "GCI pending",
      value: fmtMoney(pendingGci),
      breakdown: `${pendingClosing.length} firm pending closing${pendingClosing.length === 1 ? "" : "s"}`,
      delta: pendingClosing.length > 0 ? "conditions removed" : undefined,
      deltaTone: "",
    },
    {
      label: "GCI YTD",
      value: fmtMoney(closedYtdGci),
      breakdown: `${closedYtd.length} closed unit${closedYtd.length === 1 ? "" : "s"}`,
      delta: undefined,
      deltaTone: "",
    },
    {
      label: "Active deals",
      value: String(active.length),
      breakdown: `${listingCount} listing · ${buyerCount} buyer`,
      delta: undefined,
      deltaTone: "",
    },
    {
      label: "In offer / conditions",
      value: String(inMotion.length),
      breakdown: `${inMotionListing} listing · ${inMotionBuyer} buyer`,
      delta: inMotion.length > 0 ? "Hot stage" : undefined,
      deltaTone: inMotion.length > 0 ? "warn" : "",
    },
    {
      label: "Closed YTD units",
      value: String(closedYtd.length),
      breakdown: closedYtdGci > 0 ? `${fmtMoney(closedYtdGci)} GCI` : "—",
      delta: undefined,
      deltaTone: "",
    },
    {
      label: "Closed YTD volume",
      value: fmtMoney(closedYtdVolume),
      breakdown: `${closedYtd.length} closed unit${closedYtd.length === 1 ? "" : "s"}`,
      delta: undefined,
      deltaTone: "",
    },
    {
      label: "Key dates this week",
      value: String(upcomingDates.length),
      breakdown: "removal · close · possession",
      delta: undefined,
      deltaTone: "",
    },
  ];
}
