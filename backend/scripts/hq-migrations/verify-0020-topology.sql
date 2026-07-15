-- Migration 0020 moves five public functions into a private schema and is not
-- replay-safe. Require the exact 0019 topology immediately before applying it.
do $elevate_0020_precheck$
begin
  if to_regnamespace('elevate_internal') is not null then
    raise exception '0020 topology check failed: elevate_internal already exists';
  end if;

  if to_regprocedure(
       'public.start_device_grant_atomic_v3(text,text,text,text,text,text,timestamp with time zone)'
     ) is not null
     or to_regprocedure('public.elevate_hq_schema_readiness_v1()') is not null then
    raise exception '0020 topology check failed: public v3/readiness function already exists';
  end if;

  if to_regprocedure('public.rotate_license_refresh_v2(text,text,text)') is null
     or to_regprocedure('public.approve_device_grant_atomic_v2(uuid,uuid)') is null
     or to_regprocedure('public.poll_device_grant_pending_v2(text,text)') is null
     or to_regprocedure('public.claim_device_grant_atomic_v2(text,text)') is null
     or to_regprocedure('public.expire_stale_device_grants_v2()') is null
     or to_regprocedure('public.issue_existing_user_license_v2(uuid,text,text,text)') is null
     or to_regprocedure('public.signup_with_license_v2(text,text,text,text,text,text)') is null
     or to_regprocedure('public.replay_signup_license_v2(uuid,text,text)') is null then
    raise exception using
      message = '0020 topology check failed: required 0017-0019 public functions are incomplete',
      hint = 'Do not apply or retry 0020 until the exact topology is reviewed.';
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
    raise exception '0020 topology check failed: expected six 0017-0019 columns';
  end if;

  if not exists (
       select 1
         from pg_catalog.pg_attribute
        where attrelid = 'public.licenses'::regclass
          and attname = 'refresh_family_expires_at'
          and attnotnull
          and not attisdropped
     )
     or to_regclass('public.licenses_previous_refresh_token_hash_idx') is null
     or to_regclass('public.device_grants_proposed_refresh_token_hash_uidx') is null
     or not exists (
       select 1
         from pg_catalog.pg_index
        where indexrelid = to_regclass(
          'public.licenses_previous_refresh_token_hash_idx'
        )
          and indisvalid
          and indisready
          and indpred is not null
     )
     or not exists (
       select 1
         from pg_catalog.pg_index
        where indexrelid = to_regclass(
          'public.device_grants_proposed_refresh_token_hash_uidx'
        )
          and indisvalid
          and indisready
          and indisunique
          and indpred is not null
     )
     or not exists (
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
    raise exception '0020 topology check failed: required 0017-0019 constraints or indexes are incomplete';
  end if;

  if exists (
    select 1
      from pg_catalog.pg_trigger
     where tgrelid = 'public.device_grants'::regclass
       and tgname = 'device_grants_capability_lock_v1'
       and not tgisinternal
  ) then
    raise exception '0020 topology check failed: v3 trigger already exists';
  end if;
end
$elevate_0020_precheck$;

select 'ELEVATE_AUDIT check=0020_topology state=pass baseline=0019';
