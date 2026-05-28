"""Sprint 5.2 — analyze_template_gaps tests.

Two kinds of gap:

1. ``low_reply_rate`` — for a (lane, channel) combo, every live
   template that has cleared the min-sample window has replyRate
   below 5%.
2. ``no_template_fit`` — inbound conversations with no same-channel
   templated outbound reply within 24h.

These tests verify the SQL/threshold logic in isolation. The AI
drafting downstream is out of scope (Codex auth blocked).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from elevate_cli import data
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _approve(conn, *, name, lane="new-outreach", channel="any"):
    proposed = data.propose_template(
        conn, lane=lane, name=name, body="hi", channel=channel,
        origin="ai_oneoff", actor="agent:claude",
    )
    return data.approve_template(
        conn, proposed["id"], actor="human:test-admin",
    )


def _bump(conn, template_id, *, uses, wins=0):
    for _ in range(uses):
        data.record_template_use(conn, template_id)
    for _ in range(wins):
        data.record_template_reply(conn, template_id, confident=True)


def _force_created(conn, template_id, iso):
    conn.execute(
        "UPDATE templates SET created_at=? WHERE id=?",
        (iso, template_id),
    )


def _ts(now, **delta):
    return (now + timedelta(**delta)).isoformat(timespec="seconds")


# ─── low_reply_rate gaps ────────────────────────────────────────────────


def test_low_reply_rate_gap_emitted_when_all_cleared_templates_under_5pct():
    with data.connect() as conn:
        bad = _approve(conn, name="bad", channel="email")
        # 100 uses, only 2 confident replies → 2% reply rate.
        _bump(conn, bad["id"], uses=100, wins=2)

        gaps = data.analyze_template_gaps(conn)
    low = [g for g in gaps if g["kind"] == "low_reply_rate"]
    assert len(low) == 1
    assert low[0]["lane"] == "new-outreach"
    assert low[0]["channel"] == "email"
    assert low[0]["maxReplyRate"] == pytest.approx(0.02, abs=0.0001)
    assert bad["id"] in low[0]["templateIds"]


def test_low_reply_rate_gap_NOT_emitted_when_winner_above_threshold():
    """If even one cleared template is above 5%, the lane/channel is
    not flagged — at least one of your scripts is landing."""
    with data.connect() as conn:
        bad = _approve(conn, name="bad", channel="email")
        good = _approve(conn, name="good", channel="email")
        _bump(conn, bad["id"], uses=100, wins=2)
        _bump(conn, good["id"], uses=100, wins=10)

        gaps = data.analyze_template_gaps(conn)
    assert all(g["kind"] != "low_reply_rate" for g in gaps)


def test_low_reply_rate_skips_templates_below_min_sample_window():
    """A 5-uses template doesn't qualify for low-reply-rate analysis —
    the sample is too thin to be a real signal."""
    with data.connect() as conn:
        thin = _approve(conn, name="thin", channel="email")
        _bump(conn, thin["id"], uses=5, wins=0)

        gaps = data.analyze_template_gaps(conn)
    # No low_reply_rate gap because no template cleared the window.
    assert all(g["kind"] != "low_reply_rate" for g in gaps)


def test_low_reply_rate_age_threshold_qualifies_old_template():
    """A template that's been around > 30 days qualifies as cleared
    even with low usage."""
    with data.connect() as conn:
        old = _approve(conn, name="old & quiet", channel="email")
        _bump(conn, old["id"], uses=10, wins=0)
        old_iso = (
            datetime.now(timezone.utc) - timedelta(days=45)
        ).isoformat(timespec="seconds")
        _force_created(conn, old["id"], old_iso)

        gaps = data.analyze_template_gaps(conn)
    low = [g for g in gaps if g["kind"] == "low_reply_rate"]
    assert len(low) == 1
    assert old["id"] in low[0]["templateIds"]


# ─── no_template_fit gaps ──────────────────────────────────────────────


def test_no_template_fit_emits_when_inbound_has_no_templated_reply():
    """An inbound that never receives a templated outbound reply within
    24h should appear in the gap report."""
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="apple-messages",
            channel="imessage", thread_key="t1",
        )
        now = datetime.now(timezone.utc)
        data.record_inbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="imessage", body="hey",
            source_id="apple-messages", thread_key="t1",
            ts=_ts(now, days=-2),
        )

        gaps = data.analyze_template_gaps(conn)
    fits = [g for g in gaps if g["kind"] == "no_template_fit"]
    assert len(fits) == 1
    assert fits[0]["channel"] == "imessage"
    assert fits[0]["sourceId"] == "apple-messages"
    assert fits[0]["inboundCount"] == 1


def test_no_template_fit_not_emitted_when_templated_reply_lands_in_window():
    """A templated outbound within 24h of the inbound clears the gap."""
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="apple-messages",
            channel="imessage", thread_key="t1",
        )
        proposed = data.propose_template(
            conn, lane="new-outreach", name="reply", body="hi",
            origin="ai_oneoff", actor="agent:claude",
        )
        tpl = data.approve_template(
            conn, proposed["id"], actor="human:d",
        )
        now = datetime.now(timezone.utc)
        data.record_inbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="imessage", body="hey",
            source_id="apple-messages", thread_key="t1",
            ts=_ts(now, days=-2, hours=-2),
        )
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="imessage", body="hey back",
            source_id="apple-messages", thread_key="t1",
            template_id=tpl["id"],
            ts=_ts(now, days=-2, hours=-1),
        )

        gaps = data.analyze_template_gaps(conn)
    assert all(g["kind"] != "no_template_fit" for g in gaps)


def test_no_template_fit_groups_by_channel_and_source():
    """Three SMS inbounds under one source roll up as inboundCount=3."""
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="apple-messages",
            channel="sms", thread_key="t1",
        )
        now = datetime.now(timezone.utc)
        for i in range(3):
            data.record_inbound(
                conn, contact_id=c["id"], conversation_id=cv["id"],
                channel="sms", body=f"hey {i}",
                source_id="apple-messages",
                thread_key=f"t1-{i}",
                ts=_ts(now, days=-2, minutes=-i),
            )

        gaps = data.analyze_template_gaps(conn)
    fits = [g for g in gaps if g["kind"] == "no_template_fit"]
    assert len(fits) == 1
    assert fits[0]["inboundCount"] == 3
    assert len(fits[0]["exampleInboundIds"]) == 3


def test_no_template_fit_respects_lookback_days():
    """An inbound from 60 days ago is outside a 30-day lookback
    window and should not be flagged."""
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="apple-messages",
            channel="sms", thread_key="t1",
        )
        now = datetime.now(timezone.utc)
        data.record_inbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="sms", body="ancient",
            source_id="apple-messages", thread_key="t1-old",
            ts=_ts(now, days=-60),
        )

        gaps = data.analyze_template_gaps(conn, days_back=30)
    assert all(g["kind"] != "no_template_fit" for g in gaps)


def test_analyze_returns_empty_when_clean():
    """An empty operational store returns no gaps."""
    with data.connect() as conn:
        gaps = data.analyze_template_gaps(conn)
    assert gaps == []
