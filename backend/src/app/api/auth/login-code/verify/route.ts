import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  consumeLoginCode,
  createLicense,
  effectiveAccess,
  findActiveLoginCode,
  findActiveUser,
  findUserByEmail,
  incrementLoginCodeAttempts,
} from "@/lib/store";
import { signAccessToken, generateRefreshToken, TTL } from "@/lib/jwt";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
  code: z.string().regex(/^\d{6}$/),
  device_label: z.string().optional(),
});

const MAX_ATTEMPTS = 5;

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
  // Uniform 401 so neither unknown emails nor missing codes are distinguishable.
  if (!user) {
    return NextResponse.json({ error: "invalid code" }, { status: 401 });
  }

  const active_code = await findActiveLoginCode(user.id);
  if (!active_code) {
    return NextResponse.json({ error: "invalid code" }, { status: 401 });
  }

  // Brute-force cap per issued code.
  if (active_code.attempts >= MAX_ATTEMPTS) {
    return NextResponse.json(
      { error: "too many attempts; request a new code" },
      { status: 429 },
    );
  }

  const code_hash = crypto.createHash("sha256").update(code).digest("hex");
  const match = crypto.timingSafeEqual(
    Buffer.from(code_hash, "hex"),
    Buffer.from(active_code.code_hash, "hex"),
  );

  if (!match) {
    const attempts = await incrementLoginCodeAttempts(active_code.id);
    const remaining = Math.max(0, MAX_ATTEMPTS - attempts);
    return NextResponse.json(
      { error: "invalid code", attempts_remaining: remaining },
      { status: 401 },
    );
  }

  // Single-use: consume before issuing the session.
  await consumeLoginCode(active_code.id);

  const active = await findActiveUser(user.id);
  if (!active) {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  const access_info = await effectiveAccess(user.id);
  const refresh = generateRefreshToken();
  const license = await createLicense(user.id, refresh.hash, device_label || null);
  const access = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: access_info.tier,
    license_id: license.id,
  });

  return NextResponse.json({
    access_token: access,
    refresh_token: refresh.token,
    license_id: license.id,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    orgs: access_info.orgs,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
