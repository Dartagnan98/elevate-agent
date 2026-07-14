import type { StatusResponse } from "@/lib/api";

export type MemoryPolicyState = "loading" | "unavailable" | "beta" | "stable";

export function isRealtorBetaStatus(status: StatusResponse | null): boolean {
  return status?.beta_runtime?.releaseChannel === "beta";
}

export function resolveMemoryPolicyState(
  status: StatusResponse | null | undefined,
): MemoryPolicyState {
  if (status === undefined) return "loading";
  if (status === null) return "unavailable";
  return isRealtorBetaStatus(status) ? "beta" : "stable";
}
