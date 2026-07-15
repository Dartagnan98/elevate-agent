"""Regression coverage for backend-specific holographic fact search."""

from __future__ import annotations

import sqlite3

from plugins.memory.holographic.retrieval import FactRetriever


class _PostgresLikeStore:
    """Small store double whose non-SQLite connection selects Postgres."""

    def __init__(self, outcome):
        self._conn = object()
        self._outcome = outcome
        self.calls: list[tuple[str, list]] = []

    def _read_all(self, sql: str, params: list):
        self.calls.append((sql, params))
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _SQLiteStore:
    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self.calls: list[tuple[str, list]] = []
        self._conn.executescript(
            """
            CREATE TABLE facts (
                fact_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                trust_score REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE VIRTUAL TABLE facts_fts
                USING fts5(content, tags, content=facts, content_rowid=fact_id);
            CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, content, tags)
                    VALUES (new.fact_id, new.content, new.tags);
            END;
            """
        )
        self._conn.execute(
            """
            INSERT INTO facts(content, category, tags, trust_score)
            VALUES (?, ?, ?, ?)
            """,
            ("Client Jane has a 500000 budget", "client", "buyer", 0.9),
        )
        self._conn.commit()

    def _read_all(self, sql: str, params: list):
        self.calls.append((sql, params))
        return self._conn.execute(sql, params).fetchall()


def test_postgres_empty_result_never_falls_through_to_sqlite_match():
    store = _PostgresLikeStore([])
    retriever = FactRetriever(store)

    assert retriever._fts_candidates("What is the missing budget?", None, 0.3, 10) == []

    # The forgiving second attempt must remain on the Postgres query family.
    assert len(store.calls) == 2
    assert all("websearch_to_tsquery" in sql for sql, _params in store.calls)
    assert all("facts_fts MATCH" not in sql for sql, _params in store.calls)


def test_postgres_error_never_falls_through_to_sqlite_match():
    store = _PostgresLikeStore(RuntimeError("postgres unavailable"))
    retriever = FactRetriever(store)

    assert retriever._fts_candidates("missing", None, 0.3, 10) == []

    assert len(store.calls) == 1
    assert "websearch_to_tsquery" in store.calls[0][0]
    assert "facts_fts MATCH" not in store.calls[0][0]


def test_sqlite_store_still_uses_fts5_match_and_returns_candidates():
    store = _SQLiteStore()
    retriever = FactRetriever(store)
    try:
        rows = retriever._fts_candidates("Jane budget", "client", 0.3, 10)
    finally:
        store._conn.close()

    assert [row["content"] for row in rows] == ["Client Jane has a 500000 budget"]
    assert rows[0]["fts_rank"] == 1.0
    assert len(store.calls) == 1
    assert "facts_fts MATCH" in store.calls[0][0]
    assert "websearch_to_tsquery" not in store.calls[0][0]
