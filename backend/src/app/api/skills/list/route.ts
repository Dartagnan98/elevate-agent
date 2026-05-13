import { NextRequest, NextResponse } from "next/server";
import { listEnabledSkills } from "@/lib/store";
import { requireAccess } from "@/lib/auth-guard";
import { userCanAccessSkill } from "@/lib/skill-access";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { user } = guard;

  const visible = listEnabledSkills().filter((skill) => userCanAccessSkill(user, skill));

  return NextResponse.json({
    tier: user.tier,
    entitlements: user.entitlements,
    skills: visible.map((s) => ({
      name: s.name,
      version: s.version,
      tier_required: s.tier_required,
      manifest: s.manifest,
    })),
  });
}
