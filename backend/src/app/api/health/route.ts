import { NextResponse } from "next/server";
import { entitlementSignerReadiness } from "@/lib/entitlement-assertion";
import {
  DATABASE_SCHEMA_CONTRACT,
  DATABASE_SCHEMA_VERSION,
  cachedDatabaseSchemaReadiness,
} from "@/lib/schema-readiness";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const signer = entitlementSignerReadiness();
  const schema = await cachedDatabaseSchemaReadiness();
  const ready = signer.ready && schema.ready;
  return NextResponse.json(
    {
      ok: ready,
      service: "elevate-backend",
      backend_build_id: process.env.ELEVATE_BACKEND_BUILD_ID || "development",
      entitlement_signer_ready: signer.ready,
      entitlement_signing_active_kid: signer.activeKid,
      entitlement_signing_configuration_mode: signer.configurationMode,
      entitlement_signing_complete_key_ring_ready: signer.completeKeyRingReady,
      entitlement_public_keyset_sha256: signer.publicKeysetSha256,
      database_schema_ready: schema.ready,
      database_schema_contract: DATABASE_SCHEMA_CONTRACT,
      database_schema_version: DATABASE_SCHEMA_VERSION,
      initial_issuance_v2_ready: schema.initialIssuanceV2Ready,
    },
    { status: ready ? 200 : 503 },
  );
}
