import { NextRequest, NextResponse } from "next/server";
import { effectiveAccess, listEnabledSkills } from "@/lib/store";
import { requireAccess } from "@/lib/auth-guard";
import { userCanAccessSkill } from "@/lib/skill-access";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { user } = guard;

  const access_info = await effectiveAccess(user.id);
  const merged = { ...user, tier: access_info.tier, entitlements: access_info.entitlements };

  const all = await listEnabledSkills();
  const visible = all.filter((skill) => userCanAccessSkill(merged, skill));

  return NextResponse.json({
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    orgs: access_info.orgs,
    skills: visible.map((s) => ({
      name: s.name,
      version: s.version,
      tier_required: s.tier_required,
      manifest: s.manifest,
    })),
  });
}
