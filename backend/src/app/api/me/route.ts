import { NextRequest, NextResponse } from "next/server";
import { requireAccess } from "@/lib/auth-guard";
import { effectiveAccess } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { user } = guard;

  const access_info = await effectiveAccess(user.id);

  // Derive account type from membership shape:
  //   - team_owner: owns at least one org
  //   - team_member: belongs to org(s) but owns none
  //   - single_user: no org membership at all
  const ownsAny = access_info.orgs.some((o) => o.role === "owner");
  const account_type = ownsAny
    ? "team_owner"
    : access_info.orgs.length > 0
      ? "team_member"
      : "single_user";

  return NextResponse.json({
    id: user.id,
    email: user.email,
    role: user.role,
    is_developer: user.is_developer,
    account_type,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    personal_entitlements: user.entitlements,
    status: user.status,
    orgs: access_info.orgs,
    billing: {
      has_customer: !!user.stripe_customer,
      current_period_end: user.current_period_end,
      personal_tier: user.tier,
      personal_status: user.status,
    },
  });
}
