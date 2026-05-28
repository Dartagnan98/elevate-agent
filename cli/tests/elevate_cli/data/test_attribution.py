"""Sprint 4B tests — two-tier reply attribution.

Covers the five branches of :func:`attribute_inbound_reply`:

* confident — exactly one same-channel outbound with a template_id
* no_outbound — nothing in the 30-day window
* cross_channel_reply — outbound on email, reply on SMS
* multiple_outbounds_in_window — two same-channel outbounds
* outbound_has_no_template_id — same-channel one-off

Plus the 30-day window boundary so we know stale outbounds don't get
spuriously credited.
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


def _bootstrap(conn, *, channel="email"):
    """Common scaffolding: contact + conversation."""
    c = data.upsert_contact(conn, display_name="C")
    cv = data.get_or_create_conversation(
        conn, contact_id=c["id"], source_id="lofty-default",
        channel=channel, thread_key=f"thr-{channel}",
    )
    return c, cv


def _approve(conn, *, name="t"):
    proposed = data.propose_template(
        conn, lane="new-outreach", name=name, body="hi",
        origin="ai_oneoff", actor="agent:claude",
    )
    return data.approve_template(
        conn, proposed["id"], actor="human:test-admin",
    )


def _ts(now: datetime, **delta) -> str:
    return (now + timedelta(**delta)).isoformat(timespec="seconds")


def test_confident_path_bumps_wins():
    with data.connect() as conn:
        c, cv = _bootstrap(conn)
        tpl = _approve(conn)
        now = datetime.now(timezone.utc)
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="hello",
            source_id="lofty-default", thread_key="thr-email",
            template_id=tpl["id"], draft_attempt_id="draft-7",
            ts=_ts(now, days=-2),
        )

        verdict = attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="email",
            ts=_ts(now, days=0),
        )
        assert verdict["verdict"] == "confident"
        assert verdict["templateId"] == tpl["id"]
        assert verdict["draftAttemptId"] == "draft-7"

        stats = data.template_stats(conn, tpl["id"])
        assert stats["winsConfident"] == 1
        assert stats["replies"] == 1

        # reply_attributed event landed.
        rows = conn.execute(
            "SELECT kind FROM events WHERE conversation_id=? AND kind='reply_attributed'",
            (cv["id"],),
        ).fetchall()
        assert len(rows) == 1


def test_no_outbound_emits_ambiguous_with_empty_candidates():
    with data.connect() as conn:
        c, cv = _bootstrap(conn)
        now = datetime.now(timezone.utc)
        verdict = attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="email",
            ts=_ts(now, days=0),
        )
        assert verdict == {
            "verdict": "no_outbound",
            "candidateTemplateIds": [],
            "reason": "no_prior_outbound_in_window",
        }
        # Audit row still landed so the inbound is accounted for.
        rows = conn.execute(
            "SELECT payload_json FROM events WHERE kind='attribution_ambiguous'"
        ).fetchall()
        assert len(rows) == 1


def test_cross_channel_reply_marks_ambiguous_and_bumps_replies_only():
    with data.connect() as conn:
        c, cv = _bootstrap(conn, channel="sms")
        tpl = _approve(conn)
        now = datetime.now(timezone.utc)
        # Outbound on EMAIL channel.
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="hi",
            source_id="lofty-default", thread_key="thr-sms",
            template_id=tpl["id"],
            ts=_ts(now, days=-1),
        )
        # Inbound arrives on SMS — cross channel.
        verdict = attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="sms",
            ts=_ts(now, days=0),
        )
        assert verdict["verdict"] == "ambiguous"
        assert verdict["reason"] == "cross_channel_reply"
        assert verdict["candidateTemplateIds"] == [tpl["id"]]
        # replies bumped, wins NOT bumped.
        stats = data.template_stats(conn, tpl["id"])
        assert stats["winsConfident"] == 0
        assert stats["replies"] == 1


def test_multiple_outbounds_in_window_marks_ambiguous():
    with data.connect() as conn:
        c, cv = _bootstrap(conn)
        a = _approve(conn, name="A")
        b = _approve(conn, name="B")
        now = datetime.now(timezone.utc)
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="m1",
            source_id="lofty-default", thread_key="thr-email",
            template_id=a["id"], ts=_ts(now, days=-5),
        )
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="m2",
            source_id="lofty-default", thread_key="thr-email",
            template_id=b["id"], ts=_ts(now, days=-1),
        )
        verdict = attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="email",
            ts=_ts(now, days=0),
        )
        assert verdict["verdict"] == "ambiguous"
        assert verdict["reason"] == "multiple_outbounds_in_window"
        assert set(verdict["candidateTemplateIds"]) == {a["id"], b["id"]}
        # Both candidates: replies bumped, wins not bumped.
        for tid in (a["id"], b["id"]):
            s = data.template_stats(conn, tid)
            assert s["winsConfident"] == 0
            assert s["replies"] == 1


def test_outbound_with_no_template_id_marks_ambiguous():
    with data.connect() as conn:
        c, cv = _bootstrap(conn)
        now = datetime.now(timezone.utc)
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="freehand",
            source_id="lofty-default", thread_key="thr-email",
            template_id=None,
            ts=_ts(now, days=-1),
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
        assert verdict["candidateTemplateIds"] == []


def test_outbound_outside_30_day_window_is_ignored():
    """A 60-day-old outbound shouldn't be considered the parent of
    today's inbound — that would let stale templates accumulate
    spurious wins."""
    with data.connect() as conn:
        c, cv = _bootstrap(conn)
        tpl = _approve(conn)
        now = datetime.now(timezone.utc)
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="ancient",
            source_id="lofty-default", thread_key="thr-email",
            template_id=tpl["id"],
            ts=_ts(now, days=-60),
        )
        verdict = attribute_inbound_reply(
            conn,
            contact_id=c["id"],
            conversation_id=cv["id"],
            channel="email",
            ts=_ts(now, days=0),
        )
        assert verdict["verdict"] == "no_outbound"
        # No wins or replies bumped.
        stats = data.template_stats(conn, tpl["id"])
        assert stats["winsConfident"] == 0
        assert stats["replies"] == 0
