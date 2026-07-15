import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  DATABASE_SCHEMA_CONTRACT,
  DATABASE_SCHEMA_READINESS_TTL_MS,
  DATABASE_SCHEMA_VERSION,
  cachedDatabaseSchemaReadiness,
  databaseSchemaReadiness,
  validateDatabaseSchemaReadiness,
} from "../src/lib/schema-readiness";

function readinessResult() {
  return {
    contract: DATABASE_SCHEMA_CONTRACT,
    schema_version: DATABASE_SCHEMA_VERSION,
    ready: true,
    tables_ready: true,
    columns_ready: true,
    constraints_ready: true,
    indexes_ready: true,
    rpcs_ready: true,
    triggers_ready: true,
    privileges_ready: true,
    data_invariants_ready: true,
    initial_issuance_v2_ready: true,
  };
}

describe("read-only database schema readiness", () => {
  it("strictly accepts the exact 0020 RPC contract", () => {
    assert.deepEqual(validateDatabaseSchemaReadiness(readinessResult()), {
      ready: true,
      initialIssuanceV2Ready: true,
    });
  });

  it("fails closed for missing, extra, wrong-version, or false checks", () => {
    for (const body of [
      { ...readinessResult(), indexes_ready: false },
      { ...readinessResult(), contract: "older-contract" },
      { ...readinessResult(), schema_version: "0019" },
      { ...readinessResult(), unexpected: true },
      Object.fromEntries(
        Object.entries(readinessResult()).filter(
          ([key]) => key !== "rpcs_ready",
        ),
      ),
    ]) {
      assert.equal(validateDatabaseSchemaReadiness(body).ready, false);
    }
    assert.deepEqual(
      validateDatabaseSchemaReadiness({
        ...readinessResult(),
        initial_issuance_v2_ready: false,
      }),
      { ready: false, initialIssuanceV2Ready: false },
    );
  });

  it("invokes only the authenticated, fixed read-only readiness RPC", async () => {
    const secret = "service-role-secret-marker";
    const requests: Array<{ input: string; init?: RequestInit }> = [];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push({ input: String(input), init });
      return new Response(JSON.stringify(readinessResult()), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    };

    assert.deepEqual(
      await databaseSchemaReadiness(
        {
          SUPABASE_URL: "https://schema.example.test",
          SUPABASE_SERVICE_ROLE_KEY: secret,
        },
        fetcher,
      ),
      { ready: true, initialIssuanceV2Ready: true },
    );
    const request = requests[0];
    assert(request);
    assert.equal(
      request.input,
      "https://schema.example.test/rest/v1/rpc/elevate_hq_schema_readiness_v1",
    );
    assert.equal(request.init?.method, "POST");
    assert.equal(request.init?.body, "{}");

    const failed = await databaseSchemaReadiness(
      {
        SUPABASE_URL: "https://schema.example.test",
        SUPABASE_SERVICE_ROLE_KEY: secret,
      },
      async () =>
        new Response(JSON.stringify({ error: secret }), { status: 500 }),
    );
    assert.deepEqual(failed, { ready: false, initialIssuanceV2Ready: false });
    assert.equal(JSON.stringify(failed).includes(secret), false);
  });

  it("single-flights and briefly caches the public deep readiness probe", async () => {
    const environment = {
      SUPABASE_URL: "https://cache.example.test",
      SUPABASE_SERVICE_ROLE_KEY: "cache-secret",
    };
    let calls = 0;
    let nowMs = 1_000;
    let releaseFirst: () => void = () => {
      throw new Error("first readiness probe was not initialized");
    };
    const firstGate = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    const fetcher: typeof fetch = async () => {
      calls += 1;
      if (calls === 1) await firstGate;
      return new Response(JSON.stringify(readinessResult()), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    };
    const now = () => nowMs;

    const concurrent = Array.from({ length: 25 }, () =>
      cachedDatabaseSchemaReadiness(environment, fetcher, now),
    );
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(calls, 1);
    releaseFirst();
    assert.equal((await Promise.all(concurrent)).every((value) => value.ready), true);
    assert.equal(calls, 1);

    assert.equal(
      (await cachedDatabaseSchemaReadiness(environment, fetcher, now)).ready,
      true,
    );
    assert.equal(calls, 1);

    nowMs += DATABASE_SCHEMA_READINESS_TTL_MS + 1;
    assert.equal(
      (await cachedDatabaseSchemaReadiness(environment, fetcher, now)).ready,
      true,
    );
    assert.equal(calls, 2);
  });

  it("pins a stable invoker-only RPC with no mutation statements", () => {
    const migration = readFileSync(
      new URL(
        "../supabase/migrations/0020_device_start_v3_idempotency.sql",
        import.meta.url,
      ),
      "utf8",
    );
    const start = migration.indexOf(
      "create or replace function public.elevate_hq_schema_readiness_v1()",
    );
    const end = migration.indexOf(
      "revoke execute on function public.elevate_hq_schema_readiness_v1()",
      start,
    );
    assert.ok(start > 0 && end > start);
    const readinessFunction = migration.slice(start, end);
    assert.match(
      readinessFunction,
      /language plpgsql\s+stable\s+security invoker/,
    );
    assert.match(
      readinessFunction,
      /set search_path = pg_catalog, public, pg_temp/,
    );
    assert.doesNotMatch(
      readinessFunction,
      /\b(?:insert\s+into|update\s+public\.|delete\s+from|alter\s+table|execute\s+)\b/i,
    );
    assert.match(
      migration,
      /revoke execute on function public\.elevate_hq_schema_readiness_v1\(\)[\s\S]*from public, anon, authenticated;[\s\S]*grant execute on function public\.elevate_hq_schema_readiness_v1\(\)[\s\S]*to service_role;/,
    );
  });
});
