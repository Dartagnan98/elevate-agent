import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import crypto from "node:crypto";
import { z } from "zod";
import {
  acceptInvitationAtomic,
  effectiveAccess,
  findInvitationByTokenHash,
  findOrgById,
  findUserByEmail,
  getMembership,
  listMembershipsForOrg,
} from "@/lib/store";
import { signAccessToken, generateRefreshToken } from "@/lib/jwt";
import {
  createEntitlementEnvelope,
  tryLoadEntitlementSigner,
} from "@/lib/entitlement-assertion";

export const runtime = "nodejs";

const Body = z.object({
  token: z.string().min(1),
  // password is required only when the email isn't an existing user
  password: z.string().min(8).optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const password = parsed.data.password;

  const tokenHash = crypto.createHash("sha256").update(parsed.data.token).digest("hex");
  const inv = await findInvitationByTokenHash(tokenHash);
  if (!inv) return NextResponse.json({ error: "invalid invitation" }, { status: 404 });
  if (inv.status !== "pending") {
    return NextResponse.json({ error: `invitation ${inv.status}` }, { status: 410 });
  }
  if (new Date(inv.expires_at).getTime() < Date.now()) {
    return NextResponse.json({ error: "invitation expired" }, { status: 410 });
  }

  const user = await findUserByEmail(inv.email);
  const existing = user ? await getMembership(inv.org_id, user.id) : null;
  if (!existing) {
    const org = await findOrgById(inv.org_id);
    if (!org) return NextResponse.json({ error: "org not found" }, { status: 404 });
    const memberCount = (await listMembershipsForOrg(inv.org_id)).length;
    if (memberCount >= org.seat_limit) {
      return NextResponse.json({ error: "seat limit reached" }, { status: 409 });
    }
  }

  if (!user && !password) {
    return NextResponse.json(
      { error: "password required to create account", needs_password: true, email: inv.email },
      { status: 400 },
    );
  }

  // Resolve the signer before creating a user, joining an org, or consuming
  // the invitation so deployment mistakes cannot leave a partial acceptance.
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  // Prepare every credential/input that does not depend on the committed
  // membership before the transactional RPC. The RPC resolves the invited
  // email again, creates it from these route-generated values only if needed,
  // rechecks active status, allocates the seat, consumes the invite, and creates
  // this exact license as one commit.
  const passwordHash = password ? await bcrypt.hash(password, 12) : null;
  const refresh = generateRefreshToken();
  const licenseId = crypto.randomUUID();
  let accepted: Awaited<ReturnType<typeof acceptInvitationAtomic>>;
  try {
    accepted = await acceptInvitationAtomic({
      invitationId: inv.id,
      tokenHash,
      newUserId: crypto.randomUUID(),
      newUserPasswordHash: passwordHash,
      licenseId,
      refreshTokenHash: refresh.hash,
    });
  } catch (error) {
    console.error("[invitations/accept] atomic acceptance failed:", error);
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  if (accepted.result === "invalid") {
    return NextResponse.json({ error: "invalid invitation" }, { status: 404 });
  }
  if (accepted.result === "already_accepted") {
    return NextResponse.json({ error: "invitation accepted" }, { status: 410 });
  }
  if (accepted.result === "revoked") {
    return NextResponse.json({ error: "invitation revoked" }, { status: 410 });
  }
  if (accepted.result === "expired") {
    return NextResponse.json({ error: "invitation expired" }, { status: 410 });
  }
  if (accepted.result === "org_not_found") {
    return NextResponse.json({ error: "org not found" }, { status: 404 });
  }
  if (accepted.result === "seat_limit") {
    return NextResponse.json({ error: "seat limit reached" }, { status: 409 });
  }
  if (accepted.result === "password_required") {
    return NextResponse.json(
      {
        error: "password required to create account",
        needs_password: true,
        email: accepted.email || inv.email,
      },
      { status: 400 },
    );
  }
  if (accepted.result === "inactive") {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  // Entitlements depend on the just-committed membership, so this is the first
  // point where the final access envelope can be constructed truthfully.
  const access_info = await effectiveAccess(accepted.user.id);
  const access = await signAccessToken({
    sub: accepted.user.id,
    email: accepted.user.email,
    tier: access_info.tier,
    license_id: licenseId,
  });

  const envelope = createEntitlementEnvelope({
    access_token: access,
    refresh_token: refresh.token,
    sub: accepted.user.id,
    license_id: licenseId,
    email: accepted.user.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
  }, entitlementSigner);

  return NextResponse.json({
    accepted: true,
    ...envelope,
    orgs: access_info.orgs,
  });
}
