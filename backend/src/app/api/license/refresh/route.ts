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
} from "@/lib/jwt";
import {
  createEntitlementEnvelope,
  tryLoadEntitlementSigner,
} from "@/lib/entitlement-assertion";

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
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  const next = generateRefreshToken();
  const access = await signAccessToken({
    sub: license.user_id,
    email: active.email,
    tier: access_info.tier,
    license_id: license.id,
  });
  const envelope = createEntitlementEnvelope({
    access_token: access,
    refresh_token: next.token,
    sub: license.user_id,
    license_id: license.id,
    email: active.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
  }, entitlementSigner);

  // Rotate only after both tokens and their binding assertion exist. If signer
  // configuration is broken, the caller's current refresh remains usable.
  await rotateLicenseRefreshToken(license.id, next.hash);

  return NextResponse.json({
    ...envelope,
    orgs: access_info.orgs,
  });
}
