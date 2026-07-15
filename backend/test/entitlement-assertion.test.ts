import assert from "node:assert/strict";
import crypto, { type KeyObject } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  createEntitlementEnvelope,
  ENTITLEMENT_ASSERTION,
  ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  ENTITLEMENT_ASSERTION_KEYSET_SHA256,
  ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
  entitlementAssertionKeysetSha256,
  EntitlementSigningConfigurationError,
  entitlementSignerReadiness,
  loadEntitlementSigner,
  type EntitlementSigningEnvironment,
} from "../src/lib/entitlement-assertion";

const LEGACY_PRIVATE_KEY_ENV = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64";
const ACTIVE_KID_ENV = "ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID";
const PRIVATE_KEY_RING_ENV = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON";
const KEY_A = "ent-2026-07-a";
const KEY_B = "ent-2026-07-b";

function generatePrivateKey(): { privateKey: KeyObject; privateKeyB64: string } {
  const { privateKey } = crypto.generateKeyPairSync("ed25519");
  return {
    privateKey,
    privateKeyB64: privateKey.export({ format: "der", type: "pkcs8" }).toString("base64"),
  };
}

const signingA = generatePrivateKey();
const signingB = generatePrivateKey();

type GoldenFixture = {
  fixture: string;
  environment: string;
  header: Record<string, unknown>;
  test_public_key_spki_der_b64: string;
  production_public_key_spki_der_b64: string;
  access_token: string;
  refresh_token: string;
  payload: Record<string, unknown>;
  compact_jws: string;
};

type KeysetFixture = {
  schema: number;
  accepted_key_ids: string[];
  public_keys_spki_der_b64: Record<string, string>;
  keyset_sha256: string;
  future_key_public_spki_sha256: string;
};

const golden = JSON.parse(
  readFileSync(new URL("./fixtures/entitlement-assertion-v1.json", import.meta.url), "utf8"),
) as GoldenFixture;

// This is the same fixture consumed by the Python verifier tests. Reading it
// directly prevents backend fingerprint expectations from drifting into a
// second, independently maintained copy.
const keysetFixture = JSON.parse(
  readFileSync(
    new URL("../../cli/tests/fixtures/entitlement-keyset-v1.json", import.meta.url),
    "utf8",
  ),
) as KeysetFixture;

function legacyEnvironment(
  privateKeyB64: string | undefined,
  nodeEnv = "test",
): EntitlementSigningEnvironment {
  return {
    NODE_ENV: nodeEnv,
    [LEGACY_PRIVATE_KEY_ENV]: privateKeyB64,
  };
}

function ringEnvironment(
  activeKeyId: string,
  values: Record<string, string> = {
    [KEY_A]: signingA.privateKeyB64,
    [KEY_B]: signingB.privateKeyB64,
  },
  extra: EntitlementSigningEnvironment = {},
): EntitlementSigningEnvironment {
  return {
    NODE_ENV: "test",
    [ACTIVE_KID_ENV]: activeKeyId,
    [PRIVATE_KEY_RING_ENV]: JSON.stringify(values),
    ...extra,
  };
}

function decodeCompact(jws: string): {
  header: Record<string, unknown>;
  payload: Record<string, unknown>;
  signingInput: Buffer;
  signature: Buffer;
} {
  const segments = jws.split(".");
  assert.equal(segments.length, 3);
  return {
    header: JSON.parse(Buffer.from(segments[0], "base64url").toString("utf8")),
    payload: JSON.parse(Buffer.from(segments[1], "base64url").toString("utf8")),
    signingInput: Buffer.from(`${segments[0]}.${segments[1]}`, "ascii"),
    signature: Buffer.from(segments[2], "base64url"),
  };
}

function envelopeWith(environment: EntitlementSigningEnvironment) {
  return createEntitlementEnvelope(
    {
      access_token: "access-exact\nbytes",
      refresh_token: "refresh-exact\nbytes",
      sub: "user-1",
      license_id: "license-1",
      email: " Agent@Example.COM ",
      tier: "builder",
      entitlements: [],
    },
    loadEntitlementSigner(environment),
    { nowSeconds: 1000, jti: "jti-1" },
  );
}

function assertSignedBy(
  compact: string,
  keyId: string,
  privateKey: KeyObject,
): ReturnType<typeof decodeCompact> {
  const decoded = decodeCompact(compact);
  assert.deepEqual(decoded.header, {
    alg: "EdDSA",
    typ: "elevate-entitlement+jwt",
    kid: keyId,
  });
  assert.equal(
    crypto.verify(
      null,
      decoded.signingInput,
      crypto.createPublicKey(privateKey),
      decoded.signature,
    ),
    true,
  );
  return decoded;
}

function assertConfigurationFailure(
  environment: EntitlementSigningEnvironment,
  expected?: RegExp,
): EntitlementSigningConfigurationError {
  let failure: unknown;
  try {
    loadEntitlementSigner(environment);
  } catch (error) {
    failure = error;
  }
  assert.ok(failure instanceof EntitlementSigningConfigurationError);
  if (expected) assert.match(failure.message, expected);
  for (const secret of [signingA.privateKeyB64, signingB.privateKeyB64]) {
    assert.equal(failure.message.includes(secret), false);
  }
  return failure;
}

describe("signed entitlement assertions", () => {
  it("matches the deterministic assertion golden fixture", () => {
    assert.equal(
      golden.production_public_key_spki_der_b64,
      ENTITLEMENT_ASSERTION.PRODUCTION_PUBLIC_KEY_SPKI_DER_B64,
    );

    const decoded = decodeCompact(golden.compact_jws);
    assert.deepEqual(decoded.header, golden.header);
    assert.deepEqual(decoded.payload, golden.payload);
    assert.equal(
      decoded.payload.ath,
      crypto.createHash("sha256").update(golden.access_token).digest("base64url"),
    );
    assert.equal(
      decoded.payload.rth,
      crypto.createHash("sha256").update(golden.refresh_token).digest("base64url"),
    );
    const publicKey = crypto.createPublicKey({
      key: Buffer.from(golden.test_public_key_spki_der_b64, "base64"),
      format: "der",
      type: "spki",
    });
    assert.equal(crypto.verify(null, decoded.signingInput, publicKey, decoded.signature), true);
  });

  it("matches the shared Python/Desktop A+B keyset fixture and fingerprint", () => {
    assert.equal(keysetFixture.schema, 1);
    assert.deepEqual(
      [...ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS],
      keysetFixture.accepted_key_ids,
    );
    assert.deepEqual(
      ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
      keysetFixture.public_keys_spki_der_b64,
    );
    assert.equal(ENTITLEMENT_ASSERTION_KEYSET_SHA256, keysetFixture.keyset_sha256);
    assert.equal(entitlementAssertionKeysetSha256(), keysetFixture.keyset_sha256);
    assert.equal(
      crypto
        .createHash("sha256")
        .update(Buffer.from(ENTITLEMENT_ASSERTION_PUBLIC_KEYS[KEY_B], "base64"))
        .digest("hex"),
      keysetFixture.future_key_public_spki_sha256,
    );
  });

  it("keeps the legacy signer on A when both ring variables are absent", () => {
    const signer = loadEntitlementSigner(legacyEnvironment(signingA.privateKeyB64));
    assert.equal(signer.keyId, KEY_A);
    const envelope = envelopeWith(legacyEnvironment(signingA.privateKeyB64));
    const decoded = assertSignedBy(envelope.entitlement_assertion, KEY_A, signingA.privateKey);

    assert.equal(envelope.email, "agent@example.com");
    assert.deepEqual(envelope.entitlements, []);
    assert.equal(decoded.payload.email, envelope.email);
    assert.equal(decoded.payload.iat, 1000);
    assert.equal(decoded.payload.nbf, 1000);
    assert.equal(decoded.payload.exp, 4600);
  });

  it("selects A or B from a complete ring and signs with only that private key", () => {
    for (const [keyId, key] of [
      [KEY_A, signingA],
      [KEY_B, signingB],
    ] as const) {
      const signer = loadEntitlementSigner(ringEnvironment(keyId));
      assert.equal(signer.keyId, keyId);
      const envelope = envelopeWith(ringEnvironment(keyId));
      assertSignedBy(envelope.entitlement_assertion, keyId, key.privateKey);
    }
  });

  it("normalizes entitlement names without changing the selected signer", () => {
    const signer = loadEntitlementSigner(ringEnvironment(KEY_B));
    const normalized = createEntitlementEnvelope(
      {
        access_token: "access",
        refresh_token: "refresh",
        sub: "user-1",
        license_id: "license-1",
        email: "agent@example.com",
        tier: "pro",
        entitlements: [" real_estate_sales ", "real_estate_admin", "real_estate_sales"],
      },
      signer,
    );
    assert.deepEqual(normalized.entitlements, ["real_estate_admin", "real_estate_sales"]);
    assertSignedBy(normalized.entitlement_assertion, KEY_B, signingB.privateKey);
    assert.throws(
      () =>
        createEntitlementEnvelope(
          {
            access_token: "access",
            refresh_token: "refresh",
            sub: "user-1",
            license_id: "license-1",
            email: "agent@example.com",
            tier: "pro",
            entitlements: ["   "],
          },
          signer,
        ),
      /must not contain empty names/,
    );
  });

  it("never falls back to legacy when either new variable is present", () => {
    const validLegacy = { [LEGACY_PRIVATE_KEY_ENV]: signingA.privateKeyB64, NODE_ENV: "test" };
    assertConfigurationFailure(
      { ...validLegacy, [ACTIVE_KID_ENV]: KEY_A },
      /must be configured together/,
    );
    assertConfigurationFailure(
      {
        ...validLegacy,
        [PRIVATE_KEY_RING_ENV]: JSON.stringify({
          [KEY_A]: signingA.privateKeyB64,
          [KEY_B]: signingB.privateKeyB64,
        }),
      },
      /must be configured together/,
    );
    assertConfigurationFailure(
      {
        ...validLegacy,
        [ACTIVE_KID_ENV]: KEY_A,
        [PRIVATE_KEY_RING_ENV]: "not-json",
      },
      /must be a JSON object/,
    );
    assertConfigurationFailure(
      {
        ...validLegacy,
        [ACTIVE_KID_ENV]: KEY_A,
        [PRIVATE_KEY_RING_ENV]: `\u00a0${JSON.stringify({
          [KEY_A]: signingA.privateKeyB64,
          [KEY_B]: signingB.privateKeyB64,
        })}`,
      },
      /must be a JSON object/,
    );
  });

  it("strictly rejects duplicate, partial, and unknown ring keys", () => {
    const duplicate = `{"${KEY_A}":"${signingA.privateKeyB64}","${KEY_A}":"${signingA.privateKeyB64}","${KEY_B}":"${signingB.privateKeyB64}"}`;
    assertConfigurationFailure(
      {
        NODE_ENV: "test",
        [ACTIVE_KID_ENV]: KEY_A,
        [PRIVATE_KEY_RING_ENV]: duplicate,
      },
      /duplicate key id/,
    );

    const escapedDuplicate = `{"${KEY_A}":"${signingA.privateKeyB64}","ent-2026-07-\\u0061":"${signingA.privateKeyB64}","${KEY_B}":"${signingB.privateKeyB64}"}`;
    assertConfigurationFailure(
      {
        NODE_ENV: "test",
        [ACTIVE_KID_ENV]: KEY_A,
        [PRIVATE_KEY_RING_ENV]: escapedDuplicate,
      },
      /duplicate key id/,
    );

    const unterminatedAfterComma = `{"${KEY_A}":"${signingA.privateKeyB64}","${KEY_B}":"${signingB.privateKeyB64}",`;
    assertConfigurationFailure(
      {
        NODE_ENV: "test",
        [ACTIVE_KID_ENV]: KEY_A,
        [PRIVATE_KEY_RING_ENV]: unterminatedAfterComma,
      },
      /must be a JSON object/,
    );

    assertConfigurationFailure(
      ringEnvironment(KEY_A, { [KEY_A]: signingA.privateKeyB64 }),
      /missing a compiled entitlement key id/,
    );
    assertConfigurationFailure(
      ringEnvironment(KEY_A, {
        [KEY_A]: signingA.privateKeyB64,
        [KEY_B]: signingB.privateKeyB64,
        "ent-2026-07-c": signingB.privateKeyB64,
      }),
      /unknown key id/,
    );
    assertConfigurationFailure(ringEnvironment("ent-2026-07-c"), /not a compiled/);
  });

  it("rejects malformed, non-Ed25519, and production-mismatched rings", () => {
    assertConfigurationFailure(
      ringEnvironment(KEY_A, {
        [KEY_A]: "not base64",
        [KEY_B]: signingB.privateKeyB64,
      }),
      /canonical padded base64/,
    );

    const { privateKey: rsaPrivateKey } = crypto.generateKeyPairSync("rsa", {
      modulusLength: 2048,
    });
    const rsa = rsaPrivateKey.export({ format: "der", type: "pkcs8" }).toString("base64");
    assertConfigurationFailure(
      ringEnvironment(KEY_A, {
        [KEY_A]: rsa,
        [KEY_B]: signingB.privateKeyB64,
      }),
      /must contain an Ed25519 private key/,
    );

    const nonCanonicalPrivateKey = Buffer.concat([
      Buffer.from(signingA.privateKeyB64, "base64"),
      Buffer.from([0]),
    ]).toString("base64");
    assertConfigurationFailure(
      ringEnvironment(KEY_A, {
        [KEY_A]: nonCanonicalPrivateKey,
        [KEY_B]: signingB.privateKeyB64,
      }),
      /must contain canonical Ed25519 PKCS#8 DER/,
    );

    assertConfigurationFailure(
      ringEnvironment(
        KEY_A,
        {
          [KEY_A]: signingA.privateKeyB64,
          [KEY_B]: signingB.privateKeyB64,
        },
        { NODE_ENV: "production" },
      ),
      /does not match entitlement key/,
    );
    assertConfigurationFailure(
      legacyEnvironment(signingA.privateKeyB64, "production"),
      /does not match entitlement key ent-2026-07-a/,
    );
  });

  it("reports secret-safe readiness with the compiled fingerprint", () => {
    assert.deepEqual(entitlementSignerReadiness(legacyEnvironment(signingA.privateKeyB64)), {
      ready: true,
      activeKid: KEY_A,
      publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    });
    assert.deepEqual(entitlementSignerReadiness(ringEnvironment(KEY_B)), {
      ready: true,
      activeKid: KEY_B,
      publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    });
    assert.deepEqual(
      entitlementSignerReadiness({ NODE_ENV: "test", [ACTIVE_KID_ENV]: KEY_A }),
      {
        ready: false,
        activeKid: KEY_A,
        publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
      },
    );
    assert.deepEqual(
      entitlementSignerReadiness({
        NODE_ENV: "test",
        [ACTIVE_KID_ENV]: "unknown-value-that-must-not-be-reflected",
        [PRIVATE_KEY_RING_ENV]: "{}",
      }),
      {
        ready: false,
        activeKid: null,
        publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
      },
    );
    assert.deepEqual(entitlementSignerReadiness({ NODE_ENV: "test" }), {
      ready: false,
      activeKid: KEY_A,
      publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    });
  });
});
