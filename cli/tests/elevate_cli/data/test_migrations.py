"""Tests for the operational.db migration runner and 0001_init schema.

The conftest's ``_hermetic_environment`` fixture redirects ``ELEVATE_HOME``
to a per-test tmp dir, so every test here gets a fresh empty database.
We force the connection module to forget any cached "schema is ready"
flag at the start of each test — without that, a previous test's
ELEVATE_HOME would mark the next test's tmp DB as already migrated.
"""

from __future__ import annotations

import sqlite3

import pytest

from elevate_cli.data import migrations
from elevate_cli.data.connection import connect, _reset_schema_cache
from elevate_cli.data.paths import operational_db_path


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _now() -> str:
    return "2026-05-05T00:00:00+00:00"


def test_first_connect_applies_initial_migration():
    with connect() as conn:
        rows = conn.execute(
            "SELECT version, name FROM _schema_migrations "
            "WHERE name LIKE '%.sql' ORDER BY version"
        ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [
            (migration.version, migration.name)
            for migration in migrations.discover()
        ]


def test_expected_tables_exist_after_init():
    with connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    expected = {
        "_schema_migrations",
        "contacts",
        "identities",
        "conversations",
        "events",
        "events_summary",
        "ingest_runs",
        "identity_conflicts",
        "lead_signals",
        "pcs_buyers",
        "templates",
        "draft_attempts",
        "send_queue",
        "thread_meta",
        "lane_config",
        "inbound_seen",
        "data_parity_snapshots",
        "meta",
        "deals",
        "deal_events",
        "admin_action_registry",
        "admin_action_runs",
        "conditional_docs",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_second_connect_is_noop():
    with connect() as conn:
        conn.execute(
            "INSERT INTO contacts(id, type, stage, created_at, updated_at) "
            "VALUES('c1','unclassified','cold',?,?)",
            (_now(), _now()),
        )
    _reset_schema_cache()  # second open re-checks ledger
    with connect() as conn:
        applied = migrations.applied(conn)
        assert list(applied) == [migration.version for migration in migrations.discover()]
        c = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        assert c == 1, "second open dropped data"


def test_drift_detection_raises():
    with connect() as conn:
        conn.execute(
            "UPDATE _schema_migrations SET sha256='deadbeef' WHERE version='0001'"
        )
    _reset_schema_cache()
    with pytest.raises(migrations.MigrationDriftError):
        with connect() as conn:
            pass


def test_events_kind_enum_is_frozen():
    with connect() as conn:
        conn.execute(
            "INSERT INTO contacts(id, type, stage, created_at, updated_at) "
            "VALUES('c1','unclassified','cold',?,?)",
            (_now(), _now()),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO events(id, contact_id, kind, source_id, "
                "actor, event_hash, ts) "
                "VALUES('e1','c1','random_kind','crm','system','h1',?)",
                (_now(),),
            )


def test_event_hash_unique():
    with connect() as conn:
        conn.execute(
            "INSERT INTO contacts(id, type, stage, created_at, updated_at) "
            "VALUES('c1','unclassified','cold',?,?)",
            (_now(), _now()),
        )
        conn.execute(
            "INSERT INTO events(id, contact_id, kind, source_id, "
            "actor, event_hash, ts) "
            "VALUES('e1','c1','inbound','crm','system','h1',?)",
            (_now(),),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO events(id, contact_id, kind, source_id, "
                "actor, event_hash, ts) "
                "VALUES('e2','c1','outbound','crm','system','h1',?)",
                (_now(),),
            )


def test_template_approval_invariant_blocks_unapproved_live():
    with connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO templates(id, lane, name, body, status, "
                "created_at, updated_at) "
                "VALUES('t1','new-outreach','x','hi','live',?,?)",
                (_now(), _now()),
            )


def test_template_proposed_forbids_approved_at():
    with connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO templates(id, lane, name, body, status, "
                "approved_at, approved_by, created_at, updated_at) "
                "VALUES('t2','new-outreach','x','hi','proposed',?,'human',?,?)",
                (_now(), _now(), _now()),
            )


def test_template_live_with_human_approver_succeeds():
    with connect() as conn:
        conn.execute(
            "INSERT INTO templates(id, lane, name, body, status, "
            "approved_at, approved_by, created_at, updated_at) "
            "VALUES('t3','new-outreach','x','hi','live',?,'human',?,?)",
            (_now(), _now(), _now()),
        )
        row = conn.execute(
            "SELECT status, approved_by FROM templates WHERE id='t3'"
        ).fetchone()
        assert row[0] == "live"
        assert row[1] == "human"


def test_contact_delete_cascades_to_events():
    with connect() as conn:
        conn.execute(
            "INSERT INTO contacts(id, type, stage, created_at, updated_at) "
            "VALUES('c1','unclassified','cold',?,?)",
            (_now(), _now()),
        )
        conn.execute(
            "INSERT INTO events(id, contact_id, kind, source_id, "
            "actor, event_hash, ts) "
            "VALUES('e1','c1','inbound','crm','system','h1',?)",
            (_now(),),
        )
        conn.execute("DELETE FROM contacts WHERE id='c1'")
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert n == 0
