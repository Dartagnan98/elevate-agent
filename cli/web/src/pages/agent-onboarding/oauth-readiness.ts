import type { OAuthProvider, OAuthProviderStatus } from "@/lib/api-types";

const PRIMARY_OAUTH_RUNTIME_PROVIDER: Record<string, string> = {
  openai: "openai-codex",
  qwen: "qwen-oauth",
  xai: "xai-oauth",
  gemini: "google-gemini-cli",
  minimax: "minimax-oauth",
};

const PRIMARY_OAUTH_WIZARD_PROVIDER: Record<string, string> = Object.fromEntries(
  Object.entries(PRIMARY_OAUTH_RUNTIME_PROVIDER).map(([wizard, runtime]) => [runtime, wizard]),
);

type ExistingPrimarySetup = {
  status: string;
  provider?: string | null;
  value?: unknown;
};

function expiryMs(value: OAuthProviderStatus["expires_at"]): number | null {
  if (value == null || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(numeric)) {
    return Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric;
  }
  const parsed = Date.parse(String(value));
  return Number.isNaN(parsed) ? null : parsed;
}

export function isOAuthProviderUsable(provider: OAuthProvider): boolean {
  const status = provider.status;
  if (!status.logged_in || status.error) return false;
  const expiresAt = expiryMs(status.expires_at);
  return expiresAt == null || expiresAt > Date.now() || Boolean(status.has_refresh_token);
}

export function resolvePrimaryWizardProvider(runtimeProvider: string): string {
  const runtime = runtimeProvider.trim();
  if (runtime === "claude-code") return "anthropic";
  return PRIMARY_OAUTH_WIZARD_PROVIDER[runtime] ?? runtime;
}

export function isUsableSecretPresence(present: boolean, source: string): boolean {
  return present && source !== "config" && source !== "oauth";
}

export function resolvePrimaryRuntimeProvider(
  selectedProvider: string,
  providers: OAuthProvider[] | null,
  existingRuntimeProvider = "",
): string {
  const selected = selectedProvider.trim();
  if (providers === null) return existingRuntimeProvider.trim() || selected;
  const oauthRuntime = PRIMARY_OAUTH_RUNTIME_PROVIDER[selected];
  if (
    oauthRuntime &&
    providers.some(
      (provider) => provider.id === oauthRuntime && isOAuthProviderUsable(provider),
    )
  ) {
    return oauthRuntime;
  }
  return selected;
}

export function resolveConfiguredPrimaryRuntimeProvider({
  selectedProvider,
  hasDirectSecret,
  providers,
  existingRuntimeProvider = "",
}: {
  selectedProvider: string;
  hasDirectSecret: boolean;
  providers: OAuthProvider[] | null;
  existingRuntimeProvider?: string;
}): string {
  const selected = selectedProvider.trim();
  if (hasDirectSecret) return selected;
  return resolvePrimaryRuntimeProvider(selected, providers, existingRuntimeProvider);
}

export function hasUsablePrimaryOAuth(
  selectedProvider: string,
  providers: OAuthProvider[],
): boolean {
  const runtimeProvider = resolvePrimaryRuntimeProvider(selectedProvider, providers);
  return providers.some(
    (provider) => provider.id === runtimeProvider && isOAuthProviderUsable(provider),
  );
}

export function isPrimaryModelReady({
  selectedProvider,
  selectedModel,
  hasSecret,
  oauthProviders,
  existingPrimary,
}: {
  selectedProvider: string;
  selectedModel: string;
  hasSecret: boolean;
  oauthProviders: OAuthProvider[] | null;
  existingPrimary?: ExistingPrimarySetup;
}): boolean {
  const provider = selectedProvider.trim();
  const model = selectedModel.trim();
  if (!provider || !model) return false;
  if (hasSecret) return true;
  if (oauthProviders !== null) {
    return hasUsablePrimaryOAuth(provider, oauthProviders);
  }
  if (
    existingPrimary?.status !== "configured" ||
    resolvePrimaryWizardProvider(existingPrimary.provider ?? "") !== provider
  ) {
    return false;
  }
  const value = (existingPrimary.value ?? {}) as Record<string, unknown>;
  return String(value.model ?? "").trim() === model;
}
