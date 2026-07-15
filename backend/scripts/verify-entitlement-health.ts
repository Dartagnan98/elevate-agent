import crypto from "node:crypto";
import { pathToFileURL } from "node:url";

import {
  ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS,
  ENTITLEMENT_ASSERTION_KEYSET_SHA256,
} from "../src/lib/entitlement-assertion";
import {
  DATABASE_SCHEMA_CONTRACT,
  DATABASE_SCHEMA_VERSION,
} from "../src/lib/schema-readiness";

const DEFAULT_URL = "https://api.elevationrealestatehq.com/api/health";
const MAX_HEALTH_BYTES = 64 * 1024;
const SAFE_BUILD_ID = /^[A-Za-z0-9._-]{1,128}$/;
const SAFE_FINGERPRINT = /^http-2\d\d-sha256-[0-9a-f]{64}$/;

type HealthBody = Record<string, unknown>;

export type VerifiedEntitlementHealth = Readonly<{
  service: "elevate-backend";
  backendBuildId: string;
  activeKid: string;
  publicKeysetSha256: string;
  databaseSchemaContract: typeof DATABASE_SCHEMA_CONTRACT;
  databaseSchemaVersion: typeof DATABASE_SCHEMA_VERSION;
}>;

function isObject(value: unknown): value is HealthBody {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Error messages name failed public fields but never serialize the response. */
export function verifyEntitlementHealth({
  status,
  body,
  expectedBuildId,
}: Readonly<{
  status: number;
  body: unknown;
  expectedBuildId: string;
}>): VerifiedEntitlementHealth {
  if (!SAFE_BUILD_ID.test(expectedBuildId)) {
    throw new Error("expected build id is invalid");
  }
  if (status < 200 || status >= 300) {
    throw new Error(`health endpoint returned HTTP ${status}`);
  }
  if (!isObject(body)) {
    throw new Error("health endpoint did not return a JSON object");
  }
  if (body.ok !== true) {
    throw new Error("health field ok must be true");
  }
  if (body.service !== "elevate-backend") {
    throw new Error("health field service is not elevate-backend");
  }
  if (body.backend_build_id !== expectedBuildId) {
    throw new Error(
      "health field backend_build_id does not match this deployment",
    );
  }
  if (body.entitlement_signer_ready !== true) {
    throw new Error("health field entitlement_signer_ready must be true");
  }

  const activeKid = body.entitlement_signing_active_kid;
  if (
    typeof activeKid !== "string" ||
    !ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS.includes(
      activeKid as (typeof ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS)[number],
    )
  ) {
    throw new Error(
      "health field entitlement_signing_active_kid is not accepted by this release",
    );
  }
  if (
    body.entitlement_public_keyset_sha256 !==
    ENTITLEMENT_ASSERTION_KEYSET_SHA256
  ) {
    throw new Error(
      "health field entitlement_public_keyset_sha256 does not match this release",
    );
  }
  if (body.database_schema_ready !== true) {
    throw new Error("health field database_schema_ready must be true");
  }
  if (body.database_schema_contract !== DATABASE_SCHEMA_CONTRACT) {
    throw new Error(
      "health field database_schema_contract does not match this release",
    );
  }
  if (body.database_schema_version !== DATABASE_SCHEMA_VERSION) {
    throw new Error(
      "health field database_schema_version does not match this release",
    );
  }
  if (body.initial_issuance_v2_ready !== true) {
    throw new Error("health field initial_issuance_v2_ready must be true");
  }

  return Object.freeze({
    service: "elevate-backend",
    backendBuildId: expectedBuildId,
    activeKid,
    publicKeysetSha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
    databaseSchemaContract: DATABASE_SCHEMA_CONTRACT,
    databaseSchemaVersion: DATABASE_SCHEMA_VERSION,
  });
}

type CliOptions = Readonly<{
  url: string;
  attempts: number;
  delayMs: number;
  consecutive: number;
  expectedBuildId: string | null;
  fingerprint: boolean;
  expectedFingerprint: string | null;
  selfCheck: boolean;
}>;

function positiveInteger(value: string, flag: string): number {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error(`${flag} must be a positive integer`);
  }
  return parsed;
}

function parseArgs(args: string[]): CliOptions {
  let url = DEFAULT_URL;
  let attempts = 1;
  let delayMs = 1000;
  let consecutive = 1;
  let expectedBuildId: string | null = null;
  let fingerprint = false;
  let expectedFingerprint: string | null = null;
  let selfCheck = false;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--self-check") {
      selfCheck = true;
      continue;
    }
    if (argument === "--fingerprint") {
      fingerprint = true;
      continue;
    }
    const value = args[index + 1];
    if (!value) throw new Error(`unknown or incomplete argument: ${argument}`);
    if (argument === "--url") url = value;
    else if (argument === "--attempts")
      attempts = positiveInteger(value, argument);
    else if (argument === "--delay-ms")
      delayMs = positiveInteger(value, argument);
    else if (argument === "--consecutive") {
      consecutive = positiveInteger(value, argument);
    } else if (argument === "--expected-build-id") expectedBuildId = value;
    else if (argument === "--expected-fingerprint") expectedFingerprint = value;
    else throw new Error(`unknown or incomplete argument: ${argument}`);
    index += 1;
  }

  const parsedUrl = new URL(url);
  if (parsedUrl.protocol !== "https:")
    throw new Error("health URL must use HTTPS");
  if (attempts < consecutive)
    throw new Error("attempts must be at least consecutive");
  if (expectedBuildId !== null && !SAFE_BUILD_ID.test(expectedBuildId)) {
    throw new Error("expected build id is invalid");
  }
  if (
    expectedFingerprint !== null &&
    !SAFE_FINGERPRINT.test(expectedFingerprint)
  ) {
    throw new Error("expected health fingerprint is invalid");
  }
  if (!selfCheck && !fingerprint && expectedBuildId === null) {
    throw new Error(
      "--expected-build-id is required for deployment verification",
    );
  }
  if (expectedFingerprint !== null && !fingerprint) {
    throw new Error("--expected-fingerprint requires --fingerprint");
  }

  return Object.freeze({
    url: parsedUrl.toString(),
    attempts,
    delayMs,
    consecutive,
    expectedBuildId,
    fingerprint,
    expectedFingerprint,
    selfCheck,
  });
}

async function requestHealth(
  url: string,
): Promise<Readonly<{ status: number; text: string }>> {
  const response = await fetch(url, {
    headers: { accept: "application/json", "cache-control": "no-cache" },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  const text = await response.text();
  if (Buffer.byteLength(text, "utf8") > MAX_HEALTH_BYTES) {
    throw new Error("health response exceeds the size limit");
  }
  return Object.freeze({ status: response.status, text });
}

async function fetchAndVerify(
  url: string,
  expectedBuildId: string,
): Promise<VerifiedEntitlementHealth> {
  const response = await requestHealth(url);
  let body: unknown;
  try {
    body = JSON.parse(response.text);
  } catch {
    throw new Error("health endpoint did not return valid JSON");
  }
  return verifyEntitlementHealth({
    status: response.status,
    body,
    expectedBuildId,
  });
}

async function fetchFingerprint(url: string): Promise<string> {
  const response = await requestHealth(url);
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`health endpoint returned HTTP ${response.status}`);
  }
  const digest = crypto
    .createHash("sha256")
    .update(response.text, "utf8")
    .digest("hex");
  return `http-${response.status}-sha256-${digest}`;
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function verifyConsecutive(options: CliOptions): Promise<void> {
  let consecutiveSuccesses = 0;
  let baselineFingerprint = options.expectedFingerprint;
  let lastError: unknown;
  let lastVerified: VerifiedEntitlementHealth | null = null;

  for (let attempt = 1; attempt <= options.attempts; attempt += 1) {
    try {
      if (options.fingerprint) {
        const current = await fetchFingerprint(options.url);
        if (baselineFingerprint === null) baselineFingerprint = current;
        if (current !== baselineFingerprint)
          throw new Error("health fingerprint changed");
      } else {
        lastVerified = await fetchAndVerify(
          options.url,
          options.expectedBuildId as string,
        );
      }
      consecutiveSuccesses += 1;
      if (consecutiveSuccesses >= options.consecutive) {
        if (options.fingerprint) {
          console.log(baselineFingerprint);
        } else if (lastVerified) {
          console.log(
            `[health] ready service=${lastVerified.service} build_id=${lastVerified.backendBuildId} active_kid=${lastVerified.activeKid} keyset_sha256=${lastVerified.publicKeysetSha256} schema=${lastVerified.databaseSchemaContract}@${lastVerified.databaseSchemaVersion} consecutive=${consecutiveSuccesses}`,
          );
        }
        return;
      }
    } catch (error) {
      lastError = error;
      consecutiveSuccesses = 0;
      if (options.fingerprint && options.expectedFingerprint === null) {
        baselineFingerprint = null;
      }
    }
    if (attempt < options.attempts) await wait(options.delayMs);
  }

  const message =
    lastError instanceof Error
      ? lastError.message
      : "health verification failed";
  throw new Error(message);
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2));
  if (options.selfCheck) {
    const activeKid = ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS[0];
    verifyEntitlementHealth({
      status: 200,
      expectedBuildId: "self-check",
      body: {
        ok: true,
        service: "elevate-backend",
        backend_build_id: "self-check",
        entitlement_signer_ready: true,
        entitlement_signing_active_kid: activeKid,
        entitlement_public_keyset_sha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
        database_schema_ready: true,
        database_schema_contract: DATABASE_SCHEMA_CONTRACT,
        database_schema_version: DATABASE_SCHEMA_VERSION,
        initial_issuance_v2_ready: true,
      },
    });
    console.log(
      `[health] verifier contract loaded; accepted_kids=${ENTITLEMENT_ASSERTION_ACCEPTED_KEY_IDS.length} keyset_sha256=${ENTITLEMENT_ASSERTION_KEYSET_SHA256} schema=${DATABASE_SCHEMA_CONTRACT}@${DATABASE_SCHEMA_VERSION}`,
    );
    return;
  }
  await verifyConsecutive(options);
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().catch((error: unknown) => {
    const message =
      error instanceof Error ? error.message : "health verification failed";
    console.error(`[health] ERROR: ${message}`);
    process.exitCode = 1;
  });
}
