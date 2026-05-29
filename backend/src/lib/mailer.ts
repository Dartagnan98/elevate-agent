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
  const fromName = process.env.MAIL_FROM_NAME || "Elevate";
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
  const subject = "Reset your Elevate password";
  const html = baseTemplate({
    preheader: "Use the link below to set a new password.",
    body: `
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#ECECEC;">Someone requested a password reset for your Elevate account. If that was you, set a new password using the button below.</p>
      <p style="margin:0 0 24px;">
        <a href="${escapeAttr(opts.resetUrl)}" style="display:inline-block;background:#8A8A8A;color:#0F0F0F;font-weight:600;font-size:15px;padding:12px 22px;border-radius:6px;text-decoration:none;">Reset password</a>
      </p>
      <p style="margin:0 0 8px;font-size:13px;color:#A0A0A0;">Link expires in ${minutes} minutes.</p>
      <p style="margin:0;font-size:13px;color:#A0A0A0;">If you didn't request this, you can ignore this email — your password won't change.</p>
    `,
  });
  return { subject, html };
}

export function loginCodeEmail(opts: {
  code: string;
  expiresInMinutes: number;
}): { subject: string; html: string } {
  const minutes = opts.expiresInMinutes;
  const subject = `Your Elevate login code: ${opts.code}`;
  const html = baseTemplate({
    preheader: "Your one-time login code.",
    body: `
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#ECECEC;">Use this code to sign in to Elevate:</p>
      <p style="margin:0 0 24px;">
        <span style="display:inline-block;background:#0F0F0F;color:#ECECEC;border:1px solid #2A2A2A;font-weight:700;font-size:30px;letter-spacing:8px;padding:14px 24px;border-radius:8px;font-family:monospace;">${escapeHtml(opts.code)}</span>
      </p>
      <p style="margin:0 0 8px;font-size:13px;color:#A0A0A0;">Code expires in ${minutes} minutes.</p>
      <p style="margin:0;font-size:13px;color:#A0A0A0;">If you didn't try to sign in, you can ignore this email.</p>
    `,
  });
  return { subject, html };
}

export function inviteEmail(opts: {
  inviteUrl: string;
  orgName: string;
  inviterName?: string;
}): { subject: string; html: string } {
  const subject = `You've been invited to ${opts.orgName} on Elevate`;
  const inviter = opts.inviterName ? `${escapeHtml(opts.inviterName)} ` : "";
  const html = baseTemplate({
    preheader: `Join ${escapeHtml(opts.orgName)} on Elevate.`,
    body: `
      <p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#1a1b1a;">${inviter}invited you to join <strong>${escapeHtml(opts.orgName)}</strong> on Elevate.</p>
      <p style="margin:0 0 24px;">
        <a href="${escapeAttr(opts.inviteUrl)}" style="display:inline-block;background:#d97757;color:#fff;font-weight:600;font-size:15px;padding:12px 22px;border-radius:6px;text-decoration:none;">Accept invitation</a>
      </p>
      <p style="margin:0;font-size:13px;color:#5a5c5a;">If you weren't expecting this, you can ignore the email.</p>
    `,
  });
  return { subject, html };
}

function baseTemplate(opts: { preheader: string; body: string }): string {
  // Dark graphite shell to match the desktop/web app (#0F0F0F canvas, #1A1A1A
  // card, #2A2A2A borders, #ECECEC text, #8A8A8A brand mark). bgcolor attrs +
  // color-scheme hints help clients honor the dark background; some still force
  // their own light/dark, which is unavoidable in HTML email.
  return `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark light"><title>Elevate</title></head>
<body style="margin:0;padding:0;background:#0F0F0F;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,sans-serif;">
<span style="display:none;font-size:1px;color:#0F0F0F;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">${escapeHtml(opts.preheader)}</span>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#0F0F0F" style="background:#0F0F0F;">
  <tr><td align="center" style="padding:40px 20px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="520" bgcolor="#1A1A1A" style="max-width:520px;background:#1A1A1A;border-radius:12px;border:1px solid #2A2A2A;">
      <tr><td style="padding:28px 32px 8px;">
        <span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:#8A8A8A;vertical-align:middle;margin-right:9px;"></span><span style="font-size:16px;font-weight:600;letter-spacing:-0.01em;color:#ECECEC;vertical-align:middle;">Elevate</span>
      </td></tr>
      <tr><td style="padding:12px 32px 32px;">
        ${opts.body}
      </td></tr>
      <tr><td style="padding:0 32px 24px;border-top:1px solid #2A2A2A;">
        <p style="margin:18px 0 0;font-size:12px;color:#8A8A8A;">Elevation Real Estate HQ · <a href="https://elevationrealestatehq.com" style="color:#8A8A8A;text-decoration:underline;">elevationrealestatehq.com</a></p>
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
