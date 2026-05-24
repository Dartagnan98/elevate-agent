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
  findInvitationByTokenHash,
  findUserByEmail,
  getMembership,
} from "@/lib/store";
import { signAccessToken, generateRefreshToken, TTL } from "@/lib/jwt";

export const runtime = "nodejs";

const Body = z.object({
  token: z.string().min(1),
  // password is required only when the email isn't an existing user
  password: z.string().min(8).optional(),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });

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
  if (!user) {
    if (!parsed.data.password) {
      return NextResponse.json(
        { error: "password required to create account", needs_password: true, email: inv.email },
        { status: 400 },
      );
    }
    const password_hash = await bcrypt.hash(parsed.data.password, 12);
    user = await createUser({
      email: inv.email,
      password_hash,
      role: "user",
    });
  }

  const existing = await getMembership(inv.org_id, user.id);
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

  return NextResponse.json({
    accepted: true,
    access_token: access,
    refresh_token: refresh.token,
    license_id: license.id,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    orgs: access_info.orgs,
    expires_in: TTL.ACCESS_SECONDS,
  });
}
