"use strict";

const crypto = require("node:crypto");

const ENTITLEMENT_ASSERTION = Object.freeze({
  issuer: "https://api.elevationrealestatehq.com",
  audience: "elevate-realtor-beta",
  schema: 1,
  keyId: "ent-2026-07-a",
  type: "elevate-entitlement+jwt",
  algorithm: "EdDSA",
  productionPublicKeySpkiDerB64:
    "MCowBQYDK2VwAyEAexzoft6MmOXSkKHVJH4hBLgss5LN51wWaQ7bfUom1CQ=",
});

const BASE64URL_RE = /^[A-Za-z0-9_-]+$/;
const TOKEN_HASH_RE = /^[A-Za-z0-9_-]{43}$/;
const HEADER_KEYS = Object.freeze(["alg", "kid", "typ"]);
const CLAIM_KEYS = Object.freeze([
  "ath",
  "aud",
  "email",
  "entitlements",
  "exp",
  "iat",
  "iss",
  "jti",
  "license_id",
  "nbf",
  "rth",
  "schema",
  "sub",
  "tier",
]);

class EntitlementAssertionError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "EntitlementAssertionError";
    this.code = code;
  }
}

function assertionError(code, message) {
  return new EntitlementAssertionError(code, message);
}

function decodeBase64Url(segment, label) {
  if (!segment || !BASE64URL_RE.test(segment)) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      `The entitlement assertion ${label} is not canonical base64url.`,
    );
  }
  const decoded = Buffer.from(segment, "base64url");
  if (!decoded.length || decoded.toString("base64url") !== segment) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      `The entitlement assertion ${label} is not canonical base64url.`,
    );
  }
  return decoded;
}

function decodeJsonSegment(segment, label) {
  try {
    const value = JSON.parse(decodeBase64Url(segment, label).toString("utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError("not an object");
    }
    return value;
  } catch (error) {
    if (error instanceof EntitlementAssertionError) throw error;
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      `The entitlement assertion ${label} is not a JSON object.`,
    );
  }
}

function tokenHash(token) {
  return crypto.createHash("sha256").update(token, "utf8").digest("base64url");
}

function safeEqualText(left, right) {
  const a = Buffer.from(String(left), "utf8");
  const b = Buffer.from(String(right), "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function hasExactKeys(value, expected) {
  const actual = Object.keys(value).sort();
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  );
}

function productionKeyset() {
  return Object.freeze({
    [ENTITLEMENT_ASSERTION.keyId]: crypto.createPublicKey({
      key: Buffer.from(
        ENTITLEMENT_ASSERTION.productionPublicKeySpkiDerB64,
        "base64",
      ),
      format: "der",
      type: "spki",
    }),
  });
}

function resolvePublicKey(keyset, keyId) {
  const configured = keyset && keyset[keyId];
  if (!configured) {
    throw assertionError(
      "beta_entitlement_assertion_key_unknown",
      "The entitlement assertion uses an unknown signing key.",
    );
  }
  try {
    const key = configured.type === "public"
      ? configured
      : crypto.createPublicKey(configured);
    if (key.asymmetricKeyType !== "ed25519") throw new TypeError("not Ed25519");
    return key;
  } catch (error) {
    throw assertionError(
      "beta_entitlement_assertion_key_invalid",
      "The pinned entitlement verification key is invalid.",
    );
  }
}

function requireString(value, name) {
  if (typeof value !== "string" || !value) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      `The entitlement assertion is missing ${name}.`,
    );
  }
  return value;
}

function requireTimestamp(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      `The entitlement assertion has an invalid ${name}.`,
    );
  }
  return value;
}

function validateEntitlements(value) {
  if (!Array.isArray(value)) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      "The entitlement assertion has no canonical entitlement list.",
    );
  }
  if (
    value.some(
      (item) =>
        typeof item !== "string" ||
        !item ||
        item.trim() !== item,
    )
  ) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      "The entitlement assertion contains an invalid entitlement name.",
    );
  }
  const canonical = [...new Set(value)].sort();
  if (
    canonical.length !== value.length ||
    canonical.some((item, index) => item !== value[index])
  ) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      "The entitlement assertion entitlement list is not canonical.",
    );
  }
  return canonical;
}

function verifyEntitlementAssertion({
  assertion,
  accessToken,
  refreshToken,
  keyset = productionKeyset(),
  nowSeconds = Math.floor(Date.now() / 1000),
  clockSkewSeconds = 30,
  requireCurrent = true,
}) {
  requireString(assertion, "signed assertion");
  requireString(accessToken, "access token binding");
  requireString(refreshToken, "refresh token binding");
  if (!Number.isSafeInteger(nowSeconds) || nowSeconds < 0) {
    throw new TypeError("nowSeconds must be a non-negative integer");
  }
  if (!Number.isSafeInteger(clockSkewSeconds) || clockSkewSeconds < 0) {
    throw new TypeError("clockSkewSeconds must be a non-negative integer");
  }

  const parts = assertion.split(".");
  if (parts.length !== 3) {
    throw assertionError(
      "beta_entitlement_assertion_invalid",
      "The entitlement assertion is not a compact JWS.",
    );
  }
  const [protectedSegment, payloadSegment, signatureSegment] = parts;
  const header = decodeJsonSegment(protectedSegment, "header");
  if (
    !hasExactKeys(header, HEADER_KEYS) ||
    header.alg !== ENTITLEMENT_ASSERTION.algorithm ||
    header.typ !== ENTITLEMENT_ASSERTION.type ||
    header.kid !== ENTITLEMENT_ASSERTION.keyId
  ) {
    throw assertionError(
      "beta_entitlement_assertion_header_invalid",
      "The entitlement assertion header is not supported.",
    );
  }

  const publicKey = resolvePublicKey(keyset, header.kid);
  const signature = decodeBase64Url(signatureSegment, "signature");
  const signingInput = `${protectedSegment}.${payloadSegment}`;
  if (
    signature.length !== 64 ||
    !crypto.verify(null, Buffer.from(signingInput, "ascii"), publicKey, signature)
  ) {
    throw assertionError(
      "beta_entitlement_assertion_signature_invalid",
      "The entitlement assertion signature is invalid.",
    );
  }

  const claims = decodeJsonSegment(payloadSegment, "payload");
  if (
    !hasExactKeys(claims, CLAIM_KEYS) ||
    claims.iss !== ENTITLEMENT_ASSERTION.issuer ||
    claims.aud !== ENTITLEMENT_ASSERTION.audience ||
    claims.schema !== ENTITLEMENT_ASSERTION.schema
  ) {
    throw assertionError(
      "beta_entitlement_assertion_claims_invalid",
      "The entitlement assertion was issued for a different runtime.",
    );
  }

  const sub = requireString(claims.sub, "subject");
  const licenseId = requireString(claims.license_id, "license id");
  const email = requireString(claims.email, "email");
  if (email.trim().toLowerCase() !== email) {
    throw assertionError(
      "beta_entitlement_assertion_claims_invalid",
      "The entitlement assertion email is not canonical.",
    );
  }
  if (claims.tier !== "pro" && claims.tier !== "builder") {
    throw assertionError(
      "beta_entitlement_assertion_claims_invalid",
      "The entitlement assertion tier is invalid.",
    );
  }
  const entitlements = validateEntitlements(claims.entitlements);
  const iat = requireTimestamp(claims.iat, "issued-at timestamp");
  const nbf = requireTimestamp(claims.nbf, "not-before timestamp");
  const exp = requireTimestamp(claims.exp, "expiry timestamp");
  requireString(claims.jti, "assertion id");
  if (iat !== nbf || exp <= iat || exp - iat > 3600) {
    throw assertionError(
      "beta_entitlement_assertion_claims_invalid",
      "The entitlement assertion validity window is invalid.",
    );
  }
  if (iat > nowSeconds + clockSkewSeconds || nbf > nowSeconds + clockSkewSeconds) {
    throw assertionError(
      "beta_entitlement_assertion_not_yet_valid",
      "The entitlement assertion is not yet valid.",
    );
  }
  if (requireCurrent && exp <= nowSeconds - clockSkewSeconds) {
    throw assertionError(
      "beta_entitlement_assertion_expired",
      "The entitlement assertion has expired.",
    );
  }

  const accessHash = requireString(claims.ath, "access-token hash");
  const refreshHash = requireString(claims.rth, "refresh-token hash");
  if (!TOKEN_HASH_RE.test(accessHash) || !TOKEN_HASH_RE.test(refreshHash)) {
    throw assertionError(
      "beta_entitlement_assertion_claims_invalid",
      "The entitlement assertion token binding is malformed.",
    );
  }
  if (
    !safeEqualText(accessHash, tokenHash(accessToken)) ||
    !safeEqualText(refreshHash, tokenHash(refreshToken))
  ) {
    throw assertionError(
      "beta_entitlement_assertion_token_mismatch",
      "The entitlement assertion does not match this account session.",
    );
  }

  return Object.freeze({
    ...claims,
    sub,
    license_id: licenseId,
    email,
    tier: claims.tier,
    entitlements: Object.freeze(entitlements),
    iat,
    nbf,
    exp,
  });
}

module.exports = {
  ENTITLEMENT_ASSERTION,
  EntitlementAssertionError,
  productionKeyset,
  tokenHash,
  verifyEntitlementAssertion,
};
