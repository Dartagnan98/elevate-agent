"""CLI surface for the central data module.

Currently houses:

* ``elevate parity-report`` — print shadow-read parity stats and recent
  diffs. Used to gate the Sprint 2 cutover (3-day clean window before
  flipping reads off the legacy JSONL path).
* ``elevate migrate-data`` — Sprint 1E backfill runner. Replays legacy
  JSONL sources + the outreach.db ``templates`` table into the central
  operational store. Always backs up first; supports dry-run and
  rollback.

Keeping the CLI surface in one module prevents main.py from sprouting
yet another inline import block.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from elevate_cli.data import (
    connect,
    parity_diff_count,
    parity_total_count,
    recent_diffs,
)
from elevate_cli.data.migrate import (
    BackfillStats,
    restore_from_backup,
    run_backfill,
)
from elevate_cli.data.paths import data_root


def _iso_window_start(days: int) -> str:
    """ISO-8601 timestamp ``days`` ago in UTC. Used as the lower bound
    of the parity window the report inspects."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Normalize to seconds — we don't care about sub-second on a 3-day
    # window, and stripping microseconds keeps the printed range clean.
    return cutoff.replace(microsecond=0).isoformat()


def _format_diff_block(diff: dict[str, Any]) -> str:
    body = json.dumps(diff.get("diff", {}), indent=2, sort_keys=True, default=str)
    args = json.dumps(diff.get("requestArgs", {}), sort_keys=True, default=str)
    return (
        f"  - {diff['capturedAt']}  {diff['endpoint']}\n"
        f"    args: {args}\n"
        f"    diff: {body[:400]}{'...' if len(body) > 400 else ''}"
    )


def cmd_parity_report(args: argparse.Namespace) -> int:
    """Print shadow-read parity stats over the last ``--days`` days
    (default 3 — the Sprint 2 flip gate). Returns exit code 0 when the
    window is clean, 1 when there are unresolved diffs."""
    days = max(1, int(getattr(args, "days", 3)))
    limit = max(1, int(getattr(args, "limit", 20)))
    json_out = bool(getattr(args, "json", False))

    since = _iso_window_start(days)

    with connect() as conn:
        total = parity_total_count(conn, since=since)
        diffs = parity_diff_count(conn, since=since)
        recent = recent_diffs(conn, limit=limit) if diffs else []

    clean = diffs == 0

    if json_out:
        payload = {
            "windowStart": since,
            "windowDays": days,
            "totalSnapshots": total,
            "diffCount": diffs,
            "matchRate": (
                round(1.0 - (diffs / total), 6) if total else None
            ),
            "clean": clean,
            "recentDiffs": recent,
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if clean else 1

    rate = f"{(1.0 - (diffs / total)) * 100:.2f}%" if total else "n/a"
    print(f"Shadow-read parity report — last {days}d (since {since})")
    print(f"  total snapshots : {total}")
    print(f"  diffs           : {diffs}")
    print(f"  match rate      : {rate}")
    if total == 0:
        print(
            "\nNo snapshots recorded. Either ELEVATE_DATA_SHADOW_READ is "
            "off, or no shadow-wired endpoints have been exercised."
        )
        # No snapshots is not "clean" in a meaningful sense — return
        # non-zero so a CI gate keying on this command doesn't
        # accidentally green-light a flip on an unexercised window.
        return 1

    if clean:
        print(
            "\nWindow is clean. Sprint 2 cutover gate satisfied for this "
            "window length — see docs/central-data-model-v1-plan.md "
            "before flipping the reads."
        )
        return 0

    print(f"\nMost recent {min(limit, len(recent))} diffs:")
    for d in recent:
        print(_format_diff_block(d))
    return 1


def add_parity_report_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``parity-report`` subcommand on a CLI subparsers
    object. main.py calls this in its parser-build phase."""
    parser = subparsers.add_parser(
        "parity-report",
        help="Show shadow-read parity stats and recent diffs",
        description=(
            "Inspect recent shadow-mode requests against the operational "
            "database. Exit code 0 when the window is clean (zero diffs), "
            "1 otherwise. Used to gate the Sprint 2 cutover."
        ),
    )
    parser.add_argument(
        "--days", type=int, default=3,
        help="Window length in days (default 3 — the cutover gate)",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Max recent diffs to print",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable output",
    )
    parser.set_defaults(func=lambda a: sys.exit(cmd_parity_report(a)))


# ─── elevate migrate-data ──────────────────────────────────────────────


def _default_sources_root() -> Path:
    """Where the legacy JSONL connectors land their state. The
    ``ELEVATE_LEGACY_SOURCES_ROOT`` env override is mostly here so
    tests don't have to monkey-patch the module."""
    override = os.environ.get("ELEVATE_LEGACY_SOURCES_ROOT")
    if override:
        return Path(override)
    return data_root().parent / "tmp" / "skyleigh-tools" / "data" / "sources"


def _default_outreach_db() -> Path:
    override = os.environ.get("ELEVATE_LEGACY_OUTREACH_DB")
    if override:
        return Path(override)
    return data_root().parent / "tmp" / "skyleigh-tools" / "data" / "outreach" / "outreach.db"


def _print_stats(stats: BackfillStats) -> None:
    print("Migrate-data summary")
    print(f"  dry-run         : {stats.dry_run}")
    if stats.backup_path:
        print(f"  backup          : {stats.backup_path}")
    elif not stats.dry_run:
        print("  backup          : (no source DB existed yet)")
    print(f"  sources walked  : {', '.join(stats.sources_walked) or '(none)'}")
    print(
        f"  contacts        : {stats.contacts} written, "
        f"{stats.contacts_skipped} already present"
    )
    print(
        f"  identities      : {stats.identities} written, "
        f"{stats.identities_skipped} skipped (conflict/empty)"
    )
    print(
        f"  conversations   : {stats.conversations} written, "
        f"{stats.conversations_skipped} already present"
    )
    print(
        f"  messages        : {stats.messages} written, "
        f"{stats.messages_skipped} skipped (dup hash / orphan)"
    )
    print(f"  lifecycle events: {stats.lifecycle_events}")
    print(
        f"  templates       : {stats.templates} written, "
        f"{stats.templates_skipped} already present"
    )
    if stats.errors:
        print(f"\n{len(stats.errors)} error(s):")
        for e in stats.errors[:20]:
            print(f"  - {e}")
        if len(stats.errors) > 20:
            print(f"  (... {len(stats.errors) - 20} more truncated)")


def cmd_migrate_data(args: argparse.Namespace) -> int:
    """Backfill the central operational store from legacy JSONL +
    outreach.db. Returns 0 on success, 1 if any per-row errors were
    captured (the migration itself still committed; the operator
    should triage)."""
    if getattr(args, "rollback", None):
        path = Path(args.rollback)
        try:
            dest = restore_from_backup(path)
        except FileNotFoundError as exc:
            print(f"rollback failed: {exc}", file=sys.stderr)
            return 2
        print(f"Restored {path} → {dest}")
        return 0

    sources_root = Path(args.sources_root) if args.sources_root else _default_sources_root()
    outreach_db = (
        Path(args.outreach_db) if args.outreach_db else _default_outreach_db()
    )
    only_sources: list[str] | None = None
    if args.source:
        only_sources = [s.strip() for s in args.source.split(",") if s.strip()]

    try:
        stats = run_backfill(
            sources_root=sources_root,
            outreach_db=outreach_db,
            only_sources=only_sources,
            dry_run=bool(args.dry_run),
            skip_backup=bool(args.no_backup),
            limit=args.limit,
        )
    except RuntimeError as exc:
        print(f"migrate-data refused to run: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(stats.to_dict(), indent=2, sort_keys=True, default=str))
    else:
        _print_stats(stats)

    return 0 if not stats.errors else 1


def add_migrate_data_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "migrate-data",
        help="Backfill the central operational DB from legacy JSONL/outreach.db",
        description=(
            "Sprint 1E backfill — walks legacy connector JSONL sources "
            "and the legacy outreach.db templates table, replaying rows "
            "through the data module. Always takes a backup first; safe "
            "to re-run (idempotent on source-natural keys + event_hash). "
            "Use --rollback PATH to restore a backup."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Walk sources and count what would be written without committing",
    )
    parser.add_argument(
        "--source", default=None,
        help="Comma-separated list of source ids (e.g. 'crm,apple-messages'). "
             "Use 'outreach' to target the legacy outreach.db.",
    )
    parser.add_argument(
        "--sources-root", default=None,
        help="Override the legacy JSONL sources root (debug/test only)",
    )
    parser.add_argument(
        "--outreach-db", default=None,
        help="Override the legacy outreach.db path (debug/test only)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap rows per JSONL file (use during smoke-tests)",
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="Skip the pre-migration backup. DANGEROUS — only use with --dry-run.",
    )
    parser.add_argument(
        "--rollback", default=None, metavar="PATH",
        help="Restore the operational DB from a backup file and exit",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable output",
    )
    parser.set_defaults(func=lambda a: sys.exit(cmd_migrate_data(a)))
