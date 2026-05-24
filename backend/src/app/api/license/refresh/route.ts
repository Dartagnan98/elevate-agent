import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import {
  effectiveAccess,
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
  const license = await findLicenseByRefreshHash(oldHash);

  if (!license || license.revoked) {
    return NextResponse.json({ error: "invalid or revoked refresh token" }, { status: 401 });
  }

  const active = await findActiveUser(license.user_id);

  if (!active) {
    await revokeLicense(license.id);
    return NextResponse.json({ error: "subscription inactive" }, { status: 402 });
  }

  const access_info = await effectiveAccess(license.user_id);

  const next = generateRefreshToken();
  await rotateLicenseRefreshToken(license.id, next.hash);

  const access = await signAccessToken({
    sub: license.user_id,
    email: active.email,
    tier: access_info.tier,
    license_id: license.id,
  });

  return NextResponse.json({
    access_token: access,
    refresh_token: next.token,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    orgs: access_info.orgs,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
