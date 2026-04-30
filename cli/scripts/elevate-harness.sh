#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(cd "$CLI_DIR/.." && pwd)"

HARNESS_ROOT="${ELEVATE_HARNESS_ROOT:-}"
KEEP="${ELEVATE_HARNESS_KEEP:-0}"

usage() {
    cat <<'EOF'
Elevate harness

Usage:
  cli/scripts/elevate-harness.sh audit
  cli/scripts/elevate-harness.sh smoke
  cli/scripts/elevate-harness.sh install
  cli/scripts/elevate-harness.sh migration
  cli/scripts/elevate-harness.sh uninstall
  cli/scripts/elevate-harness.sh all

Environment:
  ELEVATE_HARNESS_ROOT=/tmp/elevate-harness   Reuse a specific temp root
  ELEVATE_HARNESS_KEEP=1                      Keep temp files after run
  ELEVATE_INSTALL_EXTRAS=...                  Override setup-elevate extras
EOF
}

make_root() {
    if [ -n "$HARNESS_ROOT" ]; then
        mkdir -p "$HARNESS_ROOT"
    else
        HARNESS_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/elevate-harness.XXXXXX")"
    fi
}

cleanup() {
    if [ "$KEEP" != "1" ] && [ -n "${HARNESS_ROOT:-}" ] && [ -d "$HARNESS_ROOT" ]; then
        rm -rf "$HARNESS_ROOT"
    fi
}

copy_repo() {
    local dst="$1"
    mkdir -p "$dst"
    rsync -a \
        --exclude '.git' \
        --exclude '.venv' \
        --exclude 'venv' \
        --exclude 'node_modules' \
        --exclude '__pycache__' \
        --exclude '.pytest_cache' \
        --exclude '.mypy_cache' \
        --exclude '.ruff_cache' \
        "$REPO_DIR/" "$dst/"
}

run_audit() {
    "$CLI_DIR/.venv/bin/python" "$CLI_DIR/scripts/elevate_separation_audit.py"
}

run_smoke() {
    (cd "$CLI_DIR" && bash -n setup-elevate.sh)
    (cd "$CLI_DIR" && .venv/bin/python -m compileall -q elevate_cli cli.py run_agent.py model_tools.py toolsets.py)
    (cd "$CLI_DIR" && ./elevate --help >/dev/null)
    local dry_run_output
    dry_run_output="$(cd "$CLI_DIR" && ./elevate uninstall --full --yes --dry-run)"
    grep -q "Keep source code directory" <<<"$dry_run_output"
    echo "Smoke checks passed"
}

run_install() {
    make_root
    local repo="$HARNESS_ROOT/install/repo"
    local home="$HARNESS_ROOT/install/home"
    copy_repo "$repo"
    mkdir -p "$home"
    (
        cd "$repo/cli"
        HOME="$home" \
        ELEVATE_HOME="$home/.elevate" \
        ELEVATE_MIGRATE_HERMES=0 \
        ELEVATE_SKIP_SETUP_PROMPT=1 \
        ./setup-elevate.sh
    )
    HOME="$home" ELEVATE_HOME="$home/.elevate" PATH="$home/.local/bin:$PATH" elevate --help >/dev/null
    HOME="$home" ELEVATE_HOME="$home/.elevate" PATH="$home/.local/bin:$PATH" elevate status >/dev/null
    test -f "$home/.elevate/config.yaml"
    test -f "$home/.elevate/.env"
    echo "Fresh install harness passed: $HARNESS_ROOT/install"
}

run_migration() {
    make_root
    local repo="$HARNESS_ROOT/migration/repo"
    local home="$HARNESS_ROOT/migration/home"
    copy_repo "$repo"
    mkdir -p "$home/.hermes/skills/demo" "$home/.hermes/memories" "$home/.hermes/sessions"
    cat > "$home/.hermes/config.yaml" <<'YAML'
_config_version: 22
enabled_toolsets:
  - hermes-cli
gateway:
  toolset: hermes-telegram
command_allowlist:
  - stop/restart hermes gateway
  - hermes update
YAML
    printf 'TELEGRAM_BOT_TOKEN=fake\n' > "$home/.hermes/.env"
    printf '{"provider":"codex"}\n' > "$home/.hermes/auth.json"
    printf '{"telegram":["123"]}\n' > "$home/.hermes/channel_directory.json"
    printf '# Demo\n' > "$home/.hermes/skills/demo/SKILL.md"
    printf '# Memory\n' > "$home/.hermes/memories/MEMORY.md"
    sqlite3 "$home/.hermes/state.db" 'create table sessions(id text); insert into sessions values("s1");'

    (
        cd "$repo/cli"
        HOME="$home" \
        ELEVATE_HOME="$home/.elevate" \
        ELEVATE_MIGRATE_HERMES=1 \
        ELEVATE_SKIP_SETUP_PROMPT=1 \
        ELEVATE_INSTALL_EXTRAS="${ELEVATE_INSTALL_EXTRAS-}" \
        ./setup-elevate.sh
    )

    rg 'hermes-(cli|telegram)|hermes update|stop/restart hermes gateway' "$home/.elevate/config.yaml" && {
        echo "Migration left Hermes command names in config" >&2
        return 1
    }
    rg 'elevate-(cli|telegram)|elevate update|stop/restart elevate gateway' "$home/.elevate/config.yaml" >/dev/null
    test "$(sqlite3 "$home/.elevate/state.db" 'select count(*) from sessions;')" = "1"
    find "$home/.elevate/migration-backups" -mindepth 1 -maxdepth 1 -type d | grep -q .
    echo "Hermes migration harness passed: $HARNESS_ROOT/migration"
}

run_uninstall() {
    make_root
    local repo="$HARNESS_ROOT/uninstall/repo"
    local home="$HARNESS_ROOT/uninstall/home"
    copy_repo "$repo"
    mkdir -p "$home"
    (
        cd "$repo/cli"
        HOME="$home" \
        ELEVATE_HOME="$home/.elevate" \
        ELEVATE_MIGRATE_HERMES=0 \
        ELEVATE_SKIP_SETUP_PROMPT=1 \
        ./setup-elevate.sh >/dev/null
    )
    HOME="$home" ELEVATE_HOME="$home/.elevate" PATH="$home/.local/bin:$PATH" elevate uninstall --full --yes >/dev/null
    test ! -e "$home/.local/bin/elevate"
    test ! -e "$home/.elevate"
    test ! -e "$repo/cli"
    echo "Full uninstall harness passed: $HARNESS_ROOT/uninstall"
}

main() {
    local cmd="${1:-}"
    case "$cmd" in
        audit) run_audit ;;
        smoke) run_smoke ;;
        install) trap cleanup EXIT; run_install ;;
        migration) trap cleanup EXIT; run_migration ;;
        uninstall) trap cleanup EXIT; run_uninstall ;;
        all)
            trap cleanup EXIT
            run_audit
            run_smoke
            run_install
            run_migration
            run_uninstall
            ;;
        -h|--help|help|"") usage ;;
        *) echo "Unknown harness command: $cmd" >&2; usage >&2; return 2 ;;
    esac
}

main "$@"
