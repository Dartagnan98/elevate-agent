"""Sprint 5.1 — one-off candidate detector tests.

When attribution finds a confident reply to a same-channel outbound
that had ``template_id IS NULL`` (a freehand reply, not a template),
we seed a ``proposed`` template with the freehand body so the realtor
can templatize it on /admin/templates. This test file proves:

1. The candidate is created with the right body / origin / proposed_by.
2. A ``template_candidate`` event lands.
3. The verdict carries ``seededCandidateId``.
4. Re-running attribution on a duplicate inbound does NOT double-propose.
5. We don't seed a candidate when the outbound already had a template_id
   (confident path) or when there were no outbounds at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from elevate_cli import data
from elevate_cli.data.attribution import attribute_inbound_reply
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _bootstrap(channel="email"):
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="lofty-default",
            channel=channel, thread_key=f"thr-{channel}",
        )
    return c, cv


def _ts(now: datetime, **delta) -> str:
    return (now + timedelta(**delta)).isoformat(timespec="seconds")


def test_oneoff_seeds_proposed_template_with_freehand_body():
    c, cv = _bootstrap()
    now = datetime.now(timezone.utc)
    freehand = "Just thinking of you — how's the house hunt going?"
    with data.connect() as conn:
        outbound = data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body=freehand,
            source_id="lofty-default", thread_key="thr-email",
            template_id=None, ts=_ts(now, days=-1),
        )
        verdict = attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="email",
            ts=_ts(now, days=0),
        )

    assert verdict["verdict"] == "ambiguous"
    assert verdict["reason"] == "outbound_has_no_template_id"
    assert "seededCandidateId" in verdict

    # Candidate template was created.
    with data.connect() as conn:
        proposed = data.list_proposed_templates(conn)
    assert len(proposed) == 1
    cand = proposed[0]
    assert cand["body"] == freehand
    assert cand["origin"] == "ai_oneoff"
    assert cand["proposedByEventId"] == outbound["id"]
    assert cand["channel"] == "email"
    assert cand["status"] == "proposed"
    assert cand["active"] is False  # not live until human approves
    assert cand["id"] == verdict["seededCandidateId"]


def test_oneoff_records_template_candidate_event():
    c, cv = _bootstrap()
    now = datetime.now(timezone.utc)
    with data.connect() as conn:
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="hand-written ping",
            source_id="lofty-default", thread_key="thr-email",
            template_id=None, ts=_ts(now, days=-1),
        )
        attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="email",
            ts=_ts(now, days=0),
        )

        rows = conn.execute(
            "SELECT actor, template_id FROM events WHERE kind='template_candidate'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["actor"] == "agent:oneoff_detector"
    assert rows[0]["template_id"] is not None


def test_oneoff_is_idempotent_on_repeated_attribution():
    """Two inbounds in the same conversation should not double-propose
    the same outbound's freehand body."""
    c, cv = _bootstrap()
    now = datetime.now(timezone.utc)
    with data.connect() as conn:
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="ping",
            source_id="lofty-default", thread_key="thr-email",
            template_id=None, ts=_ts(now, days=-2),
        )
        # First inbound triggers seeding.
        attribute_inbound_reply(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", ts=_ts(now, hours=-1),
        )
        # Second inbound: still outbound_has_no_template_id, but the
        # candidate already exists.
        attribute_inbound_reply(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", ts=_ts(now, days=0),
        )
        proposed = data.list_proposed_templates(conn)
    assert len(proposed) == 1


def test_no_candidate_seeded_on_confident_path():
    """A reply to a templated outbound shouldn't seed a freehand
    candidate — that template already exists."""
    c, cv = _bootstrap()
    now = datetime.now(timezone.utc)
    with data.connect() as conn:
        existing_proposed = data.propose_template(
            conn, lane="new-outreach", name="existing", body="hi",
            origin="ai_oneoff", actor="agent:claude",
        )
        existing = data.approve_template(
            conn, existing_proposed["id"], actor="human:d",
        )
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="hi",
            source_id="lofty-default", thread_key="thr-email",
            template_id=existing["id"], ts=_ts(now, days=-1),
        )
        verdict = attribute_inbound_reply(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", ts=_ts(now, days=0),
        )
        proposed = data.list_proposed_templates(conn)

    assert verdict["verdict"] == "confident"
    # Only the seeded existing template — no freehand candidate added.
    assert len(proposed) == 0
    assert "seededCandidateId" not in verdict


def test_no_candidate_seeded_when_no_outbound_in_window():
    c, cv = _bootstrap()
    now = datetime.now(timezone.utc)
    with data.connect() as conn:
        verdict = attribute_inbound_reply(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", ts=_ts(now, days=0),
        )
        proposed = data.list_proposed_templates(conn)
    assert verdict["verdict"] == "no_outbound"
    assert len(proposed) == 0
