import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import {
  effectiveAccess,
  findActiveUser,
  findLicenseByRefreshHash,
  revokeLicense,
  rotateLicenseRefreshV2,
  rotateLicenseRefreshToken,
} from "@/lib/store";
import {
  signAccessToken,
  generateRefreshToken,
  hashRefreshToken,
} from "@/lib/jwt";
import {
  createEntitlementEnvelope,
  tryLoadEntitlementSigner,
} from "@/lib/entitlement-assertion";

export const runtime = "nodejs";

function isCanonical32ByteBase64Url(value: string): boolean {
  if (!/^[A-Za-z0-9_-]{43}$/.test(value)) return false;
  const decoded = Buffer.from(value, "base64url");
  return decoded.length === 32 && decoded.toString("base64url") === value;
}

const ClientNonce = z.string().refine(isCanonical32ByteBase64Url);

const Body = z
  .object({
    refresh_token: z.string().min(1),
    next_refresh_token: ClientNonce.optional(),
    refresh_attempt_id: ClientNonce.optional(),
  })
  .superRefine((value, context) => {
    const hasSuccessor = value.next_refresh_token !== undefined;
    const hasAttempt = value.refresh_attempt_id !== undefined;
    if (hasSuccessor !== hasAttempt) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "refresh v2 fields must appear together",
      });
    }
    if (hasSuccessor && value.next_refresh_token === value.refresh_token) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "refresh successor must be new",
        path: ["next_refresh_token"],
      });
    }
  });

type RefreshBody = z.infer<typeof Body>;

export async function POST(req: NextRequest) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: "bad request" }, { status: 400 });

  if (
    parsed.data.next_refresh_token !== undefined &&
    parsed.data.refresh_attempt_id !== undefined
  ) {
    return refreshV2(parsed.data as RefreshBody & {
      next_refresh_token: string;
      refresh_attempt_id: string;
    });
  }

  return refreshV1(parsed.data.refresh_token);
}

async function refreshV1(refreshToken: string) {
  const oldHash = hashRefreshToken(refreshToken);
  const license = await findLicenseByRefreshHash(oldHash);

  if (!license || license.revoked) {
    return NextResponse.json({ error: "invalid or revoked refresh token" }, { status: 401 });
  }

  const familyExpiresAt = Date.parse(license.refresh_family_expires_at);
  if (!Number.isFinite(familyExpiresAt) || Date.now() >= familyExpiresAt) {
    await revokeLicense(license.id);
    return NextResponse.json({ error: "invalid or revoked refresh token" }, { status: 401 });
  }

  const active = await findActiveUser(license.user_id);

  if (!active) {
    await revokeLicense(license.id);
    return NextResponse.json({ error: "subscription inactive" }, { status: 402 });
  }

  const access_info = await effectiveAccess(license.user_id);
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  const next = generateRefreshToken();
  const access = await signAccessToken({
    sub: license.user_id,
    email: active.email,
    tier: access_info.tier,
    license_id: license.id,
  });
  const envelope = createEntitlementEnvelope({
    access_token: access,
    refresh_token: next.token,
    sub: license.user_id,
    license_id: license.id,
    email: active.email,
    tier: access_info.tier,
    entitlements: access_info.entitlements,
  }, entitlementSigner);

  // Rotate only after both tokens and their binding assertion exist. If signer
  // configuration is broken, the caller's current refresh remains usable.
  const rotated = await rotateLicenseRefreshToken(license.id, oldHash, next.hash);
  if (!rotated) {
    // Another request already consumed this refresh token. Never return the
    // credentials we prepared for the losing request.
    return NextResponse.json({ error: "invalid or revoked refresh token" }, { status: 401 });
  }

  return NextResponse.json({
    ...envelope,
    orgs: access_info.orgs,
  });
}

async function refreshV2(
  body: RefreshBody & { next_refresh_token: string; refresh_attempt_id: string },
) {
  // Resolve signer configuration before the transactional mutation. After a
  // successful RPC, any later 5xx is recoverable by replaying the exact A/B/I.
  const entitlementSigner = tryLoadEntitlementSigner();
  if (!entitlementSigner) {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }

  let rotation: Awaited<ReturnType<typeof rotateLicenseRefreshV2>>;
  try {
    rotation = await rotateLicenseRefreshV2({
      currentRefreshTokenHash: hashRefreshToken(body.refresh_token),
      nextRefreshTokenHash: hashRefreshToken(body.next_refresh_token),
      refreshAttemptHash: hashRefreshToken(body.refresh_attempt_id),
    });
  } catch {
    return NextResponse.json({ error: "license refresh unavailable" }, { status: 503 });
  }

  if (rotation.result === "inactive") {
    return NextResponse.json({ error: "subscription inactive" }, { status: 402 });
  }
  if (rotation.result !== "rotated" && rotation.result !== "replay") {
    return NextResponse.json(
      { error: "invalid or revoked refresh token" },
      { status: 401 },
    );
  }

  try {
    const access_info = await effectiveAccess(rotation.user_id);
    const access = await signAccessToken({
      sub: rotation.user_id,
      email: rotation.email,
      tier: access_info.tier,
      license_id: rotation.license_id,
    });
    const envelope = createEntitlementEnvelope(
      {
        access_token: access,
        refresh_token: body.next_refresh_token,
        sub: rotation.user_id,
        license_id: rotation.license_id,
        email: rotation.email,
        tier: access_info.tier,
        entitlements: access_info.entitlements,
      },
      entitlementSigner,
    );
    return NextResponse.json({
      ...envelope,
      orgs: access_info.orgs,
    });
  } catch {
    return NextResponse.json({ error: "license issuance unavailable" }, { status: 503 });
  }
}
