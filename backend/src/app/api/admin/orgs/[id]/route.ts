import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAdmin } from "@/lib/admin-guard";
import {
  deleteOrg,
  findOrgById,
  listMembershipsForOrg,
  listPendingInvitationsForOrg,
  logAdminAction,
  updateOrg,
} from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { id } = await ctx.params;

  const org = await findOrgById(id);
  if (!org) return NextResponse.json({ error: "not found" }, { status: 404 });

  const [members, invitations] = await Promise.all([
    listMembershipsForOrg(id),
    listPendingInvitationsForOrg(id),
  ]);

  return NextResponse.json({
    org,
    members: members.map((m) => ({
      id: m.id,
      user_id: m.user_id,
      role: m.role,
      created_at: m.created_at,
      email: m.user?.email ?? null,
    })),
    invitations: invitations.map((i) => ({
      id: i.id,
      email: i.email,
      role: i.role,
      status: i.status,
      expires_at: i.expires_at,
      created_at: i.created_at,
    })),
  });
}

const PatchBody = z.object({
  name: z.string().min(1).optional(),
  slug: z.string().min(1).regex(/^[a-z0-9-]+$/).optional(),
  tier: z.enum(["pro", "builder"]).optional(),
  status: z.enum(["active", "trialing", "inactive", "canceled", "past_due"]).optional(),
  entitlements: z.array(z.string()).optional(),
  seat_limit: z.number().int().min(1).optional(),
});

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { id } = await ctx.params;

  const parsed = PatchBody.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request", issues: parsed.error.issues }, { status: 400 });
  }

  await updateOrg(id, parsed.data);
  await logAdminAction({
    actor_user_id: guard.claims.sub,
    target_user_id: null,
    action: "org_updated",
    payload: { org_id: id, ...parsed.data } as Record<string, unknown>,
  });
  return NextResponse.json({ ok: true });
}

export async function DELETE(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { id } = await ctx.params;

  await deleteOrg(id);
  await logAdminAction({
    actor_user_id: guard.claims.sub,
    target_user_id: null,
    action: "org_deleted",
    payload: { org_id: id },
  });
  return NextResponse.json({ ok: true });
}
