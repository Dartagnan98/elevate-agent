import type { BetaRuntimeReceipt, OAuthProvider } from "@/lib/api-types";

export const REALTOR_BETA_OAUTH_PROVIDER_ID = "openai-codex";
export const REALTOR_BETA_PRIMARY_PROVIDER = "openai-codex";
export const REALTOR_BETA_PROVIDER_POLICY_VERSION = "realtor-beta-codex-v1";
export const REALTOR_BETA_ALLOWED_MODELS_VERSION = "2026-07-14-v1";

type PrimaryProviderDraft = {
  primaryProvider: string;
  primaryModel: string;
  primaryApiKey: string;
  primarySecretPresent: boolean;
  primarySecretPreview: string;
};

export type BetaPrimaryUiContract =
  | {
      valid: true;
      provider: typeof REALTOR_BETA_PRIMARY_PROVIDER;
      model: string;
      error: null;
    }
  | {
      valid: false;
      provider: typeof REALTOR_BETA_PRIMARY_PROVIDER;
      model: "";
      error: string;
    };

type BetaPrimaryContractInput = {
  runtime: BetaRuntimeReceipt | undefined;
  setupProvider: unknown;
  setupValue: unknown;
};

function invalidContract(error: string): BetaPrimaryUiContract {
  return {
    valid: false,
    provider: REALTOR_BETA_PRIMARY_PROVIDER,
    model: "",
    error,
  };
}

/**
 * Join the runtime receipt to the server-authored setup overlay.
 *
 * The browser does not carry its own model allowlist. The backend chooses the
 * model and versions that choice; a stale frontend/backend combination pauses
 * onboarding instead of guessing or silently substituting a model.
 */
export function resolveBetaPrimaryUiContract({
  runtime,
  setupProvider,
  setupValue,
}: BetaPrimaryContractInput): BetaPrimaryUiContract {
  if (!runtime) {
    return invalidContract(
      "Elevation could not verify the Realtor Beta model policy. Refresh the app before continuing.",
    );
  }
  if (
    runtime.allowedProvider !== REALTOR_BETA_PRIMARY_PROVIDER ||
    runtime.providerPolicyVersion !== REALTOR_BETA_PROVIDER_POLICY_VERSION
  ) {
    return invalidContract(
      "This onboarding screen does not match the installed Realtor Beta provider policy. Update Elevation Beta, then reopen onboarding.",
    );
  }
  if (runtime.allowedModelsVersion !== REALTOR_BETA_ALLOWED_MODELS_VERSION) {
    return invalidContract(
      `This onboarding screen supports model policy ${REALTOR_BETA_ALLOWED_MODELS_VERSION}, but the runtime reported ${runtime.allowedModelsVersion || "no version"}. Update Elevation Beta, then reopen onboarding.`,
    );
  }

  const value = setupValue && typeof setupValue === "object"
    ? setupValue as Record<string, unknown>
    : {};
  if (
    String(setupProvider ?? "").trim() !== runtime.allowedProvider ||
    String(value.runtimeProvider ?? "").trim() !== runtime.allowedProvider
  ) {
    return invalidContract(
      "Elevation could not verify the Codex setup for this Beta profile. Refresh onboarding before continuing.",
    );
  }
  if (
    String(value.policyVersion ?? "").trim() !== runtime.providerPolicyVersion ||
    String(value.allowedModelsVersion ?? "").trim() !== runtime.allowedModelsVersion
  ) {
    return invalidContract(
      "The Realtor Beta model setup is out of date. Refresh onboarding; if this continues, update Elevation Beta.",
    );
  }

  const model = String(value.model ?? "").trim();
  if (!model) {
    return invalidContract(
      "Elevation did not receive a supported Realtor Beta model. Refresh onboarding before continuing.",
    );
  }
  return {
    valid: true,
    provider: REALTOR_BETA_PRIMARY_PROVIDER,
    model,
    error: null,
  };
}

export function isOAuthProviderAllowedInOnboarding(
  providerId: string,
  realtorBeta: boolean,
): boolean {
  return !realtorBeta || providerId === REALTOR_BETA_OAUTH_PROVIDER_ID;
}

export function scopeOAuthProvidersForOnboarding(
  providers: OAuthProvider[],
  realtorBeta: boolean,
): OAuthProvider[] {
  if (!realtorBeta) return providers;
  return providers.filter((provider) =>
    isOAuthProviderAllowedInOnboarding(provider.id, true),
  );
}

export type OAuthProviderRow = {
  provider: OAuthProvider;
  showDocs: boolean;
  showCopyCommand: boolean;
  canStartLogin: boolean;
  canDisconnect: boolean;
};

export function oauthProviderRowsForOnboarding(
  providers: OAuthProvider[],
  realtorBeta: boolean,
): OAuthProviderRow[] {
  return scopeOAuthProvidersForOnboarding(providers, realtorBeta).map((provider) => ({
    provider,
    showDocs: Boolean(provider.docs_url) && !realtorBeta,
    showCopyCommand: !provider.status.logged_in && !realtorBeta,
    canStartLogin:
      provider.flow !== "external" &&
      isOAuthProviderAllowedInOnboarding(provider.id, realtorBeta),
    canDisconnect:
      provider.status.logged_in &&
      provider.flow !== "external" &&
      isOAuthProviderAllowedInOnboarding(provider.id, realtorBeta),
  }));
}

type ProviderRefreshArgs = {
  load: () => Promise<{ providers: OAuthProvider[] }>;
  realtorBeta: boolean;
  publish: (providers: OAuthProvider[] | null) => void;
};

export type ProviderRefreshResult = {
  providers: OAuthProvider[] | null;
  error: string | null;
};

/** Drive the same initial-load and manual-Refresh transition used by the card. */
export async function refreshOAuthProvidersForOnboarding({
  load,
  realtorBeta,
  publish,
}: ProviderRefreshArgs): Promise<ProviderRefreshResult> {
  if (realtorBeta) publish(null);
  try {
    const response = await load();
    const providers = scopeOAuthProvidersForOnboarding(
      response.providers,
      realtorBeta,
    );
    if (
      realtorBeta &&
      !providers.some((provider) => provider.id === REALTOR_BETA_OAUTH_PROVIDER_ID)
    ) {
      throw new Error("required Codex provider missing from the Beta response");
    }
    publish(providers);
    return { providers, error: null };
  } catch (error) {
    if (realtorBeta) publish(null);
    const detail = error instanceof Error && error.message
      ? ` (${error.message})`
      : "";
    return {
      providers: null,
      error: realtorBeta
        ? `Could not refresh OpenAI Codex sign-in${detail}. Check your connection, then press Refresh. If this continues, update Elevation Beta.`
        : `Failed to load providers: ${String(error)}`,
    };
  }
}

/**
 * Keep the browser draft identical to the server's exact-Beta transport.
 *
 * The Beta UI deliberately offers no provider, model, or API-key picker. A
 * stale snapshot therefore cannot smuggle an older selection back into a save.
 */
export function canonicalizePrimaryDraftForOnboarding<
  T extends PrimaryProviderDraft,
>(
  draft: T,
  realtorBeta: boolean,
  contract?: BetaPrimaryUiContract,
): T {
  if (!realtorBeta) return draft;
  return {
    ...draft,
    primaryProvider: REALTOR_BETA_PRIMARY_PROVIDER,
    primaryModel: contract?.valid ? contract.model : "",
    primaryApiKey: "",
    primarySecretPresent: false,
    primarySecretPreview: "",
  };
}
