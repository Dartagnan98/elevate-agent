import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-guard";
import { listAllUsers } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const users = await listAllUsers();
  return NextResponse.json({
    users: users.map((u) => ({
      id: u.id,
      email: u.email,
      tier: u.tier,
      status: u.status,
      role: u.role,
      is_developer: u.is_developer,
      first_name: u.first_name,
      last_name: u.last_name,
      entitlements: u.entitlements,
      blocked_entitlements: u.blocked_entitlements || [],
      stripe_customer: u.stripe_customer,
      current_period_end: u.current_period_end,
      created_at: u.created_at,
    })),
  });
}
