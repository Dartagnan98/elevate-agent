import type { OAuthProvider } from "@/lib/api-types";

export const REALTOR_BETA_OAUTH_PROVIDER_ID = "openai-codex";
export const REALTOR_BETA_PRIMARY_PROVIDER = "openai-codex";
export const REALTOR_BETA_DEFAULT_MODEL = "gpt-5.5";

const REALTOR_BETA_ALLOWED_MODELS = new Set([
  REALTOR_BETA_DEFAULT_MODEL,
  "gpt-5.4-mini",
  "gpt-5.4",
  "gpt-5.3-codex",
  "gpt-5.3-codex-spark",
  "gpt-5.2-codex",
  "gpt-5.1-codex-max",
  "gpt-5.1-codex-mini",
]);

type PrimaryProviderDraft = {
  primaryProvider: string;
  primaryModel: string;
  primaryApiKey: string;
  primarySecretPresent: boolean;
  primarySecretPreview: string;
};

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

/**
 * Keep the browser draft identical to the server's exact-Beta transport.
 *
 * The Beta UI deliberately offers no provider, model, or API-key picker. A
 * stale snapshot therefore cannot smuggle an older selection back into a save.
 */
export function canonicalizePrimaryDraftForOnboarding<
  T extends PrimaryProviderDraft,
>(draft: T, realtorBeta: boolean): T {
  if (!realtorBeta) return draft;
  const selectedModel = draft.primaryModel.trim();
  return {
    ...draft,
    primaryProvider: REALTOR_BETA_PRIMARY_PROVIDER,
    primaryModel: REALTOR_BETA_ALLOWED_MODELS.has(selectedModel)
      ? selectedModel
      : REALTOR_BETA_DEFAULT_MODEL,
    primaryApiKey: "",
    primarySecretPresent: false,
    primarySecretPreview: "",
  };
}
