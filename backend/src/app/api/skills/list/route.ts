import { NextRequest, NextResponse } from "next/server";
import { supabase, DEV_FIXTURE } from "@/lib/supabase";
import { FIXTURE_SKILLS } from "@/lib/fixtures";
import { requireAccess } from "@/lib/auth-guard";

export const runtime = "nodejs";

const TIER_RANK: Record<string, number> = { pro: 1, builder: 2 };

export async function GET(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { claims } = guard;

  const skills = DEV_FIXTURE
    ? FIXTURE_SKILLS.map(({ name, version, tier_required, manifest }) => ({ name, version, tier_required, manifest }))
    : (await supabase
        .from("skills")
        .select("name,version,tier_required,manifest")
        .eq("enabled", true)
        .order("name")).data;

  const userRank = TIER_RANK[claims.tier] ?? 0;
  const visible = (skills ?? []).filter((s) => (TIER_RANK[s.tier_required] ?? 999) <= userRank);

  return NextResponse.json({
    tier: claims.tier,
    skills: visible.map((s) => ({
      name: s.name,
      version: s.version,
      tier_required: s.tier_required,
      manifest: s.manifest,
    })),
  });
}
