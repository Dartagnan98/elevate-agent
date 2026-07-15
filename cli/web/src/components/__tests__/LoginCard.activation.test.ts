import { describe, expect, it, vi } from "vitest";

import type {
  LicenseActivateResponse,
  LicenseStatusResponse,
} from "@/lib/api-types";
import { applyActivationOutcome, needsRequiredSetup } from "../LoginCard";

function response(
  overrides: Partial<LicenseActivateResponse> = {},
): LicenseActivateResponse {
  return {
    authenticated: true,
    email: "agent@example.test",
    tier: "realtor",
    license_id: "license-1",
    entitlements: ["real-estate-admin"],
    expires_at: 2_000_000_000,
    packs: {
      realEstateSales: false,
      realEstateMarketing: false,
      realEstateAdmin: true,
      realEstateCma: false,
      realEstateAny: true,
    },
    skill_count: 12,
    skill_names: ["real-estate-admin"],
    skill_error: null,
    skill_sync_warnings: [],
    activation_complete: true,
    ...overrides,
  };
}

describe("LoginCard activation boundary", () => {
  it("runs the confirmed path only when activation is explicitly complete", () => {
    const confirmed = vi.fn();
    const incomplete = vi.fn();

    const accepted = applyActivationOutcome(response(), { confirmed, incomplete });

    expect(accepted).toBe(true);
    expect(confirmed).toHaveBeenCalledOnce();
    expect(incomplete).not.toHaveBeenCalled();
  });

  it("routes a verified-but-incomplete status to required setup", () => {
    const status = {
      authenticated: false,
      account_verified: true,
      activation_complete: false,
    } as LicenseStatusResponse;

    expect(needsRequiredSetup(status)).toBe(true);
    expect(
      needsRequiredSetup({
        ...status,
        authenticated: true,
        activation_complete: true,
      }),
    ).toBe(false);
    expect(
      needsRequiredSetup({ ...status, account_verified: false }),
    ).toBe(false);
  });

  it.each([
    ["explicitly incomplete", response({ activation_complete: false })],
    [
      "missing completion proof",
      { ...response(), activation_complete: undefined } as unknown as LicenseActivateResponse,
    ],
    ["not authenticated", response({ authenticated: false })],
  ])("keeps %s out of the authenticated success path", (_label, result) => {
    const confirmed = vi.fn();
    const incomplete = vi.fn();

    const accepted = applyActivationOutcome(result, { confirmed, incomplete });

    expect(accepted).toBe(false);
    expect(confirmed).not.toHaveBeenCalled();
    expect(incomplete).toHaveBeenCalledOnce();
  });

  it("surfaces the server's skill failure as a retryable setup error", () => {
    const incomplete = vi.fn();

    applyActivationOutcome(
      response({
        activation_complete: false,
        skill_count: 0,
        skill_error: "Signed skill verification failed.",
      }),
      { confirmed: vi.fn(), incomplete },
    );

    expect(incomplete).toHaveBeenCalledWith(
      expect.stringContaining("Signed skill verification failed."),
      expect.any(Object),
    );
    expect(incomplete.mock.calls[0]?.[0]).toContain("Try again.");
  });
});
