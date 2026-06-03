import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import {
  createLicense,
  createUser,
  effectiveAccess,
  findUserByEmail,
} from "@/lib/store";
import { signAccessToken, generateRefreshToken, TTL } from "@/lib/jwt";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";

export const runtime = "nodejs";

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
  device_label: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "a valid email and a password of at least 8 characters are required" },
      { status: 400 },
    );
  }
  const { password, device_label } = parsed.data;
  const email = parsed.data.email.toLowerCase().trim();

  // Throttle account creation per IP to blunt abuse / scripted signups.
  const ip = clientIp(req);
  const limited = await enforceLimits([
    { key: `signup:ip:${ip}`, max: 5, windowSeconds: 3600 },
    { key: `signup:email:${email}`, max: 3, windowSeconds: 3600 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const existing = await findUserByEmail(email);
  if (existing) {
    return NextResponse.json(
      { error: "an account with this email already exists — sign in instead" },
      { status: 409 },
    );
  }

  const password_hash = await bcrypt.hash(password, 12);
  // Defaults: status "active", entitlements []. Active so login passes; empty
  // so the admin controls which packs each realtor gets.
  const user = await createUser({ email, password_hash, entitlements: [] });

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
    created: true,
    access_token: access,
    refresh_token: refresh.token,
    license_id: license.id,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    orgs: access_info.orgs,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
