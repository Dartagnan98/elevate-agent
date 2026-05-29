// Mailjet transactional email wrapper.
//
// Why fetch instead of node-mailjet: keeps dep tree lean (the SDK pulls in
// request and a pile of legacy deps). The v3.1/send API is a single POST.
//
// Env:
//   MAILJET_API_KEY        public key
//   MAILJET_API_SECRET     private key
//   MAIL_FROM              sender email (must be verified in Mailjet)
//   MAIL_FROM_NAME         sender display name
//   MAIL_REPLY_TO          optional reply-to override
//
// Returns { ok: true } on success, { ok: false, error } on failure. Callers
// decide whether to surface dev fallback links when sending is disabled.

export type MailResult =
  | { ok: true; messageId: string }
  | { ok: false; error: string; disabled?: boolean };

interface SendArgs {
  to: string;
  toName?: string;
  subject: string;
  html: string;
  text?: string;
  replyTo?: string;
}

function basicAuthHeader() {
  const key = process.env.MAILJET_API_KEY;
  const secret = process.env.MAILJET_API_SECRET;
  if (!key || !secret) return null;
  return "Basic " + Buffer.from(`${key}:${secret}`).toString("base64");
}

export function mailerEnabled(): boolean {
  return Boolean(
    process.env.MAILJET_API_KEY &&
      process.env.MAILJET_API_SECRET &&
      process.env.MAIL_FROM,
  );
}

export async function sendMail(args: SendArgs): Promise<MailResult> {
  const auth = basicAuthHeader();
  const from = process.env.MAIL_FROM;
  const fromName = process.env.MAIL_FROM_NAME || "Elevation Real Estate HQ";
  const replyTo = args.replyTo || process.env.MAIL_REPLY_TO;

  if (!auth || !from) {
    return { ok: false, error: "mailer not configured", disabled: true };
  }

  const body = {
    Messages: [
      {
        From: { Email: from, Name: fromName },
        To: [{ Email: args.to, Name: args.toName || args.to }],
        Subject: args.subject,
        HTMLPart: args.html,
        TextPart: args.text || stripHtml(args.html),
        ...(replyTo ? { ReplyTo: { Email: replyTo } } : {}),
      },
    ],
  };

  try {
    const res = await fetch("https://api.mailjet.com/v3.1/send", {
      method: "POST",
      headers: {
        Authorization: auth,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const text = await res.text();
      return { ok: false, error: `mailjet ${res.status}: ${text.slice(0, 500)}` };
    }

    const json = (await res.json()) as {
      Messages?: Array<{ Status: string; To?: Array<{ MessageID?: string }> }>;
    };
    const first = json.Messages?.[0];
    const messageId = String(first?.To?.[0]?.MessageID || "unknown");

    if (first?.Status !== "success") {
      return { ok: false, error: `mailjet status ${first?.Status}` };
    }
    return { ok: true, messageId };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

function stripHtml(html: string): string {
  return html
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+\n/g, "\n")
    .replace(/\n\s+/g, "\n")
    .trim();
}

// --- Templates ---

export function passwordResetEmail(opts: {
  resetUrl: string;
  expiresInMinutes: number;
}): { subject: string; html: string } {
  const minutes = opts.expiresInMinutes;
  const subject = "Reset your password";
  const html = baseTemplate({
    preheader: "Use the link below to set a new password.",
    body: `
      <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;font-weight:600;letter-spacing:-0.02em;color:#FFFFFF;">Reset your password</h1>
      <p style="margin:0 0 26px;font-size:15px;line-height:1.6;color:#C8C8C8;">Someone requested a password reset for your account. If that was you, tap the button below to set a new one.</p>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 26px;"><tr><td bgcolor="#D97757" style="border-radius:8px;">
        <a href="${escapeAttr(opts.resetUrl)}" style="display:inline-block;background:#D97757;color:#FFFFFF;font-weight:600;font-size:15px;padding:13px 30px;border-radius:8px;text-decoration:none;">Reset password</a>
      </td></tr></table>
      <p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#8C8C8C;">This link expires in ${minutes} minutes.</p>
      <p style="margin:0;font-size:13px;line-height:1.5;color:#8C8C8C;">If you didn't request this, you can ignore this email — your password won't change.</p>
    `,
  });
  return { subject, html };
}

export function loginCodeEmail(opts: {
  code: string;
  expiresInMinutes: number;
}): { subject: string; html: string } {
  const minutes = opts.expiresInMinutes;
  const subject = `Your login code: ${opts.code}`;
  const html = baseTemplate({
    preheader: `Your one-time login code is ${opts.code}.`,
    body: `
      <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;font-weight:600;letter-spacing:-0.02em;color:#FFFFFF;">Your sign-in code</h1>
      <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#C8C8C8;">Enter this code to finish signing in:</p>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:0 0 24px;"><tr><td align="center" bgcolor="#0E0E0E" style="background:#0E0E0E;border:1px solid #2C2C2C;border-radius:10px;padding:20px;">
        <span style="font-family:'SF Mono',ui-monospace,Menlo,Consolas,monospace;font-weight:700;font-size:34px;letter-spacing:10px;color:#FFFFFF;">${escapeHtml(opts.code)}</span>
      </td></tr></table>
      <p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#8C8C8C;">This code expires in ${minutes} minutes.</p>
      <p style="margin:0;font-size:13px;line-height:1.5;color:#8C8C8C;">If you didn't try to sign in, you can ignore this email.</p>
    `,
  });
  return { subject, html };
}

export function inviteEmail(opts: {
  inviteUrl: string;
  orgName: string;
  inviterName?: string;
}): { subject: string; html: string } {
  const subject = `You've been invited to ${opts.orgName} on Elevation Real Estate HQ`;
  const inviter = opts.inviterName ? `${escapeHtml(opts.inviterName)} ` : "";
  const html = baseTemplate({
    preheader: `Join ${escapeHtml(opts.orgName)} on Elevation Real Estate HQ.`,
    body: `
      <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;font-weight:600;letter-spacing:-0.02em;color:#FFFFFF;">You've been invited</h1>
      <p style="margin:0 0 26px;font-size:15px;line-height:1.6;color:#C8C8C8;">${inviter}invited you to join <strong style="color:#FFFFFF;">${escapeHtml(opts.orgName)}</strong> on Elevation Real Estate HQ.</p>
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 26px;"><tr><td bgcolor="#D97757" style="border-radius:8px;">
        <a href="${escapeAttr(opts.inviteUrl)}" style="display:inline-block;background:#D97757;color:#FFFFFF;font-weight:600;font-size:15px;padding:13px 30px;border-radius:8px;text-decoration:none;">Accept invitation</a>
      </td></tr></table>
      <p style="margin:0;font-size:13px;line-height:1.5;color:#8C8C8C;">If you weren't expecting this, you can ignore the email.</p>
    `,
  });
  return { subject, html };
}

function baseTemplate(opts: { preheader: string; body: string }): string {
  // Dark graphite shell to match the desktop/web app (#0F0F0F canvas, #1A1A1A
  // card, #2A2A2A borders, #ECECEC text, #8A8A8A brand mark). bgcolor attrs +
  // color-scheme hints help clients honor the dark background; some still force
  // their own light/dark, which is unavoidable in HTML email.
  const logo = "https://api.elevationrealestatehq.com/elevateos-wordmark-dark.png";
  return `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark light"><title>Elevation Real Estate HQ</title></head>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
<span style="display:none;font-size:1px;color:#0A0A0A;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">${escapeHtml(opts.preheader)}</span>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#0A0A0A" style="background:#0A0A0A;">
  <tr><td align="center" style="padding:44px 20px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="520" style="max-width:520px;width:100%;">
      <!-- logo above the card -->
      <tr><td align="center" style="padding:0 0 22px;">
        <img src="${logo}" width="150" alt="Elevation Real Estate HQ" style="display:block;height:26px;width:auto;border:0;outline:none;text-decoration:none;" />
      </td></tr>
      <!-- card -->
      <tr><td bgcolor="#161616" style="background:#161616;border-radius:14px;border:1px solid #262626;box-shadow:0 18px 40px rgba(0,0,0,0.45);">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr><td style="padding:34px 38px 30px;">
            ${opts.body}
          </td></tr>
          <tr><td style="padding:20px 38px;border-top:1px solid #262626;">
            <p style="margin:0;font-size:12px;line-height:1.6;color:#7C7C7C;">
              Sent by <span style="color:#A8A8A8;">Elevation Real Estate HQ</span> ·
              <a href="https://elevationrealestatehq.com" style="color:#A8A8A8;text-decoration:none;">elevationrealestatehq.com</a><br/>
              This is an automated security message — please don't reply.
            </p>
          </td></tr>
        </table>
      </td></tr>
      <tr><td align="center" style="padding:20px 0 0;">
        <p style="margin:0;font-size:11px;color:#5A5A5A;">© Elevation Real Estate HQ</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(s: string): string {
  return escapeHtml(s);
}
