import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import {
  findUserByEmail,
  findUserById,
  logAdminAction,
  updateUserEmail,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export async function PATCH(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const newEmail = parsed.data.email.toLowerCase().trim();

  // Verify caller still knows the password (defense against stolen-token email takeover).
  const fresh = await findUserById(auth.user.id);
  if (!fresh || !fresh.password_hash) {
    return NextResponse.json({ error: "account has no password set" }, { status: 400 });
  }
  const ok = await bcrypt.compare(parsed.data.password, fresh.password_hash);
  if (!ok) {
    return NextResponse.json({ error: "wrong password" }, { status: 401 });
  }

  // Block collision with another account.
  if (newEmail !== fresh.email.toLowerCase()) {
    const collision = await findUserByEmail(newEmail);
    if (collision && collision.id !== auth.user.id) {
      return NextResponse.json({ error: "email already in use" }, { status: 409 });
    }
  }

  await updateUserEmail(auth.user.id, newEmail);

  await logAdminAction({
    actor_user_id: auth.user.id,
    target_user_id: auth.user.id,
    action: "user.email_changed",
    payload: { from: fresh.email, to: newEmail },
  }).catch(() => undefined);

  return NextResponse.json({ ok: true, email: newEmail });
}
