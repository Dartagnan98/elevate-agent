"""Debug route inventory drift guard.

The desktop debugging epic is the production-readiness ledger for route
coverage. If the route surface changes, the ledger must move with it.
"""

from __future__ import annotations

import re
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
EPIC_PATH = REPO_ROOT / "cli/docs/epic-desktop-debugging-routes-2026-06-18.md"
INVENTORY_PATH = REPO_ROOT / "cli/docs/desktop-debug-route-inventory.tsv"
GENERATOR_PATH = REPO_ROOT / "cli/scripts/generate_debug_route_inventory.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location("generate_debug_route_inventory", GENERATOR_PATH)
assert GENERATOR_SPEC is not None
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
assert GENERATOR_SPEC.loader is not None
sys.modules[GENERATOR_SPEC.name] = GENERATOR
GENERATOR_SPEC.loader.exec_module(GENERATOR)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _inventory_rows():
    return GENERATOR.generate_rows(REPO_ROOT)


def _local_route_fingerprint() -> str:
    entries = [
        f"{row.surface}:{row.kind}:{row.method}:{row.path}:{row.file}:{row.line}"
        for row in _inventory_rows()
        if row.surface in {"local", "local_plugin"}
    ]
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return digest[:16]


def _local_route_count() -> int:
    return sum(1 for row in _inventory_rows() if row.surface in {"local", "local_plugin"})


def _hosted_route_count() -> int:
    return len(list((REPO_ROOT / "backend/src/app/api").rglob("route.ts")))


def _caller_inventory() -> list[str]:
    result = subprocess.run(
        [
            "rg",
            "-n",
            r"fetchJSON|cachedFetchJSON|fetch\(|/api/|new WebSocket|elevateDesktop|openExternal\(",
            "desktop/src",
            "cli/web/src",
            "backend/src/app",
            "--glob",
            "!**/web_dist/**",
            "--glob",
            "!**/node_modules/**",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    return sorted(result.stdout.splitlines())


def _caller_inventory_fingerprint() -> str:
    return hashlib.sha256("\n".join(_caller_inventory()).encode("utf-8")).hexdigest()[:16]


def _hosted_route_files() -> list[str]:
    return [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "backend/src/app/api").rglob("route.ts"))
    ]


def _hosted_route_block(epic: str) -> list[str]:
    match = re.search(
        r"^- Hosted route file inventory:\n(?P<body>(?:  - `[^`]+`\n)+)",
        epic,
        re.MULTILINE,
    )
    assert match is not None, "hosted route file inventory block missing"
    return [line.strip()[3:-1] for line in match.group("body").splitlines()]


def test_desktop_debugging_epic_route_inventory_is_current():
    epic = _read(EPIC_PATH)

    local_count = _local_route_count()
    hosted_count = _hosted_route_count()

    assert f"Local inventory: {local_count} decorated local routes/WebSockets" in epic
    assert f"Local route identity fingerprint: `{_local_route_fingerprint()}`" in epic
    assert f"Hosted inventory: {hosted_count} tracked `backend/src/app/api/**/route.ts` files" in epic
    caller_count = len(_caller_inventory())
    assert f"Caller inventory: the latest sweep found {caller_count} frontend/desktop caller" in epic
    assert f"Caller inventory fingerprint: `{_caller_inventory_fingerprint()}`" in epic


def test_desktop_debug_route_inventory_tsv_is_current():
    rows = _inventory_rows()
    expected = GENERATOR.to_tsv(rows)

    assert _read(INVENTORY_PATH) == expected

    keys = [(row.surface, row.kind, row.method, row.path, row.file, row.line) for row in rows]
    assert len(keys) == len(set(keys))


def test_desktop_debugging_epic_hosted_route_file_list_is_current():
    epic = _read(EPIC_PATH)

    assert _hosted_route_block(epic) == _hosted_route_files()
