"""Sprint 2 tests — DB-derived response builders + cutover flip flag.

The shadow-read wrapper executes both legacy and db read paths during
Sprint 2 and writes a parity snapshot. ``ELEVATE_DATA_PRIMARY=db`` is
the cutover knob that flips reads onto the data module after a clean
parity window. ``ELEVATE_DATA_FALLBACK=jsonl`` is the rollback knob.

What the suite checks:

1. ``db_source_inbox_response`` — returns the same top-level keys as
   the legacy builder, with empty lists / zero counters on a fresh DB.
2. ``db_source_inbox_response`` populates threads/messages/contacts
   counters once rows are written through the data module.
3. ``db_thread_context_response`` raises ValueError on an unknown
   source (matches legacy 404 contract).
4. ``db_thread_context_response`` aggregates messages, lead detail,
   and lifecycle activity for a known thread.
5. ``shadow_read`` with primary=jsonl returns legacy result.
6. ``shadow_read`` with primary=db returns db result.
7. ``shadow_read`` with primary=db + fallback=jsonl + db_fn raises
   re-asserts legacy without surfacing the error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elevate_cli.data import (
    bump_conversation_counters,
    connect,
    db_source_inbox_response,
    db_thread_context_response,
    get_or_create_conversation,
    record_inbound,
    record_outbound,
    set_heat,
    shadow_read,
    upsert_contact,
)
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.source_connectors import get_source_root_info


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _source_root() -> Path:
    return Path(get_source_root_info(None)["sourceRoot"])


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


@pytest.fixture
def primary_db(monkeypatch):
    monkeypatch.setenv("ELEVATE_DATA_PRIMARY", "db")


@pytest.fixture
def primary_jsonl(monkeypatch):
    monkeypatch.delenv("ELEVATE_DATA_PRIMARY", raising=False)


@pytest.fixture
def shadow_off(monkeypatch):
    monkeypatch.delenv("ELEVATE_DATA_SHADOW_READ", raising=False)


@pytest.fixture
def shadow_on(monkeypatch):
    monkeypatch.setenv("ELEVATE_DATA_SHADOW_READ", "1")


# ─── reads.db_source_inbox_response ────────────────────────────────────


def test_source_inbox_empty_db_has_correct_shape():
    """A fresh DB should produce a valid empty inbox response — same
    top-level keys as the legacy builder, zero counters, empty lists."""
    response = db_source_inbox_response(limit=16)

    # Top-level keys match the legacy contract.
    for key in (
        "toolsRoot", "toolsRootSource", "toolsRootIo", "sourceRoot",
        "limit", "recordCounts", "hiddenCounts", "sources", "profiles",
        "threads", "drafts", "skippedDrafts", "privateSearchBuyers",
    ):
        assert key in response, f"missing top-level key {key!r}"

    assert response["limit"] == 16
    assert response["threads"] == []
    assert response["drafts"] == []
    assert response["skippedDrafts"] == []
    assert response["privateSearchBuyers"] == []
    counts = response["recordCounts"]
    assert counts["sources"] == 0
    assert counts["threads"] == 0
    assert counts["messages"] == 0
    assert counts["conversations"] == 0
    assert counts["contacts"] == 0
    assert counts["hotThreads"] == 0
    assert counts["drafts"] == 0


def test_source_inbox_includes_populated_threads():
    """Once we write a contact + conversation + inbound message via the
    data module, the inbox response should surface a thread row with
    the right counts."""
    with connect() as conn:
        contact = upsert_contact(
            conn,
            display_name="Jane Buyer",
            primary_email="jane@example.com",
            source_key="lofty:c-1",
        )
        conv = get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id="apple-messages",
            channel="imessage",
            thread_key="t-1",
        )
        record_inbound(
            conn,
            contact_id=contact["id"],
            conversation_id=conv["id"],
            channel="imessage",
            body="hey are you free this week?",
            source_id="apple-messages",
            thread_key="t-1",
            ts="2026-05-01T10:00:00+00:00",
        )
        bump_conversation_counters(
            conn, conv["id"], direction="inbound",
            ts="2026-05-01T10:00:00+00:00",
        )
        set_heat(conn, conv["id"], score=85, label="hot")

    response = db_source_inbox_response(limit=16)
    threads = response["threads"]
    assert len(threads) == 1
    t = threads[0]
    assert t["sourceId"] == "apple-messages"
    assert t["threadId"] == "t-1"
    assert t["personName"] == "Jane Buyer"
    assert t["channel"] == "imessage"
    assert t["latestText"] == "hey are you free this week?"
    assert t["heatLabel"] == "hot"
    assert t["heatScore"] == 85
    assert t["inboundCount"] == 1
    assert t["outboundCount"] == 0
    assert t["messageCount"] == 1
    assert t["direction"] == "inbound"

    counts = response["recordCounts"]
    assert counts["threads"] == 1
    assert counts["messages"] == 1
    assert counts["conversations"] == 1
    assert counts["contacts"] == 1
    assert counts["hotThreads"] == 1
    assert counts["sources"] == 1
    assert counts["people"] == 1
    assert counts["conversationPeople"] == 1
    assert response["profiles"][0]["displayName"] == "Jane Buyer"
    assert response["profiles"][0]["emails"] == ["jane@example.com"]


def test_source_inbox_includes_private_search_buyers():
    _write_jsonl(
        _source_root() / "mls-private-search" / "buyers.jsonl",
        [
            {"id": "buyer-low", "score": 42, "days": 1},
            {"id": "buyer-hot", "score": 95, "days": 3},
        ],
    )

    response = db_source_inbox_response(limit=16)

    assert [buyer["id"] for buyer in response["privateSearchBuyers"]] == [
        "buyer-hot",
        "buyer-low",
    ]


def test_source_inbox_includes_dynamic_composio_sources():
    _write_jsonl(
        _source_root() / "composio-gmail" / "messages.jsonl",
        [{"id": "m1", "text": "hello"}],
    )
    with connect() as conn:
        contact = upsert_contact(
            conn,
            display_name="Gmail Lead",
            primary_email="gmail@example.com",
            source_key="composio-gmail:g-1",
        )
        conv = get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id="composio-gmail",
            channel="email",
            thread_key="gmail-thread-1",
        )
        record_inbound(
            conn,
            contact_id=contact["id"],
            conversation_id=conv["id"],
            channel="email",
            body="thinking about buying soon",
            source_id="composio-gmail",
            thread_key="gmail-thread-1",
            ts="2026-05-01T11:00:00+00:00",
        )
        bump_conversation_counters(
            conn, conv["id"], direction="inbound",
            ts="2026-05-01T11:00:00+00:00",
        )

    response = db_source_inbox_response(limit=16)

    assert any(source["id"] == "composio-gmail" for source in response["sources"])
    thread = response["threads"][0]
    assert thread["sourceId"] == "composio-gmail"
    assert thread["sourceLabel"] == "Composio — gmail"


def test_source_inbox_excludes_done_and_archived():
    """Conversations with status != 'open' don't appear in the threads
    list. The legacy builder does the same via ui-state.json."""
    with connect() as conn:
        contact = upsert_contact(
            conn, display_name="Old Lead", source_key="crm:c-2"
        )
        conv = get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id="crm",
            channel="crm",
            thread_key="archived-1",
        )
        # Force status='archived' so the open-only WHERE filters it out.
        conn.execute(
            "UPDATE conversations SET status='archived' WHERE id=?",
            (conv["id"],),
        )

    response = db_source_inbox_response(limit=16)
    assert response["threads"] == []


def test_source_inbox_respects_limit():
    """``limit`` clamps the visible threads. The DB walk pulls 4x the
    limit but the response only returns the top N."""
    with connect() as conn:
        for i in range(5):
            contact = upsert_contact(
                conn,
                display_name=f"Lead {i}",
                source_key=f"lofty:c-{i}",
            )
            get_or_create_conversation(
                conn,
                contact_id=contact["id"],
                source_id="crm",
                channel="crm",
                thread_key=f"t-{i}",
            )

    response = db_source_inbox_response(limit=3)
    # ``threads`` is sliced to ``limit`` for display; ``recordCounts.threads``
    # carries the total walked count — the legacy builder does the same so
    # the dashboard total reflects everything actionable, not just the
    # visible page. (legacy: source_connectors.py:1938-1939)
    assert len(response["threads"]) == 3
    assert response["recordCounts"]["threads"] == 5


# ─── reads.db_thread_context_response ──────────────────────────────────


def test_thread_context_unknown_source_raises_value_error():
    """Mirrors the legacy 404 contract — the web layer turns ValueError
    into HTTPException(404)."""
    with pytest.raises(ValueError, match="Unknown source connector"):
        db_thread_context_response(
            "does-not-exist", "any-thread", limit=200,
        )


def test_thread_context_empty_thread_returns_stub_shape():
    """For a known source but unknown thread, the response should still
    have the canonical shape — no messages, no lead, but valid keys."""
    response = db_thread_context_response(
        "apple-messages", "no-such-thread", limit=200,
    )
    for key in (
        "sourceId", "threadId", "source", "personName", "messageCount",
        "messages", "lastInboundAt", "lastOutboundAt", "pendingDraft",
        "sends", "meta", "lead", "notes", "tasks", "activity",
    ):
        assert key in response, f"missing top-level key {key!r}"

    assert response["sourceId"] == "apple-messages"
    assert response["threadId"] == "no-such-thread"
    assert response["messages"] == []
    assert response["messageCount"] == 0
    assert response["lead"] is None
    assert response["activity"] == []
    assert response["tasks"] == []
    assert response["sends"] == []
    assert response["meta"] is None
    assert response["pendingDraft"] is None
    assert response["personName"] == "Client"


def test_thread_context_aggregates_messages_and_lead():
    """Messages + contact + last activity all funnel into the response."""
    with connect() as conn:
        contact = upsert_contact(
            conn,
            display_name="Tom Seller",
            primary_email="tom@example.com",
            primary_phone="+15555550100",
            source_key="lofty:c-9",
        )
        conv = get_or_create_conversation(
            conn,
            contact_id=contact["id"],
            source_id="email",
            channel="email",
            thread_key="thread-9",
        )
        record_inbound(
            conn,
            contact_id=contact["id"],
            conversation_id=conv["id"],
            channel="email",
            body="ready to list when you are",
            source_id="email",
            thread_key="thread-9",
            ts="2026-05-02T09:00:00+00:00",
        )
        bump_conversation_counters(
            conn, conv["id"], direction="inbound",
            ts="2026-05-02T09:00:00+00:00",
        )
        record_outbound(
            conn,
            contact_id=contact["id"],
            conversation_id=conv["id"],
            channel="email",
            body="great — sending the listing agreement now",
            source_id="email",
            thread_key="thread-9",
            ts="2026-05-02T09:30:00+00:00",
        )
        bump_conversation_counters(
            conn, conv["id"], direction="outbound",
            ts="2026-05-02T09:30:00+00:00",
        )
    _write_jsonl(
        _source_root() / "email" / "lead-events.jsonl",
        [
            {
                "source_record_id": "note-1",
                "contact_id": "thread-9",
                "type": "lofty_note",
                "title": "Seller note",
                "summary": "Needs pricing confidence.",
                "author": "Lofty",
                "timestamp": "2026-05-02T10:00:00+00:00",
            },
            {
                "source_record_id": "task-1",
                "contact_id": "thread-9",
                "type": "lofty_task",
                "title": "Send CMA",
                "summary": "Prepare pricing package.",
                "status": "open",
                "dueAt": "2026-05-03T10:00:00+00:00",
                "timestamp": "2026-05-02T10:15:00+00:00",
            },
            {
                "source_record_id": "activity-1",
                "contact_id": "thread-9",
                "type": "lofty_activity",
                "title": "Viewed listing report",
                "summary": "Opened CMA email.",
                "timestamp": "2026-05-02T10:30:00+00:00",
            },
        ],
    )

    response = db_thread_context_response(
        "email", "thread-9", limit=200,
    )
    assert response["personName"] == "Tom Seller"
    assert response["messageCount"] == 2
    bodies = [m["text"] for m in response["messages"]]
    assert bodies == [
        "ready to list when you are",
        "great — sending the listing agreement now",
    ]
    directions = [m["direction"] for m in response["messages"]]
    assert directions == ["inbound", "outbound"]

    lead = response["lead"]
    assert lead is not None
    assert lead["displayName"] == "Tom Seller"
    assert lead["emails"] == ["tom@example.com"]
    assert lead["phones"] == ["+15555550100"]
    assert lead["channel"] == "email"

    assert response["lastInboundAt"] == "2026-05-02T09:00:00+00:00"
    assert response["lastOutboundAt"] == "2026-05-02T09:30:00+00:00"
    assert response["notes"][0]["title"] == "Seller note"
    assert response["tasks"][0]["title"] == "Send CMA"
    assert response["activity"][0]["title"] == "Viewed listing report"


# ─── shadow_read flip flag (ELEVATE_DATA_PRIMARY) ──────────────────────


def _legacy():
    return {"source": "legacy"}


def _db():
    return {"source": "db"}


def test_shadow_off_primary_jsonl_returns_legacy(shadow_off, primary_jsonl):
    out = shadow_read(
        endpoint="GET /x", request_args={},
        jsonl_fn=_legacy, db_fn=_db,
    )
    assert out == {"source": "legacy"}


def test_shadow_off_primary_db_returns_db(shadow_off, primary_db):
    """Cutover knob: with shadow off and primary=db, the wrapper should
    skip legacy entirely and return the db result."""
    legacy_called = []

    def legacy_with_marker():
        legacy_called.append(True)
        return _legacy()

    out = shadow_read(
        endpoint="GET /x", request_args={},
        jsonl_fn=legacy_with_marker, db_fn=_db,
    )
    assert out == {"source": "db"}
    assert legacy_called == []  # legacy was not invoked


def test_shadow_on_primary_jsonl_records_parity_returns_legacy(shadow_on, primary_jsonl):
    out = shadow_read(
        endpoint="GET /x", request_args={},
        jsonl_fn=_legacy, db_fn=_db,
    )
    # Differing responses — wrapper still returns legacy.
    assert out == {"source": "legacy"}
    # And a parity snapshot was recorded.
    from elevate_cli.data import parity_total_count
    with connect() as conn:
        assert parity_total_count(conn) == 1


def test_shadow_on_primary_db_records_parity_returns_db(shadow_on, primary_db):
    out = shadow_read(
        endpoint="GET /x", request_args={},
        jsonl_fn=_legacy, db_fn=_db,
    )
    assert out == {"source": "db"}
    from elevate_cli.data import parity_total_count
    with connect() as conn:
        assert parity_total_count(conn) == 1


def test_primary_db_fallback_jsonl_swallows_db_error(monkeypatch, shadow_off):
    """Emergency rollback knob: when primary=db and db_fn raises,
    ELEVATE_DATA_FALLBACK=jsonl re-asserts legacy without restart."""
    monkeypatch.setenv("ELEVATE_DATA_PRIMARY", "db")
    monkeypatch.setenv("ELEVATE_DATA_FALLBACK", "jsonl")

    def boom():
        raise RuntimeError("db side broken")

    out = shadow_read(
        endpoint="GET /x", request_args={},
        jsonl_fn=_legacy, db_fn=boom,
    )
    assert out == {"source": "legacy"}


def test_primary_db_no_fallback_propagates_db_error(monkeypatch, shadow_off):
    """Without the fallback flag, the db_fn error surfaces — operators
    decide whether to flip the flag or roll back the primary."""
    monkeypatch.setenv("ELEVATE_DATA_PRIMARY", "db")
    monkeypatch.delenv("ELEVATE_DATA_FALLBACK", raising=False)

    def boom():
        raise RuntimeError("db side broken")

    with pytest.raises(RuntimeError, match="db side broken"):
        shadow_read(
            endpoint="GET /x", request_args={},
            jsonl_fn=_legacy, db_fn=boom,
        )
