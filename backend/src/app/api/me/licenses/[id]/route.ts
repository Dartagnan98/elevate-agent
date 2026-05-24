import { NextRequest, NextResponse } from "next/server";
import { requireAccess } from "@/lib/auth-guard";
import { logAdminAction, revokeLicenseForUser } from "@/lib/store";

export const runtime = "nodejs";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const { id } = await params;

  const ok = await revokeLicenseForUser(id, auth.user.id);
  if (!ok) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  await logAdminAction({
    actor_user_id: auth.user.id,
    target_user_id: auth.user.id,
    action: "license.self_revoked",
    payload: { license_id: id, revoked_self: id === auth.claims.license_id },
  });

  return NextResponse.json({ ok: true });
}
