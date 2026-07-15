-- Fail closed unless this is the pristine HQ schema state immediately before
-- migration 0011. A prior partial run must be reviewed, never blindly replayed.
do $elevate_baseline$
begin
  if to_regclass('public.users') is null
     or to_regclass('public.licenses') is null
     or to_regclass('public.device_grants') is null
     or to_regclass('public.login_codes') is null
     or to_regclass('public.automations') is null then
    raise exception
      'HQ migration baseline check failed: required schema through 0010 is absent';
  end if;

  if to_regclass('public.session_diagnostic_events') is not null
     or to_regclass('public.app_crash_reports') is not null
     or to_regnamespace('elevate_internal') is not null
     or exists (
       select 1
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
     )
     or exists (
       select 1
         from pg_catalog.pg_proc as proc
         join pg_catalog.pg_namespace as namespace
           on namespace.oid = proc.pronamespace
        where namespace.nspname in ('public', 'elevate_internal')
          and proc.proname in (
            'approve_device_grant_atomic',
            'issue_login_code_atomic',
            'record_login_code_attempt_atomic',
            'redeem_login_code_atomic',
            'add_org_membership_atomic',
            'create_org_with_owner_atomic',
            'accept_invitation_atomic',
            'rotate_license_refresh_v2',
            'approve_device_grant_atomic_v2',
            'poll_device_grant_pending_v2',
            'claim_device_grant_atomic_v2',
            'expire_stale_device_grants_v2',
            'issue_existing_user_license_v2',
            'signup_with_license_v2',
            'replay_signup_license_v2',
            'start_device_grant_atomic_v3',
            'elevate_hq_schema_readiness_v1'
          )
     )
     or to_regclass('public.login_codes_one_unconsumed_per_user_idx') is not null
     or to_regclass('public.licenses_previous_refresh_token_hash_idx') is not null
     or to_regclass('public.device_grants_proposed_refresh_token_hash_uidx') is not null then
    raise exception using
      message = 'HQ migration baseline is not pristine 0010',
      detail = 'At least one 0011-0020 sentinel already exists.',
      hint = 'Do not retry. Inspect the audit evidence and database topology, then prepare an explicit reviewed recovery plan.';
  end if;
end
$elevate_baseline$;

select 'ELEVATE_AUDIT check=initial_topology state=pass baseline=0010';
