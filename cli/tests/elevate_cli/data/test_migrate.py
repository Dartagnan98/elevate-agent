"""Tests for ``elevate migrate-data`` — Sprint 1E backfill.

What the migrator must guarantee:

1. **Backup first.** A real run snapshots the operational DB to
   ``backups_root()`` before any writes.
2. **Idempotency.** Re-running the same migrate-data against an
   unchanged source produces zero new rows. Operators rely on this so
   they can re-run safely after a transient failure.
3. **Dry-run.** ``--dry-run`` walks sources and updates the stats but
   does not commit.
4. **Channel coercion.** Legacy free-form ``channel`` strings (``Lofty
   CRM``, ``apple-messages``) get mapped onto the V1 frozen enum.
5. **Lifecycle replay.** ``lead-events.jsonl`` rows become
   ``lifecycle_change`` events.
6. **Templates replay.** Legacy outreach.db ``status='active'`` →
   proposed-then-approved live template; non-active rows stay
   proposed.
7. **Rollback.** ``restore_from_backup`` swaps the operational DB
   file back to a backup snapshot.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from elevate_cli.data import connect
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data.migrate import (
    backup_operational_db,
    restore_from_backup,
    run_backfill,
    walk_jsonl_source,
)
from elevate_cli.data.paths import backups_root, operational_db_path


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r))
            fh.write("\n")


def _build_legacy_outreach_db(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE templates (
            id TEXT PRIMARY KEY, lane TEXT, name TEXT, body TEXT,
            channel TEXT DEFAULT 'any',
            active INTEGER DEFAULT 1,
            uses INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT,
            status TEXT DEFAULT 'active',
            rationale TEXT
        )
        """
    )
    for r in rows:
        conn.execute(
            "INSERT INTO templates(id,lane,name,body,channel,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                r["id"], r["lane"], r["name"], r["body"],
                r.get("channel", "any"),
                r.get("status", "active"),
                "2026-05-05T00:00:00+00:00",
                "2026-05-05T00:00:00+00:00",
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def legacy_layout(tmp_path: Path) -> dict[str, Path]:
    """Build a small CRM source dir + outreach.db with deterministic
    rows. Two contacts, one conversation, three messages, one
    lead-event, two templates."""
    sources = tmp_path / "sources"
    crm = sources / "crm"

    _write_jsonl(crm / "contacts.jsonl", [
        {
            "source_id": "crm",
            "contact_id": "lofty-lead:1001",
            "display_name": "Alex Buyer",
            "channel": "Lofty CRM",
            "emails": "alex@example.com",
            "phones": "+15555550111",
        },
        {
            "source_id": "crm",
            "contact_id": "lofty-lead:1002",
            "display_name": "Jordan Seller",
            "channel": "Lofty CRM",
            "emails": ["jordan@example.com", "jordan.alt@example.com"],
            "phones": "5555550112",
        },
    ])
    _write_jsonl(crm / "conversations.jsonl", [
        {
            "source_id": "crm",
            "conversation_id": "lofty-thread:T-1",
            "contact_id": "lofty-lead:1001",
            "channel": "Lofty CRM",
            "first_message_at": "2026-05-01T10:00:00+00:00",
            "last_message_at": "2026-05-04T14:42:09+00:00",
        },
    ])
    _write_jsonl(crm / "messages.jsonl", [
        {
            "source_id": "crm",
            "conversation_id": "lofty-thread:T-1",
            "contact_id": "lofty-lead:1001",
            "channel": "Lofty CRM",
            "direction": "inbound",
            "timestamp": "2026-05-01T10:00:00+00:00",
            "text": "Hi, looking for a 3 bed in Vernon",
        },
        {
            "source_id": "crm",
            "conversation_id": "lofty-thread:T-1",
            "contact_id": "lofty-lead:1001",
            "channel": "Lofty CRM",
            "direction": "outbound",
            "timestamp": "2026-05-01T10:30:00+00:00",
            "text": "Got it — I'll send a few options.",
        },
        # Orphan message — references a thread we never declared.
        # Migrator should lazy-create the conversation row.
        {
            "source_id": "crm",
            "conversation_id": "lofty-thread:T-2",
            "contact_id": "lofty-lead:1002",
            "channel": "Lofty CRM",
            "direction": "inbound",
            "timestamp": "2026-05-02T09:00:00+00:00",
            "text": "Are you taking on new sellers?",
        },
    ])
    _write_jsonl(crm / "lead-events.jsonl", [
        {
            "source_id": "crm",
            "contact_id": "lofty-lead:1001",
            "type": "crm_lead_synced",
            "title": "Lofty lead synced",
            "summary": "Synced from Lofty",
            "timestamp": "2026-05-01T09:00:00+00:00",
        },
    ])

    outreach_db = tmp_path / "outreach.db"
    _build_legacy_outreach_db(outreach_db, [
        {"id": "tpl-1", "lane": "new-outreach", "name": "Cold opener v1",
         "body": "Hi {name}, saw you were looking in {area}.", "status": "active"},
        {"id": "tpl-2", "lane": "follow-ups", "name": "Bump 1",
         "body": "Following up on the listings.", "status": "draft"},
    ])

    return {"sources": sources, "outreach": outreach_db}


# ─── Backup / restore ─────────────────────────────────────────────────


def test_backup_no_op_when_db_missing():
    """Fresh install — operational.db doesn't exist yet. Backup must
    not crash; it returns a placeholder path that doesn't exist on
    disk so the orchestrator can log "no backup needed"."""
    op_path = operational_db_path()
    if op_path.exists():
        op_path.unlink()
    _reset_schema_cache()
    backup = backup_operational_db()
    assert not backup.exists()
    assert backup.parent == backups_root()


def test_backup_then_restore_roundtrip():
    # Cause the schema to materialize.
    with connect() as conn:
        conn.execute("INSERT INTO meta(key,value) VALUES ('test_marker','before')")

    backup = backup_operational_db()
    assert backup.exists(), "backup file should exist after running backup"

    # Mutate the live DB.
    _reset_schema_cache()
    with connect() as conn:
        conn.execute(
            "UPDATE meta SET value='after' WHERE key='test_marker'"
        )

    with connect() as conn:
        assert conn.execute(
            "SELECT value FROM meta WHERE key='test_marker'"
        ).fetchone()["value"] == "after"

    restore_from_backup(backup)

    with connect() as conn:
        assert conn.execute(
            "SELECT value FROM meta WHERE key='test_marker'"
        ).fetchone()["value"] == "before"


# ─── Backfill behavior ────────────────────────────────────────────────


def test_dry_run_does_not_write(legacy_layout):
    stats = run_backfill(
        sources_root=legacy_layout["sources"],
        outreach_db=legacy_layout["outreach"],
        dry_run=True,
    )
    assert stats.dry_run is True
    assert stats.contacts == 2
    assert stats.conversations == 1
    assert stats.messages == 3
    assert stats.templates == 2

    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0


def test_full_run_writes_expected_rows(legacy_layout):
    stats = run_backfill(
        sources_root=legacy_layout["sources"],
        outreach_db=legacy_layout["outreach"],
    )
    assert stats.errors == [], f"backfill errors: {stats.errors}"
    assert stats.dry_run is False
    assert stats.contacts == 2
    # 1 declared in conversations.jsonl + 1 lazy-created from the
    # orphan T-2 message = 2.
    assert stats.conversations == 2
    assert stats.messages == 3
    assert stats.lifecycle_events == 1
    assert stats.templates == 2
    # 1 active → live, 1 draft → proposed.
    with connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM templates WHERE status='live'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM templates WHERE status='proposed'"
        ).fetchone()[0] == 1
        # All conversations land on the frozen `crm` channel since
        # legacy "Lofty CRM" maps there.
        chans = {
            row["channel"]
            for row in conn.execute("SELECT channel FROM conversations").fetchall()
        }
        assert chans == {"crm"}
        # Each contact has at least one identity.
        ident_counts = conn.execute(
            "SELECT contact_id, COUNT(*) AS n FROM identities GROUP BY contact_id"
        ).fetchall()
        assert all(r["n"] >= 1 for r in ident_counts)


def test_idempotent_rerun_writes_zero_new_rows(legacy_layout):
    run_backfill(
        sources_root=legacy_layout["sources"],
        outreach_db=legacy_layout["outreach"],
    )
    second = run_backfill(
        sources_root=legacy_layout["sources"],
        outreach_db=legacy_layout["outreach"],
    )
    assert second.contacts == 0
    assert second.contacts_skipped == 2
    # Lazy-created conversation from T-2 means second run sees both as
    # already-present.
    assert second.conversations == 0
    assert second.conversations_skipped == 1  # only the declared one
    assert second.messages == 0
    assert second.messages_skipped == 3
    assert second.templates == 0
    assert second.templates_skipped == 2
    # Lifecycle events go through event_hash UNIQUE so they're silent
    # idempotent — count is unchanged from second invocation.
    with connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind='lifecycle_change'"
        ).fetchone()[0] == 1


def test_only_sources_filters_jsonl_walk(legacy_layout, tmp_path):
    other = legacy_layout["sources"] / "apple-messages"
    _write_jsonl(other / "contacts.jsonl", [
        {"source_id": "apple-messages",
         "contact_id": "apple-handle:+17787777777",
         "display_name": "+17787777777",
         "channel": "apple-messages"},
    ])

    stats = run_backfill(
        sources_root=legacy_layout["sources"],
        outreach_db=legacy_layout["outreach"],
        only_sources=["crm"],
    )
    # The new apple-messages dir was on disk but not walked.
    assert stats.sources_walked == ["crm"]
    assert stats.contacts == 2

    with connect() as conn:
        # The skipped source's contact must not exist.
        miss = conn.execute(
            "SELECT id FROM contacts WHERE source_key=?",
            ("apple-messages:apple-handle:+17787777777",),
        ).fetchone()
        assert miss is None


def test_no_backup_flag_skips_backup(legacy_layout):
    # Materialize the DB so backup *would* write a file otherwise.
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('marker','x')")

    before = {p.name for p in backups_root().glob("migrate-data-*.db")}
    stats = run_backfill(
        sources_root=legacy_layout["sources"],
        outreach_db=legacy_layout["outreach"],
        skip_backup=True,
    )
    after = {p.name for p in backups_root().glob("migrate-data-*.db")}
    assert before == after, "no-backup run still produced a backup file"
    assert stats.backup_path is None


def test_walk_jsonl_source_directly(legacy_layout):
    """Directly invoke ``walk_jsonl_source`` to confirm the helper
    doesn't rely on the orchestrator's connection management."""
    from elevate_cli.data.migrate import BackfillStats

    stats = BackfillStats()
    with connect() as conn:
        walk_jsonl_source(
            legacy_layout["sources"] / "crm",
            conn=conn, stats=stats,
        )
    assert "crm" in stats.sources_walked
    assert stats.contacts == 2
    assert stats.messages == 3
