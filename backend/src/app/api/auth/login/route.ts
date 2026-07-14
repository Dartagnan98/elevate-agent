import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import {
  createLicense,
  effectiveAccess,
  findActiveUser,
  findUserByEmail,
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
  password: z.string().min(1),
  device_label: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const { email, password, device_label } = parsed.data;

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
