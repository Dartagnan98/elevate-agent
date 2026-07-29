"""Skyleigh's fork upgrade path: 0035-0039 slot collision + 0040 reconcile.

Her install recorded five CRM migrations of its own at versions 0035-0039.
Mainline reused those version numbers for different files and renumbered her
work to 0041-0044. Without ``_COMPATIBLE_PRIOR_HASHES`` the runner drops her
ledger rows and applies mainline's 0035-0039 on top of her fork schema, which
dies at ``0035_crm_redesign.sql`` (its pipeline_status CHECK has no 'attempted'
slug, which her live rows use).

These tests build a fork-shaped database out of a clean one, then upgrade it.
"""

from __future__ import annotations

import pytest

from elevate_cli.data import migrations
from elevate_cli.data.connection import connect, _reset_schema_cache

FORK_APPLIED_AT = "2026-07-16T00:00:00+00:00"

# version -> (fork filename, fork sha256). Verified by sha256-ing her snapshot
# at skyleigh-fork-snapshot/.../migrations_pg/ and cross-checked against the
# _schema_migrations rows in elevate_op_acct_f956ca5305ff5aaf.
FORK_LEDGER = {
    "0035": ("0035_crm_goals.sql",
             "9c59e596a8c1bc1871802ca91e9bb401c1dfd89c428ed9e9b9b880f24cd156b7"),
    "0036": ("0036_pipeline_stages_expand.sql",
             "b66be7804294839cadad0aa3cb890b3ad886c2703a4feb1642ef3e11cf39fe2d"),
    "0037": ("0037_contact_items.sql",
             "19d23a3f88a672dc2ae4d4b98ef46bace3cdb76f91ff01b3b5da046199e8586d"),
    "0038": ("0038_contacts_recency_segment.sql",
             "d53d22e69a31f1a566c153622a7f0d64780daddc7aee2a7813a807c8edbe2d0c"),
    "0039": ("0039_contact_documents.sql",
             "cb4eefc5d10553eb9a72f9a3c1c679166ad5b18a5eafe0d9910d1ccd0355ceb2"),
}

# The stage list her 0036_pipeline_stages_expand.sql pinned. Note 'attempted',
# which mainline's 0035_crm_redesign.sql does NOT allow (it has
# 'attempted_contact' instead).
FORK_PIPELINE_CHECK = """
ALTER TABLE contacts ADD CONSTRAINT contacts_pipeline_status_check
    CHECK (pipeline_status IS NULL OR pipeline_status IN (
        'new_lead', 'follow_up', 'ghosting', 'dead',
        'closed_seller', 'closed_buyer',
        'attempted', 'prospect', 'client', 'pending_deal',
        'closed', 'referred', 'realtor_contact', 'trash'
    ));
"""

# Everything mainline 0035-0039 adds that her fork never had. Stripping these
# from a clean box is what turns it into a fork-shaped box.
MAINLINE_ONLY_CONTACT_COLUMNS = (
    "tags_json",
    "search_criteria_json",
    "custom_fields_json",
    "documents_json",
    "lists_json",
    "outreach_paused",
)


def _now() -> str:
    return "2026-07-28T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _schema_snapshot(conn) -> tuple:
    cols = conn.execute(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = 'public'"
    ).fetchall()
    idx = conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
    ).fetchall()
    cons = conn.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE connamespace = 'public'::regnamespace"
    ).fetchall()
    return (
        sorted(tuple(r) for r in cols),
        sorted(tuple(r) for r in idx),
        sorted(tuple(r) for r in cons),
    )


def _reconcile_sql() -> str:
    path = next(
        f.path for f in migrations.discover()
        if f.name == "0040_crm_fork_reconcile.sql"
    )
    return path.read_text(encoding="utf-8")


def _make_fork_shaped(conn) -> None:
    """Rewind a clean head-of-mainline database to Skyleigh's fork shape."""
    # 1. Undo the mainline-only schema from 0035-0039.
    conn.executescript(
        "\n".join(
            f"ALTER TABLE contacts DROP COLUMN IF EXISTS {c};"
            for c in MAINLINE_ONLY_CONTACT_COLUMNS
        )
        + """
        ALTER TABLE lead_profile_flags DROP COLUMN IF EXISTS top25;
        ALTER TABLE lead_profile_flags DROP COLUMN IF EXISTS top25_at;
        DROP TABLE IF EXISTS account_goals;
        DROP TABLE IF EXISTS crm_settings;
        ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_pipeline_status_check;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_title_unique
            ON chat_sessions(title) WHERE title IS NOT NULL;
        """
        + FORK_PIPELINE_CHECK
    )

    # 2. Rewrite the ledger: her five rows at 0035-0039, nothing above.
    conn.execute("DELETE FROM _schema_migrations WHERE version >= '0035'")
    for version, (name, sha) in FORK_LEDGER.items():
        conn.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (version, name, sha, FORK_APPLIED_AT),
        )
    conn.commit()


def _seed_attempted_contact(conn, contact_id: str = "sky-attempted") -> None:
    conn.execute(
        "INSERT INTO contacts(id, type, stage, pipeline_status, created_at, updated_at) "
        "VALUES(?, 'unclassified', 'cold', 'attempted', ?, ?)",
        (contact_id, _now(), _now()),
    )
    conn.commit()


# ─── Fork upgrade ──────────────────────────────────────────────────────


def test_fork_shaped_ledger_upgrades_without_applying_mainline_0035_0039():
    with connect() as conn:
        _make_fork_shaped(conn)
        _seed_attempted_contact(conn)

    _reset_schema_cache()
    with connect() as conn:  # this is the upgrade; must not raise
        ledger = migrations.applied(conn)

        # Her five slots now carry mainline's names + shas...
        on_disk = {f.version: f for f in migrations.discover()}
        for version in FORK_LEDGER:
            assert ledger[version]["name"] == on_disk[version].name
            assert ledger[version]["sha256"] == on_disk[version].sha256
            # ...but the original apply timestamp is untouched, which is only
            # true on the re-label path. The apply path would have stamped now.
            assert ledger[version]["applied_at"] == FORK_APPLIED_AT, (
                f"migration {version} was re-applied instead of re-labelled"
            )

        # 0040 and the renumbered fork migrations did run.
        assert ledger["0040"]["name"] == "0040_crm_fork_reconcile.sql"
        assert ledger["0040"]["applied_at"] != FORK_APPLIED_AT
        for version in ("0041", "0042", "0043", "0044"):
            assert version in ledger

        # Mainline 0035's DDL never touched the table: had it run, its
        # ADD CONSTRAINT would have failed on the seeded 'attempted' row.
        row = conn.execute(
            "SELECT pipeline_status FROM contacts WHERE id = 'sky-attempted'"
        ).fetchone()
        assert row is not None, "her contact row did not survive the upgrade"
        assert row[0] == "attempted"


def test_fork_upgrade_leaves_pipeline_status_unconstrained():
    with connect() as conn:
        _make_fork_shaped(conn)
        _seed_attempted_contact(conn)

    _reset_schema_cache()
    with connect() as conn:
        # 0040 ends with no CHECK — mainline's deliberate end state.
        checks = conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'contacts'::regclass AND contype = 'c' "
            "AND conname = 'contacts_pipeline_status_check'"
        ).fetchall()
        assert checks == []

        # New writes at her slug still work, as do operator-defined stages.
        conn.execute(
            "INSERT INTO contacts(id, type, stage, pipeline_status, created_at, updated_at) "
            "VALUES('post-upgrade', 'unclassified', 'cold', 'attempted', ?, ?)",
            (_now(), _now()),
        )
        conn.commit()


def test_fork_upgrade_backfills_mainline_only_schema():
    with connect() as conn:
        _make_fork_shaped(conn)

    _reset_schema_cache()
    with connect() as conn:
        contact_cols = {
            r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'contacts'"
            )
        }
        assert set(MAINLINE_ONLY_CONTACT_COLUMNS) <= contact_cols

        flag_cols = {
            r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'lead_profile_flags'"
            )
        }
        assert {"top25", "top25_at"} <= flag_cols

        settings_cols = {
            r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'crm_settings'"
            )
        }
        assert {
            "id", "custom_columns_json", "custom_stages_json",
            "lead_lists_json", "updated_at",
        } <= settings_cols

        tables = {
            r[0] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        }
        assert "account_goals" in tables

        indexes = {
            r[0] for r in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            )
        }
        assert "idx_lead_profile_flags_top25" in indexes
        assert "idx_chat_sessions_title_unique" not in indexes


# ─── 0040 idempotence ──────────────────────────────────────────────────


def test_reconcile_is_a_noop_on_a_clean_box_and_repeatable():
    with connect() as conn:
        before = _schema_snapshot(conn)
        sql = _reconcile_sql()
        conn.executescript(sql)
        conn.commit()
        assert _schema_snapshot(conn) == before, "0040 changed a clean box"
        conn.executescript(sql)
        conn.commit()
        assert _schema_snapshot(conn) == before, "0040 is not idempotent"


def test_reconcile_is_idempotent_on_a_fork_box():
    with connect() as conn:
        _make_fork_shaped(conn)

    _reset_schema_cache()
    with connect() as conn:
        after_upgrade = _schema_snapshot(conn)
        conn.executescript(_reconcile_sql())
        conn.commit()
        assert _schema_snapshot(conn) == after_upgrade


# ─── Atomicity of the version-slot-reuse branch ────────────────────────


def test_failed_slot_reuse_apply_leaves_the_ledger_row_intact(tmp_path, monkeypatch):
    """A mid-apply failure must not strand the version slot.

    The slot-reuse branch deletes the old ledger row before applying the
    on-disk file. If that delete is committed on its own, a failing apply
    leaves the row gone AND the new file unrecorded — permanently.
    """
    boom = tmp_path / "9999_boom.sql"
    boom.write_text("CREATE TABLE definitely_not_valid (;\n", encoding="utf-8")

    with connect() as conn:
        # Patch only after connect() has migrated the real schema, so the
        # bogus directory is used solely by the explicit run_pending below.
        monkeypatch.setattr(migrations, "_MIGRATIONS_DIR", tmp_path)
        conn.execute(
            "INSERT INTO _schema_migrations(version, name, sha256, applied_at) "
            "VALUES('9999', '9999_other.sql', 'deadbeef', ?)",
            (FORK_APPLIED_AT,),
        )
        conn.commit()

        with pytest.raises(migrations.MigrationError):
            migrations.run_pending(conn)

        row = conn.execute(
            "SELECT name, sha256, applied_at FROM _schema_migrations "
            "WHERE version = '9999'"
        ).fetchone()
        assert row is not None, "failed apply stranded the version slot"
        assert (row[0], row[1], row[2]) == (
            "9999_other.sql", "deadbeef", FORK_APPLIED_AT,
        )
