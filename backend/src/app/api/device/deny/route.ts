import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import { denyDeviceGrant, findDeviceGrantByUserCode, logAdminAction } from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  user_code: z.string().min(4).max(20),
});

export async function POST(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const grant = await findDeviceGrantByUserCode(parsed.data.user_code.trim().toUpperCase());
  if (!grant) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  if (grant.status !== "pending") {
    return NextResponse.json({ error: `already ${grant.status}` }, { status: 409 });
  }

  await denyDeviceGrant(grant.id, auth.user.id);

  await logAdminAction({
    actor_user_id: auth.user.id,
    target_user_id: auth.user.id,
    action: "device.link.denied",
    payload: { grant_id: grant.id, user_code: grant.user_code },
  });

  return NextResponse.json({ ok: true });
}
