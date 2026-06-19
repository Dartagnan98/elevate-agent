import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAdmin } from "@/lib/admin-guard";
import { createOrg, listOrgs, logAdminAction } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const orgs = await listOrgs();
  return NextResponse.json({ orgs });
}

const CreateBody = z.object({
  slug: z.string().min(1).regex(/^[a-z0-9-]+$/, "lowercase, digits, dashes only"),
  name: z.string().min(1),
  tier: z.enum(["pro", "builder"]).optional(),
  entitlements: z.array(z.string()).optional(),
  seat_limit: z.number().int().min(1).optional(),
});

export async function POST(req: NextRequest) {
  const guard = await requireAdmin(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const parsed = CreateBody.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request", issues: parsed.error.issues }, { status: 400 });
  }

  try {
    const org = await createOrg(parsed.data);
    await logAdminAction({
      actor_user_id: guard.claims.sub,
      target_user_id: null,
      action: "org_created",
      org_id: org.id,
      payload: { org_id: org.id, slug: org.slug, name: org.name },
    });
    return NextResponse.json({ org });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "create failed";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
