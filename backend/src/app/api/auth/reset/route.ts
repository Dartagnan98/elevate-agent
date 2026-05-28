import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import crypto from "node:crypto";
import { z } from "zod";
import {
  consumePasswordReset,
  findPasswordResetByHash,
  findUserById,
  logAdminAction,
  revokeLicensesForUser,
  updateUserPasswordHash,
} from "@/lib/store";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";

export const runtime = "nodejs";

const Body = z.object({
  token: z.string().min(10),
  new_password: z.string().min(8).max(200),
});

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json(
      { error: "bad request — new_password must be at least 8 chars" },
      { status: 400 },
    );
  }

  // Throttle token-guessing attempts per IP (tokens are unguessable, but this
  // is cheap defense-in-depth against churn).
  const ip = clientIp(req);
  const limited = await enforceLimits([
    { key: `reset:ip:${ip}`, max: 20, windowSeconds: 3600 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const token_hash = crypto
    .createHash("sha256")
    .update(parsed.data.token)
    .digest("hex");

  const row = await findPasswordResetByHash(token_hash);
  if (!row) {
    return NextResponse.json({ error: "invalid or expired token" }, { status: 400 });
  }
  if (row.consumed_at) {
    return NextResponse.json({ error: "token already used" }, { status: 400 });
  }
  if (new Date(row.expires_at).getTime() < Date.now()) {
    return NextResponse.json({ error: "token expired" }, { status: 400 });
  }

  const user = await findUserById(row.user_id);
  if (!user) {
    return NextResponse.json({ error: "account not found" }, { status: 404 });
  }

  const hash = await bcrypt.hash(parsed.data.new_password, 12);
  await updateUserPasswordHash(user.id, hash);

  // Reset always nukes every active session — if the email was actually
  // compromised, the attacker's tokens die here.
  await revokeLicensesForUser(user.id);
  await consumePasswordReset(row.id);

  await logAdminAction({
    actor_user_id: user.id,
    target_user_id: user.id,
    action: "password.reset_completed",
    payload: { reset_id: row.id },
  });

  return NextResponse.json({ ok: true, email: user.email });
}
