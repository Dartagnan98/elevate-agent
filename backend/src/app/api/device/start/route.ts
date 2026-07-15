import { NextRequest, NextResponse } from "next/server";
import crypto from "node:crypto";
import { z } from "zod";
import {
  createDeviceGrant,
  DeviceGrantProposalConflictError,
  DeviceGrantUserCodeConflictError,
} from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  device_label: z.string().max(120).optional(),
  proposed_refresh_token_hash: z.string().regex(/^[0-9a-f]{64}$/).optional(),
});

// Unambiguous alphabet (no 0/O, no 1/I/L)
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function generateUserCode(): string {
  const bytes = crypto.randomBytes(8);
  let out = "";
  for (let i = 0; i < 8; i++) {
    out += ALPHABET[bytes[i] % ALPHABET.length];
  }
  return `${out.slice(0, 4)}-${out.slice(4)}`;
}

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
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
