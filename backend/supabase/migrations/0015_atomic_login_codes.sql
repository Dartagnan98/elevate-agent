-- Serialize passwordless login-code issuance, failed attempts, and redemption.
--
-- Every function locks the owning user row first, then the newest active code.
-- That common lock order makes a new-code request, wrong guess, and correct
-- redemption mutually exclusive for one account. The redeem function consumes
-- the code and creates its license in the same transaction; any error rolls
-- both writes back.

-- Old route-level issuance could leave several unconsumed rows for one user.
-- Normalize those rows before enforcing the invariant, while blocking legacy
-- writers for the short migration transaction so none can slip into the gap.
lock table public.login_codes in share row exclusive mode;

with ranked_unconsumed as (
  select id,
         row_number() over (
           partition by user_id
           order by created_at desc, id desc
         ) as recency_rank
    from public.login_codes
   where consumed_at is null
)
update public.login_codes as login_code
   set consumed_at = clock_timestamp()
  from ranked_unconsumed
 where login_code.id = ranked_unconsumed.id
   and ranked_unconsumed.recency_rank > 1;

create unique index if not exists login_codes_one_unconsumed_per_user_idx
  on public.login_codes (user_id)
  where consumed_at is null;

create or replace function public.issue_login_code_atomic(
  p_user_id uuid,
  p_code_hash text,
  p_expires_at timestamptz,
  p_ip_addr text,
  p_user_agent text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_code_id uuid;
begin
  if p_user_id is null
     or p_code_hash is null
     or p_code_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid login code hash' using errcode = '22023';
  end if;
  if p_expires_at is null or p_expires_at <= v_now then
    raise exception 'login code expiry must be in the future' using errcode = '22023';
  end if;

  -- This row is the per-account mutex shared by all three login-code RPCs.
  perform 1
    from public.users
   where id = p_user_id
   for update;
  if not found then
    return jsonb_build_object('result', 'not_found');
  end if;

  -- Supersede every older code, including legacy rows left unconsumed by the
  -- pre-atomic implementation. Exactly one code remains active after commit.
  update public.login_codes
     set consumed_at = v_now
   where user_id = p_user_id
     and consumed_at is null;

  insert into public.login_codes (
    user_id,
    code_hash,
    created_at,
    expires_at,
    ip_addr,
    user_agent
  ) values (
    p_user_id,
    p_code_hash,
    v_now,
    p_expires_at,
    p_ip_addr,
    p_user_agent
  ) returning id into v_code_id;

  insert into public.audit_log (
    actor_user_id,
    target_user_id,
    action,
    payload
  ) values (
    p_user_id,
    p_user_id,
    'auth.login_code_requested',
    jsonb_build_object('ip', p_ip_addr, 'ua', p_user_agent)
  );

  return jsonb_build_object('result', 'issued', 'login_code_id', v_code_id);
end;
$$;

create or replace function public.record_login_code_attempt_atomic(
  p_user_id uuid,
  p_login_code_id uuid,
  p_attempted_code_hash text,
  p_max_attempts integer
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_code_id uuid;
  v_code_hash text;
  v_attempts integer;
begin
  if p_user_id is null
     or p_login_code_id is null
     or p_attempted_code_hash is null
     or p_attempted_code_hash !~ '^[0-9a-f]{64}$'
     or p_max_attempts is null
     or p_max_attempts < 1
     or p_max_attempts > 100 then
    raise exception 'invalid login code attempt parameters' using errcode = '22023';
  end if;

  perform 1
    from public.users
   where id = p_user_id
   for update;
  if not found then
    return jsonb_build_object('result', 'invalid');
  end if;

  select id, code_hash, attempts
    into v_code_id, v_code_hash, v_attempts
    from public.login_codes
   where user_id = p_user_id
     and consumed_at is null
     and expires_at > clock_timestamp()
   order by created_at desc, id desc
   limit 1
   for update;

  if not found or v_code_id <> p_login_code_id then
    return jsonb_build_object('result', 'invalid');
  end if;
  if v_attempts >= p_max_attempts then
    return jsonb_build_object('result', 'locked', 'attempts', v_attempts);
  end if;
  if v_code_hash = p_attempted_code_hash then
    -- The route calls this function only for a locally detected mismatch. Do
    -- not consume or increment if its snapshot raced an unexpected hash change.
    return jsonb_build_object('result', 'match', 'attempts', v_attempts);
  end if;

  update public.login_codes
     set attempts = attempts + 1
   where id = v_code_id
  returning attempts into v_attempts;

  return jsonb_build_object(
    'result', case when v_attempts >= p_max_attempts then 'locked' else 'invalid' end,
    'attempts', v_attempts
  );
end;
$$;

create or replace function public.redeem_login_code_atomic(
  p_user_id uuid,
  p_login_code_id uuid,
  p_code_hash text,
  p_license_id uuid,
  p_refresh_token_hash text,
  p_device_label text,
  p_max_attempts integer
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_status public.user_status;
  v_code_id uuid;
  v_code_hash text;
  v_attempts integer;
  v_now timestamptz := clock_timestamp();
begin
  if p_user_id is null
     or p_login_code_id is null
     or p_license_id is null
     or p_code_hash is null
     or p_code_hash !~ '^[0-9a-f]{64}$'
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or p_max_attempts is null
     or p_max_attempts < 1
     or p_max_attempts > 100 then
    raise exception 'invalid login code redemption parameters' using errcode = '22023';
  end if;

  select status
    into v_status
    from public.users
   where id = p_user_id
   for update;
  if not found then
    return jsonb_build_object('result', 'invalid');
  end if;
  if v_status not in ('active', 'trialing') then
    return jsonb_build_object('result', 'inactive');
  end if;

  select id, code_hash, attempts
    into v_code_id, v_code_hash, v_attempts
    from public.login_codes
   where user_id = p_user_id
     and consumed_at is null
     and expires_at > v_now
   order by created_at desc, id desc
   limit 1
   for update;

  if not found
     or v_code_id <> p_login_code_id
     or v_code_hash <> p_code_hash then
    return jsonb_build_object('result', 'invalid');
  end if;
  if v_attempts >= p_max_attempts then
    return jsonb_build_object('result', 'locked');
  end if;

  update public.login_codes
     set consumed_at = v_now
   where id = v_code_id
     and consumed_at is null;
  if not found then
    return jsonb_build_object('result', 'invalid');
  end if;

  insert into public.licenses (
    id,
    user_id,
    refresh_token_hash,
    device_label
  ) values (
    p_license_id,
    p_user_id,
    p_refresh_token_hash,
    nullif(p_device_label, '')
  );

  return jsonb_build_object('result', 'redeemed', 'license_id', p_license_id);
end;
$$;

revoke execute on function public.issue_login_code_atomic(uuid, text, timestamptz, text, text)
  from public, anon, authenticated;
grant execute on function public.issue_login_code_atomic(uuid, text, timestamptz, text, text)
  to service_role;

revoke execute on function public.record_login_code_attempt_atomic(uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.record_login_code_attempt_atomic(uuid, uuid, text, integer)
  to service_role;

revoke execute on function public.redeem_login_code_atomic(uuid, uuid, text, uuid, text, text, integer)
  from public, anon, authenticated;
grant execute on function public.redeem_login_code_atomic(uuid, uuid, text, uuid, text, text, integer)
  to service_role;
