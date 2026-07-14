import fs from "node:fs";
import { describe, expect, it } from "vitest";
import type { OAuthProvider } from "@/lib/api-types";
import {
  hasUsablePrimaryOAuth,
  isPrimaryModelReady,
  isUsableSecretPresence,
  primaryProviderUsesEnvKey,
  resolveConfiguredPrimaryRuntimeProvider,
  resolvePrimaryRuntimeProvider,
  resolvePrimaryWizardProvider,
} from "../oauth-readiness";

function provider(
  status: OAuthProvider["status"],
  id = "anthropic",
): OAuthProvider {
  return {
    id,
    name: id,
    flow: "pkce",
    cli_command: `elevate auth add ${id}`,
    docs_url: "https://example.test",
    status,
  };
}

describe("agent onboarding OAuth readiness", () => {
  it("accepts a selected primary provider when its OAuth connection is usable", () => {
    expect(
      hasUsablePrimaryOAuth(
        "anthropic",
        [provider({ logged_in: true, expires_at: "2999-01-01T00:00:00Z" })],
      ),
    ).toBe(true);
  });

  it("accepts runtime-validated Claude Code credentials through the Anthropic provider", () => {
    expect(
      hasUsablePrimaryOAuth(
        "anthropic",
        [
          provider({
            logged_in: true,
            source: "claude_code",
            expires_at: "2999-01-01T00:00:00Z",
          }),
        ],
      ),
    ).toBe(true);
  });

  it("does not treat the display-only Claude Code row as a runtime provider", () => {
    expect(
      hasUsablePrimaryOAuth(
        "anthropic",
        [provider({ logged_in: true, expires_at: null }, "claude-code")],
      ),
    ).toBe(false);
  });

  it("rejects expired OAuth without a usable refresh path", () => {
    expect(
      hasUsablePrimaryOAuth(
        "anthropic",
        [
          provider({
            logged_in: true,
            expires_at: "2000-01-01T00:00:00Z",
            has_refresh_token: false,
          }),
        ],
      ),
    ).toBe(false);
  });

  it("accepts an expired access token when the runtime reports a refresh path", () => {
    expect(
      hasUsablePrimaryOAuth("gemini", [
        provider(
          {
            logged_in: true,
            expires_at: 1_700_000_000_000,
            has_refresh_token: true,
          },
          "google-gemini-cli",
        ),
      ]),
    ).toBe(true);
  });

  it("does not accept a logged-out provider even if refresh metadata remains", () => {
    expect(
      hasUsablePrimaryOAuth("anthropic", [
        provider({ logged_in: false, expires_at: null, has_refresh_token: true }),
      ]),
    ).toBe(false);
  });

  it.each([
    ["xai", "xai-oauth"],
    ["gemini", "google-gemini-cli"],
    ["minimax", "minimax-oauth"],
  ])("aligns grouped %s selection with the usable runtime provider %s", (selected, runtime) => {
    expect(
      resolvePrimaryRuntimeProvider(
        selected,
        [provider({ logged_in: true, expires_at: null }, runtime)],
      ),
    ).toBe(runtime);
    expect(resolvePrimaryRuntimeProvider(selected, [])).toBe(selected);
  });

  it.each([
    ["openai-codex", "openai"],
    ["qwen-oauth", "qwen"],
    ["xai-oauth", "xai"],
    ["google-gemini-cli", "gemini"],
    ["minimax-oauth", "minimax"],
    ["alibaba", "qwen"],
    ["azure-foundry", "azure_openai"],
    ["claude-code", "anthropic"],
  ])("maps runtime provider %s back to wizard option %s", (runtime, wizard) => {
    expect(resolvePrimaryWizardProvider(runtime)).toBe(wizard);
  });

  it("does not mistake a configured model name for credential presence", () => {
    expect(isUsableSecretPresence(true, "config")).toBe(false);
    expect(isUsableSecretPresence(true, "oauth")).toBe(false);
    expect(isUsableSecretPresence(true, "env")).toBe(true);
    expect(isUsableSecretPresence(true, "")).toBe(true);
  });

  it("uses the persisted runtime provider only while OAuth status is unknown", () => {
    expect(resolvePrimaryRuntimeProvider("xai", null, "xai-oauth")).toBe("xai-oauth");
    expect(resolvePrimaryRuntimeProvider("xai", [], "xai-oauth")).toBe("xai");
  });

  it("lets a direct OpenAI key override a live Codex OAuth connection", () => {
    expect(
      resolveConfiguredPrimaryRuntimeProvider({
        selectedProvider: "openai",
        hasDirectSecret: true,
        providers: [
          provider({ logged_in: true, expires_at: null }, "openai-codex"),
        ],
      }),
    ).toBe("openai");
  });

  it.each([
    ["qwen", "alibaba"],
    ["azure_openai", "azure-foundry"],
  ])("canonicalizes direct %s credentials to runtime provider %s", (selected, runtime) => {
    expect(
      resolveConfiguredPrimaryRuntimeProvider({
        selectedProvider: selected,
        hasDirectSecret: true,
        providers: [],
      }),
    ).toBe(runtime);
  });

  it("matches raw key state to the selected provider regardless of save order", () => {
    const envKeys = new Set([
      "GEMINI_API_KEY",
      "DASHSCOPE_API_KEY",
      "AZURE_FOUNDRY_API_KEY",
      "AZURE_FOUNDRY_BASE_URL",
    ]);

    expect(primaryProviderUsesEnvKey("gemini", envKeys)).toBe(true);
    expect(primaryProviderUsesEnvKey("qwen", envKeys)).toBe(true);
    expect(primaryProviderUsesEnvKey("azure_openai", envKeys)).toBe(true);
    expect(primaryProviderUsesEnvKey("deepseek", envKeys)).toBe(false);
    expect(
      primaryProviderUsesEnvKey("azure_openai", new Set(["AZURE_FOUNDRY_API_KEY"])),
    ).toBe(false);
  });

  it("preserves only the unchanged configured model while OAuth status is unavailable", () => {
    const existingPrimary = {
      status: "configured",
      provider: "anthropic",
      value: { model: "claude-sonnet-4-6", runtimeProvider: "anthropic" },
    } as const;
    const base = {
      selectedProvider: "anthropic",
      selectedModel: "claude-sonnet-4-6",
      hasSecret: false,
      existingPrimary,
    };

    expect(isPrimaryModelReady({ ...base, oauthProviders: null })).toBe(true);
    expect(
      isPrimaryModelReady({ ...base, selectedModel: "claude-opus-4-7", oauthProviders: null }),
    ).toBe(false);
    expect(isPrimaryModelReady({ ...base, oauthProviders: [] })).toBe(false);
  });

  it.each([
    ["openai-codex", "openai"],
    ["xai-oauth", "xai"],
  ])("preserves config-detected runtime provider %s through a grouped draft", (runtime, wizard) => {
    expect(resolvePrimaryWizardProvider(runtime)).toBe(wizard);
    expect(
      isPrimaryModelReady({
        selectedProvider: wizard,
        selectedModel: "test-model",
        hasSecret: false,
        oauthProviders: null,
        existingPrimary: {
          status: "configured",
          provider: runtime,
          value: { model: "test-model", runtimeProvider: runtime },
        },
      }),
    ).toBe(true);
  });

  it("uses the same live OAuth snapshot for validation and both save paths", () => {
    const serializer = fs.readFileSync(new URL("../index.tsx", import.meta.url), "utf8");
    const wizard = fs.readFileSync(new URL("../wizard.tsx", import.meta.url), "utf8");

    expect(serializer).toContain("runtimeProvider: primaryRuntimeProvider");
    expect(serializer).toContain("resolveConfiguredPrimaryRuntimeProvider({");
    expect(serializer).toContain("primaryProvider: resolvePrimaryWizardProvider(");
    expect(wizard).toContain("oauthProviders.filter(isOAuthProviderUsable)");
    expect(wizard).toContain("const primaryReady = isPrimaryModelReady({");
    expect(wizard).toContain("resolveConfiguredPrimaryRuntimeProvider({");
    expect(
      wizard.match(
        /buildItemUpdates\(\s*draftToSave,\s*oauthProviders,\s*primaryItem,\s*primaryDirectSecretPresent,\s*\)/g,
      ),
    ).toHaveLength(2);
    expect(wizard).toContain(
      "canonicalizePrimaryDraftForOnboarding(draft, realtorBeta)",
    );
    expect(wizard).toContain('setup.items.find((item) => item.key === "model_primary")');
    expect(wizard).not.toContain("setOauthProviders([])");
    expect(wizard).toContain("onEnvStateChange={handleApiKeyEnvStateChange}");
    expect(wizard).toContain("primaryProviderUsesEnvKey(draft.primaryProvider");
    expect(
      serializer.match(
        /buildItemUpdates\(\s*draftToSave,\s*oauthProviders,\s*primaryItem,?\s*\)/g,
      ),
    ).toHaveLength(2);
    expect(serializer).toContain(
      "canonicalizePrimaryDraftForOnboarding(draft, realtorBeta)",
    );
    expect(serializer).toContain("api.getOAuthProviders()");
  });
});
