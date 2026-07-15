-- Structural, data-invariant, routing, and privilege gates required before the
-- upgraded HQ backend is allowed to serve traffic.
do $elevate_final_readiness$
declare
  function_signature text;
  readiness_result jsonb;
begin
  if to_regclass('public.session_diagnostic_events') is null
     or to_regclass('public.app_crash_reports') is null then
    raise exception 'final readiness failed: 0011 or 0013 table is absent';
  end if;

  if not (
       select relrowsecurity
         from pg_catalog.pg_class
        where oid = 'public.session_diagnostic_events'::regclass
     )
     or not (
       select relrowsecurity
         from pg_catalog.pg_class
        where oid = 'public.app_crash_reports'::regclass
     ) then
    raise exception 'final readiness failed: diagnostic table RLS is disabled';
  end if;

  if not pg_catalog.has_table_privilege(
       'service_role', 'public.session_diagnostic_events',
       'SELECT'
     )
     or not pg_catalog.has_table_privilege(
       'service_role', 'public.session_diagnostic_events',
       'INSERT'
     )
     or not pg_catalog.has_table_privilege(
       'service_role', 'public.app_crash_reports', 'SELECT'
     )
     or not pg_catalog.has_table_privilege(
       'service_role', 'public.app_crash_reports', 'INSERT'
     )
     or pg_catalog.has_table_privilege(
       'anon', 'public.session_diagnostic_events', 'SELECT'
     )
     or pg_catalog.has_table_privilege(
       'anon', 'public.session_diagnostic_events', 'INSERT'
     )
     or pg_catalog.has_table_privilege(
       'authenticated', 'public.session_diagnostic_events', 'SELECT'
     )
     or pg_catalog.has_table_privilege(
       'authenticated', 'public.session_diagnostic_events', 'INSERT'
     )
     or pg_catalog.has_table_privilege(
       'anon', 'public.app_crash_reports', 'SELECT'
     )
     or pg_catalog.has_table_privilege(
       'anon', 'public.app_crash_reports', 'INSERT'
     )
     or pg_catalog.has_table_privilege(
       'authenticated', 'public.app_crash_reports', 'SELECT'
     )
     or pg_catalog.has_table_privilege(
       'authenticated', 'public.app_crash_reports', 'INSERT'
     ) then
    raise exception 'final readiness failed: diagnostic table grants are unsafe';
  end if;

  if (
    select count(*)
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
  ) <> 6 then
    raise exception 'final readiness failed: expected six recovery columns';
  end if;

  if not exists (
    select 1
      from pg_catalog.pg_attribute
     where attrelid = 'public.licenses'::regclass
       and attname = 'refresh_family_expires_at'
       and attnotnull
       and not attisdropped
  ) then
    raise exception 'final readiness failed: refresh family expiry is nullable';
  end if;

  if exists (
       select 1
         from public.licenses
        where refresh_family_expires_at is null
     ) then
    raise exception 'final readiness failed: null refresh family expiry remains';
  end if;

  if exists (
       select 1
         from public.login_codes
        where consumed_at is null
        group by user_id
       having count(*) > 1
     ) then
    raise exception 'final readiness failed: duplicate unconsumed login codes remain';
  end if;

  if (
    select count(*)
      from pg_catalog.pg_class as relation
      join pg_catalog.pg_namespace as namespace
        on namespace.oid = relation.relnamespace
      join pg_catalog.pg_index as index_metadata
        on index_metadata.indexrelid = relation.oid
     where namespace.nspname = 'public'
       and relation.relkind = 'i'
       and index_metadata.indisvalid
       and index_metadata.indisready
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
         or index_metadata.indisunique
       )
       and (
         relation.relname not in (
           'login_codes_one_unconsumed_per_user_idx',
           'licenses_previous_refresh_token_hash_idx',
           'device_grants_proposed_refresh_token_hash_uidx'
         )
         or index_metadata.indpred is not null
       )
  ) <> 9 then
    raise exception 'final readiness failed: required indexes are incomplete';
  end if;

  if not exists (
       select 1
         from pg_catalog.pg_constraint
        where conrelid = 'public.licenses'::regclass
          and conname = 'licenses_initial_issuance_kind_check'
          and convalidated
     )
     or (
       select count(*)
         from pg_catalog.pg_constraint
        where conrelid = 'public.device_grants'::regclass
          and conname in (
            'device_grants_proposed_refresh_hash_format_ck',
            'device_grants_v2_plaintext_exclusive_ck',
            'device_grants_claim_retry_window_ck'
          )
          and convalidated
     ) <> 3 then
    raise exception 'final readiness failed: recovery constraints are incomplete';
  end if;

  if to_regnamespace('elevate_internal') is null
     or to_regprocedure(
       'public.start_device_grant_atomic_v3(text,text,text,text,text,text,timestamp with time zone)'
     ) is null
     or to_regprocedure('elevate_internal.lock_refresh_capability_v1(text)') is null
     or to_regprocedure('elevate_internal.lock_device_grant_capability_v1()') is null then
    raise exception 'final readiness failed: 0020 schema, v3 RPC, or lock helpers are absent';
  end if;

  if to_regprocedure('public.elevate_hq_schema_readiness_v1()') is null
     or not exists (
       select 1
         from pg_catalog.pg_proc as proc
         join pg_catalog.pg_namespace as namespace
           on namespace.oid = proc.pronamespace
         join pg_catalog.pg_language as language
           on language.oid = proc.prolang
        where namespace.nspname = 'public'
          and proc.proname = 'elevate_hq_schema_readiness_v1'
          and proc.pronargs = 0
          and proc.prorettype = 'jsonb'::regtype
          and language.lanname = 'plpgsql'
          and proc.provolatile = 's'
          and not proc.prosecdef
          and proc.proconfig @> array[
            'search_path=pg_catalog, public, pg_temp'
          ]::text[]
     ) then
    raise exception 'final readiness failed: readiness RPC contract is absent or unsafe';
  end if;

  foreach function_signature in array array[
    'rotate_license_refresh_v2(text,text,text)',
    'approve_device_grant_atomic_v2(uuid,uuid)',
    'issue_existing_user_license_v2(uuid,text,text,text)',
    'signup_with_license_v2(text,text,text,text,text,text)',
    'replay_signup_license_v2(uuid,text,text)'
  ]
  loop
    if to_regprocedure('public.' || function_signature) is null
       or to_regprocedure('elevate_internal.' || function_signature) is null then
      raise exception 'final readiness failed: public/internal function pair absent for %',
        function_signature;
    end if;

    if position(
      'elevate_internal.' in pg_catalog.pg_get_functiondef(
        to_regprocedure('public.' || function_signature)
      )
    ) = 0 then
      raise exception 'final readiness failed: public wrapper does not route internally for %',
        function_signature;
    end if;
  end loop;

  if not exists (
    select 1
      from pg_catalog.pg_trigger
     where tgrelid = 'public.device_grants'::regclass
       and tgname = 'device_grants_capability_lock_v1'
       and not tgisinternal
       and tgenabled in ('O', 'A')
       and tgfoid = to_regprocedure(
         'elevate_internal.lock_device_grant_capability_v1()'
       )
  ) then
    raise exception 'final readiness failed: v3 capability trigger is absent';
  end if;

  if not pg_catalog.has_schema_privilege('service_role', 'elevate_internal', 'USAGE')
     or pg_catalog.has_schema_privilege('anon', 'elevate_internal', 'USAGE')
     or pg_catalog.has_schema_privilege('authenticated', 'elevate_internal', 'USAGE') then
    raise exception 'final readiness failed: elevate_internal schema grants are unsafe';
  end if;

  foreach function_signature in array array[
    'public.approve_device_grant_atomic(uuid,uuid,text,text)',
    'public.issue_login_code_atomic(uuid,text,timestamp with time zone,text,text)',
    'public.record_login_code_attempt_atomic(uuid,uuid,text,integer)',
    'public.redeem_login_code_atomic(uuid,uuid,text,uuid,text,text,integer)',
    'public.add_org_membership_atomic(uuid,uuid,public.org_role)',
    'public.create_org_with_owner_atomic(uuid,uuid,text,text)',
    'public.accept_invitation_atomic(uuid,text,uuid,text,uuid,text)',
    'public.elevate_hq_schema_readiness_v1()',
    'public.start_device_grant_atomic_v3(text,text,text,text,text,text,timestamp with time zone)',
    'public.rotate_license_refresh_v2(text,text,text)',
    'public.approve_device_grant_atomic_v2(uuid,uuid)',
    'public.poll_device_grant_pending_v2(text,text)',
    'public.claim_device_grant_atomic_v2(text,text)',
    'public.expire_stale_device_grants_v2()',
    'public.issue_existing_user_license_v2(uuid,text,text,text)',
    'public.signup_with_license_v2(text,text,text,text,text,text)',
    'public.replay_signup_license_v2(uuid,text,text)',
    'elevate_internal.lock_refresh_capability_v1(text)',
    'elevate_internal.lock_device_grant_capability_v1()',
    'elevate_internal.rotate_license_refresh_v2(text,text,text)',
    'elevate_internal.approve_device_grant_atomic_v2(uuid,uuid)',
    'elevate_internal.issue_existing_user_license_v2(uuid,text,text,text)',
    'elevate_internal.signup_with_license_v2(text,text,text,text,text,text)',
    'elevate_internal.replay_signup_license_v2(uuid,text,text)'
  ]
  loop
    if not pg_catalog.has_function_privilege('service_role', function_signature, 'EXECUTE')
       or pg_catalog.has_function_privilege('anon', function_signature, 'EXECUTE')
       or pg_catalog.has_function_privilege('authenticated', function_signature, 'EXECUTE') then
      raise exception 'final readiness failed: function grants are unsafe for %',
        function_signature;
    end if;
  end loop;

  select public.elevate_hq_schema_readiness_v1()
    into readiness_result;

  if readiness_result is distinct from pg_catalog.jsonb_build_object(
       'contract', 'elevate-hq-schema-readiness-v1',
       'schema_version', '0020',
       'ready', true,
       'tables_ready', true,
       'columns_ready', true,
       'constraints_ready', true,
       'indexes_ready', true,
       'rpcs_ready', true,
       'triggers_ready', true,
       'privileges_ready', true,
       'data_invariants_ready', true,
       'initial_issuance_v2_ready', true
     ) then
    raise exception using
      message = 'final readiness failed: readiness RPC did not return exact success contract',
      detail = coalesce(readiness_result::text, 'null');
  end if;
end
$elevate_final_readiness$;

select 'ELEVATE_AUDIT check=final_readiness state=pass schema=0020';
