import type { LeadsDraft, LeadsProfile } from "../leads-data";
import { matchesLeadsSourceFilter } from "./action-queue-helpers";

export type CrmTemperature = "all" | "hot" | "warm" | "cool";

export interface CrmProfileFilters {
  sourceFilter: string;
  pipelineFilter: string;
  temperatureFilter: CrmTemperature;
  tagFilters: string[];
  searchQuery: string;
}

export function crmTemperatureForProfile(profile: Pick<LeadsProfile, "heat">): Exclude<CrmTemperature, "all"> {
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
