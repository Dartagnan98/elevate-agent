import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAdmin } from "@/lib/admin-guard";
import {
  getMembership,
  listMembershipsForOrg,
  logAdminAction,
  removeMembership,
  updateMembershipRole,
} from "@/lib/store";

export const runtime = "nodejs";

const PatchBody = z.object({
  role: z.enum(["owner", "admin", "member"]),
});

export async function PATCH(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; userId: string }> },
) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { id: orgId, userId } = await ctx.params;

  const parsed = PatchBody.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });

  const membership = await getMembership(orgId, userId);
  if (!membership) {
    return NextResponse.json({ error: "membership not found" }, { status: 404 });
  }

  if (membership.role === "owner" && parsed.data.role !== "owner") {
    const ownerCount = (await listMembershipsForOrg(orgId)).filter((m) => m.role === "owner").length;
    if (ownerCount <= 1) {
      return NextResponse.json({ error: "org must keep an owner" }, { status: 409 });
    }
  }

  await updateMembershipRole(orgId, userId, parsed.data.role);
  await logAdminAction({
    actor_user_id: guard.claims.sub,
    target_user_id: userId,
    action: "membership_role_changed",
    org_id: orgId,
    payload: { role: parsed.data.role },
  });
  return NextResponse.json({ ok: true });
}

export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string; userId: string }> },
) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { id: orgId, userId } = await ctx.params;

  const membership = await getMembership(orgId, userId);
  if (!membership) {
    return NextResponse.json({ error: "membership not found" }, { status: 404 });
  }

  if (membership.role === "owner") {
    const ownerCount = (await listMembershipsForOrg(orgId)).filter((m) => m.role === "owner").length;
    if (ownerCount <= 1) {
      return NextResponse.json({ error: "org must keep an owner" }, { status: 409 });
    }
  }

  await removeMembership(orgId, userId);
  await logAdminAction({
    actor_user_id: guard.claims.sub,
    target_user_id: userId,
    action: "membership_removed",
    org_id: orgId,
    payload: { org_id: orgId },
  });
  return NextResponse.json({ ok: true });
}
