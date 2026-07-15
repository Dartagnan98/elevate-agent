import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const migration = readFileSync(
  new URL(
    "../supabase/migrations/0020_device_start_v3_idempotency.sql",
    import.meta.url,
  ),
  "utf8",
);
const deviceV2Migration = readFileSync(
  new URL(
    "../supabase/migrations/0018_device_v2_response_recovery.sql",
    import.meta.url,
  ),
  "utf8",
);

function functionDefinitionIn(source: string, qualifiedName: string): string {
  const start = source.indexOf(`create or replace function ${qualifiedName}(`);
  assert.ok(start >= 0, `missing ${qualifiedName}`);
  const end = source.indexOf("\n$$;", start);
  assert.ok(end > start, `unterminated ${qualifiedName}`);
  return source.slice(start, end + 4);
}

function functionDefinition(qualifiedName: string): string {
  return functionDefinitionIn(migration, qualifiedName);
}

function assertOrdered(definition: string, ...fragments: string[]): void {
  let previous = -1;
  for (const fragment of fragments) {
    const current = definition.indexOf(fragment, previous + 1);
    assert.ok(current > previous, `missing or out of order: ${fragment}`);
    previous = current;
  }
}

describe("device start v3 migration contract", () => {
  it("does not use the reserved SQL keyword grant as a table alias", () => {
    for (const [name, source] of [
      ["device v2", deviceV2Migration],
      ["device v3", migration],
    ] as const) {
      const executableSql = source
        .split(/\r?\n/)
        .filter((line) => !/^\s*--/.test(line))
        .join("\n");
      assert.doesNotMatch(
        executableSql,
        /\bas\s+grant\b|\bgrant\./i,
        `${name} migration uses reserved alias grant`,
      );
    }
    assert.match(migration, /from public\.device_grants as device_grant/);
  });

  it("accepts and persists hashes only behind a service-role RPC", () => {
    const start = functionDefinition("public.start_device_grant_atomic_v3");
    assert.match(start, /security invoker/);
    assert.match(start, /set search_path = public, pg_temp/);
    assert.match(
      migration,
      /revoke execute on function public\.start_device_grant_atomic_v3\([\s\S]*?\) from public, anon, authenticated;/,
    );
    assert.match(
      migration,
      /grant execute on function public\.start_device_grant_atomic_v3\([\s\S]*?\) to service_role;/,
    );
    assert.doesNotMatch(migration, /p_device_code(?!_hash)/);
    assert.doesNotMatch(migration, /p_refresh_token_plain/);
    assert.doesNotMatch(migration, /p_proposed_refresh_token(?!_hash)/);
  });

  it("uses one shared B lock for Device grants and client-controlled license writers", () => {
    const helper = functionDefinition(
      "elevate_internal.lock_refresh_capability_v1",
    );
    assert.match(helper, /security invoker/);
    assert.match(helper, /set search_path = public, pg_temp/);
    assert.match(helper, /elevate-refresh-capability-v1:/);
    assert.doesNotMatch(migration, /elevate-device-start-v3-b:/);

    const trigger = functionDefinition(
      "elevate_internal.lock_device_grant_capability_v1",
    );
    assertOrdered(
      trigger,
      "tg_op = 'UPDATE'",
      "new.proposed_refresh_token_hash is distinct from",
      "device grant refresh proposal is immutable",
      "return new",
      "lock_refresh_capability_v1",
    );
    assertOrdered(
      trigger,
      "lock_refresh_capability_v1",
      "from public.licenses",
      "license.refresh_token_hash",
      "license.previous_refresh_token_hash",
    );
    assert.match(
      migration,
      /before insert or update of proposed_refresh_token_hash[\s\S]*?execute function elevate_internal\.lock_device_grant_capability_v1\(\);/,
    );

    for (const signature of [
      "rotate_license_refresh_v2(text, text, text)",
      "approve_device_grant_atomic_v2(uuid, uuid)",
      "issue_existing_user_license_v2(uuid, text, text, text)",
      "signup_with_license_v2(text, text, text, text, text, text)",
      "replay_signup_license_v2(uuid, text, text)",
    ]) {
      assert.ok(
        migration.includes(`alter function public.${signature}\n  set schema elevate_internal;`),
        `missing private move for ${signature}`,
      );
      assert.ok(
        migration.includes(`alter function elevate_internal.${signature}\n  set search_path = public, pg_temp;`),
        `missing search_path reassertion for ${signature}`,
      );
    }

    for (const name of [
      "public.rotate_license_refresh_v2",
      "public.approve_device_grant_atomic_v2",
      "public.issue_existing_user_license_v2",
      "public.signup_with_license_v2",
      "public.replay_signup_license_v2",
    ]) {
      const wrapper = functionDefinition(name);
      assert.match(wrapper, /security invoker/);
      assert.match(wrapper, /set search_path = public, pg_temp/);
      assert.match(wrapper, /elevate_internal\.lock_refresh_capability_v1/);
    }
  });

  it("takes shared B before durable locks and revalidates each relevant table", () => {
    const refresh = functionDefinition("public.rotate_license_refresh_v2");
    assertOrdered(
      refresh,
      "lock_refresh_capability_v1",
      "from public.device_grants",
      "elevate_internal.rotate_license_refresh_v2",
    );
    assert.ok(
      refresh.indexOf("lock_refresh_capability_v1") < refresh.indexOf("for update"),
    );

    for (const [name, result] of [
      ["public.issue_existing_user_license_v2", "collision"],
      ["public.signup_with_license_v2", "collision"],
      ["public.replay_signup_license_v2", "invalid"],
    ] as const) {
      const wrapper = functionDefinition(name);
      assertOrdered(
        wrapper,
        "lock_refresh_capability_v1",
        "from public.device_grants",
        `'result', '${result}'`,
        name.replace("public.", "elevate_internal."),
      );
    }

    const start = functionDefinition("public.start_device_grant_atomic_v3");
    assertOrdered(
      start,
      "elevate-device-start-v3-d:",
      "elevate_internal.lock_refresh_capability_v1",
      "from public.device_grants",
      "for update",
    );
    assert.match(
      start,
      /license\.refresh_token_hash = p_proposed_refresh_token_hash[\s\S]*?license\.previous_refresh_token_hash = p_proposed_refresh_token_hash/,
    );
  });

  it("locks approval B then grant then user before sampling the internal clock", () => {
    const approval = functionDefinition("public.approve_device_grant_atomic_v2");
    const firstRead = approval.indexOf(
      "select device_grant.proposed_refresh_token_hash",
    );
    const capabilityLock = approval.indexOf("lock_refresh_capability_v1");
    const lockedRead = approval.indexOf(
      "select device_grant.proposed_refresh_token_hash",
      capabilityLock,
    );
    const grantRowLock = approval.indexOf("for update", lockedRead);
    const exactRevalidation = approval.indexOf(
      "v_locked_proposed_hash is distinct from v_proposed_hash",
      grantRowLock,
    );
    const userRead = approval.indexOf("select app_user.status", exactRevalidation);
    const userRowLock = approval.indexOf("for update", userRead);
    const delegation = approval.indexOf(
      "elevate_internal.approve_device_grant_atomic_v2",
      userRowLock,
    );
    assert.ok(firstRead >= 0);
    assert.ok(capabilityLock > firstRead);
    assert.equal(approval.slice(firstRead, capabilityLock).includes("for update"), false);
    assert.ok(lockedRead > capabilityLock);
    assert.match(
      approval.slice(lockedRead, grantRowLock),
      /device_grant\.proposed_refresh_token_hash,[\s\S]*?device_grant\.status/,
    );
    assert.ok(grantRowLock > lockedRead);
    assert.ok(exactRevalidation > grantRowLock);
    assert.ok(userRead > exactRevalidation);
    assert.ok(userRowLock > userRead);
    assert.match(
      approval.slice(userRead, userRowLock),
      /where app_user\.id = p_user_id/,
    );
    assert.ok(delegation > userRowLock);
    assert.equal(
      approval.slice(capabilityLock, grantRowLock).includes("from public.users"),
      false,
      "no user row lock may precede the grant row lock",
    );

    const originalApproval = functionDefinitionIn(
      deviceV2Migration,
      "public.approve_device_grant_atomic_v2",
    );
    const internalClock = originalApproval.indexOf(
      "v_now timestamptz := clock_timestamp()",
    );
    const internalUserLock = originalApproval.indexOf("select app_user.status");
    const internalGrantLock = originalApproval.indexOf(
      "select device_grant.device_label",
      internalUserLock,
    );
    assert.ok(internalClock >= 0);
    assert.ok(internalUserLock > internalClock);
    assert.ok(internalGrantLock > internalUserLock);
    assert.match(
      approval.slice(capabilityLock, delegation),
      /entry clock is sampled only after every[\s\S]*?possible wait/,
    );
    assert.match(
      approval,
      /Claim already takes[\s\S]*?grant -> license -> user/,
    );
  });

  it("serializes D and B, recovers unique races, and replays absolute expiry", () => {
    const start = functionDefinition("public.start_device_grant_atomic_v3");
    const dLock = start.indexOf("elevate-device-start-v3-d:");
    const bLock = start.indexOf("elevate_internal.lock_refresh_capability_v1");
    assert.ok(dLock > 0);
    assert.ok(bLock > dLock);
    assert.match(start, /exception when unique_violation/);
    assert.match(start, /'result', 'user_code_conflict'/);
    assert.match(start, /'result', 'conflict'/);
    assert.match(
      start,
      /'result', 'replay',[\s\S]*?'user_code', v_user_code,[\s\S]*?'expires_at', v_expires_at/,
    );
    assert.doesNotMatch(start, /set\s+expires_at\s*=/i);
    assert.match(start, /v_status = 'approved'[\s\S]*?'result', 'resume_poll'/);
    assert.match(start, /v_status = 'claimed'[\s\S]*?'result', 'resume_poll'/);
    assert.match(start, /v_status = 'denied'[\s\S]*?'result', 'denied'/);
    assert.match(start, /v_status = 'expired'[\s\S]*?'result', 'expired'/);

    const refreshedClockIndex = start.indexOf("v_now := clock_timestamp();", bLock);
    const insertIndex = start.indexOf("insert into public.device_grants");
    const insertClockIndex = start.lastIndexOf(
      "v_now := clock_timestamp();",
      insertIndex,
    );
    assert.ok(refreshedClockIndex > bLock);
    assert.ok(insertClockIndex > refreshedClockIndex);
    assert.match(
      start.slice(insertClockIndex, insertIndex),
      /if p_expires_at <= v_now then[\s\S]*?'result', 'expired'/,
    );
  });

  it("keeps private helpers service-only and records the legacy random residual", () => {
    assert.match(
      migration,
      /revoke all on schema elevate_internal from public, anon, authenticated;/,
    );
    assert.match(migration, /grant usage on schema elevate_internal to service_role;/);
    for (const signature of [
      "lock_refresh_capability_v1(text)",
      "lock_device_grant_capability_v1()",
      "rotate_license_refresh_v2(text, text, text)",
      "approve_device_grant_atomic_v2(uuid, uuid)",
      "issue_existing_user_license_v2(uuid, text, text, text)",
      "signup_with_license_v2(text, text, text, text, text, text)",
      "replay_signup_license_v2(uuid, text, text)",
    ]) {
      assert.ok(
        migration.includes(
          `revoke execute on function elevate_internal.${signature}\n  from public, anon, authenticated;`,
        ),
        `missing private revoke for ${signature}`,
      );
      assert.ok(
        migration.includes(
          `grant execute on function elevate_internal.${signature}\n  to service_role;`,
        ),
        `missing private service grant for ${signature}`,
      );
    }
    assert.match(migration, /collision residual is the[\s\S]*?2\^-256/);
  });
});
