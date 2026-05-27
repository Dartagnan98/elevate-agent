import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/admin-guard";
import { findUserById, listLicensesForUser } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const guard = await requireAdmin(req);
  if (!guard.ok) {
    return NextResponse.json({ error: guard.error }, { status: guard.status });
  }

  const { id } = await params;
  const user = await findUserById(id);
  if (!user) {
    return NextResponse.json({ error: "user not found" }, { status: 404 });
  }

  const licenses = await listLicensesForUser(id);
  return NextResponse.json({
    licenses: licenses.map((l) => ({
      id: l.id,
      device_label: l.device_label,
      created_at: l.created_at,
      last_used_at: l.last_used_at,
    })),
  });
}
