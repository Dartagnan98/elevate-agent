#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

bash -n scripts/deploy.sh

if scripts/deploy.sh >/dev/null 2>&1; then
  echo "deploy.sh must require an explicit mode" >&2
  exit 1
fi

dry_run_output="$(scripts/deploy.sh --dry-run)"
grep -Fq "no remote or public endpoint was contacted" <<<"$dry_run_output"
grep -Fq "archive and validate current source plus .next/server" <<<"$dry_run_output"
grep -Fq "acquire /root/elevation-hq/.deploy-lock" <<<"$dry_run_output"
grep -Fq "three matching entitlement/schema samples" <<<"$dry_run_output"
grep -Fq "stream the exact committed backend tree" <<<"$dry_run_output"
grep -Fq "database migrations: disabled" <<<"$dry_run_output"

grep -Fq -- "--exclude=.env.local" scripts/deploy.sh
grep -Fq -- "--exclude=.env.production.local" scripts/deploy.sh
grep -Fq -- "--exclude='.env.*'" scripts/deploy.sh
grep -Fq -- "npm ci --ignore-scripts" scripts/deploy.sh
grep -Fq -- "verify-entitlement-health.ts" scripts/deploy.sh
grep -Fq -- "./node_modules/.bin/next build" scripts/deploy.sh
grep -Fq -- "--expected-build-id \"\$DEPLOY_ID\"" scripts/deploy.sh
grep -Fq -- "--consecutive 3" scripts/deploy.sh
grep -Fq -- 'readonly -a dotenv_names=(.env .env.local .env.production.local)' scripts/deploy.sh
grep -Fq -- "trap remove_dotenv_links EXIT" scripts/deploy.sh
grep -Fq -- 'mkdir -m 700 -- "$lock_dir"' scripts/deploy.sh
grep -Fq -- '[[ -d "$rollback_backend/.next/server" ]]' scripts/deploy.sh
grep -Fq -- "pm2 jlist" scripts/deploy.sh
grep -Fq -- "--expected-fingerprint \"\$PRIOR_HEALTH_FINGERPRINT\"" scripts/deploy.sh
grep -Fq -- "git status --porcelain=v1 --untracked-files=all" scripts/deploy.sh
grep -Fq -- "git HEAD must exactly match its tracked upstream" scripts/deploy.sh
grep -Fq -- 'git ls-remote --exit-code "$UPSTREAM_REMOTE" "$UPSTREAM_MERGE"' scripts/deploy.sh
grep -Fq -- 'git archive --format=tar "$SOURCE_REV:backend"' scripts/deploy.sh
grep -Fq -- 'pm2 stop elevation-hq' scripts/deploy.sh
grep -Fq -- '--delay-ms 11000' scripts/deploy.sh

if grep -Fq -- "npm run build" scripts/deploy.sh; then
  echo "deploy must invoke Next directly without npm pre/post hooks" >&2
  exit 1
fi

env_exclusion_count="$(grep -Fc -- "--exclude='.env.*'" scripts/deploy.sh)"
[[ "$env_exclusion_count" -eq 3 ]] || {
  echo "dotenv wildcard must protect archive, cutover, and rollback" >&2
  exit 1
}

git_exclusion_count="$(grep -Fc -- "--exclude=.git" scripts/deploy.sh)"
vercel_exclusion_count="$(grep -Fc -- "--exclude=.vercel" scripts/deploy.sh)"
[[ "$git_exclusion_count" -eq 3 && "$vercel_exclusion_count" -eq 3 ]] || {
  echo ".git and .vercel must be protected in archive, cutover, and rollback" >&2
  exit 1
}

archive_line="$(grep -nFm1 "acquiring lock and archiving current remote source/build" scripts/deploy.sh | cut -d: -f1)"
upload_line="$(grep -nFm1 "streaming exact committed backend source" scripts/deploy.sh | cut -d: -f1)"
[[ "$archive_line" -lt "$upload_line" ]] || {
  echo "remote archive must happen before source upload" >&2
  exit 1
}

# A dirty/untracked source must stop before either network-capable command can
# run. Stub node/git so this regression stays local and deterministic.
dirty_harness="$(mktemp -d "${TMPDIR:-/tmp}/elevate-deploy-dirty.XXXXXX")"
trap 'rm -rf "$dirty_harness"' EXIT
mkdir -p \
  "$dirty_harness/scripts" \
  "$dirty_harness/node_modules/tsx" \
  "$dirty_harness/node_modules/.bin" \
  "$dirty_harness/bin"
cp scripts/deploy.sh "$dirty_harness/scripts/deploy.sh"
chmod 755 "$dirty_harness/scripts/deploy.sh"
touch \
  "$dirty_harness/package.json" \
  "$dirty_harness/package-lock.json" \
  "$dirty_harness/scripts/verify-entitlement-health.ts"

for command_name in node; do
  printf '#!/usr/bin/env bash\nexit 0\n' >"$dirty_harness/bin/$command_name"
  chmod 755 "$dirty_harness/bin/$command_name"
done
printf '#!/usr/bin/env bash\nexit 0\n' >"$dirty_harness/node_modules/.bin/next"
chmod 755 "$dirty_harness/node_modules/.bin/next"
printf '#!/usr/bin/env bash\nif [[ "$1" == status ]]; then printf "?? untracked-file\\n"; exit 0; fi\nexit 90\n' \
  >"$dirty_harness/bin/git"
chmod 755 "$dirty_harness/bin/git"
for command_name in ssh rsync; do
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >"$DEPLOY_NETWORK_MARKER"\nexit 91\n' \
    >"$dirty_harness/bin/$command_name"
  chmod 755 "$dirty_harness/bin/$command_name"
done

network_marker="$dirty_harness/network-called"
set +e
dirty_output="$(
  DEPLOY_NETWORK_MARKER="$network_marker" \
    PATH="$dirty_harness/bin:/usr/bin:/bin" \
    "$dirty_harness/scripts/deploy.sh" --deploy 2>&1
)"
dirty_status=$?
set -e
[[ "$dirty_status" -ne 0 ]] || {
  echo "dirty deployment unexpectedly succeeded" >&2
  exit 1
}
grep -Fq "dirty or untracked working tree" <<<"$dirty_output"
[[ ! -e "$network_marker" ]] || {
  echo "dirty deployment reached ssh or rsync" >&2
  exit 1
}

# A clean commit without a tracked upstream must also fail before remote access.
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'case "$*" in' \
  '  "status --porcelain=v1 --untracked-files=all") exit 0 ;;' \
  '  "symbolic-ref --quiet --short HEAD") printf "beta\\n" ;;' \
  '  "rev-parse --verify HEAD") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n" ;;' \
  '  "rev-parse --abbrev-ref --symbolic-full-name @{upstream}") exit 1 ;;' \
  '  *) exit 90 ;;' \
  'esac' >"$dirty_harness/bin/git"
rm -f "$network_marker"
set +e
no_upstream_output="$(
  DEPLOY_NETWORK_MARKER="$network_marker" \
    PATH="$dirty_harness/bin:/usr/bin:/bin" \
    "$dirty_harness/scripts/deploy.sh" --deploy 2>&1
)"
no_upstream_status=$?
set -e
[[ "$no_upstream_status" -ne 0 ]] || {
  echo "deployment without an upstream unexpectedly succeeded" >&2
  exit 1
}
grep -Fq "deployment branch has no tracked upstream" <<<"$no_upstream_output"
[[ ! -e "$network_marker" ]] || {
  echo "deployment without an upstream reached ssh or rsync" >&2
  exit 1
}

# A clean local commit that differs from its tracked upstream is not a
# publishable source identity and must fail before remote access.
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'case "$*" in' \
  '  "status --porcelain=v1 --untracked-files=all") exit 0 ;;' \
  '  "symbolic-ref --quiet --short HEAD") printf "beta\\n" ;;' \
  '  "rev-parse --verify HEAD") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n" ;;' \
  '  "rev-parse --abbrev-ref --symbolic-full-name @{upstream}") printf "origin/beta\\n" ;;' \
  '  "rev-parse --verify origin/beta") printf "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\n" ;;' \
  '  *) exit 90 ;;' \
  'esac' >"$dirty_harness/bin/git"
rm -f "$network_marker"
set +e
upstream_mismatch_output="$(
  DEPLOY_NETWORK_MARKER="$network_marker" \
    PATH="$dirty_harness/bin:/usr/bin:/bin" \
    "$dirty_harness/scripts/deploy.sh" --deploy 2>&1
)"
upstream_mismatch_status=$?
set -e
[[ "$upstream_mismatch_status" -ne 0 ]] || {
  echo "deployment with mismatched upstream unexpectedly succeeded" >&2
  exit 1
}
grep -Fq "git HEAD must exactly match its tracked upstream" \
  <<<"$upstream_mismatch_output"
[[ ! -e "$network_marker" ]] || {
  echo "deployment with mismatched upstream reached ssh or rsync" >&2
  exit 1
}

# A matching cached tracking ref is insufficient when the live remote ref has
# moved. This gate must also fail before any ssh/rsync call.
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'case "$*" in' \
  '  "status --porcelain=v1 --untracked-files=all") exit 0 ;;' \
  '  "symbolic-ref --quiet --short HEAD") printf "beta\\n" ;;' \
  '  "rev-parse --verify HEAD") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n" ;;' \
  '  "rev-parse --abbrev-ref --symbolic-full-name @{upstream}") printf "origin/beta\\n" ;;' \
  '  "rev-parse --verify origin/beta") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n" ;;' \
  '  "config --get branch.beta.remote") printf "origin\\n" ;;' \
  '  "config --get branch.beta.merge") printf "refs/heads/beta\\n" ;;' \
  '  "ls-remote --exit-code origin refs/heads/beta") printf "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\trefs/heads/beta\\n" ;;' \
  '  *) exit 90 ;;' \
  'esac' >"$dirty_harness/bin/git"
rm -f "$network_marker"
set +e
live_upstream_mismatch_output="$(
  DEPLOY_NETWORK_MARKER="$network_marker" \
    PATH="$dirty_harness/bin:/usr/bin:/bin" \
    "$dirty_harness/scripts/deploy.sh" --deploy 2>&1
)"
live_upstream_mismatch_status=$?
set -e
[[ "$live_upstream_mismatch_status" -ne 0 ]] || {
  echo "deployment with a moved live upstream unexpectedly succeeded" >&2
  exit 1
}
grep -Fq "git HEAD must exactly match the live upstream ref" \
  <<<"$live_upstream_mismatch_output"
[[ ! -e "$network_marker" ]] || {
  echo "live-upstream mismatch reached ssh or rsync" >&2
  exit 1
}

# Once every provenance gate matches, the rendered remote command must carry
# the full commit identity (the ssh executable remains a local test stub).
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'case "$*" in' \
  '  "status --porcelain=v1 --untracked-files=all") exit 0 ;;' \
  '  "symbolic-ref --quiet --short HEAD") printf "beta\\n" ;;' \
  '  "rev-parse --verify HEAD") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n" ;;' \
  '  "rev-parse --abbrev-ref --symbolic-full-name @{upstream}") printf "origin/beta\\n" ;;' \
  '  "rev-parse --verify origin/beta") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n" ;;' \
  '  "config --get branch.beta.remote") printf "origin\\n" ;;' \
  '  "config --get branch.beta.merge") printf "refs/heads/beta\\n" ;;' \
  '  "ls-remote --exit-code origin refs/heads/beta") printf "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\trefs/heads/beta\\n" ;;' \
  '  *) exit 90 ;;' \
  'esac' >"$dirty_harness/bin/git"
rm -f "$network_marker"
set +e
matched_output="$(
  DEPLOY_NETWORK_MARKER="$network_marker" \
    PATH="$dirty_harness/bin:/usr/bin:/bin" \
    "$dirty_harness/scripts/deploy.sh" --deploy 2>&1
)"
matched_status=$?
set -e
[[ "$matched_status" -ne 0 ]] || {
  echo "stubbed deployment unexpectedly succeeded" >&2
  exit 1
}
[[ -f "$network_marker" ]] || {
  echo "matching provenance never reached the local ssh stub" >&2
  exit 1
}
grep -Eq '[0-9]{8}T[0-9]{6}Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
  "$network_marker"
grep -Fq "acquiring lock and archiving current remote source/build" \
  <<<"$matched_output"

echo "deploy script static checks passed"
