-- Refresh API v2 makes a discarded successful response recoverable without
-- storing plaintext bearer material. The database retains exactly one hashed
-- predecessor and its hashed client attempt id, plus an absolute family
-- expiry that rotation never extends.

alter table public.licenses
  add column if not exists previous_refresh_token_hash text,
  add column if not exists previous_refresh_attempt_hash text,
  add column if not exists refresh_family_expires_at timestamptz;

update public.licenses
   set refresh_family_expires_at = created_at + interval '90 days'
 where refresh_family_expires_at is null;

alter table public.licenses
  alter column refresh_family_expires_at
    set default (now() + interval '90 days'),
  alter column refresh_family_expires_at set not null;

create index if not exists licenses_previous_refresh_token_hash_idx
  on public.licenses (previous_refresh_token_hash)
  where previous_refresh_token_hash is not null;

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
  v_now timestamptz := clock_timestamp();
  v_license_id uuid;
  v_user_id uuid;
  v_current_hash text;
  v_previous_hash text;
  v_previous_attempt_hash text;
  v_family_expires_at timestamptz;
  v_revoked boolean;
  v_user_status public.user_status;
  v_user_email text;
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

  -- This lock is the protocol serialization point. After a concurrent first
  -- execution commits, PostgreSQL rechecks the row and it still matches via
  -- previous_refresh_token_hash, turning an identical waiter into a replay.
  select license.id,
         license.user_id,
         license.refresh_token_hash,
         license.previous_refresh_token_hash,
         license.previous_refresh_attempt_hash,
         license.refresh_family_expires_at,
         license.revoked
    into v_license_id,
         v_user_id,
         v_current_hash,
         v_previous_hash,
         v_previous_attempt_hash,
         v_family_expires_at,
         v_revoked
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

  if v_family_expires_at <= v_now then
    update public.licenses
       set revoked = true
     where id = v_license_id;
    return jsonb_build_object('result', 'expired');
  end if;

  if v_current_hash = p_current_refresh_token_hash then
    -- Refuse token recycling. In particular, B -> A must not reopen the
    -- recovery window for the earlier A -> B exchange. Also refuse a
    -- successor already present in another family's current or recovery slot;
    -- the licenses.refresh_token_hash unique constraint closes the concurrent
    -- current-token collision race.
    if p_next_refresh_token_hash = v_previous_hash
       or exists (
         select 1
           from public.licenses as other_license
          where other_license.id <> v_license_id
            and (
              other_license.refresh_token_hash = p_next_refresh_token_hash
              or other_license.previous_refresh_token_hash = p_next_refresh_token_hash
            )
       ) then
      update public.licenses
         set revoked = true
       where id = v_license_id;
      return jsonb_build_object('result', 'conflict');
    end if;
  elsif v_previous_hash = p_current_refresh_token_hash then
    if v_current_hash <> p_next_refresh_token_hash
       or v_previous_attempt_hash <> p_refresh_attempt_hash then
      update public.licenses
         set revoked = true
       where id = v_license_id;
      return jsonb_build_object('result', 'conflict');
    end if;
  else
    return jsonb_build_object('result', 'invalid');
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
    return jsonb_build_object('result', 'inactive');
  end if;

  if v_current_hash = p_current_refresh_token_hash then
    update public.licenses
       set refresh_token_hash = p_next_refresh_token_hash,
           previous_refresh_token_hash = p_current_refresh_token_hash,
           previous_refresh_attempt_hash = p_refresh_attempt_hash,
           last_used_at = v_now
     where id = v_license_id;

    return jsonb_build_object(
      'result', 'rotated',
      'license_id', v_license_id,
      'user_id', v_user_id,
      'email', v_user_email
    );
  end if;

  -- Exact retry: current is still B and predecessor/attempt are exactly A/I.
  -- Keep the hashes unchanged; only record successful family use.
  update public.licenses
     set last_used_at = v_now
   where id = v_license_id;

  return jsonb_build_object(
    'result', 'replay',
    'license_id', v_license_id,
    'user_id', v_user_id,
    'email', v_user_email
  );
end;
$$;

revoke execute on function public.rotate_license_refresh_v2(text, text, text)
  from public, anon, authenticated;
grant execute on function public.rotate_license_refresh_v2(text, text, text)
  to service_role;
