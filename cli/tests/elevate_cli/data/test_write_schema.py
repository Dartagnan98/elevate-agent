"""Guard: every column the code INSERTs must be created by a migration.

A column referenced in an INSERT column-list with no migration to create it
makes every INSERT into that table fail. Under the shared-transaction backfill
that first failure aborts the whole transaction and silently drops the rest of
the sync — this is exactly the `lofty_lead_user_id` incident (a column added to
`contacts._ENRICHMENT_COLUMNS` with no matching migration dropped ~1,500
contacts + all lead/lifecycle events on a live box).

This test fails the build the moment such a gap is introduced, for every table
whose INSERT is built from a code-side column list. It is a pure static parse
of the migration SQL — no database required, so it runs anywhere CI runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from elevate_cli.data.contacts import _ENRICHMENT_COLUMNS
from elevate_cli.data.deals import _DEAL_INSERT_BASE_COLUMNS

_MIGRATIONS = (
    Path(__file__).resolve().parents[3]
    / "elevate_cli"
    / "data"
    / "migrations_pg"
)

_CONSTRAINT = re.compile(
    r"(?i)^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT)\b"
)
_IDENT = re.compile(r'^"?([a-zA-Z_][a-zA-Z0-9_]*)"?')


def _all_migration_sql() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(_MIGRATIONS.glob("*.sql"))
    )


def _columns_created_for(table: str) -> set[str]:
    """Every column created for ``table`` across all migrations — both the
    CREATE TABLE body and any ALTER TABLE ... ADD COLUMN."""
    sql = _all_migration_sql()
    cols: set[str] = set()

    # CREATE TABLE [IF NOT EXISTS] <table> ( ... );
    for m in re.finditer(
        rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{table}\s*\((.*?)\n\s*\)\s*;",
        sql,
        re.IGNORECASE | re.DOTALL,
    ):
        for raw in m.group(1).splitlines():
            line = raw.strip().rstrip(",").strip()
            if not line or line.startswith("--") or _CONSTRAINT.match(line):
                continue
            ident = _IDENT.match(line)
            if ident:
                cols.add(ident.group(1))

    # ALTER TABLE <table> ADD COLUMN [IF NOT EXISTS] <name>
    for m in re.finditer(
        rf'ALTER\s+TABLE\s+{table}\s+ADD\s+COLUMN\s+'
        rf'(?:IF\s+NOT\s+EXISTS\s+)?"?([a-zA-Z_][a-zA-Z0-9_]*)"?',
        sql,
        re.IGNORECASE,
    ):
        cols.add(m.group(1))

    return cols


@pytest.mark.parametrize(
    "table, whitelist",
    [
        ("contacts", _ENRICHMENT_COLUMNS),
        ("deals", _DEAL_INSERT_BASE_COLUMNS),
    ],
)
def test_insert_columns_have_migrations(table, whitelist):
    created = _columns_created_for(table)
    assert created, f"no migration creates table {table!r}"
    missing = [c for c in whitelist if c not in created]
    assert not missing, (
        f"{table}: columns are written by code (INSERT column list) but no "
        f"migration creates them: {missing}. Add a numbered migration in "
        f"migrations_pg/ — do not just add the column to the code list."
    )
