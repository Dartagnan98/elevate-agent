import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import {
  findUserById,
  logAdminAction,
  revokeAllLicensesExcept,
  updateUserPasswordHash,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  current_password: z.string().min(1),
  new_password: z.string().min(8).max(200),
  sign_out_everywhere: z.boolean().optional(),
});

export async function PATCH(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "bad request — new_password must be at least 8 chars" },
      { status: 400 },
    );
  }

  const fresh = await findUserById(auth.user.id);
  if (!fresh || !fresh.password_hash) {
    return NextResponse.json({ error: "account has no password set" }, { status: 400 });
  }

  const ok = await bcrypt.compare(parsed.data.current_password, fresh.password_hash);
  if (!ok) {
    return NextResponse.json({ error: "wrong current password" }, { status: 401 });
  }

  const hash = await bcrypt.hash(parsed.data.new_password, 12);
  await updateUserPasswordHash(auth.user.id, hash);

  if (parsed.data.sign_out_everywhere) {
    await revokeAllLicensesExcept(auth.user.id, auth.claims.license_id);
  }

  await logAdminAction({
    actor_user_id: auth.user.id,
    target_user_id: auth.user.id,
    action: "user.password_changed",
    payload: { signed_out_other_devices: !!parsed.data.sign_out_everywhere },
  });

  return NextResponse.json({ ok: true });
}
