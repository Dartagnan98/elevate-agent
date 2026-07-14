import { describe, expect, it } from "vitest";
import type {
  AgentSetupItem,
  BetaRuntimeReceipt,
  OAuthProvider,
} from "@/lib/api-types";
import {
  buildPrimaryModelItemUpdate,
  isPrimaryModelReady,
} from "../oauth-readiness";
import {
  REALTOR_BETA_ALLOWED_MODELS_VERSION,
  REALTOR_BETA_OAUTH_PROVIDER_ID,
  REALTOR_BETA_PROVIDER_POLICY_VERSION,
  REALTOR_BETA_WIZARD_STEP_IDS,
  canonicalizePrimaryDraftForOnboarding,
  isOAuthProviderAllowedInOnboarding,
  oauthProviderRowsForOnboarding,
  refreshOAuthProvidersForOnboarding,
  resolveBetaPrimaryUiContract,
} from "../beta-provider-ui";

const BETA_MODEL = "gpt-5.5";

function provider(id: string, loggedIn = true): OAuthProvider {
  return {
    id,
    name: id,
    flow: "device_code",
    cli_command: `elevate auth add ${id}`,
    docs_url: "https://example.test",
    status: { logged_in: loggedIn },
  };
}

function betaRuntime(
  overrides: Partial<BetaRuntimeReceipt> = {},
): BetaRuntimeReceipt {
  return {
    releaseChannel: "beta",
    elevateHome: "/tmp/elevate-beta",
    providerPolicyVersion: REALTOR_BETA_PROVIDER_POLICY_VERSION,
    allowedModelsVersion: REALTOR_BETA_ALLOWED_MODELS_VERSION,
    allowedProvider: REALTOR_BETA_OAUTH_PROVIDER_ID,
    configuredProvider: REALTOR_BETA_OAUTH_PROVIDER_ID,
    configuredModel: BETA_MODEL,
    authReady: true,
    authReason: null,
    runtimeReady: true,
    blockedReason: null,
    ...overrides,
  };
}

function primaryItem(): AgentSetupItem {
  return {
    key: "model_primary",
    category: "model",
    label: "Primary model",
    description: null,
    required: true,
    status: "configured",
    provider: REALTOR_BETA_OAUTH_PROVIDER_ID,
    value: {
      model: BETA_MODEL,
      runtimeProvider: REALTOR_BETA_OAUTH_PROVIDER_ID,
      policyVersion: REALTOR_BETA_PROVIDER_POLICY_VERSION,
      allowedModelsVersion: REALTOR_BETA_ALLOWED_MODELS_VERSION,
    },
    notes: null,
    sortOrder: 1,
    updatedAt: null,
  };
}

function browserDraft() {
  return {
    primaryProvider: "anthropic",
    primaryModel: "claude-opus-4-7",
    primaryApiKey: "must-not-survive",
    primarySecretPresent: true,
    primarySecretPreview: "…live",
  };
}

function betaContract(primary = primaryItem()) {
  return resolveBetaPrimaryUiContract({
    runtime: betaRuntime(),
    setupProvider: primary.provider,
    setupValue: primary.value,
  });
}

describe("Realtor Beta onboarding provider UI", () => {
  it("uses the realtor-only five-step setup sequence", () => {
    expect(REALTOR_BETA_WIZARD_STEP_IDS).toEqual([
      "models",
      "memory",
      "inbound",
      "tools",
      "subagents",
    ]);
  });

  it("recovers from an initial provider failure and publishes Refresh state that unlocks Next", async () => {
    const primary = primaryItem();
    const contract = betaContract(primary);
    const draft = canonicalizePrimaryDraftForOnboarding(
      browserDraft(),
      true,
      contract,
    );
    let sharedProviders: OAuthProvider[] | null = null;
    const published: Array<OAuthProvider[] | null> = [];
    let attempts = 0;
    const refresh = () => refreshOAuthProvidersForOnboarding({
      realtorBeta: true,
      load: async () => {
        attempts += 1;
        if (attempts === 1) throw new Error("gateway restarting");
        return {
          providers: [
            provider("anthropic"),
            provider(REALTOR_BETA_OAUTH_PROVIDER_ID),
          ],
        };
      },
      publish: (next) => {
        sharedProviders = next;
        published.push(next);
      },
    });
    const ready = () => isPrimaryModelReady({
      selectedProvider: draft.primaryProvider,
      selectedModel: draft.primaryModel,
      hasSecret: false,
      oauthProviders: sharedProviders,
      existingPrimary: primary,
    });

    const failed = await refresh();
    expect(failed.error).toContain("press Refresh");
    expect(sharedProviders).toBeNull();
    expect(ready()).toBe(false);

    const recovered = await refresh();
    expect(recovered.error).toBeNull();
    expect(sharedProviders?.map((item) => item.id)).toEqual([
      REALTOR_BETA_OAUTH_PROVIDER_ID,
    ]);
    expect(ready()).toBe(true);
    expect(published.map((items) => items?.map((item) => item.id) ?? null))
      .toEqual([null, null, null, [REALTOR_BETA_OAUTH_PROVIDER_ID]]);
  });

  it("builds only the exact-Beta Codex row and permits only its supported actions", () => {
    const rows = oauthProviderRowsForOnboarding(
      [
        provider("anthropic", false),
        provider(REALTOR_BETA_OAUTH_PROVIDER_ID, false),
        provider("google-gemini-cli", false),
      ],
      true,
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      provider: { id: REALTOR_BETA_OAUTH_PROVIDER_ID },
      showDocs: false,
      showCopyCommand: false,
      canStartLogin: true,
      canDisconnect: false,
    });
    expect(isOAuthProviderAllowedInOnboarding("anthropic", true)).toBe(false);
    expect(isOAuthProviderAllowedInOnboarding("google-gemini-cli", true)).toBe(false);
  });

  it("serializes a stale browser draft to the backend-authored Codex provider and model", () => {
    const primary = primaryItem();
    const contract = betaContract(primary);
    const draft = canonicalizePrimaryDraftForOnboarding(
      browserDraft(),
      true,
      contract,
    );
    const primaryUpdate = buildPrimaryModelItemUpdate({
      selectedProvider: draft.primaryProvider,
      selectedModel: draft.primaryModel,
      apiKey: draft.primaryApiKey,
      secretPresent: draft.primarySecretPresent,
      oauthProviders: [provider(REALTOR_BETA_OAUTH_PROVIDER_ID)],
      existingPrimary: primary,
    });

    expect(primaryUpdate).toEqual({
      key: "model_primary",
      status: "configured",
      provider: REALTOR_BETA_OAUTH_PROVIDER_ID,
      value: {
        model: BETA_MODEL,
        runtimeProvider: REALTOR_BETA_OAUTH_PROVIDER_ID,
        apiKey: "",
        usesEnvSecret: false,
      },
    });
  });

  it("clears generic credentials, channels, and arbitrary agent routing before Beta saves", () => {
    const draft = canonicalizePrimaryDraftForOnboarding(
      {
        ...browserDraft(),
        imageProvider: "gemini",
        imageApiKey: "ambient-image",
        imageSecretPresent: true,
        composioApiKey: "ambient-composio",
        composioWorkspace: "default",
        telegramBotToken: "malformed",
        telegramChatId: "*",
        discordBotToken: "discord",
        discordChannelId: "all",
        whatsappProvider: "meta",
        whatsappToken: "whatsapp",
        slackWebhookUrl: "https://hooks.invalid",
        outboundDiscordEnabled: true,
        subagentsEnabled: true,
        subagentsPack: "agent_default",
        agentChannels: { ads: { discord: ["all"] } },
      },
      true,
      betaContract(),
    );

    expect(draft).toMatchObject({
      imageProvider: "",
      imageApiKey: "",
      imageSecretPresent: false,
      composioApiKey: "",
      composioWorkspace: "",
      telegramBotToken: "",
      telegramChatId: "",
      discordBotToken: "",
      discordChannelId: "",
      whatsappProvider: "",
      whatsappToken: "",
      slackWebhookUrl: "",
      outboundDiscordEnabled: false,
      subagentsEnabled: false,
      subagentsPack: "",
      agentChannels: {},
    });
  });

  it("fails closed with an actionable error when the runtime model policy is newer", () => {
    const primary = primaryItem();
    const contract = resolveBetaPrimaryUiContract({
      runtime: betaRuntime({ allowedModelsVersion: "2099-01-01-v2" }),
      setupProvider: primary.provider,
      setupValue: primary.value,
    });
    const draft = canonicalizePrimaryDraftForOnboarding(
      browserDraft(),
      true,
      contract,
    );

    expect(contract.valid).toBe(false);
    expect(contract.error).toContain("Update Elevation Beta");
    expect(draft.primaryProvider).toBe(REALTOR_BETA_OAUTH_PROVIDER_ID);
    expect(draft.primaryModel).toBe("");
  });

  it("leaves Stable rows, refresh semantics, and drafts unchanged", async () => {
    const returned = [provider("anthropic", false), provider("openai-codex")];
    const rows = oauthProviderRowsForOnboarding(returned, false);
    expect(rows.map((row) => row.provider)).toEqual(returned);
    expect(rows[0]).toMatchObject({
      showDocs: true,
      showCopyCommand: true,
      canStartLogin: true,
      canDisconnect: false,
    });

    const published: Array<OAuthProvider[] | null> = [];
    const failed = await refreshOAuthProvidersForOnboarding({
      realtorBeta: false,
      load: async () => {
        throw new Error("offline");
      },
      publish: (next) => published.push(next),
    });
    expect(failed.error).toContain("Failed to load providers");
    expect(published).toEqual([]);

    const stableDraft = {
      primaryProvider: "anthropic",
      primaryModel: "claude-opus-4-7",
      primaryApiKey: "secret",
      primarySecretPresent: true,
      primarySecretPreview: "…live",
    };
    expect(
      canonicalizePrimaryDraftForOnboarding(stableDraft, false, betaContract()),
    ).toBe(stableDraft);
  });
});
