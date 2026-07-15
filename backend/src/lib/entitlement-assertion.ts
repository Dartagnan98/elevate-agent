import crypto, { type KeyObject } from "node:crypto";

import { TTL } from "@/lib/jwt";

export const ENTITLEMENT_ASSERTION_PUBLIC_KEYS = Object.freeze({
  "ent-2026-07-a":
    "MCowBQYDK2VwAyEAexzoft6MmOXSkKHVJH4hBLgss5LN51wWaQ7bfUom1CQ=",
  "ent-2026-07-b":
    "MCowBQYDK2VwAyEA6ohPc76/T+8U0Wi+pK704Sc9a+dBBS77egvXHe8wYiA=",
} as const);

export type EntitlementSigningKeyId = keyof typeof ENTITLEMENT_ASSERTION_PUBLIC_KEYS;

export const ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS = Object.freeze(
  Object.keys(ENTITLEMENT_ASSERTION_PUBLIC_KEYS).sort() as EntitlementSigningKeyId[],
);

export const ENTITLEMENT_ASSERTION_KEYSET_SHA256 =
  "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c";

export const ENTITLEMENT_ASSERTION = {
  ISSUER: "https://api.elevationrealestatehq.com",
  AUDIENCE: "elevate-realtor-beta",
  SCHEMA: 1,
  // A remains the default and legacy active signer until the adoption gate.
  KEY_ID: "ent-2026-07-a",
  ACCEPTED_KEY_IDS: ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  KEYSET_SHA256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
  TYPE: "elevate-entitlement+jwt",
  ALGORITHM: "EdDSA",
  PRODUCTION_PUBLIC_KEY_SPKI_DER_B64:
    ENTITLEMENT_ASSERTION_PUBLIC_KEYS["ent-2026-07-a"],
} as const;

const LEGACY_PRIVATE_KEY_ENV = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64";
const ACTIVE_KID_ENV = "ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID";
const PRIVATE_KEY_RING_ENV = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON";
const KEYSET_FINGERPRINT_DOMAIN = "elevate-entitlement-keyset-v1\0";
const MAX_PRIVATE_KEY_RING_JSON_LENGTH = 64 * 1024;

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
  keyId: EntitlementSigningKeyId;
  sign: (claims: EntitlementAssertionClaims) => string;
}>;

export type EntitlementSigningEnvironment = Readonly<Record<string, string | undefined>>;

export type EntitlementSignerReadiness = Readonly<{
  ready: boolean;
  activeKid: string | null;
  publicKeysetSha256: typeof ENTITLEMENT_ASSERTION_KEYSET_SHA256;
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

function decodeStrictBase64(value: string, label: string): Buffer {
  // Deployment format is intentionally exact: standard padded RFC 4648
  // base64, with no whitespace, containing an unencrypted PKCS#8 DER key.
  if (
    value.length === 0 ||
    value.length % 4 !== 0 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)
  ) {
    throw new EntitlementSigningConfigurationError(
      `${label} must be canonical padded base64 without whitespace`,
    );
  }
  const decoded = Buffer.from(value, "base64");
  if (decoded.length === 0 || decoded.toString("base64") !== value) {
    throw new EntitlementSigningConfigurationError(
      `${label} is not canonical base64`,
    );
  }
  return decoded;
}

function loadPrivateKey(value: string, label: string): KeyObject {
  const encodedPrivateKey = decodeStrictBase64(value, label);
  let privateKey: KeyObject;
  try {
    privateKey = crypto.createPrivateKey({
      key: encodedPrivateKey,
      format: "der",
      type: "pkcs8",
    });
  } catch (error) {
    if (error instanceof EntitlementSigningConfigurationError) throw error;
    throw new EntitlementSigningConfigurationError(
      `${label} must contain an unencrypted Ed25519 PKCS#8 DER private key`,
      { cause: error },
    );
  }

  if (privateKey.asymmetricKeyType !== "ed25519") {
    throw new EntitlementSigningConfigurationError(
      `${label} must contain an Ed25519 private key`,
    );
  }
  const canonicalPrivateKey = privateKey.export({ format: "der", type: "pkcs8" });
  if (
    canonicalPrivateKey.length !== encodedPrivateKey.length ||
    !crypto.timingSafeEqual(canonicalPrivateKey, encodedPrivateKey)
  ) {
    throw new EntitlementSigningConfigurationError(
      `${label} must contain canonical Ed25519 PKCS#8 DER`,
    );
  }
  return privateKey;
}

function assertProductionPublicKey(
  privateKey: KeyObject,
  keyId: EntitlementSigningKeyId,
  environment: EntitlementSigningEnvironment,
  label: string,
): void {
  if (environment.NODE_ENV !== "production") return;

  const actual = crypto.createPublicKey(privateKey).export({
    format: "der",
    type: "spki",
  });
  const expected = Buffer.from(
    ENTITLEMENT_ASSERTION_PUBLIC_KEYS[keyId],
    "base64",
  );
  if (actual.length !== expected.length || !crypto.timingSafeEqual(actual, expected)) {
    throw new EntitlementSigningConfigurationError(
      `${label} does not match entitlement key ${keyId}`,
    );
  }
}

export function entitlementAssertionKeysetSha256(
  publicKeys: Readonly<Record<string, string>> = ENTITLEMENT_ASSERTION_PUBLIC_KEYS,
): string {
  const hash = crypto.createHash("sha256");
  hash.update(KEYSET_FINGERPRINT_DOMAIN, "utf8");
  for (const keyId of Object.keys(publicKeys).sort()) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(keyId)) {
      throw new EntitlementSigningConfigurationError("entitlement public key id is invalid");
    }
    const canonicalPublicKey = publicKeys[keyId];
    decodeStrictBase64(canonicalPublicKey, `entitlement public key ${keyId}`);
    hash.update(keyId, "utf8");
    hash.update("\0", "utf8");
    hash.update(canonicalPublicKey, "utf8");
    hash.update("\0", "utf8");
  }
  return hash.digest("hex");
}

function validateCompiledPublicKeyset(): void {
  for (const keyId of ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS) {
    const encodedPublicKey = decodeStrictBase64(
      ENTITLEMENT_ASSERTION_PUBLIC_KEYS[keyId],
      `entitlement public key ${keyId}`,
    );
    let publicKey: KeyObject;
    try {
      publicKey = crypto.createPublicKey({
        key: encodedPublicKey,
        format: "der",
        type: "spki",
      });
    } catch (error) {
      if (error instanceof EntitlementSigningConfigurationError) throw error;
      throw new EntitlementSigningConfigurationError(
        `entitlement public key ${keyId} is not SPKI DER`,
        { cause: error },
      );
    }
    if (publicKey.asymmetricKeyType !== "ed25519") {
      throw new EntitlementSigningConfigurationError(
        `entitlement public key ${keyId} is not Ed25519`,
      );
    }
    const canonicalPublicKey = publicKey.export({ format: "der", type: "spki" });
    if (
      canonicalPublicKey.length !== encodedPublicKey.length ||
      !crypto.timingSafeEqual(canonicalPublicKey, encodedPublicKey)
    ) {
      throw new EntitlementSigningConfigurationError(
        `entitlement public key ${keyId} is not canonical SPKI DER`,
      );
    }
  }
  if (entitlementAssertionKeysetSha256() !== ENTITLEMENT_ASSERTION_KEYSET_SHA256) {
    throw new EntitlementSigningConfigurationError(
      "compiled entitlement public keyset fingerprint mismatch",
    );
  }
}

validateCompiledPublicKeyset();

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

function malformedPrivateKeyRing(): never {
  throw new EntitlementSigningConfigurationError(
    `${PRIVATE_KEY_RING_ENV} must be a JSON object mapping unique key ids to private-key base64 strings`,
  );
}

function parseJsonString(
  source: string,
  start: number,
): { value: string; end: number } {
  if (source[start] !== '"') return malformedPrivateKeyRing();
  let escaped = false;
  for (let index = start + 1; index < source.length; index += 1) {
    const character = source[index];
    if (character === '"' && !escaped) {
      const fragment = source.slice(start, index + 1);
      try {
        const value = JSON.parse(fragment) as unknown;
        if (typeof value !== "string") return malformedPrivateKeyRing();
        return { value, end: index + 1 };
      } catch {
        return malformedPrivateKeyRing();
      }
    }
    if (character === "\\" && !escaped) escaped = true;
    else escaped = false;
  }
  return malformedPrivateKeyRing();
}

function parsePrivateKeyRing(source: string): Map<string, string> {
  if (source.length === 0 || source.length > MAX_PRIVATE_KEY_RING_JSON_LENGTH) {
    return malformedPrivateKeyRing();
  }
  let index = 0;
  const skipWhitespace = () => {
    while (
      index < source.length &&
      (source[index] === " " ||
        source[index] === "\t" ||
        source[index] === "\r" ||
        source[index] === "\n")
    ) {
      index += 1;
    }
  };

  skipWhitespace();
  if (source[index] !== "{") return malformedPrivateKeyRing();
  index += 1;
  skipWhitespace();

  const entries = new Map<string, string>();
  let closed = false;
  if (source[index] === "}") {
    index += 1;
    closed = true;
  } else {
    while (index < source.length) {
      const key = parseJsonString(source, index);
      if (entries.has(key.value)) {
        throw new EntitlementSigningConfigurationError(
          `${PRIVATE_KEY_RING_ENV} contains a duplicate key id`,
        );
      }
      index = key.end;
      skipWhitespace();
      if (source[index] !== ":") return malformedPrivateKeyRing();
      index += 1;
      skipWhitespace();
      const value = parseJsonString(source, index);
      entries.set(key.value, value.value);
      index = value.end;
      skipWhitespace();
      if (source[index] === "}") {
        index += 1;
        closed = true;
        break;
      }
      if (source[index] !== ",") return malformedPrivateKeyRing();
      index += 1;
      skipWhitespace();
    }
  }

  if (!closed) return malformedPrivateKeyRing();
  skipWhitespace();
  if (index !== source.length) return malformedPrivateKeyRing();
  return entries;
}

function hasEnvironmentVariable(
  environment: EntitlementSigningEnvironment,
  name: string,
): boolean {
  return (
    Object.prototype.hasOwnProperty.call(environment, name) &&
    environment[name] !== undefined
  );
}

function createSigner(
  keyId: EntitlementSigningKeyId,
  privateKey: KeyObject,
): EntitlementSigner {
  return Object.freeze({
    keyId,
    sign(claims: EntitlementAssertionClaims): string {
      const protectedHeader = encodeJson({
        alg: ENTITLEMENT_ASSERTION.ALGORITHM,
        typ: ENTITLEMENT_ASSERTION.TYPE,
        kid: keyId,
      });
      const payload = encodeJson(claims);
      const signingInput = `${protectedHeader}.${payload}`;
      const signature = crypto.sign(null, Buffer.from(signingInput, "ascii"), privateKey);
      return `${signingInput}.${signature.toString("base64url")}`;
    },
  });
}

/**
 * Load and validate the backend signing ring.
 *
 * The legacy A-only variable is accepted only while both ring variables are
 * absent. Once either ring variable exists, the complete A+B configuration is
 * mandatory and errors never fall back to legacy material.
 */
export function loadEntitlementSigner(
  environment: EntitlementSigningEnvironment = process.env,
): EntitlementSigner {
  const hasActiveKeyId = hasEnvironmentVariable(environment, ACTIVE_KID_ENV);
  const hasPrivateKeyRing = hasEnvironmentVariable(environment, PRIVATE_KEY_RING_ENV);

  if (!hasActiveKeyId && !hasPrivateKeyRing) {
    const configured = environment[LEGACY_PRIVATE_KEY_ENV];
    if (!configured) {
      throw new EntitlementSigningConfigurationError(
        `${LEGACY_PRIVATE_KEY_ENV} is not set`,
      );
    }
    const privateKey = loadPrivateKey(configured, LEGACY_PRIVATE_KEY_ENV);
    assertProductionPublicKey(
      privateKey,
      ENTITLEMENT_ASSERTION.KEY_ID,
      environment,
      LEGACY_PRIVATE_KEY_ENV,
    );
    return createSigner(ENTITLEMENT_ASSERTION.KEY_ID, privateKey);
  }

  if (!hasActiveKeyId || !hasPrivateKeyRing) {
    throw new EntitlementSigningConfigurationError(
      `${ACTIVE_KID_ENV} and ${PRIVATE_KEY_RING_ENV} must be configured together`,
    );
  }

  const activeKeyId = environment[ACTIVE_KID_ENV] as string;
  if (!ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS.includes(activeKeyId as EntitlementSigningKeyId)) {
    throw new EntitlementSigningConfigurationError(
      `${ACTIVE_KID_ENV} is not a compiled entitlement key id`,
    );
  }

  const configuredRing = parsePrivateKeyRing(environment[PRIVATE_KEY_RING_ENV] as string);
  for (const configuredKeyId of configuredRing.keys()) {
    if (
      !ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS.includes(
        configuredKeyId as EntitlementSigningKeyId,
      )
    ) {
      throw new EntitlementSigningConfigurationError(
        `${PRIVATE_KEY_RING_ENV} contains an unknown key id`,
      );
    }
  }
  for (const expectedKeyId of ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS) {
    if (!configuredRing.has(expectedKeyId)) {
      throw new EntitlementSigningConfigurationError(
        `${PRIVATE_KEY_RING_ENV} is missing a compiled entitlement key id`,
      );
    }
  }

  const privateKeys = new Map<EntitlementSigningKeyId, KeyObject>();
  for (const keyId of ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS) {
    const label = `${PRIVATE_KEY_RING_ENV}[${keyId}]`;
    const privateKey = loadPrivateKey(configuredRing.get(keyId) as string, label);
    assertProductionPublicKey(privateKey, keyId, environment, label);
    privateKeys.set(keyId, privateKey);
  }

  return createSigner(
    activeKeyId as EntitlementSigningKeyId,
    privateKeys.get(activeKeyId as EntitlementSigningKeyId) as KeyObject,
  );
}

/** Resolve the signer for a route without leaking secret/config details. */
export function tryLoadEntitlementSigner(
  environment: EntitlementSigningEnvironment = process.env,
): EntitlementSigner | null {
  try {
    return loadEntitlementSigner(environment);
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown signing configuration error";
    console.error(`[entitlement-assertion] ${message}`);
    return null;
  }
}

function configuredActiveKidForHealth(
  environment: EntitlementSigningEnvironment,
): string | null {
  const hasActiveKeyId = hasEnvironmentVariable(environment, ACTIVE_KID_ENV);
  const hasPrivateKeyRing = hasEnvironmentVariable(environment, PRIVATE_KEY_RING_ENV);
  if (!hasActiveKeyId && !hasPrivateKeyRing) return ENTITLEMENT_ASSERTION.KEY_ID;
  const configured = environment[ACTIVE_KID_ENV];
  if (
    typeof configured === "string" &&
    ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS.includes(
      configured as EntitlementSigningKeyId,
    )
  ) {
    return configured;
  }
  return null;
}

export function entitlementSignerReadiness(
  environment: EntitlementSigningEnvironment = process.env,
): EntitlementSignerReadiness {
  try {
    const signer = loadEntitlementSigner(environment);
    return Object.freeze({
      ready: true,
      activeKid: signer.keyId,
      publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    });
  } catch {
    return Object.freeze({
      ready: false,
      activeKid: configuredActiveKidForHealth(environment),
      publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    });
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
