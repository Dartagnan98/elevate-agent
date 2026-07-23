import type { LeadsDraft, LeadsProfile } from "../leads-data";
import { matchesLeadsSourceFilter } from "./action-queue-helpers";

export type CrmTemperature = "all" | "hot" | "warm" | "lukewarm" | "cool" | "soi" | "nurture";

export const CRM_TEMPERATURE_LABELS: Record<Exclude<CrmTemperature, "all">, string> = {
  hot: "Hot",
  warm: "Warm",
  lukewarm: "Lukewarm",
  cool: "Cool",
  soi: "SOI",
  nurture: "Nurture",
};

export interface CrmProfileFilters {
  sourceFilter: string;
  pipelineFilter: string;
  temperatureFilter: CrmTemperature;
  tagFilters: string[];
  /** Configured list key, or "all" (migration 0038 named lead lists). */
  listFilter?: string;
  searchQuery: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const SOI_STATUSES = new Set(["closed", "closed seller", "closed buyer"]);

/**
 * Follow-up segment for a profile — the operator's own cadence system:
 * Hot 0–30d / Warm 30–90d / Lukewarm 90–180d / Cool 180–365d / Nurture 365d+,
 * with SOI (sphere of influence) for closed/past clients regardless of recency.
 * Falls back to the heat score when there's no activity timestamp.
 */
export function crmTemperatureForProfile(
  profile: Pick<LeadsProfile, "heat"> & Partial<Pick<LeadsProfile, "latestAt" | "status" | "tags">>,
): Exclude<CrmTemperature, "all"> {
  const status = (profile.status || "").trim().toLowerCase();
  const tags = (profile.tags || []).map((tag) => tag.trim().toLowerCase());
  if (SOI_STATUSES.has(status) || tags.includes("past client") || tags.includes("soi")) {
    return "soi";
  }
  const latest = profile.latestAt ? Date.parse(profile.latestAt) : NaN;
  if (Number.isFinite(latest)) {
    const days = Math.max(0, (Date.now() - latest) / DAY_MS);
    if (days <= 30) return "hot";
    if (days <= 90) return "warm";
    if (days <= 180) return "lukewarm";
    if (days <= 365) return "cool";
    return "nurture";
  }
  if (profile.heat >= 80) return "hot";
  if (profile.heat >= 50) return "warm";
  return "cool";
}

export function matchesCrmProfile(profile: LeadsProfile, filters: CrmProfileFilters): boolean {
  if (!matchesLeadsSourceFilter(profile, filters.sourceFilter)) return false;
  if (filters.pipelineFilter !== "all" && profile.status.toLowerCase() !== filters.pipelineFilter.toLowerCase()) {
    return false;
  }
  if (filters.temperatureFilter !== "all" && crmTemperatureForProfile(profile) !== filters.temperatureFilter) {
    return false;
  }
  const profileTags = new Set(profile.tags.map((tag) => tag.trim().toLowerCase()));
  if (filters.tagFilters.some((tag) => !profileTags.has(tag.trim().toLowerCase()))) return false;
  const listFilter = (filters.listFilter || "all").trim();
  if (listFilter !== "all" && !(profile.lists || []).includes(listFilter)) return false;

  const query = filters.searchQuery.trim().toLowerCase();
  if (!query) return true;
  return [profile.name, profile.email, profile.phone]
    .some((value) => value.toLowerCase().includes(query));
}

export function draftMatchesProfile(draft: LeadsDraft, profile: LeadsProfile): boolean {
  const draftHasThreadIdentity = Boolean(draft.sourceId || draft.threadId);
  const profileHasThreadIdentity = Boolean(profile.sourceId || profile.threadId);
  if (draftHasThreadIdentity || profileHasThreadIdentity) {
    return Boolean(
      draft.threadId
      && profile.threadId
      && draft.threadId === profile.threadId
      && draft.sourceId
      && profile.sourceId
      && draft.sourceId === profile.sourceId,
    );
  }
  return Boolean(draft.contactId && profile.contactIds?.includes(draft.contactId));
}
