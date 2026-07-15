import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import {
  createLicense,
  effectiveAccess,
  findActiveUser,
  findUserByEmail,
  issueExistingUserLicenseV2,
} from "@/lib/store";
import {
  signAccessToken,
  generateRefreshToken,
  hashRefreshToken,
} from "@/lib/jwt";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";
import {
  createEntitlementEnvelope,
  tryLoadEntitlementSigner,
} from "@/lib/entitlement-assertion";

export const runtime = "nodejs";

function isCanonical32ByteBase64Url(value: string): boolean {
  if (!/^[A-Za-z0-9_-]{43}$/.test(value)) return false;
  const decoded = Buffer.from(value, "base64url");
  return decoded.length === 32 && decoded.toString("base64url") === value;
}

const Body = z.object({
  email: z.string().email(),
  password: z.string().min(1),
  device_label: z.string().optional(),
  initial_refresh_token: z.string().refine(isCanonical32ByteBase64Url).optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const { email, password, device_label, initial_refresh_token } = parsed.data;

  // Throttle online brute-force / credential stuffing.
  const ip = clientIp(req);
  const limited = await enforceLimits([
    { key: `login:ip:${ip}`, max: 10, windowSeconds: 900 },
    { key: `login:email:${email.toLowerCase().trim()}`, max: 5, windowSeconds: 900 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const user = await findUserByEmail(email);

  if (!user || !user.password_hash || !(await bcrypt.compare(password, user.password_hash))) {
    return NextResponse.json({ error: "invalid credentials" }, { status: 401 });
  }

  const active = await findActiveUser(user.id);
  if (!active) {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  if (initial_refresh_token !== undefined) {
    const entitlementSigner = tryLoadEntitlementSigner();
    if (!entitlementSigner) {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }

    let issuance: Awaited<ReturnType<typeof issueExistingUserLicenseV2>>;
    try {
      issuance = await issueExistingUserLicenseV2({
        userId: user.id,
        expectedPasswordHash: user.password_hash,
        refreshTokenHash: hashRefreshToken(initial_refresh_token),
        deviceLabel: device_label || null,
      });
    } catch {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }

    if (issuance.result === "inactive") {
      return NextResponse.json({ error: "no active subscription" }, { status: 402 });
    }
    if (issuance.result === "invalid") {
      return NextResponse.json({ error: "invalid credentials" }, { status: 401 });
    }
    if (issuance.result === "collision") {
      return NextResponse.json(
        { error: "initial refresh token unavailable" },
        { status: 409 },
      );
    }
    if (issuance.result !== "issued" && issuance.result !== "replay") {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }

    try {
      const access_info = await effectiveAccess(issuance.user_id);
      const access = await signAccessToken({
        sub: issuance.user_id,
        email: issuance.email,
        tier: access_info.tier,
        license_id: issuance.license_id,
      });
      const envelope = createEntitlementEnvelope(
        {
          access_token: access,
          refresh_token: initial_refresh_token,
          sub: issuance.user_id,
          license_id: issuance.license_id,
          email: issuance.email,
          tier: access_info.tier,
          entitlements: access_info.entitlements,
        },
        entitlementSigner,
      );
      return NextResponse.json({
        ...envelope,
        orgs: access_info.orgs,
      });
    } catch {
      // The hash-only license is already committed. The caller still owns B
      // and can recover through Refresh v2 without replaying the password.
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }
  }

  const access_info = await effectiveAccess(user.id);
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  const refresh = generateRefreshToken();
  const license = await createLicense(user.id, refresh.hash, device_label || null);

  const access = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: access_info.tier,
    license_id: license.id,
  });

  const envelope = createEntitlementEnvelope({
    access_token: access,
    refresh_token: refresh.token,
    sub: user.id,
    license_id: license.id,
    email: user.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
  }, entitlementSigner);

  return NextResponse.json({
    ...envelope,
    orgs: access_info.orgs,
  });
}
