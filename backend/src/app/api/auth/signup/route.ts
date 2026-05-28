import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import {
  createLicense,
  createUser,
  effectiveAccess,
  findUserByEmail,
  logAdminAction,
} from "@/lib/store";
import { signAccessToken, generateRefreshToken, TTL } from "@/lib/jwt";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(200),
  device_label: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "bad request — password must be at least 8 chars" },
      { status: 400 },
    );
  }
  const { email, password, device_label } = parsed.data;
  const normalized = email.toLowerCase().trim();

  // Throttle mass/automated account creation per IP.
  const ip = clientIp(req);
  const limited = await enforceLimits([
    { key: `signup:ip:${ip}`, max: 5, windowSeconds: 3600 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const existing = await findUserByEmail(normalized);
  if (existing) {
    return NextResponse.json({ error: "email already registered" }, { status: 409 });
  }

  const password_hash = await bcrypt.hash(password, 12);

  // New self-serve accounts start as single_user / pro tier / active /
  // no entitlements. They can join a team or upgrade via Stripe later.
  const user = await createUser({
    email: normalized,
    password_hash,
    tier: "pro",
    status: "active",
    role: "user",
    entitlements: [],
  });

  const access_info = await effectiveAccess(user.id);

  const refresh = generateRefreshToken();
  const license = await createLicense(user.id, refresh.hash, device_label || "signup");

  const access = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: access_info.tier,
    license_id: license.id,
  });

  await logAdminAction({
    actor_user_id: user.id,
    target_user_id: user.id,
    action: "user.signup_self",
    payload: { email: user.email },
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
