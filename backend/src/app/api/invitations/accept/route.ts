import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import crypto from "node:crypto";
import { z } from "zod";
import {
  acceptInvitation,
  addMembership,
  createLicense,
  createUser,
  effectiveAccess,
  findActiveUser,
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

  let user = await findUserByEmail(inv.email);
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

  if (!user) {
    if (!password) throw new Error("validated invitation password is missing");
    const password_hash = await bcrypt.hash(password, 12);
    user = await createUser({
      email: inv.email,
      password_hash,
      role: "user",
    });
  }

  // Mint a license only for an ACTIVE subscription — same gate as /auth/login
  // and /auth/login-code/verify. A newly created invitee is `active` by default;
  // this blocks an EXISTING lapsed user from re-accepting a pending invite to
  // consuming the invite, joining the org, or bypassing the paywall.
  const active = await findActiveUser(user.id);
  if (!active) {
    return NextResponse.json({ error: "no active subscription" }, { status: 402 });
  }

  if (!existing) {
    await addMembership({ org_id: inv.org_id, user_id: user.id, role: inv.role });
  }

  await acceptInvitation(inv.id, user.id);

  const access_info = await effectiveAccess(user.id);
  const refresh = generateRefreshToken();
  const license = await createLicense(user.id, refresh.hash, "invite-accept");
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
    accepted: true,
    ...envelope,
    orgs: access_info.orgs,
  });
}
