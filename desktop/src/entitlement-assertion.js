"use strict";

const crypto = require("node:crypto");
const { TextDecoder } = require("node:util");

const ENTITLEMENT_ASSERTION_PUBLIC_KEYS = Object.freeze({
  "ent-2026-07-a":
    "MCowBQYDK2VwAyEAexzoft6MmOXSkKHVJH4hBLgss5LN51wWaQ7bfUom1CQ=",
  "ent-2026-07-b":
    "MCowBQYDK2VwAyEA6ohPc76/T+8U0Wi+pK704Sc9a+dBBS77egvXHe8wYiA=",
});
const ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS = Object.freeze(
  Object.keys(ENTITLEMENT_ASSERTION_PUBLIC_KEYS).sort(),
);
const ENTITLEMENT_ASSERTION_KEYSET_SHA256 =
  "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c";

const ENTITLEMENT_ASSERTION = Object.freeze({
  issuer: "https://api.elevationrealestatehq.com",
  audience: "elevate-realtor-beta",
  schema: 1,
  // A remains the backend signing kid until the dual-key Beta adoption gate.
  keyId: "ent-2026-07-a",
  acceptedKeyIds: ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  keysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
  type: "elevate-entitlement+jwt",
  algorithm: "EdDSA",
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
const STRICT_UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });

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

function assertNoDuplicateJsonKeys(text, label) {
  let index = 0;

  function malformed() {
    throw new SyntaxError(`invalid ${label} JSON`);
  }

  function skipWhitespace() {
    while (index < text.length && /\s/.test(text[index])) index += 1;
  }

  function readString() {
    if (text[index] !== '"') malformed();
    const start = index;
    index += 1;
    while (index < text.length) {
      const character = text[index];
      if (character === '"') {
        index += 1;
        return JSON.parse(text.slice(start, index));
      }
      if (character === "\\") {
        index += 1;
        if (index >= text.length) malformed();
        if (text[index] === "u") index += 4;
      }
      index += 1;
    }
    malformed();
    return "";
  }

  function scanPrimitive() {
    const start = index;
    while (index < text.length && !/[\s,\]}]/.test(text[index])) index += 1;
    if (start === index) malformed();
  }

  function scanArray() {
    index += 1;
    skipWhitespace();
    if (text[index] === "]") {
      index += 1;
      return;
    }
    while (index < text.length) {
      scanValue();
      skipWhitespace();
      if (text[index] === "]") {
        index += 1;
        return;
      }
      if (text[index] !== ",") malformed();
      index += 1;
      skipWhitespace();
    }
    malformed();
  }

  function scanObject() {
    const keys = new Set();
    index += 1;
    skipWhitespace();
    if (text[index] === "}") {
      index += 1;
      return;
    }
    while (index < text.length) {
      const key = readString();
      if (keys.has(key)) {
        throw assertionError(
          "beta_entitlement_assertion_invalid",
          `The entitlement assertion ${label} repeats ${JSON.stringify(key)}.`,
        );
      }
      keys.add(key);
      skipWhitespace();
      if (text[index] !== ":") malformed();
      index += 1;
      scanValue();
      skipWhitespace();
      if (text[index] === "}") {
        index += 1;
        return;
      }
      if (text[index] !== ",") malformed();
      index += 1;
      skipWhitespace();
    }
    malformed();
  }

  function scanValue() {
    skipWhitespace();
    if (text[index] === "{") scanObject();
    else if (text[index] === "[") scanArray();
    else if (text[index] === '"') readString();
    else scanPrimitive();
  }

  scanValue();
  skipWhitespace();
  if (index !== text.length) malformed();
}

function decodeJsonSegment(segment, label) {
  try {
    const text = STRICT_UTF8_DECODER.decode(decodeBase64Url(segment, label));
    assertNoDuplicateJsonKeys(text, label);
    const value = JSON.parse(text);
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

function entitlementAssertionKeysetSha256(
  publicKeys = ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
) {
  if (!publicKeys || typeof publicKeys !== "object" || Array.isArray(publicKeys)) {
    throw assertionError(
      "beta_entitlement_assertion_key_invalid",
      "The pinned entitlement verification key ring is invalid.",
    );
  }
  const hash = crypto.createHash("sha256");
  hash.update("elevate-entitlement-keyset-v1\0", "utf8");
  for (const kid of Object.keys(publicKeys).sort()) {
    const spkiDerBase64 = publicKeys[kid];
    const der = typeof spkiDerBase64 === "string"
      ? Buffer.from(spkiDerBase64, "base64")
      : Buffer.alloc(0);
    if (
      !kid ||
      kid.length > 128 ||
      /[\u0000-\u001f]/.test(kid) ||
      !der.length ||
      der.toString("base64") !== spkiDerBase64
    ) {
      throw assertionError(
        "beta_entitlement_assertion_key_invalid",
        "The pinned entitlement verification key ring is invalid.",
      );
    }
    hash.update(`${kid}\0${spkiDerBase64}\0`, "utf8");
  }
  return hash.digest("hex");
}

function loadPinnedKeyset(publicKeys, acceptedKeyIds, expectedSha256) {
  if (
    !publicKeys ||
    typeof publicKeys !== "object" ||
    Array.isArray(publicKeys) ||
    !Array.isArray(acceptedKeyIds) ||
    typeof expectedSha256 !== "string"
  ) {
    throw assertionError(
      "beta_entitlement_assertion_key_invalid",
      "The pinned entitlement verification key ring is invalid.",
    );
  }
  const keyIds = Object.keys(publicKeys).sort();
  if (
    keyIds.length !== acceptedKeyIds.length ||
    keyIds.some((kid, index) => kid !== acceptedKeyIds[index]) ||
    !safeEqualText(
      entitlementAssertionKeysetSha256(publicKeys),
      expectedSha256,
    )
  ) {
    throw assertionError(
      "beta_entitlement_assertion_key_invalid",
      "The pinned entitlement verification key ring does not match this build.",
    );
  }
  try {
    const entries = keyIds.map((kid) => {
      const key = crypto.createPublicKey({
        key: Buffer.from(publicKeys[kid], "base64"),
        format: "der",
        type: "spki",
      });
      if (key.asymmetricKeyType !== "ed25519") {
        throw new TypeError("not Ed25519");
      }
      return [kid, key];
    });
    return Object.freeze(Object.fromEntries(entries));
  } catch (error) {
    throw assertionError(
      "beta_entitlement_assertion_key_invalid",
      "The pinned entitlement verification key ring is invalid.",
    );
  }
}

function productionKeyset() {
  return loadPinnedKeyset(
    ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
    ENTITLEMENT_ASSERTION.acceptedKeyIds,
    ENTITLEMENT_ASSERTION.keysetSha256,
  );
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
    typeof header.kid !== "string" ||
    !header.kid ||
    header.kid.length > 128 ||
    /[\u0000-\u001f]/.test(header.kid)
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
  ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  ENTITLEMENT_ASSERTION_KEYSET_SHA256,
  ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
  EntitlementAssertionError,
  entitlementAssertionKeysetSha256,
  loadPinnedKeyset,
  productionKeyset,
  tokenHash,
  verifyEntitlementAssertion,
};
