import fs from "node:fs";
import { describe, expect, it } from "vitest";
import type { OAuthProvider } from "@/lib/api-types";
import {
  REALTOR_BETA_DEFAULT_MODEL,
  REALTOR_BETA_OAUTH_PROVIDER_ID,
  canonicalizePrimaryDraftForOnboarding,
  isOAuthProviderAllowedInOnboarding,
  scopeOAuthProvidersForOnboarding,
} from "../beta-provider-ui";

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

function source(relative: string): string {
  return fs.readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("Realtor Beta onboarding provider UI", () => {
  it("never exposes or authorizes a returned non-Codex OAuth provider", () => {
    const returned = [
      provider("anthropic"),
      provider(REALTOR_BETA_OAUTH_PROVIDER_ID),
      provider("google-gemini-cli"),
    ];

    expect(scopeOAuthProvidersForOnboarding(returned, true).map((item) => item.id))
      .toEqual([REALTOR_BETA_OAUTH_PROVIDER_ID]);
    expect(isOAuthProviderAllowedInOnboarding("anthropic", true)).toBe(false);
    expect(isOAuthProviderAllowedInOnboarding("google-gemini-cli", true)).toBe(false);
    expect(
      isOAuthProviderAllowedInOnboarding(REALTOR_BETA_OAUTH_PROVIDER_ID, true),
    ).toBe(true);

    expect(scopeOAuthProvidersForOnboarding(returned, false)).toBe(returned);
    expect(isOAuthProviderAllowedInOnboarding("anthropic", false)).toBe(true);
  });

  it("repairs a stale provider, model, and direct key before an exact-Beta save", () => {
    const draft = canonicalizePrimaryDraftForOnboarding(
      {
        primaryProvider: "anthropic",
        primaryModel: "claude-opus-4-7",
        primaryApiKey: "must-not-survive",
        primarySecretPresent: true,
        primarySecretPreview: "…live",
        untouched: "preserved",
      },
      true,
    );

    expect(draft).toMatchObject({
      primaryProvider: REALTOR_BETA_OAUTH_PROVIDER_ID,
      primaryModel: REALTOR_BETA_DEFAULT_MODEL,
      primaryApiKey: "",
      primarySecretPresent: false,
      primarySecretPreview: "",
      untouched: "preserved",
    });
  });

  it("preserves an allowed Codex model while leaving Stable drafts byte-for-byte alone", () => {
    const allowed = {
      primaryProvider: "openai-codex",
      primaryModel: "gpt-5.4-mini",
      primaryApiKey: "",
      primarySecretPresent: false,
      primarySecretPreview: "",
    };
    expect(canonicalizePrimaryDraftForOnboarding(allowed, true).primaryModel)
      .toBe("gpt-5.4-mini");

    const stable = { ...allowed, primaryProvider: "anthropic" };
    expect(canonicalizePrimaryDraftForOnboarding(stable, false)).toBe(stable);
  });

  it("renders only the scoped sign-in path in both Beta onboarding surfaces", () => {
    const wizard = source("../wizard.tsx");
    const page = source("../index.tsx");
    const oauthCard = source("../../../components/OAuthProvidersCard.tsx");

    expect(wizard).toContain('title="Connect OpenAI Codex"');
    expect(wizard).toContain("No API key or model choice is needed.");
    expect(wizard).toContain("<OAuthProvidersCard\n                      realtorBeta");
    expect(wizard).toContain('title="Or paste API keys"');
    expect(wizard).toContain("realtorBeta ? (");

    expect(page).toContain('title="OpenAI Codex"');
    expect(page).toContain("No provider picker, model picker, or API key is needed");
    expect(page).toContain("<OAuthProvidersCard\n            realtorBeta");

    expect(oauthCard).toContain(
      "scopeOAuthProvidersForOnboarding(resp.providers, realtorBeta)",
    );
    expect(oauthCard).toContain("!p.status.logged_in && !realtorBeta");
    expect(oauthCard).toContain("p.docs_url && !realtorBeta");
    expect(oauthCard).toContain(
      "isOAuthProviderAllowedInOnboarding(loginFor.id, realtorBeta)",
    );
  });
});
