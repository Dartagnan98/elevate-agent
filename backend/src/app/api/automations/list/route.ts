import { NextRequest, NextResponse } from "next/server";
import { effectiveAccess, listEnabledAutomations } from "@/lib/store";
import { requireAccess } from "@/lib/auth-guard";
import { userCanAccessGated } from "@/lib/skill-access";

export const runtime = "nodejs";

// Premium lead/admin automation kit. Mirrors /api/skills/list: tier +
// entitlement gated, returns full specs (the client seeds them PAUSED per
// account). Unlike skills there's no separate "run" fetch — the whole spec
// ships in the list so the CLI can create the cron job offline-once-cached.
export async function GET(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });
  const { user } = guard;

  let access_info;
  let all;
  try {
    access_info = await effectiveAccess(user.id);
    all = await listEnabledAutomations();
  } catch (e) {
    console.error("[automations/list] catalog unavailable:", e);
    return NextResponse.json({ error: "automations catalog unavailable" }, { status: 503 });
  }

  const merged = { ...user, tier: access_info.tier, entitlements: access_info.entitlements };
  const visible = all.filter((a) => userCanAccessGated(merged, a));

  return NextResponse.json({
    tier: access_info.tier,
    entitlements: access_info.entitlements,
    automations: visible.map((a) => ({
      name: a.name,
      surface: a.surface,
      kind: a.kind,
      schedule: a.schedule,
      skill: a.skill,
      prompt: a.prompt,
      deliver: a.deliver,
      spec: a.spec,
      version: a.version,
      tier_required: a.tier_required,
      manifest: a.manifest,
    })),
  });
}
