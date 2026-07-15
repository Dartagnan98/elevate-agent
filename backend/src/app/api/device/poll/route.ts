import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  effectiveAccess,
  expireDeviceGrant,
  findActiveUser,
  findDeviceGrantByDeviceCodeHash,
  findLicenseById,
  markDeviceGrantClaimed,
  revokeLicense,
  touchDeviceGrantPoll,
} from "@/lib/store";
import { hashRefreshToken, signAccessToken } from "@/lib/jwt";
import {
  createEntitlementEnvelope,
  tryLoadEntitlementSigner,
} from "@/lib/entitlement-assertion";

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
  const expiresAt = Date.parse(grant.expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await expireDeviceGrant(grant.id);
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
    await expireDeviceGrant(grant.id);
    return NextResponse.json({ error: "license_revoked" }, { status: 403 });
  }
  if (license.user_id !== grant.user_id) {
    await expireDeviceGrant(grant.id);
    return NextResponse.json({ error: "invalid_grant" }, { status: 500 });
  }

  const user = await findActiveUser(grant.user_id);
  if (!user) {
    await expireDeviceGrant(grant.id);
    await revokeLicense(license.id);
    return NextResponse.json({ error: "subscription inactive" }, { status: 402 });
  }

  const access_info = await effectiveAccess(user.id);
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  // Approval stashes the raw refresh token for this one-shot claim. Read it
  // without clearing it, build the complete signed envelope, then atomically
  // mark the grant claimed and clear the stash in one database update.
  let refresh_payload: string;
  try {
    refresh_payload = await readStashedRefresh(grant.id);
  } catch {
    return NextResponse.json({ error: "invalid_grant" }, { status: 500 });
  }
  if (hashRefreshToken(refresh_payload) !== license.refresh_token_hash) {
    await expireDeviceGrant(grant.id);
    return NextResponse.json({ error: "invalid_grant" }, { status: 500 });
  }

  const access_token = await signAccessToken({
    sub: user.id,
    email: user.email,
    tier: access_info.tier,
    license_id: license.id,
  });
  const envelope = createEntitlementEnvelope({
    access_token,
    refresh_token: refresh_payload,
    sub: user.id,
    license_id: license.id,
    email: user.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
  }, entitlementSigner);

  try {
    const claimed = await markDeviceGrantClaimed(grant.id);
    if (!claimed) {
      // Another poll won the one-shot claim. Do not return the credentials
      // prepared by this losing request.
      return NextResponse.json(
        { error: "already_claimed", status: "claimed" },
        { status: 410 },
      );
    }
  } catch {
    // The atomic claim+clear write failed, so return no credentials. The grant
    // and its stash remain retryable rather than leaking a one-shot refresh.
    return NextResponse.json({ error: "invalid_grant" }, { status: 500 });
  }

  return NextResponse.json({
    status: "approved",
    ...envelope,
    orgs: access_info.orgs,
  });
}

// Kept here because the short-lived plaintext stash is an implementation
// detail of the device grant claim, not a general store operation.
async function readStashedRefresh(grantId: string): Promise<string> {
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
  return raw;
}
