"""Targeted tests for the bounded daily memory_relations prune + vacuum.

Covers ISSUE #6 (memory_store.db bloat from memory_relations):
  - prune is BOUNDED (per-run cap on rows deleted is respected)
  - prune is IDEMPOTENT (a second run is a no-op)
  - prune is CONSERVATIVE (rows it can't prove are dead are left alone)
  - the destructive method is UNREACHABLE from the recall/hot path
  - it only fires from the daily-gated maintenance entrypoint

All tests use a temp-file SQLite DB via the provider config — never the
live ~/.elevate/memory_store.db.
"""

from __future__ import annotations

import pytest

from plugins.memory.holographic import HolographicMemoryProvider
from plugins.memory.holographic.store import DAILY_MAINTENANCE_TOKEN


def _store(tmp_path):
    provider = HolographicMemoryProvider(
        config={
            "db_path": str(tmp_path / "memory.db"),
            "embedding_enabled": "false",
            "turn_journal_enabled": "false",
            "organize_on_session_end": "false",
            "organize_every_n_turns": "0",
        }
    )
    provider.initialize("session-1")
    return provider, provider._store


def _mk_entities(store, n):
    ids = []
    with store._lock:
        for i in range(n):
            cur = store._conn.execute(
                "INSERT INTO entities (name) VALUES (?)", (f"ent-{i}",)
            )
            ids.append(int(cur.lastrowid))
        store._conn.commit()
    return ids


def _rel_count(store):
    return int(
        store._conn.execute(
            "SELECT COUNT(*) AS c FROM memory_relations"
        ).fetchone()["c"]
    )


def _mk_real_chunk(store):
    """Insert a real document+chunk so chunk-backed relations are NOT orphans."""
    with store._lock:
        doc_id = int(
            store._conn.execute(
                "INSERT INTO memory_documents (source_uri, title) VALUES (?,?)",
                ("doc://t", "t"),
            ).lastrowid
        )
        chunk_id = int(
            store._conn.execute(
                "INSERT INTO memory_chunks "
                "(document_id, chunk_index, content) VALUES (?,?,?)",
                (doc_id, 0, "real chunk body"),
            ).lastrowid
        )
        store._conn.commit()
    return chunk_id


def test_orphan_prune_bounded_idempotent_and_no_dedup(tmp_path):
    """Only orphans are pruned. Cross-source rows are corroboration signal
    (recall ranks by SUM(weight)/COUNT(*) over all rows for a pair) so they
    must SURVIVE — dedup was removed after the Codex review (2026-05-19)."""
    provider, store = _store(tmp_path)
    try:
        e = _mk_entities(store, 4)
        real_chunk = _mk_real_chunk(store)

        with store._lock:
            # (a) 60 orphaned fact relations (source_id -> no facts row).
            for k in range(60):
                store._conn.execute(
                    "INSERT INTO memory_relations "
                    "(source_entity_id, target_entity_id, relation_type, "
                    " source_type, source_id) VALUES (?,?,?,?,?)",
                    (e[0], e[1], "co_occurs_with", "fact", 9000 + k),
                )
            # Multi-source corroboration: the SAME (e2,e3,co_occurs_with)
            # edge under 6 distinct (source_type, source_id) pairs, none
            # orphaned. This is 6-fold recall signal and must be preserved
            # in full — NOT collapsed to one row.
            store._conn.execute(
                "INSERT INTO memory_relations "
                "(source_entity_id, target_entity_id, relation_type, "
                " source_type, source_id) VALUES (?,?,?,?,?)",
                (e[2], e[3], "co_occurs_with", "chunk", real_chunk),
            )
            for k in range(5):
                store._conn.execute(
                    "INSERT INTO memory_relations "
                    "(source_entity_id, target_entity_id, relation_type, "
                    " source_type, source_id) VALUES (?,?,?,?,?)",
                    (e[2], e[3], "co_occurs_with", "manual", 7000 + k),
                )
            # CONSERVATIVE: unknown-provenance rows must NEVER be pruned.
            store._conn.execute(
                "INSERT INTO memory_relations "
                "(source_entity_id, target_entity_id, relation_type, "
                " source_type, source_id) VALUES (?,?,?,?,?)",
                (e[0], e[2], "co_occurs_with", "", 0),
            )
            store._conn.execute(
                "INSERT INTO memory_relations "
                "(source_entity_id, target_entity_id, relation_type, "
                " source_type, source_id) VALUES (?,?,?,?,?)",
                (e[1], e[3], "co_occurs_with", "fact", 0),
            )
            store._conn.commit()

        total_before = _rel_count(store)
        assert total_before == 60 + 6 + 2  # 68

        # --- Run 1: cap the run at 20 deletions ---
        r1 = store.prune_and_compact_relations(
            daily_maintenance_token=DAILY_MAINTENANCE_TOKEN,
            max_delete=20,
            batch_size=7,
            incremental_vacuum_pages=64,
        )
        # BOUND: never exceeds max_delete.
        assert r1["deleted_total"] == 20
        assert r1["bound_hit"] is True
        assert r1["deleted_duplicates"] == 0          # dedup never runs
        assert r1["space_reclaimed"] is False          # honest reclaim flag
        assert _rel_count(store) == total_before - 20

        # --- Run 2: large cap, drain the rest ---
        r2 = store.prune_and_compact_relations(
            daily_maintenance_token=DAILY_MAINTENANCE_TOKEN,
            max_delete=5000,
            batch_size=500,
            incremental_vacuum_pages=2000,
        )
        # Prunable = 60 orphans ONLY (no dedup); 20 already gone -> 40 left.
        assert r2["deleted_total"] == 40
        assert r1["deleted_orphans"] + r2["deleted_orphans"] == 60
        assert r1["deleted_duplicates"] + r2["deleted_duplicates"] == 0

        # 6 multi-source corroboration rows + 2 unknown-provenance survive.
        assert _rel_count(store) == 8
        corroboration = store._conn.execute(
            "SELECT COUNT(*) AS c FROM memory_relations "
            "WHERE source_entity_id=? AND target_entity_id=? "
            "AND relation_type='co_occurs_with'",
            (e[2], e[3]),
        ).fetchone()["c"]
        assert corroboration == 6, "multi-source edge must NOT be deduped"
        provs = sorted(
            (r["source_type"], r["source_id"])
            for r in store._conn.execute(
                "SELECT source_type, source_id FROM memory_relations"
            ).fetchall()
        )
        assert ("", 0) in provs               # empty source_type kept
        assert ("fact", 0) in provs           # source_id<=0 kept
        assert ("chunk", real_chunk) in provs  # corroboration row kept

        # --- Run 3: IDEMPOTENT — nothing left to prune ---
        r3 = store.prune_and_compact_relations(
            daily_maintenance_token=DAILY_MAINTENANCE_TOKEN,
            max_delete=5000,
        )
        assert r3["deleted_total"] == 0
        assert r3["noop"] is True
        assert _rel_count(store) == 8
    finally:
        provider.shutdown()


def test_prune_refuses_without_daily_token(tmp_path):
    """Hot-path guard: no token / wrong token => hard refusal, zero deletes."""
    provider, store = _store(tmp_path)
    try:
        e = _mk_entities(store, 2)
        with store._lock:
            store._conn.execute(
                "INSERT INTO memory_relations "
                "(source_entity_id, target_entity_id, relation_type, "
                " source_type, source_id) VALUES (?,?,?,?,?)",
                (e[0], e[1], "co_occurs_with", "fact", 9999),
            )
            store._conn.commit()

        # Missing token.
        with pytest.raises(TypeError):
            store.prune_and_compact_relations()  # type: ignore[call-arg]

        # Wrong token (a freshly-minted sentinel — what any non-maintenance
        # caller could at best fabricate; identity check still fails).
        with pytest.raises(PermissionError):
            store.prune_and_compact_relations(daily_maintenance_token=object())

        with pytest.raises(PermissionError):
            store.prune_and_compact_relations(daily_maintenance_token=None)

        # Nothing was deleted by any refused call.
        assert _rel_count(store) == 1
    finally:
        provider.shutdown()


def test_recall_path_never_triggers_prune(tmp_path, monkeypatch):
    """The recall/hot path must not be able to reach prune_and_compact_relations.

    We tripwire the method: if any add/search/probe/related/recent call on the
    agent hot path touches it, the test fails loudly.
    """
    provider, store = _store(tmp_path)
    try:
        called = {"hit": False}
        original = store.prune_and_compact_relations

        def _tripwire(*args, **kwargs):
            called["hit"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "prune_and_compact_relations", _tripwire)

        # Write path.
        provider.handle_tool_call(
            "fact_store",
            {
                "action": "add",
                "content": "Acme Corp uses Widget Pro for invoicing workflows.",
                "category": "general",
            },
        )
        # Every read/recall surface the agent hot path exercises.
        for arg in (
            {"action": "search", "query": "Acme", "limit": 5},
            {"action": "probe", "entity": "Acme Corp", "limit": 5},
            {"action": "related", "entity": "Acme Corp", "limit": 5},
            {"action": "recent", "limit": 5},
        ):
            provider.handle_tool_call("fact_store", arg)

        assert called["hit"] is False, (
            "prune_and_compact_relations was reached from the recall/hot path"
        )
    finally:
        provider.shutdown()
