import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import { requireAdmin } from "@/lib/admin-guard";
import { inviteEmail, mailerEnabled, sendMail } from "@/lib/mailer";
import { publicBaseUrl } from "@/lib/base-url";
import {
  addMembership,
  createInvitation,
  findOrgById,
  findUserByEmail,
  getMembership,
  logAdminAction,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
  role: z.enum(["owner", "admin", "member"]).default("member"),
});

// POST /api/admin/orgs/[id]/members
// If the email already exists in users, add a membership directly.
// Otherwise create an invitation and return the invite URL the admin can share.
export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { id: orgId } = await ctx.params;

  const org = await findOrgById(orgId);
  if (!org) return NextResponse.json({ error: "org not found" }, { status: 404 });

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const { email, role } = parsed.data;

  const existing = await findUserByEmail(email);
  if (existing) {
    const already = await getMembership(orgId, existing.id);
    if (already) {
      return NextResponse.json({ error: "user already a member" }, { status: 409 });
    }
    const membership = await addMembership({ org_id: orgId, user_id: existing.id, role });
    await logAdminAction({
      actor_user_id: guard.claims.sub,
      target_user_id: existing.id,
      action: "membership_added",
      org_id: orgId,
      payload: { role, org_id: orgId },
    });
    return NextResponse.json({ added: true, membership });
  }

  // create invitation
  const token = crypto.randomBytes(32).toString("base64url");
  const token_hash = crypto.createHash("sha256").update(token).digest("hex");

  const invitation = await createInvitation({
    org_id: orgId,
    email,
    role,
    token_hash,
    invited_by: guard.claims.sub,
  });

  await logAdminAction({
    actor_user_id: guard.claims.sub,
    target_user_id: null,
    action: "invitation_created",
    payload: { invitation_id: invitation.id, email, role, org_id: orgId },
  });

  const accept_url = `${publicBaseUrl()}/invite/${token}`;

  // Email the invitee the accept link. Best-effort: the accept_url is still
  // returned so the admin can copy/share it if mail is disabled or fails.
  let emailed = false;
  if (mailerEnabled()) {
    const { subject, html } = inviteEmail({ inviteUrl: accept_url, orgName: org.name });
    const result = await sendMail({ to: email, subject, html });
    emailed = result.ok;
  }

  return NextResponse.json({
    invited: true,
    emailed,
    invitation: {
      id: invitation.id,
      email: invitation.email,
      role: invitation.role,
      expires_at: invitation.expires_at,
    },
    accept_url,
    token,
  });
}
