import assert from "node:assert/strict";
import crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  createEntitlementEnvelope,
  ENTITLEMENT_ASSERTION,
  EntitlementSigningConfigurationError,
  loadEntitlementSigner,
} from "../src/lib/entitlement-assertion";

const PRIVATE_KEY_ENV = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64";
const ephemeralKeyPair = crypto.generateKeyPairSync("ed25519");
const EPHEMERAL_PUBLIC_KEY = ephemeralKeyPair.publicKey;
const EPHEMERAL_PRIVATE_KEY_B64 = ephemeralKeyPair.privateKey
  .export({ format: "der", type: "pkcs8" })
  .toString("base64");

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

const golden = JSON.parse(
  readFileSync(new URL("./fixtures/entitlement-assertion-v1.json", import.meta.url), "utf8"),
) as GoldenFixture;

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

function withSigningEnvironment<T>(
  privateKey: string | undefined,
  nodeEnv: string | undefined,
  run: () => T,
): T {
  const previousKey = process.env[PRIVATE_KEY_ENV];
  const previousNodeEnv = process.env.NODE_ENV;
  if (privateKey === undefined) Reflect.deleteProperty(process.env, PRIVATE_KEY_ENV);
  else Reflect.set(process.env, PRIVATE_KEY_ENV, privateKey);
  if (nodeEnv === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
  else Reflect.set(process.env, "NODE_ENV", nodeEnv);
  try {
    return run();
  } finally {
    if (previousKey === undefined) Reflect.deleteProperty(process.env, PRIVATE_KEY_ENV);
    else Reflect.set(process.env, PRIVATE_KEY_ENV, previousKey);
    if (previousNodeEnv === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Reflect.set(process.env, "NODE_ENV", previousNodeEnv);
  }
}

describe("signed entitlement assertions", () => {
  it("matches the deterministic cross-runtime golden fixture", () => {
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

  it("binds exact tokens, normalizes duplicates, and supports empty entitlements", () => {
    const envelope = withSigningEnvironment(
      EPHEMERAL_PRIVATE_KEY_B64,
      "test",
      () =>
        createEntitlementEnvelope(
          {
            access_token: "access-exact\nbytes",
            refresh_token: "refresh-exact\nbytes",
            sub: "user-1",
            license_id: "license-1",
            email: " Agent@Example.COM ",
            tier: "builder",
            entitlements: [],
          },
          loadEntitlementSigner(),
          { nowSeconds: 1000, jti: "jti-1" },
        ),
    );
    const decoded = decodeCompact(envelope.entitlement_assertion);

    assert.deepEqual(decoded.header, golden.header);
    assert.equal(
      crypto.verify(null, decoded.signingInput, EPHEMERAL_PUBLIC_KEY, decoded.signature),
      true,
    );
    assert.equal(envelope.email, "agent@example.com");
    assert.deepEqual(envelope.entitlements, []);
    assert.equal(decoded.payload.email, envelope.email);
    assert.deepEqual(decoded.payload.entitlements, envelope.entitlements);
    assert.equal(decoded.payload.tier, envelope.tier);
    assert.equal(decoded.payload.license_id, envelope.license_id);
    assert.equal(decoded.payload.iat, 1000);
    assert.equal(decoded.payload.nbf, 1000);
    assert.equal(decoded.payload.exp, 4600);
    assert.equal(
      decoded.payload.ath,
      crypto.createHash("sha256").update(envelope.access_token).digest("base64url"),
    );
    assert.equal(
      decoded.payload.rth,
      crypto.createHash("sha256").update(envelope.refresh_token).digest("base64url"),
    );

    withSigningEnvironment(EPHEMERAL_PRIVATE_KEY_B64, "test", () => {
      const signer = loadEntitlementSigner();
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
  });

  it("fails closed when the signer is missing, malformed, wrong-type, or not the production key", () => {
    assert.throws(
      () => withSigningEnvironment(undefined, "test", () => loadEntitlementSigner()),
      (error: unknown) =>
        error instanceof EntitlementSigningConfigurationError &&
        error.message === `${PRIVATE_KEY_ENV} is not set`,
    );
    assert.throws(
      () => withSigningEnvironment("not base64", "test", () => loadEntitlementSigner()),
      EntitlementSigningConfigurationError,
    );

    const { privateKey: rsaPrivateKey } = crypto.generateKeyPairSync("rsa", {
      modulusLength: 2048,
    });
    const rsa = rsaPrivateKey.export({ format: "der", type: "pkcs8" }).toString("base64");
    assert.throws(
      () => withSigningEnvironment(rsa, "test", () => loadEntitlementSigner()),
      /must contain an Ed25519 private key/,
    );
    assert.throws(
      () =>
        withSigningEnvironment(
          EPHEMERAL_PRIVATE_KEY_B64,
          "production",
          () => loadEntitlementSigner(),
        ),
      new RegExp(`does not match entitlement key ${ENTITLEMENT_ASSERTION.KEY_ID}`),
    );
  });
});
