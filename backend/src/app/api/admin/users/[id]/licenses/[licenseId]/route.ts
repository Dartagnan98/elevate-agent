import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-guard";
import { findUserById, logAdminAction, revokeLicenseForUser } from "@/lib/store";

export const runtime = "nodejs";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; licenseId: string }> },
) {
  const guard = await requireAdmin(req);
  if (!guard.ok) {
    return NextResponse.json({ error: guard.error }, { status: guard.status });
  }

  const { id, licenseId } = await params;
  const target = await findUserById(id);
  if (!target) {
    return NextResponse.json({ error: "user not found" }, { status: 404 });
  }

  const ok = await revokeLicenseForUser(licenseId, id);
  if (!ok) {
    return NextResponse.json({ error: "license not found" }, { status: 404 });
  }

  await logAdminAction({
    actor_user_id: guard.user.id,
    target_user_id: id,
    action: "license.admin_revoked",
    payload: { license_id: licenseId, target_email: target.email },
  });

  return NextResponse.json({ ok: true });
}
