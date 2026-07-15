import { NextResponse } from "next/server";
import { entitlementSignerReadiness } from "@/lib/entitlement-assertion";

export const runtime = "nodejs";

export async function GET() {
  const signer = entitlementSignerReadiness();
  return NextResponse.json(
    {
      ok: signer.ready,
      service: "elevate-backend",
      entitlement_signer_ready: signer.ready,
      entitlement_signing_active_kid: signer.activeKid,
      entitlement_public_keyset_sha256: signer.publicKeysetSha256,
    },
    { status: signer.ready ? 200 : 503 },
  );
}
