import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  createDeviceGrant,
  DeviceGrantProposalConflictError,
  DeviceGrantUserCodeConflictError,
  expireStaleDeviceGrants,
  formatDeviceV3UserCode,
  startDeviceGrantV3,
} from "@/lib/store";
import { publicBaseUrl } from "@/lib/base-url";

export const runtime = "nodejs";

const Body = z
  .object({
    // These keys did not exist in the legacy schema and were therefore
    // stripped as unknown input. Preserve that compatibility boundary: only
    // exact numeric 3 opts into v3; every other value stays on v1/v2.
    protocol_version: z.unknown().optional(),
    device_code: z.unknown().optional(),
    device_label: z.string().max(120).optional(),
    proposed_refresh_token_hash: z.string().regex(/^[0-9a-f]{64}$/).optional(),
  })
  .superRefine((value, context) => {
    const isV3 = value.protocol_version === 3;
    const hasProposal = value.proposed_refresh_token_hash !== undefined;
    if (
      isV3 &&
      (typeof value.device_code !== "string" || !hasProposal)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "device v3 requires protocol, device code, and refresh proposal",
      });
    }
    if (
      isV3 &&
      typeof value.device_code === "string" &&
      !/^[A-Za-z0-9_-]{43}$/.test(value.device_code)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "invalid device code",
        path: ["device_code"],
      });
    }
  });

// Historical v1/v2 alphabet omits 0/O and 1/I but includes L. Preserve it so
// existing Stable flows do not change their user-code space.
const LEGACY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
function generateUserCode(): string {
  const bytes = crypto.randomBytes(8);
  let out = "";
  for (let i = 0; i < 8; i++) {
    out += LEGACY_ALPHABET[bytes[i] % LEGACY_ALPHABET.length];
  }
  return `${out.slice(0, 4)}-${out.slice(4)}`;
}

function generateDeviceV3UserCode(): string {
  return formatDeviceV3UserCode(crypto.randomBytes(8));
}

function isCanonicalDeviceCode(value: string): boolean {
  try {
    const decoded = Buffer.from(value, "base64url");
    return decoded.length === 32 && decoded.toString("base64url") === value;
  } catch {
    return false;
  }
}

function boundedHeader(value: string | null, maxLength: number): string | null {
  return value ? value.slice(0, maxLength) : null;
}

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  if (parsed.data.protocol_version === 3) {
    const deviceCode =
      typeof parsed.data.device_code === "string" ? parsed.data.device_code : "";
    if (!isCanonicalDeviceCode(deviceCode)) {
      return NextResponse.json({ error: "bad request" }, { status: 400 });
    }

    const deviceCodeHash = crypto
      .createHash("sha256")
      .update(deviceCode)
      .digest("hex");
    const expiresAt = new Date(Date.now() + 10 * 60 * 1000);

    try {
      // Preserve the existing start-time orphan cleanup for the v3 path. Run
      // it once before any user-code collision retries.
      await expireStaleDeviceGrants();
    } catch {
      return NextResponse.json(
        { error: "device authorization unavailable" },
        { status: 503 },
      );
    }

    for (let attempts = 0; attempts < 5; attempts += 1) {
      try {
        const result = await startDeviceGrantV3({
          userCode: generateDeviceV3UserCode(),
          deviceCodeHash,
          proposedRefreshTokenHash: parsed.data.proposed_refresh_token_hash!,
          deviceLabel: parsed.data.device_label || null,
          ipAddress: boundedHeader(req.headers.get("x-forwarded-for"), 255),
          userAgent: boundedHeader(req.headers.get("user-agent"), 1024),
          expiresAt,
        });

        if (result.result === "user_code_conflict") continue;
        if (result.result === "conflict") {
          return NextResponse.json(
            { error: "device_start_conflict" },
            { status: 409 },
          );
        }
        if (result.result === "expired") {
          return NextResponse.json({ error: "expired_token" }, { status: 410 });
        }
        if (result.result === "denied") {
          return NextResponse.json(
            { error: "authorization_denied" },
            { status: 403 },
          );
        }
        if (result.result === "resume_poll") {
          return NextResponse.json({
            protocol_version: 3,
            status: "resume_poll",
            grant_status: result.grant_status,
            interval: 5,
          });
        }
        if (result.result !== "created" && result.result !== "replay") {
          return NextResponse.json(
            { error: "device authorization unavailable" },
            { status: 503 },
          );
        }

        const origin = publicBaseUrl();
        const expiresIn = Math.max(
          0,
          Math.ceil((Date.parse(result.expires_at) - Date.now()) / 1000),
        );
        return NextResponse.json({
          protocol_version: 3,
          device_code: deviceCode,
          user_code: result.user_code,
          verification_uri: `${origin}/link`,
          verification_uri_complete: `${origin}/link?code=${result.user_code}`,
          expires_in: expiresIn,
          interval: 5,
        });
      } catch {
        return NextResponse.json(
          { error: "device authorization unavailable" },
          { status: 503 },
        );
      }
    }

    return NextResponse.json(
      { error: "device authorization unavailable" },
      { status: 503 },
    );
  }

  const device_code = crypto.randomBytes(32).toString("base64url");
  const device_code_hash = crypto.createHash("sha256").update(device_code).digest("hex");

  // Retry up to 5x on user_code collision (1-in-trillion odds, but cheap)
  let userCode = "";
  let attempts = 0;
  while (attempts < 5) {
    userCode = generateUserCode();
    try {
      await createDeviceGrant({
        user_code: userCode,
        device_code_hash,
        proposed_refresh_token_hash:
          parsed.data.proposed_refresh_token_hash ?? null,
        device_label: parsed.data.device_label || null,
        ip_addr: req.headers.get("x-forwarded-for") || null,
        user_agent: req.headers.get("user-agent") || null,
        expires_at: new Date(Date.now() + 10 * 60 * 1000), // 10 min
      });
      break;
    } catch (e: unknown) {
      if (e instanceof DeviceGrantProposalConflictError) {
        return NextResponse.json(
          { error: "refresh_token_proposal_conflict" },
          { status: 409 },
        );
      }
      if (e instanceof DeviceGrantUserCodeConflictError) {
        attempts += 1;
        continue;
      }
      return NextResponse.json(
        { error: "device authorization unavailable" },
        { status: 503 },
      );
    }
  }

  if (!userCode || attempts >= 5) {
    return NextResponse.json(
      { error: "device authorization unavailable" },
      { status: 503 },
    );
  }

  const origin = req.headers.get("origin") || new URL(req.url).origin;

  return NextResponse.json({
    device_code,
    user_code: userCode,
    verification_uri: `${origin}/link`,
    verification_uri_complete: `${origin}/link?code=${userCode}`,
    expires_in: 600,
    interval: 5,
    ...(parsed.data.proposed_refresh_token_hash
      ? { protocol_version: 2 }
      : {}),
  });
}
