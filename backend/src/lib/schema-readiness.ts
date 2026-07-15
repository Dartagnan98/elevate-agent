export const DATABASE_SCHEMA_CONTRACT =
  "elevate-hq-schema-readiness-v1" as const;
export const DATABASE_SCHEMA_VERSION = "0020" as const;
export const DATABASE_SCHEMA_READINESS_TTL_MS = 10_000;

const READINESS_BOOLEAN_FIELDS = Object.freeze([
  "ready",
  "tables_ready",
  "columns_ready",
  "constraints_ready",
  "indexes_ready",
  "rpcs_ready",
  "triggers_ready",
  "privileges_ready",
  "data_invariants_ready",
  "initial_issuance_v2_ready",
] as const);

const EXACT_RESPONSE_KEYS = Object.freeze(
  ["contract", "schema_version", ...READINESS_BOOLEAN_FIELDS].sort(),
);

type ReadinessBooleanField = (typeof READINESS_BOOLEAN_FIELDS)[number];
type ReadinessRpcBody = Readonly<
  {
    contract: typeof DATABASE_SCHEMA_CONTRACT;
    schema_version: typeof DATABASE_SCHEMA_VERSION;
  } & Record<ReadinessBooleanField, boolean>
>;

export type DatabaseSchemaReadiness = Readonly<{
  ready: boolean;
  initialIssuanceV2Ready: boolean;
}>;

type SchemaEnvironment = Readonly<Record<string, string | undefined>>;

type ReadinessCacheEntry = Readonly<{
  supabaseUrl: string | undefined;
  serviceRoleKey: string | undefined;
  expiresAt: number;
  value: DatabaseSchemaReadiness;
}>;

type ReadinessInFlight = Readonly<{
  supabaseUrl: string | undefined;
  serviceRoleKey: string | undefined;
  promise: Promise<DatabaseSchemaReadiness>;
}>;

let readinessCache: ReadinessCacheEntry | null = null;
let readinessInFlight: ReadinessInFlight | null = null;

function failClosed(): DatabaseSchemaReadiness {
  return Object.freeze({ ready: false, initialIssuanceV2Ready: false });
}

/** Strictly validate the exact public result of the read-only PostgreSQL RPC. */
export function validateDatabaseSchemaReadiness(
  value: unknown,
): DatabaseSchemaReadiness {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return failClosed();
  }
  const body = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(body).sort()) !==
    JSON.stringify(EXACT_RESPONSE_KEYS)
  ) {
    return failClosed();
  }
  if (
    body.contract !== DATABASE_SCHEMA_CONTRACT ||
    body.schema_version !== DATABASE_SCHEMA_VERSION ||
    !READINESS_BOOLEAN_FIELDS.every((field) => typeof body[field] === "boolean")
  ) {
    return failClosed();
  }

  const readiness = body as ReadinessRpcBody;
  const everyCheckReady = READINESS_BOOLEAN_FIELDS.every(
    (field) => readiness[field] === true,
  );
  return Object.freeze({
    ready: everyCheckReady,
    initialIssuanceV2Ready: readiness.initial_issuance_v2_ready === true,
  });
}

/**
 * Invoke only the STABLE, SECURITY INVOKER readiness RPC installed by 0020.
 * It performs catalog SELECTs and invariant reads; it cannot migrate or write.
 * Errors and credentials are never reflected into the public health response.
 */
export async function databaseSchemaReadiness(
  environment: SchemaEnvironment = process.env,
  fetcher: typeof fetch = fetch,
): Promise<DatabaseSchemaReadiness> {
  const supabaseUrl = environment.SUPABASE_URL;
  const serviceRoleKey = environment.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceRoleKey) return failClosed();

  try {
    const endpoint = new URL(
      "/rest/v1/rpc/elevate_hq_schema_readiness_v1",
      supabaseUrl,
    );
    const response = await fetcher(endpoint, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        apikey: serviceRoleKey,
        authorization: `Bearer ${serviceRoleKey}`,
      },
      body: "{}",
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return failClosed();
    return validateDatabaseSchemaReadiness(await response.json());
  } catch {
    return failClosed();
  }
}

/**
 * Bound public health traffic to one deep database probe per worker/TTL and
 * one in-flight request at a time. A newly restarted deployment has an empty
 * module cache, so its first build-bound health sample is always fresh.
 */
export async function cachedDatabaseSchemaReadiness(
  environment: SchemaEnvironment = process.env,
  fetcher: typeof fetch = fetch,
  now: () => number = Date.now,
): Promise<DatabaseSchemaReadiness> {
  const supabaseUrl = environment.SUPABASE_URL;
  const serviceRoleKey = environment.SUPABASE_SERVICE_ROLE_KEY;
  const currentTime = now();
  if (
    readinessCache &&
    readinessCache.supabaseUrl === supabaseUrl &&
    readinessCache.serviceRoleKey === serviceRoleKey &&
    currentTime < readinessCache.expiresAt
  ) {
    return readinessCache.value;
  }
  if (
    readinessInFlight &&
    readinessInFlight.supabaseUrl === supabaseUrl &&
    readinessInFlight.serviceRoleKey === serviceRoleKey
  ) {
    return readinessInFlight.promise;
  }

  const promise = databaseSchemaReadiness(environment, fetcher)
    .then((value) => {
      readinessCache = Object.freeze({
        supabaseUrl,
        serviceRoleKey,
        expiresAt: now() + DATABASE_SCHEMA_READINESS_TTL_MS,
        value,
      });
      return value;
    })
    .finally(() => {
      if (readinessInFlight?.promise === promise) readinessInFlight = null;
    });
  readinessInFlight = Object.freeze({ supabaseUrl, serviceRoleKey, promise });
  return promise;
}
