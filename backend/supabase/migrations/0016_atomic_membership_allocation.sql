-- Serialize every membership allocation on the owning organization row.
--
-- All application membership writers call add_org_membership_atomic, either
-- directly or from one of the larger transactional RPCs below. Holding the
-- organization lock across the seat count and insert makes the final seat a
-- one-winner operation across direct adds, invitation accepts, and initial
-- owner creation.

create or replace function public.add_org_membership_atomic(
  p_org_id uuid,
  p_user_id uuid,
  p_role public.org_role
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_seat_limit integer;
  v_member_count bigint;
  v_membership public.memberships%rowtype;
begin
  if p_org_id is null or p_user_id is null or p_role is null then
    raise exception 'invalid membership allocation parameters' using errcode = '22023';
  end if;

  -- The organization row is the shared seat-allocation mutex. Seat-limit
  -- updates also take this row lock, so allocation observes one stable limit.
  select seat_limit
    into v_seat_limit
    from public.organizations
   where id = p_org_id
   for update;
  if not found then
    return jsonb_build_object('result', 'org_not_found');
  end if;

  -- Preserve idempotent already-member behavior even when the organization is
  -- full: an existing member never consumes a second seat.
  select *
    into v_membership
    from public.memberships
   where org_id = p_org_id
     and user_id = p_user_id;
  if found then
    return jsonb_build_object(
      'result', 'already_member',
      'membership', to_jsonb(v_membership)
    );
  end if;

  perform 1
    from public.users
   where id = p_user_id
   for key share;
  if not found then
    return jsonb_build_object('result', 'user_not_found');
  end if;

  select count(*)
    into v_member_count
    from public.memberships
   where org_id = p_org_id;
  if v_member_count >= v_seat_limit then
    return jsonb_build_object('result', 'seat_limit');
  end if;

  insert into public.memberships (org_id, user_id, role)
  values (p_org_id, p_user_id, p_role)
  returning * into v_membership;

  return jsonb_build_object(
    'result', 'added',
    'membership', to_jsonb(v_membership)
  );
end;
$$;

-- Self-service organization creation must not leave an ownerless organization
-- if its initial membership write fails. The route pre-generates the UUID and
-- this RPC commits the organization and owner membership together.
create or replace function public.create_org_with_owner_atomic(
  p_org_id uuid,
  p_owner_user_id uuid,
  p_slug text,
  p_name text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_org public.organizations%rowtype;
  v_allocation jsonb;
begin
  if p_org_id is null
     or p_owner_user_id is null
     or p_slug is null
     or p_slug !~ '^[a-z0-9-]{2,60}$'
     or p_name is null
     or length(p_name) < 2
     or length(p_name) > 80 then
    raise exception 'invalid organization creation parameters' using errcode = '22023';
  end if;

  perform 1
    from public.users
   where id = p_owner_user_id
   for key share;
  if not found then
    return jsonb_build_object('result', 'owner_not_found');
  end if;

  insert into public.organizations (
    id,
    slug,
    name,
    tier,
    status,
    entitlements,
    seat_limit
  ) values (
    p_org_id,
    p_slug,
    p_name,
    'pro',
    'active',
    '{}'::text[],
    1
  )
  returning * into v_org;

  v_allocation := public.add_org_membership_atomic(
    p_org_id,
    p_owner_user_id,
    'owner'
  );
  if v_allocation->>'result' <> 'added' then
    raise exception 'initial owner allocation failed: %', v_allocation->>'result'
      using errcode = '40001';
  end if;

  return jsonb_build_object(
    'result', 'created',
    'organization', to_jsonb(v_org),
    'membership', v_allocation->'membership'
  );
end;
$$;

-- Accepting an invitation creates or resolves the invited email user,
-- allocates its seat, consumes the invitation, and creates the exact license
-- prepared by the route in one transaction. The refresh bearer itself never
-- enters the database.
create or replace function public.accept_invitation_atomic(
  p_invitation_id uuid,
  p_token_hash text,
  p_new_user_id uuid,
  p_new_user_password_hash text,
  p_license_id uuid,
  p_refresh_token_hash text
) returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := clock_timestamp();
  v_invitation public.invitations%rowtype;
  v_org public.organizations%rowtype;
  v_user public.users%rowtype;
  v_member_count bigint;
  v_allocation jsonb;
  v_allocation_result text;
  v_user_created boolean := false;
  v_updated_invitation_id uuid;
begin
  if p_invitation_id is null
     or p_new_user_id is null
     or p_license_id is null
     or p_token_hash is null
     or p_token_hash !~ '^[0-9a-f]{64}$'
     or p_refresh_token_hash is null
     or p_refresh_token_hash !~ '^[0-9a-f]{64}$'
     or (
       p_new_user_password_hash is not null
       and (length(p_new_user_password_hash) < 50 or length(p_new_user_password_hash) > 100)
     ) then
    raise exception 'invalid invitation acceptance parameters' using errcode = '22023';
  end if;

  select *
    into v_invitation
    from public.invitations
   where id = p_invitation_id
     and token_hash = p_token_hash
   for update;
  if not found then
    return jsonb_build_object('result', 'invalid');
  end if;
  if v_invitation.status <> 'pending' then
    return jsonb_build_object('result', v_invitation.status::text);
  end if;
  if v_invitation.expires_at <= v_now then
    return jsonb_build_object('result', 'expired');
  end if;

  -- Lock the organization before any seat decision or new-user write. Losing
  -- final-seat contenders therefore return without leaving orphan users.
  select *
    into v_org
    from public.organizations
   where id = v_invitation.org_id
   for update;
  if not found then
    return jsonb_build_object('result', 'org_not_found');
  end if;

  select *
    into v_user
    from public.users
   where email = lower(v_invitation.email)
   for update;

  if not found then
    -- Match the existing route contract: a full organization is reported
    -- before asking a brand-new invitee for a password.
    select count(*)
      into v_member_count
      from public.memberships
     where org_id = v_invitation.org_id;
    if v_member_count >= v_org.seat_limit then
      return jsonb_build_object('result', 'seat_limit');
    end if;
    if p_new_user_password_hash is null then
      return jsonb_build_object(
        'result', 'password_required',
        'email', v_invitation.email
      );
    end if;

    insert into public.users (
      id,
      email,
      password_hash,
      tier,
      status,
      entitlements,
      role
    ) values (
      p_new_user_id,
      lower(v_invitation.email),
      p_new_user_password_hash,
      'pro',
      'active',
      '{}'::text[],
      'user'
    )
    on conflict (email) do nothing
    returning * into v_user;

    if found then
      v_user_created := true;
    else
      -- A normal signup can win the email race without holding this org lock.
      -- Resolve that exact account; never substitute route-provided identity.
      select *
        into v_user
        from public.users
       where email = lower(v_invitation.email)
       for update;
      if not found then
        raise exception 'invited user resolution changed during acceptance'
          using errcode = '40001';
      end if;
    end if;
  end if;

  -- Hold the user lock through commit so subscription status cannot change
  -- between this check and license creation.
  if v_user.status not in ('active', 'trialing') then
    return jsonb_build_object('result', 'inactive');
  end if;

  v_allocation := public.add_org_membership_atomic(
    v_invitation.org_id,
    v_user.id,
    v_invitation.role
  );
  v_allocation_result := v_allocation->>'result';

  if v_allocation_result = 'seat_limit' then
    -- Under the organization lock this can only happen for a pre-existing
    -- account. Never commit a newly created user without its membership.
    if v_user_created then
      raise exception 'seat availability changed during invitation acceptance'
        using errcode = '40001';
    end if;
    return jsonb_build_object('result', 'seat_limit');
  end if;
  if v_allocation_result not in ('added', 'already_member') then
    raise exception 'invitation membership allocation failed: %', v_allocation_result
      using errcode = '40001';
  end if;

  update public.invitations
     set status = 'accepted',
         accepted_at = v_now,
         accepted_user_id = v_user.id
   where id = v_invitation.id
     and status = 'pending'
  returning id into v_updated_invitation_id;
  if not found then
    raise exception 'invitation changed while acceptance was finalizing'
      using errcode = '40001';
  end if;

  insert into public.licenses (
    id,
    user_id,
    refresh_token_hash,
    device_label
  ) values (
    p_license_id,
    v_user.id,
    p_refresh_token_hash,
    'invite-accept'
  );

  return jsonb_build_object(
    'result', 'accepted',
    'license_id', p_license_id,
    'user', jsonb_build_object(
      'id', v_user.id,
      'email', v_user.email,
      'tier', v_user.tier::text,
      'status', v_user.status::text
    ),
    'membership_result', v_allocation_result,
    'membership', v_allocation->'membership',
    'user_created', v_user_created
  );
end;
$$;

revoke execute on function public.add_org_membership_atomic(uuid, uuid, public.org_role)
  from public, anon, authenticated;
grant execute on function public.add_org_membership_atomic(uuid, uuid, public.org_role)
  to service_role;

revoke execute on function public.create_org_with_owner_atomic(uuid, uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.create_org_with_owner_atomic(uuid, uuid, text, text)
  to service_role;

revoke execute on function public.accept_invitation_atomic(uuid, text, uuid, text, uuid, text)
  from public, anon, authenticated;
grant execute on function public.accept_invitation_atomic(uuid, text, uuid, text, uuid, text)
  to service_role;
