import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import {
  findActiveUser,
  findLicenseByRefreshHash,
  revokeLicense,
  rotateLicenseRefreshToken,
} from "@/lib/store";
import {
  signAccessToken,
  generateRefreshToken,
  hashRefreshToken,
  TTL,
} from "@/lib/jwt";

export const runtime = "nodejs";

const Body = z.object({ refresh_token: z.string().min(1) });

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });

  const oldHash = hashRefreshToken(parsed.data.refresh_token);
  const license = findLicenseByRefreshHash(oldHash);

  if (!license || license.revoked) {
    return NextResponse.json({ error: "invalid or revoked refresh token" }, { status: 401 });
  }

  const active = findActiveUser(license.user_id);

  if (!active) {
    revokeLicense(license.id);
    return NextResponse.json({ error: "subscription inactive" }, { status: 402 });
  }

  const next = generateRefreshToken();
  rotateLicenseRefreshToken(license.id, next.hash);

  const access = await signAccessToken({
    sub: license.user_id,
    email: active.email,
    tier: (active.tier as "pro" | "builder") ?? "pro",
    license_id: license.id,
  });

  return NextResponse.json({
    access_token: access,
    refresh_token: next.token,
    entitlements: active.entitlements,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
