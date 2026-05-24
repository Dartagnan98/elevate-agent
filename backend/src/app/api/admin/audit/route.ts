import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-guard";
import { supabase } from "@/lib/supabase";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const sp = req.nextUrl.searchParams;
  const action = sp.get("action");
  const actor = sp.get("actor_user_id");
  const target = sp.get("target_user_id");
  const orgId = sp.get("org_id");
  const limit = Math.min(200, Math.max(1, Number(sp.get("limit")) || 100));

  let q = supabase()
    .from("audit_log")
    .select("*, actor:users!audit_log_actor_user_id_fkey(email), target:users!audit_log_target_user_id_fkey(email), org:organizations(name, slug)")
    .order("created_at", { ascending: false })
    .limit(limit);

  if (action) q = q.ilike("action", `%${action}%`);
  if (actor) q = q.eq("actor_user_id", actor);
  if (target) q = q.eq("target_user_id", target);
  if (orgId) q = q.eq("org_id", orgId);

  const { data, error } = await q;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ entries: data || [] });
}
