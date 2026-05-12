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
  cli/scripts/elevate-harness.sh memory
  cli/scripts/elevate-harness.sh memory-stress
  cli/scripts/elevate-harness.sh memory-openai
  cli/scripts/elevate-harness.sh access
  cli/scripts/elevate-harness.sh context-efficiency
  cli/scripts/elevate-harness.sh context-stress
  cli/scripts/elevate-harness.sh adversarial
  cli/scripts/elevate-harness.sh all

Environment:
  ELEVATE_HARNESS_ROOT=/tmp/elevate-harness   Reuse a specific temp root
  ELEVATE_HARNESS_KEEP=1                      Keep temp files after run
  ELEVATE_INSTALL_EXTRAS=...                  Override setup-elevate extras
  OPENAI_API_KEY=...                          Required for memory-openai
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
    mkdir -p "$home/.hermes"
    cat > "$home/.hermes/config.yaml" <<'YAML'
enabled_toolsets:
  - hermes-cli
YAML
    printf 'HERMES_SECRET=should-not-import\n' > "$home/.hermes/.env"
    (
        cd "$repo/cli"
        HOME="$home" \
        ELEVATE_HOME="$home/.elevate" \
        ELEVATE_SKIP_SETUP_PROMPT=1 \
        ./setup-elevate.sh
    )
    HOME="$home" ELEVATE_HOME="$home/.elevate" PATH="$home/.local/bin:$PATH" elevate --help >/dev/null
    HOME="$home" ELEVATE_HOME="$home/.elevate" PATH="$home/.local/bin:$PATH" elevate status >/dev/null
    test -f "$home/.elevate/config.yaml"
    test -f "$home/.elevate/.env"
    ! grep -q 'HERMES_SECRET' "$home/.elevate/.env"
    ! test -d "$home/.elevate/migration-backups"
    echo "Fresh install harness passed: $HARNESS_ROOT/install"
}

run_migration() {
    make_root
    local repo="$HARNESS_ROOT/migration/repo"
    local home="$HARNESS_ROOT/migration/home"
    copy_repo "$repo"
    mkdir -p \
        "$home/.hermes/skills/demo" \
        "$home/.hermes/memories" \
        "$home/.hermes/sessions/2026" \
        "$home/.hermes/cron" \
        "$home/.hermes/secrets" \
        "$home/.hermes/plugins/demo" \
        "$home/.hermes/logs" \
        "$home/.hermes/mcp-tokens"
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
    printf 'Legacy Hermes persona\n' > "$home/.hermes/SOUL.md"
    printf '# Demo\n' > "$home/.hermes/skills/demo/SKILL.md"
    printf '# Memory\n' > "$home/.hermes/memories/MEMORY.md"
    printf '{"id":"session-json"}\n' > "$home/.hermes/sessions/2026/s1.json"
    printf '{"jobs":[{"name":"daily"}]}\n' > "$home/.hermes/cron/jobs.json"
    printf '{"api":"secret"}\n' > "$home/.hermes/secrets/client.json"
    printf 'name: demo\n' > "$home/.hermes/plugins/demo/plugin.yaml"
    printf 'gateway log\n' > "$home/.hermes/logs/gateway.log"
    printf '{"access_token":"token"}\n' > "$home/.hermes/mcp-tokens/server.json"
    printf 'do-not-copy\n' > "$home/.hermes/gateway.pid"
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
    cmp -s "$home/.hermes/.env" "$home/.elevate/.env"
    cmp -s "$home/.hermes/auth.json" "$home/.elevate/auth.json"
    cmp -s "$home/.hermes/channel_directory.json" "$home/.elevate/channel_directory.json"
    cmp -s "$home/.hermes/SOUL.md" "$home/.elevate/SOUL.md"
    cmp -s "$home/.hermes/skills/demo/SKILL.md" "$home/.elevate/skills/demo/SKILL.md"
    cmp -s "$home/.hermes/memories/MEMORY.md" "$home/.elevate/memories/MEMORY.md"
    cmp -s "$home/.hermes/sessions/2026/s1.json" "$home/.elevate/sessions/2026/s1.json"
    cmp -s "$home/.hermes/cron/jobs.json" "$home/.elevate/cron/jobs.json"
    cmp -s "$home/.hermes/secrets/client.json" "$home/.elevate/secrets/client.json"
    cmp -s "$home/.hermes/plugins/demo/plugin.yaml" "$home/.elevate/plugins/demo/plugin.yaml"
    cmp -s "$home/.hermes/logs/gateway.log" "$home/.elevate/logs/gateway.log"
    cmp -s "$home/.hermes/mcp-tokens/server.json" "$home/.elevate/mcp-tokens/server.json"
    test ! -e "$home/.elevate/gateway.pid"
    local report
    report="$(find "$home/.elevate/migration-backups" -name migration-report.json -print -quit)"
    test -n "$report"
    python3 - "$report" <<'PY'
import json
import sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
assert not report["errors"], report
required = {
    ".env",
    "auth.json",
    "channel_directory.json",
    "SOUL.md",
    "skills/demo/SKILL.md",
    "memories/MEMORY.md",
    "sessions/2026/s1.json",
    "cron/jobs.json",
    "secrets/client.json",
    "plugins/demo/plugin.yaml",
    "logs/gateway.log",
    "mcp-tokens/server.json",
    "config.yaml",
    "state.db",
}
missing = required - set(report["verified"])
assert not missing, missing
PY
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

run_memory() {
    make_root
    local db="$HARNESS_ROOT/memory/memory_store.db"
    mkdir -p "$(dirname "$db")"
    (
        cd "$CLI_DIR"
        .venv/bin/python - "$db" <<'PY'
import sys
from plugins.memory.holographic.embeddings import EmbeddingError, HashEmbeddingClient, build_embedding_client
from plugins.memory.holographic.retrieval import FactRetriever
from plugins.memory.holographic.store import MemoryStore

try:
    build_embedding_client({
        "embedding_enabled": "true",
        "embedding_provider": "hash",
        "embedding_dimensions": "auto",
    })
except EmbeddingError:
    pass
else:
    raise AssertionError("invalid embedding_dimensions should raise EmbeddingError")

db_path = sys.argv[1]
store = MemoryStore(
    db_path=db_path,
    embedding_client=HashEmbeddingClient(dimensions=64),
)
store.add_fact(
    "Maria is a buyer lead looking for a quiet mid-century home away from busy roads.",
    category="lead",
    tags="buyer,quiet,mid-century",
)
store.add_fact(
    "Jason is the preferred home inspector for older listings.",
    category="vendor",
    tags="inspector,vendor",
)
status = store.embedding_status()
assert status["enabled"] is True, status
assert status["indexed_facts"] == 2, status
retriever = FactRetriever(store=store, embedding_weight=0.45, hrr_weight=0.0)
results = retriever.search("quiet buyer home", limit=1)
assert results and "Maria" in results[0]["content"], results
backfill = store.backfill_embeddings()
assert backfill["indexed"] == 0, backfill
store.close()
PY
    )
    echo "Memory embedding harness passed: $HARNESS_ROOT/memory"
}

run_memory_openai() {
    make_root
    local db="$HARNESS_ROOT/memory-openai/memory_store.db"
    mkdir -p "$(dirname "$db")"
    (
        cd "$CLI_DIR"
        .venv/bin/python - "$db" <<'PY'
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path.home() / ".elevate/.env")
except Exception:
    pass

if not (os.getenv("OPENAI_API_KEY") or os.getenv("ELEVATE_EMBEDDINGS_API_KEY")):
    raise SystemExit(
        "memory-openai requires OPENAI_API_KEY or ELEVATE_EMBEDDINGS_API_KEY "
        "in the environment or ~/.elevate/.env"
    )

from plugins.memory.holographic.embeddings import build_embedding_client
from plugins.memory.holographic.retrieval import FactRetriever
from plugins.memory.holographic.store import MemoryStore

db_path = sys.argv[1]
client = build_embedding_client({
    "embedding_enabled": "true",
    "embedding_provider": "openai",
    "embedding_model": os.getenv("ELEVATE_EMBEDDING_TEST_MODEL", "text-embedding-3-small"),
})
store = MemoryStore(db_path=db_path, embedding_client=client)
fact_id = store.add_fact(
    "Maria is a buyer lead who wants a quiet mid-century home away from busy roads.",
    category="lead",
    tags="buyer,quiet,mid-century",
)
status = store.embedding_status()
assert status["enabled"] is True, status
assert status["indexed_facts"] == 1, status
assert status["missing_or_stale"] == 0, status
retriever = FactRetriever(store=store, embedding_weight=0.55, hrr_weight=0.0)
results = retriever.search("buyer looking for a calm home away from traffic", limit=1)
assert results and results[0]["fact_id"] == fact_id, results
print(
    "OpenAI memory embedding harness passed: "
    f"provider={status['provider']} model={status['model']} db={db_path}"
)
store.close()
PY
    )
}

run_access() {
    make_root
    local home="$HARNESS_ROOT/access/home"
    local skills="$home/.elevate/skills"
    mkdir -p "$skills/team-skill" "$skills/free-skill"
    cat > "$home/.elevate/config.yaml" <<'YAML'
access:
  profile: standalone
YAML
    cat > "$skills/free-skill/SKILL.md" <<'YAML'
---
name: free-skill
description: Free local skill
---

Free skill body.
YAML
    cat > "$skills/team-skill/SKILL.md" <<'YAML'
---
name: team-skill
description: Team-only skill
access:
  entitlement: real_estate_team_pack
---

Team skill body.
YAML
    (
        cd "$CLI_DIR"
        ELEVATE_HOME="$home/.elevate" .venv/bin/python - <<'PY'
import json
from tools.skills_tool import skills_list, skill_view

listed = json.loads(skills_list())
names = {skill["name"] for skill in listed["skills"]}
assert "free-skill" in names, listed
assert "team-skill" not in names, listed
locked = json.loads(skill_view("team-skill"))
assert locked["success"] is False, locked
assert locked["readiness_status"] == "locked", locked
PY
        ELEVATE_HOME="$home/.elevate" ./elevate access profile team_pack >/dev/null
        ELEVATE_HOME="$home/.elevate" .venv/bin/python - <<'PY'
import json
from tools.skills_tool import skills_list, skill_view

listed = json.loads(skills_list())
names = {skill["name"] for skill in listed["skills"]}
assert "team-skill" in names, listed
loaded = json.loads(skill_view("team-skill"))
assert loaded["success"] is True, loaded
PY
        ELEVATE_HOME="$home/.elevate" ./elevate access affiliation --status left_team >/dev/null
        ELEVATE_HOME="$home/.elevate" .venv/bin/python - <<'PY'
import json
from tools.skills_tool import skills_list

listed = json.loads(skills_list())
names = {skill["name"] for skill in listed["skills"]}
assert "team-skill" not in names, listed
PY
    )
    echo "Access profile harness passed: $HARNESS_ROOT/access"
}

run_memory_stress() {
    make_root
    local db="$HARNESS_ROOT/memory-stress/memory_store.db"
    mkdir -p "$(dirname "$db")"
    (
        cd "$CLI_DIR"
        .venv/bin/python - "$db" <<'PY'
import random
import string
import sys
import threading
import time

from plugins.memory.holographic.embeddings import HashEmbeddingClient
from plugins.memory.holographic.retrieval import FactRetriever
from plugins.memory.holographic.store import MemoryStore

random.seed(42)
db_path = sys.argv[1]
store = MemoryStore(db_path=db_path, embedding_client=HashEmbeddingClient(dimensions=128))

names = ["Maria", "Taylor", "James", "Amanda", "Priya", "Leo", "Nora", "Ethan"]
needs = ["quiet mid-century home", "walkable condo", "large yard", "school district", "duplex", "ocean view"]
areas = ["Kitsilano", "Burnaby", "Mount Pleasant", "North Van", "Richmond", "Victoria"]

fact_ids = []
count = 1200
start = time.perf_counter()
for i in range(count):
    noise = "".join(random.choice(string.ascii_lowercase) for _ in range(16))
    fact_ids.append(store.add_fact(
        f"{names[i % len(names)]} {i} is a lead looking for a {needs[(i * 7) % len(needs)]} in {areas[(i * 11) % len(areas)]}; notes {noise}.",
        category="lead",
        tags=f"{needs[i % len(needs)]},{areas[i % len(areas)]}",
    ))
insert_s = time.perf_counter() - start
status = store.embedding_status()
assert status["facts"] == count, status
assert status["indexed_facts"] == count, status
assert status["missing_or_stale"] == 0, status

retriever = FactRetriever(store=store, embedding_weight=0.55, hrr_weight=0.0)
queries = ["quiet buyer away from traffic", "school district family", "ocean view lead", "walkable condo"] * 40
start = time.perf_counter()
for query in queries:
    results = retriever.search(query, limit=6)
    assert results, query
search_s = time.perf_counter() - start

for fact_id in fact_ids[::25]:
    assert store.update_fact(fact_id, content=f"Updated fact {fact_id}: urgent buyer wants quiet home near parks.")
for fact_id in fact_ids[::40]:
    store.remove_fact(fact_id)
status = store.embedding_status()
assert status["missing_or_stale"] == 0, status

errors = []
def worker(worker_id):
    local = MemoryStore(db_path=db_path, embedding_client=HashEmbeddingClient(dimensions=128))
    try:
        for j in range(30):
            local.add_fact(f"Concurrent worker {worker_id} lead note {j}: calm street and strong schools.", category="lead")
    except Exception as exc:
        errors.append((worker_id, repr(exc)))
    finally:
        local.close()

threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
assert not errors, errors
status = store.embedding_status()
assert status["missing_or_stale"] == 0, status

shared_errors = []
stop = threading.Event()

def shared_reader(worker_id):
    try:
        while not stop.is_set():
            store.semantic_search(f"quiet buyer pool schools {worker_id}", limit=8)
    except Exception as exc:
        shared_errors.append((f"reader-{worker_id}", type(exc).__name__, str(exc)))

def shared_writer():
    try:
        for j in range(150):
            store.add_fact(f"Shared live write {j}: buyer wants calm street and strong schools.", category="lead")
            if j % 30 == 0:
                store.backfill_embeddings(limit=20)
    except Exception as exc:
        shared_errors.append(("writer", type(exc).__name__, str(exc)))
    finally:
        stop.set()

readers = [threading.Thread(target=shared_reader, args=(i,)) for i in range(8)]
for thread in readers:
    thread.start()
writer_thread = threading.Thread(target=shared_writer)
writer_thread.start()
writer_thread.join()
stop.set()
for thread in readers:
    thread.join()
assert not shared_errors, shared_errors

status = store.embedding_status()
assert status["missing_or_stale"] == 0, status
store.close()

print(
    "Memory stress harness passed: "
    f"facts={status['facts']} indexed={status['indexed_facts']} "
    f"insert_s={insert_s:.2f} avg_search_ms={(search_s / len(queries)) * 1000:.2f}"
)
PY
    )
}

run_context_efficiency() {
    (
        cd "$CLI_DIR"
        .venv/bin/python scripts/elevate_context_efficiency.py
    )
}

run_context_stress() {
    (
        cd "$CLI_DIR"
        .venv/bin/python scripts/elevate_context_efficiency.py --stress
    )
}

run_adversarial() {
    (
        cd "$CLI_DIR"
        .venv/bin/python scripts/elevate_context_efficiency.py --adversarial
    )
}

main() {
    local cmd="${1:-}"
    case "$cmd" in
        audit) run_audit ;;
        smoke) run_smoke ;;
        install) trap cleanup EXIT; run_install ;;
        migration) trap cleanup EXIT; run_migration ;;
        uninstall) trap cleanup EXIT; run_uninstall ;;
        memory) trap cleanup EXIT; run_memory ;;
        memory-stress) trap cleanup EXIT; run_memory_stress ;;
        memory-openai) trap cleanup EXIT; run_memory_openai ;;
        access) trap cleanup EXIT; run_access ;;
        context-efficiency) run_context_efficiency ;;
        context-stress) run_context_stress ;;
        adversarial) run_adversarial ;;
        all)
            trap cleanup EXIT
            run_audit
            run_smoke
            run_install
            run_migration
            run_uninstall
            run_memory
            run_memory_stress
            run_access
            run_context_efficiency
            run_context_stress
            run_adversarial
            ;;
        -h|--help|help|"") usage ;;
        *) echo "Unknown harness command: $cmd" >&2; usage >&2; return 2 ;;
    esac
}

main "$@"
