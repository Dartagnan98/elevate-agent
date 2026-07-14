import { describe, expect, it } from "vitest";

import type { StatusResponse } from "@/lib/api";
import { resolveEnvProviderUiPolicy } from "@/pages/env-provider-ui-policy";

function statusFor(channel: "beta" | "stable"): StatusResponse {
  const base = {
    active_sessions: 0,
    config_path: "/profile/config.yaml",
    config_version: 1,
    env_path: "/profile/.env",
    gateway_exit_reason: null,
    gateway_health_url: null,
    gateway_pid: null,
    gateway_platforms: {},
    gateway_running: false,
    gateway_state: null,
    gateway_updated_at: null,
    project_root: "/app",
    elevate_home: "/profile",
    latest_config_version: 1,
    release_date: "2026-07-14",
    version: "1.2.68",
  } satisfies Omit<StatusResponse, "beta_runtime">;

  if (channel === "stable") return base;
  return {
    ...base,
    beta_runtime: {
      releaseChannel: "beta",
      elevateHome: "/profile",
      providerPolicyVersion: "realtor-beta-v1",
      allowedModelsVersion: "realtor-beta-models-v1",
      allowedProvider: "openai-codex",
      configuredProvider: "openai-codex",
      configuredModel: "gpt-5-codex",
      authReady: true,
      authReason: null,
      runtimeReady: true,
      blockedReason: null,
    },
  };
}

describe("EnvPage provider policy", () => {
  it("keeps every credential and provider control closed before runtime truth arrives", () => {
    expect(resolveEnvProviderUiPolicy(undefined)).toEqual({
      state: "loading",
      envCacheKey: "envvars-policy-pending",
      showCredentialControls: false,
      showGenericProviderControls: false,
      realtorBeta: false,
    });

    expect(resolveEnvProviderUiPolicy(null)).toEqual({
      state: "unavailable",
      envCacheKey: "envvars-policy-pending",
      showCredentialControls: false,
      showGenericProviderControls: false,
      realtorBeta: false,
    });
  });

  it("keeps Beta credentials available while removing Stable-only provider controls", () => {
    expect(resolveEnvProviderUiPolicy(statusFor("beta"))).toEqual({
      state: "beta",
      envCacheKey: "realtor-beta-envvars",
      showCredentialControls: true,
      showGenericProviderControls: false,
      realtorBeta: true,
    });
  });

  it("preserves the existing provider controls for a verified Stable runtime", () => {
    expect(resolveEnvProviderUiPolicy(statusFor("stable"))).toEqual({
      state: "stable",
      envCacheKey: "agent-hub-envvars",
      showCredentialControls: true,
      showGenericProviderControls: true,
      realtorBeta: false,
    });
  });
});
