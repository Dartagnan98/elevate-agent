"""CLI surface for the central data module.

Currently houses:

* ``elevate parity-report`` — print shadow-read parity stats and recent
  diffs. Used to gate the Sprint 2 cutover (3-day clean window before
  flipping reads off the legacy JSONL path).
* ``elevate migrate-data`` — Sprint 1E backfill runner. Replays legacy
  JSONL sources + the outreach.db ``templates`` table into the central
  operational store. Always backs up first; supports dry-run and
  rollback.
* ``elevate review-contacts`` — run the AI heat-scoring sweep across
  ``contacts``, populating heat_label / heat_score / needs_follow_up /
  buyer_search_active / listing_active. Idempotent; safe to re-run.

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
    review_all_contacts,
    score_contact,
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
    return data_root().parent / "tmp" / "client-tools" / "data" / "sources"


def _default_outreach_db() -> Path:
    override = os.environ.get("ELEVATE_LEGACY_OUTREACH_DB")
    if override:
        return Path(override)
    return data_root().parent / "tmp" / "client-tools" / "data" / "outreach" / "outreach.db"


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


# ─── elevate review-contacts ────────────────────────────────────────────


def cmd_review_contacts(args: argparse.Namespace) -> int:
    """Run the AI heat-scoring sweep against the operational DB."""
    if args.contact_id:
        with connect() as conn:
            try:
                result = score_contact(
                    conn,
                    args.contact_id,
                    actor=args.actor,
                    write=not args.dry_run,
                )
            except LookupError as exc:
                print(f"score-contact failed: {exc}", file=sys.stderr)
                return 2
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        else:
            print(f"contact_id  : {result['contact_id']}")
            if result.get("skipped"):
                print(f"skipped     : {result['skipped']}")
            else:
                print(f"heat_label  : {result['heat_label']}")
                print(f"heat_score  : {result['heat_score']}")
                print(f"heat_reason : {result['heat_reason']}")
                print(f"needs_follow_up    : {result['needs_follow_up']}")
                print(f"buyer_search_active: {result['buyer_search_active']}")
                print(f"listing_active     : {result['listing_active']}")
                print(f"wrote       : {result['wrote']}")
        return 0

    with connect() as conn:
        summary = review_all_contacts(
            conn,
            actor=args.actor,
            limit=args.limit,
            write=not args.dry_run,
        )

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return 0

    print(f"review-contacts run_id={summary['run_id']} version={summary['scoring_version']}")
    print(f"  scanned : {summary['scanned']}")
    print(f"  wrote   : {summary['wrote']}{'  (dry-run)' if args.dry_run else ''}")
    print(f"  skipped : {summary['skipped']} (closed contacts)")
    print(f"  hot     : {summary['by_label']['hot']}")
    print(f"  warm    : {summary['by_label']['warm']}")
    print(f"  watch   : {summary['by_label']['watch']}")
    print(f"  normal  : {summary['by_label']['normal']}")
    print(f"  needs_follow_up    : {summary['needs_follow_up']}")
    print(f"  buyer_search_active: {summary['buyer_search_active']}")
    print(f"  listing_active     : {summary['listing_active']}")
    errs = summary.get("errors") or []
    if errs:
        print(f"  errors  : {len(errs)} (first 5 shown)")
        for e in errs[:5]:
            print(f"    - {e}")
        return 1
    return 0


def add_review_contacts_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review-contacts",
        help="Run the AI heat-scoring sweep against contacts",
        description=(
            "Score every non-closed contact and write back heat_label, "
            "heat_score, heat_reason, needs_follow_up, next_follow_up_at, "
            "buyer_search_active, listing_active. Idempotent. Pulls "
            "CRM-native scores (pcs_buyers / lead_signals payload) as a "
            "floor, then adds event-derived signals on top."
        ),
    )
    parser.add_argument(
        "--contact-id", default=None,
        help="Score a single contact instead of the whole sweep",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute scores without writing flag changes back to contacts",
    )
    parser.add_argument(
        "--actor", default="cli:review-contacts",
        help="Actor string for the lifecycle_change events (default cli:review-contacts)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap the number of contacts scanned (debug/smoke use)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable output",
    )
    parser.set_defaults(func=lambda a: sys.exit(cmd_review_contacts(a)))


# ─── elevate sync ──────────────────────────────────────────────────────
#
# Provider-agnostic dispatch over every connected source. Same flow for
# Lofty, Follow Up Boss, Sierra, Brivity, apple-messages, social, gmail —
# anything registered in source_connectors.scaffold_source. The CLI
# never names the provider; the connector reads it from
# ``integrations.crm.provider`` in the config and routes itself.


_KNOWN_SOURCE_IDS = ("apple-messages", "crm", "social", "gmail")


def _load_connector_config() -> dict[str, Any]:
    from elevate_cli.source_connectors import load_config
    return load_config()


def cmd_sync(args: argparse.Namespace) -> int:
    """Run a connector sync. ``--all`` walks every known source.

    Provider-agnostic — the CRM connector picks its adapter from the
    configured provider, so this command name never changes across
    Lofty / FUB / Sierra / Brivity / BoldTrail workspaces.
    """
    from elevate_cli.source_connectors import scaffold_source

    if args.all:
        targets = list(_KNOWN_SOURCE_IDS)
    elif args.source:
        targets = [s.strip() for s in args.source.split(",") if s.strip()]
    else:
        print(
            "elevate sync: pass a source id (e.g. crm, apple-messages, social) or --all",
            file=sys.stderr,
        )
        return 2

    config = _load_connector_config()
    results: dict[str, Any] = {}
    failed: list[str] = []
    for source_id in targets:
        try:
            # 'social' and 'gmail' are Composio-backed inbound channels — the
            # live pull happens through composio_inbound.pull_all_supported,
            # not the scaffolder (which only writes setup files). Route them
            # directly so the CLI surface matches what the cron does.
            if source_id in ("social", "gmail"):
                from elevate_cli import composio_inbound as _ci
                view = _ci.pull_all_supported()
            else:
                view = scaffold_source(source_id, config)
            results[source_id] = {"ok": True, "view": view}
            if not args.json:
                state = (view or {}).get("state") or "unknown"
                counts = (view or {}).get("counts") or {}
                count_summary = " ".join(
                    f"{k}={v}" for k, v in counts.items() if v not in (None, 0)
                ) or "(no rows)"
                print(f"[{source_id}] state={state} {count_summary}")
        except Exception as exc:
            failed.append(source_id)
            results[source_id] = {"ok": False, "error": str(exc)}
            if not args.json:
                print(f"[{source_id}] FAILED: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True, default=str))

    return 0 if not failed else 1


def add_sync_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "sync",
        help="Run a connector sync (provider-agnostic)",
        description=(
            "Drive any connected source's sync from the CLI. The CRM "
            "connector picks its adapter from the configured provider — "
            "no Lofty-specific command. Identity-first writethrough in "
            "data/migrate.py ensures the same person collapses to one "
            "contact_id across every source."
        ),
    )
    parser.add_argument(
        "source", nargs="?", default=None,
        help="Source id: apple-messages, crm, social, gmail (comma-separated for several)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help=f"Run every known source in order: {', '.join(_KNOWN_SOURCE_IDS)}",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable output",
    )
    parser.set_defaults(func=lambda a: sys.exit(cmd_sync(a)))


# ─── elevate review-unmatched ──────────────────────────────────────────
#
# Surface contacts that exist on a message channel (apple-messages,
# whatsapp, gmail, instagram, etc.) but are NOT yet in any CRM —
# candidates the operator should review and either add to the CRM or
# park as not-a-lead. CRM-agnostic: filters out anyone with a
# lofty_id / fub_id / sierra_id / brivity_id / boldtrail_id identity.


_CRM_IDENTITY_KINDS = (
    "lofty_id", "fub_id", "sierra_id", "brivity_id", "boldtrail_id",
)
_MESSAGE_IDENTITY_KINDS = (
    "apple_handle", "wa_id",
    "instagram_id", "instagram_handle", "facebook_id", "telegram_id",
    # generic phone/email count too — gmail contacts and SMS-only people
    "phone", "email",
)


def cmd_review_unmatched(args: argparse.Namespace) -> int:
    """List contacts who have a message-channel identity but no CRM id.

    These are the "potential leads" — people the operator has a thread
    with on iMessage / WhatsApp / Gmail / Instagram, but who aren't in
    the CRM yet. After review, the operator can push them into the
    configured CRM via the CRM adapter (task #29) or park as noise.
    """
    min_outbound = max(0, int(getattr(args, "min_outbound", 0)))
    min_inbound = max(0, int(getattr(args, "min_inbound", 1)))
    limit = max(1, int(getattr(args, "limit", 100)))

    crm_kinds_csv = ",".join(f"'{k}'" for k in _CRM_IDENTITY_KINDS)
    msg_kinds_csv = ",".join(f"'{k}'" for k in _MESSAGE_IDENTITY_KINDS)

    sql = f"""
        WITH
        crm_contacts AS (
            SELECT DISTINCT contact_id FROM identities
            WHERE kind IN ({crm_kinds_csv})
        ),
        msg_contacts AS (
            SELECT DISTINCT contact_id FROM identities
            WHERE kind IN ({msg_kinds_csv})
        ),
        thread_totals AS (
            SELECT
                contact_id,
                COALESCE(SUM(inbound_count), 0)  AS inbound,
                COALESCE(SUM(outbound_count), 0) AS outbound,
                MAX(COALESCE(last_inbound_at, last_outbound_at)) AS last_activity
            FROM conversations
            GROUP BY contact_id
        )
        SELECT
            c.id, c.display_name, c.primary_phone, c.primary_email,
            c.last_activity_at,
            COALESCE(t.inbound, 0)  AS inbound,
            COALESCE(t.outbound, 0) AS outbound,
            t.last_activity AS last_thread_activity
        FROM contacts c
        JOIN msg_contacts m  ON m.contact_id = c.id
        LEFT JOIN crm_contacts cc ON cc.contact_id = c.id
        LEFT JOIN thread_totals t ON t.contact_id = c.id
        WHERE cc.contact_id IS NULL
          AND COALESCE(t.inbound, 0)  >= ?
          AND COALESCE(t.outbound, 0) >= ?
        ORDER BY COALESCE(t.last_activity, c.last_activity_at) DESC NULLS LAST
        LIMIT ?
    """

    with connect() as conn:
        try:
            rows = conn.execute(sql, (min_inbound, min_outbound, limit)).fetchall()
        except Exception:
            # SQLite older than 3.30 doesn't grok NULLS LAST; retry without.
            sql2 = sql.replace("DESC NULLS LAST", "DESC")
            rows = conn.execute(sql2, (min_inbound, min_outbound, limit)).fetchall()

    out_rows = [
        {
            "contactId": r["id"],
            "displayName": r["display_name"],
            "primaryPhone": r["primary_phone"],
            "primaryEmail": r["primary_email"],
            "inbound": r["inbound"],
            "outbound": r["outbound"],
            "lastActivityAt": r["last_thread_activity"] or r["last_activity_at"],
        }
        for r in rows
    ]

    if args.json:
        print(json.dumps({"count": len(out_rows), "contacts": out_rows},
                         indent=2, sort_keys=True, default=str))
        return 0

    if not out_rows:
        print("No unmatched contacts above thresholds.")
        return 0

    print(f"{len(out_rows)} potential lead(s) — in messages but not in any CRM:")
    print()
    print(f"  {'NAME':30}  {'PHONE/EMAIL':30}  IN/OUT   LAST ACTIVITY")
    print("  " + "-" * 90)
    for row in out_rows:
        handle = row["primaryPhone"] or row["primaryEmail"] or ""
        name = (row["displayName"] or "")[:30]
        last = (row["lastActivityAt"] or "")[:19]
        print(
            f"  {name:30}  {handle:30}  "
            f"{row['inbound']:>3}/{row['outbound']:<3}  {last}"
        )
    print()
    print("Push promising ones into the CRM, park noise as not-a-lead.")
    return 0


def add_review_unmatched_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "review-unmatched",
        help="List message-channel contacts not yet in any CRM",
        description=(
            "Show contacts who have a message-channel identity "
            "(apple-messages, WhatsApp, Gmail, Instagram, raw phone/email) "
            "but no CRM identity. CRM-agnostic — filters out anyone with "
            "a lofty_id / fub_id / sierra_id / brivity_id / boldtrail_id. "
            "Use to surface potential leads after a sync run."
        ),
    )
    parser.add_argument(
        "--min-inbound", type=int, default=1,
        help="Minimum inbound message count to qualify (default 1)",
    )
    parser.add_argument(
        "--min-outbound", type=int, default=0,
        help="Minimum outbound message count to qualify (default 0)",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Cap rows returned (default 100)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable output",
    )
    parser.set_defaults(func=lambda a: sys.exit(cmd_review_unmatched(a)))


def cmd_apple_contacts(args: argparse.Namespace) -> int:
    """elevate apple-contacts resolve [--apply]

    Retrofit identity rows (apple_handle, phone, email, apple_addressbook_id,
    apple_chat_id) onto legacy apple-messages contacts so cross-source
    matching (Lofty <-> apple) works. Enrichment-only — never merges,
    never deletes, never overwrites human-readable names. Phone collisions
    with existing CRM contacts are logged to identity_conflicts for
    operator review (no auto-merge).

    Default is dry-run; pass --apply to commit.
    """
    from elevate_cli.apple_contacts_backfill import render, run

    sub = getattr(args, "apple_contacts_cmd", None)
    if sub != "resolve":
        print("usage: elevate apple-contacts resolve [--apply]")
        return 2

    stats = run(apply=bool(getattr(args, "apply", False)))
    print(render(stats, applied=bool(getattr(args, "apply", False))))
    return 0 if not stats.errors else 1


def add_apple_contacts_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "apple-contacts",
        help="Enrich apple-messages contacts with identity rows",
        description=(
            "Retrofit identities (apple_handle, phone, email, "
            "apple_addressbook_id, apple_chat_id) onto legacy "
            "apple-messages contacts. Enrichment-only — never merges, "
            "never deletes, never clobbers curated display names."
        ),
    )
    sub = parser.add_subparsers(dest="apple_contacts_cmd")
    resolve = sub.add_parser(
        "resolve",
        help="Walk apple-messages contacts and backfill identity rows",
    )
    resolve.add_argument(
        "--apply", action="store_true",
        help="Commit changes. Default is dry-run.",
    )
    parser.set_defaults(func=lambda a: sys.exit(cmd_apple_contacts(a)))


# ─── elevate scheduler ─────────────────────────────────────────────────
#
# Manage the recurring connector-sync launchd jobs that ``elevate db init``
# installs automatically. Idempotent — useful for inspection, manual
# refresh after a CLI upgrade, or tear-down before uninstall.


def cmd_scheduler(args: argparse.Namespace) -> int:
    from elevate_cli import sync_scheduler as ss

    action = getattr(args, "scheduler_action", None) or "status"

    if action == "status":
        rows = ss.status()
        if getattr(args, "json", False):
            print(json.dumps(rows, indent=2, sort_keys=True, default=str))
        else:
            ss.print_status(rows)
        return 0

    if action == "install":
        results = ss.install_all(force=getattr(args, "force", False))
        rc = ss.print_results(results)
        return rc

    if action == "uninstall":
        results = ss.uninstall_all()
        rc = ss.print_results(results)
        return rc

    if action == "run":
        # Fire each registered source synchronously — useful as a manual
        # "setup cron" trigger right after install, or after a long offline
        # gap when you want the DB hot before the next launchd tick.
        source_filter = getattr(args, "source", None)
        targets = [j for j in ss.jobs() if (source_filter is None or j.source_id == source_filter)]
        if not targets:
            print(f"No matching sync job for source={source_filter!r}", file=sys.stderr)
            return 2
        from elevate_cli.source_connectors import scaffold_source
        config = _load_connector_config()
        rc = 0
        for job in targets:
            sid = job.source_id
            try:
                if sid in ("social", "gmail"):
                    from elevate_cli import composio_inbound as _ci
                    view = _ci.pull_all_supported()
                else:
                    view = scaffold_source(sid, config)
                state = (view or {}).get("state") or "unknown"
                counts = (view or {}).get("counts") or {}
                count_summary = " ".join(f"{k}={v}" for k, v in counts.items() if v not in (None, 0)) or "(no rows)"
                print(f"[{sid}] state={state} {count_summary}")
            except Exception as exc:
                print(f"[{sid}] FAILED: {exc}", file=sys.stderr)
                rc = 1
        return rc

    print(f"Unknown scheduler action: {action}", file=sys.stderr)
    return 2


def add_scheduler_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "scheduler",
        help="Manage recurring connector-sync jobs (launchd)",
        description=(
            "Install / inspect / remove the launchd plists that drive "
            "recurring `elevate sync <source>` runs. `elevate db init` "
            "calls `install` automatically so a fresh download just works."
        ),
    )
    sub = parser.add_subparsers(dest="scheduler_action")

    status = sub.add_parser("status", help="Show installed / loaded state for each sync job")
    status.add_argument("--json", action="store_true")

    install = sub.add_parser("install", help="Install / refresh all sync plists (idempotent)")
    install.add_argument("--force", action="store_true", help="Rewrite plists even if byte-identical")

    sub.add_parser("uninstall", help="Bootout and remove all sync plists")

    run = sub.add_parser("run", help="Run the registered sync jobs immediately (one-shot)")
    run.add_argument("--source", default=None, help="Only fire one source (apple-messages, crm, social)")

    parser.set_defaults(func=lambda a: sys.exit(cmd_scheduler(a)))
