import { NextRequest, NextResponse } from "next/server";
import { requireAccess } from "@/lib/auth-guard";
import { logAdminAction, revokeAllLicensesExcept } from "@/lib/store";

export const runtime = "nodejs";

// Revokes every license for the caller EXCEPT the current one. The current
// session continues to work — to also sign out here, the client should
// drop its localStorage tokens after a successful response.
export async function POST(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  await revokeAllLicensesExcept(auth.user.id, auth.claims.license_id);

  await logAdminAction({
    actor_user_id: auth.user.id,
    target_user_id: auth.user.id,
    action: "license.sign_out_everywhere",
    payload: { kept_license_id: auth.claims.license_id },
  });

  return NextResponse.json({ ok: true });
}
