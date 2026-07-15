import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  ENTITLEMENT_ASSERTION_KEYSET_SHA256,
} from "../src/lib/entitlement-assertion";
import {
  DATABASE_SCHEMA_CONTRACT,
  DATABASE_SCHEMA_VERSION,
} from "../src/lib/schema-readiness";
import { verifyEntitlementHealth } from "../scripts/verify-entitlement-health";

const expectedBuildId = "deploy-test-123";

function healthyBody(activeKid = ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS[0]) {
  return {
    ok: true,
    service: "elevate-backend",
    backend_build_id: expectedBuildId,
    entitlement_signer_ready: true,
    entitlement_signing_active_kid: activeKid,
    entitlement_public_keyset_sha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    database_schema_ready: true,
    database_schema_contract: DATABASE_SCHEMA_CONTRACT,
    database_schema_version: DATABASE_SCHEMA_VERSION,
    initial_issuance_v2_ready: true,
  };
}

describe("deployment entitlement health verifier", () => {
  it("accepts every key id compiled into this release", () => {
    for (const activeKid of ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS) {
      assert.deepEqual(
        verifyEntitlementHealth({
          status: 200,
          body: healthyBody(activeKid),
          expectedBuildId,
        }),
        {
          service: "elevate-backend",
          backendBuildId: expectedBuildId,
          activeKid,
          publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
          databaseSchemaContract: DATABASE_SCHEMA_CONTRACT,
          databaseSchemaVersion: DATABASE_SCHEMA_VERSION,
        },
      );
    }
  });

  it("rejects the legacy shallow health response", () => {
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: { ok: true },
          expectedBuildId,
        }),
      /service is not elevate-backend/,
    );
  });

  it("rejects an otherwise-ready old worker with the wrong build id", () => {
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: { ...healthyBody(), backend_build_id: "older-deployment" },
          expectedBuildId,
        }),
      /backend_build_id does not match/,
    );
  });

  it("rejects signer-not-ready, unknown key id, and fingerprint drift", () => {
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: { ...healthyBody(), entitlement_signer_ready: false },
          expectedBuildId,
        }),
      /entitlement_signer_ready/,
    );
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: {
            ...healthyBody(),
            entitlement_signing_active_kid: "unknown-kid",
          },
          expectedBuildId,
        }),
      /active_kid is not accepted/,
    );
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: {
            ...healthyBody(),
            entitlement_public_keyset_sha256: "0".repeat(64),
          },
          expectedBuildId,
        }),
      /keyset_sha256 does not match/,
    );
  });

  it("rejects non-success HTTP status without reflecting response fields", () => {
    const secretMarker = "must-not-be-reflected";
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 503,
          body: { ...healthyBody(), internal_error: secretMarker },
          expectedBuildId,
        }),
      (error: unknown) => {
        assert(error instanceof Error);
        assert.match(error.message, /HTTP 503/);
        assert.equal(error.message.includes(secretMarker), false);
        return true;
      },
    );
  });

  it("rejects missing live schema and initial issuance readiness", () => {
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: { ...healthyBody(), database_schema_ready: false },
          expectedBuildId,
        }),
      /database_schema_ready/,
    );
    assert.throws(
      () =>
        verifyEntitlementHealth({
          status: 200,
          body: { ...healthyBody(), initial_issuance_v2_ready: false },
          expectedBuildId,
        }),
      /initial_issuance_v2_ready/,
    );
  });
});
