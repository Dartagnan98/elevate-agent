import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAdmin } from "@/lib/admin-guard";
import {
  logAdminAction,
  revokeLicensesForUser,
  setUserDeveloperFlag,
  updateUserEntitlements,
  updateUserStatus,
  updateUserTier,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  entitlements: z.array(z.string()).optional(),
  tier: z.enum(["pro", "builder"]).optional(),
  status: z.enum(["active", "trialing", "inactive", "canceled", "past_due"]).optional(),
  revoke_licenses: z.boolean().optional(),
  is_developer: z.boolean().optional(),
});

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const { id } = await ctx.params;
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const body = parsed.data;

  if (body.entitlements) {
    await updateUserEntitlements(id, body.entitlements);
  }
  if (body.tier) {
    await updateUserTier(id, body.tier);
  }
  if (body.status) {
    await updateUserStatus(id, body.status);
  }
  if (body.revoke_licenses) {
    await revokeLicensesForUser(id);
  }
  if (typeof body.is_developer === "boolean") {
    await setUserDeveloperFlag(id, body.is_developer);
  }

  await logAdminAction({
    actor_user_id: guard.claims.sub,
    target_user_id: id,
    action: "user_updated",
    payload: body as Record<string, unknown>,
  });

  return NextResponse.json({ ok: true });
}
