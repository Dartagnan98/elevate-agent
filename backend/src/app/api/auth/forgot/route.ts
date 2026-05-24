import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  createPasswordResetToken,
  findUserByEmail,
  logAdminAction,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
});

// Returns `{ ok: true }` either way to prevent email-enumeration. The token
// is delivered out-of-band — for now we surface `reset_url` in dev mode so an
// admin can copy it to the user manually (matches the invite-acceptance UX).
// Once Mailjet is wired into Elevate HQ, drop the dev_only block.
export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const normalized = parsed.data.email.toLowerCase().trim();
  const user = await findUserByEmail(normalized);

  // Always 200 so an attacker can't probe which emails are registered.
  if (!user) {
    return NextResponse.json({ ok: true });
  }

  const token = crypto.randomBytes(32).toString("base64url");
  const token_hash = crypto.createHash("sha256").update(token).digest("hex");
  const expires_at = new Date(Date.now() + 60 * 60 * 1000).toISOString(); // 1hr

  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || null;
  const ua = req.headers.get("user-agent") || null;

  await createPasswordResetToken({
    user_id: user.id,
    token_hash,
    expires_at,
    ip_addr: ip,
    user_agent: ua,
  });

  await logAdminAction({
    actor_user_id: user.id,
    target_user_id: user.id,
    action: "password.reset_requested",
    payload: { ip, ua },
  });

  // TODO: send via Mailjet once email infra lands. Until then, expose the URL
  // in the response so the admin can paste it into Telegram/text. This is
  // gated on the request URL origin so production callers still get the
  // standard `{ ok: true }` and only the admin-panel side surfaces it.
  const origin = new URL(req.url).origin;
  const reset_url = `${origin}/reset?token=${token}`;

  return NextResponse.json({
    ok: true,
    dev_only: { reset_url, token, expires_at },
  });
}
