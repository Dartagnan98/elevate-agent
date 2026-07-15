import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const migration = readFileSync(
  new URL(
    "../supabase/migrations/0018_device_v2_response_recovery.sql",
    import.meta.url,
  ),
  "utf8",
);

function functionDefinition(name: string, nextName?: string): string {
  const start = migration.indexOf(`create or replace function public.${name}`);
  assert.notEqual(start, -1, `missing ${name}`);
  const end = nextName
    ? migration.indexOf(`create or replace function public.${nextName}`, start + 1)
    : migration.indexOf("revoke execute on function", start + 1);
  assert.notEqual(end, -1, `missing end marker for ${name}`);
  return migration.slice(start, end);
}

describe("device v2 migration contract", () => {
  it("keeps proposal state hash-only and the replay window schema-bounded", () => {
    assert.match(migration, /proposed_refresh_token_hash text/);
    assert.match(migration, /claim_retry_until timestamptz/);
    assert.match(
      migration,
      /proposed_refresh_token_hash ~ '\^\[0-9a-f\]\{64\}\$'/,
    );
    assert.match(
      migration,
      /proposed_refresh_token_hash is null\s+or refresh_token_plain is null/,
    );
    assert.match(
      migration,
      /claim_retry_until <= claimed_at \+ interval '2 minutes'/,
    );
    assert.match(
      migration,
      /create unique index if not exists device_grants_proposed_refresh_token_hash_uidx/,
    );
  });

  it("makes every v2 RPC fixed-search-path and service-role-only", () => {
    const functions = [
      {
        name: "approve_device_grant_atomic_v2",
        next: "poll_device_grant_pending_v2",
        signature: "approve_device_grant_atomic_v2(uuid, uuid)",
      },
      {
        name: "poll_device_grant_pending_v2",
        next: "claim_device_grant_atomic_v2",
        signature: "poll_device_grant_pending_v2(text, text)",
      },
      {
        name: "claim_device_grant_atomic_v2",
        next: "expire_stale_device_grants_v2",
        signature: "claim_device_grant_atomic_v2(text, text)",
      },
      {
        name: "expire_stale_device_grants_v2",
        signature: "expire_stale_device_grants_v2()",
      },
    ] as const;

    for (const entry of functions) {
      const definition = functionDefinition(
        entry.name,
        "next" in entry ? entry.next : undefined,
      );
      assert.match(definition, /security invoker/);
      assert.match(definition, /set search_path = public, pg_temp/);
      assert.match(
        migration,
        new RegExp(
          `revoke execute on function public\\.${entry.signature.replace(
            /[()]/g,
            "\\$&",
          )}\\s+from public, anon, authenticated;`,
        ),
      );
      assert.match(
        migration,
        new RegExp(
          `grant execute on function public\\.${entry.signature.replace(
            /[()]/g,
            "\\$&",
          )}\\s+to service_role;`,
        ),
      );
    }
  });

  it("accepts no plaintext bearer in approval, pending-poll, or claim RPCs", () => {
    const approval = functionDefinition(
      "approve_device_grant_atomic_v2",
      "poll_device_grant_pending_v2",
    );
    const pendingPoll = functionDefinition(
      "poll_device_grant_pending_v2",
      "claim_device_grant_atomic_v2",
    );
    const claim = functionDefinition(
      "claim_device_grant_atomic_v2",
      "expire_stale_device_grants_v2",
    );
    assert.doesNotMatch(approval, /p_refresh_token_plain/);
    assert.doesNotMatch(approval, /p_refresh_token(?!_hash)/);
    assert.doesNotMatch(pendingPoll, /p_refresh_token_plain/);
    assert.doesNotMatch(pendingPoll, /p_refresh_token(?!_hash)/);
    assert.doesNotMatch(pendingPoll, /set status = 'claimed'/);
    assert.doesNotMatch(claim, /p_refresh_token_plain/);
    assert.doesNotMatch(claim, /p_refresh_token(?!_hash)/);
    const plaintextAssignments = [...`${approval}\n${pendingPoll}\n${claim}`.matchAll(
      /refresh_token_plain\s*=\s*([^,\n]+)/g,
    )].map((match) => match[1].trim());
    assert.ok(plaintextAssignments.length > 0);
    assert.ok(plaintextAssignments.every((value) => value === "null"));
  });
});
