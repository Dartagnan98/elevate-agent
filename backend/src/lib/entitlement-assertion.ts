import crypto, { type KeyObject } from "node:crypto";

import { TTL } from "@/lib/jwt";

export const ENTITLEMENT_ASSERTION = {
  ISSUER: "https://api.elevationrealestatehq.com",
  AUDIENCE: "elevate-realtor-beta",
  SCHEMA: 1,
  KEY_ID: "ent-2026-07-a",
  TYPE: "elevate-entitlement+jwt",
  ALGORITHM: "EdDSA",
  PRODUCTION_PUBLIC_KEY_SPKI_DER_B64:
    "MCowBQYDK2VwAyEAexzoft6MmOXSkKHVJH4hBLgss5LN51wWaQ7bfUom1CQ=",
} as const;

const PRIVATE_KEY_ENV = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64";

export type EntitlementTier = "pro" | "builder";

export type EntitlementAssertionClaims = {
  iss: typeof ENTITLEMENT_ASSERTION.ISSUER;
  aud: typeof ENTITLEMENT_ASSERTION.AUDIENCE;
  schema: typeof ENTITLEMENT_ASSERTION.SCHEMA;
  sub: string;
  license_id: string;
  email: string;
  tier: EntitlementTier;
  entitlements: string[];
  iat: number;
  nbf: number;
  exp: number;
  jti: string;
  ath: string;
  rth: string;
};

export type EntitlementSigner = Readonly<{
  sign: (claims: EntitlementAssertionClaims) => string;
}>;

export type EntitlementEnvelopeInput = {
  access_token: string;
  refresh_token: string;
  sub: string;
  license_id: string;
  email: string;
  tier: EntitlementTier;
  entitlements: readonly string[];
};

export type EntitlementEnvelope = {
  access_token: string;
  refresh_token: string;
  entitlement_assertion: string;
  license_id: string;
  email: string;
  tier: EntitlementTier;
  entitlements: string[];
  expires_in: number;
};

type AssertionClock = {
  nowSeconds?: number;
  jti?: string;
};

export class EntitlementSigningConfigurationError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "EntitlementSigningConfigurationError";
  }
}

function decodeStrictBase64(value: string): Buffer {
  // Deployment format is intentionally exact: standard padded RFC 4648
  // base64, with no whitespace, containing an unencrypted PKCS#8 DER key.
  if (
    value.length === 0 ||
    value.length % 4 !== 0 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)
  ) {
    throw new EntitlementSigningConfigurationError(
      `${PRIVATE_KEY_ENV} must be canonical padded base64 without whitespace`,
    );
  }
  const decoded = Buffer.from(value, "base64");
  if (decoded.length === 0 || decoded.toString("base64") !== value) {
    throw new EntitlementSigningConfigurationError(
      `${PRIVATE_KEY_ENV} is not canonical base64`,
    );
  }
  return decoded;
}

function loadPrivateKey(value: string): KeyObject {
  let privateKey: KeyObject;
  try {
    privateKey = crypto.createPrivateKey({
      key: decodeStrictBase64(value),
      format: "der",
      type: "pkcs8",
    });
  } catch (error) {
    if (error instanceof EntitlementSigningConfigurationError) throw error;
    throw new EntitlementSigningConfigurationError(
      `${PRIVATE_KEY_ENV} must contain an unencrypted Ed25519 PKCS#8 DER private key`,
      { cause: error },
    );
  }

  if (privateKey.asymmetricKeyType !== "ed25519") {
    throw new EntitlementSigningConfigurationError(
      `${PRIVATE_KEY_ENV} must contain an Ed25519 private key`,
    );
  }
  return privateKey;
}

function assertProductionPublicKey(privateKey: KeyObject): void {
  if (process.env.NODE_ENV !== "production") return;

  const actual = crypto.createPublicKey(privateKey).export({
    format: "der",
    type: "spki",
  });
  const expected = Buffer.from(
    ENTITLEMENT_ASSERTION.PRODUCTION_PUBLIC_KEY_SPKI_DER_B64,
    "base64",
  );
  if (actual.length !== expected.length || !crypto.timingSafeEqual(actual, expected)) {
    throw new EntitlementSigningConfigurationError(
      `${PRIVATE_KEY_ENV} does not match entitlement key ${ENTITLEMENT_ASSERTION.KEY_ID}`,
    );
  }
}

function encodeJson(value: unknown): string {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

function tokenHash(token: string): string {
  return crypto.createHash("sha256").update(token, "utf8").digest("base64url");
}

function normalizedEntitlements(values: readonly string[]): string[] {
  if (!values.every((value) => typeof value === "string")) {
    throw new TypeError("entitlements must contain only strings");
  }
  const normalized = values.map((value) => value.trim());
  if (normalized.some((value) => value.length === 0)) {
    throw new TypeError("entitlements must not contain empty names");
  }
  return [...new Set(normalized)].sort();
}

function required(value: string, name: string): string {
  if (!value) throw new TypeError(`${name} is required`);
  return value;
}

/**
 * Load and validate the backend signing key.
 *
 * The only private-key source is ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64,
 * encoded as canonical padded base64 of unencrypted Ed25519 PKCS#8 DER. There
 * is deliberately no development or production fallback. Production also
 * verifies that the derived public key is the pinned key for the advertised
 * `kid` before any assertion can be issued.
 */
export function loadEntitlementSigner(): EntitlementSigner {
  const configured = process.env[PRIVATE_KEY_ENV];
  if (!configured) {
    throw new EntitlementSigningConfigurationError(`${PRIVATE_KEY_ENV} is not set`);
  }

  const privateKey = loadPrivateKey(configured);
  assertProductionPublicKey(privateKey);

  return Object.freeze({
    sign(claims: EntitlementAssertionClaims): string {
      const protectedHeader = encodeJson({
        alg: ENTITLEMENT_ASSERTION.ALGORITHM,
        typ: ENTITLEMENT_ASSERTION.TYPE,
        kid: ENTITLEMENT_ASSERTION.KEY_ID,
      });
      const payload = encodeJson(claims);
      const signingInput = `${protectedHeader}.${payload}`;
      const signature = crypto.sign(null, Buffer.from(signingInput, "ascii"), privateKey);
      return `${signingInput}.${signature.toString("base64url")}`;
    },
  });
}

/** Resolve the signer for a route without leaking secret/config details. */
export function tryLoadEntitlementSigner(): EntitlementSigner | null {
  try {
    return loadEntitlementSigner();
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown signing configuration error";
    console.error(`[entitlement-assertion] ${message}`);
    return null;
  }
}

/**
 * Build the canonical response fields and the assertion together so duplicated
 * email/tier/license/entitlement values cannot drift from the signed payload.
 */
export function createEntitlementEnvelope(
  input: EntitlementEnvelopeInput,
  signer: EntitlementSigner,
  clock: AssertionClock = {},
): EntitlementEnvelope {
  const accessToken = required(input.access_token, "access_token");
  const refreshToken = required(input.refresh_token, "refresh_token");
  const sub = required(input.sub, "sub");
  const licenseId = required(input.license_id, "license_id");
  const email = required(input.email.trim().toLowerCase(), "email");
  const entitlements = normalizedEntitlements(input.entitlements);
  if (input.tier !== "pro" && input.tier !== "builder") {
    throw new TypeError("tier must be pro or builder");
  }
  const now = clock.nowSeconds ?? Math.floor(Date.now() / 1000);
  const jti = clock.jti ?? crypto.randomUUID();
  if (!Number.isSafeInteger(now) || now < 0) throw new TypeError("nowSeconds must be a timestamp");
  required(jti, "jti");

  const claims: EntitlementAssertionClaims = {
    iss: ENTITLEMENT_ASSERTION.ISSUER,
    aud: ENTITLEMENT_ASSERTION.AUDIENCE,
    schema: ENTITLEMENT_ASSERTION.SCHEMA,
    sub,
    license_id: licenseId,
    email,
    tier: input.tier,
    entitlements,
    iat: now,
    nbf: now,
    exp: now + TTL.ACCESS_SECONDS,
    jti,
    ath: tokenHash(accessToken),
    rth: tokenHash(refreshToken),
  };

  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    entitlement_assertion: signer.sign(claims),
    license_id: licenseId,
    email,
    tier: input.tier,
    entitlements,
    expires_in: TTL.ACCESS_SECONDS,
  };
}
