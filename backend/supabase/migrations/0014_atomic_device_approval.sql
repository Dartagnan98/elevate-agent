-- Approve a device grant, create its license, stash the one-shot refresh
-- bearer, and record the audit event in one database transaction.
--
-- The first UPDATE is the compare-and-swap: only an untouched, pending,
-- unexpired grant can acquire an approver. Concurrent calls serialize on the
-- row and every loser observes the winner's committed status without creating
-- a second license.

create or replace function public.approve_device_grant_atomic(
  p_grant_id uuid,
  p_user_id uuid,
  p_refresh_token_hash text,
  p_refresh_token_plain text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_device_label text;
  v_user_code text;
  v_license_id uuid;
  v_status public.device_grant_status;
  v_row_count integer;
begin
  if p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or p_refresh_token_plain is null
     or p_refresh_token_plain !~ '^[A-Za-z0-9_-]{43}$' then
    raise exception 'invalid device refresh token material' using errcode = '22023';
  end if;

  if not exists (
    select 1
      from public.users
     where id = p_user_id
       and status in ('active', 'trialing')
  ) then
    raise exception 'device approver is not active' using errcode = 'P0001';
  end if;

  -- Opportunistically remove expired plaintext stashes. The partial expiry
  -- index from migration 0004 keeps this bounded to pending/approved grants.
  update public.device_grants
     set status = 'expired',
         refresh_token_plain = null
   where expires_at <= clock_timestamp()
     and status in ('pending', 'approved');

  -- CAS ownership. Requiring every issuance field to be empty also refuses
  -- partially-written rows left by the pre-atomic implementation.
  update public.device_grants
     set user_id = p_user_id
   where id = p_grant_id
     and status = 'pending'
     and expires_at > clock_timestamp()
     and user_id is null
     and license_id is null
     and refresh_token_plain is null
  returning device_label, user_code
       into v_device_label, v_user_code;

  if not found then
    select status
      into v_status
      from public.device_grants
     where id = p_grant_id;

    if not found then
      return jsonb_build_object('result', 'not_found');
    end if;

    -- A malformed pending row must never retain a claimable plaintext bearer.
    if v_status = 'pending' then
      update public.device_grants
         set status = 'expired',
             refresh_token_plain = null
       where id = p_grant_id
         and status = 'pending';
      return jsonb_build_object('result', 'invalid', 'grant_status', 'expired');
    end if;

    return jsonb_build_object(
      'result', case when v_status = 'expired' then 'expired' else 'conflict' end,
      'grant_status', v_status::text
    );
  end if;

  insert into public.licenses (
    user_id,
    refresh_token_hash,
    device_label
  ) values (
    p_user_id,
    p_refresh_token_hash,
    coalesce(v_device_label, 'linked-device')
  ) returning id into v_license_id;

  update public.device_grants
     set status = 'approved',
         license_id = v_license_id,
         approved_at = clock_timestamp(),
         refresh_token_plain = p_refresh_token_plain
   where id = p_grant_id
     and status = 'pending'
     and user_id = p_user_id
     and license_id is null
     and refresh_token_plain is null
     and expires_at > clock_timestamp();

  get diagnostics v_row_count = row_count;
  if v_row_count <> 1 then
    -- Raising rolls back both the CAS ownership and the license insert.
    raise exception 'device grant changed while approval was finalizing'
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
    'device.link.approved',
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

revoke execute on function public.approve_device_grant_atomic(uuid, uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.approve_device_grant_atomic(uuid, uuid, text, text)
  to service_role;
