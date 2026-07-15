const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  ENTITLEMENT_ASSERTION,
  ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  ENTITLEMENT_ASSERTION_KEYSET_SHA256,
  ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
  EntitlementAssertionError,
  entitlementAssertionKeysetSha256,
  loadPinnedKeyset,
  productionKeyset,
  tokenHash,
  verifyEntitlementAssertion,
} = require("../src/entitlement-assertion");
const { BETA } = require("../src/release-profile");

const NOW = 1_800_000_000;

function testSigner() {
  return crypto.generateKeyPairSync("ed25519");
}

function signedAssertion({
  privateKey,
  accessToken = "access-token",
  refreshToken = "refresh-token",
  header = {},
  protectedHeaderJson = null,
  claims = {},
}) {
  const protectedHeader = {
    alg: ENTITLEMENT_ASSERTION.algorithm,
    typ: ENTITLEMENT_ASSERTION.type,
    kid: ENTITLEMENT_ASSERTION.keyId,
    ...header,
  };
  const payload = {
    iss: ENTITLEMENT_ASSERTION.issuer,
    aud: ENTITLEMENT_ASSERTION.audience,
    schema: ENTITLEMENT_ASSERTION.schema,
    sub: "user-1",
    license_id: "license-1",
    email: "agent@example.test",
    tier: "pro",
    entitlements: ["real_estate_admin", "real_estate_sales"],
    iat: NOW,
    nbf: NOW,
    exp: NOW + 3600,
    jti: "11111111-2222-4333-8444-555555555555",
    ath: tokenHash(accessToken),
    rth: tokenHash(refreshToken),
    ...claims,
  };
  const first = Buffer.from(
    protectedHeaderJson === null
      ? JSON.stringify(protectedHeader)
      : protectedHeaderJson,
  ).toString("base64url");
  const second = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const input = `${first}.${second}`;
  const signature = crypto.sign(null, Buffer.from(input, "ascii"), privateKey);
  return `${input}.${signature.toString("base64url")}`;
}

function verify(assertion, publicKey, overrides = {}) {
  return verifyEntitlementAssertion({
    assertion,
    accessToken: "access-token",
    refreshToken: "refresh-token",
    keyset: { [ENTITLEMENT_ASSERTION.keyId]: publicKey },
    nowSeconds: NOW + 10,
    ...overrides,
  });
}

test("desktop accepts the shared cross-runtime golden assertion", () => {
  const fixture = JSON.parse(
    fs.readFileSync(
      path.resolve(
        __dirname,
        "../../backend/test/fixtures/entitlement-assertion-v1.json",
      ),
      "utf8",
    ),
  );
  const publicKey = crypto.createPublicKey({
    key: Buffer.from(fixture.test_public_key_spki_der_b64, "base64"),
    format: "der",
    type: "spki",
  });

  const claims = verifyEntitlementAssertion({
    assertion: fixture.compact_jws,
    accessToken: fixture.access_token,
    refreshToken: fixture.refresh_token,
    keyset: { [ENTITLEMENT_ASSERTION.keyId]: publicKey },
    nowSeconds: fixture.payload.iat + 10,
  });

  assert.equal(claims.license_id, fixture.payload.license_id);
  assert.deepEqual([...claims.entitlements], fixture.payload.entitlements);
  assert.equal(claims.ath, fixture.payload.ath);
  assert.equal(claims.rth, fixture.payload.rth);
});

test("desktop production key ring matches the cross-runtime fixture", () => {
  const fixture = JSON.parse(
    fs.readFileSync(
      path.resolve(
        __dirname,
        "../../cli/tests/fixtures/entitlement-keyset-v1.json",
      ),
      "utf8",
    ),
  );

  assert.deepEqual(
    [...ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS],
    fixture.accepted_key_ids,
  );
  assert.deepEqual(
    ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
    fixture.public_keys_spki_der_b64,
  );
  assert.equal(ENTITLEMENT_ASSERTION_KEYSET_SHA256, fixture.keyset_sha256);
  assert.deepEqual(
    [...BETA.entitlementAssertionAcceptedKeyIds],
    fixture.accepted_key_ids,
  );
  assert.equal(BETA.entitlementAssertionKeysetSha256, fixture.keyset_sha256);
  assert.equal(
    entitlementAssertionKeysetSha256(ENTITLEMENT_ASSERTION_PUBLIC_KEYS),
    fixture.keyset_sha256,
  );
  assert.equal(
    crypto.createHash("sha256")
      .update(Buffer.from(ENTITLEMENT_ASSERTION_PUBLIC_KEYS["ent-2026-07-b"], "base64"))
      .digest("hex"),
    fixture.future_key_public_spki_sha256,
  );
  const keyset = productionKeyset();
  assert.deepEqual(Object.keys(keyset), fixture.accepted_key_ids);
  assert.ok(Object.values(keyset).every((key) => key.asymmetricKeyType === "ed25519"));
});

test("desktop pinned key-ring loader rejects malformed and non-Ed25519 SPKI", () => {
  const kid = "ent-test-rsa";
  const { publicKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const rsaSpki = publicKey.export({ format: "der", type: "spki" }).toString("base64");
  const rsaRing = { [kid]: rsaSpki };

  assert.throws(
    () => loadPinnedKeyset(
      rsaRing,
      [kid],
      entitlementAssertionKeysetSha256(rsaRing),
    ),
    (error) =>
      error instanceof EntitlementAssertionError &&
      error.code === "beta_entitlement_assertion_key_invalid",
  );
  assert.throws(
    () => loadPinnedKeyset({ [kid]: "not-base64" }, [kid], "0".repeat(64)),
    (error) =>
      error instanceof EntitlementAssertionError &&
      error.code === "beta_entitlement_assertion_key_invalid",
  );
});

test("desktop verifies Ed25519 claims and both token bindings", () => {
  const { privateKey, publicKey } = testSigner();
  const assertion = signedAssertion({ privateKey });

  const claims = verify(assertion, publicKey);

  assert.equal(claims.sub, "user-1");
  assert.equal(claims.email, "agent@example.test");
  assert.deepEqual([...claims.entitlements], [
    "real_estate_admin",
    "real_estate_sales",
  ]);
});

test("desktop rejects assertion algorithm confusion and unknown key ids", () => {
  const { privateKey, publicKey } = testSigner();

  for (const header of [
    { alg: "none" },
    { alg: "HS256" },
    { typ: "JWT" },
    { crit: ["attacker"] },
    { extra: "unsupported" },
  ]) {
    assert.throws(
      () => verify(signedAssertion({ privateKey, header }), publicKey),
      (error) =>
        error instanceof EntitlementAssertionError &&
        error.code === "beta_entitlement_assertion_header_invalid",
    );
  }

  assert.throws(
    () => verify(signedAssertion({ privateKey, header: { kid: "attacker-key" } }), publicKey),
    (error) =>
      error instanceof EntitlementAssertionError &&
      error.code === "beta_entitlement_assertion_key_unknown",
  );
});

test("desktop routes both trusted kids and rejects cross-key signatures", () => {
  const signerA = testSigner();
  const signerB = testSigner();
  const kidB = ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS[1];
  const keyset = {
    [ENTITLEMENT_ASSERTION.keyId]: signerA.publicKey,
    [kidB]: signerB.publicKey,
  };
  const assertionB = signedAssertion({
    privateKey: signerB.privateKey,
    header: { kid: kidB },
  });

  assert.equal(verifyEntitlementAssertion({
    assertion: assertionB,
    accessToken: "access-token",
    refreshToken: "refresh-token",
    keyset,
    nowSeconds: NOW + 10,
  }).license_id, "license-1");

  const expiredB = signedAssertion({
    privateKey: signerB.privateKey,
    header: { kid: kidB },
    claims: { iat: NOW - 7200, nbf: NOW - 7200, exp: NOW - 3600 },
  });
  assert.equal(verifyEntitlementAssertion({
    assertion: expiredB,
    accessToken: "access-token",
    refreshToken: "refresh-token",
    keyset,
    nowSeconds: NOW,
    requireCurrent: false,
  }).exp, NOW - 3600);

  const mislabeled = signedAssertion({
    privateKey: signerA.privateKey,
    header: { kid: kidB },
  });
  assert.throws(
    () => verifyEntitlementAssertion({
      assertion: mislabeled,
      accessToken: "access-token",
      refreshToken: "refresh-token",
      keyset,
      nowSeconds: NOW + 10,
    }),
    (error) =>
      error instanceof EntitlementAssertionError &&
      error.code === "beta_entitlement_assertion_signature_invalid",
  );
});

test("desktop rejects duplicate JSON keys and malformed UTF-8 before verification", () => {
  const { privateKey, publicKey } = testSigner();
  const escapedDuplicate = Buffer.from(
    '{"alg":"EdDSA","typ":"elevate-entitlement+jwt",' +
      '"kid":"ent-2026-07-a","k\\u0069d":"ent-2026-07-b"}',
    "utf8",
  );
  const nestedDuplicate = Buffer.from(
    '{"alg":"EdDSA","typ":"elevate-entitlement+jwt",' +
      '"kid":"ent-2026-07-a","extra":{"x":1,"x":2}}',
    "utf8",
  );
  const malformedUtf8 = Buffer.concat([
    Buffer.from('{"alg":"EdDSA","typ":"elevate-entitlement+jwt","kid":"'),
    Buffer.from([0xc3, 0x28]),
    Buffer.from('"}'),
  ]);

  for (const protectedHeaderJson of [
    escapedDuplicate,
    nestedDuplicate,
    malformedUtf8,
  ]) {
    assert.throws(
      () => verify(signedAssertion({ privateKey, protectedHeaderJson }), publicKey),
      (error) =>
        error instanceof EntitlementAssertionError &&
        error.code === "beta_entitlement_assertion_invalid",
    );
  }
});

test("desktop rejects bad signatures, claim drift, and noncanonical grants", () => {
  const signer = testSigner();
  const attacker = testSigner();
  const cases = [
    signedAssertion({ privateKey: attacker.privateKey }),
    signedAssertion({ privateKey: signer.privateKey, claims: { iss: "https://attacker.test" } }),
    signedAssertion({ privateKey: signer.privateKey, claims: { aud: "other-app" } }),
    signedAssertion({ privateKey: signer.privateKey, claims: { schema: 2 } }),
    signedAssertion({ privateKey: signer.privateKey, claims: { extra: "unsupported" } }),
    signedAssertion({ privateKey: signer.privateKey, claims: { email: "Agent@Example.test" } }),
    signedAssertion({
      privateKey: signer.privateKey,
      claims: { entitlements: ["real_estate_sales", "real_estate_admin"] },
    }),
    signedAssertion({
      privateKey: signer.privateKey,
      claims: { entitlements: ["real_estate_admin", "real_estate_admin"] },
    }),
  ];

  for (const assertion of cases) {
    assert.throws(
      () => verify(assertion, signer.publicKey),
      EntitlementAssertionError,
    );
  }
});

test("desktop rejects expired, future, overlong, and mixed-token assertions", () => {
  const { privateKey, publicKey } = testSigner();
  const expired = signedAssertion({
    privateKey,
    claims: { iat: NOW - 7200, nbf: NOW - 7200, exp: NOW - 3600 },
  });
  const future = signedAssertion({
    privateKey,
    claims: { iat: NOW + 120, nbf: NOW + 120, exp: NOW + 3720 },
  });
  const overlong = signedAssertion({
    privateKey,
    claims: { exp: NOW + 7200 },
  });
  const mixed = signedAssertion({
    privateKey,
    refreshToken: "different-refresh",
  });

  assert.throws(() => verify(expired, publicKey), /expired/i);
  assert.throws(() => verify(future, publicKey), /not yet valid/i);
  assert.throws(() => verify(overlong, publicKey), /validity window/i);
  assert.throws(() => verify(mixed, publicKey), /does not match/i);

  const historical = verifyEntitlementAssertion({
    assertion: expired,
    accessToken: "access-token",
    refreshToken: "refresh-token",
    keyset: { [ENTITLEMENT_ASSERTION.keyId]: publicKey },
    nowSeconds: NOW,
    requireCurrent: false,
  });
  assert.equal(historical.exp, NOW - 3600);
});
