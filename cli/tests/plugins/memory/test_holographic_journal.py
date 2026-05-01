"""Tests for the holographic memory turn journal."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from elevate_cli.memory_maintenance import (
    organize_holographic_journal,
    run_due_daily_memory_maintenance,
)
from plugins.memory.holographic import HolographicMemoryProvider


def _provider(tmp_path, **overrides):
    config = {
        "db_path": str(tmp_path / "memory.db"),
        "embedding_enabled": "false",
        "turn_journal_enabled": "true",
        "organize_on_session_end": "false",
        "organize_every_n_turns": "0",
    }
    config.update(overrides)
    provider = HolographicMemoryProvider(config=config)
    provider.initialize("session-1")
    return provider


def _tool(provider, args):
    return json.loads(provider.handle_tool_call("fact_store", args))


def _facts(provider, limit=200):
    return _tool(provider, {"action": "list", "limit": limit})["facts"]


def _runtime_config(tmp_path, **overrides):
    plugin_config = {
        "db_path": str(tmp_path / "memory.db"),
        "embedding_enabled": "false",
        "turn_journal_enabled": "true",
        "organize_on_session_end": "false",
        "organize_every_n_turns": "0",
        "organize_batch_limit": "2",
        "daily_organize_enabled": "true",
        "daily_organize_hour": "23",
        "daily_organize_minute": "55",
        "daily_organize_max_batches": "10",
    }
    plugin_config.update(overrides)
    return {
        "memory": {"provider": "holographic"},
        "plugins": {"elevate-memory-store": plugin_config},
        "timezone": "UTC",
    }


def test_sync_turn_records_pending_journal_without_fact(tmp_path):
    provider = _provider(tmp_path)

    provider.sync_turn(
        "Remember this: Skyleigh Elevate uses Telegram for quick testing.",
        "Saved.",
        session_id="telegram-1",
    )

    status = _tool(provider, {"action": "journal_status", "session_id": "telegram-1"})
    assert status["total"] == 1
    assert status["pending"] == 1
    assert status["processed"] == 0
    assert _facts(provider) == []


def test_organize_journal_promotes_explicit_memory(tmp_path):
    provider = _provider(tmp_path)
    provider.sync_turn(
        "Remember this: Skyleigh Elevate uses Telegram for quick testing.",
        "Saved.",
        session_id="telegram-1",
    )

    result = _tool(provider, {
        "action": "organize_journal",
        "session_id": "telegram-1",
    })

    assert result["processed"] == 1
    assert result["promoted"] == 1
    assert result["pending"] == 0
    facts = _facts(provider)
    assert len(facts) == 1
    assert facts[0]["content"] == "Skyleigh Elevate uses Telegram for quick testing"


def test_organize_every_n_turns_promotes_after_completed_turn(tmp_path):
    provider = _provider(tmp_path, organize_every_n_turns="1")

    provider.sync_turn(
        "We decided to keep the Elevate memory journal local.",
        "Got it.",
        session_id="cli-1",
    )

    status = _tool(provider, {"action": "journal_status", "session_id": "cli-1"})
    assert status["pending"] == 0
    facts = _facts(provider)
    assert len(facts) == 1
    assert "memory journal local" in facts[0]["content"]
    assert facts[0]["category"] == "project"


def test_duplicate_turn_is_idempotent(tmp_path):
    provider = _provider(tmp_path)
    user = "Remember this: Elevate Agent memory facts should stay local."
    assistant = "Saved."

    provider.sync_turn(user, assistant, session_id="cli-1")
    provider.sync_turn(user, assistant, session_id="cli-1")

    status = _tool(provider, {"action": "journal_status", "session_id": "cli-1"})
    assert status["total"] == 1
    assert status["pending"] == 1

    first = _tool(provider, {"action": "organize_journal", "session_id": "cli-1"})
    second = _tool(provider, {"action": "organize_journal", "session_id": "cli-1"})

    assert first["processed"] == 1
    assert first["promoted"] == 1
    assert second["processed"] == 0
    assert len(_facts(provider)) == 1


def test_journal_status_segments_sessions_by_day(tmp_path):
    provider = _provider(tmp_path)
    store = provider._store

    store.record_turn(
        "telegram-a",
        "Remember this: Session A started on April 30.",
        "Saved.",
        session_day="2026-04-30",
        created_at="2026-04-30 23:50:00",
    )
    store.record_turn(
        "telegram-a",
        "Remember this: Session A continued on May 1.",
        "Saved.",
        session_day="2026-05-01",
        created_at="2026-05-01 00:10:00",
    )
    store.record_turn(
        "cli-b",
        "Remember this: CLI session B is separate.",
        "Saved.",
        session_day="2026-04-30",
        created_at="2026-04-30 18:00:00",
    )

    status = _tool(provider, {"action": "journal_status"})
    assert status["total"] == 3
    assert status["pending"] == 3
    assert status["active_session_count"] == 2
    assert status["session_segment_count"] == 3
    assert {
        (entry["session_id"], entry["session_day"])
        for entry in status["sessions"]
    } == {
        ("telegram-a", "2026-04-30"),
        ("telegram-a", "2026-05-01"),
        ("cli-b", "2026-04-30"),
    }

    session_status = _tool(provider, {
        "action": "journal_status",
        "session_id": "telegram-a",
    })
    assert session_status["total"] == 2
    assert session_status["active_session_count"] == 1
    assert session_status["session_segment_count"] == 2

    day_status = _tool(provider, {
        "action": "journal_status",
        "session_day": "2026-05-01",
    })
    assert day_status["total"] == 1
    assert day_status["sessions"][0]["session_id"] == "telegram-a"


def test_concurrent_session_writes_and_organization(tmp_path):
    provider = _provider(tmp_path)
    total_turns = 64

    def write_turn(i):
        session_id = f"telegram-{i % 4}"
        provider.sync_turn(
            f"Remember this: stress fact {i} belongs to {session_id}.",
            "Saved.",
            session_id=session_id,
        )
        return i

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_turn, i) for i in range(total_turns)]
        assert sorted(f.result() for f in as_completed(futures)) == list(range(total_turns))

    status = _tool(provider, {"action": "journal_status"})
    assert status["total"] == total_turns
    assert status["pending"] == total_turns
    assert status["active_session_count"] == 4
    assert {entry["session_id"] for entry in status["sessions"]} == {
        "telegram-0",
        "telegram-1",
        "telegram-2",
        "telegram-3",
    }

    result = _tool(provider, {"action": "organize_journal", "limit": total_turns})
    assert result["processed"] == total_turns
    assert result["promoted"] == total_turns
    assert result["pending"] == 0

    final_status = _tool(provider, {"action": "journal_status"})
    assert final_status["pending"] == 0
    assert final_status["processed"] == total_turns
    assert len(_facts(provider)) == total_turns


def test_maintenance_organize_can_drain_multiple_batches(tmp_path):
    config = _runtime_config(tmp_path, organize_batch_limit="2")
    provider = HolographicMemoryProvider(config=config["plugins"]["elevate-memory-store"])
    provider.initialize("session-1")
    for i in range(5):
        provider.sync_turn(
            f"Remember this: daily drain fact {i} should be durable.",
            "Saved.",
            session_id="long-session",
        )
    provider.shutdown()

    result = organize_holographic_journal(config=config, drain=True)

    assert result["ran"] is True
    assert result["processed"] == 5
    assert result["promoted"] == 5
    assert result["pending"] == 0
    assert result["batches"] == 3


def test_daily_maintenance_runs_once_for_target_day(tmp_path):
    config = _runtime_config(tmp_path, organize_batch_limit="1")
    provider = HolographicMemoryProvider(config=config["plugins"]["elevate-memory-store"])
    provider.initialize("session-1")
    provider.sync_turn(
        "Remember this: daily maintenance does not require the session to end.",
        "Saved.",
        session_id="telegram-open-session",
    )
    provider.shutdown()

    now = datetime(2026, 5, 1, 0, 5, tzinfo=timezone.utc)
    first = run_due_daily_memory_maintenance(
        config=config,
        now=now,
        elevate_home=tmp_path,
    )
    second = run_due_daily_memory_maintenance(
        config=config,
        now=now,
        elevate_home=tmp_path,
    )

    assert first["ran"] is True
    assert first["target_day"] == "2026-04-30"
    assert first["processed"] == 1
    assert first["pending"] == 0
    assert second["ran"] is False
    assert "already ran" in second["reason"]
    assert (tmp_path / "memory_daily_state.json").exists()


def test_recent_action_is_scoped_to_session(tmp_path):
    provider = _provider(tmp_path)
    provider.sync_turn(
        "Remember this: Telegram session needs fast recent recall.",
        "Saved.",
        session_id="telegram-1",
    )
    provider.sync_turn(
        "Remember this: CLI session is a separate memory lane.",
        "Saved.",
        session_id="cli-1",
    )

    result = _tool(provider, {
        "action": "recent",
        "session_id": "telegram-1",
        "query": "recent recall",
        "limit": 5,
    })

    assert result["count"] == 1
    assert result["turns"][0]["session_id"] == "telegram-1"
    assert "Telegram session" in result["turns"][0]["user_content"]
    assert "assistant_content" not in result["turns"][0]


def test_entity_wiki_returns_facts_and_backlinks(tmp_path):
    provider = _provider(tmp_path)
    provider._store.add_fact(
        "Skyleigh Elevate uses Telegram Gateway for agent messages.",
        category="project",
    )
    provider._store.add_fact(
        "Telegram Gateway routes Skyleigh Elevate replies to approved users.",
        category="tool",
    )

    wiki = _tool(provider, {"action": "wiki", "entity": "Skyleigh Elevate"})

    assert wiki["exists"] is True
    assert wiki["wiki_link"] == "[[Skyleigh Elevate]]"
    assert len(wiki["facts"]) == 2
    assert any(
        rel["wiki_link"] == "[[Telegram Gateway]]"
        for rel in wiki["related_entities"]
    )


def test_layered_prefetch_includes_recent_durable_and_graph(tmp_path):
    provider = _provider(tmp_path, durable_recall_limit="3", graph_recall_limit="2")
    provider.sync_turn(
        "Remember this: Skyleigh Elevate memory should use recent session recall.",
        "Saved.",
        session_id="telegram-1",
    )
    provider._store.add_fact(
        "Skyleigh Elevate uses Telegram Gateway for approved user messages.",
        category="project",
    )
    provider._store.add_fact(
        "Telegram Gateway is connected to Skyleigh Elevate.",
        category="tool",
    )

    context = provider.prefetch(
        "How does Skyleigh Elevate use Telegram Gateway memory?",
        session_id="telegram-1",
    )

    assert "## Elevate Memory Core" in context
    assert "### Recent Session" in context
    assert "### Durable + Semantic" in context
    assert "### Graph Wiki" in context
    assert "[[Skyleigh Elevate]]" in context
    assert "recent session recall" in context


def test_layered_recall_tool_matches_prefetch_surface(tmp_path):
    provider = _provider(tmp_path)
    provider._store.add_fact(
        "Skyleigh Elevate keeps memory local before promoting semantic facts.",
        category="project",
    )

    result = _tool(provider, {
        "action": "layered_recall",
        "query": "Skyleigh Elevate semantic facts",
        "session_id": "cli-1",
    })

    assert result["empty"] is False
    assert "### Durable + Semantic" in result["context"]
