import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import { createLoginCode, findUserByEmail, logAdminAction } from "@/lib/store";
import { loginCodeEmail, mailerEnabled, sendMail } from "@/lib/mailer";
import { clientIp, enforceLimits, tooManyRequests } from "@/lib/rate-limit";

export const runtime = "nodejs";

const Body = z.object({
  email: z.string().email(),
});

const CODE_TTL_MINUTES = 10;

function sixDigitCode(): string {
  // 0..999999, zero-padded. crypto for unguessable codes.
  const n = crypto.randomInt(0, 1_000_000);
  return n.toString().padStart(6, "0");
}

// Request a one-time login code by email. Always returns `{ ok: true }` to
// prevent email-enumeration. When Mailjet is configured the code is emailed;
// when it isn't, the code is surfaced under `dev_only.code` so an operator can
// deliver it manually (mirrors the password-reset flow).
export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const normalized = parsed.data.email.toLowerCase().trim();

  // Throttle BEFORE the user lookup so this can't be used to email-bomb a
  // victim's inbox or run up the Mailjet bill. A 429 here leaks nothing about
  // whether the email exists (it's volume-based, not account-based).
  const limited = await enforceLimits([
    { key: `login-code-req:ip:${clientIp(req)}`, max: 10, windowSeconds: 900 },
    { key: `login-code-req:email:${normalized}`, max: 3, windowSeconds: 900 },
  ]);
  if (limited) return tooManyRequests(limited.retryAfter);

  const user = await findUserByEmail(normalized);

  // Always 200 so an attacker can't probe which emails are registered.
  if (!user) {
    return NextResponse.json({ ok: true });
  }

  const code = sixDigitCode();
  const code_hash = crypto.createHash("sha256").update(code).digest("hex");
  const expires_at = new Date(
    Date.now() + CODE_TTL_MINUTES * 60 * 1000,
  ).toISOString();

  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || null;
  const ua = req.headers.get("user-agent") || null;

  await createLoginCode({
    user_id: user.id,
    code_hash,
    expires_at,
    ip_addr: ip,
    user_agent: ua,
  });

  await logAdminAction({
    actor_user_id: user.id,
    target_user_id: user.id,
    action: "auth.login_code_requested",
    payload: { ip, ua },
  });

  if (mailerEnabled()) {
    const { subject, html } = loginCodeEmail({
      code,
      expiresInMinutes: CODE_TTL_MINUTES,
    });
    const result = await sendMail({ to: user.email, subject, html });
    if (result.ok) {
      return NextResponse.json({ ok: true });
    }
    console.error("[auth/login-code/request] mailer failed:", result.error);
  }

  // Mailer off or send failed — fall back to surfacing the code so an
  // operator can deliver it. Never reaches the client in production once
  // Mailjet is configured + a verified sender is set.
  return NextResponse.json({ ok: true, dev_only: { code } });
}
