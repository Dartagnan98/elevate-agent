"""Regression coverage for recurring Lofty snapshot disk growth."""
import json

import pytest

from elevate_cli.data import connect, record_lifecycle
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data.migrate import BackfillStats, walk_jsonl_source


@pytest.fixture
def crm(tmp_path):
    _reset_schema_cache()
    source = tmp_path / "sources" / "crm"
    source.mkdir(parents=True)
    contacts = [
        {"contact_id": f"lofty-lead:{i}", "display_name": f"Test {i}",
         "emails": f"snapshot{i}@example.com", "channel": "Lofty CRM"}
        for i in (1, 2)
    ]
    (source / "contacts.jsonl").write_text(
        "\n".join(json.dumps(r) for r in contacts) + "\n"
    )
    yield source
    _reset_schema_cache()


def snapshot(**overrides):
    return {"contact_id": "lofty-lead:1", "type": "crm_lead_synced",
            "timestamp": "2026-09-07T01:00:00+00:00",
            "title": "Lofty lead synced", "summary": "Test is in New Lead.",
            **overrides}


def replay(crm, rows):
    (crm / "lead-events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n"
    )
    stats = BackfillStats()
    with connect() as conn:
        walk_jsonl_source(crm, conn=conn, stats=stats)
    assert not stats.errors, stats.errors
    return stats.lifecycle_events


def test_unchanged_snapshot_ignores_poll_timestamp(crm):
    assert replay(crm, [snapshot()]) == 1
    assert replay(crm, [snapshot()]) == 0
    assert replay(crm, [snapshot(timestamp="2026-09-07T02:00:00+00:00")]) == 0
    with connect() as conn:
        rows = conn.execute("SELECT ts FROM events").fetchall()
    assert len(rows) == 1
    assert rows[0]["ts"] == "2026-09-07T01:00:00+00:00"


def test_changed_snapshot_and_other_lead_are_preserved(crm):
    assert replay(crm, [snapshot()]) == 1
    assert replay(crm, [snapshot(summary="Test is in Client.")]) == 1
    assert replay(crm, [snapshot(contact_id="lofty-lead:2")]) == 1
    assert replay(crm, [snapshot(summary="Test is in Client.")]) == 0


def test_pre_fix_random_hash_history_is_recognized(crm):
    replay(crm, [])
    payload = {"legacyType": "crm_lead_synced", "title": "Lofty lead synced",
               "summary": "Test is in New Lead.", "body": None}
    with connect() as conn:
        contact = conn.execute("SELECT id FROM contacts WHERE display_name=?", ("Test 1",)).fetchone()
        old = record_lifecycle(conn, contact_id=contact["id"], kind="lifecycle_change",
                               actor="legacy_backfill", source_id="crm", payload=payload,
                               ts="2026-09-06T00:00:00+00:00")
    assert replay(crm, [snapshot()]) == 0
    with connect() as conn:
        rows = conn.execute("SELECT id FROM events").fetchall()
    assert [r["id"] for r in rows] == [old["id"]]


def test_notes_and_live_actions_keep_occurrence_semantics(crm):
    assert replay(crm, [snapshot(type="crm_note", body="Call tomorrow")]) == 1
    assert replay(crm, [snapshot(type="crm_note", body="Call tomorrow",
                                 timestamp="2026-09-07T02:00:00+00:00")]) == 1
    with connect() as conn:
        contact = conn.execute("SELECT id FROM contacts LIMIT 1").fetchone()["id"]
        for _ in range(2):
            record_lifecycle(conn, contact_id=contact, kind="parked", actor="human",
                             ts="2026-09-07T02:00:00+00:00", payload={"reason": "later"})
        assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='parked'").fetchone()[0] == 2


def test_unique_index_protects_when_prechecks_miss(crm):
    """Simulate another importer committing after our duplicate prechecks."""
    assert replay(crm, [snapshot()]) == 1

    class EmptyResult:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class StalePrechecks:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            if (sql.startswith("SELECT id FROM events WHERE event_hash=")
                    or sql.startswith("SELECT payload_json, payload_ref FROM events ")):
                return EmptyResult()
            return self.conn.execute(sql, params)

    stats = BackfillStats()
    with connect() as conn:
        walk_jsonl_source(crm, conn=StalePrechecks(conn), stats=stats)
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert stats.errors == []
    assert stats.lifecycle_events == 0
