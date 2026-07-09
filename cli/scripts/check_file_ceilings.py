#!/usr/bin/env python3
"""D1 — freeze the known mega-files at a line ceiling so they can't keep growing.

The audit flagged a cluster of 10–15k-line files as a bus-factor / merge-pain
cliff. Decomposition is a continuous effort; this guard stops the cliff from
getting *worse*. A file that must legitimately grow bumps its ceiling here in
the same PR, so the decision is visible in the diff. Wired into CI.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root

# Frozen ceilings (2026-07). Do NOT raise casually — extract a cohesive module
# instead. Raising one should come with the reason in the PR description.
CEILINGS = {
    "cli/run_agent.py": 15030,
    "cli/gateway/run.py": 14965,
    "cli/cli.py": 11255,
    "cli/elevate_cli/main.py": 10295,
    "cli/tui_gateway/server.py": 7760,
    "cli/web/src/pages/ChatPage.tsx": 11965,
}


def main() -> int:
    failed = False
    for rel, ceiling in CEILINGS.items():
        path = ROOT / rel
        if not path.exists():
            print(f"[skip] {rel}: not found")
            continue
        with path.open(encoding="utf-8", errors="ignore") as fh:
            n = sum(1 for _ in fh)
        over = n > ceiling
        print(f"[{'OVER' if over else 'ok'}] {rel}: {n} / {ceiling}")
        failed = failed or over
    if failed:
        print(
            "\nA mega-file grew past its frozen ceiling. Extract the new code into "
            "a cohesive module (see the plan's D1) instead of growing the file — or, "
            "if the growth is genuinely justified, bump the ceiling in "
            "scripts/check_file_ceilings.py in this same change."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
