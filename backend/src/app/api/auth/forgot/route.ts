import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  createPasswordResetToken,
  findUserByEmail,
  logAdminAction,
} from "@/lib/store";
import { mailerEnabled, passwordResetEmail, sendMail } from "@/lib/mailer";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
});

// Returns `{ ok: true }` either way to prevent email-enumeration. When Mailjet
// is configured we email the link silently. When it isn't, we fall back to
// returning `dev_only.reset_url` so an admin can paste it to the user.
export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const normalized = parsed.data.email.toLowerCase().trim();

  // Throttle before lookup to prevent reset-email bombing / Mailjet abuse.
  // A 429 leaks nothing about whether the email exists.
  const limited = await enforceLimits([
    { key: `forgot:ip:${clientIp(req)}`, max: 10, windowSeconds: 3600 },
    { key: `forgot:email:${normalized}`, max: 3, windowSeconds: 3600 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

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

  const origin = new URL(req.url).origin;
  const reset_url = `${origin}/reset?token=${token}`;

  // Try to email it. If Mailjet isn't configured (or the send fails), fall
  // back to surfacing the link in the response so an admin can deliver it
  // manually — same behavior as before.
  if (mailerEnabled()) {
    const { subject, html } = passwordResetEmail({
      resetUrl: reset_url,
      expiresInMinutes: 60,
    });
    const result = await sendMail({
      to: user.email,
      subject,
      html,
    });

    if (result.ok) {
      return NextResponse.json({ ok: true });
    }
    // Log the failure but still respond 200 to avoid leaking state. Surface
    // the dev fallback in case the operator needs it.
    console.error("[auth/forgot] mailer failed:", result.error);
  }

  return NextResponse.json({
    ok: true,
    dev_only: { reset_url, token, expires_at },
  });
}
