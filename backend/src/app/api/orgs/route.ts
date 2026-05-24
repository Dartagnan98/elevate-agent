// Self-serve org creation. Any authenticated user can create a team.
// Caller automatically becomes the org owner. Starts on pro tier with
// 1 seat (themselves); upgrade/seat-buy flow lives in admin/billing.
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import {
  addMembership,
  createOrg,
  findOrgBySlug,
  listMembershipsForUser,
  logAdminAction,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  name: z.string().min(2).max(80),
  slug: z
    .string()
    .min(2)
    .max(60)
    .regex(/^[a-z0-9-]+$/, "lowercase, digits, dashes only")
    .optional(),
});

function slugify(s: string) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

// GET: list orgs the caller belongs to.
export async function GET(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const memberships = await listMembershipsForUser(guard.user.id);
  return NextResponse.json({
    orgs: memberships.map((m) => ({
      id: m.organization.id,
      slug: m.organization.slug,
      name: m.organization.name,
      tier: m.organization.tier,
      status: m.organization.status,
      seat_limit: m.organization.seat_limit,
      entitlements: m.organization.entitlements,
      role: m.role,
    })),
  });
}

// POST: create a new org with the caller as owner.
export async function POST(req: NextRequest) {
  const guard = await requireAccess(req);
  if (!guard.ok) return NextResponse.json({ error: guard.error }, { status: guard.status });

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request", issues: parsed.error.issues }, { status: 400 });
  }

  const baseSlug = parsed.data.slug || slugify(parsed.data.name);
  if (!baseSlug) {
    return NextResponse.json({ error: "could not derive slug from name" }, { status: 400 });
  }

  // Find a free slug; append -2, -3, ... if needed.
  let slug = baseSlug;
  for (let i = 2; i < 30; i++) {
    const existing = await findOrgBySlug(slug);
    if (!existing) break;
    slug = `${baseSlug}-${i}`;
  }

  try {
    const org = await createOrg({
      name: parsed.data.name,
      slug,
      tier: "pro",
      status: "active",
      entitlements: [],
      seat_limit: 1,
    });
    await addMembership({ org_id: org.id, user_id: guard.user.id, role: "owner" });
    await logAdminAction({
      actor_user_id: guard.user.id,
      target_user_id: null,
      org_id: org.id,
      action: "org_self_created",
      payload: { slug: org.slug, name: org.name },
    });
    return NextResponse.json({ org });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "create failed";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
