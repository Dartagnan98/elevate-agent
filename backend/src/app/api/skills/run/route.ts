import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import { supabase, DEV_FIXTURE } from "@/lib/supabase";
import { FIXTURE_SKILLS } from "@/lib/fixtures";
import { requireAccess } from "@/lib/auth-guard";

export const runtime = "nodejs";

const Body = z.object({
  skill_name: z.string().min(1),
  args: z.record(z.unknown()).optional(),
});

const TIER_RANK: Record<string, number> = { pro: 1, builder: 2 };

export async function POST(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { claims } = guard;

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const { skill_name, args } = parsed.data;

  const skill = DEV_FIXTURE
    ? FIXTURE_SKILLS.find((s) => s.name === skill_name) || null
    : (await supabase
        .from("skills")
        .select("name,version,tier_required,manifest,body,enabled")
        .eq("name", skill_name)
        .eq("enabled", true)
        .maybeSingle()).data;

  if (!skill) return NextResponse.json({ error: "skill not found" }, { status: 404 });

  const userRank = TIER_RANK[claims.tier] ?? 0;
  const requiredRank = TIER_RANK[skill.tier_required] ?? 999;
  if (userRank < requiredRank) {
    return NextResponse.json(
      { error: `skill requires ${skill.tier_required} tier, you have ${claims.tier}` },
      { status: 403 },
    );
  }

  const argsHash = args
    ? crypto.createHash("sha256").update(JSON.stringify(args)).digest("hex")
    : null;

  if (!DEV_FIXTURE) {
    await supabase.from("skill_invocations").insert({
      user_id: claims.sub,
      skill_name,
      args_hash: argsHash,
      ip_address: req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || null,
      user_agent: req.headers.get("user-agent") || null,
    });
  }

  return NextResponse.json({
    name: skill.name,
    version: skill.version,
    manifest: skill.manifest,
    body: skill.body,
  });
}
