import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  effectiveAccess,
  findActiveLoginCode,
  findActiveUser,
  findUserByEmail,
  recordLoginCodeAttempt,
  redeemLoginCode,
} from "@/lib/store";
import { signAccessToken, generateRefreshToken } from "@/lib/jwt";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";
import {
  createEntitlementEnvelope,
  tryLoadEntitlementSigner,
} from "@/lib/entitlement-assertion";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
  code: z.string().regex(/^\d{6}$/),
  device_label: z.string().optional(),
});

const MAX_ATTEMPTS = 5;

function invalidCode() {
  return NextResponse.json({ error: "invalid code" }, { status: 401 });
}

// Verify a one-time login code and issue a session — mirrors the password
// login route, swapping the bcrypt check for a hashed-code check.
export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const { email, code, device_label } = parsed.data;

  // Throttle verification attempts per IP+email on top of the per-code cap,
  // so an attacker can't churn many codes/guesses across the endpoint.
  const ip = clientIp(req);
  const normalized = email.toLowerCase().trim();
  const limited = await enforceLimits([
    { key: `login-code-verify:ip:${ip}`, max: 20, windowSeconds: 900 },
    { key: `login-code-verify:email:${normalized}`, max: 10, windowSeconds: 900 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const user = await findUserByEmail(normalized);
  // Uniform 401/body so unknown emails, missing/expired codes, wrong guesses,
  // exhausted codes, and concurrent losers are not distinguishable.
  if (!user) {
    return invalidCode();
  }

  const active_code = await findActiveLoginCode(user.id);
  if (!active_code) {
    return invalidCode();
  }

  if (active_code.attempts >= MAX_ATTEMPTS) {
    return invalidCode();
  }

  const code_hash = crypto.createHash("sha256").update(code).digest("hex");
  const storedHashIsValid = /^[0-9a-f]{64}$/.test(active_code.code_hash);
  const match =
    storedHashIsValid &&
    crypto.timingSafeEqual(
      Buffer.from(code_hash, "hex"),
      Buffer.from(active_code.code_hash, "hex"),
    );

  if (!match) {
    try {
      await recordLoginCodeAttempt({
        userId: user.id,
        loginCodeId: active_code.id,
        attemptedCodeHash: code_hash,
        maxAttempts: MAX_ATTEMPTS,
      });
    } catch (error) {
      // A verification-storage fault must not turn the endpoint into an email
      // oracle. The atomic RPC either counted the attempt or rolled it back.
      console.error("[auth/login-code/verify] atomic attempt failed:", error);
    }
    return invalidCode();
  }

  const active = await findActiveUser(user.id);
  if (!active) {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  // Keep the single-use code retryable if the assertion signer is unavailable.
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  const access_info = await effectiveAccess(user.id);
  const refresh = generateRefreshToken();
  const licenseId = crypto.randomUUID();
  const access = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: access_info.tier,
    license_id: licenseId,
  });

  const envelope = createEntitlementEnvelope({
    access_token: access,
    refresh_token: refresh.token,
    sub: user.id,
    license_id: licenseId,
    email: user.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
  }, entitlementSigner);

  // Only after the complete signed response exists do we consume the code and
  // create its exact license. The RPC rechecks newest/unexpired/attempt state
  // and active subscription under one per-user lock, then commits both writes
  // together. A concurrent loser receives no prepared credentials.
  let redeemed: Awaited<ReturnType<typeof redeemLoginCode>>;
  try {
    redeemed = await redeemLoginCode({
      userId: user.id,
      loginCodeId: active_code.id,
      codeHash: code_hash,
      licenseId,
      refreshTokenHash: refresh.hash,
      deviceLabel: device_label || null,
      maxAttempts: MAX_ATTEMPTS,
    });
  } catch (error) {
    console.error("[auth/login-code/verify] atomic redeem failed:", error);
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  if (redeemed.result === "inactive") {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }
  if (redeemed.result !== "redeemed") {
    return invalidCode();
  }

  return NextResponse.json({
    ...envelope,
    orgs: access_info.orgs,
  });
}
