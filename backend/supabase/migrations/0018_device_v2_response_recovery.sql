-- Device API v2 makes a discarded successful poll response recoverable
-- without ever persisting the client-proposed refresh bearer. The device
-- grant stores only SHA-256(B), and a claimed grant can replay only for a
-- fixed two-minute window while its license still has SHA-256(B) as current.

alter table public.device_grants
  add column if not exists proposed_refresh_token_hash text,
  add column if not exists claim_retry_until timestamptz;

do $$
begin
  if not exists (
    select 1
      from pg_constraint
     where conname = 'device_grants_proposed_refresh_hash_format_ck'
       and conrelid = 'public.device_grants'::regclass
  ) then
    alter table public.device_grants
      add constraint device_grants_proposed_refresh_hash_format_ck
      check (
        proposed_refresh_token_hash is null
        or proposed_refresh_token_hash ~ '^[0-9a-f]{64}$'
      );
  end if;

  if not exists (
    select 1
      from pg_constraint
     where conname = 'device_grants_v2_plaintext_exclusive_ck'
       and conrelid = 'public.device_grants'::regclass
  ) then
    alter table public.device_grants
      add constraint device_grants_v2_plaintext_exclusive_ck
      check (
        proposed_refresh_token_hash is null
        or refresh_token_plain is null
      );
  end if;

  if not exists (
    select 1
      from pg_constraint
     where conname = 'device_grants_claim_retry_window_ck'
       and conrelid = 'public.device_grants'::regclass
  ) then
    alter table public.device_grants
      add constraint device_grants_claim_retry_window_ck
      check (
        claim_retry_until is null
        or (
          proposed_refresh_token_hash is not null
          and status = 'claimed'
          and claimed_at is not null
          and claim_retry_until >= claimed_at
          and claim_retry_until <= claimed_at + interval '2 minutes'
        )
      );
  end if;
end
$$;

create unique index if not exists device_grants_proposed_refresh_token_hash_uidx
  on public.device_grants (proposed_refresh_token_hash)
  where proposed_refresh_token_hash is not null;

-- Browser approval for a v2 grant accepts no bearer material. The proposal
-- was committed at anonymous start, and this transaction creates the license
-- from that hash only after locking both the approving account and grant.
create or replace function public.approve_device_grant_atomic_v2(
  p_grant_id uuid,
  p_user_id uuid
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_user_status public.user_status;
  v_device_label text;
  v_user_code text;
  v_proposed_hash text;
  v_license_id uuid;
  v_status public.device_grant_status;
  v_expires_at timestamptz;
  v_user_id uuid;
  v_existing_license_id uuid;
  v_plaintext_is_clear boolean;
  v_row_count integer;
begin
  if p_grant_id is null or p_user_id is null then
    raise exception 'invalid device v2 approval parameters' using errcode = '22023';
  end if;

  select app_user.status
    into v_user_status
    from public.users as app_user
   where app_user.id = p_user_id
   for update;

  if not found or v_user_status not in ('active', 'trialing') then
    raise exception 'device approver is not active' using errcode = 'P0001';
  end if;

  select grant.device_label,
         grant.user_code,
         grant.proposed_refresh_token_hash,
         grant.status,
         grant.expires_at,
         grant.user_id,
         grant.license_id,
         grant.refresh_token_plain is null
    into v_device_label,
         v_user_code,
         v_proposed_hash,
         v_status,
         v_expires_at,
         v_user_id,
         v_existing_license_id,
         v_plaintext_is_clear
    from public.device_grants as grant
   where grant.id = p_grant_id
   for update;

  if not found then
    return jsonb_build_object('result', 'not_found');
  end if;

  if v_status in ('pending', 'approved') and v_expires_at <= v_now then
    if v_status = 'approved' and v_existing_license_id is not null then
      update public.licenses
         set revoked = true
       where id = v_existing_license_id;
    end if;
    update public.device_grants
       set status = 'expired',
           refresh_token_plain = null,
           claim_retry_until = null
     where id = p_grant_id;
    return jsonb_build_object('result', 'expired', 'grant_status', 'expired');
  end if;

  if v_status <> 'pending' then
    return jsonb_build_object(
      'result', 'conflict',
      'grant_status', v_status::text
    );
  end if;

  if v_user_id is not null
     or v_existing_license_id is not null
     or not v_plaintext_is_clear
     or v_proposed_hash is null
     or v_proposed_hash !~ '^[0-9a-f]{64}$' then
    update public.device_grants
       set status = 'expired',
           refresh_token_plain = null,
           claim_retry_until = null
     where id = p_grant_id;
    return jsonb_build_object('result', 'invalid', 'grant_status', 'expired');
  end if;

  if exists (
    select 1
      from public.licenses as license
     where license.refresh_token_hash = v_proposed_hash
        or license.previous_refresh_token_hash = v_proposed_hash
  ) then
    update public.device_grants
       set status = 'expired',
           claim_retry_until = null
     where id = p_grant_id;
    return jsonb_build_object('result', 'collision', 'grant_status', 'expired');
  end if;

  begin
    insert into public.licenses (
      user_id,
      refresh_token_hash,
      device_label
    ) values (
      p_user_id,
      v_proposed_hash,
      coalesce(v_device_label, 'linked-device')
    ) returning id into v_license_id;
  exception when unique_violation then
    update public.device_grants
       set status = 'expired',
           claim_retry_until = null
     where id = p_grant_id;
    return jsonb_build_object('result', 'collision', 'grant_status', 'expired');
  end;

  update public.device_grants
     set status = 'approved',
         user_id = p_user_id,
         license_id = v_license_id,
         approved_at = v_now,
         refresh_token_plain = null,
         claim_retry_until = null
   where id = p_grant_id
     and status = 'pending'
     and user_id is null
     and license_id is null
     and proposed_refresh_token_hash = v_proposed_hash
     and refresh_token_plain is null
     and expires_at > v_now;

  get diagnostics v_row_count = row_count;
  if v_row_count <> 1 then
    raise exception 'device v2 grant changed while approval was finalizing'
      using errcode = '40001';
  end if;

  insert into public.audit_log (
    actor_user_id,
    target_user_id,
    action,
    payload
  ) values (
    p_user_id,
    p_user_id,
    'device.link.approved.v2',
    jsonb_build_object(
      'grant_id', p_grant_id,
      'user_code', v_user_code,
      'device_label', v_device_label,
      'license_id', v_license_id
    )
  );

  return jsonb_build_object(
    'result', 'approved',
    'license_id', v_license_id
  );
end;
$$;

-- A route that observed a pending row must not expire or touch that stale
-- snapshot directly: browser approval may have committed in the meantime.
-- This status-only RPC serializes with approval and claim. It never claims an
-- approved grant, so the route can preflight the signer after `ready` and then
-- enter the claim RPC without risking an unissuable committed claim.
create or replace function public.poll_device_grant_pending_v2(
  p_device_code_hash text,
  p_refresh_token_hash text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_grant_id uuid;
  v_proposed_hash text;
  v_status public.device_grant_status;
  v_expires_at timestamptz;
  v_license_id uuid;
  v_plaintext_is_clear boolean;
begin
  if p_device_code_hash is null
     or p_device_code_hash !~ '^[0-9a-f]{64}$'
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid pending device v2 poll token material'
      using errcode = '22023';
  end if;

  select grant.id,
         grant.proposed_refresh_token_hash,
         grant.status,
         grant.expires_at,
         grant.license_id,
         grant.refresh_token_plain is null
    into v_grant_id,
         v_proposed_hash,
         v_status,
         v_expires_at,
         v_license_id,
         v_plaintext_is_clear
    from public.device_grants as grant
   where grant.device_code_hash = p_device_code_hash
   for update;

  if not found then
    return jsonb_build_object('result', 'not_found');
  end if;

  if v_proposed_hash is null
     or v_proposed_hash !~ '^[0-9a-f]{64}$'
     or not v_plaintext_is_clear
     or v_proposed_hash <> p_refresh_token_hash then
    return jsonb_build_object('result', 'invalid');
  end if;

  if v_status in ('pending', 'approved') and v_expires_at <= v_now then
    if v_status = 'approved' and v_license_id is not null then
      update public.licenses
         set revoked = true
       where id = v_license_id;
    end if;
    update public.device_grants
       set status = 'expired',
           claim_retry_until = null,
           refresh_token_plain = null
     where id = v_grant_id;
    return jsonb_build_object('result', 'expired');
  end if;

  if v_status = 'pending' then
    update public.device_grants
       set last_polled_at = v_now
     where id = v_grant_id
       and status = 'pending';
    return jsonb_build_object('result', 'pending');
  end if;
  if v_status = 'denied' then
    return jsonb_build_object('result', 'denied');
  end if;
  if v_status = 'expired' then
    return jsonb_build_object('result', 'expired');
  end if;
  if v_status in ('approved', 'claimed') then
    return jsonb_build_object('result', 'ready');
  end if;

  return jsonb_build_object('result', 'invalid');
end;
$$;

-- Claim and exact replay share one grant-row serialization point. The raw B
-- is hashed by the route; this RPC receives hashes only and returns identity
-- metadata, never bearer material.
create or replace function public.claim_device_grant_atomic_v2(
  p_device_code_hash text,
  p_refresh_token_hash text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_grant_id uuid;
  v_proposed_hash text;
  v_status public.device_grant_status;
  v_expires_at timestamptz;
  v_claim_retry_until timestamptz;
  v_user_id uuid;
  v_license_id uuid;
  v_plaintext_is_clear boolean;
  v_license_user_id uuid;
  v_current_hash text;
  v_family_expires_at timestamptz;
  v_revoked boolean;
  v_user_status public.user_status;
  v_user_email text;
begin
  if p_device_code_hash is null
     or p_device_code_hash !~ '^[0-9a-f]{64}$'
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid device v2 claim token material' using errcode = '22023';
  end if;

  select grant.id,
         grant.proposed_refresh_token_hash,
         grant.status,
         grant.expires_at,
         grant.claim_retry_until,
         grant.user_id,
         grant.license_id,
         grant.refresh_token_plain is null
    into v_grant_id,
         v_proposed_hash,
         v_status,
         v_expires_at,
         v_claim_retry_until,
         v_user_id,
         v_license_id,
         v_plaintext_is_clear
    from public.device_grants as grant
   where grant.device_code_hash = p_device_code_hash
   for update;

  if not found then
    return jsonb_build_object('result', 'not_found');
  end if;

  if v_proposed_hash is null
     or v_proposed_hash !~ '^[0-9a-f]{64}$'
     or not v_plaintext_is_clear
     or v_proposed_hash <> p_refresh_token_hash then
    return jsonb_build_object('result', 'invalid');
  end if;

  if v_status in ('pending', 'approved') and v_expires_at <= v_now then
    if v_status = 'approved' and v_license_id is not null then
      update public.licenses
         set revoked = true
       where id = v_license_id;
    end if;
    update public.device_grants
       set status = 'expired',
           claim_retry_until = null,
           refresh_token_plain = null
     where id = v_grant_id;
    return jsonb_build_object('result', 'expired');
  end if;

  if v_status = 'pending' then
    update public.device_grants
       set last_polled_at = v_now
     where id = v_grant_id;
    return jsonb_build_object('result', 'pending');
  end if;
  if v_status = 'denied' then
    return jsonb_build_object('result', 'denied');
  end if;
  if v_status = 'expired' then
    return jsonb_build_object('result', 'expired');
  end if;
  if v_status = 'claimed'
     and (v_claim_retry_until is null or v_claim_retry_until <= v_now) then
    return jsonb_build_object('result', 'retry_expired');
  end if;
  if v_status not in ('approved', 'claimed')
     or v_user_id is null
     or v_license_id is null then
    return jsonb_build_object('result', 'invalid');
  end if;

  select license.user_id,
         license.refresh_token_hash,
         license.refresh_family_expires_at,
         license.revoked
    into v_license_user_id,
         v_current_hash,
         v_family_expires_at,
         v_revoked
    from public.licenses as license
   where license.id = v_license_id
   for update;

  if not found or v_license_user_id <> v_user_id then
    return jsonb_build_object('result', 'invalid');
  end if;
  if v_revoked then
    return jsonb_build_object('result', 'revoked');
  end if;
  if v_current_hash <> p_refresh_token_hash then
    -- B has rotated to C (or the row is corrupt). Never return either token.
    return jsonb_build_object('result', 'stale');
  end if;
  if v_family_expires_at <= v_now then
    update public.licenses
       set revoked = true
     where id = v_license_id;
    update public.device_grants
       set status = 'expired',
           claim_retry_until = null
     where id = v_grant_id;
    return jsonb_build_object('result', 'expired');
  end if;

  select app_user.status, app_user.email
    into v_user_status, v_user_email
    from public.users as app_user
   where app_user.id = v_user_id
   for update;

  if not found or v_user_status not in ('active', 'trialing') then
    update public.licenses
       set revoked = true
     where id = v_license_id;
    update public.device_grants
       set status = 'expired',
           claim_retry_until = null
     where id = v_grant_id;
    return jsonb_build_object('result', 'inactive');
  end if;

  if v_status = 'approved' then
    update public.device_grants
       set status = 'claimed',
           claimed_at = v_now,
           claim_retry_until = least(
             v_now + interval '2 minutes',
             v_family_expires_at
           ),
           last_polled_at = v_now,
           refresh_token_plain = null
     where id = v_grant_id
       and status = 'approved'
       and proposed_refresh_token_hash = p_refresh_token_hash
       and refresh_token_plain is null;

    if not found then
      raise exception 'device v2 grant changed while claim was finalizing'
        using errcode = '40001';
    end if;
  else
    update public.device_grants
       set last_polled_at = v_now
     where id = v_grant_id
       and status = 'claimed'
       and claim_retry_until > v_now;
  end if;

  return jsonb_build_object(
    'result', case when v_status = 'approved' then 'claimed' else 'replay' end,
    'license_id', v_license_id,
    'user_id', v_user_id,
    'email', v_user_email
  );
end;
$$;

-- Opportunistic start-time cleanup closes approved-but-never-polled v2
-- licenses. Claim and cleanup serialize on the same grant row, so a valid
-- first claim either wins before expiry or the orphan license is revoked.
create or replace function public.expire_stale_device_grants_v2()
returns integer
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_grant record;
  v_count integer := 0;
begin
  for v_grant in
    select grant.id, grant.status, grant.license_id
      from public.device_grants as grant
     where grant.proposed_refresh_token_hash is not null
       and grant.status in ('pending', 'approved')
       and grant.expires_at <= clock_timestamp()
     order by grant.id
     for update
  loop
    if v_grant.status = 'approved' and v_grant.license_id is not null then
      update public.licenses
         set revoked = true
       where id = v_grant.license_id;
    end if;

    update public.device_grants
       set status = 'expired',
           refresh_token_plain = null,
           claim_retry_until = null
     where id = v_grant.id;
    v_count := v_count + 1;
  end loop;

  return v_count;
end;
$$;

revoke execute on function public.approve_device_grant_atomic_v2(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.approve_device_grant_atomic_v2(uuid, uuid)
  to service_role;

revoke execute on function public.poll_device_grant_pending_v2(text, text)
  from public, anon, authenticated;
grant execute on function public.poll_device_grant_pending_v2(text, text)
  to service_role;

revoke execute on function public.claim_device_grant_atomic_v2(text, text)
  from public, anon, authenticated;
grant execute on function public.claim_device_grant_atomic_v2(text, text)
  to service_role;

revoke execute on function public.expire_stale_device_grants_v2()
  from public, anon, authenticated;
grant execute on function public.expire_stale_device_grants_v2()
  to service_role;
