#!/usr/bin/env python3
"""Audit that Elevate runtime surfaces are separated from Hermes/RAgent.

This intentionally allows a small number of legacy references:
- Hermes migration bridges in setup/docs.
- Upstream attribution in NOTICE/LICENSE/docs.
- Hermes 3/4 model warnings and tests.
- Historical test issue links and datasets.

Everything else is treated as a separation leak.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
    "web_dist",
}

PATTERNS = {
    "legacy_ragent": re.compile(
        r"\bRAgent\b|\bragent\b|\.ragent\b|ai\.ragent\b|ragent-gateway"
    ),
    "old_nous_elevate": re.compile(r"NousResearch/elevate(?!-megascience)"),
    "hermes_runtime": re.compile(
        r"\.hermes\b|ai\.hermes\b|hermes-agent|Hermes-Agent|"
        r"hermes-(?:cli|telegram|discord|whatsapp|slack|signal|homeassistant|qqbot)",
        re.IGNORECASE,
    ),
}

PATH_PATTERNS = {
    "legacy_path": re.compile(r"(^|/)(?:.*ragent.*|.*hermes.*)(/|$)", re.IGNORECASE),
}


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_excluded(path: Path) -> bool:
    if path.name.startswith(".rename-"):
        return True
    if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in path.parts):
        return True
    return False


def _is_text(path: Path) -> bool:
    try:
        path.read_text(encoding="utf-8")
        return True
    except UnicodeDecodeError:
        return False
    except OSError:
        return False


def _allowed(path: str, line: str, kind: str) -> str | None:
    lower_line = line.lower()

    if "/tests/" in f"/{path}":
        return "test-only legacy naming or upstream regression link"

    if path in {"README.md", "cli/README.md"}:
        if ".hermes" in lower_line or "hermes installs" in lower_line:
            return "documented Hermes-to-Elevate migration path"
        if "hermes-agent" in lower_line or "upstream attribution" in lower_line:
            return "upstream attribution"

    if path == "cli/setup-elevate.sh":
        if "hermes" in lower_line:
            return "intentional Hermes-to-Elevate migration bridge"

    if path == "cli/NOTICE":
        if "hermes-agent" in lower_line or "nousresearch/hermes-agent" in lower_line:
            return "upstream attribution"

    if path in {"cli/LICENSE", "LICENSE"}:
        return "license text"

    if path in {"cli/elevate_cli/model_switch.py", "cli/cli.py"}:
        if "hermes" in lower_line:
            return "warning for actual Hermes 3/4 LLM model families"

    if path == "cli/scripts/sample_and_compress.py":
        if "nousresearch/elevate-megascience" in lower_line:
            return "historical dataset identifier"

    if path == "cli/scripts/elevate-harness.sh":
        if ".hermes" in lower_line or "hermes-" in lower_line:
            return "Hermes migration fixture"

    if path == "cli/scripts/elevate_separation_audit.py":
        if "hermes" in lower_line or "ragent" in lower_line or "nousresearch/elevate" in lower_line:
            return "audit detector definition"

    if path.startswith("cli/datagen-config-examples/"):
        if "wikipedia.org/wiki/hermes" in lower_line:
            return "example browser task about the mythological topic"

    if path == "cli/website/docs/developer-guide/environments.md":
        if "tokenizer_name" in lower_line and "hermes" in lower_line:
            return "example model tokenizer"

    return None


def iter_text_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or _is_excluded(path):
            continue
        if _is_text(path):
            paths.append(path)
    return sorted(paths)


def run(show_allowed: bool = False) -> int:
    blocked: list[tuple[str, int, str, str]] = []
    allowed: list[tuple[str, int, str, str]] = []

    for path in iter_text_files():
        rel = _relative(path)

        for kind, pattern in PATH_PATTERNS.items():
            if pattern.search(rel):
                reason = "test-only legacy path" if "/tests/" in f"/{rel}" else None
                if reason:
                    allowed.append((rel, 0, kind, reason))
                else:
                    blocked.append((rel, 0, kind, "legacy name in file path"))

        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for kind, pattern in PATTERNS.items():
                if not pattern.search(line):
                    continue
                reason = _allowed(rel, line, kind)
                if reason:
                    allowed.append((rel, lineno, kind, reason))
                else:
                    blocked.append((rel, lineno, kind, line.strip()))

    if blocked:
        print("Elevate separation audit FAILED")
        print()
        for rel, lineno, kind, detail in blocked[:80]:
            suffix = f":{lineno}" if lineno else ""
            print(f"  [{kind}] {rel}{suffix}: {detail}")
        if len(blocked) > 80:
            print(f"  ... {len(blocked) - 80} more")
        print()
        print("Only migration, attribution, model-warning, dataset, and test refs are allowed.")
        return 1

    print("Elevate separation audit passed")
    print(f"  Allowed legacy refs: {len(allowed)}")
    if show_allowed and allowed:
        for rel, lineno, kind, reason in allowed:
            suffix = f":{lineno}" if lineno else ""
            print(f"  [{kind}] {rel}{suffix}: {reason}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-allowed",
        action="store_true",
        help="Print allowlisted legacy references too",
    )
    args = parser.parse_args()
    return run(show_allowed=args.show_allowed)


if __name__ == "__main__":
    sys.exit(main())
