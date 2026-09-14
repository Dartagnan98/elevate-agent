import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  effectiveAccess,
  findDeviceGrantByDeviceCodeHash,
  findLicenseById,
  findUserById,
  markDeviceGrantClaimed,
  touchDeviceGrantPoll,
} from "@/lib/store";
import { signAccessToken, TTL } from "@/lib/jwt";

export const runtime = "nodejs";

const Body = z.object({
  device_code: z.string().min(10),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const hash = crypto.createHash("sha256").update(parsed.data.device_code).digest("hex");
  const grant = await findDeviceGrantByDeviceCodeHash(hash);

  if (!grant) {
    return NextResponse.json({ error: "invalid_grant" }, { status: 404 });
  }

  // Expiry check (covers race where status hasn't been swept yet)
  if (new Date(grant.expires_at).getTime() < Date.now()) {
    return NextResponse.json({ error: "expired_token", status: "expired" }, { status: 410 });
  }

  if (grant.status === "denied") {
    return NextResponse.json({ error: "access_denied", status: "denied" }, { status: 403 });
  }

  if (grant.status === "expired") {
    return NextResponse.json({ error: "expired_token", status: "expired" }, { status: 410 });
  }

  if (grant.status === "claimed") {
    return NextResponse.json({ error: "already_claimed", status: "claimed" }, { status: 410 });
  }

  if (grant.status === "pending") {
    await touchDeviceGrantPoll(grant.id);
    return NextResponse.json({ status: "pending", interval: 5 });
  }

  // status === "approved" — issue fresh access token bound to the pre-created license
  if (!grant.user_id || !grant.license_id) {
    return NextResponse.json({ error: "invalid_grant" }, { status: 500 });
  }

  const license = await findLicenseById(grant.license_id);
  if (!license || license.revoked) {
    return NextResponse.json({ error: "license_revoked" }, { status: 403 });
  }

  const user = await findUserById(grant.user_id);
  if (!user) {
    return NextResponse.json({ error: "user_not_found" }, { status: 404 });
  }

  const access_info = await effectiveAccess(user.id);

  const access_token = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: access_info.tier,
    license_id: license.id,
  });

  // The refresh token was generated at approval time and embedded in the grant
  // payload? No — we never round-trip the raw refresh token through the DB.
  // Instead, at approval time we rotate the license and stash the raw refresh
  // in a one-shot field on the grant. Simpler: issue the refresh at claim time.
  // (See approve/route.ts — it pre-creates the license but the raw refresh
  // token is short-lived and stored alongside the device_code so it's only
  // ever read by the polling CLI on exactly one successful claim.)
  let refresh_payload: string;
  try {
    refresh_payload = await consumeStashedRefresh(grant.id);
  } catch {
    return NextResponse.json({ error: "invalid_grant" }, { status: 500 });
  }

  await markDeviceGrantClaimed(grant.id);

  return NextResponse.json({
    status: "approved",
    access_token,
    refresh_token: refresh_payload,
    license_id: license.id,
    email: user.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    orgs: access_info.orgs,
    expires_in: TTL.ACCESS_SECONDS,
  });
}

// Helper kept here (and not in store.ts) because the field-stash is an
// implementation detail of the device-grant flow. We use an out-of-band
// row in `licenses.metadata` would couple things; instead, abuse the
// `device_grants` table itself by storing the raw refresh token under
// a column we'll add via migration. For now: re-mint a refresh by rotating
// the license, since rotating is idempotent enough for a one-time claim.
async function consumeStashedRefresh(grantId: string): Promise<string> {
  // Read raw refresh from the grant row (added in migration 0004 as
  // `device_grants.refresh_token_plain text null`). We delete it as part
  // of the markClaimed write so it lives in the DB for ~30s tops.
  const { supabase } = await import("@/lib/supabase");
  const { data, error } = await supabase()
    .from("device_grants")
    .select("refresh_token_plain")
    .eq("id", grantId)
    .single();
  if (error) throw error;
  const raw = (data as { refresh_token_plain: string | null }).refresh_token_plain;
  if (!raw) throw new Error("missing stashed refresh token");
  const { error: clearError } = await supabase()
    .from("device_grants")
    .update({ refresh_token_plain: null })
    .eq("id", grantId);
  if (clearError) throw clearError;
  return raw;
}
