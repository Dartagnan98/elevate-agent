"""Sprint 4A tests — template picker.

Covers eligibility (lane/channel/active/status), 7-day per-contact
cooldown, Thompson seed determinism, match_rules predicates, the AI
ranker hook (override + fallback on miss/exception), and the
no-eligible-templates → ``None`` branch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from elevate_cli import data
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data.picker import (
    _channel_matches,
    _match_rules_pass,
    eligible_templates,
    pick_template,
)


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _approve(conn, *, lane="new-outreach", name, body="hi", channel="any",
             match_rules=None):
    proposed = data.propose_template(
        conn, lane=lane, name=name, body=body, channel=channel,
        match_rules=match_rules, origin="ai_oneoff", actor="agent:claude",
    )
    return data.approve_template(
        conn, proposed["id"], actor="human:test-admin",
    )


def test_channel_matches_helper():
    assert _channel_matches("any", "email") is True
    assert _channel_matches("any", "sms") is True
    assert _channel_matches("email", "email") is True
    assert _channel_matches("email", "sms") is False


def test_match_rules_pass_simple_predicates():
    assert _match_rules_pass(None, {}) is True
    assert _match_rules_pass({}, {"contactType": "buyer"}) is True
    assert _match_rules_pass(
        {"contactType": "buyer"}, {"contactType": "buyer"}
    ) is True
    assert _match_rules_pass(
        {"contactType": "buyer"}, {"contactType": "listing"}
    ) is False
    # list-of-allowed
    assert _match_rules_pass(
        {"contactType": ["buyer", "investor"]},
        {"contactType": "investor"},
    ) is True
    # JSON-string form (the column is JSON-typed)
    assert _match_rules_pass(
        '{"contactType": "buyer"}', {"contactType": "buyer"}
    ) is True
    # malformed JSON falls through (don't silently drop)
    assert _match_rules_pass("{not-json}", {"contactType": "buyer"}) is True


def test_eligible_templates_filters_by_lane_and_channel():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        sms_only = _approve(conn, name="sms only", channel="sms")
        any_ch = _approve(conn, name="any channel", channel="any")
        wrong_lane = _approve(
            conn, lane="hot-leads-watcher", name="wrong lane",
        )

        eligible = eligible_templates(
            conn,
            contact_id=contact["id"],
            lane="new-outreach",
            channel="email",
        )
        ids = {t["id"] for t in eligible}
        # SMS-only and wrong-lane filtered out; channel='any' kept.
        assert any_ch["id"] in ids
        assert sms_only["id"] not in ids
        assert wrong_lane["id"] not in ids


def test_eligible_templates_excludes_proposed_and_inactive():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        live = _approve(conn, name="live")
        proposed = data.propose_template(
            conn, lane="new-outreach", name="still proposed",
            body="hi", origin="ai_oneoff", actor="agent:claude",
        )
        retired = _approve(conn, name="retired")
        data.retire_template(conn, retired["id"], actor="human:d")

        eligible = eligible_templates(
            conn,
            contact_id=contact["id"],
            lane="new-outreach",
            channel="email",
        )
        ids = {t["id"] for t in eligible}
        assert live["id"] in ids
        assert proposed["id"] not in ids
        assert retired["id"] not in ids


def test_cooldown_excludes_recently_sent_template():
    """A template sent to this contact in the last 7 days is excluded."""
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=contact["id"], source_id="lofty-default",
            channel="email", thread_key="t",
        )
        recent = _approve(conn, name="recent")
        old = _approve(conn, name="old")
        fresh = _approve(conn, name="fresh")

        now = datetime.now(timezone.utc)
        # recent: 2 days ago — inside cooldown
        data.record_send(
            conn, contact_id=contact["id"], conversation_id=cv["id"],
            channel="email", template_id=recent["id"],
            provider_message_id="m1", source_id="lofty-default",
            ts=(now - timedelta(days=2)).isoformat(timespec="seconds"),
        )
        # old: 14 days ago — outside cooldown
        data.record_send(
            conn, contact_id=contact["id"], conversation_id=cv["id"],
            channel="email", template_id=old["id"],
            provider_message_id="m2", source_id="lofty-default",
            ts=(now - timedelta(days=14)).isoformat(timespec="seconds"),
        )

        eligible = eligible_templates(
            conn,
            contact_id=contact["id"],
            lane="new-outreach",
            channel="email",
            now=now,
        )
        ids = {t["id"] for t in eligible}
        assert recent["id"] not in ids
        assert old["id"] in ids
        assert fresh["id"] in ids


def test_cooldown_does_not_leak_across_contacts():
    """Cooldown is per-contact: a send to contact A shouldn't gate B."""
    with data.connect() as conn:
        a = data.upsert_contact(conn, display_name="A")
        b = data.upsert_contact(conn, display_name="B")
        cv = data.get_or_create_conversation(
            conn, contact_id=a["id"], source_id="lofty-default",
            channel="email", thread_key="t",
        )
        tpl = _approve(conn, name="shared")
        data.record_send(
            conn, contact_id=a["id"], conversation_id=cv["id"],
            channel="email", template_id=tpl["id"],
            provider_message_id="m1", source_id="lofty-default",
        )

        eligible_a = eligible_templates(
            conn, contact_id=a["id"],
            lane="new-outreach", channel="email",
        )
        eligible_b = eligible_templates(
            conn, contact_id=b["id"],
            lane="new-outreach", channel="email",
        )
        assert tpl["id"] not in {t["id"] for t in eligible_a}
        assert tpl["id"] in {t["id"] for t in eligible_b}


def test_match_rules_filter_uses_context():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        buyer_only = _approve(
            conn, name="buyer only", match_rules={"contactType": "buyer"},
        )
        no_rule = _approve(conn, name="no rule")

        buyer_pool = eligible_templates(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
            context={"contactType": "buyer"},
        )
        listing_pool = eligible_templates(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
            context={"contactType": "listing"},
        )
        buyer_ids = {t["id"] for t in buyer_pool}
        listing_ids = {t["id"] for t in listing_pool}
        assert buyer_only["id"] in buyer_ids
        assert buyer_only["id"] not in listing_ids
        # template with no rule survives both contexts
        assert no_rule["id"] in buyer_ids
        assert no_rule["id"] in listing_ids


def test_pick_template_returns_none_when_pool_empty():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        # No templates exist at all.
        pick = pick_template(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
        )
        assert pick is None


def test_pick_template_thompson_is_deterministic_with_seed():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        a = _approve(conn, name="A")
        b = _approve(conn, name="B")
        c = _approve(conn, name="C")
        # Diverging counters so the Beta distributions actually differ.
        for _ in range(5):
            data.record_template_use(conn, a["id"])
        for _ in range(5):
            data.record_template_use(conn, b["id"])
            data.record_template_reply(conn, b["id"], confident=True)
        for _ in range(2):
            data.record_template_use(conn, c["id"])

        pick1 = pick_template(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email", seed=12345,
        )
        pick2 = pick_template(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email", seed=12345,
        )
        assert pick1 is not None
        assert pick2 is not None
        assert pick1["id"] == pick2["id"]
        assert pick1["pickRationale"] == "thompson"
        assert pick1["thompsonScores"].keys() == {a["id"], b["id"], c["id"]}


def test_pick_template_ranker_override_when_eligible():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        a = _approve(conn, name="A")
        b = _approve(conn, name="B")

        captured = {}

        def ranker(pool, context):
            captured["pool_ids"] = [t["id"] for t in pool]
            captured["scores"] = context.get("thompsonScores")
            # Always pick B regardless of Thompson order.
            for t in pool:
                if t["id"] == b["id"]:
                    return t
            return None

        pick = pick_template(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
            ranker=ranker, seed=1,
        )
        assert pick["id"] == b["id"]
        assert pick["pickRationale"] == "ai_override"
        # Ranker received both candidates + the score map.
        assert set(captured["pool_ids"]) == {a["id"], b["id"]}
        assert set(captured["scores"].keys()) == {a["id"], b["id"]}


def test_pick_template_ranker_falls_back_when_pick_not_eligible():
    """Ranker returning a template that's not in the eligible pool is
    discarded — protects against the AI hallucinating an id."""
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        a = _approve(conn, name="A")

        def liar_ranker(pool, context):
            return {"id": "not-a-real-template-id"}

        pick = pick_template(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
            ranker=liar_ranker, seed=1,
        )
        assert pick["id"] == a["id"]
        assert pick["pickRationale"] == "thompson"


def test_pick_template_ranker_exception_falls_back_to_thompson():
    with data.connect() as conn:
        contact = data.upsert_contact(conn, display_name="C")
        a = _approve(conn, name="A")

        def angry_ranker(pool, context):
            raise RuntimeError("ranker exploded")

        pick = pick_template(
            conn, contact_id=contact["id"],
            lane="new-outreach", channel="email",
            ranker=angry_ranker, seed=1,
        )
        # We still got a deterministic pick — ranker error doesn't
        # propagate up to the outreach worker.
        assert pick["id"] == a["id"]
        assert pick["pickRationale"] == "thompson"
