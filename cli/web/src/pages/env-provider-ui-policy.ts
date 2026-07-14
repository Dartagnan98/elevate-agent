import type { StatusResponse } from "@/lib/api";
import { resolveMemoryPolicyState } from "@/lib/beta-runtime";

export interface EnvProviderUiPolicy {
  state: "loading" | "unavailable" | "beta" | "stable";
  envCacheKey: "envvars-policy-pending" | "realtor-beta-envvars" | "agent-hub-envvars";
  showCredentialControls: boolean;
  showGenericProviderControls: boolean;
  realtorBeta: boolean;
}

/**
 * Provider controls fail closed until the server confirms the active release
 * policy. EnvPage uses this view model for every render branch so a loading or
 * failed status request cannot expose Stable-only provider configuration.
 */
export function resolveEnvProviderUiPolicy(
  status: StatusResponse | null | undefined,
): EnvProviderUiPolicy {
  const state = resolveMemoryPolicyState(status);
  return {
    state,
    envCacheKey:
      state === "beta"
        ? "realtor-beta-envvars"
        : state === "stable"
          ? "agent-hub-envvars"
          : "envvars-policy-pending",
    showCredentialControls: state === "beta" || state === "stable",
    showGenericProviderControls: state === "stable",
    realtorBeta: state === "beta",
  };
}
