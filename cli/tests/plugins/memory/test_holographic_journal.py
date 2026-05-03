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


def _seed_rag_memory(provider):
    _tool(provider, {
        "action": "add",
        "content": "Uppercuts Barber Academy teaches chair confidence with Alex Med inside a working barbershop.",
        "category": "project",
        "source_uri": "fact://uppercuts-positioning",
    })
    _tool(provider, {
        "action": "document_add",
        "title": "Uppercuts Curriculum",
        "source_uri": "doc://uppercuts-curriculum",
        "source_type": "brief",
        "chunks": [
            "Uppercuts curriculum covers clipper control, consultations, sanitation, fading, and client handling.",
            "The Academy CTA is a form submit followed by a representative call to confirm the student's spot.",
        ],
    })
    provider.sync_turn(
        "We decided Uppercuts copy should say classes, not cohorts.",
        "Saved.",
        session_id="session-1",
    )


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


def test_rag_query_mixes_facts_documents_recent_and_graph(tmp_path):
    provider = _provider(tmp_path)
    _seed_rag_memory(provider)

    result = _tool(provider, {
        "action": "rag_query",
        "query": "What do we know about Uppercuts Barber Academy classes and curriculum?",
        "limit": 5,
    })

    assert result["mode"] == "mix"
    assert result["empty"] is False
    assert result["sections"]["facts"]
    assert result["sections"]["chunks"]
    assert result["sections"]["recent"]
    assert result["sections"]["graph"]
    assert result["citations"]
    assert "Elevate Native RAG" in result["context"]
    assert "Uppercuts" in result["context"]
    assert result["raw_data"]["telemetry"]["counts"]["chunks"] >= 1
    assert result["keywords"]["low_level"]
    events = _tool(provider, {"action": "memory_events", "limit": 5})["events"]
    assert any(event["event"] == "memory.rag_query.complete" for event in events)


def test_relation_backfill_and_document_search_diversity(tmp_path):
    provider = _provider(tmp_path)
    _tool(provider, {
        "action": "document_add",
        "title": "Doc One",
        "source_uri": "doc://one",
        "source_type": "brief",
        "chunks": [
            "Alex Med teaches Uppercuts Barber Academy chair practice and student confidence.",
            "Alex Med and Uppercuts Barber Academy repeat chair practice for confidence drills.",
            "Alex Med runs Uppercuts Barber Academy curriculum checks with students.",
        ],
    })
    _tool(provider, {
        "action": "document_add",
        "title": "Doc Two",
        "source_uri": "doc://two",
        "source_type": "brief",
        "chunks": ["Uppercuts Barber Academy has pricing, curriculum, and launch planning notes."],
    })

    backfill = _tool(provider, {"action": "relation_backfill", "source_type": "brief"})
    assert backfill["chunks_processed"] == 4
    assert backfill["relations_after"] >= 1

    search = _tool(provider, {
        "action": "document_search",
        "query": "Uppercuts Barber Academy curriculum confidence",
        "source_type": "brief",
        "limit": 2,
    })["results"]
    assert len({item["document_id"] for item in search}) == 2


def test_rag_query_supports_naive_and_local_modes(tmp_path):
    provider = _provider(tmp_path)
    _seed_rag_memory(provider)

    naive = _tool(provider, {
        "action": "rag_query",
        "query": "clipper control curriculum",
        "mode": "naive",
        "limit": 3,
    })
    assert naive["mode"] == "naive"
    assert naive["sections"]["chunks"]
    assert naive["sections"]["facts"] == []
    assert naive["sections"]["graph"] == []

    local = _tool(provider, {
        "action": "rag_query",
        "query": "Uppercuts Barber Academy Alex Med",
        "mode": "local",
        "limit": 3,
    })
    assert local["mode"] == "local"
    assert local["sections"]["facts"]
    assert local["sections"]["chunks"] == []
    assert local["sections"]["graph"]


def test_lightrag_prompt_bypass_and_raganything_multimodal_query(tmp_path):
    provider = _provider(tmp_path)
    _seed_rag_memory(provider)

    multimodal = _tool(provider, {
        "action": "rag_query",
        "query": "What does the table say about curriculum confidence?",
        "mode": "mix",
        "limit": 4,
        "only_need_prompt": True,
        "response_type": "Bullet Points",
        "conversation_history": [{"role": "user", "content": "We care about Uppercuts classes."}],
        "multimodal_content": [{
            "type": "table",
            "table_caption": ["Uppercuts class outcomes"],
            "table_body": "Metric | Value\nStudent confidence | High after live chair practice",
            "page": 2,
        }],
    })
    assert multimodal["sections"]["modal_query"]
    assert multimodal["raw_data"]["telemetry"]["counts"]["modal_query"] == 1
    assert "Multimodal Query Inputs" in multimodal["prompt"]
    assert "Response type: Bullet Points" in multimodal["context"]
    assert "Conversation History" in multimodal["context"]

    bypass = _tool(provider, {
        "action": "rag_query",
        "query": "Answer without retrieval",
        "mode": "bypass",
        "only_need_prompt": True,
    })
    assert bypass["mode"] == "bypass"
    assert bypass["sections"] == {}
    assert bypass["context"].startswith("---Role---")


def test_document_status_and_delete_cover_lightrag_doc_ops(tmp_path):
    provider = _provider(tmp_path)
    added = _tool(provider, {
        "action": "document_add",
        "title": "Modal Doc",
        "source_uri": "doc://modal",
        "source_type": "brief",
        "chunks": ["Uppercuts Barber Academy table and image notes."],
        "modal_assets": [{"type": "image", "caption": "Chair practice photo", "path": "image://chair"}],
    })
    assert added["chunks"] == 2
    assert added["modal_assets"] == 1

    status = _tool(provider, {"action": "document_status", "source_type": "brief"})
    assert status["count"] == 1
    assert status["documents"][0]["status"] == "processed"
    assert status["documents"][0]["modal_assets"] == 1

    deleted = _tool(provider, {"action": "document_delete", "source_uri": "doc://modal"})
    assert deleted["status"] == "success"
    assert deleted["chunks"] == 2
    assert _tool(provider, {"action": "document_status", "source_type": "brief"})["count"] == 0


def test_community_reports_power_global_rag_mode(tmp_path):
    provider = _provider(tmp_path)
    first = _tool(provider, {
        "action": "add",
        "content": "Uppercuts Barber Academy teaches hands-on barber classes with Alex Med inside a working shop.",
        "category": "project",
        "tags": "uppercuts,barber",
    })
    second = _tool(provider, {
        "action": "add",
        "content": "Uppercuts Academy CTA is form submit followed by a representative call to confirm spot details.",
        "category": "project",
        "tags": "uppercuts,cta",
    })
    third = _tool(provider, {
        "action": "add",
        "content": "Alex Med has trained 1000 plus barber students and has a 100K plus YouTube audience.",
        "category": "project",
        "tags": "uppercuts,alex-med",
    })

    cluster = _tool(provider, {
        "action": "cluster",
        "fact_ids": [first["fact_id"], second["fact_id"], third["fact_id"]],
        "query": "Uppercuts Academy Alex Med barber classes",
    })
    assert cluster["community_report"]["built"] is True

    reports = _tool(provider, {
        "action": "community_reports",
        "query": "Uppercuts Academy barber classes",
        "limit": 3,
    })
    assert reports["count"] >= 1
    assert "Uppercuts" in reports["results"][0]["summary"]

    global_rag = _tool(provider, {
        "action": "rag_query",
        "query": "Uppercuts Academy barber classes",
        "mode": "global",
        "limit": 3,
        "max_chars": 2400,
    })
    assert global_rag["sections"]["communities"]
    assert global_rag["sections"]["facts"] == []
    assert "Community Reports" in global_rag["context"]
    assert any(c["type"] == "community" for c in global_rag["citations"])


def test_document_chunks_create_entity_links_and_relations(tmp_path):
    provider = _provider(tmp_path)
    _tool(provider, {
        "action": "document_add",
        "title": "Uppercuts RAG Brief",
        "source_uri": "doc://uppercuts-rag-brief",
        "source_type": "brief",
        "chunks": [
            "Alex Med teaches Uppercuts Barber Academy students in Kamloops with real chair practice.",
        ],
    })

    wiki = _tool(provider, {"action": "wiki", "entity": "Alex Med", "limit": 5})
    assert wiki["exists"] is True
    related = {item["entity"] for item in wiki["related_entities"]}
    assert "Uppercuts Barber Academy" in related


def test_document_add_accepts_multimodal_assets_as_rag_chunks(tmp_path):
    provider = _provider(tmp_path)
    result = _tool(provider, {
        "action": "document_add",
        "title": "Listing PDF With Table",
        "source_uri": "doc://listing-pdf-table",
        "source_type": "pdf",
        "chunks": ["Listing package overview for Sagebrush Drive."],
        "modal_assets": [
            {
                "asset_type": "table",
                "locator": "page 4",
                "summary": "Showing activity table lists 12 showings and 3 repeat buyers.",
                "text_content": "Showings: 12. Repeat buyers: 3. Feedback: price sensitive.",
            },
            {
                "asset_type": "image",
                "locator": "page 2",
                "summary": "Exterior listing photo shows strong curb appeal and clean landscaping.",
            },
        ],
    })

    assert result["modal_assets"] == 2
    search = _tool(provider, {
        "action": "document_search",
        "query": "repeat buyers showing activity table",
        "source_type": "pdf",
        "limit": 5,
    })
    assert search["count"] >= 1
    assert any("Multimodal table" in item["content"] for item in search["results"])


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


def test_retrieval_updates_usage_signal_for_ranked_facts(tmp_path):
    provider = _provider(tmp_path)
    fact_id = provider._store.add_fact(
        "Skyleigh Elevate recall should learn which durable facts are surfaced.",
        category="project",
    )

    before = provider._store.list_facts(limit=1)[0]
    assert before["retrieval_count"] == 0

    result = _tool(provider, {
        "action": "search",
        "query": "Skyleigh Elevate recall durable facts surfaced",
        "limit": 3,
    })

    assert result["count"] == 1
    assert result["results"][0]["fact_id"] == fact_id
    after = provider._store.list_facts(limit=1)[0]
    assert after["retrieval_count"] == 1


def test_source_aware_fact_fields_roundtrip(tmp_path):
    provider = _provider(tmp_path)

    result = _tool(provider, {
        "action": "add",
        "content": "Uppercuts Barber Academy CTA is form submit then representative call.",
        "category": "project",
        "source_type": "plaud",
        "source_uri": "plaud:test-cta",
        "source_excerpt": "Fill out the form. A representative will call.",
        "observed_at": "2026-05-02 12:00:00",
    })

    facts = _facts(provider)
    assert facts[0]["fact_id"] == result["fact_id"]
    assert facts[0]["source_type"] == "plaud"
    assert facts[0]["source_uri"] == "plaud:test-cta"
    assert "representative" in facts[0]["source_excerpt"]


def test_document_add_search_and_recall_route(tmp_path):
    provider = _provider(tmp_path)

    added = _tool(provider, {
        "action": "document_add",
        "source_type": "plaud",
        "source_uri": "plaud:academy-call",
        "title": "Academy Call",
        "content": "Alex Med discussed Uppercuts Barber Academy classes and real-shop barber training.",
    })
    assert added["chunks"] == 1

    search = _tool(provider, {
        "action": "document_search",
        "source_type": "plaud",
        "query": "real shop barber training Alex Med",
    })
    assert search["count"] == 1
    assert search["results"][0]["source_uri"] == "plaud:academy-call"

    routed = _tool(provider, {
        "action": "recall_route",
        "query": "What did we discuss on the Plaud call about Alex Med?",
    })
    assert "plaud" in routed["lanes"]
    assert routed["sections"]["plaud_chunks"][0]["source_uri"] == "plaud:academy-call"


def test_hygiene_reports_popular_and_source_gaps(tmp_path):
    provider = _provider(tmp_path)
    provider._store.add_fact(
        "Skyleigh Elevate memory hygiene should find source gaps.",
        category="project",
    )
    _tool(provider, {"action": "search", "query": "memory hygiene source gaps"})

    report = _tool(provider, {"action": "hygiene", "limit": 5})

    assert report["popular"]
    assert report["source_gaps"]


def test_jcode_memory_audit_replay_profile_and_supersession(tmp_path):
    provider = _provider(tmp_path)

    old = _tool(provider, {
        "action": "add",
        "content": "Old CTA is tour-first for Uppercuts.",
        "category": "project",
        "source_type": "manual",
        "memory_space": "uppercuts",
    })["fact_id"]
    new = _tool(provider, {
        "action": "add",
        "content": "Uppercuts CTA is form submit followed by representative call.",
        "category": "project",
        "source_type": "manual",
        "memory_space": "uppercuts",
    })["fact_id"]

    result = _tool(provider, {"action": "supersede", "old_fact_id": old, "new_fact_id": new})
    assert result["superseded"] is True

    context = provider.prefetch("Uppercuts CTA", session_id="telegram-a")
    assert "representative call" in context
    assert "tour-first" not in context

    replay = _tool(provider, {"action": "memory_replay", "session_id": "telegram-a"})
    assert replay["count"] >= 1
    assert replay["injections"][0]["prompt_chars"] > 0

    events = _tool(provider, {"action": "memory_events", "limit": 20})
    assert events["count"] > 0
    assert any(event["event"] in {"memory.injected", "memory.superseded"} for event in events["events"])

    profile = _tool(provider, {"action": "memory_profile", "session_id": "telegram-a"})
    assert profile["facts"] >= 1
    assert profile["memory_injections"] >= 1

    facts = _facts(provider)
    assert {fact["content"] for fact in facts} == {"Uppercuts CTA is form submit followed by representative call."}


def test_topic_extraction_is_opt_in_and_promotes_on_shift(tmp_path):
    provider = _provider(
        tmp_path,
        topic_extraction_enabled="true",
        topic_extract_min_turns="1",
        topic_change_threshold="0.9",
        organize_batch_limit="10",
    )

    provider.sync_turn("Remember this: Uppercuts classes use real shop training.", "Saved.", session_id="topic-1")
    provider.sync_turn("Google ads OAuth callback uses localhost auth flow.", "Got it.", session_id="topic-1")

    facts = _facts(provider)
    assert any("Uppercuts classes use real shop training" in fact["content"] for fact in facts)
    events = _tool(provider, {"action": "memory_events", "session_id": "topic-1", "limit": 20})
    assert any(event["event"] == "memory.topic_extract.started" for event in events["events"])


def test_repeated_prefetch_dedupes_injected_fact_within_session(tmp_path):
    provider = _provider(tmp_path)
    _tool(provider, {
        "action": "add",
        "content": "Plaud recall should use chunk-level RAG for past meeting questions.",
        "category": "project",
        "tags": "plaud,rag",
    })

    first = provider.prefetch("Plaud RAG meeting recall", session_id="telegram-dedupe")
    second = provider.prefetch("Plaud RAG meeting recall", session_id="telegram-dedupe")

    assert "chunk-level RAG" in first
    # Re-injecting the same fact every turn is what jcode avoided.
    assert "chunk-level RAG" not in second
    replay = _tool(provider, {"action": "memory_replay", "session_id": "telegram-dedupe"})
    assert replay["count"] == 1

def test_chunk_embedding_backfill_indexes_document_chunks_with_hash_backend(tmp_path):
    provider = _provider(
        tmp_path,
        embedding_enabled="true",
        embedding_provider="hash",
        embedding_model="hash-test-64",
        embedding_dimensions="64",
    )
    add = _tool(provider, {
        "action": "document_add",
        "source_uri": "plaud://test-barber-meeting",
        "source_type": "plaud",
        "title": "Test Barber Academy Meeting",
        "content": "Alex Med discussed hands-on barber academy training and viewbook marketing. Students train in a real shop.",
    })
    assert add["chunks"] >= 1

    status_before = _tool(provider, {"action": "embedding_status"})
    assert status_before["chunks"] >= 1
    assert status_before["indexed_chunks"] >= 1  # document_add embeds immediately when enabled

    # Force a clean backfill path by deleting the chunk embeddings.
    provider._store._conn.execute("DELETE FROM memory_embeddings WHERE target_type = 'chunk'")
    provider._store._conn.commit()

    result = _tool(provider, {
        "action": "chunk_embedding_backfill",
        "source_type": "plaud",
        "batch_size": 2,
    })
    assert result["enabled"] is True
    assert result["indexed"] >= 1

    status_after = _tool(provider, {"action": "embedding_status"})
    assert status_after["indexed_chunks"] == status_after["chunks"]
    assert status_after["missing_or_stale_chunks"] == 0

    rows = _tool(provider, {
        "action": "document_search",
        "source_type": "plaud",
        "query": "real shop barber training marketing",
        "limit": 3,
    })["results"]
    assert rows
    assert rows[0].get("semantic_score", 0) >= 0


def test_jcode_remaining_cluster_tag_confidence_prune_and_benchmark(tmp_path):
    provider = _provider(tmp_path)
    a = _tool(provider, {"action": "add", "content": "Uppercuts Academy uses live client practice with instructor coaching.", "category": "project", "tags": "uppercuts"})["fact_id"]
    b = _tool(provider, {"action": "add", "content": "Alex Med anchors Uppercuts Academy training and student confidence.", "category": "project"})["fact_id"]
    c = _tool(provider, {"action": "add", "content": "Old weak note that should decay out.", "category": "general"})["fact_id"]

    clustered = _tool(provider, {"action": "cluster", "fact_ids": f"{a},{b}", "query": "Uppercuts Academy instructor coaching"})
    assert clustered["clustered"] is True
    assert clustered["members"] == 2
    assert clustered["cluster_id"].startswith("cluster:")
    assert clustered["name"]

    tagged = _tool(provider, {"action": "auto_tag", "fact_ids": f"{a},{b}"})
    assert tagged["updated"] >= 1

    maintained = _tool(provider, {"action": "confidence_maintenance", "verified_ids": f"{a},{b}", "rejected_ids": str(c), "prune": "false"})
    assert maintained["boosted"] == 2
    assert maintained["decayed"] == 1

    profile = _tool(provider, {"action": "memory_profile"})
    assert profile["clusters"] >= 1
    assert profile["cluster_members"] >= 2
    assert "estimated_injection_tokens" in profile

    bench = _tool(provider, {"action": "benchmark", "queries": "Uppercuts Academy instructor coaching", "limit": 3})
    assert bench["ran"] if "ran" in bench else True
    assert bench["query_count"] == 1
    assert bench["queries"][0]["hits"] >= 1

    pruned = _tool(provider, {"action": "prune_logs", "retention_days": 1})
    assert "total_removed" in pruned


def test_post_retrieval_maintenance_creates_cluster_and_infers_tags(tmp_path):
    provider = _provider(tmp_path)
    a = _tool(provider, {"action": "add", "content": "Google Ads search campaigns use open early keywords.", "category": "project"})["fact_id"]
    b = _tool(provider, {"action": "add", "content": "Uppercuts Google Ads campaign reporting comes from Supabase.", "category": "project"})["fact_id"]
    result = provider._store.post_retrieval_maintenance(verified_ids=[a, b], rejected_ids=[], query="Google Ads campaign reporting", session_id="s1")
    assert result["cluster"]["clustered"] is True
    assert result["tags"]["updated"] >= 1
