import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { createLicense, findActiveUser, findUserByEmail } from "@/lib/store";
import { signAccessToken, generateRefreshToken, TTL } from "@/lib/jwt";

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

  const user = findUserByEmail(email);

  if (!user || !user.password_hash || !(await bcrypt.compare(password, user.password_hash))) {
    return NextResponse.json({ error: "invalid credentials" }, { status: 401 });
  }

  const active = findActiveUser(user.id);
  if (!active) {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  const refresh = generateRefreshToken();
  const license = createLicense(user.id, refresh.hash, device_label || null);

  const access = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: active.tier,
    license_id: license.id,
  });

  return NextResponse.json({
    access_token: access,
    refresh_token: refresh.token,
    license_id: license.id,
    tier: active.tier,
    entitlements: active.entitlements,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
