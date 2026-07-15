-- Exact-Beta login and signup can recover a discarded successful response
-- without storing plaintext bearer material. The client proposes the initial
-- refresh capability; only its SHA-256 hash enters PostgreSQL.

alter table public.licenses
  add column if not exists initial_issuance_kind text;

do $$
begin
  if not exists (
    select 1
      from pg_constraint
     where conname = 'licenses_initial_issuance_kind_check'
       and conrelid = 'public.licenses'::regclass
  ) then
    alter table public.licenses
      add constraint licenses_initial_issuance_kind_check
      check (
        initial_issuance_kind is null
        or initial_issuance_kind = 'signup'
      );
  end if;
end
$$;

comment on column public.licenses.initial_issuance_kind is
  'Bounded source proof for replay-only initial issuance; null for legacy, login, and device licenses.';

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
declare
  v_now timestamptz := clock_timestamp();
  v_user_id uuid;
  v_user_email text;
  v_user_password_hash text;
  v_user_status public.user_status;
  v_license_id uuid;
  v_license_user_id uuid;
  v_current_hash text;
  v_previous_hash text;
  v_family_expires_at timestamptz;
  v_revoked boolean;
begin
  if p_user_id is null
     or p_expected_password_hash is null
     or length(p_expected_password_hash) < 50
     or length(p_expected_password_hash) > 100
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid initial issuance material' using errcode = '22023';
  end if;

  -- Serialize all login/signup v2 attempts proposing the same capability.
  -- This closes the no-row unique-index race before the license exists.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('elevate-initial-refresh-v2:' || p_refresh_token_hash, 0)
  );

  -- Lock token lineage before the user row, matching Refresh v2's lock order.
  -- A rotated B remains visible through previous_refresh_token_hash and can
  -- never be reinserted as a new current token.
  select license.id,
         license.user_id,
         license.refresh_token_hash,
         license.previous_refresh_token_hash,
         license.refresh_family_expires_at,
         license.revoked
    into v_license_id,
         v_license_user_id,
         v_current_hash,
         v_previous_hash,
         v_family_expires_at,
         v_revoked
    from public.licenses as license
   where license.refresh_token_hash = p_refresh_token_hash
      or license.previous_refresh_token_hash = p_refresh_token_hash
   order by case
              when license.previous_refresh_token_hash = p_refresh_token_hash then 0
              else 1
            end,
            license.created_at desc,
            license.id desc
   limit 1
   for update;

  select app_user.id,
         app_user.email,
         app_user.password_hash,
         app_user.status
    into v_user_id,
         v_user_email,
         v_user_password_hash,
         v_user_status
    from public.users as app_user
   where app_user.id = p_user_id
   for update;

  if not found or v_user_password_hash is distinct from p_expected_password_hash then
    return jsonb_build_object('result', 'invalid');
  end if;

  if v_user_status not in ('active', 'trialing') then
    return jsonb_build_object('result', 'inactive');
  end if;

  if v_license_id is not null then
    if v_previous_hash = p_refresh_token_hash
       or v_current_hash <> p_refresh_token_hash
       or v_license_user_id <> v_user_id
       or v_revoked
       or v_family_expires_at is null
       or v_family_expires_at <= v_now then
      return jsonb_build_object('result', 'collision');
    end if;

    return jsonb_build_object(
      'result', 'replay',
      'license_id', v_license_id,
      'user_id', v_user_id,
      'email', v_user_email
    );
  end if;

  begin
    insert into public.licenses (
      user_id,
      device_label,
      refresh_token_hash,
      initial_issuance_kind
    ) values (
      v_user_id,
      p_device_label,
      p_refresh_token_hash,
      null
    )
    returning id into v_license_id;
  exception
    when unique_violation then
      -- Another issuance surface won a token collision. Never convert the
      -- losing request into credentials from an identity we did not prove.
      return jsonb_build_object('result', 'collision');
  end;

  return jsonb_build_object(
    'result', 'issued',
    'license_id', v_license_id,
    'user_id', v_user_id,
    'email', v_user_email
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
declare
  v_existing_user_id uuid;
  v_user_id uuid;
  v_user_email text;
  v_user_tier public.user_tier;
  v_user_status public.user_status;
  v_license_id uuid;
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

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('elevate-initial-refresh-v2:' || p_refresh_token_hash, 0)
  );

  select app_user.id
    into v_existing_user_id
    from public.users as app_user
   where app_user.email = p_email
   for update;

  if found then
    return jsonb_build_object('result', 'email_conflict');
  end if;

  -- An already-used current or predecessor capability belongs to another
  -- transaction. The separate replay RPC is the only existing-account path.
  if exists (
    select 1
      from public.licenses as license
     where license.refresh_token_hash = p_refresh_token_hash
        or license.previous_refresh_token_hash = p_refresh_token_hash
  ) then
    return jsonb_build_object('result', 'collision');
  end if;

  begin
    insert into public.users (
      email,
      password_hash,
      entitlements,
      first_name,
      last_name
    ) values (
      p_email,
      p_password_hash,
      '{}'::text[],
      p_first_name,
      p_last_name
    )
    returning id, email, tier, status
      into v_user_id, v_user_email, v_user_tier, v_user_status;

    insert into public.licenses (
      user_id,
      device_label,
      refresh_token_hash,
      initial_issuance_kind
    ) values (
      v_user_id,
      p_device_label,
      p_refresh_token_hash,
      'signup'
    )
    returning id into v_license_id;
  exception
    when unique_violation then
      -- The subtransaction rolls back both inserts before classification.
      if exists (
        select 1 from public.users as app_user where app_user.email = p_email
      ) then
        return jsonb_build_object('result', 'email_conflict');
      end if;
      return jsonb_build_object('result', 'collision');
  end;

  return jsonb_build_object(
    'result', 'created',
    'license_id', v_license_id,
    'user', jsonb_build_object(
      'id', v_user_id,
      'email', v_user_email,
      'tier', v_user_tier,
      'status', v_user_status
    )
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
declare
  v_now timestamptz := clock_timestamp();
  v_user_id uuid;
  v_user_email text;
  v_user_password_hash text;
  v_user_tier public.user_tier;
  v_user_status public.user_status;
  v_license_id uuid;
  v_license_user_id uuid;
  v_current_hash text;
  v_previous_hash text;
  v_family_expires_at timestamptz;
  v_revoked boolean;
  v_initial_issuance_kind text;
begin
  if p_user_id is null
     or p_expected_password_hash is null
     or length(p_expected_password_hash) < 50
     or length(p_expected_password_hash) > 100
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid signup replay material' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('elevate-initial-refresh-v2:' || p_refresh_token_hash, 0)
  );

  select license.id,
         license.user_id,
         license.refresh_token_hash,
         license.previous_refresh_token_hash,
         license.refresh_family_expires_at,
         license.revoked,
         license.initial_issuance_kind
    into v_license_id,
         v_license_user_id,
         v_current_hash,
         v_previous_hash,
         v_family_expires_at,
         v_revoked,
         v_initial_issuance_kind
    from public.licenses as license
   where license.refresh_token_hash = p_refresh_token_hash
      or license.previous_refresh_token_hash = p_refresh_token_hash
   order by case
              when license.previous_refresh_token_hash = p_refresh_token_hash then 0
              else 1
            end,
            license.created_at desc,
            license.id desc
   limit 1
   for update;

  if not found
     or v_previous_hash = p_refresh_token_hash
     or v_previous_hash is not null
     or v_current_hash <> p_refresh_token_hash
     or v_license_user_id <> p_user_id
     or v_initial_issuance_kind <> 'signup'
     or v_revoked
     or v_family_expires_at is null
     or v_family_expires_at <= v_now then
    return jsonb_build_object('result', 'invalid');
  end if;

  select app_user.id,
         app_user.email,
         app_user.password_hash,
         app_user.tier,
         app_user.status
    into v_user_id,
         v_user_email,
         v_user_password_hash,
         v_user_tier,
         v_user_status
    from public.users as app_user
   where app_user.id = p_user_id
   for update;

  if not found or v_user_password_hash is distinct from p_expected_password_hash then
    return jsonb_build_object('result', 'invalid');
  end if;

  if v_user_status not in ('active', 'trialing') then
    return jsonb_build_object('result', 'inactive');
  end if;

  return jsonb_build_object(
    'result', 'replay',
    'license_id', v_license_id,
    'user', jsonb_build_object(
      'id', v_user_id,
      'email', v_user_email,
      'tier', v_user_tier,
      'status', v_user_status
    )
  );
end;
$$;

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
