const EMAIL_RE = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/;
const ENVELOPE_RE = /^\s*(?:"([^"]+)"|([^<]*?))\s*<\s*([^>\s]+)\s*>\s*$/;
const FORWARDED_RE = /\.gmail\.com@/i;
const PLACEHOLDER_DOMAINS = /(?:\.fdske\.com|\.example\.com|@noreply|@no-reply)$/i;

export type ParsedIdentity = {
  /** Display name suitable for the row title. Falls back to local-part. */
  name: string;
  /** Email address if one was parsed and looks legitimate. */
  email: string | null;
  /** True when the input was clearly an RFC822 envelope. */
  isEnvelope: boolean;
};

export function parseIdentity(raw: string | null | undefined): ParsedIdentity {
  const input = (raw ?? "").trim();
  if (!input) return { name: "—", email: null, isEnvelope: false };

  const envelopeMatch = input.match(ENVELOPE_RE);
  if (envelopeMatch) {
    const quoted = envelopeMatch[1];
    const bare = envelopeMatch[2];
    const email = envelopeMatch[3] ?? null;
    const rawName = (quoted ?? bare ?? "").trim();
    const email_ = email && EMAIL_RE.test(email) ? email : null;
    const name = rawName.length > 0 ? rawName : email_ ? localPart(email_) : input;
    return {
      name: cleanName(name),
      email: hideJunkEmail(email_),
      isEnvelope: true,
    };
  }

  if (EMAIL_RE.test(input)) {
    return {
      name: cleanName(localPart(input)),
      email: hideJunkEmail(input),
      isEnvelope: true,
    };
  }

  return { name: cleanName(input), email: null, isEnvelope: false };
}

function localPart(email: string): string {
  const at = email.indexOf("@");
  if (at <= 0) return email;
  return email.slice(0, at);
}

function cleanName(name: string): string {
  return name.replace(/^["']+|["']+$/g, "").trim() || "—";
}

function hideJunkEmail(email: string | null): string | null {
  if (!email) return null;
  if (FORWARDED_RE.test(email)) return null;
  if (PLACEHOLDER_DOMAINS.test(email)) return null;
  return email;
}

/**
 * Combine a sourceLabel like "Composio — gmail" with a channel like "gmail".
 * Returns the de-duplicated provenance string for the row's secondary line.
 */
export function provenanceLine(sourceLabel: string, channel: string): string {
  const src = sourceLabel.trim();
  const ch = channel.trim();
  if (!src) return ch;
  if (!ch) return src;
  if (src.toLowerCase().includes(ch.toLowerCase())) return src;
  return `${src} · ${ch}`;
}
