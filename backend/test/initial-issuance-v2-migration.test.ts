import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const migration = readFileSync(
  new URL(
    "../supabase/migrations/0019_initial_issuance_v2.sql",
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

describe("initial issuance v2 migration contract", () => {
  it("keeps initial bearer state hash-only with a bounded signup source", () => {
    assert.match(migration, /add column if not exists initial_issuance_kind text/);
    assert.match(migration, /from pg_constraint/);
    assert.match(migration, /conname = 'licenses_initial_issuance_kind_check'/);
    assert.match(migration, /conrelid = 'public\.licenses'::regclass/);
    assert.match(
      migration,
      /initial_issuance_kind is null\s+or initial_issuance_kind = 'signup'/,
    );
    assert.doesNotMatch(migration, /p_initial_refresh_token/);
    assert.doesNotMatch(migration, /p_refresh_token(?!_hash)/);
    assert.doesNotMatch(migration, /p_password\s+text/);
    assert.doesNotMatch(migration, /p_raw_password/);
  });

  it("makes every issuance RPC fixed-search-path and service-role-only", () => {
    const functions = [
      {
        name: "issue_existing_user_license_v2",
        next: "signup_with_license_v2",
        signature: "issue_existing_user_license_v2(uuid, text, text, text)",
      },
      {
        name: "signup_with_license_v2",
        next: "replay_signup_license_v2",
        signature: "signup_with_license_v2(text, text, text, text, text, text)",
      },
      {
        name: "replay_signup_license_v2",
        signature: "replay_signup_license_v2(uuid, text, text)",
      },
    ] as const;

    for (const entry of functions) {
      const definition = functionDefinition(
        entry.name,
        "next" in entry ? entry.next : undefined,
      );
      assert.match(definition, /security invoker/);
      assert.match(definition, /set search_path = public, pg_temp/);
      assert.match(definition, /pg_advisory_xact_lock/);
      const signature = entry.signature.replace(/[()]/g, "\\$&");
      assert.match(
        migration,
        new RegExp(
          `revoke execute on function public\\.${signature}\\s+from public, anon, authenticated;`,
        ),
      );
      assert.match(
        migration,
        new RegExp(`grant execute on function public\\.${signature}\\s+to service_role;`),
      );
    }
  });

  it("locks token lineage and the exact verified password-hash snapshot", () => {
    const login = functionDefinition(
      "issue_existing_user_license_v2",
      "signup_with_license_v2",
    );
    assert.match(login, /previous_refresh_token_hash = p_refresh_token_hash/);
    assert.match(login, /limit 1\s+for update/);
    assert.match(
      login,
      /v_user_password_hash is distinct from p_expected_password_hash/,
    );
    assert.match(login, /v_user_status not in \('active', 'trialing'\)/);
    assert.match(login, /v_family_expires_at <= v_now/);
    assert.match(login, /'result', 'replay'/);
    assert.match(login, /'result', 'issued'/);
  });

  it("creates signup user and license atomically while replay stays insert-free", () => {
    const signup = functionDefinition(
      "signup_with_license_v2",
      "replay_signup_license_v2",
    );
    const replay = functionDefinition("replay_signup_license_v2");

    assert.match(signup, /insert into public\.users/);
    assert.match(signup, /insert into public\.licenses/);
    assert.match(signup, /initial_issuance_kind[\s\S]*'signup'/);
    assert.match(signup, /when unique_violation then/);

    assert.doesNotMatch(replay, /insert into/);
    assert.doesNotMatch(replay, /update public\./);
    assert.doesNotMatch(replay, /delete from/);
    assert.match(replay, /v_initial_issuance_kind <> 'signup'/);
    assert.match(replay, /v_previous_hash is not null/);
    assert.match(
      replay,
      /v_user_password_hash is distinct from p_expected_password_hash/,
    );
  });
});
