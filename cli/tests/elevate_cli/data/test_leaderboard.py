"""Sprint 4C tests — template leaderboard with min-sample window.

Covers:

* Lineage rollup — every row in a parent_template_id chain contributes
  its uses/replies/wins to the lineage's aggregate; the live row is the
  display.
* Authoritative bucket — uses ≥ 50 OR lineage age > 30 days.
* Trial bucket — picker-eligible but stats too thin to rank.
* Sort order — authoritative by (winRate, uses) desc; trial by
  createdAt desc.
* lane / channel filters.
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


def _approve(conn, *, lane="new-outreach", name, channel="any"):
    proposed = data.propose_template(
        conn, lane=lane, name=name, body="hi", channel=channel,
        origin="ai_oneoff", actor="agent:claude",
    )
    return data.approve_template(
        conn, proposed["id"], actor="human:dartagnan",
    )


def _force_created(conn, template_id, iso):
    """Backdate a template's created_at — leaderboard age is by lineage."""
    conn.execute(
        "UPDATE templates SET created_at=? WHERE id=?",
        (iso, template_id),
    )


def _bump(conn, template_id, *, uses, wins=0, replies=None):
    if replies is None:
        replies = wins  # confident replies match wins by default
    for _ in range(uses):
        data.record_template_use(conn, template_id)
    for _ in range(wins):
        data.record_template_reply(conn, template_id, confident=True)
    extra = replies - wins
    for _ in range(extra):
        data.record_template_reply(conn, template_id, confident=False)


def test_authoritative_vs_trial_bucket_split_by_uses_threshold():
    with data.connect() as conn:
        big = _approve(conn, name="big sample")
        small = _approve(conn, name="thin sample")
        _bump(conn, big["id"], uses=60, wins=12)
        _bump(conn, small["id"], uses=3, wins=1)

        board = data.template_leaderboard(conn)
        auth_ids = {r["lineageRootId"] for r in board["authoritative"]}
        trial_ids = {r["lineageRootId"] for r in board["trial"]}
        assert big["id"] in auth_ids
        assert small["id"] in trial_ids


def test_age_threshold_promotes_to_authoritative_even_with_low_uses():
    """A template that's been around > 30 days qualifies as authoritative
    regardless of sample size — at that age its stats are believable."""
    with data.connect() as conn:
        old = _approve(conn, name="old but quiet")
        _bump(conn, old["id"], uses=4, wins=1)
        old_iso = (
            datetime.now(timezone.utc) - timedelta(days=45)
        ).isoformat(timespec="seconds")
        _force_created(conn, old["id"], old_iso)

        board = data.template_leaderboard(conn)
        auth_ids = {r["lineageRootId"] for r in board["authoritative"]}
        assert old["id"] in auth_ids


def test_lineage_rollup_aggregates_versions():
    """When a human edits a live template, the new row's counters reset
    to zero. The leaderboard must roll the chain back up so a
    well-performing template doesn't disappear after one edit."""
    with data.connect() as conn:
        v1 = _approve(conn, name="evergreen")
        _bump(conn, v1["id"], uses=40, wins=10)
        v2 = data.edit_template(
            conn, v1["id"], new_body="tighter copy", actor="human:d",
        )
        _bump(conn, v2["id"], uses=20, wins=5)

        board = data.template_leaderboard(conn)
        # Single lineage entry; uses/wins summed.
        rows = [r for r in board["authoritative"] + board["trial"]
                if r["lineageRootId"] == v1["id"]]
        assert len(rows) == 1
        row = rows[0]
        assert row["uses"] == 60
        assert row["wins"] == 15
        # Display picks the live row (v2), not the superseded v1.
        assert row["displayId"] == v2["id"]
        assert row["body"] == "tighter copy"
        assert row["versionCount"] == 2
        # 60 uses ≥ 50 → authoritative.
        assert row in board["authoritative"]


def test_authoritative_sorted_by_winrate_then_uses():
    with data.connect() as conn:
        a = _approve(conn, name="A high winrate")
        b = _approve(conn, name="B low winrate")
        c = _approve(conn, name="C tied winrate but more uses")
        _bump(conn, a["id"], uses=50, wins=25)   # 50% winrate
        _bump(conn, b["id"], uses=50, wins=10)   # 20%
        _bump(conn, c["id"], uses=100, wins=50)  # 50%, more uses

        board = data.template_leaderboard(conn)
        ids_in_order = [r["lineageRootId"] for r in board["authoritative"]]
        # A and C tied on winRate (0.5), C wins on uses tiebreak; B last.
        assert ids_in_order.index(c["id"]) < ids_in_order.index(a["id"])
        assert ids_in_order.index(a["id"]) < ids_in_order.index(b["id"])


def test_trial_sorted_by_created_at_desc():
    with data.connect() as conn:
        first = _approve(conn, name="first")
        # Backdate first so the second is newer in created_at terms.
        _force_created(
            conn,
            first["id"],
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat(timespec="seconds"),
        )
        second = _approve(conn, name="second")

        board = data.template_leaderboard(conn)
        ids_in_order = [r["lineageRootId"] for r in board["trial"]]
        assert ids_in_order.index(second["id"]) < ids_in_order.index(first["id"])


def test_lane_and_channel_filters():
    with data.connect() as conn:
        new = _approve(conn, lane="new-outreach", name="new", channel="email")
        watcher = _approve(
            conn, lane="hot-leads-watcher", name="hot", channel="email",
        )
        sms = _approve(conn, lane="new-outreach", name="sms", channel="sms")

        new_only = data.template_leaderboard(conn, lane="new-outreach")
        new_ids = {r["lineageRootId"]
                   for r in new_only["authoritative"] + new_only["trial"]}
        assert new["id"] in new_ids
        assert sms["id"] in new_ids
        assert watcher["id"] not in new_ids

        # channel='email' allows email + 'any'; sms-only excluded.
        email_only = data.template_leaderboard(
            conn, lane="new-outreach", channel="email",
        )
        email_ids = {r["lineageRootId"]
                     for r in email_only["authoritative"] + email_only["trial"]}
        assert new["id"] in email_ids
        assert sms["id"] not in email_ids
