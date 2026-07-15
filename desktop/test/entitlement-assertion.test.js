const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  ENTITLEMENT_ASSERTION,
  EntitlementAssertionError,
  tokenHash,
  verifyEntitlementAssertion,
} = require("../src/entitlement-assertion");

const NOW = 1_800_000_000;

function testSigner() {
  return crypto.generateKeyPairSync("ed25519");
}

function signedAssertion({
  privateKey,
  accessToken = "access-token",
  refreshToken = "refresh-token",
  header = {},
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
  const first = Buffer.from(JSON.stringify(protectedHeader)).toString("base64url");
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
    { kid: "attacker-key" },
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
