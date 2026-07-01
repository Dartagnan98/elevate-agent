"""CI gate: nothing outside ``elevate_cli/data/`` writes the central tables.

Sprint 1A invariant from ``docs/central-data-model-v1-plan.md``:

> **No-SQL-outside-module enforcement test.** New file
> ``tests/test_data_module_isolation.py`` greps the codebase for
> ``import sqlite3``, ``cursor.execute``, raw ``.db`` paths, and direct
> ``.jsonl`` writes outside ``elevate_cli/data/`` and
> ``elevate_cli/connectors/``. Fails CI if any are found.

The honest version: blanket-banning ``sqlite3`` would fail on day one
(Apple chat.db read-only, state.db runtime, agent_hub state, etc.).
What we actually care about is that no module other than
``elevate_cli/data/`` writes to the central operational store
(``contacts``, ``identities``, ``conversations``, ``events``,
``ingest_runs``, ``identity_conflicts``, ``lead_signals``, ``pcs_buyers``,
``data_parity_snapshots``, ``events_summary``).

The scan looks for SQL writes against those table names anywhere in
``elevate_cli/`` outside ``elevate_cli/data/``. Pre-existing modules
that legitimately write to the central DB during the cutover (notably
``outreach_db.py``, which folds in during Sprint 1E) live on the
allow-list below; remove their entry once they're gone.

Read-only queries (``SELECT … FROM events``) are NOT scanned — Sprint 2
shadow-mode is allowed to read directly while the dual-read middleware
is still spinning up. By Sprint 2 close, even those should route through
the data module; that test gets tightened then.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_PKG_ROOT = _REPO_ROOT / "elevate_cli"

# Paths that may legitimately write central tables during the
# Sprint 1 → Sprint 2 cutover. Each entry is a relative path (under
# ``elevate_cli/``) and a one-line reason. Remove an entry when the
# code stops touching the central tables.
_ALLOWLIST: dict[str, str] = {
    # Sprint 1B/1C — the data module itself.
    "data/": "the data module IS the central writer",
    # Phase-out target. outreach.db merges into operational.db in
    # Sprint 1E (`elevate migrate-data`) and the file goes away by
    # the end of Sprint 2. Until then, it owns templates/draft_attempts
    # writes against the legacy DB and that's expected.
    "outreach_db.py": "legacy SQLite store, folded in by Sprint 1E",
    # source_connectors writes to the legacy outreach.db schema (same
    # table names — contacts/conversations — but different columns:
    # source_record_id/display_name/etc., not the operational store's
    # id/source_id/source_native_id). Connectors get refactored to
    # route through elevate_cli.data helpers in Sprint 2 after the
    # backfill in Sprint 1E proves out.
    "source_connectors.py": "legacy connector writes, refactored in Sprint 2",
    # The source_connectors monolith split into source_connector_modules/;
    # these carry the SAME sanctioned legacy outreach.db writes under the
    # new paths (apple_messages REPLACE INTO conversations/contacts,
    # source_actions UPDATE conversations). Same Sprint 2 phase-out.
    "source_connector_modules/apple_messages.py": "legacy connector writes (split from source_connectors.py), refactored in Sprint 2",
    "source_connector_modules/source_actions.py": "legacy connector writes (split from source_connectors.py), refactored in Sprint 2",
    # One-shot Apple Contacts backfill that seeds identities/contacts
    # from macOS AddressBook + chat.db. Routes through elevate_cli.data
    # helpers in Sprint 2 once apple-messages becomes a first-class
    # connector; today it owns its identities/contacts writes.
    "apple_contacts_backfill.py": "one-shot backfill, refactored in Sprint 2 alongside apple-messages connector",
    "xposure_pcs_connector.py": "PCS import cutover still writes central lead tables directly; route through elevate_cli.data helpers in the PCS refactor",
    "xposure_pcs_enrichment.py": "PCS enrichment cutover still patches central contacts directly; route through elevate_cli.data helpers in the PCS refactor",
    "xposure_pcs_views.py": "PCS view helpers still patch PCS/contact state directly; route through elevate_cli.data helpers in the PCS refactor",
}

# Tables we want to lock down. Anything writing these from outside the
# data module is a violation worth investigating.
_CENTRAL_TABLES = (
    "contacts",
    "identities",
    "conversations",
    "events",
    "events_summary",
    "ingest_runs",
    "identity_conflicts",
    "lead_signals",
    "pcs_buyers",
    "data_parity_snapshots",
)

# SQL write verbs we care about. The regex tolerates whitespace and
# casing; it deliberately doesn't try to parse — false positives are
# the right side to err on for a CI gate.
_WRITE_VERBS = ("INSERT INTO", "UPDATE", "DELETE FROM", "REPLACE INTO")
_TABLE_GROUP = "|".join(re.escape(t) for t in _CENTRAL_TABLES)
_PATTERNS = [
    re.compile(rf"\b{verb}\s+(?:`|\")?({_TABLE_GROUP})\b", re.IGNORECASE)
    for verb in _WRITE_VERBS
]


def _is_allowlisted(rel_path: Path) -> bool:
    rel = rel_path.as_posix()
    for prefix in _ALLOWLIST:
        if rel == prefix or rel.startswith(prefix.rstrip("/") + "/") or rel.startswith(prefix):
            return True
    return False


def _python_files() -> list[Path]:
    return [
        p for p in _PKG_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def test_no_central_table_writes_outside_data_module():
    """Any write against contacts/identities/conversations/events/...
    from a file outside ``elevate_cli/data/`` (and outside the
    allow-list above) is treated as a regression."""
    violations: list[str] = []
    for path in _python_files():
        rel = path.relative_to(_PKG_ROOT)
        if _is_allowlisted(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for rx in _PATTERNS:
                m = rx.search(line)
                if m:
                    violations.append(
                        f"{rel}:{line_no}: {m.group(0)!r} — central tables "
                        "must only be written from elevate_cli/data/"
                    )
    if violations:
        msg = (
            "Central-store write found outside elevate_cli/data/:\n  - "
            + "\n  - ".join(violations)
            + "\n\nFix: use elevate_cli.data helpers, or add the file to "
            "_ALLOWLIST in this test with a one-line phase-out plan."
        )
        pytest.fail(msg)
