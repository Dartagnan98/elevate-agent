"""Sprint 5.4 — approval invariant.

A template row may only land in ``status='live'`` when a human signed
off. This is enforced at TWO layers:

1. **Schema CHECK** — the templates table refuses any row with
   ``status='live' AND (approved_at IS NULL OR approved_by IS NULL)``.
2. **Data module** — :func:`approve_template` rejects any actor that
   doesn't start with ``'human'``.

If either guard slips, an agent could promote its own template into
the live pool and start being chosen by the picker without a human
ever seeing it. These tests prove neither guard is leaky.
"""

from __future__ import annotations

import sqlite3

import pytest

from elevate_cli import data
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data._util import new_id, now_iso


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_raw_insert_live_without_approval_fails_check():
    """The schema CHECK forbids an end-run around the data module."""
    with data.connect() as conn:
        now = now_iso()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO templates(
                    id, lane, name, body, channel, active, status,
                    uses, replies, wins, version, origin,
                    approved_at, approved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'any', 1, 'live',
                          0, 0, 0, 1, 'ai_oneoff',
                          NULL, NULL, ?, ?)
                """,
                (new_id(), "new-outreach", "sneaky", "live without approval",
                 now, now),
            )


def test_raw_insert_live_with_only_approved_at_still_fails_check():
    """Both approved_at AND approved_by must be set."""
    with data.connect() as conn:
        now = now_iso()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO templates(
                    id, lane, name, body, channel, active, status,
                    uses, replies, wins, version, origin,
                    approved_at, approved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'any', 1, 'live',
                          0, 0, 0, 1, 'ai_oneoff',
                          ?, NULL, ?, ?)
                """,
                (new_id(), "new-outreach", "half-approved",
                 "approved_by missing", now, now, now),
            )


def test_raw_insert_proposed_with_approved_at_fails_check():
    """A proposed template with an approval timestamp is incoherent."""
    with data.connect() as conn:
        now = now_iso()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO templates(
                    id, lane, name, body, channel, active, status,
                    uses, replies, wins, version, origin,
                    approved_at, approved_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'any', 0, 'proposed',
                          0, 0, 0, 1, 'ai_oneoff',
                          ?, 'human:test-admin', ?, ?)
                """,
                (new_id(), "new-outreach", "approved while proposed",
                 "premature approval", now, now, now),
            )


def test_approve_template_rejects_agent_actor():
    """Module gate: agent:claude cannot approve, even if it proposed."""
    with data.connect() as conn:
        proposed = data.propose_template(
            conn,
            lane="new-outreach",
            name="agent self-approve",
            body="hi",
            origin="ai_oneoff",
            actor="agent:claude",
        )
        with pytest.raises(PermissionError):
            data.approve_template(
                conn, proposed["id"], actor="agent:claude"
            )
        # Still proposed, still not active.
        same = data.get_template(conn, proposed["id"])
        assert same["status"] == "proposed"
        assert same["active"] == 0
        assert same["approvedAt"] is None
        assert same["approvedBy"] is None


def test_approve_template_rejects_cron_and_other_non_human_actors():
    """Anything not starting with 'human' is denied."""
    with data.connect() as conn:
        proposed = data.propose_template(
            conn,
            lane="new-outreach",
            name="cron self-approve",
            body="hi",
            origin="ai_pattern",
            actor="agent:claude",
        )
        for actor in ("cron", "system", "agent:codex", "bot:zapier"):
            with pytest.raises(PermissionError):
                data.approve_template(
                    conn, proposed["id"], actor=actor
                )


def test_approve_template_accepts_human_actor():
    with data.connect() as conn:
        proposed = data.propose_template(
            conn,
            lane="new-outreach",
            name="legit",
            body="hi",
            origin="ai_oneoff",
            actor="agent:claude",
        )
        approved = data.approve_template(
            conn, proposed["id"], actor="human:test-admin",
        )
        assert approved["status"] == "live"
        assert approved["active"] == 1
        assert approved["approvedAt"] is not None
        assert approved["approvedBy"] == "human:test-admin"


def test_edit_template_also_requires_human_actor():
    """Edits create a fresh live row — same approval invariant applies."""
    with data.connect() as conn:
        proposed = data.propose_template(
            conn, lane="new-outreach", name="for editing",
            body="v1", origin="ai_oneoff", actor="agent:claude",
        )
        live = data.approve_template(
            conn, proposed["id"], actor="human:d",
        )
        with pytest.raises(PermissionError):
            data.edit_template(
                conn, live["id"], new_body="v2", actor="agent:claude",
            )


def test_no_path_from_propose_to_live_without_human():
    """End-to-end: an agent cannot get a live template no matter what
    sequence of public data-module calls it makes."""
    with data.connect() as conn:
        # Propose
        proposed = data.propose_template(
            conn, lane="new-outreach", name="end-run",
            body="trying to bypass", origin="ai_pattern",
            actor="agent:claude",
        )
        # Try to approve as agent — denied.
        with pytest.raises(PermissionError):
            data.approve_template(
                conn, proposed["id"], actor="agent:claude",
            )
        # Try to edit as agent — denied.
        with pytest.raises(PermissionError):
            data.edit_template(
                conn, proposed["id"], new_body="x", actor="agent:claude",
            )
        # Verify nothing flipped.
        final = data.get_template(conn, proposed["id"])
        assert final["status"] == "proposed"
        # Picker won't see it (status='live' AND active=1 are filters).
        from elevate_cli.data.picker import eligible_templates
        contact = data.upsert_contact(conn, display_name="C")
        eligible = eligible_templates(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
        )
        assert proposed["id"] not in {t["id"] for t in eligible}
