#!/usr/bin/env bash
set -Eeuo pipefail

# Deliberately narrow production runner for the one-time Elevate HQ 0011-0020
# upgrade. It accepts the connection URI only through an explicitly named
# environment variable, so credentials do not appear in argv or evidence.

readonly EXPECTED_PROJECT_REF="gpmzkdjxfwbryculteee"
readonly REQUIRED_CONFIRMATION="APPLY-ELEVATE-HQ-PRODUCTION-0011-0020"
readonly LOCAL_TEST_CONFIRMATION="TEST-ONLY-APPLY-ELEVATE-HQ-0011-0020"
readonly LOCAL_TEST_ATTESTATION="LOCAL-EPHEMERAL-POSTGRES"

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
readonly MIGRATIONS_DIR="$BACKEND_DIR/supabase/migrations"
readonly CHECKS_DIR="$SCRIPT_DIR/hq-migrations"

readonly MIGRATION_FILES=(
  "0011_session_diagnostic_events.sql"
  "0012_lock_down_public_privileges.sql"
  "0013_app_crash_reports.sql"
  "0014_atomic_device_approval.sql"
  "0015_atomic_login_codes.sql"
  "0016_atomic_membership_allocation.sql"
  "0017_refresh_v2_response_recovery.sql"
  "0018_device_v2_response_recovery.sql"
  "0019_initial_issuance_v2.sql"
  "0020_device_start_v3_idempotency.sql"
)

usage() {
  cat <<'USAGE'
Usage:
  ELEVATE_HQ_DB_SSLROOTCERT='/absolute/path/to/prod-supabase.cer' \
  ELEVATE_HQ_PRODUCTION_DATABASE_URL='postgresql://...' \
    backend/scripts/apply-hq-migrations-0011-0020.sh \
      --database-url-env ELEVATE_HQ_PRODUCTION_DATABASE_URL \
      --confirm APPLY-ELEVATE-HQ-PRODUCTION-0011-0020 \
      --evidence-dir /root/elevation-hq/backups/migration-evidence

Safety contract:
  - accepts only the Elevate HQ production Supabase project reference
  - requires an explicit connection-URL environment variable and confirmation
  - requires a pristine 0010 baseline; partial runs are never auto-resumed
  - applies exactly 0011 through 0020, in order, one transaction per file
  - stops on the first error and never retries
  - requires the exact 0019 topology immediately before non-replay-safe 0020
  - writes a root/private audit transcript without recording the connection URL

The HQ application must be in maintenance mode before this script is run.

Ephemeral test-only target (never accepted for production):
  ELEVATE_HQ_MIGRATION_TEST_ONLY=LOCAL-EPHEMERAL-POSTGRES \
  ELEVATE_HQ_TEST_DATABASE_URL='postgresql://...@127.0.0.1:5433/elevate_hq_migration_test_ci?sslmode=disable' \
    backend/scripts/apply-hq-migrations-0011-0020.sh \
      --database-url-env ELEVATE_HQ_TEST_DATABASE_URL \
      --local-test-database elevate_hq_migration_test_ci \
      --confirm TEST-ONLY-APPLY-ELEVATE-HQ-0011-0020 \
      --evidence-dir /tmp/elevate-hq-migration-evidence
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    die "sha256sum or shasum is required"
  fi
}

psql_include_path() {
  local path="$1"
  [[ "$path" != *$'\n'* && "$path" != *$'\r'* ]] \
    || die "SQL include path contains a newline"
  path=${path//\'/\'\'}
  printf '%s' "$path"
}

utc_now() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

url_decode_component() {
  local input="$1"
  local output=""
  local index=0
  local length=${#input}
  local character hex decoded

  while [[ $index -lt $length ]]; do
    character=${input:$index:1}
    if [[ "$character" == "%" ]]; then
      [[ $((index + 2)) -lt $length ]] || die "connection URI has truncated percent encoding"
      hex=${input:$((index + 1)):2}
      [[ "$hex" =~ ^[0-9A-Fa-f]{2}$ ]] || die "connection URI has invalid percent encoding"
      case "$hex" in
        00|0A|0a|0D|0d)
          die "connection URI contains a forbidden encoded control character"
          ;;
      esac
      printf -v decoded '%b' "\\x$hex"
      output="${output}${decoded}"
      index=$((index + 3))
    else
      output="${output}${character}"
      index=$((index + 1))
    fi
  done
  printf '%s' "$output"
}

DATABASE_URL_ENV=""
CONFIRMATION=""
EVIDENCE_DIR=""
LOCAL_TEST_DATABASE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database-url-env)
      [[ $# -ge 2 ]] || die "--database-url-env requires a value"
      DATABASE_URL_ENV="$2"
      shift 2
      ;;
    --confirm)
      [[ $# -ge 2 ]] || die "--confirm requires a value"
      CONFIRMATION="$2"
      shift 2
      ;;
    --evidence-dir)
      [[ $# -ge 2 ]] || die "--evidence-dir requires a value"
      EVIDENCE_DIR="$2"
      shift 2
      ;;
    --local-test-database)
      [[ $# -ge 2 ]] || die "--local-test-database requires a value"
      LOCAL_TEST_DATABASE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ "$DATABASE_URL_ENV" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
  || die "--database-url-env must name an environment variable"
[[ -n "$EVIDENCE_DIR" ]] || die "--evidence-dir is required"

DATABASE_URL="${!DATABASE_URL_ENV-}"
[[ -n "$DATABASE_URL" ]] || die "$DATABASE_URL_ENV is empty or unset"
case "$DATABASE_URL" in
  postgresql://*|postgres://*) ;;
  *) die "$DATABASE_URL_ENV must contain a PostgreSQL connection URI" ;;
esac
[[ "$DATABASE_URL" != *'#'* ]] || die "$DATABASE_URL_ENV must not contain a URI fragment"
[[ "$DATABASE_URL" != *$'\n'* && "$DATABASE_URL" != *$'\r'* ]] \
  || die "$DATABASE_URL_ENV must not contain line breaks"
uri_remainder=${DATABASE_URL#*://}
[[ "$uri_remainder" == */* ]] || die "$DATABASE_URL_ENV must include an explicit database"
uri_authority=${uri_remainder%%/*}
uri_path_query=${uri_remainder#*/}
[[ "$uri_authority" == *@* ]] || die "$DATABASE_URL_ENV has no URI user/host boundary"
uri_authority_without_at=${uri_authority//@/}
[[ $(( ${#uri_authority} - ${#uri_authority_without_at} )) -eq 1 ]] \
  || die "$DATABASE_URL_ENV has ambiguous URI user information"
uri_userinfo=${uri_authority%@*}
uri_username_encoded=${uri_userinfo%%:*}
if [[ "$uri_userinfo" == *:* ]]; then
  uri_password_encoded=${uri_userinfo#*:}
else
  uri_password_encoded=""
fi
uri_username="$(url_decode_component "$uri_username_encoded")"
uri_password="$(url_decode_component "$uri_password_encoded")"
uri_hostport=${uri_authority##*@}
[[ -n "$uri_username" && -n "$uri_hostport" ]] \
  || die "$DATABASE_URL_ENV has an empty URI user or host"
case "$uri_hostport" in
  *:*)
    uri_host=${uri_hostport%:*}
    uri_port=${uri_hostport##*:}
    [[ "$uri_host" != *:* ]] || die "$DATABASE_URL_ENV must use a DNS or IPv4 host"
    ;;
  *)
    uri_host=$uri_hostport
    uri_port=5432
    ;;
esac
[[ "$uri_port" =~ ^[0-9]+$ ]] || die "$DATABASE_URL_ENV has an invalid port"

uri_database=${uri_path_query%%\?*}
if [[ "$uri_path_query" == *\?* ]]; then
  uri_query=${uri_path_query#*\?}
else
  uri_query=""
fi
[[ -n "$uri_database" && "$uri_database" != */* ]] \
  || die "$DATABASE_URL_ENV has an invalid database path"

sslmode_count=0
sslmode_value=""
old_ifs=$IFS
IFS='&'
read -r -a uri_query_parameters <<< "$uri_query"
IFS=$old_ifs
for uri_query_parameter in "${uri_query_parameters[@]}"; do
  uri_query_name=${uri_query_parameter%%=*}
  uri_query_value=${uri_query_parameter#*=}
  if [[ "$uri_query_name" == "sslmode" ]]; then
    sslmode_count=$((sslmode_count + 1))
    sslmode_value=$uri_query_value
  elif [[ -n "$uri_query_name" ]]; then
    die "$DATABASE_URL_ENV contains an unapproved connection query parameter"
  fi
done
[[ $sslmode_count -eq 1 ]] || die "$DATABASE_URL_ENV must set sslmode exactly once"

TARGET_MODE="production"
TARGET_LABEL="$EXPECTED_PROJECT_REF"
if [[ -n "$LOCAL_TEST_DATABASE" ]]; then
  [[ "$LOCAL_TEST_DATABASE" =~ ^elevate_hq_migration_test_[A-Za-z0-9_]+$ ]] \
    || die "--local-test-database must start with elevate_hq_migration_test_"
  [[ "${ELEVATE_HQ_MIGRATION_TEST_ONLY-}" == "$LOCAL_TEST_ATTESTATION" ]] \
    || die "local test target requires ELEVATE_HQ_MIGRATION_TEST_ONLY=$LOCAL_TEST_ATTESTATION"
  [[ "$CONFIRMATION" == "$LOCAL_TEST_CONFIRMATION" ]] \
    || die "local test confirmation mismatch; expected $LOCAL_TEST_CONFIRMATION"
  [[ "$uri_host" == "127.0.0.1" || "$uri_host" == "localhost" ]] \
    || die "local test target must use 127.0.0.1 or localhost"
  [[ "$uri_port" -ge 1024 && "$uri_port" -le 65535 ]] \
    || die "local test target port must be between 1024 and 65535"
  [[ "$uri_database" == "$LOCAL_TEST_DATABASE" ]] \
    || die "local test database does not match the URI"
  [[ "$sslmode_value" == "disable" ]] \
    || die "local test target must explicitly set sslmode=disable"
  TARGET_MODE="local_test"
  TARGET_LABEL="$LOCAL_TEST_DATABASE"
else
  [[ "$CONFIRMATION" == "$REQUIRED_CONFIRMATION" ]] \
    || die "confirmation mismatch; expected $REQUIRED_CONFIRMATION"
  [[ "$uri_database" == "postgres" ]] \
    || die "production connection URI must target database postgres"
  [[ "$uri_userinfo" == *:* && -n "$uri_password" ]] \
    || die "production connection URI must include an explicit password"
  [[ "$sslmode_value" == "verify-full" ]] \
    || die "production connection URI must use sslmode=verify-full"
  [[ -n "${ELEVATE_HQ_DB_SSLROOTCERT-}" ]] \
    || die "production migration requires ELEVATE_HQ_DB_SSLROOTCERT"
  [[ "$ELEVATE_HQ_DB_SSLROOTCERT" == /* ]] \
    || die "ELEVATE_HQ_DB_SSLROOTCERT must be an absolute path"
  [[ "$ELEVATE_HQ_DB_SSLROOTCERT" != *$'\n'* && "$ELEVATE_HQ_DB_SSLROOTCERT" != *$'\r'* ]] \
    || die "ELEVATE_HQ_DB_SSLROOTCERT must not contain line breaks"
  [[ -f "$ELEVATE_HQ_DB_SSLROOTCERT" && ! -L "$ELEVATE_HQ_DB_SSLROOTCERT" && -r "$ELEVATE_HQ_DB_SSLROOTCERT" ]] \
    || die "ELEVATE_HQ_DB_SSLROOTCERT must name a readable regular CA file, not a symlink"

  direct_host="db.$EXPECTED_PROJECT_REF.supabase.co"
  if [[ "$uri_host" == "$direct_host" ]]; then
    [[ "$uri_username" == "postgres" && "$uri_port" -eq 5432 ]] \
      || die "direct production URI must use postgres on port 5432"
  elif [[ "$uri_host" == *.pooler.supabase.com ]]; then
    [[ "$uri_username" == "postgres.$EXPECTED_PROJECT_REF" ]] \
      || die "pooler production URI has the wrong project-scoped username"
    # This runner holds one session-level advisory lock across ten separately
    # committed migrations. Supabase's 6543 transaction pooler can change the
    # backing PostgreSQL session between transactions, defeating that lock.
    [[ "$uri_port" -eq 5432 ]] \
      || die "pooler production URI must use session port 5432; transaction pooler port 6543 is unsafe"
  else
    die "production URI host is not an approved Supabase direct or pooler host"
  fi
fi

# Do not inherit the caller's full credential-bearing URI into psql. The
# decoded fields below are passed through libpq's dedicated environment only.
unset "$DATABASE_URL_ENV"

command -v psql >/dev/null 2>&1 || die "psql is required"
command -v node >/dev/null 2>&1 || die "node is required"
command -v tee >/dev/null 2>&1 || die "tee is required"

for required_check in \
  verify-0010-baseline.sql \
  verify-0020-topology.sql \
  verify-final-readiness.sql; do
  [[ -f "$CHECKS_DIR/$required_check" ]] || die "missing check: $required_check"
done

for migration_file in "${MIGRATION_FILES[@]}"; do
  [[ -f "$MIGRATIONS_DIR/$migration_file" ]] \
    || die "missing migration: $migration_file"
  if grep -Ev '^[[:space:]]*--' "$MIGRATIONS_DIR/$migration_file" \
       | grep -Eiq '(^|[^[:alnum:]_])as[[:space:]]+grant([^[:alnum:]_]|$)|(^|[^[:alnum:]_])grant\.'; then
    die "migration uses reserved PostgreSQL alias grant: $migration_file"
  fi
  migration_prefix=${migration_file%%_*}
  shopt -s nullglob
  matching_migrations=("$MIGRATIONS_DIR/${migration_prefix}_"*.sql)
  shopt -u nullglob
  [[ ${#matching_migrations[@]} -eq 1 ]] \
    || die "expected exactly one migration with prefix $migration_prefix"
done

umask 077
mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_DIR"

readonly RUN_ID="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
readonly EVIDENCE_FILE="$EVIDENCE_DIR/elevate-hq-0011-0020-$RUN_ID.audit.log"
PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/elevate-hq-migrations.XXXXXX")" \
  || die "could not create a private migration plan"
readonly PLAN_FILE
touch "$EVIDENCE_FILE"
chmod 600 "$EVIDENCE_FILE" "$PLAN_FILE"

FINALIZED=0
cleanup() {
  local exit_code=$?
  rm -f "$PLAN_FILE"
  if [[ $FINALIZED -eq 0 ]]; then
    printf '%s event=run_finished state=failed exit_code=%s\n' \
      "$(utc_now)" "$exit_code" >>"$EVIDENCE_FILE"
    printf 'Migration run failed. Audit evidence: %s\n' "$EVIDENCE_FILE" >&2
  fi
}
trap cleanup EXIT

printf '%s event=run_started target_mode=%s target_label=%s baseline=0010 target_schema=0020 retries=disabled\n' \
  "$(utc_now)" "$TARGET_MODE" "$TARGET_LABEL" >>"$EVIDENCE_FILE"
printf '%s event=safety_contract app_maintenance_required=true one_transaction_per_file=true stop_on_first_error=true lock_timeout=5s statement_timeout=5min search_path=public,pg_temp advisory_key=elevate-hq-schema-migration\n' \
  "$(utc_now)" >>"$EVIDENCE_FILE"
printf '%s event=runner_identity runner_sha256=%s initial_check_sha256=%s pre_0020_check_sha256=%s final_check_sha256=%s\n' \
  "$(utc_now)" \
  "$(sha256_file "$SCRIPT_DIR/apply-hq-migrations-0011-0020.sh")" \
  "$(sha256_file "$CHECKS_DIR/verify-0010-baseline.sql")" \
  "$(sha256_file "$CHECKS_DIR/verify-0020-topology.sql")" \
  "$(sha256_file "$CHECKS_DIR/verify-final-readiness.sql")" \
  >>"$EVIDENCE_FILE"

for migration_file in "${MIGRATION_FILES[@]}"; do
  migration_path="$MIGRATIONS_DIR/$migration_file"
  migration_sha256="$(sha256_file "$migration_path")"
  printf '%s event=migration_planned migration=%s sha256=%s\n' \
    "$(utc_now)" "${migration_file%%_*}" "$migration_sha256" >>"$EVIDENCE_FILE"
done

{
  printf '\\set ON_ERROR_STOP on\n'
  printf '\\set VERBOSITY verbose\n'
  printf '\\echo ELEVATE_AUDIT event=connection_opened target_mode=%s target_label=%s\n' \
    "$TARGET_MODE" "$TARGET_LABEL"
  printf "select 'ELEVATE_AUDIT event=target_identity database=' || current_database() || ' user=' || current_user || ' server_address=' || coalesce(inet_server_addr()::text, 'local') || ' server_port=' || coalesce(inet_server_port()::text, 'local') || ' server_version=' || current_setting('server_version');\n"
  if [[ "$TARGET_MODE" == "local_test" ]]; then
    printf "do \$elevate_local_target\$ begin if current_database() <> '%s' or inet_server_addr() is null or not (inet_server_addr() << inet '127.0.0.0/8' or inet_server_addr() = inet '::1') then raise exception 'local test target identity check failed'; end if; end \$elevate_local_target\$;\n" \
      "$LOCAL_TEST_DATABASE"
    printf '\\echo ELEVATE_AUDIT event=local_target_identity state=pass\n'
  fi
  printf "set lock_timeout = '5s';\n"
  printf "set statement_timeout = '5min';\n"
  printf "select pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended('elevate-hq-schema-migration-runner', 0));\n"
  printf '\\echo ELEVATE_AUDIT event=runner_lock state=acquired\n'
  printf "\\i '%s'\n" "$(psql_include_path "$CHECKS_DIR/verify-0010-baseline.sql")"

  for migration_file in "${MIGRATION_FILES[@]}"; do
    migration_path="$MIGRATIONS_DIR/$migration_file"
    migration_number=${migration_file%%_*}
    migration_sha256="$(sha256_file "$migration_path")"

    if [[ "$migration_number" == "0020" ]]; then
      printf "\\i '%s'\n" "$(psql_include_path "$CHECKS_DIR/verify-0020-topology.sql")"
    fi

    printf '\\echo ELEVATE_AUDIT event=migration state=started migration=%s sha256=%s\n' \
      "$migration_number" "$migration_sha256"
    printf 'begin;\n'
    printf "set local lock_timeout = '5s';\n"
    printf "set local statement_timeout = '5min';\n"
    printf 'set local search_path = public, pg_temp;\n'
    printf "select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('elevate-hq-schema-migration', 0));\n"
    printf "\\i '%s'\n" "$(psql_include_path "$migration_path")"
    printf 'commit;\n'
    printf '\\echo ELEVATE_AUDIT event=migration state=committed migration=%s sha256=%s\n' \
      "$migration_number" "$migration_sha256"
  done

  printf "\\i '%s'\n" "$(psql_include_path "$CHECKS_DIR/verify-final-readiness.sql")"
  printf "notify pgrst, 'reload schema';\n"
  printf '\\echo ELEVATE_AUDIT event=postgrest_schema_reload state=notified\n'
  printf "select pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended('elevate-hq-schema-migration-runner', 0));\n"
  printf '\\echo ELEVATE_AUDIT event=runner_lock state=released\n'
} >"$PLAN_FILE"

printf '%s event=execution_started\n' "$(utc_now)" >>"$EVIDENCE_FILE"
ELEVATE_HQ_PSQL_URL="$DATABASE_URL" \
  ELEVATE_HQ_DB_SSLROOTCERT="${ELEVATE_HQ_DB_SSLROOTCERT-}" \
  node "$SCRIPT_DIR/run-psql-with-url-env.mjs" ELEVATE_HQ_PSQL_URL "$PLAN_FILE" \
  2>&1 | tee -a "$EVIDENCE_FILE"
printf '%s event=run_finished state=succeeded schema=0020\n' \
  "$(utc_now)" >>"$EVIDENCE_FILE"

FINALIZED=1
printf 'Migrations 0011-0020 passed every readiness gate. Audit evidence: %s\n' \
  "$EVIDENCE_FILE"
