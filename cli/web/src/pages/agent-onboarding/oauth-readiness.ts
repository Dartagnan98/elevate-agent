import type {
  AgentSetupItemUpdate,
  OAuthProvider,
  OAuthProviderStatus,
} from "@/lib/api-types";

const PRIMARY_OAUTH_RUNTIME_PROVIDER: Record<string, string> = {
  openai: "openai-codex",
  qwen: "qwen-oauth",
  xai: "xai-oauth",
  gemini: "google-gemini-cli",
  minimax: "minimax-oauth",
};

const PRIMARY_DIRECT_RUNTIME_PROVIDER: Record<string, string> = {
  qwen: "alibaba",
  azure_openai: "azure-foundry",
};

const PRIMARY_DIRECT_ENV: Record<string, string> = {
  anthropic: "ANTHROPIC_API_KEY",
  openai: "OPENAI_API_KEY",
  openrouter: "OPENROUTER_API_KEY",
  gemini: "GEMINI_API_KEY",
  xai: "XAI_API_KEY",
  minimax: "MINIMAX_API_KEY",
  deepseek: "DEEPSEEK_API_KEY",
  zai: "GLM_API_KEY",
  "kimi-coding": "KIMI_API_KEY",
  nvidia: "NVIDIA_API_KEY",
  huggingface: "HF_TOKEN",
  "ollama-cloud": "OLLAMA_API_KEY",
  qwen: "DASHSCOPE_API_KEY",
  azure_openai: "AZURE_FOUNDRY_API_KEY",
};

const PRIMARY_RUNTIME_WIZARD_PROVIDER: Record<string, string> = Object.fromEntries(
  [...Object.entries(PRIMARY_OAUTH_RUNTIME_PROVIDER), ...Object.entries(PRIMARY_DIRECT_RUNTIME_PROVIDER)]
    .map(([wizard, runtime]) => [runtime, wizard]),
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
  return PRIMARY_RUNTIME_WIZARD_PROVIDER[runtime] ?? runtime;
}

export function primaryProviderUsesEnvKey(
  selectedProvider: string,
  envKeys: ReadonlySet<string>,
): boolean {
  const provider = selectedProvider.trim();
  const envKey = PRIMARY_DIRECT_ENV[provider];
  if (provider === "azure_openai") {
    return Boolean(envKey && envKeys.has(envKey) && envKeys.has("AZURE_FOUNDRY_BASE_URL"));
  }
  return Boolean(envKey && envKeys.has(envKey));
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
  if (hasDirectSecret) return PRIMARY_DIRECT_RUNTIME_PROVIDER[selected] ?? selected;
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

export function buildPrimaryModelItemUpdate({
  selectedProvider,
  selectedModel,
  apiKey,
  secretPresent,
  oauthProviders,
  existingPrimary,
}: {
  selectedProvider: string;
  selectedModel: string;
  apiKey: string;
  secretPresent: boolean;
  oauthProviders: OAuthProvider[] | null;
  existingPrimary?: ExistingPrimarySetup;
}): AgentSetupItemUpdate {
  const hasSecret = Boolean(apiKey.trim()) || secretPresent;
  const ready = isPrimaryModelReady({
    selectedProvider,
    selectedModel,
    hasSecret,
    oauthProviders,
    existingPrimary,
  });
  const existingValue = (existingPrimary?.value ?? {}) as Record<string, unknown>;
  const runtimeProvider = resolveConfiguredPrimaryRuntimeProvider({
    selectedProvider,
    hasDirectSecret: hasSecret,
    providers: oauthProviders,
    existingRuntimeProvider: String(existingValue.runtimeProvider ?? ""),
  }) || null;
  return {
    key: "model_primary",
    status: ready ? "configured" : "missing",
    provider: selectedProvider.trim() || null,
    value: {
      model: selectedModel.trim(),
      runtimeProvider,
      apiKey,
      usesEnvSecret: !apiKey.trim() && secretPresent,
    },
  };
}
