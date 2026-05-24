import { NextRequest, NextResponse } from "next/server";
import { requireAccess } from "@/lib/auth-guard";
import { listLicensesForUser } from "@/lib/store";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const licenses = await listLicensesForUser(auth.user.id);

  return NextResponse.json({
    current_license_id: auth.claims.license_id,
    licenses: licenses.map((l) => ({
      id: l.id,
      device_label: l.device_label,
      created_at: l.created_at,
      last_used_at: l.last_used_at,
      is_current: l.id === auth.claims.license_id,
    })),
  });
}
