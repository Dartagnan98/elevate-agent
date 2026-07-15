import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import {
  createLicense,
  createUser,
  effectiveAccess,
  findUserByEmail,
  replaySignupLicenseV2,
  signupWithLicenseV2,
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

// Open self-serve account creation from the desktop app.
//
// The account is created ACTIVE (status defaults to "active" in createUser) so
// the realtor can sign in to the app shell immediately — but it carries ZERO
// entitlements, so no paid packs (Sales/Marketing/Admin/CMA) are unlocked until
// an admin grants them per person from the control panel ("open signup, you
// grant access"). Account creation does not imply paid access.
//
// On success we mint the same token pair as /api/auth/login so the client is
// signed in in a single round-trip.
const Body = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  first_name: z.string().trim().min(1).max(100).optional(),
  last_name: z.string().trim().min(1).max(100).optional(),
  device_label: z.string().optional(),
  initial_refresh_token: z.string().refine(isCanonical32ByteBase64Url).optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "a valid email and a password of at least 8 characters are required" },
      { status: 400 },
    );
  }
  const { password, device_label, initial_refresh_token } = parsed.data;
  const email = parsed.data.email.toLowerCase().trim();

  // Throttle account creation per IP to blunt abuse / scripted signups.
  const ip = clientIp(req);
  const limited = await enforceLimits([
    { key: `signup:ip:${ip}`, max: 5, windowSeconds: 3600 },
    { key: `signup:email:${email}`, max: 3, windowSeconds: 3600 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  if (initial_refresh_token !== undefined) {
    // The signer must be usable before the atomic user/license mutation. Any
    // failure after that transaction is recoverable because the caller owns B.
    const entitlementSigner = tryLoadEntitlementSigner();
    if (!entitlementSigner) {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }

    const proposedHash = hashRefreshToken(initial_refresh_token);
    const passwordHash = await bcrypt.hash(password, 12);
    let issuance:
      | {
          result: "created" | "replay";
          license_id: string;
          user: {
            id: string;
            email: string;
            tier: "pro" | "builder";
            status: "active" | "trialing";
          };
        }
      | { result: "collision" | "invalid" | "inactive" };

    try {
      const created = await signupWithLicenseV2({
        email,
        passwordHash,
        firstName: parsed.data.first_name ?? null,
        lastName: parsed.data.last_name ?? null,
        refreshTokenHash: proposedHash,
        deviceLabel: device_label || null,
      });

      if (created.result === "created") {
        issuance = created;
      } else if (created.result === "collision") {
        issuance = { result: "collision" };
      } else {
        // Existing email is never implicitly treated as login. The raw
        // password is verified in the route, then the replay-only RPC locks
        // the account and requires this exact stored-hash snapshot plus a
        // current signup-sourced B. It cannot create either row.
        const existing = await findUserByEmail(email);
        if (
          !existing ||
          !existing.password_hash ||
          !(await bcrypt.compare(password, existing.password_hash))
        ) {
          issuance = { result: "invalid" };
        } else {
          issuance = await replaySignupLicenseV2({
            userId: existing.id,
            expectedPasswordHash: existing.password_hash,
            refreshTokenHash: proposedHash,
          });
        }
      }
    } catch {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }

    if (issuance.result === "collision") {
      return NextResponse.json(
        { error: "initial refresh token unavailable" },
        { status: 409 },
      );
    }
    if (issuance.result === "invalid" || issuance.result === "inactive") {
      return NextResponse.json(
        { error: "an account with this email already exists — sign in instead" },
        { status: 409 },
      );
    }
    if (issuance.result !== "created" && issuance.result !== "replay") {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }

    try {
      const access_info = await effectiveAccess(issuance.user.id);
      const access = await signAccessToken({
        sub: issuance.user.id,
        email: issuance.user.email,
        tier: access_info.tier,
        license_id: issuance.license_id,
      });
      const envelope = createEntitlementEnvelope(
        {
          access_token: access,
          refresh_token: initial_refresh_token,
          sub: issuance.user.id,
          license_id: issuance.license_id,
          email: issuance.user.email,
          tier: access_info.tier,
          entitlements: access_info.entitlements,
        },
        entitlementSigner,
      );
      return NextResponse.json({
        created: true,
        ...envelope,
        orgs: access_info.orgs,
      });
    } catch {
      return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
    }
  }

  const existing = await findUserByEmail(email);
  if (existing) {
    return NextResponse.json(
      { error: "an account with this email already exists — sign in instead" },
      { status: 409 },
    );
  }

  // Validate the signing boundary before creating the account or license. A
  // misconfigured issuer must not leave a half-created successful signup.
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  const password_hash = await bcrypt.hash(password, 12);
  // Defaults: status "active", entitlements []. Active so login passes; empty
  // so the admin controls which packs each realtor gets.
  const user = await createUser({
    email,
    password_hash,
    entitlements: [],
    first_name: parsed.data.first_name ?? null,
    last_name: parsed.data.last_name ?? null,
  });

  const access_info = await effectiveAccess(user.id);
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
    created: true,
    ...envelope,
    orgs: access_info.orgs,
  });
}
