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

function daysBetween(a: string, b: string): number {
  const ms = new Date(b).getTime() - new Date(a).getTime();
  return Math.max(0, Math.round(ms / 86_400_000));
}

function startOfMonth(now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth(), 1);
}
function endOfMonth(now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth() + 1, 1);
}
function startOfYear(now: Date): Date {
  return new Date(now.getFullYear(), 0, 1);
}

export function computeAdminKpis(deals: AdminDeal[]): AdminKpi[] {
  const now = new Date();
  const monthStart = startOfMonth(now);
  const monthEnd = endOfMonth(now);
  const yearStart = startOfYear(now);

  const active = deals.filter(isActive);
  const activeListing = active.filter(d => d.side === "listing");
  const activeBuyer = active.filter(d => d.side === "buyer");

  // 1. Pipeline value = sum of listPrice on active deals
  const pipelineListing = activeListing.reduce((s, d) => s + (d.listPrice || 0), 0);
  const pipelineBuyer = activeBuyer.reduce((s, d) => s + (d.offerPrice || d.listPrice || 0), 0);
  const pipelineTotal = pipelineListing + pipelineBuyer;

  // 2. Closing this month = completionDate within current month, projected commission @ default 5%
  const closingThisMonth = deals.filter(d => {
    if (!d.completionDate) return false;
    const c = new Date(d.completionDate);
    return c >= monthStart && c < monthEnd;
  });
  const projectedRevenue = closingThisMonth.reduce((s, d) => {
    const price = d.offerPrice || d.listPrice || 0;
    const pct = (d.commissionPct ?? 2.5) / 100;
    return s + price * pct;
  }, 0);
  const firmCount = closingThisMonth.filter(d => !!d.subjectsRemovedAt).length;
  const conditionalCount = closingThisMonth.length - firmCount;

  // 3. Avg time to close (createdAt → completedAt) over closed deals
  const closedAll = deals.filter(d => !!d.completedAt);
  const avgDays = closedAll.length === 0
    ? 0
    : Math.round(
        closedAll.reduce((s, d) => s + daysBetween(d.createdAt, d.completedAt as string), 0) /
          closedAll.length,
      );

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

  // 6. Closed YTD
  const closedYtd = deals.filter(d => {
    if (!d.completedAt) return false;
    return new Date(d.completedAt) >= yearStart;
  });
  const closedYtdRevenue = closedYtd.reduce((s, d) => {
    const price = d.offerPrice || d.listPrice || 0;
    const pct = (d.commissionPct ?? 2.5) / 100;
    return s + price * pct;
  }, 0);

  // 7. Stalled deals: in same stage > 21 days and not closed
  const stalled = active.filter(d => {
    if (!d.stageEnteredAt) return false;
    return daysBetween(d.stageEnteredAt, now.toISOString()) >= 21;
  });

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
      label: "Closing this month",
      value: String(closingThisMonth.length),
      breakdown: projectedRevenue > 0 ? `${fmtMoney(projectedRevenue)} projected` : "—",
      delta: closingThisMonth.length > 0 ? `${firmCount} firm · ${conditionalCount} conditional` : undefined,
      deltaTone: "",
    },
    {
      label: "Avg time to close",
      value: avgDays > 0 ? `${avgDays}d` : "—",
      breakdown: `${closedAll.length} closed deals`,
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
      label: "Closed YTD",
      value: String(closedYtd.length),
      breakdown: closedYtdRevenue > 0 ? `${fmtMoney(closedYtdRevenue)} GCI` : "—",
      delta: undefined,
      deltaTone: "",
    },
    {
      label: "Stalled deals",
      value: String(stalled.length),
      breakdown: "≥ 21d in stage",
      delta: stalled.length > 0 ? "Needs attention" : "All moving",
      deltaTone: stalled.length > 0 ? "warn" : "up",
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
