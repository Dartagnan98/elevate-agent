-- Device Start v3 makes a discarded successful start response recoverable.
-- The client proposes D and B, but PostgreSQL receives and stores only their
-- SHA-256 hashes. Exact retries reuse one absolute expiry and one user code.

-- Keep the unlocked implementations from 0017-0019 callable only inside a
-- non-exposed schema. Public wrappers below acquire one shared capability
-- lock before those implementations can lock or mutate durable rows.
create schema if not exists elevate_internal;
revoke all on schema elevate_internal from public, anon, authenticated;
grant usage on schema elevate_internal to service_role;

create or replace function elevate_internal.lock_refresh_capability_v1(
  p_refresh_token_hash text
) returns void
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid refresh capability hash' using errcode = '22023';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'elevate-refresh-capability-v1:' || p_refresh_token_hash,
      0
    )
  );
end;
$$;

-- The legacy issuance lanes that generate refresh tokens entirely on the
-- server remain unchanged. Their only cross-lane collision residual is the
-- SHA-256 preimage space (2^-256); existing uniqueness/final checks fail
-- closed if that residual event ever occurs.

-- Proposal-only Device v2 still inserts through the table API. This trigger
-- puts that compatibility path on the same capability lock as v3 and rejects
-- a B that already belongs to any license current/recovery slot. PostgreSQL
-- has already taken a tuple lock before a BEFORE ROW UPDATE trigger runs, so a
-- proposal update must fail without taking B; otherwise approval's B -> grant
-- order could deadlock against an update's grant -> B order.
create or replace function elevate_internal.lock_device_grant_capability_v1()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if tg_op = 'UPDATE' then
    if new.proposed_refresh_token_hash is distinct from
       old.proposed_refresh_token_hash then
      raise exception 'device grant refresh proposal is immutable'
        using errcode = '23514';
    end if;
    return new;
  end if;

  if new.proposed_refresh_token_hash is null then
    return new;
  end if;

  perform elevate_internal.lock_refresh_capability_v1(
    new.proposed_refresh_token_hash
  );
  if exists (
    select 1
      from public.licenses as license
     where license.refresh_token_hash = new.proposed_refresh_token_hash
        or license.previous_refresh_token_hash = new.proposed_refresh_token_hash
  ) then
    raise exception
      'duplicate key value violates unique constraint "device_grants_proposed_refresh_token_hash_uidx"'
      using errcode = '23505',
            constraint = 'device_grants_proposed_refresh_token_hash_uidx';
  end if;
  return new;
end;
$$;

drop trigger if exists device_grants_capability_lock_v1
  on public.device_grants;
create trigger device_grants_capability_lock_v1
before insert or update of proposed_refresh_token_hash
on public.device_grants
for each row execute function elevate_internal.lock_device_grant_capability_v1();

create or replace function public.start_device_grant_atomic_v3(
  p_device_code_hash text,
  p_proposed_refresh_token_hash text,
  p_user_code text,
  p_device_label text,
  p_ip_addr text,
  p_user_agent text,
  p_expires_at timestamptz
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_attempt integer;
  v_grant_id uuid;
  v_proposed_hash text;
  v_user_code text;
  v_status public.device_grant_status;
  v_expires_at timestamptz;
  v_user_id uuid;
  v_license_id uuid;
  v_plaintext_is_clear boolean;
  v_claim_retry_until timestamptz;
begin
  if p_device_code_hash is null
     or p_device_code_hash !~ '^[0-9a-f]{64}$'
     or p_proposed_refresh_token_hash is null
     or p_proposed_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or p_user_code is null
     or p_user_code !~ '^[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}$'
     or p_expires_at is null
     or p_expires_at <= v_now
     or p_expires_at > v_now + interval '11 minutes'
     or length(coalesce(p_device_label, '')) > 120
     or length(coalesce(p_ip_addr, '')) > 255
     or length(coalesce(p_user_agent, '')) > 1024 then
    raise exception 'invalid device v3 start material' using errcode = '22023';
  end if;

  -- D then B is the global lock order for v3 requests. Proposal-only Device v2
  -- inserts take the same B lock in the table trigger; unique constraints stay
  -- as the final serialization boundary and are recovered below.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('elevate-device-start-v3-d:' || p_device_code_hash, 0)
  );
  perform elevate_internal.lock_refresh_capability_v1(
    p_proposed_refresh_token_hash
  );
  -- Lock waits can be arbitrarily long; never classify against the function's
  -- entry timestamp.
  v_now := clock_timestamp();

  for v_attempt in 1..2 loop
    v_grant_id := null;
    select device_grant.id,
           device_grant.proposed_refresh_token_hash,
           device_grant.user_code,
           device_grant.status,
           device_grant.expires_at,
           device_grant.user_id,
           device_grant.license_id,
           device_grant.refresh_token_plain is null,
           device_grant.claim_retry_until
      into v_grant_id,
           v_proposed_hash,
           v_user_code,
           v_status,
           v_expires_at,
           v_user_id,
           v_license_id,
           v_plaintext_is_clear,
           v_claim_retry_until
      from public.device_grants as device_grant
     where device_grant.device_code_hash = p_device_code_hash
     for update;
    -- A direct v2 update can also make the row lock wait after the advisory
    -- locks were acquired.
    v_now := clock_timestamp();

    if found then
      if v_proposed_hash is distinct from p_proposed_refresh_token_hash then
        return jsonb_build_object('result', 'conflict');
      end if;

      if v_status = 'pending' then
        if v_expires_at <= v_now then
          update public.device_grants
             set status = 'expired',
                 refresh_token_plain = null,
                 claim_retry_until = null
           where id = v_grant_id;
          return jsonb_build_object('result', 'expired');
        end if;
        if v_user_id is null
           and v_license_id is null
           and v_plaintext_is_clear
           and v_claim_retry_until is null then
          if exists (
            select 1
              from public.licenses as license
             where license.refresh_token_hash = p_proposed_refresh_token_hash
                or license.previous_refresh_token_hash = p_proposed_refresh_token_hash
          ) then
            return jsonb_build_object('result', 'conflict');
          end if;
          return jsonb_build_object(
            'result', 'replay',
            'user_code', v_user_code,
            'expires_at', v_expires_at
          );
        end if;
        return jsonb_build_object('result', 'conflict');
      end if;

      if v_status = 'approved' then
        if v_expires_at <= v_now then
          if v_license_id is not null then
            update public.licenses
               set revoked = true
             where id = v_license_id
               and user_id = v_user_id
               and (
                 refresh_token_hash = p_proposed_refresh_token_hash
                 or previous_refresh_token_hash = p_proposed_refresh_token_hash
               );
          end if;
          update public.device_grants
             set status = 'expired',
                 refresh_token_plain = null,
                 claim_retry_until = null
           where id = v_grant_id;
          return jsonb_build_object('result', 'expired');
        end if;
        if v_user_id is not null
           and v_license_id is not null
           and v_plaintext_is_clear
           and exists (
             select 1
               from public.licenses as license
              where license.id = v_license_id
                and license.user_id = v_user_id
                and (
                  license.refresh_token_hash = p_proposed_refresh_token_hash
                  or license.previous_refresh_token_hash = p_proposed_refresh_token_hash
                )
           ) then
          return jsonb_build_object(
            'result', 'resume_poll',
            'grant_status', 'approved'
          );
        end if;
        return jsonb_build_object('result', 'conflict');
      end if;

      if v_status = 'claimed' then
        if v_user_id is not null
           and v_license_id is not null
           and v_plaintext_is_clear
           and exists (
             select 1
               from public.licenses as license
              where license.id = v_license_id
                and license.user_id = v_user_id
                and (
                  license.refresh_token_hash = p_proposed_refresh_token_hash
                  or license.previous_refresh_token_hash = p_proposed_refresh_token_hash
                )
           ) then
          return jsonb_build_object(
            'result', 'resume_poll',
            'grant_status', 'claimed'
          );
        end if;
        return jsonb_build_object('result', 'conflict');
      end if;

      if v_status = 'denied' then
        return jsonb_build_object('result', 'denied');
      end if;
      if v_status = 'expired' then
        return jsonb_build_object('result', 'expired');
      end if;
      return jsonb_build_object('result', 'conflict');
    end if;

    -- B may already belong to a different device start or any live/recovery
    -- slot in a license lineage. Never reveal which collision occurred.
    if exists (
      select 1
        from public.device_grants as device_grant
       where device_grant.proposed_refresh_token_hash = p_proposed_refresh_token_hash
    ) or exists (
      select 1
        from public.licenses as license
       where license.refresh_token_hash = p_proposed_refresh_token_hash
          or license.previous_refresh_token_hash = p_proposed_refresh_token_hash
    ) then
      return jsonb_build_object('result', 'conflict');
    end if;

    if exists (
      select 1
        from public.device_grants as device_grant
       where device_grant.user_code = p_user_code
    ) then
      return jsonb_build_object('result', 'user_code_conflict');
    end if;

    v_now := clock_timestamp();
    if p_expires_at <= v_now then
      return jsonb_build_object('result', 'expired');
    end if;

    begin
      insert into public.device_grants (
        user_code,
        device_code_hash,
        proposed_refresh_token_hash,
        device_label,
        ip_addr,
        user_agent,
        expires_at,
        refresh_token_plain,
        claim_retry_until
      ) values (
        p_user_code,
        p_device_code_hash,
        p_proposed_refresh_token_hash,
        p_device_label,
        p_ip_addr,
        p_user_agent,
        p_expires_at,
        null,
        null
      ) returning id into v_grant_id;

      return jsonb_build_object(
        'result', 'created',
        'user_code', p_user_code,
        'expires_at', p_expires_at
      );
    exception when unique_violation then
      -- A v2 route or direct insert may have committed while this transaction
      -- waited. Re-read once and classify it without exposing either hash.
      if v_attempt = 2 then
        return jsonb_build_object('result', 'conflict');
      end if;
    end;
  end loop;

  return jsonb_build_object('result', 'conflict');
end;
$$;

-- Preserve the previously tested implementations verbatim inside the private
-- schema. The public signatures stay stable and become lock/collision guards.
alter function public.rotate_license_refresh_v2(text, text, text)
  set schema elevate_internal;
alter function public.approve_device_grant_atomic_v2(uuid, uuid)
  set schema elevate_internal;
alter function public.issue_existing_user_license_v2(uuid, text, text, text)
  set schema elevate_internal;
alter function public.signup_with_license_v2(text, text, text, text, text, text)
  set schema elevate_internal;
alter function public.replay_signup_license_v2(uuid, text, text)
  set schema elevate_internal;

-- Reassert the trusted lookup boundary after the schema move instead of
-- relying on inherited function metadata from an earlier migration.
alter function elevate_internal.rotate_license_refresh_v2(text, text, text)
  set search_path = public, pg_temp;
alter function elevate_internal.approve_device_grant_atomic_v2(uuid, uuid)
  set search_path = public, pg_temp;
alter function elevate_internal.issue_existing_user_license_v2(uuid, text, text, text)
  set search_path = public, pg_temp;
alter function elevate_internal.signup_with_license_v2(text, text, text, text, text, text)
  set search_path = public, pg_temp;
alter function elevate_internal.replay_signup_license_v2(uuid, text, text)
  set search_path = public, pg_temp;

create or replace function public.rotate_license_refresh_v2(
  p_current_refresh_token_hash text,
  p_next_refresh_token_hash text,
  p_refresh_attempt_hash text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz;
  v_license_id uuid;
  v_revoked boolean;
  v_family_expires_at timestamptz;
begin
  if p_current_refresh_token_hash is null
     or p_current_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or p_next_refresh_token_hash is null
     or p_next_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or p_refresh_attempt_hash is null
     or p_refresh_attempt_hash !~ '^[0-9a-f]{64}$'
     or p_current_refresh_token_hash = p_next_refresh_token_hash then
    raise exception 'invalid refresh v2 token material' using errcode = '22023';
  end if;

  perform elevate_internal.lock_refresh_capability_v1(
    p_next_refresh_token_hash
  );

  if not exists (
    select 1
      from public.device_grants as device_grant
     where device_grant.proposed_refresh_token_hash = p_next_refresh_token_hash
  ) then
    return elevate_internal.rotate_license_refresh_v2(
      p_current_refresh_token_hash,
      p_next_refresh_token_hash,
      p_refresh_attempt_hash
    );
  end if;

  -- A device grant owns B. Match the existing Refresh v2 collision semantics:
  -- a valid live source family is revoked; invalid/revoked/expired families
  -- keep their prior classifications.
  select license.id,
         license.revoked,
         license.refresh_family_expires_at
    into v_license_id,
         v_revoked,
         v_family_expires_at
    from public.licenses as license
   where license.refresh_token_hash = p_current_refresh_token_hash
      or license.previous_refresh_token_hash = p_current_refresh_token_hash
   order by case
              when license.refresh_token_hash = p_current_refresh_token_hash then 0
              else 1
            end,
            license.created_at desc,
            license.id desc
   limit 1
   for update;

  if not found or v_revoked then
    return jsonb_build_object('result', 'invalid');
  end if;
  v_now := clock_timestamp();
  if v_family_expires_at <= v_now then
    update public.licenses set revoked = true where id = v_license_id;
    return jsonb_build_object('result', 'expired');
  end if;

  update public.licenses set revoked = true where id = v_license_id;
  return jsonb_build_object('result', 'conflict');
end;
$$;

create or replace function public.approve_device_grant_atomic_v2(
  p_grant_id uuid,
  p_user_id uuid
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_proposed_hash text;
  v_locked_proposed_hash text;
  v_locked_status public.device_grant_status;
  v_user_status public.user_status;
begin
  if p_grant_id is null or p_user_id is null then
    raise exception 'invalid device v2 approval parameters' using errcode = '22023';
  end if;

  -- This first read is deliberately not a row lock. B must be acquired before
  -- any durable grant/user/license row lock.
  select device_grant.proposed_refresh_token_hash
    into v_proposed_hash
    from public.device_grants as device_grant
   where device_grant.id = p_grant_id;

  if found and v_proposed_hash ~ '^[0-9a-f]{64}$' then
    perform elevate_internal.lock_refresh_capability_v1(v_proposed_hash);
  end if;

  -- Use the global Device order: B, then grant, then user. Claim already takes
  -- grant -> license -> user, so a repeat approval must not hold user while
  -- waiting for claim's grant row. Taking both locks before delegation also
  -- means the internal function's entry clock is sampled only after every
  -- possible wait.

  -- Bind the capability lock to the grant before continuing. A concurrent
  -- proposal update may have committed while the wrapper waited for B;
  -- the original implementation must never approve that replacement B under
  -- the stale lock.
  select device_grant.proposed_refresh_token_hash,
         device_grant.status
    into v_locked_proposed_hash,
         v_locked_status
    from public.device_grants as device_grant
   where device_grant.id = p_grant_id
   for update;

  if found
     and v_proposed_hash ~ '^[0-9a-f]{64}$'
     and v_locked_proposed_hash is distinct from v_proposed_hash then
    return jsonb_build_object(
      'result', 'conflict',
      'grant_status', v_locked_status::text
    );
  end if;

  select app_user.status
    into v_user_status
    from public.users as app_user
   where app_user.id = p_user_id
   for update;

  if not found or v_user_status not in ('active', 'trialing') then
    raise exception 'device approver is not active' using errcode = 'P0001';
  end if;

  -- The internal user/grant locks are same-transaction reentrant and cannot
  -- wait, so its entry timestamp is fresh for expiry and approved_at.

  return elevate_internal.approve_device_grant_atomic_v2(
    p_grant_id,
    p_user_id
  );
end;
$$;

create or replace function public.issue_existing_user_license_v2(
  p_user_id uuid,
  p_expected_password_hash text,
  p_refresh_token_hash text,
  p_device_label text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if p_user_id is null
     or p_expected_password_hash is null
     or length(p_expected_password_hash) < 50
     or length(p_expected_password_hash) > 100
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid initial issuance material' using errcode = '22023';
  end if;

  perform elevate_internal.lock_refresh_capability_v1(p_refresh_token_hash);
  if exists (
    select 1
      from public.device_grants as device_grant
     where device_grant.proposed_refresh_token_hash = p_refresh_token_hash
  ) then
    return jsonb_build_object('result', 'collision');
  end if;

  return elevate_internal.issue_existing_user_license_v2(
    p_user_id,
    p_expected_password_hash,
    p_refresh_token_hash,
    p_device_label
  );
end;
$$;

create or replace function public.signup_with_license_v2(
  p_email text,
  p_password_hash text,
  p_first_name text,
  p_last_name text,
  p_refresh_token_hash text,
  p_device_label text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if p_email is null
     or p_email = ''
     or p_email <> lower(btrim(p_email))
     or length(p_email) > 320
     or p_password_hash is null
     or length(p_password_hash) < 50
     or length(p_password_hash) > 100
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or (p_first_name is not null and (
       p_first_name <> btrim(p_first_name)
       or length(p_first_name) < 1
       or length(p_first_name) > 100
     ))
     or (p_last_name is not null and (
       p_last_name <> btrim(p_last_name)
       or length(p_last_name) < 1
       or length(p_last_name) > 100
     )) then
    raise exception 'invalid signup issuance material' using errcode = '22023';
  end if;

  perform elevate_internal.lock_refresh_capability_v1(p_refresh_token_hash);
  if exists (
    select 1
      from public.device_grants as device_grant
     where device_grant.proposed_refresh_token_hash = p_refresh_token_hash
  ) then
    return jsonb_build_object('result', 'collision');
  end if;

  return elevate_internal.signup_with_license_v2(
    p_email,
    p_password_hash,
    p_first_name,
    p_last_name,
    p_refresh_token_hash,
    p_device_label
  );
end;
$$;

create or replace function public.replay_signup_license_v2(
  p_user_id uuid,
  p_expected_password_hash text,
  p_refresh_token_hash text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  if p_user_id is null
     or p_expected_password_hash is null
     or length(p_expected_password_hash) < 50
     or length(p_expected_password_hash) > 100
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid signup replay material' using errcode = '22023';
  end if;

  perform elevate_internal.lock_refresh_capability_v1(p_refresh_token_hash);
  if exists (
    select 1
      from public.device_grants as device_grant
     where device_grant.proposed_refresh_token_hash = p_refresh_token_hash
  ) then
    return jsonb_build_object('result', 'invalid');
  end if;

  return elevate_internal.replay_signup_license_v2(
    p_user_id,
    p_expected_password_hash,
    p_refresh_token_hash
  );
end;
$$;

revoke execute on function public.start_device_grant_atomic_v3(
  text, text, text, text, text, text, timestamptz
) from public, anon, authenticated;
grant execute on function public.start_device_grant_atomic_v3(
  text, text, text, text, text, text, timestamptz
) to service_role;

revoke execute on function elevate_internal.lock_refresh_capability_v1(text)
  from public, anon, authenticated;
grant execute on function elevate_internal.lock_refresh_capability_v1(text)
  to service_role;
revoke execute on function elevate_internal.lock_device_grant_capability_v1()
  from public, anon, authenticated;
grant execute on function elevate_internal.lock_device_grant_capability_v1()
  to service_role;

revoke execute on function public.rotate_license_refresh_v2(text, text, text)
  from public, anon, authenticated;
grant execute on function public.rotate_license_refresh_v2(text, text, text)
  to service_role;
revoke execute on function public.approve_device_grant_atomic_v2(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.approve_device_grant_atomic_v2(uuid, uuid)
  to service_role;
revoke execute on function public.issue_existing_user_license_v2(uuid, text, text, text)
  from public, anon, authenticated;
grant execute on function public.issue_existing_user_license_v2(uuid, text, text, text)
  to service_role;
revoke execute on function public.signup_with_license_v2(text, text, text, text, text, text)
  from public, anon, authenticated;
grant execute on function public.signup_with_license_v2(text, text, text, text, text, text)
  to service_role;
revoke execute on function public.replay_signup_license_v2(uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.replay_signup_license_v2(uuid, text, text)
  to service_role;

revoke execute on function elevate_internal.rotate_license_refresh_v2(text, text, text)
  from public, anon, authenticated;
grant execute on function elevate_internal.rotate_license_refresh_v2(text, text, text)
  to service_role;
revoke execute on function elevate_internal.approve_device_grant_atomic_v2(uuid, uuid)
  from public, anon, authenticated;
grant execute on function elevate_internal.approve_device_grant_atomic_v2(uuid, uuid)
  to service_role;
revoke execute on function elevate_internal.issue_existing_user_license_v2(uuid, text, text, text)
  from public, anon, authenticated;
grant execute on function elevate_internal.issue_existing_user_license_v2(uuid, text, text, text)
  to service_role;
revoke execute on function elevate_internal.signup_with_license_v2(text, text, text, text, text, text)
  from public, anon, authenticated;
grant execute on function elevate_internal.signup_with_license_v2(text, text, text, text, text, text)
  to service_role;
revoke execute on function elevate_internal.replay_signup_license_v2(uuid, text, text)
  from public, anon, authenticated;
grant execute on function elevate_internal.replay_signup_license_v2(uuid, text, text)
  to service_role;

-- One service-role-only, read-only deployment gate. The application health
-- route calls this instead of attempting a write or inferring readiness from
-- a successful connection. Every result field is a boolean/public version
-- label; no row contents or configuration values leave PostgreSQL.
create or replace function public.elevate_hq_schema_readiness_v1()
returns jsonb
language plpgsql
stable
security invoker
set search_path = pg_catalog, public, pg_temp
as $$
declare
  function_signature text;
  v_tables_ready boolean;
  v_columns_ready boolean;
  v_constraints_ready boolean;
  v_indexes_ready boolean;
  v_rpcs_ready boolean := true;
  v_triggers_ready boolean;
  v_privileges_ready boolean;
  v_data_invariants_ready boolean;
  v_initial_issuance_v2_ready boolean;
  v_ready boolean;
begin
  v_tables_ready :=
    to_regclass('public.session_diagnostic_events') is not null
    and to_regclass('public.app_crash_reports') is not null
    and coalesce((
      select relation.relrowsecurity
        from pg_catalog.pg_class as relation
       where relation.oid = to_regclass('public.session_diagnostic_events')
    ), false)
    and coalesce((
      select relation.relrowsecurity
        from pg_catalog.pg_class as relation
       where relation.oid = to_regclass('public.app_crash_reports')
    ), false);

  v_columns_ready := (
    select count(*) = 6
      from information_schema.columns
     where table_schema = 'public'
       and (
         (table_name = 'licenses' and column_name in (
           'previous_refresh_token_hash',
           'previous_refresh_attempt_hash',
           'refresh_family_expires_at',
           'initial_issuance_kind'
         ))
         or
         (table_name = 'device_grants' and column_name in (
           'proposed_refresh_token_hash',
           'claim_retry_until'
         ))
       )
  ) and coalesce((
    select attribute.attnotnull
      from pg_catalog.pg_attribute as attribute
     where attribute.attrelid = to_regclass('public.licenses')
       and attribute.attname = 'refresh_family_expires_at'
       and not attribute.attisdropped
  ), false);

  v_constraints_ready := (
    select count(*) = 4
      from pg_catalog.pg_constraint as constraint_row
     where (
       (
         constraint_row.conrelid = to_regclass('public.licenses')
         and constraint_row.conname = 'licenses_initial_issuance_kind_check'
       ) or (
         constraint_row.conrelid = to_regclass('public.device_grants')
         and constraint_row.conname in (
           'device_grants_proposed_refresh_hash_format_ck',
           'device_grants_v2_plaintext_exclusive_ck',
           'device_grants_claim_retry_window_ck'
         )
       )
     )
     and constraint_row.convalidated
  );

  v_indexes_ready := (
    select count(*) = 9
      from pg_catalog.pg_class as relation
      join pg_catalog.pg_namespace as namespace
        on namespace.oid = relation.relnamespace
      join pg_catalog.pg_index as index_row
        on index_row.indexrelid = relation.oid
     where namespace.nspname = 'public'
       and relation.relkind = 'i'
       and index_row.indisvalid
       and index_row.indisready
       and relation.relname in (
         'session_diagnostic_events_user_created_idx',
         'session_diagnostic_events_session_created_idx',
         'session_diagnostic_events_event_created_idx',
         'app_crash_reports_user_created_idx',
         'app_crash_reports_version_created_idx',
         'app_crash_reports_kind_created_idx',
         'login_codes_one_unconsumed_per_user_idx',
         'licenses_previous_refresh_token_hash_idx',
         'device_grants_proposed_refresh_token_hash_uidx'
       )
       and (
         relation.relname not in (
           'login_codes_one_unconsumed_per_user_idx',
           'device_grants_proposed_refresh_token_hash_uidx'
         )
         or index_row.indisunique
       )
       and (
         relation.relname not in (
           'login_codes_one_unconsumed_per_user_idx',
           'licenses_previous_refresh_token_hash_idx',
           'device_grants_proposed_refresh_token_hash_uidx'
         )
         or index_row.indpred is not null
       )
  );

  foreach function_signature in array array[
    'public.check_rate_limit(text,integer,integer)',
    'public.approve_device_grant_atomic(uuid,uuid,text,text)',
    'public.issue_login_code_atomic(uuid,text,timestamp with time zone,text,text)',
    'public.record_login_code_attempt_atomic(uuid,uuid,text,integer)',
    'public.redeem_login_code_atomic(uuid,uuid,text,uuid,text,text,integer)',
    'public.add_org_membership_atomic(uuid,uuid,public.org_role)',
    'public.create_org_with_owner_atomic(uuid,uuid,text,text)',
    'public.accept_invitation_atomic(uuid,text,uuid,text,uuid,text)',
    'public.start_device_grant_atomic_v3(text,text,text,text,text,text,timestamp with time zone)',
    'public.rotate_license_refresh_v2(text,text,text)',
    'public.approve_device_grant_atomic_v2(uuid,uuid)',
    'public.poll_device_grant_pending_v2(text,text)',
    'public.claim_device_grant_atomic_v2(text,text)',
    'public.expire_stale_device_grants_v2()',
    'public.issue_existing_user_license_v2(uuid,text,text,text)',
    'public.signup_with_license_v2(text,text,text,text,text,text)',
    'public.replay_signup_license_v2(uuid,text,text)',
    'public.elevate_hq_schema_readiness_v1()',
    'elevate_internal.lock_refresh_capability_v1(text)',
    'elevate_internal.lock_device_grant_capability_v1()',
    'elevate_internal.rotate_license_refresh_v2(text,text,text)',
    'elevate_internal.approve_device_grant_atomic_v2(uuid,uuid)',
    'elevate_internal.issue_existing_user_license_v2(uuid,text,text,text)',
    'elevate_internal.signup_with_license_v2(text,text,text,text,text,text)',
    'elevate_internal.replay_signup_license_v2(uuid,text,text)'
  ]
  loop
    if to_regprocedure(function_signature) is null then
      v_rpcs_ready := false;
    end if;
  end loop;

  foreach function_signature in array array[
    'rotate_license_refresh_v2(text,text,text)',
    'approve_device_grant_atomic_v2(uuid,uuid)',
    'issue_existing_user_license_v2(uuid,text,text,text)',
    'signup_with_license_v2(text,text,text,text,text,text)',
    'replay_signup_license_v2(uuid,text,text)'
  ]
  loop
    if to_regprocedure('public.' || function_signature) is null
       or to_regprocedure('elevate_internal.' || function_signature) is null
       or position(
         'elevate_internal.' in pg_catalog.pg_get_functiondef(
           to_regprocedure('public.' || function_signature)
         )
       ) = 0 then
      v_rpcs_ready := false;
    end if;
  end loop;

  v_triggers_ready :=
    to_regnamespace('elevate_internal') is not null
    and exists (
      select 1
        from pg_catalog.pg_trigger as trigger_row
       where trigger_row.tgrelid = to_regclass('public.device_grants')
         and trigger_row.tgname = 'device_grants_capability_lock_v1'
         and not trigger_row.tgisinternal
         and trigger_row.tgenabled in ('O', 'A')
         and trigger_row.tgfoid = to_regprocedure(
           'elevate_internal.lock_device_grant_capability_v1()'
         )
    );

  v_privileges_ready :=
    pg_catalog.has_schema_privilege('service_role', 'elevate_internal', 'USAGE')
    and not pg_catalog.has_schema_privilege('anon', 'elevate_internal', 'USAGE')
    and not pg_catalog.has_schema_privilege('authenticated', 'elevate_internal', 'USAGE');

  if v_tables_ready then
    v_privileges_ready := v_privileges_ready
      and pg_catalog.has_table_privilege(
        'service_role', 'public.session_diagnostic_events', 'SELECT'
      )
      and pg_catalog.has_table_privilege(
        'service_role', 'public.session_diagnostic_events', 'INSERT'
      )
      and pg_catalog.has_table_privilege(
        'service_role', 'public.app_crash_reports', 'SELECT'
      )
      and pg_catalog.has_table_privilege(
        'service_role', 'public.app_crash_reports', 'INSERT'
      )
      and not pg_catalog.has_table_privilege(
        'anon', 'public.session_diagnostic_events', 'SELECT'
      )
      and not pg_catalog.has_table_privilege(
        'anon', 'public.session_diagnostic_events', 'INSERT'
      )
      and not pg_catalog.has_table_privilege(
        'authenticated', 'public.session_diagnostic_events', 'SELECT'
      )
      and not pg_catalog.has_table_privilege(
        'authenticated', 'public.session_diagnostic_events', 'INSERT'
      )
      and not pg_catalog.has_table_privilege(
        'anon', 'public.app_crash_reports', 'SELECT'
      )
      and not pg_catalog.has_table_privilege(
        'anon', 'public.app_crash_reports', 'INSERT'
      )
      and not pg_catalog.has_table_privilege(
        'authenticated', 'public.app_crash_reports', 'SELECT'
      )
      and not pg_catalog.has_table_privilege(
        'authenticated', 'public.app_crash_reports', 'INSERT'
      );
  else
    v_privileges_ready := false;
  end if;

  foreach function_signature in array array[
    'public.check_rate_limit(text,integer,integer)',
    'public.approve_device_grant_atomic(uuid,uuid,text,text)',
    'public.issue_login_code_atomic(uuid,text,timestamp with time zone,text,text)',
    'public.record_login_code_attempt_atomic(uuid,uuid,text,integer)',
    'public.redeem_login_code_atomic(uuid,uuid,text,uuid,text,text,integer)',
    'public.add_org_membership_atomic(uuid,uuid,public.org_role)',
    'public.create_org_with_owner_atomic(uuid,uuid,text,text)',
    'public.accept_invitation_atomic(uuid,text,uuid,text,uuid,text)',
    'public.start_device_grant_atomic_v3(text,text,text,text,text,text,timestamp with time zone)',
    'public.rotate_license_refresh_v2(text,text,text)',
    'public.approve_device_grant_atomic_v2(uuid,uuid)',
    'public.poll_device_grant_pending_v2(text,text)',
    'public.claim_device_grant_atomic_v2(text,text)',
    'public.expire_stale_device_grants_v2()',
    'public.issue_existing_user_license_v2(uuid,text,text,text)',
    'public.signup_with_license_v2(text,text,text,text,text,text)',
    'public.replay_signup_license_v2(uuid,text,text)',
    'public.elevate_hq_schema_readiness_v1()',
    'elevate_internal.lock_refresh_capability_v1(text)',
    'elevate_internal.lock_device_grant_capability_v1()',
    'elevate_internal.rotate_license_refresh_v2(text,text,text)',
    'elevate_internal.approve_device_grant_atomic_v2(uuid,uuid)',
    'elevate_internal.issue_existing_user_license_v2(uuid,text,text,text)',
    'elevate_internal.signup_with_license_v2(text,text,text,text,text,text)',
    'elevate_internal.replay_signup_license_v2(uuid,text,text)'
  ]
  loop
    if to_regprocedure(function_signature) is null
       or not pg_catalog.has_function_privilege(
         'service_role', function_signature, 'EXECUTE'
       )
       or pg_catalog.has_function_privilege('anon', function_signature, 'EXECUTE')
       or pg_catalog.has_function_privilege(
         'authenticated', function_signature, 'EXECUTE'
       ) then
      v_privileges_ready := false;
    end if;
  end loop;

  v_data_invariants_ready := false;
  if to_regclass('public.licenses') is not null
     and to_regclass('public.login_codes') is not null
     and to_regclass('public.device_grants') is not null then
    v_data_invariants_ready :=
      not exists (
        select 1
          from public.licenses
         where refresh_family_expires_at is null
      )
      and not exists (
        select 1
          from public.login_codes
         where consumed_at is null
         group by user_id
        having count(*) > 1
      )
      and not exists (
        select 1
          from public.device_grants
         where proposed_refresh_token_hash is not null
           and refresh_token_plain is not null
      );
  end if;

  v_initial_issuance_v2_ready :=
    v_columns_ready
    and v_constraints_ready
    and to_regprocedure(
      'public.issue_existing_user_license_v2(uuid,text,text,text)'
    ) is not null
    and to_regprocedure(
      'public.signup_with_license_v2(text,text,text,text,text,text)'
    ) is not null
    and to_regprocedure(
      'public.replay_signup_license_v2(uuid,text,text)'
    ) is not null
    and to_regprocedure(
      'elevate_internal.issue_existing_user_license_v2(uuid,text,text,text)'
    ) is not null
    and to_regprocedure(
      'elevate_internal.signup_with_license_v2(text,text,text,text,text,text)'
    ) is not null
    and to_regprocedure(
      'elevate_internal.replay_signup_license_v2(uuid,text,text)'
    ) is not null;

  v_ready :=
    v_tables_ready
    and v_columns_ready
    and v_constraints_ready
    and v_indexes_ready
    and v_rpcs_ready
    and v_triggers_ready
    and v_privileges_ready
    and v_data_invariants_ready
    and v_initial_issuance_v2_ready;

  return pg_catalog.jsonb_build_object(
    'contract', 'elevate-hq-schema-readiness-v1',
    'schema_version', '0020',
    'ready', v_ready,
    'tables_ready', v_tables_ready,
    'columns_ready', v_columns_ready,
    'constraints_ready', v_constraints_ready,
    'indexes_ready', v_indexes_ready,
    'rpcs_ready', v_rpcs_ready,
    'triggers_ready', v_triggers_ready,
    'privileges_ready', v_privileges_ready,
    'data_invariants_ready', v_data_invariants_ready,
    'initial_issuance_v2_ready', v_initial_issuance_v2_ready
  );
end;
$$;

revoke execute on function public.elevate_hq_schema_readiness_v1()
  from public, anon, authenticated;
grant execute on function public.elevate_hq_schema_readiness_v1()
  to service_role;
