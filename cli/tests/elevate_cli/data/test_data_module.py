"""End-to-end smoke test for the Sprint 1C data module surface.

Walks the typical realtor flow:

    open ingest run
      → upsert contact + identity
      → resolve identity for inbound message
      → get_or_create_conversation
      → record_inbound, record_outbound, record_send
      → propose template (agent), reject for non-human approve, then human approve
      → record reply, classify contact, park contact
    close ingest run

The conftest's ``_hermetic_environment`` fixture redirects
``ELEVATE_HOME`` to a per-test tmp dir so every test starts with an
empty database.
"""

from __future__ import annotations

import sqlite3

import pytest

from elevate_cli import data
from elevate_cli.data.connection import _reset_schema_cache


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def test_ingest_run_lifecycle():
    with data.connect() as conn:
        run = data.record_ingest_run_started(conn, "lofty-default")
        assert run["status"] == "running"
        contact = data.upsert_contact(
            conn,
            display_name="Demo Agent Test",
            primary_email="client_tools@example.com",
            source_key="lofty-lead:1142409008547568",
            ingest_run_id=run["id"],
        )
        # ingest_marker uses the contact as anchor — verify it lands
        marker = data.record_ingest_marker(
            conn,
            kind="ingest_run_started",
            ingest_run_id=run["id"],
            source_id="lofty-default",
            contact_id=contact["id"],
        )
        assert marker["kind"] == "ingest_run_started"

        completed = data.record_ingest_run_completed(
            conn,
            run["id"],
            status="completed",
            rows_seen=10,
            rows_written=10,
        )
        assert completed["status"] == "completed"
        assert completed["rowsWritten"] == 10


def test_identity_resolve_round_trip():
    with data.connect() as conn:
        contact = data.upsert_contact(
            conn, display_name="Buyer", primary_email="buyer@example.com"
        )
        data.add_identity(
            conn,
            contact_id=contact["id"],
            kind="email",
            value="Buyer@Example.com",   # caps + extra spaces — should normalize
            source_id="lofty-default",
            verified=True,
        )
        resolved = data.resolve_identity(conn, "email", "buyer@EXAMPLE.com")
        assert resolved is not None
        assert resolved["id"] == contact["id"]


def test_identity_conflict_blocks_auto_merge():
    with data.connect() as conn:
        a = data.upsert_contact(conn, display_name="A")
        b = data.upsert_contact(conn, display_name="B")
        data.add_identity(
            conn, contact_id=a["id"], kind="email",
            value="dup@example.com", source_id="src1",
        )
        # Second contact tries to claim the same email — should NOT merge,
        # should write a conflict and flag both contacts.
        data.add_identity(
            conn, contact_id=b["id"], kind="email",
            value="dup@example.com", source_id="src2",
        )
        conflicts = data.list_open_conflicts(conn)
        assert len(conflicts) == 1
        assert conflicts[0]["reason"] == "multiple_matches"
        assert set(conflicts[0]["candidateContactIds"]) == {a["id"], b["id"]}
        # Both contacts flagged.
        assert data.get_contact(conn, a["id"])["hasOpenConflict"] is True
        assert data.get_contact(conn, b["id"])["hasOpenConflict"] is True


def test_human_resolves_conflict_with_merge():
    with data.connect() as conn:
        a = data.upsert_contact(conn, display_name="A")
        b = data.upsert_contact(conn, display_name="B")
        data.add_identity(
            conn, contact_id=a["id"], kind="email",
            value="x@example.com", source_id="src1",
        )
        data.add_identity(
            conn, contact_id=b["id"], kind="email",
            value="x@example.com", source_id="src2",
        )
        conflict = data.list_open_conflicts(conn)[0]
        result = data.resolve_identity_conflict(
            conn,
            conflict["id"],
            resolution=f"merged_into:{a['id']}",
            actor="human:dartagnan",
        )
        assert result["resolution"] == f"merged_into:{a['id']}"
        # b should be gone.
        assert data.get_contact(conn, b["id"]) is None
        # No more open conflicts on a.
        assert data.get_contact(conn, a["id"])["hasOpenConflict"] is False


def test_merge_rejects_agent_actor():
    with data.connect() as conn:
        a = data.upsert_contact(conn, display_name="A")
        b = data.upsert_contact(conn, display_name="B")
        with pytest.raises(PermissionError):
            data.merge_contacts(
                conn, primary_id=a["id"], duplicate_id=b["id"],
                actor="agent:claude",
            )


def test_conversation_get_or_create_is_idempotent():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv1 = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="apple-messages",
            channel="imessage", thread_key="thread-A",
        )
        cv2 = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="apple-messages",
            channel="imessage", thread_key="thread-A",
        )
        assert cv1["id"] == cv2["id"]


def test_inbound_outbound_events_and_counters():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="lofty-default",
            channel="email", thread_key="thr-1",
        )
        data.record_inbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="Hi, can we chat?",
            source_id="lofty-default", thread_key="thr-1",
            ts="2026-05-05T10:00:00+00:00",
        )
        data.bump_conversation_counters(
            conn, cv["id"], direction="inbound",
            ts="2026-05-05T10:00:00+00:00",
        )
        data.record_outbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body="Sure — when works?",
            source_id="lofty-default", thread_key="thr-1",
            ts="2026-05-05T10:05:00+00:00",
        )
        data.bump_conversation_counters(
            conn, cv["id"], direction="outbound",
            ts="2026-05-05T10:05:00+00:00",
        )
        cv_after = data.get_conversation(conn, cv["id"])
        assert cv_after["inboundCount"] == 1
        assert cv_after["outboundCount"] == 1
        # last_activity_at on contact bumped by event recorders
        assert data.get_contact(conn, c["id"])["lastActivityAt"] == "2026-05-05T10:05:00+00:00"


def test_template_propose_then_human_approve():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        proposed = data.propose_template(
            conn,
            lane="new-outreach",
            name="AI test 1",
            body="Hey {first_name}, saw you on {source}.",
            origin="ai_pattern",
            rationale="3 of 5 high-reply templates open with 'saw you'",
            actor="agent:claude",
            seed_event_contact_id=c["id"],
        )
        assert proposed["status"] == "proposed"
        # Agent cannot self-approve.
        with pytest.raises(PermissionError):
            data.approve_template(
                conn, proposed["id"], actor="agent:claude",
            )
        # Human approves.
        approved = data.approve_template(
            conn, proposed["id"], actor="human:dartagnan",
            seed_event_contact_id=c["id"],
        )
        assert approved["status"] == "live"
        assert approved["approvedBy"] == "human:dartagnan"


def test_template_edit_bumps_version_and_supersedes():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        proposed = data.propose_template(
            conn, lane="new-outreach", name="Edit test",
            body="v1 body", origin="ai_oneoff",
            actor="agent:claude", seed_event_contact_id=c["id"],
        )
        live = data.approve_template(
            conn, proposed["id"], actor="human:d",
        )
        # Agent edit → must reject.
        with pytest.raises(PermissionError):
            data.edit_template(
                conn, live["id"], new_body="v2 body", actor="agent:claude",
            )
        # Human edit → bumps version.
        v2 = data.edit_template(
            conn, live["id"], new_body="v2 body", actor="human:d",
        )
        assert v2["version"] == live["version"] + 1
        assert v2["body"] == "v2 body"
        assert v2["status"] == "live"
        old = data.get_template(conn, live["id"])
        assert old["status"] == "superseded"


def test_template_stats_distinguish_confident_and_ambiguous():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="lofty-default",
            channel="email", thread_key="thr-stats",
        )
        proposed = data.propose_template(
            conn, lane="new-outreach", name="stats", body="hi",
            origin="ai_oneoff", actor="agent:claude",
            seed_event_contact_id=c["id"],
        )
        live = data.approve_template(
            conn, proposed["id"], actor="human:d",
        )
        data.record_template_use(conn, live["id"])
        data.record_template_reply(conn, live["id"], confident=True)
        # Ambiguous reply should NOT count in confident stats.
        data.record_attribution_ambiguous(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            candidate_template_ids=[live["id"], "other"],
            reason="multiple_outbound_in_window",
        )
        stats = data.template_stats(conn, live["id"])
        ext = data.template_stats_with_ambiguous(conn, live["id"])
        assert stats["winsConfident"] == 1
        assert stats["uses"] == 1
        assert ext["ambiguousReplies"] == 1


def test_lead_signal_graduate_emits_lifecycle_event():
    with data.connect() as conn:
        signal = data.upsert_lead_signal(
            conn,
            source_id="mls-private-search",
            source_native_id="mls-deadbeef",
            payload={"score": 92, "tier": "hot"},
            email="cold-lead@example.com",
            last_activity_at="2026-05-04T00:00:00+00:00",
        )
        # Re-upsert with newer activity should bump last_activity_at.
        signal2 = data.upsert_lead_signal(
            conn,
            source_id="mls-private-search",
            source_native_id="mls-deadbeef",
            payload={"score": 95, "tier": "hot"},
            email="cold-lead@example.com",
            last_activity_at="2026-05-05T00:00:00+00:00",
        )
        assert signal["id"] == signal2["id"]
        assert signal2["lastActivityAt"] == "2026-05-05T00:00:00+00:00"
        # Graduate
        contact = data.upsert_contact(
            conn, display_name="Graduated", primary_email="cold-lead@example.com"
        )
        result = data.graduate_lead_signal(
            conn, signal["id"], contact_id=contact["id"], actor="human:d"
        )
        assert result["graduatedToContactId"] == contact["id"]


def test_parity_records_match_and_diff():
    with data.connect() as conn:
        # Match
        data.record_parity_snapshot(
            conn,
            endpoint="/api/source-inbox",
            request_args={"limit": 50},
            jsonl_response={"items": [{"id": "a"}, {"id": "b"}]},
            db_response={"items": [{"id": "a"}, {"id": "b"}]},
        )
        # Diff
        data.record_parity_snapshot(
            conn,
            endpoint="/api/source-inbox",
            request_args={"limit": 50},
            jsonl_response={"items": [{"id": "a"}]},
            db_response={"items": []},
        )
        assert data.parity_total_count(conn) == 2
        assert data.parity_diff_count(conn) == 1
        diffs = data.recent_diffs(conn, limit=5)
        assert len(diffs) == 1
        assert diffs[0]["endpoint"] == "/api/source-inbox"


def test_classify_park_unpark_emit_events():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="C")
        data.classify_contact(conn, c["id"], "buyer", actor="human:d")
        data.park_contact(conn, c["id"], "no budget", actor="human:d")
        c_parked = data.get_contact(conn, c["id"])
        assert c_parked["stage"] == "parked"
        assert c_parked["parkedReason"] == "no budget"
        data.unpark_contact(conn, c["id"], actor="human:d")
        c_active = data.get_contact(conn, c["id"])
        assert c_active["stage"] == "active"
        assert c_active["parkedReason"] is None


def test_rollback_ingest_run_removes_only_its_rows():
    with data.connect() as conn:
        run_a = data.record_ingest_run_started(conn, "lofty-default")
        run_b = data.record_ingest_run_started(conn, "apple-messages")
        ca = data.upsert_contact(
            conn, display_name="A", source_key="lofty-lead:1",
            ingest_run_id=run_a["id"],
        )
        cb = data.upsert_contact(
            conn, display_name="B", source_key="apple-handle:+15555550100",
            ingest_run_id=run_b["id"],
        )
        data.record_ingest_marker(
            conn, kind="ingest_run_started",
            ingest_run_id=run_a["id"], source_id="lofty-default",
            contact_id=ca["id"],
        )
        data.record_ingest_marker(
            conn, kind="ingest_run_started",
            ingest_run_id=run_b["id"], source_id="apple-messages",
            contact_id=cb["id"],
        )

        counts = data.rollback_ingest_run(conn, run_a["id"], actor="human:d")
        assert counts["contacts"] == 1
        # cb still here.
        assert data.get_contact(conn, cb["id"]) is not None
        assert data.get_contact(conn, ca["id"]) is None


def test_payload_spillover_for_oversize_event():
    with data.connect() as conn:
        c = data.upsert_contact(conn, display_name="Big")
        cv = data.get_or_create_conversation(
            conn, contact_id=c["id"], source_id="email",
            channel="email", thread_key="big-thread",
        )
        # ~20KB body → should spill to filesystem
        big_body = "x" * 20000
        data.record_inbound(
            conn, contact_id=c["id"], conversation_id=cv["id"],
            channel="email", body=big_body,
            source_id="email", thread_key="big-thread",
            ts="2026-05-05T10:00:00+00:00",
        )
        row = conn.execute(
            "SELECT payload_json, payload_ref FROM events WHERE contact_id=?",
            (c["id"],),
        ).fetchone()
        assert row["payload_ref"] is not None
        # The inline payload is the small "_spilled" stub.
        assert "_spilled" in row["payload_json"]
