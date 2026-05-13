import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import { getEnabledSkill, logSkillInvocation } from "@/lib/store";
import { requireAccess } from "@/lib/auth-guard";
import { userCanAccessSkill } from "@/lib/skill-access";

export const runtime = "nodejs";

const Body = z.object({
  skill_name: z.string().min(1),
  args: z.record(z.unknown()).optional(),
});

export async function POST(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { claims, user } = guard;

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });
  const { skill_name, args } = parsed.data;

  const skill = getEnabledSkill(skill_name);

  if (!skill) return NextResponse.json({ error: "skill not found" }, { status: 404 });

  if (!userCanAccessSkill(user, skill)) {
    return NextResponse.json(
      { error: "skill requires an entitlement or tier this license does not include" },
      { status: 403 },
    );
  }

  const argsHash = args
    ? crypto.createHash("sha256").update(JSON.stringify(args)).digest("hex")
    : null;

  logSkillInvocation({
    user_id: claims.sub,
    skill_name,
    args_hash: argsHash,
    ip_address: req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || null,
    user_agent: req.headers.get("user-agent") || null,
  });

  return NextResponse.json({
    name: skill.name,
    version: skill.version,
    manifest: skill.manifest,
    body: skill.body,
  });
}
