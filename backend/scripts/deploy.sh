#!/usr/bin/env bash
# Production deployer for Elevation HQ.
#
# The live tree is never the build workspace. A release-specific stage is built
# first, the prior source/build is archived, and a lock serializes archive
# through health verification or rollback. Dotenv files stay at the live path:
# root-only temporary symlinks make them available to the staged Next build and
# are removed by a remote EXIT trap. No migration or npm lifecycle hook runs.
set -Eeuo pipefail

readonly HOST="root@5.78.46.234"
readonly REMOTE_ROOT="/root/elevation-hq"
readonly REMOTE_DIR="$REMOTE_ROOT/backend"
readonly LOCK_DIR="$REMOTE_ROOT/.deploy-lock"
readonly HEALTH_URL="https://api.elevationrealestatehq.com/api/health"
readonly PM2_PROCESS="elevation-hq"
readonly EXPECTED_ACTIVE_KID="ent-2026-07-a"

MODE=""

usage() {
  cat <<'USAGE'
Usage: scripts/deploy.sh --preflight | --dry-run | --deploy

  --preflight  Validate the local deployment contract. No network access.
  --dry-run    Run preflight and print deployment stages. No network access.
  --deploy     Stage, build, cut over, verify, and roll back on failure.

The deployer never copies, prints, or modifies dotenv contents. It never runs
database migrations; schema changes require a separate explicitly reviewed
migration command and path.
USAGE
}

die() {
  echo "[deploy] ERROR: $*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --preflight | --dry-run | --deploy)
      [[ -z "$MODE" ]] || die "choose exactly one deployment mode"
      MODE="$1"
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
  shift
done

if [[ -z "$MODE" ]]; then
  usage >&2
  die "an explicit mode is required"
fi

cd "$(dirname "$0")/.."

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

check_package_contract() {
  node --input-type=module <<'NODE'
import { readFileSync } from "node:fs";

const packageJson = JSON.parse(readFileSync("package.json", "utf8"));
if (packageJson?.scripts?.build !== "next build") {
  throw new Error('backend scripts.build must remain exactly "next build"');
}
const configured = Object.keys(packageJson?.scripts || {}).filter(
  (name) => /^(?:pre|post)/.test(name) || ["install", "prepare", "dependencies"].includes(name),
);
if (configured.length > 0) {
  throw new Error(`npm lifecycle hooks are forbidden in backend deploys: ${configured.join(",")}`);
}
NODE
}

run_local_preflight() {
  require_command bash
  require_command node

  [[ -f package.json ]] || die "backend/package.json is missing"
  [[ -f package-lock.json ]] || die "backend/package-lock.json is missing"
  [[ -f scripts/verify-entitlement-health.ts ]] || die "health verifier is missing"
  [[ -d node_modules/tsx ]] || die "backend dependencies are missing; run npm ci locally first"
  [[ -x node_modules/.bin/next ]] || die "local Next.js executable is missing"

  bash -n scripts/deploy.sh
  check_package_contract
  node --import tsx scripts/verify-entitlement-health.ts --self-check
  echo "[deploy] local preflight passed"
}

run_local_preflight

if [[ "$MODE" == "--preflight" ]]; then
  exit 0
fi

if [[ "$MODE" == "--deploy" ]]; then
  require_command git
  [[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] || {
    die "refusing deployment from a dirty or untracked working tree"
  }
  CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD)" || {
    die "deployment requires a named branch"
  }
  SOURCE_REV="$(git rev-parse --verify HEAD)"
  [[ "$SOURCE_REV" =~ ^[0-9a-f]{40,64}$ ]] || die "git HEAD is not a full commit id"
  UPSTREAM_REF="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" || {
    die "deployment branch has no tracked upstream"
  }
  UPSTREAM_REV="$(git rev-parse --verify "$UPSTREAM_REF")"
  [[ "$SOURCE_REV" == "$UPSTREAM_REV" ]] || {
    die "git HEAD must exactly match its tracked upstream before deployment"
  }
  UPSTREAM_REMOTE="$(git config --get "branch.$CURRENT_BRANCH.remote")" || {
    die "deployment branch has no configured upstream remote"
  }
  UPSTREAM_MERGE="$(git config --get "branch.$CURRENT_BRANCH.merge")" || {
    die "deployment branch has no configured upstream merge ref"
  }
  [[ -n "$UPSTREAM_REMOTE" && "$UPSTREAM_REMOTE" != "." ]] || {
    die "deployment upstream must be a real remote"
  }
  [[ "$UPSTREAM_MERGE" == refs/heads/* ]] || {
    die "deployment upstream merge ref is invalid"
  }
  REMOTE_REF_OUTPUT="$(
    git ls-remote --exit-code "$UPSTREAM_REMOTE" "$UPSTREAM_MERGE"
  )" || {
    die "could not verify the live upstream ref"
  }
  [[ "$(printf '%s\n' "$REMOTE_REF_OUTPUT" | awk 'NF { count += 1 } END { print count + 0 }')" -eq 1 ]] || {
    die "live upstream ref did not resolve exactly once"
  }
  REMOTE_REV="$(printf '%s\n' "$REMOTE_REF_OUTPUT" | awk 'NF { print $1 }')"
  [[ "$REMOTE_REV" =~ ^[0-9a-f]{40,64}$ ]] || {
    die "live upstream ref did not resolve to a full commit id"
  }
  [[ "$SOURCE_REV" == "$REMOTE_REV" ]] || {
    die "git HEAD must exactly match the live upstream ref before deployment"
  }
else
  SOURCE_REV="$(git rev-parse --verify HEAD 2>/dev/null || printf 'no-git')"
fi
DEPLOY_ID="$(date -u +%Y%m%dT%H%M%SZ)-$SOURCE_REV"
[[ "$DEPLOY_ID" =~ ^[A-Za-z0-9._-]{1,128}$ ]] || die "generated deploy id is unsafe"

readonly DEPLOY_ID
readonly STAGE_DIR="$REMOTE_ROOT/.deploy-staging/$DEPLOY_ID"
readonly ROLLBACK_DIR="$REMOTE_ROOT/.deploy-rollbacks/$DEPLOY_ID"

if [[ "$MODE" == "--dry-run" ]]; then
  cat <<EOF
[deploy] dry-run only; no remote or public endpoint was contacted
[deploy] release: $DEPLOY_ID
[deploy] 1. acquire $LOCK_DIR for archive through cleanup/rollback
[deploy] 2. archive and validate current source plus .next/server
[deploy] 3. record the prior public health fingerprint without storing its body
[deploy] 4. stream the exact committed backend tree to $STAGE_DIR
[deploy] 5. temporarily link exact live dotenv names into the root-only stage
[deploy] 6. npm ci --ignore-scripts; invoke Next directly with build id $DEPLOY_ID
[deploy] 7. cut over, reload PM2, and require three matching entitlement/schema samples
[deploy] signer activation gate: $EXPECTED_ACTIVE_KID
[deploy] 8. on failure, restore archive, require PM2 online and prior-health fingerprint
[deploy] database migrations: disabled; live schema is checked read-only
EOF
  exit 0
fi

require_command rsync
require_command ssh

remote_command() {
  local rendered
  printf -v rendered 'bash -s -- %q %q %q %q %q %q' \
    "$REMOTE_DIR" "$STAGE_DIR" "$ROLLBACK_DIR" "$LOCK_DIR" "$DEPLOY_ID" \
    "$EXPECTED_ACTIVE_KID"
  printf '%s' "$rendered"
}

LOCK_ACQUIRED=0
CUTOVER_STARTED=0
DEPLOY_SUCCEEDED=0
PRIOR_HEALTH_FINGERPRINT=""

cleanup_remote_deploy() {
  ssh "$HOST" "$(remote_command)" <<'REMOTE_CLEANUP'
set -Eeuo pipefail
readonly stage_dir="$2"
readonly lock_dir="$4"
readonly deploy_id="$5"

[[ -f "$lock_dir/deploy-id" ]] || exit 1
[[ "$(<"$lock_dir/deploy-id")" == "$deploy_id" ]] || exit 1
rm -rf -- "$stage_dir"
rm -f -- "$lock_dir/deploy-id"
rmdir -- "$lock_dir"
REMOTE_CLEANUP
}

restore_remote_rollback() {
  ssh "$HOST" "$(remote_command)" <<'REMOTE_ROLLBACK'
set -Eeuo pipefail
readonly current_dir="$1"
readonly rollback_backend="$3/backend"
readonly lock_dir="$4"
readonly deploy_id="$5"

[[ -f "$lock_dir/deploy-id" ]] || exit 1
[[ "$(<"$lock_dir/deploy-id")" == "$deploy_id" ]] || exit 1
[[ -f "$rollback_backend/package.json" ]] || {
  echo "[deploy] rollback package metadata is unavailable" >&2
  exit 1
}
[[ -d "$rollback_backend/.next/server" ]] || {
  echo "[deploy] rollback server build is unavailable" >&2
  exit 1
}
[[ -x "$rollback_backend/node_modules/.bin/next" ]] || {
  echo "[deploy] rollback dependencies are unavailable" >&2
  exit 1
}

# A failed new release may already be online when health verification trips.
# Stop it before restoring the archived module/build tree so rollback cannot
# expose a mixed new/old release to traffic.
pm2 stop elevation-hq
pm2 jlist | node -e '
let input="";
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  try {
    const processes = JSON.parse(input);
    const target = processes.find((entry) => entry?.name === "elevation-hq");
    process.exit(target?.pm2_env?.status === "stopped" ? 0 : 1);
  } catch { process.exit(1); }
});'

rsync -a --delete \
  --exclude=.git \
  --exclude=.vercel \
  --exclude=.env \
  --exclude=.env.local \
  --exclude=.env.production.local \
  --exclude='.env.*' \
  "$rollback_backend/" "$current_dir/"

cd "$current_dir"
pm2 restart elevation-hq --update-env
pm2 jlist | node -e '
let input="";
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  try {
    const processes = JSON.parse(input);
    const target = processes.find((entry) => entry?.name === "elevation-hq");
    process.exit(target?.pm2_env?.status === "online" ? 0 : 1);
  } catch { process.exit(1); }
});'
REMOTE_ROLLBACK
}

on_exit() {
  local status=$?
  trap - EXIT INT TERM

  if [[ "$status" -ne 0 && "$LOCK_ACQUIRED" -eq 1 ]]; then
    if [[ "$CUTOVER_STARTED" -eq 1 && "$DEPLOY_SUCCEEDED" -eq 0 ]]; then
      echo "[deploy] cutover failed; restoring archived source/build" >&2
      if restore_remote_rollback && \
        [[ -n "$PRIOR_HEALTH_FINGERPRINT" ]] && \
        node --import tsx scripts/verify-entitlement-health.ts \
          --fingerprint \
          --url "$HEALTH_URL" \
          --expected-fingerprint "$PRIOR_HEALTH_FINGERPRINT" \
          --attempts 30 \
          --consecutive 2 \
          --delay-ms 11000 >/dev/null
      then
        if cleanup_remote_deploy; then
          echo "[deploy] rollback is online and matches the prior health contract" >&2
        else
          echo "[deploy] rollback passed but deployment lock cleanup failed" >&2
        fi
      else
        echo "[deploy] CRITICAL: rollback proof failed; lock and archive retained" >&2
      fi
    else
      if cleanup_remote_deploy; then
        echo "[deploy] failed stage removed; rollback archive retained" >&2
      else
        echo "[deploy] failed to clean stage/lock; inspect $LOCK_DIR" >&2
      fi
    fi
  fi
  exit "$status"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[deploy] acquiring lock and archiving current remote source/build"
ssh "$HOST" "$(remote_command)" <<'REMOTE_ARCHIVE'
set -Eeuo pipefail
umask 077
readonly current_dir="$1"
readonly stage_dir="$2"
readonly rollback_dir="$3"
readonly rollback_backend="$rollback_dir/backend"
readonly lock_dir="$4"
readonly deploy_id="$5"
lock_created=0

release_failed_lock() {
  local status=$?
  if [[ "$status" -ne 0 && "$lock_created" -eq 1 ]]; then
    rm -rf -- "$stage_dir" "$rollback_dir"
    rm -f -- "$lock_dir/deploy-id"
    rmdir -- "$lock_dir" 2>/dev/null || true
  fi
  exit "$status"
}
trap release_failed_lock EXIT

[[ -d "$current_dir" ]] || { echo "[deploy] live backend directory is missing" >&2; exit 1; }
if ! mkdir -m 700 -- "$lock_dir"; then
  echo "[deploy] another deployment holds the remote lock" >&2
  exit 1
fi
lock_created=1
printf '%s\n' "$deploy_id" >"$lock_dir/deploy-id"
chmod 600 "$lock_dir/deploy-id"

[[ ! -e "$stage_dir" ]] || { echo "[deploy] staging directory already exists" >&2; exit 1; }
[[ ! -e "$rollback_dir" ]] || { echo "[deploy] rollback archive already exists" >&2; exit 1; }
install -d -m 700 "$stage_dir" "$rollback_backend"

rsync -a --delete \
  --exclude=.git \
  --exclude=.vercel \
  --exclude=.env \
  --exclude=.env.local \
  --exclude=.env.production.local \
  --exclude='.env.*' \
  "$current_dir/" "$rollback_backend/"

[[ -f "$rollback_backend/package.json" ]] || {
  echo "[deploy] rollback package metadata is incomplete" >&2
  exit 1
}
[[ -d "$rollback_backend/.next/server" ]] || {
  echo "[deploy] rollback server build is incomplete" >&2
  exit 1
}
[[ -x "$rollback_backend/node_modules/.bin/next" ]] || {
  echo "[deploy] rollback dependencies are incomplete" >&2
  exit 1
}
trap - EXIT
REMOTE_ARCHIVE
LOCK_ACQUIRED=1

echo "[deploy] recording prior public health contract"
PRIOR_HEALTH_FINGERPRINT="$(
  node --import tsx scripts/verify-entitlement-health.ts \
    --fingerprint \
    --url "$HEALTH_URL" \
    --attempts 5 \
    --consecutive 2 \
    --delay-ms 1000
)"
[[ "$PRIOR_HEALTH_FINGERPRINT" =~ ^http-2[0-9][0-9]-sha256-[0-9a-f]{64}$ ]] || {
  die "prior public health fingerprint is invalid"
}

echo "[deploy] streaming exact committed backend source to isolated staging"
printf -v REMOTE_EXTRACT_SCRIPT \
  'set -Eeuo pipefail; readonly stage_dir=%q; readonly lock_dir=%q; readonly deploy_id=%q; command -v tar >/dev/null; [[ -f "$lock_dir/deploy-id" ]]; [[ "$(<"$lock_dir/deploy-id")" == "$deploy_id" ]]; [[ -d "$stage_dir" ]]; tar -xpf - -C "$stage_dir"; [[ -f "$stage_dir/package.json" && -f "$stage_dir/package-lock.json" ]]' \
  "$STAGE_DIR" "$LOCK_DIR" "$DEPLOY_ID"
printf -v REMOTE_EXTRACT_COMMAND 'bash -c %q' "$REMOTE_EXTRACT_SCRIPT"
git archive --format=tar "$SOURCE_REV:backend" \
  | ssh "$HOST" "$REMOTE_EXTRACT_COMMAND"

echo "[deploy] building staged source with temporary root-only dotenv links"
ssh "$HOST" "$(remote_command)" <<'REMOTE_BUILD'
set -Eeuo pipefail
readonly current_dir="$1"
readonly stage_dir="$2"
readonly lock_dir="$4"
readonly deploy_id="$5"
readonly expected_active_kid="$6"
readonly -a dotenv_names=(.env .env.local .env.production .env.production.local)

[[ -f "$lock_dir/deploy-id" ]] || exit 1
[[ "$(<"$lock_dir/deploy-id")" == "$deploy_id" ]] || exit 1
[[ -f "$stage_dir/package.json" && -f "$stage_dir/package-lock.json" ]] || {
  echo "[deploy] staged package metadata is missing" >&2
  exit 1
}
chmod 700 "$stage_dir"

remove_dotenv_links() {
  local name
  for name in "${dotenv_names[@]}"; do
    [[ -L "$stage_dir/$name" ]] && rm -f -- "$stage_dir/$name"
  done
}
trap remove_dotenv_links EXIT

for name in "${dotenv_names[@]}"; do
  [[ ! -e "$stage_dir/$name" && ! -L "$stage_dir/$name" ]] || {
    echo "[deploy] staged dotenv path unexpectedly exists" >&2
    exit 1
  }
  if [[ -e "$current_dir/$name" ]]; then
    [[ -f "$current_dir/$name" ]] || {
      echo "[deploy] live dotenv path is not a regular file" >&2
      exit 1
    }
    ln -s -- "$current_dir/$name" "$stage_dir/$name"
  fi
done

cd "$stage_dir"
node --input-type=module <<'NODE'
import { readFileSync } from "node:fs";
const packageJson = JSON.parse(readFileSync("package.json", "utf8"));
if (packageJson?.scripts?.build !== "next build") process.exit(1);
const configured = Object.keys(packageJson?.scripts || {}).filter(
  (name) => /^(?:pre|post)/.test(name) || ["install", "prepare", "dependencies"].includes(name),
);
if (configured.length > 0) {
  process.exit(1);
}
NODE

npm ci --ignore-scripts --no-audit --no-fund --silent
[[ -x ./node_modules/.bin/next ]] || { echo "[deploy] staged Next.js executable is missing" >&2; exit 1; }
NODE_ENV=production \
  EXPECTED_ACTIVE_KID_FOR_DEPLOY="$expected_active_kid" \
  node --import tsx --input-type=module <<'NODE'
const nextEnv = (await import("@next/env")).default;
nextEnv.loadEnvConfig(process.cwd(), false);
const entitlement = (await import("./src/lib/entitlement-assertion.ts")).default;
const readiness = entitlement.entitlementSignerReadiness();
if (
  readiness.ready !== true ||
  readiness.activeKid !== process.env.EXPECTED_ACTIVE_KID_FOR_DEPLOY ||
  readiness.configurationMode !== "key-ring" ||
  readiness.completeKeyRingReady !== true
) {
  console.error("[deploy] staged complete signer ring does not match the rollout key");
  process.exit(1);
}
console.log("[deploy] staged complete signer ring matches the rollout key");
NODE
ELEVATE_BACKEND_BUILD_ID="$deploy_id" \
  NEXT_TELEMETRY_DISABLED=1 \
  NODE_ENV=production \
  ./node_modules/.bin/next build
[[ -d .next/server ]] || { echo "[deploy] staged Next.js server build is missing" >&2; exit 1; }
REMOTE_BUILD

echo "[deploy] cutting over staged release while preserving local-only paths"
CUTOVER_STARTED=1
ssh "$HOST" "$(remote_command)" <<'REMOTE_CUTOVER'
set -Eeuo pipefail
readonly current_dir="$1"
readonly stage_dir="$2"
readonly lock_dir="$4"
readonly deploy_id="$5"

[[ -f "$lock_dir/deploy-id" ]] || exit 1
[[ "$(<"$lock_dir/deploy-id")" == "$deploy_id" ]] || exit 1
[[ -d "$stage_dir/.next/server" ]] || {
  echo "[deploy] refusing cutover without a staged server build" >&2
  exit 1
}

# Keep the old worker from loading a mixed old/new module or .next tree while
# rsync replaces the live directory. The health gate below bounds the brief
# maintenance window and the EXIT trap restores the archived release on error.
pm2 stop elevation-hq
pm2 jlist | node -e '
let input="";
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  try {
    const processes = JSON.parse(input);
    const target = processes.find((entry) => entry?.name === "elevation-hq");
    process.exit(target?.pm2_env?.status === "stopped" ? 0 : 1);
  } catch { process.exit(1); }
});'

rsync -a --delete \
  --exclude=.git \
  --exclude=.vercel \
  --exclude=.env \
  --exclude=.env.local \
  --exclude=.env.production.local \
  --exclude='.env.*' \
  "$stage_dir/" "$current_dir/"

pm2 restart elevation-hq --update-env
pm2 jlist | node -e '
let input="";
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  try {
    const processes = JSON.parse(input);
    const target = processes.find((entry) => entry?.name === "elevation-hq");
    process.exit(target?.pm2_env?.status === "online" ? 0 : 1);
  } catch { process.exit(1); }
});'
REMOTE_CUTOVER

echo "[deploy] requiring build-bound entitlement and schema readiness"
node --import tsx scripts/verify-entitlement-health.ts \
  --url "$HEALTH_URL" \
  --expected-build-id "$DEPLOY_ID" \
  --expected-active-kid "$EXPECTED_ACTIVE_KID" \
  --attempts 30 \
  --consecutive 3 \
  --delay-ms 11000

DEPLOY_SUCCEEDED=1
echo "[deploy] verified; removing stage and releasing deployment lock"
cleanup_remote_deploy
LOCK_ACQUIRED=0
trap - EXIT INT TERM

echo "[deploy] live and entitlement/schema-ready at $HEALTH_URL"
echo "[deploy] rollback archive: $HOST:$ROLLBACK_DIR"
