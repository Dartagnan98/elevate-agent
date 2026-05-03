"""
SQLite-backed fact store with entity resolution and trust scoring.
Single-user Elevate memory store plugin.
"""

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .embeddings import (
    BaseEmbeddingClient,
    blob_to_vector,
    content_hash,
    cosine_similarity,
    vector_to_blob,
)

try:
    from . import holographic as hrr
except ImportError:
    import holographic as hrr  # type: ignore[no-redef]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL UNIQUE,
    category        TEXT DEFAULT 'general',
    tags            TEXT DEFAULT '',
    trust_score     REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    helpful_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hrr_vector      BLOB,
    source_type     TEXT DEFAULT '',
    source_uri      TEXT DEFAULT '',
    source_excerpt  TEXT DEFAULT '',
    observed_at     TIMESTAMP,
    memory_space    TEXT DEFAULT '',
    status          TEXT DEFAULT 'active',
    superseded_by   INTEGER
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    entity_type TEXT DEFAULT 'unknown',
    aliases     TEXT DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_entities (
    fact_id   INTEGER REFERENCES facts(fact_id),
    entity_id INTEGER REFERENCES entities(entity_id),
    PRIMARY KEY (fact_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_trust    ON facts(trust_score DESC);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_entities_name  ON entities(name);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(content, tags, content=facts, content_rowid=fact_id);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, tags)
        VALUES (new.fact_id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
        VALUES ('delete', old.fact_id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
        VALUES ('delete', old.fact_id, old.content, old.tags);
    INSERT INTO facts_fts(rowid, content, tags)
        VALUES (new.fact_id, new.content, new.tags);
END;

CREATE TABLE IF NOT EXISTS memory_banks (
    bank_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_name  TEXT NOT NULL UNIQUE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    fact_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type  TEXT NOT NULL,
    target_id    INTEGER NOT NULL,
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    dimensions   INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    vector       BLOB NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(target_type, target_id, provider, model)
);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_target
    ON memory_embeddings(target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_provider_model
    ON memory_embeddings(provider, model);

CREATE TABLE IF NOT EXISTS memory_turn_journal (
    turn_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT DEFAULT '',
    session_day       TEXT NOT NULL DEFAULT CURRENT_DATE,
    turn_hash         TEXT NOT NULL UNIQUE,
    user_content      TEXT NOT NULL,
    assistant_content TEXT NOT NULL,
    status            TEXT DEFAULT 'pending',
    extracted_count   INTEGER DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at      TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_turn_journal_status
    ON memory_turn_journal(status, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_turn_journal_session
    ON memory_turn_journal(session_id, session_day, status);


CREATE TABLE IF NOT EXISTS memory_documents (
    document_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type   TEXT DEFAULT 'document',
    source_uri    TEXT UNIQUE NOT NULL,
    title         TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memory_modal_assets (
    asset_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER NOT NULL REFERENCES memory_documents(document_id) ON DELETE CASCADE,
    asset_type    TEXT DEFAULT 'text',
    locator       TEXT DEFAULT '',
    summary       TEXT DEFAULT '',
    text_content  TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_modal_assets_document
    ON memory_modal_assets(document_id, asset_type);

CREATE INDEX IF NOT EXISTS idx_memory_documents_source
    ON memory_documents(source_type, source_uri);

CREATE TABLE IF NOT EXISTS memory_chunks (
    chunk_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER NOT NULL REFERENCES memory_documents(document_id) ON DELETE CASCADE,
    chunk_index    INTEGER NOT NULL,
    content        TEXT NOT NULL,
    char_count     INTEGER DEFAULT 0,
    source_excerpt TEXT DEFAULT '',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_memory_chunks_document
    ON memory_chunks(document_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts
    USING fts5(content, source_excerpt, content=memory_chunks, content_rowid=chunk_id);

CREATE TRIGGER IF NOT EXISTS memory_chunks_ai AFTER INSERT ON memory_chunks BEGIN
    INSERT INTO memory_chunks_fts(rowid, content, source_excerpt)
        VALUES (new.chunk_id, new.content, new.source_excerpt);
END;

CREATE TRIGGER IF NOT EXISTS memory_chunks_ad AFTER DELETE ON memory_chunks BEGIN
    INSERT INTO memory_chunks_fts(memory_chunks_fts, rowid, content, source_excerpt)
        VALUES ('delete', old.chunk_id, old.content, old.source_excerpt);
END;

CREATE TRIGGER IF NOT EXISTS memory_chunks_au AFTER UPDATE ON memory_chunks BEGIN
    INSERT INTO memory_chunks_fts(memory_chunks_fts, rowid, content, source_excerpt)
        VALUES ('delete', old.chunk_id, old.content, old.source_excerpt);
    INSERT INTO memory_chunks_fts(rowid, content, source_excerpt)
        VALUES (new.chunk_id, new.content, new.source_excerpt);
END;


CREATE TABLE IF NOT EXISTS memory_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT DEFAULT '',
    event         TEXT NOT NULL,
    detail_json   TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_events_session
    ON memory_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_events_event
    ON memory_events(event, created_at);

CREATE TABLE IF NOT EXISTS memory_injections (
    injection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT DEFAULT '',
    query        TEXT DEFAULT '',
    content      TEXT DEFAULT '',
    fact_ids     TEXT DEFAULT '',
    chunk_ids    TEXT DEFAULT '',
    source       TEXT DEFAULT '',
    prompt_chars INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_injections_session
    ON memory_injections(session_id, created_at);

CREATE TABLE IF NOT EXISTS memory_gaps (
    gap_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT DEFAULT '',
    query        TEXT DEFAULT '',
    candidate_count INTEGER DEFAULT 0,
    note         TEXT DEFAULT '',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_gaps_session
    ON memory_gaps(session_id, created_at);

CREATE TABLE IF NOT EXISTS fact_links (
    source_fact_id INTEGER NOT NULL REFERENCES facts(fact_id) ON DELETE CASCADE,
    target_fact_id INTEGER NOT NULL REFERENCES facts(fact_id) ON DELETE CASCADE,
    link_type      TEXT DEFAULT 'relates_to',
    weight         REAL DEFAULT 1.0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_fact_id, target_fact_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_fact_links_source ON fact_links(source_fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_target ON fact_links(target_fact_id);


CREATE TABLE IF NOT EXISTS memory_clusters (
    cluster_id    TEXT PRIMARY KEY,
    name          TEXT DEFAULT '',
    tags          TEXT DEFAULT '',
    fact_ids_json TEXT NOT NULL DEFAULT '[]',
    source        TEXT DEFAULT 'auto',
    weight        REAL DEFAULT 1.0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_clusters_updated
    ON memory_clusters(updated_at);

CREATE TABLE IF NOT EXISTS memory_cluster_members (
    cluster_id TEXT NOT NULL REFERENCES memory_clusters(cluster_id) ON DELETE CASCADE,
    fact_id    INTEGER NOT NULL REFERENCES facts(fact_id) ON DELETE CASCADE,
    weight     REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cluster_id, fact_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_cluster_members_fact
    ON memory_cluster_members(fact_id);

CREATE TABLE IF NOT EXISTS memory_chunk_entities (
    chunk_id  INTEGER NOT NULL REFERENCES memory_chunks(chunk_id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    weight    REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chunk_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_chunk_entities_entity
    ON memory_chunk_entities(entity_id);

CREATE TABLE IF NOT EXISTS memory_relations (
    relation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    relation_type    TEXT DEFAULT 'co_occurs_with',
    source_type      TEXT DEFAULT '',
    source_id        INTEGER DEFAULT 0,
    weight           REAL DEFAULT 1.0,
    evidence         TEXT DEFAULT '',
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_entity_id, target_entity_id, relation_type, source_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_relations_source
    ON memory_relations(source_entity_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_memory_relations_target
    ON memory_relations(target_entity_id, relation_type);

CREATE TABLE IF NOT EXISTS memory_community_reports (
    community_id  TEXT PRIMARY KEY REFERENCES memory_clusters(cluster_id) ON DELETE CASCADE,
    name          TEXT DEFAULT '',
    summary       TEXT DEFAULT '',
    tags          TEXT DEFAULT '',
    entity_names  TEXT DEFAULT '',
    fact_ids_json TEXT DEFAULT '[]',
    chunk_ids_json TEXT DEFAULT '[]',
    source        TEXT DEFAULT 'cluster',
    weight        REAL DEFAULT 1.0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_community_reports_fts
    USING fts5(community_id UNINDEXED, name, summary, tags, entity_names);
"""

# Trust adjustment constants
_HELPFUL_DELTA   =  0.05
_UNHELPFUL_DELTA = -0.10
_TRUST_MIN       =  0.0
_TRUST_MAX       =  1.0

# Entity extraction patterns
_RE_CAPITALIZED  = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_RE_DOUBLE_QUOTE = re.compile(r'"([^"]+)"')
_RE_SINGLE_QUOTE = re.compile(r"'([^']+)'")
_RE_AKA          = re.compile(
    r'(\w+(?:\s+\w+)*)\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)',
    re.IGNORECASE,
)


def _clamp_trust(value: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, value))


class MemoryStore:
    """SQLite-backed fact store with entity resolution and trust scoring."""

    def __init__(
        self,
        db_path: "str | Path | None" = None,
        default_trust: float = 0.5,
        hrr_dim: int = 1024,
        embedding_client: BaseEmbeddingClient | None = None,
    ) -> None:
        if db_path is None:
            from elevate_constants import get_elevate_home
            db_path = str(get_elevate_home() / "memory_store.db")
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_trust = _clamp_trust(default_trust)
        self.hrr_dim = hrr_dim
        self.embedding_client = embedding_client
        self._hrr_available = hrr._HAS_NUMPY
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create tables, indexes, and triggers if they do not exist. Enable WAL mode."""
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        # Migrate: add hrr_vector column if missing (safe for existing databases)
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(facts)").fetchall()}
        if "hrr_vector" not in columns:
            self._conn.execute("ALTER TABLE facts ADD COLUMN hrr_vector BLOB")
        fact_column_defaults = {
            "source_type": "TEXT DEFAULT ''",
            "source_uri": "TEXT DEFAULT ''",
            "source_excerpt": "TEXT DEFAULT ''",
            "observed_at": "TIMESTAMP",
            "memory_space": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'active'",
            "superseded_by": "INTEGER",
        }
        for name, definition in fact_column_defaults.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE facts ADD COLUMN {name} {definition}")
        journal_columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(memory_turn_journal)").fetchall()
        }
        if "session_day" not in journal_columns:
            self._conn.execute(
                "ALTER TABLE memory_turn_journal ADD COLUMN session_day TEXT NOT NULL DEFAULT ''"
            )
            self._conn.execute(
                """
                UPDATE memory_turn_journal
                SET session_day = substr(COALESCE(created_at, CURRENT_DATE), 1, 10)
                WHERE session_day = ''
                """
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_fact(
        self,
        content: str,
        category: str = "general",
        tags: str = "",
        source_type: str = "",
        source_uri: str = "",
        source_excerpt: str = "",
        observed_at: str | None = None,
        memory_space: str = "",
    ) -> int:
        """Insert a fact and return its fact_id.

        Deduplicates by content (UNIQUE constraint). On duplicate, returns
        the existing fact_id without modifying the row. Extracts entities from
        the content and links them to the fact.
        """
        with self._lock:
            content = content.strip()
            if not content:
                raise ValueError("content must not be empty")

            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO facts (
                        content, category, tags, trust_score,
                        source_type, source_uri, source_excerpt, observed_at,
                        memory_space
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        content,
                        category,
                        tags,
                        self.default_trust,
                        str(source_type or ""),
                        str(source_uri or ""),
                        str(source_excerpt or ""),
                        observed_at,
                        str(memory_space or ""),
                    ),
                )
                self._conn.commit()
                fact_id: int = cur.lastrowid  # type: ignore[assignment]
            except sqlite3.IntegrityError:
                # Duplicate content — return existing id
                row = self._conn.execute(
                    "SELECT fact_id FROM facts WHERE content = ?", (content,)
                ).fetchone()
                fact_id = int(row["fact_id"])
                self._embed_fact(fact_id, content)
                return fact_id

            # Entity extraction, linking, and lightweight relation upsert
            self._link_fact_entities(fact_id, content)

            # Compute HRR vector after entity linking
            self._compute_hrr_vector(fact_id, content)
            self._embed_fact(fact_id, content)
            self._rebuild_bank(category)

            return fact_id

    def search_facts(
        self,
        query: str,
        category: str | None = None,
        min_trust: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search over facts using FTS5.

        Returns a list of fact dicts ordered by FTS5 rank, then trust_score
        descending. Also increments retrieval_count for matched facts.
        """
        with self._lock:
            query = query.strip()
            if not query:
                return []

            params: list = [query, min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND f.category = ?"
                params.append(category)
            params.append(limit)

            sql = f"""
                SELECT f.fact_id, f.content, f.category, f.tags,
                       f.trust_score, f.retrieval_count, f.helpful_count,
                       f.created_at, f.updated_at, f.source_type, f.source_uri,
                       f.source_excerpt, f.observed_at, f.memory_space, f.status,
                       f.superseded_by
                FROM facts f
                JOIN facts_fts fts ON fts.rowid = f.fact_id
                WHERE facts_fts MATCH ?
                  AND f.trust_score >= ?
                  AND COALESCE(f.status, 'active') = 'active'
                  {category_clause}
                ORDER BY fts.rank, f.trust_score DESC
                LIMIT ?
            """

            rows = self._conn.execute(sql, params).fetchall()
            results = [self._row_to_dict(r) for r in rows]

            if results:
                ids = [r["fact_id"] for r in results]
                placeholders = ",".join("?" * len(ids))
                self._conn.execute(
                    f"UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id IN ({placeholders})",
                    ids,
                )
                self._conn.commit()

            return results

    def update_fact(
        self,
        fact_id: int,
        content: str | None = None,
        trust_delta: float | None = None,
        tags: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        source_uri: str | None = None,
        source_excerpt: str | None = None,
        observed_at: str | None = None,
        memory_space: str | None = None,
        superseded_by: int | None = None,
        status: str | None = None,
    ) -> bool:
        """Partially update a fact. Trust is clamped to [0, 1].

        Returns True if the row existed, False otherwise.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False

            assignments: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
            params: list = []

            if content is not None:
                assignments.append("content = ?")
                params.append(content.strip())
            if tags is not None:
                assignments.append("tags = ?")
                params.append(tags)
            if category is not None:
                assignments.append("category = ?")
                params.append(category)
            if source_type is not None:
                assignments.append("source_type = ?")
                params.append(source_type)
            if source_uri is not None:
                assignments.append("source_uri = ?")
                params.append(source_uri)
            if source_excerpt is not None:
                assignments.append("source_excerpt = ?")
                params.append(source_excerpt)
            if observed_at is not None:
                assignments.append("observed_at = ?")
                params.append(observed_at)
            if memory_space is not None:
                assignments.append("memory_space = ?")
                params.append(memory_space)
            if superseded_by is not None:
                assignments.append("superseded_by = ?")
                params.append(int(superseded_by))
            if status is not None:
                assignments.append("status = ?")
                params.append(status)
            if trust_delta is not None:
                new_trust = _clamp_trust(row["trust_score"] + trust_delta)
                assignments.append("trust_score = ?")
                params.append(new_trust)

            params.append(fact_id)
            self._conn.execute(
                f"UPDATE facts SET {', '.join(assignments)} WHERE fact_id = ?",
                params,
            )
            self._conn.commit()

            # If content changed, re-extract entities and relations
            if content is not None:
                self._conn.execute(
                    "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
                )
                self._conn.execute(
                    "DELETE FROM memory_relations WHERE source_type = 'fact' AND source_id = ?", (fact_id,)
                )
                self._link_fact_entities(fact_id, content)
                self._conn.commit()

            # Recompute HRR vector if content changed
            if content is not None:
                self._compute_hrr_vector(fact_id, content)
                self._embed_fact(fact_id, content)
            # Rebuild bank for relevant category
            cat = category or self._conn.execute(
                "SELECT category FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()["category"]
            self._rebuild_bank(cat)

            return True

    def remove_fact(self, fact_id: int) -> bool:
        """Delete a fact and its entity links. Returns True if the row existed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, category FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False

            self._conn.execute(
                "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
            )
            self._conn.execute(
                "DELETE FROM memory_embeddings WHERE target_type = 'fact' AND target_id = ?",
                (fact_id,),
            )
            self._conn.execute("DELETE FROM facts WHERE fact_id = ?", (fact_id,))
            self._conn.commit()
            self._rebuild_bank(row["category"])
            return True

    def list_facts(
        self,
        category: str | None = None,
        min_trust: float = 0.0,
        limit: int = 50,
    ) -> list[dict]:
        """Browse facts ordered by trust_score descending.

        Optionally filter by category and minimum trust score.
        """
        with self._lock:
            params: list = [min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND category = ?"
                params.append(category)
            params.append(limit)

            sql = f"""
                SELECT fact_id, content, category, tags, trust_score,
                       retrieval_count, helpful_count, created_at, updated_at,
                       source_type, source_uri, source_excerpt, observed_at,
                       memory_space, status, superseded_by
                FROM facts
                WHERE trust_score >= ?
                  AND COALESCE(status, 'active') = 'active'
                  {category_clause}
                ORDER BY trust_score DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def recent_turns(
        self,
        session_id: str | None = None,
        session_day: str | None = None,
        query: str | None = None,
        limit: int = 6,
        include_assistant: bool = False,
    ) -> list[dict]:
        """Return recent journal turns, optionally reranked by query overlap."""
        with self._lock:
            params: list = []
            clauses: list[str] = []
            if session_id:
                clauses.append("session_id = ?")
                params.append(session_id)
            if session_day:
                clauses.append("session_day = ?")
                params.append(session_day)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            fetch_limit = max(1, int(limit)) * 4
            rows = self._conn.execute(
                f"""
                SELECT turn_id, session_id, session_day, user_content,
                       assistant_content, status, extracted_count,
                       created_at, processed_at
                FROM memory_turn_journal
                {where}
                ORDER BY created_at DESC, turn_id DESC
                LIMIT ?
                """,
                params + [fetch_limit],
            ).fetchall()
            turns = [self._row_to_dict(r) for r in rows]

        query_tokens = self._tokens(query or "")
        if query_tokens:
            for turn in turns:
                text = turn.get("user_content", "")
                if include_assistant:
                    text += " " + turn.get("assistant_content", "")
                overlap = len(query_tokens & self._tokens(text))
                turn["_score"] = overlap
            matching = [t for t in turns if t.get("_score", 0) > 0]
            if matching:
                turns = sorted(
                    matching,
                    key=lambda t: (t.get("_score", 0), t.get("created_at") or "", t.get("turn_id") or 0),
                    reverse=True,
                )

        selected = turns[: max(1, int(limit))]
        selected.sort(key=lambda t: (t.get("created_at") or "", t.get("turn_id") or 0))
        for turn in selected:
            turn.pop("_score", None)
            if not include_assistant:
                turn.pop("assistant_content", None)
        return selected

    def entity_candidates(self, query: str, limit: int = 5) -> list[str]:
        """Find entity names likely relevant to a query."""
        query = str(query or "").strip()
        if not query:
            return []

        seen: set[str] = set()
        candidates: list[str] = []

        def add(name: str) -> None:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                candidates.append(name.strip())

        for name in self._extract_entities(query):
            add(name)

        tokens = [t for t in self._tokens(query) if len(t) >= 4]
        with self._lock:
            for token in tokens[:8]:
                rows = self._conn.execute(
                    """
                    SELECT name
                    FROM entities
                    WHERE lower(name) LIKE ?
                       OR lower(aliases) LIKE ?
                    ORDER BY length(name) ASC, name ASC
                    LIMIT ?
                    """,
                    (f"%{token.lower()}%", f"%{token.lower()}%", max(1, int(limit))),
                ).fetchall()
                for row in rows:
                    add(row["name"])
                    if len(candidates) >= limit:
                        return candidates[:limit]
        return candidates[:limit]

    def entity_wiki(self, entity: str, limit: int = 8) -> dict:
        """Return a wiki-style entity page with backlinks and connected facts."""
        entity = str(entity or "").strip()
        if not entity:
            raise ValueError("entity must not be empty")

        with self._lock:
            row = self._conn.execute(
                """
                SELECT entity_id, name, entity_type, aliases, created_at
                FROM entities
                WHERE lower(name) = lower(?)
                   OR ',' || lower(aliases) || ',' LIKE '%,' || lower(?) || ',%'
                ORDER BY CASE WHEN lower(name) = lower(?) THEN 0 ELSE 1 END,
                         length(name) ASC
                LIMIT 1
                """,
                (entity, entity, entity),
            ).fetchone()

            if row is None:
                like = f"%{entity.lower()}%"
                row = self._conn.execute(
                    """
                    SELECT entity_id, name, entity_type, aliases, created_at
                    FROM entities
                    WHERE lower(name) LIKE ?
                       OR lower(aliases) LIKE ?
                    ORDER BY length(name) ASC, name ASC
                    LIMIT 1
                    """,
                    (like, like),
                ).fetchone()

            if row is None:
                return {
                    "entity": entity,
                    "exists": False,
                    "facts": [],
                    "related_entities": [],
                    "wiki_link": f"[[{entity}]]",
                }

            entity_id = int(row["entity_id"])
            fact_rows = self._conn.execute(
                """
                SELECT f.fact_id, f.content, f.category, f.tags, f.trust_score,
                       f.retrieval_count, f.helpful_count, f.created_at, f.updated_at
                FROM facts f
                JOIN fact_entities fe ON fe.fact_id = f.fact_id
                WHERE fe.entity_id = ?
                  AND COALESCE(f.status, 'active') = 'active'
                ORDER BY f.trust_score DESC, f.updated_at DESC, f.fact_id DESC
                LIMIT ?
                """,
                (entity_id, max(1, int(limit))),
            ).fetchall()
            related_rows = self._conn.execute(
                """
                SELECT e.name, COUNT(*) AS shared_facts
                FROM fact_entities mine
                JOIN fact_entities other ON other.fact_id = mine.fact_id
                JOIN entities e ON e.entity_id = other.entity_id
                JOIN facts f ON f.fact_id = mine.fact_id
                WHERE mine.entity_id = ?
                  AND other.entity_id != ?
                  AND COALESCE(f.status, 'active') = 'active'
                GROUP BY e.entity_id, e.name
                ORDER BY shared_facts DESC, e.name ASC
                LIMIT ?
                """,
                (entity_id, entity_id, max(1, int(limit))),
            ).fetchall()
            relation_rows = self._conn.execute(
                """
                SELECT e.name, SUM(r.weight) AS relation_weight, COUNT(*) AS relation_count
                FROM memory_relations r
                JOIN entities e ON e.entity_id = CASE
                    WHEN r.source_entity_id = ? THEN r.target_entity_id
                    ELSE r.source_entity_id
                END
                WHERE r.source_entity_id = ? OR r.target_entity_id = ?
                GROUP BY e.entity_id, e.name
                ORDER BY relation_weight DESC, relation_count DESC, e.name ASC
                LIMIT ?
                """,
                (entity_id, entity_id, entity_id, max(1, int(limit))),
            ).fetchall()

        name = row["name"]
        related: dict[str, dict] = {}
        for r in related_rows:
            related[str(r["name"])] = {
                "entity": r["name"],
                "wiki_link": f"[[{r['name']}]]",
                "shared_facts": int(r["shared_facts"] or 0),
            }
        for r in relation_rows:
            item = related.setdefault(str(r["name"]), {
                "entity": r["name"],
                "wiki_link": f"[[{r['name']}]]",
                "shared_facts": 0,
            })
            item["relation_weight"] = float(r["relation_weight"] or 0.0)
            item["relation_count"] = int(r["relation_count"] or 0)
        related_entities = sorted(
            related.values(),
            key=lambda item: (float(item.get("relation_weight") or 0.0), int(item.get("shared_facts") or 0), item.get("entity", "")),
            reverse=True,
        )[: max(1, int(limit))]
        return {
            "entity_id": entity_id,
            "entity": name,
            "entity_type": row["entity_type"],
            "aliases": row["aliases"],
            "exists": True,
            "wiki_link": f"[[{name}]]",
            "facts": [self._row_to_dict(r) for r in fact_rows],
            "related_entities": related_entities,
        }

    def record_memory_event(
        self,
        event: str,
        *,
        session_id: str = "",
        detail: dict | None = None,
    ) -> None:
        """Persist a durable memory pipeline event and append a JSONL audit log."""
        detail = detail or {}
        safe_detail = self._safe_json_detail(detail)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "",
            "event": str(event or ""),
            "detail": safe_detail,
        }
        detail_json = json.dumps(safe_detail, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_events (session_id, event, detail_json)
                VALUES (?, ?, ?)
                """,
                (session_id or "", str(event or ""), detail_json),
            )
            self._conn.commit()
        try:
            from elevate_constants import get_elevate_home
            log_dir = get_elevate_home() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            path = log_dir / f"memory-events-{day}.jsonl"
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            pass

    def recent_memory_events(self, session_id: str | None = None, limit: int = 50) -> list[dict]:
        limit = max(1, int(limit))
        params: list = []
        where = ""
        if session_id:
            where = "WHERE session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT event_id, session_id, event, detail_json, created_at
                FROM memory_events
                {where}
                ORDER BY event_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        results = []
        for row in rows:
            item = self._row_to_dict(row)
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except Exception:
                item["detail"] = {}
            return_item = item
            results.append(return_item)
        return results

    def record_memory_injection(
        self,
        *,
        session_id: str,
        query: str,
        content: str,
        fact_ids: list[int] | None = None,
        chunk_ids: list[int] | None = None,
        source: str = "prefetch",
    ) -> dict:
        fact_ids = [int(x) for x in (fact_ids or []) if str(x).isdigit()]
        chunk_ids = [int(x) for x in (chunk_ids or []) if str(x).isdigit()]
        prompt_chars = len(content or "")
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO memory_injections (
                    session_id, query, content, fact_ids, chunk_ids, source, prompt_chars
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id or "",
                    self._clip_text(query, 1000),
                    self._clip_text(content, 12000),
                    json.dumps(fact_ids),
                    json.dumps(chunk_ids),
                    source,
                    prompt_chars,
                ),
            )
            self._conn.commit()
            injection_id = int(cur.lastrowid or 0)
        self.record_memory_event(
            "memory.injected",
            session_id=session_id,
            detail={"injection_id": injection_id, "fact_ids": fact_ids, "chunk_ids": chunk_ids, "prompt_chars": prompt_chars, "source": source},
        )
        return {"injection_id": injection_id, "fact_ids": fact_ids, "chunk_ids": chunk_ids, "prompt_chars": prompt_chars}

    def injected_memory_ids(self, session_id: str, limit: int = 50) -> dict:
        if not session_id:
            return {"fact_ids": set(), "chunk_ids": set()}
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT fact_ids, chunk_ids FROM memory_injections
                WHERE session_id = ?
                ORDER BY injection_id DESC
                LIMIT ?
                """,
                (session_id, max(1, int(limit))),
            ).fetchall()
        facts: set[int] = set()
        chunks: set[int] = set()
        for row in rows:
            for key, target in (("fact_ids", facts), ("chunk_ids", chunks)):
                try:
                    for value in json.loads(row[key] or "[]"):
                        target.add(int(value))
                except Exception:
                    pass
        return {"fact_ids": facts, "chunk_ids": chunks}

    def memory_replay(self, session_id: str | None = None, limit: int = 50) -> dict:
        limit = max(1, int(limit))
        params: list = []
        where = ""
        if session_id:
            where = "WHERE session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT injection_id, session_id, query, content, fact_ids, chunk_ids,
                       source, prompt_chars, created_at
                FROM memory_injections
                {where}
                ORDER BY injection_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        injections = []
        for row in rows:
            item = self._row_to_dict(row)
            for key in ("fact_ids", "chunk_ids"):
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except Exception:
                    item[key] = []
            injections.append(item)
        return {"injections": injections, "count": len(injections)}

    def record_memory_gap(self, *, session_id: str = "", query: str = "", candidate_count: int = 0, note: str = "") -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_gaps (session_id, query, candidate_count, note)
                VALUES (?, ?, ?, ?)
                """,
                (session_id or "", self._clip_text(query, 1000), int(candidate_count or 0), self._clip_text(note, 1000)),
            )
            self._conn.commit()
        self.record_memory_event("memory.gap", session_id=session_id, detail={"query": query, "candidate_count": candidate_count, "note": note})

    def post_retrieval_maintenance(
        self,
        *,
        verified_ids: list[int] | None = None,
        rejected_ids: list[int] | None = None,
        query: str = "",
        session_id: str = "",
    ) -> dict:
        verified = sorted({int(x) for x in (verified_ids or []) if str(x).isdigit()})
        rejected = sorted({int(x) for x in (rejected_ids or []) if str(x).isdigit()} - set(verified))
        boosted = decayed = links = 0
        with self._lock:
            for fact_id in verified:
                cur = self._conn.execute(
                    "UPDATE facts SET trust_score = MIN(1.0, trust_score + 0.03), updated_at = CURRENT_TIMESTAMP WHERE fact_id = ? AND COALESCE(status, 'active') = 'active'",
                    (fact_id,),
                )
                boosted += cur.rowcount or 0
            for fact_id in rejected:
                cur = self._conn.execute(
                    "UPDATE facts SET trust_score = MAX(0.0, trust_score - 0.01), updated_at = CURRENT_TIMESTAMP WHERE fact_id = ? AND COALESCE(status, 'active') = 'active'",
                    (fact_id,),
                )
                decayed += cur.rowcount or 0
            for i, src in enumerate(verified):
                for dst in verified[i + 1:]:
                    self._conn.execute(
                        """
                        INSERT INTO fact_links (source_fact_id, target_fact_id, link_type, weight, updated_at)
                        VALUES (?, ?, 'co_recalled', 1.0, CURRENT_TIMESTAMP)
                        ON CONFLICT(source_fact_id, target_fact_id, link_type) DO UPDATE SET
                            weight = fact_links.weight + 1.0,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (src, dst),
                    )
                    links += 1
            self._conn.commit()
        cluster = {"clustered": False}
        tags = {"updated": 0}
        confidence = {"boosted": 0, "decayed": 0, "archived": 0}
        if len(verified) >= 2:
            cluster = self.refine_memory_clusters(verified, query=query, session_id=session_id)
            tags = self.infer_tags_for_facts(verified, limit=len(verified))
        confidence = self.confidence_maintenance(verified_ids=verified, rejected_ids=rejected, prune=False)
        if not verified and rejected:
            self.record_memory_gap(session_id=session_id, query=query, candidate_count=len(rejected), note="retrieved candidates but verifier rejected all")
        self.record_memory_event(
            "memory.maintenance",
            session_id=session_id,
            detail={"verified": len(verified), "rejected": len(rejected), "boosted": boosted + confidence.get("boosted", 0), "decayed": decayed + confidence.get("decayed", 0), "links": links, "cluster": cluster, "tags": tags},
        )
        return {"verified": len(verified), "rejected": len(rejected), "boosted": boosted + confidence.get("boosted", 0), "decayed": decayed + confidence.get("decayed", 0), "links": links, "cluster": cluster, "tags": tags}

    def supersede_fact(self, old_fact_id: int, new_fact_id: int) -> bool:
        with self._lock:
            old = self._conn.execute("SELECT fact_id FROM facts WHERE fact_id = ?", (old_fact_id,)).fetchone()
            new = self._conn.execute("SELECT fact_id FROM facts WHERE fact_id = ?", (new_fact_id,)).fetchone()
            if not old or not new:
                return False
            self._conn.execute(
                "UPDATE facts SET status = 'superseded', superseded_by = ?, updated_at = CURRENT_TIMESTAMP WHERE fact_id = ?",
                (new_fact_id, old_fact_id),
            )
            self._conn.execute(
                """
                INSERT INTO fact_links (source_fact_id, target_fact_id, link_type, weight, updated_at)
                VALUES (?, ?, 'superseded_by', 1.0, CURRENT_TIMESTAMP)
                ON CONFLICT(source_fact_id, target_fact_id, link_type) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (old_fact_id, new_fact_id),
            )
            self._conn.commit()
        self.record_memory_event("memory.superseded", detail={"old_fact_id": old_fact_id, "new_fact_id": new_fact_id})
        return True

    def memory_profile(self, session_id: str | None = None) -> dict:
        params: list = []
        session_clause = ""
        if session_id:
            session_clause = "WHERE session_id = ?"
            params.append(session_id)
        with self._lock:
            fact_count = self._conn.execute("SELECT COUNT(*) FROM facts WHERE COALESCE(status, 'active') = 'active'").fetchone()[0]
            doc_count = self._conn.execute("SELECT COUNT(*) FROM memory_documents").fetchone()[0]
            chunk_count = self._conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
            journal = self._conn.execute(f"SELECT COUNT(*) AS c, COALESCE(SUM(length(user_content) + length(assistant_content)), 0) AS bytes FROM memory_turn_journal {session_clause}", params).fetchone()
            injections = self._conn.execute(f"SELECT COUNT(*) AS c, COALESCE(SUM(prompt_chars), 0) AS chars FROM memory_injections {session_clause}", params).fetchone()
            events = self._conn.execute(f"SELECT COUNT(*) AS c FROM memory_events {session_clause}", params).fetchone()
            gaps = self._conn.execute(f"SELECT COUNT(*) AS c FROM memory_gaps {session_clause}", params).fetchone()
            large_chunks = self._conn.execute("SELECT COUNT(*) FROM memory_chunks WHERE char_count >= 16000").fetchone()[0]
            cluster_count = self._conn.execute("SELECT COUNT(*) FROM memory_clusters").fetchone()[0]
            cluster_members = self._conn.execute("SELECT COUNT(*) FROM memory_cluster_members").fetchone()[0]
        return {
            "session_id": session_id or "",
            "facts": int(fact_count),
            "documents": int(doc_count),
            "chunks": int(chunk_count),
            "journal_turns": int(journal["c"]),
            "journal_payload_chars": int(journal["bytes"] or 0),
            "memory_injections": int(injections["c"]),
            "memory_injection_chars": int(injections["chars"] or 0),
            "memory_events": int(events["c"]),
            "memory_gaps": int(gaps["c"]),
            "large_chunks": int(large_chunks),
            "clusters": int(cluster_count),
            "cluster_members": int(cluster_members),
            "estimated_injection_tokens": int((injections["chars"] or 0) / 4),
            "estimated_journal_tokens": int((journal["bytes"] or 0) / 4),
        }


    @staticmethod
    def _stable_id(values: list[int] | list[str], prefix: str = "cluster") -> str:
        raw = "|".join(str(v) for v in sorted(values, key=lambda x: str(x)))
        import hashlib
        return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _normalise_tag(value: str) -> str:
        tag = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
        return tag[:48]

    @classmethod
    def _candidate_tags_from_text(cls, text: str, limit: int = 5) -> list[str]:
        stop = {
            "the", "and", "for", "that", "this", "with", "from", "into", "about", "your", "you",
            "are", "was", "were", "what", "when", "where", "should", "could", "would", "memory",
            "fact", "facts", "project", "user", "assistant", "content", "using", "uses", "have", "has",
        }
        tokens = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text or "")]
        counts: dict[str, int] = {}
        for t in tokens:
            if t in stop or len(t) < 3:
                continue
            counts[t] = counts.get(t, 0) + 1
        # Prefer existing hyphenated/business terms found in text before one-word fallbacks.
        phrases = re.findall(r"\b[A-Za-z0-9]+(?:[-_ ][A-Za-z0-9]+){1,3}\b", text or "")
        phrase_tags = []
        for phrase in phrases:
            tag = cls._normalise_tag(phrase)
            if tag and tag.replace('-', '') not in stop and 4 <= len(tag) <= 48:
                phrase_tags.append(tag)
        ordered = []
        for tag in phrase_tags:
            if tag not in ordered:
                ordered.append(tag)
            if len(ordered) >= limit:
                return ordered
        for token, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            tag = cls._normalise_tag(token)
            if tag and tag not in ordered:
                ordered.append(tag)
            if len(ordered) >= limit:
                break
        return ordered

    @classmethod
    def _cluster_name_from_rows(cls, rows: list[sqlite3.Row]) -> str:
        text = " ".join(" ".join(str(row[k] or "") for k in ("content", "tags", "category")) for row in rows)
        tags = cls._candidate_tags_from_text(text, limit=3)
        if tags:
            return " ".join(part.capitalize() for part in tags[0].split("-")[:4])
        return "Co-recalled Memory Cluster"

    def refine_memory_clusters(
        self,
        fact_ids: list[int] | None = None,
        *,
        query: str = "",
        session_id: str = "",
        min_members: int = 2,
    ) -> dict:
        """Create/update deterministic co-relevance clusters from facts retrieved together."""
        ids = sorted({int(x) for x in (fact_ids or []) if str(x).isdigit()})
        if len(ids) < max(2, int(min_members or 2)):
            return {"clustered": False, "reason": "not_enough_facts", "members": len(ids)}
        with self._lock:
            placeholders = ",".join("?" * len(ids))
            rows = self._conn.execute(
                f"""
                SELECT fact_id, content, category, tags, trust_score
                FROM facts
                WHERE fact_id IN ({placeholders}) AND COALESCE(status, 'active') = 'active'
                """,
                ids,
            ).fetchall()
            active_ids = sorted(int(r["fact_id"]) for r in rows)
            if len(active_ids) < max(2, int(min_members or 2)):
                return {"clustered": False, "reason": "not_enough_active_facts", "members": len(active_ids)}
            cluster_id = self._stable_id(active_ids, prefix="cluster")
            name = self._cluster_name_from_rows(rows)
            text = " ".join([query or ""] + [str(r["content"] or "") + " " + str(r["tags"] or "") for r in rows])
            tags = ",".join(self._candidate_tags_from_text(text, limit=8))
            self._conn.execute(
                """
                INSERT INTO memory_clusters (cluster_id, name, tags, fact_ids_json, source, weight, updated_at)
                VALUES (?, ?, ?, ?, 'co_relevance', 1.0, CURRENT_TIMESTAMP)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    name = excluded.name,
                    tags = excluded.tags,
                    fact_ids_json = excluded.fact_ids_json,
                    weight = memory_clusters.weight + 1.0,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (cluster_id, name, tags, json.dumps(active_ids)),
            )
            inserted_members = 0
            for fid in active_ids:
                cur = self._conn.execute(
                    """
                    INSERT INTO memory_cluster_members (cluster_id, fact_id, weight, updated_at)
                    VALUES (?, ?, 1.0, CURRENT_TIMESTAMP)
                    ON CONFLICT(cluster_id, fact_id) DO UPDATE SET
                        weight = memory_cluster_members.weight + 1.0,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (cluster_id, fid),
                )
                inserted_members += cur.rowcount or 0
            self._conn.commit()
        self.record_memory_event(
            "memory.cluster.refined",
            session_id=session_id,
            detail={"cluster_id": cluster_id, "name": name, "members": len(active_ids), "tags": tags},
        )
        report = self.build_community_report(cluster_id, session_id=session_id)
        return {
            "clustered": True,
            "cluster_id": cluster_id,
            "name": name,
            "members": len(active_ids),
            "tags": tags,
            "member_updates": inserted_members,
            "community_report": report,
        }

    def build_community_report(self, cluster_id: str, *, session_id: str = "") -> dict:
        """Build a durable global RAG community report from a memory cluster."""
        cluster_id = str(cluster_id or "").strip()
        if not cluster_id:
            return {"built": False, "reason": "missing_cluster_id"}
        with self._lock:
            cluster = self._conn.execute(
                "SELECT cluster_id, name, tags, fact_ids_json, weight FROM memory_clusters WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
            if cluster is None:
                return {"built": False, "reason": "cluster_not_found", "community_id": cluster_id}
            fact_ids = []
            try:
                fact_ids = [int(x) for x in json.loads(cluster["fact_ids_json"] or "[]") if str(x).isdigit()]
            except Exception:
                fact_ids = []
            if not fact_ids:
                rows = self._conn.execute(
                    "SELECT fact_id FROM memory_cluster_members WHERE cluster_id = ? ORDER BY weight DESC",
                    (cluster_id,),
                ).fetchall()
                fact_ids = [int(r["fact_id"]) for r in rows]
            if not fact_ids:
                return {"built": False, "reason": "empty_cluster", "community_id": cluster_id}
            placeholders = ",".join("?" * len(fact_ids))
            facts = self._conn.execute(
                f"""
                SELECT fact_id, content, category, tags, trust_score, source_uri, source_excerpt
                FROM facts
                WHERE fact_id IN ({placeholders}) AND COALESCE(status, 'active') = 'active'
                ORDER BY trust_score DESC, updated_at DESC
                """,
                fact_ids,
            ).fetchall()
            entity_rows = self._conn.execute(
                f"""
                SELECT e.name, COUNT(*) AS hits
                FROM fact_entities fe
                JOIN entities e ON e.entity_id = fe.entity_id
                WHERE fe.fact_id IN ({placeholders})
                GROUP BY e.entity_id, e.name
                ORDER BY hits DESC, e.name ASC
                LIMIT 12
                """,
                fact_ids,
            ).fetchall()
            entity_names = [str(r["name"]) for r in entity_rows]
            fact_text = " ".join(str(r["content"] or "") for r in facts)
            tags = cluster["tags"] or ",".join(self._candidate_tags_from_text(fact_text, limit=8))
            name = cluster["name"] or self._cluster_name_from_rows(facts)
            top_facts = [str(r["content"] or "") for r in facts[:5]]
            summary_bits = top_facts[:3]
            if entity_names:
                summary_bits.insert(0, "Key entities: " + ", ".join(entity_names[:6]))
            summary = " ".join(summary_bits)[:1800]
            chunk_rows = []
            if entity_names:
                like_terms = [f"%{name.lower()}%" for name in entity_names[:6]]
                clauses = " OR ".join(["lower(c.content) LIKE ?"] * len(like_terms))
                chunk_rows = self._conn.execute(
                    f"""
                    SELECT c.chunk_id
                    FROM memory_chunks c
                    WHERE {clauses}
                    ORDER BY c.updated_at DESC
                    LIMIT 12
                    """,
                    like_terms,
                ).fetchall()
            chunk_ids = [int(r["chunk_id"]) for r in chunk_rows]
            self._conn.execute("DELETE FROM memory_community_reports_fts WHERE community_id = ?", (cluster_id,))
            self._conn.execute(
                """
                INSERT INTO memory_community_reports (
                    community_id, name, summary, tags, entity_names, fact_ids_json, chunk_ids_json, source, weight, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'cluster', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(community_id) DO UPDATE SET
                    name = excluded.name,
                    summary = excluded.summary,
                    tags = excluded.tags,
                    entity_names = excluded.entity_names,
                    fact_ids_json = excluded.fact_ids_json,
                    chunk_ids_json = excluded.chunk_ids_json,
                    weight = excluded.weight,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    cluster_id,
                    name,
                    summary,
                    tags,
                    ",".join(entity_names),
                    json.dumps([int(r["fact_id"]) for r in facts]),
                    json.dumps(chunk_ids),
                    float(cluster["weight"] or 1.0),
                ),
            )
            self._conn.execute(
                "INSERT INTO memory_community_reports_fts (community_id, name, summary, tags, entity_names) VALUES (?, ?, ?, ?, ?)",
                (cluster_id, name, summary, tags, ",".join(entity_names)),
            )
            self._conn.commit()
        self.record_memory_event("memory.community.built", session_id=session_id, detail={"community_id": cluster_id, "facts": len(facts), "entities": len(entity_names)})
        return {"built": True, "community_id": cluster_id, "name": name, "summary": summary, "tags": tags, "entity_names": entity_names, "fact_ids": [int(r["fact_id"]) for r in facts], "chunk_ids": chunk_ids}

    def search_community_reports(self, query: str, *, limit: int = 5) -> list[dict]:
        """Search global community reports for LightRAG-style global recall."""
        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, int(limit or 5))
        with self._lock:
            params = [query, limit]
            sql = """
                SELECT r.community_id, r.name, r.summary, r.tags, r.entity_names,
                       r.fact_ids_json, r.chunk_ids_json, r.weight, r.updated_at,
                       memory_community_reports_fts.rank AS fts_rank_raw
                FROM memory_community_reports_fts
                JOIN memory_community_reports r ON r.community_id = memory_community_reports_fts.community_id
                WHERE memory_community_reports_fts MATCH ?
                ORDER BY memory_community_reports_fts.rank
                LIMIT ?
            """
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except Exception:
                fallback = self._fallback_fts_query(query)
                rows = self._conn.execute(sql, [fallback, limit]).fetchall() if fallback else []
            if not rows:
                for cluster in self._conn.execute("SELECT cluster_id FROM memory_clusters ORDER BY updated_at DESC LIMIT 20").fetchall():
                    self.build_community_report(str(cluster["cluster_id"]))
                try:
                    rows = self._conn.execute(sql, params).fetchall()
                except Exception:
                    rows = []
        max_rank = max((abs(float(r["fts_rank_raw"] or 0.0)) for r in rows), default=1.0) or 1.0
        results = []
        for row in rows:
            item = self._row_to_dict(row)
            item["score"] = abs(float(item.pop("fts_rank_raw") or 0.0)) / max_rank
            for key in ("fact_ids_json", "chunk_ids_json"):
                try:
                    item[key.replace("_json", "")] = json.loads(item.get(key) or "[]")
                except Exception:
                    item[key.replace("_json", "")] = []
                item.pop(key, None)
            results.append(item)
        return results

    def infer_tags_for_facts(self, fact_ids: list[int] | None = None, *, limit: int = 50) -> dict:
        """Infer lightweight tags from content/category and merge them into facts."""
        ids = sorted({int(x) for x in (fact_ids or []) if str(x).isdigit()})
        params: list = []
        where = "COALESCE(status, 'active') = 'active'"
        if ids:
            where += f" AND fact_id IN ({','.join('?' * len(ids))})"
            params.extend(ids)
        params.append(max(1, int(limit or 50)))
        updated = 0
        applied: dict[int, list[str]] = {}
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT fact_id, content, category, tags, source_uri, memory_space
                FROM facts
                WHERE {where}
                ORDER BY updated_at DESC, fact_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            for row in rows:
                existing = [self._normalise_tag(t) for t in re.split(r"[,\s]+", str(row["tags"] or "")) if t]
                text = " ".join(str(row[k] or "") for k in ("content", "category", "source_uri", "memory_space"))
                inferred = self._candidate_tags_from_text(text, limit=5)
                merged = []
                for tag in existing + inferred:
                    if tag and tag not in merged:
                        merged.append(tag)
                if merged and merged != existing:
                    self._conn.execute(
                        "UPDATE facts SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE fact_id = ?",
                        (",".join(merged[:12]), int(row["fact_id"])),
                    )
                    updated += 1
                    applied[int(row["fact_id"])] = merged[:12]
            self._conn.commit()
        self.record_memory_event("memory.tags.inferred", detail={"updated": updated})
        return {"updated": updated, "facts": applied}

    def confidence_maintenance(
        self,
        *,
        verified_ids: list[int] | None = None,
        rejected_ids: list[int] | None = None,
        prune: bool = True,
        archive_threshold: float = 0.12,
        min_age_hours: int = 24,
    ) -> dict:
        """Boost useful memories, decay rejected memories, and archive stale low-confidence facts."""
        verified = sorted({int(x) for x in (verified_ids or []) if str(x).isdigit()})
        rejected = sorted({int(x) for x in (rejected_ids or []) if str(x).isdigit()} - set(verified))
        boosted = decayed = archived = 0
        with self._lock:
            for fid in verified:
                cur = self._conn.execute(
                    "UPDATE facts SET trust_score = MIN(1.0, trust_score + 0.05), helpful_count = helpful_count + 1, updated_at = CURRENT_TIMESTAMP WHERE fact_id = ? AND COALESCE(status, 'active') = 'active'",
                    (fid,),
                )
                boosted += cur.rowcount or 0
            for fid in rejected:
                cur = self._conn.execute(
                    "UPDATE facts SET trust_score = MAX(0.0, trust_score - 0.02), updated_at = CURRENT_TIMESTAMP WHERE fact_id = ? AND COALESCE(status, 'active') = 'active'",
                    (fid,),
                )
                decayed += cur.rowcount or 0
            if prune:
                cur = self._conn.execute(
                    """
                    UPDATE facts
                    SET status = 'archived', updated_at = CURRENT_TIMESTAMP
                    WHERE COALESCE(status, 'active') = 'active'
                      AND trust_score < ?
                      AND (julianday('now') - julianday(created_at)) * 24.0 >= ?
                      AND helpful_count = 0
                    """,
                    (float(archive_threshold), int(min_age_hours)),
                )
                archived = cur.rowcount or 0
            self._conn.commit()
        self.record_memory_event("memory.confidence.maintenance", detail={"boosted": boosted, "decayed": decayed, "archived": archived})
        return {"boosted": boosted, "decayed": decayed, "archived": archived, "verified": len(verified), "rejected": len(rejected)}

    def prune_memory_logs(self, *, retention_days: int = 30) -> dict:
        """Prune old memory events/injections/gaps from SQLite while preserving facts/documents."""
        days = max(1, int(retention_days or 30))
        removed: dict[str, int] = {}
        with self._lock:
            for table, date_col in (("memory_events", "created_at"), ("memory_injections", "created_at"), ("memory_gaps", "created_at")):
                cur = self._conn.execute(
                    f"DELETE FROM {table} WHERE {date_col} < datetime('now', ?)",
                    (f"-{days} days",),
                )
                removed[table] = cur.rowcount or 0
            self._conn.commit()
        self.record_memory_event("memory.logs.pruned", detail={"retention_days": days, "removed": removed})
        return {"retention_days": days, "removed": removed, "total_removed": sum(removed.values())}

    def memory_benchmark(self, queries: list[str] | None = None, *, limit: int = 5) -> dict:
        """Small local recall benchmark: latency, hit counts, and duplicate rate across queries."""
        queries = [str(q).strip() for q in (queries or []) if str(q).strip()]
        if not queries:
            queries = ["user preferences", "project decisions", "Plaud meeting Uppercuts", "Google Ads campaigns"]
        started = time.time()
        rows = []
        seen_fact_ids: list[int] = []
        for query in queries:
            q_start = time.time()
            facts = self.list_facts(min_trust=0.0, limit=1000)
            # Prefer exact token overlap locally; this benchmark avoids external embedding calls.
            q_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
            scored = []
            for fact in facts:
                text = " ".join(str(fact.get(k, "")) for k in ("content", "tags", "category", "source_uri"))
                tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
                overlap = len(q_tokens & tokens)
                score = overlap + float(fact.get("trust_score") or 0)
                if overlap or not q_tokens:
                    scored.append((score, fact))
            scored.sort(key=lambda item: item[0], reverse=True)
            hits = [fact for _, fact in scored[: max(1, int(limit))]]
            seen_fact_ids.extend(int(f.get("fact_id")) for f in hits if f.get("fact_id"))
            rows.append({"query": query, "hits": len(hits), "latency_ms": round((time.time() - q_start) * 1000, 2), "top_fact_ids": [int(f.get("fact_id")) for f in hits if f.get("fact_id")]})
        duplicate_rate = 0.0
        if seen_fact_ids:
            duplicate_rate = 1.0 - (len(set(seen_fact_ids)) / len(seen_fact_ids))
        return {"queries": rows, "query_count": len(queries), "total_latency_ms": round((time.time() - started) * 1000, 2), "duplicate_rate": round(duplicate_rate, 4)}

    def record_feedback(self, fact_id: int, helpful: bool) -> dict:
        """Record user feedback and adjust trust asymmetrically.

        helpful=True  -> trust += 0.05, helpful_count += 1
        helpful=False -> trust -= 0.10

        Returns a dict with fact_id, old_trust, new_trust, helpful_count.
        Raises KeyError if fact_id does not exist.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score, helpful_count FROM facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"fact_id {fact_id} not found")

            old_trust: float = row["trust_score"]
            delta = _HELPFUL_DELTA if helpful else _UNHELPFUL_DELTA
            new_trust = _clamp_trust(old_trust + delta)

            helpful_increment = 1 if helpful else 0
            self._conn.execute(
                """
                UPDATE facts
                SET trust_score    = ?,
                    helpful_count  = helpful_count + ?,
                    updated_at     = CURRENT_TIMESTAMP
                WHERE fact_id = ?
                """,
                (new_trust, helpful_increment, fact_id),
            )
            self._conn.commit()

            return {
                "fact_id":      fact_id,
                "old_trust":    old_trust,
                "new_trust":    new_trust,
                "helpful_count": row["helpful_count"] + helpful_increment,
            }

    def record_retrieval_events(
        self,
        fact_ids: list[int],
        trust_delta: float = 0.0,
    ) -> dict:
        """Record that facts were surfaced by recall.

        This is intentionally separate from explicit user feedback. Retrievals
        increment usage counts so frequently surfaced facts can be inspected and
        ranked later. A tiny optional trust_delta can be used by higher-level
        retrieval flows that have verified relevance.
        """
        ids: list[int] = []
        seen: set[int] = set()
        for raw in fact_ids or []:
            try:
                fid = int(raw)
            except (TypeError, ValueError):
                continue
            if fid > 0 and fid not in seen:
                seen.add(fid)
                ids.append(fid)
        if not ids:
            return {"updated": 0}

        with self._lock:
            placeholders = ",".join("?" * len(ids))
            if trust_delta:
                rows = self._conn.execute(
                    f"SELECT fact_id, trust_score FROM facts WHERE fact_id IN ({placeholders})",
                    ids,
                ).fetchall()
                for row in rows:
                    self._conn.execute(
                        """
                        UPDATE facts
                        SET retrieval_count = retrieval_count + 1,
                            trust_score = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE fact_id = ?
                        """,
                        (_clamp_trust(float(row["trust_score"]) + trust_delta), int(row["fact_id"])),
                    )
                updated = len(rows)
            else:
                cur = self._conn.execute(
                    f"""
                    UPDATE facts
                    SET retrieval_count = retrieval_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE fact_id IN ({placeholders})
                    """,
                    ids,
                )
                updated = int(cur.rowcount or 0)
            self._conn.commit()
            return {"updated": updated}

    def record_turn(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        max_chars: int = 8000,
        session_day: str | None = None,
        created_at: str | datetime | None = None,
    ) -> int:
        """Record one completed turn in the local write-behind journal.

        The journal is intentionally separate from facts. It lets the agent
        capture turns cheaply, then promote only durable user facts in a later
        organization pass.
        """
        user_content = self._trim_journal_text(user_content, max_chars)
        assistant_content = self._trim_journal_text(assistant_content, max_chars)
        if not user_content and not assistant_content:
            raise ValueError("turn content must not be empty")

        session_id = str(session_id or "")
        created_at_text, session_day_text = self._journal_timestamp(
            created_at=created_at,
            session_day=session_day,
        )
        digest = content_hash(
            json.dumps(
                [session_id, session_day_text, user_content, assistant_content],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

        with self._lock:
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO memory_turn_journal (
                    session_id, session_day, turn_hash, user_content,
                    assistant_content, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    session_day_text,
                    digest,
                    user_content,
                    assistant_content,
                    created_at_text,
                ),
            )
            self._conn.commit()
            if cur.rowcount:
                return int(cur.lastrowid)

            row = self._conn.execute(
                "SELECT turn_id FROM memory_turn_journal WHERE turn_hash = ?",
                (digest,),
            ).fetchone()
            return int(row["turn_id"]) if row is not None else 0

    def pending_turns(
        self,
        session_id: str | None = None,
        session_day: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return pending journal rows, oldest first."""
        with self._lock:
            params: list = []
            where = "status = 'pending'"
            if session_id:
                where += " AND session_id = ?"
                params.append(session_id)
            if session_day:
                where += " AND session_day = ?"
                params.append(session_day)

            limit_clause = ""
            if limit is not None:
                safe_limit = max(1, int(limit))
                limit_clause = "LIMIT ?"
                params.append(safe_limit)

            rows = self._conn.execute(
                f"""
                SELECT turn_id, session_id, turn_hash, user_content,
                       session_day, assistant_content, status, extracted_count,
                       created_at, processed_at
                FROM memory_turn_journal
                WHERE {where}
                ORDER BY created_at ASC, turn_id ASC
                {limit_clause}
                """,
                params,
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def mark_turn_processed(self, turn_id: int, extracted_count: int = 0) -> None:
        """Mark a journal row as organized."""
        with self._lock:
            self._conn.execute(
                """
                UPDATE memory_turn_journal
                SET status = 'processed',
                    extracted_count = ?,
                    processed_at = CURRENT_TIMESTAMP
                WHERE turn_id = ?
                """,
                (max(0, int(extracted_count)), int(turn_id)),
            )
            self._conn.commit()

    def journal_status(
        self,
        session_id: str | None = None,
        session_day: str | None = None,
    ) -> dict:
        """Return turn-journal health and backlog counts."""
        with self._lock:
            params: list = []
            clauses: list[str] = []
            if session_id:
                clauses.append("session_id = ?")
                params.append(session_id)
            if session_day:
                clauses.append("session_day = ?")
                params.append(session_day)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

            rows = self._conn.execute(
                f"""
                SELECT status, COUNT(*) AS count
                FROM memory_turn_journal
                {where}
                GROUP BY status
                """,
                params,
            ).fetchall()
            counts = {str(row["status"]): int(row["count"]) for row in rows}
            total = sum(counts.values())
            latest = self._conn.execute(
                f"SELECT MAX(created_at) AS latest FROM memory_turn_journal {where}",
                params,
            ).fetchone()
            session_rows = self._conn.execute(
                f"""
                SELECT session_id,
                       session_day,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                       MIN(created_at) AS first_created_at,
                       MAX(created_at) AS latest_created_at
                FROM memory_turn_journal
                {where}
                GROUP BY session_id, session_day
                ORDER BY latest_created_at DESC, session_id ASC, session_day DESC
                """,
                params,
            ).fetchall()
            sessions = [
                {
                    "session_id": row["session_id"],
                    "session_day": row["session_day"],
                    "total": int(row["total"] or 0),
                    "pending": int(row["pending"] or 0),
                    "processed": int(row["processed"] or 0),
                    "failed": int(row["failed"] or 0),
                    "first_created_at": row["first_created_at"],
                    "latest_created_at": row["latest_created_at"],
                }
                for row in session_rows
            ]
            unique_sessions = {entry["session_id"] for entry in sessions}
            return {
                "total": total,
                "pending": counts.get("pending", 0),
                "processed": counts.get("processed", 0),
                "failed": counts.get("failed", 0),
                "latest_created_at": latest["latest"] if latest else None,
                "active_session_count": len(unique_sessions),
                "session_segment_count": len(sessions),
                "sessions": sessions,
            }

    def embeddings_enabled(self) -> bool:
        return self.embedding_client is not None

    def embedding_status(self) -> dict:
        """Return local embedding index status for facts."""
        with self._lock:
            fact_count = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            chunk_count = self._conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
            indexed_facts = 0
            indexed_chunks = 0
            if self.embedding_client:
                indexed_facts = self._conn.execute(
                    """
                    SELECT COUNT(*) FROM memory_embeddings
                    WHERE target_type = 'fact'
                      AND provider = ?
                      AND model = ?
                    """,
                    (self.embedding_client.provider, self.embedding_client.model),
                ).fetchone()[0]
                indexed_chunks = self._conn.execute(
                    """
                    SELECT COUNT(*) FROM memory_embeddings
                    WHERE target_type = 'chunk'
                      AND provider = ?
                      AND model = ?
                    """,
                    (self.embedding_client.provider, self.embedding_client.model),
                ).fetchone()[0]
            else:
                indexed_facts = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE target_type = 'fact'"
                ).fetchone()[0]
                indexed_chunks = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE target_type = 'chunk'"
                ).fetchone()[0]
            status = {
                "enabled": self.embeddings_enabled(),
                "facts": int(fact_count),
                "chunks": int(chunk_count),
                "indexed_facts": int(indexed_facts),
                "indexed_chunks": int(indexed_chunks),
                "missing_or_stale": 0,
                "missing_or_stale_chunks": 0,
            }
            if self.embedding_client:
                status.update({
                    "provider": self.embedding_client.provider,
                    "model": self.embedding_client.model,
                    "dimensions": self.embedding_client.dimensions,
                })
                missing = 0
                rows = self._conn.execute(
                    "SELECT fact_id, content FROM facts"
                ).fetchall()
                for row in rows:
                    if not self._embedding_current(row["fact_id"], row["content"]):
                        missing += 1
                status["missing_or_stale"] = missing
                chunk_missing = 0
                chunk_rows = self._conn.execute(
                    "SELECT chunk_id, content FROM memory_chunks"
                ).fetchall()
                for row in chunk_rows:
                    if not self._target_embedding_current("chunk", row["chunk_id"], row["content"]):
                        chunk_missing += 1
                status["missing_or_stale_chunks"] = chunk_missing
            return status

    def backfill_embeddings(self, limit: int | None = None) -> dict:
        """Embed facts that are missing or stale for the active embedding backend."""
        if not self.embedding_client:
            return {"enabled": False, "indexed": 0, "skipped": 0}

        with self._lock:
            rows = self._conn.execute(
                "SELECT fact_id, content FROM facts ORDER BY updated_at DESC, fact_id DESC"
            ).fetchall()
            indexed = 0
            skipped = 0
            for row in rows:
                if limit is not None and indexed >= limit:
                    break
                if self._embedding_current(row["fact_id"], row["content"]):
                    skipped += 1
                    continue
                self._embed_fact(row["fact_id"], row["content"])
                indexed += 1
            return {
                "enabled": True,
                "provider": self.embedding_client.provider,
                "model": self.embedding_client.model,
                "indexed": indexed,
                "skipped": skipped,
            }

    def backfill_chunk_embeddings(
        self,
        limit: int | None = None,
        *,
        source_type: str | None = None,
        batch_size: int = 96,
    ) -> dict:
        """Embed document chunks that are missing or stale for the active backend."""
        if not self.embedding_client:
            return {"enabled": False, "indexed": 0, "skipped": 0, "target_type": "chunk"}

        batch_size = max(1, min(int(batch_size or 96), 256))
        clauses = []
        params: list = []
        if source_type:
            clauses.append("d.source_type = ?")
            params.append(source_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT c.chunk_id, c.content
                FROM memory_chunks c
                JOIN memory_documents d ON d.document_id = c.document_id
                {where}
                ORDER BY c.updated_at DESC, c.chunk_id DESC
                """,
                params,
            ).fetchall()

        indexed = 0
        skipped = 0
        pending: list[tuple[int, str, str]] = []
        for row in rows:
            if limit is not None and indexed >= int(limit):
                break
            chunk_id = int(row["chunk_id"])
            content = str(row["content"] or "")
            digest = content_hash(content)
            with self._lock:
                current = self._target_embedding_current("chunk", chunk_id, content)
            if current:
                skipped += 1
                continue
            pending.append((chunk_id, content, digest))
            if len(pending) >= batch_size:
                indexed += self._embed_targets_batch("chunk", pending)
                pending = []
        if pending and (limit is None or indexed < int(limit)):
            indexed += self._embed_targets_batch("chunk", pending)

        self.record_memory_event(
            "memory.chunk_embedding_backfill.complete",
            detail={
                "indexed": indexed,
                "skipped": skipped,
                "source_type": source_type or "",
                "batch_size": batch_size,
                "provider": self.embedding_client.provider,
                "model": self.embedding_client.model,
            },
        )
        return {
            "enabled": True,
            "target_type": "chunk",
            "provider": self.embedding_client.provider,
            "model": self.embedding_client.model,
            "indexed": indexed,
            "skipped": skipped,
            "source_type": source_type or "",
            "batch_size": batch_size,
        }

    def semantic_search(
        self,
        query: str,
        category: str | None = None,
        min_trust: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """Search facts with the active embedding backend."""
        if not self.embedding_client or not query.strip():
            return []

        try:
            from . import activity as memory_activity

            memory_activity.record_event(
                "memory.embedding_search.started",
                message="semantic search started",
                state="embedding",
                step="search",
                status="running",
                data={"provider": self.embedding_client.provider, "model": self.embedding_client.model},
            )
        except Exception:
            memory_activity = None  # type: ignore[assignment]

        query_result = self.embedding_client.embed(query.strip())
        query_vec = query_result.vector
        params: list = [
            "fact",
            self.embedding_client.provider,
            self.embedding_client.model,
            min_trust,
        ]
        category_clause = ""
        if category:
            category_clause = "AND f.category = ?"
            params.append(category)

        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT f.fact_id, f.content, f.category, f.tags, f.trust_score,
                       f.retrieval_count, f.helpful_count, f.created_at, f.updated_at,
                       e.dimensions, e.vector
                FROM memory_embeddings e
                JOIN facts f ON f.fact_id = e.target_id
                WHERE e.target_type = ?
                  AND e.provider = ?
                  AND e.model = ?
                  AND f.trust_score >= ?
                  AND COALESCE(f.status, 'active') = 'active'
                  {category_clause}
                """,
                params,
            ).fetchall()

            scored = []
            for row in rows:
                fact = self._row_to_dict(row)
                try:
                    vec = blob_to_vector(fact.pop("vector"), int(fact.pop("dimensions")))
                except Exception:
                    continue
                sim = max(0.0, cosine_similarity(query_vec, vec))
                trust_score = float(fact.get("trust_score") or 0.0)
                fact["semantic_score"] = sim
                fact["score"] = sim * trust_score
                scored.append(fact)

            scored.sort(key=lambda x: x["score"], reverse=True)
            results = scored[:limit]

        try:
            if memory_activity is not None:  # type: ignore[name-defined]
                memory_activity.record_event(
                    "memory.embedding_search.complete",
                    message=f"semantic search returned {len(results)} result(s)",
                    state="idle",
                    step="search",
                    status="done",
                    data={"hits": len(results), "limit": limit},
                )
        except Exception:
            pass
        return results


    def add_document(
        self,
        source_uri: str,
        title: str = "",
        source_type: str = "document",
        metadata: dict | None = None,
    ) -> int:
        """Create or update a source document record and return document_id."""
        source_uri = str(source_uri or "").strip()
        if not source_uri:
            raise ValueError("source_uri must not be empty")
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_documents (source_type, source_uri, title, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_uri) DO UPDATE SET
                    source_type = excluded.source_type,
                    title = excluded.title,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (str(source_type or "document"), source_uri, str(title or ""), metadata_json),
            )
            row = self._conn.execute(
                "SELECT document_id FROM memory_documents WHERE source_uri = ?",
                (source_uri,),
            ).fetchone()
            self._conn.commit()
            return int(row["document_id"])

    def document_status(
        self,
        document_id: int | None = None,
        source_uri: str | None = None,
        source_type: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Return LightRAG-style document/index status for native document chunks."""
        limit = max(1, min(200, int(limit or 20)))
        where: list[str] = []
        params: list[object] = []
        if document_id is not None:
            where.append("d.document_id = ?")
            params.append(int(document_id))
        if source_uri:
            where.append("d.source_uri = ?")
            params.append(str(source_uri))
        if source_type:
            where.append("d.source_type = ?")
            params.append(str(source_type))
        clause = "WHERE " + " AND ".join(where) if where else ""
        with self._lock:
            counts = self._conn.execute(
                """
                SELECT d.source_type, COUNT(*) AS documents, COALESCE(SUM(chunk_counts.chunks), 0) AS chunks,
                       COALESCE(SUM(chunk_counts.indexed_chunks), 0) AS indexed_chunks,
                       COALESCE(SUM(asset_counts.assets), 0) AS modal_assets
                FROM memory_documents d
                LEFT JOIN (
                    SELECT c.document_id,
                           COUNT(*) AS chunks,
                           SUM(CASE WHEN e.embedding_id IS NOT NULL THEN 1 ELSE 0 END) AS indexed_chunks
                    FROM memory_chunks c
                    LEFT JOIN memory_embeddings e ON e.target_type = 'chunk' AND e.target_id = c.chunk_id
                    GROUP BY c.document_id
                ) chunk_counts ON chunk_counts.document_id = d.document_id
                LEFT JOIN (
                    SELECT document_id, COUNT(*) AS assets
                    FROM memory_modal_assets
                    GROUP BY document_id
                ) asset_counts ON asset_counts.document_id = d.document_id
                GROUP BY d.source_type
                ORDER BY documents DESC
                """
            ).fetchall()
            rows = self._conn.execute(
                f"""
                SELECT d.document_id, d.source_type, d.source_uri, d.title, d.metadata_json,
                       d.created_at, d.updated_at,
                       COUNT(DISTINCT c.chunk_id) AS chunks,
                       COUNT(DISTINCT e.embedding_id) AS indexed_chunks,
                       COUNT(DISTINCT a.asset_id) AS modal_assets
                FROM memory_documents d
                LEFT JOIN memory_chunks c ON c.document_id = d.document_id
                LEFT JOIN memory_embeddings e ON e.target_type = 'chunk' AND e.target_id = c.chunk_id
                LEFT JOIN memory_modal_assets a ON a.document_id = d.document_id
                {clause}
                GROUP BY d.document_id
                ORDER BY d.updated_at DESC
                LIMIT ?
                """,
                params + [limit],
            ).fetchall()
        documents = []
        for row in rows:
            item = self._row_to_dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except Exception:
                item["metadata"] = {}
            chunks = int(item.get("chunks") or 0)
            indexed = int(item.get("indexed_chunks") or 0)
            item["status"] = "indexing" if indexed and indexed < chunks else "processed"
            documents.append(item)
        return {
            "counts": [self._row_to_dict(row) for row in counts],
            "documents": documents,
            "count": len(documents),
        }

    def delete_document(self, document_id: int | None = None, source_uri: str | None = None) -> dict:
        """Delete a native RAG document, chunks, embeddings, modal assets, and relations."""
        if document_id is None and not source_uri:
            raise ValueError("document_id or source_uri is required")
        with self._lock:
            row = None
            if document_id is not None:
                row = self._conn.execute(
                    "SELECT document_id, source_uri FROM memory_documents WHERE document_id = ?",
                    (int(document_id),),
                ).fetchone()
            elif source_uri:
                row = self._conn.execute(
                    "SELECT document_id, source_uri FROM memory_documents WHERE source_uri = ?",
                    (str(source_uri),),
                ).fetchone()
            if not row:
                return {"status": "not_found", "deleted": 0}
            doc_id = int(row["document_id"])
            chunk_rows = self._conn.execute("SELECT chunk_id FROM memory_chunks WHERE document_id = ?", (doc_id,)).fetchall()
            chunk_ids = [int(r["chunk_id"]) for r in chunk_rows]
            for chunk_id in chunk_ids:
                self._conn.execute("DELETE FROM memory_embeddings WHERE target_type = 'chunk' AND target_id = ?", (chunk_id,))
                self._conn.execute(
                    "DELETE FROM memory_relations WHERE source_type = 'chunk' AND source_id = ?",
                    (chunk_id,),
                )
            self._conn.execute("DELETE FROM memory_modal_assets WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM memory_chunks WHERE document_id = ?", (doc_id,))
            self._conn.execute("DELETE FROM memory_documents WHERE document_id = ?", (doc_id,))
            self._conn.commit()
        return {"status": "success", "deleted": 1, "document_id": doc_id, "source_uri": row["source_uri"], "chunks": len(chunk_ids)}

    def add_document_chunks(
        self,
        source_uri: str,
        chunks: list[str],
        title: str = "",
        source_type: str = "document",
        metadata: dict | None = None,
        replace: bool = True,
        modal_assets: list[dict] | None = None,
    ) -> dict:
        """Store chunked document text and optional multimodal summaries for RAG recall."""
        modal_assets = modal_assets or []
        modal_chunks = self._modal_assets_to_chunks(modal_assets)
        cleaned = [" ".join(str(c or "").split()) for c in list(chunks or []) + modal_chunks]
        cleaned = [c for c in cleaned if c]
        document_id = self.add_document(
            source_uri=source_uri,
            title=title,
            source_type=source_type,
            metadata=metadata,
        )
        with self._lock:
            if replace:
                old_rows = self._conn.execute(
                    "SELECT chunk_id FROM memory_chunks WHERE document_id = ?",
                    (document_id,),
                ).fetchall()
                for row in old_rows:
                    self._conn.execute(
                        "DELETE FROM memory_embeddings WHERE target_type = 'chunk' AND target_id = ?",
                        (int(row["chunk_id"]),),
                    )
                self._conn.execute("DELETE FROM memory_chunks WHERE document_id = ?", (document_id,))
                self._conn.execute("DELETE FROM memory_modal_assets WHERE document_id = ?", (document_id,))
            self._store_modal_assets(document_id, modal_assets)
            inserted = 0
            for idx, chunk in enumerate(cleaned):
                excerpt = chunk[:400]
                cur = self._conn.execute(
                    """
                    INSERT INTO memory_chunks (
                        document_id, chunk_index, content, char_count, source_excerpt, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(document_id, chunk_index) DO UPDATE SET
                        content = excluded.content,
                        char_count = excluded.char_count,
                        source_excerpt = excluded.source_excerpt,
                        updated_at = excluded.updated_at
                    """,
                    (document_id, idx, chunk, len(chunk), excerpt),
                )
                chunk_id = int(cur.lastrowid or 0)
                if not chunk_id:
                    row = self._conn.execute(
                        "SELECT chunk_id FROM memory_chunks WHERE document_id = ? AND chunk_index = ?",
                        (document_id, idx),
                    ).fetchone()
                    chunk_id = int(row["chunk_id"])
                self._embed_chunk(chunk_id, chunk)
                self._link_chunk_entities(chunk_id, chunk)
                inserted += 1
            self._conn.commit()
            return {"document_id": document_id, "chunks": inserted, "modal_assets": len(modal_assets)}

    def _modal_assets_to_chunks(self, assets: list[dict]) -> list[str]:
        """Convert multimodal parse artifacts into searchable text chunks."""
        chunks: list[str] = []
        for asset in assets or []:
            if not isinstance(asset, dict):
                continue
            asset_type = str(asset.get("asset_type") or asset.get("type") or "asset").strip() or "asset"
            locator = str(asset.get("locator") or asset.get("page") or asset.get("path") or "").strip()
            summary = str(asset.get("summary") or asset.get("caption") or "").strip()
            text = str(asset.get("text_content") or asset.get("text") or asset.get("content") or "").strip()
            parts = [f"Multimodal {asset_type}"]
            if locator:
                parts.append(f"at {locator}")
            if summary:
                parts.append(f"summary: {summary}")
            if text:
                parts.append(f"text: {text}")
            chunk = ". ".join(parts)
            if summary or text:
                chunks.append(chunk)
        return chunks

    def _store_modal_assets(self, document_id: int, assets: list[dict]) -> None:
        """Persist parsed image/table/equation/page artifacts for future multimodal RAG."""
        for asset in assets or []:
            if not isinstance(asset, dict):
                continue
            metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
            self._conn.execute(
                """
                INSERT INTO memory_modal_assets (
                    document_id, asset_type, locator, summary, text_content, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    int(document_id),
                    str(asset.get("asset_type") or asset.get("type") or "asset"),
                    str(asset.get("locator") or asset.get("page") or asset.get("path") or ""),
                    str(asset.get("summary") or asset.get("caption") or ""),
                    str(asset.get("text_content") or asset.get("text") or asset.get("content") or ""),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

    def document_search(
        self,
        query: str,
        source_type: str | None = None,
        limit: int = 8,
    ) -> list[dict]:
        """Search document chunks using FTS plus optional semantic embeddings."""
        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, int(limit))
        results_by_id: dict[int, dict] = {}

        def add_result(row: sqlite3.Row, score: float, score_name: str) -> None:
            item = self._row_to_dict(row)
            chunk_id = int(item["chunk_id"])
            existing = results_by_id.get(chunk_id)
            if existing:
                existing[score_name] = max(float(existing.get(score_name, 0.0)), score)
                existing["score"] = max(float(existing.get("score", 0.0)), score)
            else:
                item[score_name] = score
                item["score"] = score
                results_by_id[chunk_id] = item

        with self._lock:
            params: list = [query]
            type_clause = ""
            if source_type:
                type_clause = "AND d.source_type = ?"
                params.append(source_type)
            params.append(limit * 4)
            sql = f"""
                SELECT c.chunk_id, c.document_id, c.chunk_index, c.content,
                       c.char_count, c.source_excerpt, d.source_type, d.source_uri,
                       d.title, d.metadata_json, c.updated_at, memory_chunks_fts.rank AS fts_rank_raw
                FROM memory_chunks_fts
                JOIN memory_chunks c ON c.chunk_id = memory_chunks_fts.rowid
                JOIN memory_documents d ON d.document_id = c.document_id
                WHERE memory_chunks_fts MATCH ?
                  {type_clause}
                ORDER BY memory_chunks_fts.rank
                LIMIT ?
            """
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except Exception:
                fallback = self._fallback_fts_query(query)
                rows = self._conn.execute(sql, [fallback, *params[1:]]).fetchall() if fallback else []
            if not rows:
                fallback = self._fallback_fts_query(query)
                if fallback and fallback != query:
                    try:
                        rows = self._conn.execute(sql, [fallback, *params[1:]]).fetchall()
                    except Exception:
                        rows = []
            if rows:
                max_rank = max(abs(float(r["fts_rank_raw"] or 0.0)) for r in rows) or 1.0
                for row in rows:
                    add_result(row, abs(float(row["fts_rank_raw"] or 0.0)) / max_rank, "fts_score")

            if self.embedding_client:
                query_result = self.embedding_client.embed(query)
                emb_params: list = ["chunk", self.embedding_client.provider, self.embedding_client.model]
                emb_type_clause = ""
                if source_type:
                    emb_type_clause = "AND d.source_type = ?"
                    emb_params.append(source_type)
                emb_rows = self._conn.execute(
                    f"""
                    SELECT c.chunk_id, c.document_id, c.chunk_index, c.content,
                           c.char_count, c.source_excerpt, d.source_type, d.source_uri,
                           d.title, d.metadata_json, c.updated_at, e.dimensions, e.vector
                    FROM memory_embeddings e
                    JOIN memory_chunks c ON c.chunk_id = e.target_id
                    JOIN memory_documents d ON d.document_id = c.document_id
                    WHERE e.target_type = ?
                      AND e.provider = ?
                      AND e.model = ?
                      {emb_type_clause}
                    """,
                    emb_params,
                ).fetchall()
                for row in emb_rows:
                    item = self._row_to_dict(row)
                    try:
                        vec = blob_to_vector(item.pop("vector"), int(item.pop("dimensions")))
                    except Exception:
                        continue
                    sim = max(0.0, cosine_similarity(query_result.vector, vec))
                    if sim <= 0:
                        continue
                    add_result(row, sim, "semantic_score")

        ranked_results = sorted(results_by_id.values(), key=lambda r: r.get("score", 0.0), reverse=True)
        results = self._diversify_document_results(ranked_results, limit=limit)
        for item in results:
            item.pop("fts_rank_raw", None)
            if item.get("metadata_json"):
                try:
                    item["metadata"] = json.loads(item["metadata_json"])
                except Exception:
                    item["metadata"] = {}
            item.pop("metadata_json", None)
        return results

    def _diversify_document_results(self, results: list[dict], *, limit: int) -> list[dict]:
        """Prefer high scoring chunks while avoiding one transcript crowding out all context."""
        limit = max(1, int(limit))
        if len(results) <= limit:
            return results[:limit]
        per_document_cap = 1 if limit <= 5 else 2
        selected: list[dict] = []
        per_doc: dict[int, int] = {}
        deferred: list[dict] = []
        for item in results:
            doc_id = int(item.get("document_id") or 0)
            count = per_doc.get(doc_id, 0)
            if doc_id and count >= per_document_cap:
                deferred.append(item)
                continue
            selected.append(item)
            if doc_id:
                per_doc[doc_id] = count + 1
            if len(selected) >= limit:
                return selected
        for item in deferred:
            selected.append(item)
            if len(selected) >= limit:
                break
        return selected[:limit]

    def backfill_graph_relations(self, *, source_type: str | None = None, limit: int | None = None) -> dict:
        """Backfill entity links and co-occurrence relations for existing facts/chunks."""
        started = time.time()
        max_rows = int(limit) if limit is not None else None
        facts_processed = 0
        chunks_processed = 0
        before = self._conn.execute("SELECT COUNT(*) AS count FROM memory_relations").fetchone()
        before_count = int(before["count"] or 0) if before else 0
        with self._lock:
            fact_rows = []
            if not source_type or source_type == "fact":
                fact_sql = """
                    SELECT fact_id, content
                    FROM facts
                    WHERE COALESCE(status, 'active') = 'active'
                    ORDER BY fact_id ASC
                """
                if max_rows:
                    fact_sql += " LIMIT ?"
                    fact_rows = self._conn.execute(fact_sql, (max_rows,)).fetchall()
                else:
                    fact_rows = self._conn.execute(fact_sql).fetchall()
            for row in fact_rows:
                fact_id = int(row["fact_id"])
                self._conn.execute("DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,))
                self._conn.execute("DELETE FROM memory_relations WHERE source_type = 'fact' AND source_id = ?", (fact_id,))
                self._link_fact_entities(fact_id, row["content"] or "")
                facts_processed += 1

            remaining = None if max_rows is None else max(0, max_rows - facts_processed)
            chunk_rows = []
            if source_type != "fact" and (remaining is None or remaining > 0):
                params: list = []
                type_clause = ""
                if source_type and source_type != "chunk":
                    type_clause = "AND d.source_type = ?"
                    params.append(source_type)
                chunk_sql = f"""
                    SELECT c.chunk_id, c.content
                    FROM memory_chunks c
                    JOIN memory_documents d ON d.document_id = c.document_id
                    WHERE 1=1 {type_clause}
                    ORDER BY c.chunk_id ASC
                """
                if remaining:
                    chunk_sql += " LIMIT ?"
                    params.append(remaining)
                chunk_rows = self._conn.execute(chunk_sql, params).fetchall()
            for row in chunk_rows:
                self._link_chunk_entities(int(row["chunk_id"]), row["content"] or "")
                chunks_processed += 1
            self._conn.commit()
        after = self._conn.execute("SELECT COUNT(*) AS count FROM memory_relations").fetchone()
        after_count = int(after["count"] or 0) if after else 0
        result = {
            "facts_processed": facts_processed,
            "chunks_processed": chunks_processed,
            "relations_before": before_count,
            "relations_after": after_count,
            "relations_added": max(0, after_count - before_count),
            "source_type": source_type or "all",
            "seconds": round(time.time() - started, 3),
        }
        self.record_memory_event("memory.relation_backfill.complete", detail=result)
        return result

    def memory_hygiene_report(self, limit: int = 20) -> dict:
        """Return memory maintenance candidates: duplicates, stale, popular, source gaps, contradictions."""
        limit = max(1, int(limit))
        with self._lock:
            popular = [self._row_to_dict(r) for r in self._conn.execute(
                """
                SELECT fact_id, content, category, tags, trust_score, retrieval_count,
                       helpful_count, source_type, source_uri, updated_at
                FROM facts
                WHERE retrieval_count > 0
                ORDER BY retrieval_count DESC, trust_score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()]
            low_trust = [self._row_to_dict(r) for r in self._conn.execute(
                """
                SELECT fact_id, content, category, tags, trust_score, retrieval_count,
                       helpful_count, source_type, source_uri, updated_at
                FROM facts
                WHERE trust_score < 0.3
                ORDER BY trust_score ASC, retrieval_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()]
            source_gaps = [self._row_to_dict(r) for r in self._conn.execute(
                """
                SELECT fact_id, content, category, tags, trust_score, retrieval_count,
                       helpful_count, source_type, source_uri, updated_at
                FROM facts
                WHERE COALESCE(source_type, '') = '' AND COALESCE(source_uri, '') = ''
                ORDER BY retrieval_count DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()]
            duplicate_rows = self._conn.execute(
                """
                SELECT lower(substr(content, 1, 120)) AS signature,
                       COUNT(*) AS count,
                       GROUP_CONCAT(fact_id) AS fact_ids
                FROM facts
                GROUP BY signature
                HAVING count > 1
                ORDER BY count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            duplicates = [self._row_to_dict(r) for r in duplicate_rows]
            superseded = [self._row_to_dict(r) for r in self._conn.execute(
                """
                SELECT fact_id, content, category, tags, trust_score, retrieval_count,
                       helpful_count, source_type, source_uri, updated_at, superseded_by, status
                FROM facts
                WHERE COALESCE(status, 'active') != 'active'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()]
            gaps = [self._row_to_dict(r) for r in self._conn.execute(
                """
                SELECT gap_id, session_id, query, candidate_count, note, created_at
                FROM memory_gaps
                ORDER BY gap_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()]
        return {
            "popular": popular,
            "low_trust": low_trust,
            "source_gaps": source_gaps,
            "duplicates": duplicates,
            "superseded": superseded,
            "gaps": gaps,
        }

    @staticmethod
    def chunk_text(text: str, max_chars: int = 1400, overlap: int = 180) -> list[str]:
        """Simple paragraph-aware chunker for local document RAG."""
        clean = str(text or "").strip()
        if not clean:
            return []
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", clean) if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs or [clean]:
            if len(para) > max_chars:
                if current:
                    chunks.append(current.strip())
                    current = ""
                start = 0
                while start < len(para):
                    chunks.append(para[start:start + max_chars].strip())
                    start += max(1, max_chars - overlap)
                continue
            if len(current) + len(para) + 2 <= max_chars:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append(current.strip())
                prefix = current[-overlap:].strip() if overlap and current else ""
                current = (prefix + "\n\n" + para).strip() if prefix else para
        if current:
            chunks.append(current.strip())
        return chunks

    def _embed_chunk(self, chunk_id: int, content: str) -> None:
        """Create or update the semantic embedding for a document chunk."""
        if not self.embedding_client:
            return
        digest = content_hash(content)
        row = self._conn.execute(
            """
            SELECT content_hash FROM memory_embeddings
            WHERE target_type = 'chunk'
              AND target_id = ?
              AND provider = ?
              AND model = ?
            """,
            (chunk_id, self.embedding_client.provider, self.embedding_client.model),
        ).fetchone()
        if row and row["content_hash"] == digest:
            return
        result = self.embedding_client.embed(content)
        self._conn.execute(
            """
            INSERT INTO memory_embeddings (
                target_type, target_id, provider, model, dimensions,
                content_hash, vector, updated_at
            )
            VALUES ('chunk', ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(target_type, target_id, provider, model) DO UPDATE SET
                dimensions = excluded.dimensions,
                content_hash = excluded.content_hash,
                vector = excluded.vector,
                updated_at = excluded.updated_at
            """,
            (
                chunk_id,
                result.provider,
                result.model,
                result.dimensions,
                digest,
                vector_to_blob(result.vector),
            ),
        )

    @staticmethod
    def _fallback_fts_query(query: str) -> str:
        stop = {
            "a", "an", "and", "are", "can", "did", "does", "for", "how", "i",
            "in", "is", "it", "me", "my", "of", "on", "or", "our", "the", "to",
            "was", "we", "what", "when", "where", "who", "why", "with", "you",
        }
        tokens = []
        for raw in re.findall(r"[A-Za-z0-9_]+", str(query or "").lower()):
            if len(raw) >= 3 and raw not in stop:
                tokens.append(raw)
        deduped = []
        seen = set()
        for token in tokens:
            if token not in seen:
                seen.add(token)
                deduped.append(token)
        return " OR ".join(deduped[:12])

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    def _extract_entities(self, text: str) -> list[str]:
        """Extract entity candidates from text using simple regex rules.

        Rules applied (in order):
        1. Capitalized multi-word phrases  e.g. "John Doe"
        2. Double-quoted terms             e.g. "Python"
        3. Single-quoted terms             e.g. 'pytest'
        4. AKA patterns                    e.g. "Guido aka BDFL" -> two entities

        Returns a deduplicated list preserving first-seen order.
        """
        seen: set[str] = set()
        candidates: list[str] = []

        def _add(name: str) -> None:
            stripped = name.strip()
            if stripped and stripped.lower() not in seen:
                seen.add(stripped.lower())
                candidates.append(stripped)

        for m in _RE_CAPITALIZED.finditer(text):
            _add(m.group(1))

        for m in _RE_DOUBLE_QUOTE.finditer(text):
            _add(m.group(1))

        for m in _RE_SINGLE_QUOTE.finditer(text):
            _add(m.group(1))

        for m in _RE_AKA.finditer(text):
            _add(m.group(1))
            _add(m.group(2))

        return candidates

    def _resolve_entity(self, name: str) -> int:
        """Find an existing entity by name or alias (case-insensitive) or create one.

        Returns the entity_id.
        """
        # Exact name match
        row = self._conn.execute(
            "SELECT entity_id FROM entities WHERE name LIKE ?", (name,)
        ).fetchone()
        if row is not None:
            return int(row["entity_id"])

        # Search aliases — aliases stored as comma-separated; use LIKE with % boundaries
        alias_row = self._conn.execute(
            """
            SELECT entity_id FROM entities
            WHERE ',' || aliases || ',' LIKE '%,' || ? || ',%'
            """,
            (name,),
        ).fetchone()
        if alias_row is not None:
            return int(alias_row["entity_id"])

        # Create new entity
        cur = self._conn.execute(
            "INSERT INTO entities (name) VALUES (?)", (name,)
        )
        self._conn.commit()
        return int(cur.lastrowid)  # type: ignore[return-value]

    def _link_fact_entity(self, fact_id: int, entity_id: int) -> None:
        """Insert into fact_entities, silently ignore if the link already exists."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO fact_entities (fact_id, entity_id)
            VALUES (?, ?)
            """,
            (fact_id, entity_id),
        )
        self._conn.commit()

    def _link_fact_entities(self, fact_id: int, content: str) -> list[int]:
        """Link extracted entities to a fact and upsert co-occurrence relations."""
        entity_ids: list[int] = []
        for name in self._extract_entities(content):
            entity_id = self._resolve_entity(name)
            self._link_fact_entity(fact_id, entity_id)
            if entity_id not in entity_ids:
                entity_ids.append(entity_id)
        self._upsert_cooccurrence_relations(entity_ids, source_type="fact", source_id=int(fact_id), evidence=content)
        return entity_ids

    def _link_chunk_entities(self, chunk_id: int, content: str) -> list[int]:
        """Link extracted entities to a document chunk and upsert co-occurrence relations."""
        entity_ids: list[int] = []
        self._conn.execute("DELETE FROM memory_chunk_entities WHERE chunk_id = ?", (int(chunk_id),))
        self._conn.execute(
            "DELETE FROM memory_relations WHERE source_type = 'chunk' AND source_id = ?",
            (int(chunk_id),),
        )
        for name in self._extract_entities(content):
            entity_id = self._resolve_entity(name)
            self._conn.execute(
                """
                INSERT OR IGNORE INTO memory_chunk_entities (chunk_id, entity_id, weight)
                VALUES (?, ?, 1.0)
                """,
                (int(chunk_id), entity_id),
            )
            if entity_id not in entity_ids:
                entity_ids.append(entity_id)
        self._upsert_cooccurrence_relations(entity_ids, source_type="chunk", source_id=int(chunk_id), evidence=content)
        return entity_ids

    def _upsert_cooccurrence_relations(self, entity_ids: list[int], *, source_type: str, source_id: int, evidence: str) -> None:
        """Create deterministic relation edges between entities found in the same source."""
        unique_ids = sorted({int(eid) for eid in entity_ids if int(eid) > 0})[:12]
        if len(unique_ids) < 2:
            return
        excerpt = " ".join(str(evidence or "").split())[:500]
        for idx, source_entity_id in enumerate(unique_ids):
            for target_entity_id in unique_ids[idx + 1:]:
                self._conn.execute(
                    """
                    INSERT INTO memory_relations (
                        source_entity_id, target_entity_id, relation_type,
                        source_type, source_id, weight, evidence, updated_at
                    ) VALUES (?, ?, 'co_occurs_with', ?, ?, 1.0, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_entity_id, target_entity_id, relation_type, source_type, source_id)
                    DO UPDATE SET
                        weight = memory_relations.weight + 1.0,
                        evidence = excluded.evidence,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (source_entity_id, target_entity_id, str(source_type or ""), int(source_id), excerpt),
                )

    def _compute_hrr_vector(self, fact_id: int, content: str) -> None:
        """Compute and store HRR vector for a fact. No-op if numpy unavailable."""
        with self._lock:
            if not self._hrr_available:
                return

            # Get entities linked to this fact
            rows = self._conn.execute(
                """
                SELECT e.name FROM entities e
                JOIN fact_entities fe ON fe.entity_id = e.entity_id
                WHERE fe.fact_id = ?
                """,
                (fact_id,),
            ).fetchall()
            entities = [row["name"] for row in rows]

            vector = hrr.encode_fact(content, entities, self.hrr_dim)
            self._conn.execute(
                "UPDATE facts SET hrr_vector = ? WHERE fact_id = ?",
                (hrr.phases_to_bytes(vector), fact_id),
            )
            self._conn.commit()

    def _target_embedding_current(self, target_type: str, target_id: int, content: str) -> bool:
        if not self.embedding_client:
            return False
        row = self._conn.execute(
            """
            SELECT content_hash FROM memory_embeddings
            WHERE target_type = ?
              AND target_id = ?
              AND provider = ?
              AND model = ?
            """,
            (target_type, int(target_id), self.embedding_client.provider, self.embedding_client.model),
        ).fetchone()
        return bool(row and row["content_hash"] == content_hash(content))

    def _embed_targets_batch(self, target_type: str, items: list[tuple[int, str, str]]) -> int:
        if not self.embedding_client or not items:
            return 0
        texts = [content for _, content, _ in items]
        results = self.embedding_client.embed_many(texts)
        with self._lock:
            for (target_id, _content, digest), result in zip(items, results):
                self._conn.execute(
                    """
                    INSERT INTO memory_embeddings (
                        target_type, target_id, provider, model, dimensions,
                        content_hash, vector, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(target_type, target_id, provider, model) DO UPDATE SET
                        dimensions = excluded.dimensions,
                        content_hash = excluded.content_hash,
                        vector = excluded.vector,
                        updated_at = excluded.updated_at
                    """,
                    (
                        target_type,
                        int(target_id),
                        result.provider,
                        result.model,
                        result.dimensions,
                        digest,
                        vector_to_blob(result.vector),
                    ),
                )
            self._conn.commit()
        return len(results)

    def _embedding_current(self, fact_id: int, content: str) -> bool:
        return self._target_embedding_current("fact", fact_id, content)

    def _embed_fact(self, fact_id: int, content: str) -> None:
        """Create or update the semantic embedding for a fact."""
        if not self.embedding_client:
            return
        digest = content_hash(content)
        if self._embedding_current(fact_id, content):
            return
        result = self.embedding_client.embed(content)
        self._conn.execute(
            """
            INSERT INTO memory_embeddings (
                target_type, target_id, provider, model, dimensions,
                content_hash, vector, updated_at
            )
            VALUES ('fact', ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(target_type, target_id, provider, model) DO UPDATE SET
                dimensions = excluded.dimensions,
                content_hash = excluded.content_hash,
                vector = excluded.vector,
                updated_at = excluded.updated_at
            """,
            (
                fact_id,
                result.provider,
                result.model,
                result.dimensions,
                digest,
                vector_to_blob(result.vector),
            ),
        )
        self._conn.commit()

    def _rebuild_bank(self, category: str) -> None:
        """Full rebuild of a category's memory bank from all its fact vectors."""
        with self._lock:
            if not self._hrr_available:
                return

            bank_name = f"cat:{category}"
            rows = self._conn.execute(
                "SELECT hrr_vector FROM facts WHERE category = ? AND hrr_vector IS NOT NULL",
                (category,),
            ).fetchall()

            if not rows:
                self._conn.execute("DELETE FROM memory_banks WHERE bank_name = ?", (bank_name,))
                self._conn.commit()
                return

            vectors = [hrr.bytes_to_phases(row["hrr_vector"]) for row in rows]
            bank_vector = hrr.bundle(*vectors)
            fact_count = len(vectors)

            # Check SNR
            hrr.snr_estimate(self.hrr_dim, fact_count)

            self._conn.execute(
                """
                INSERT INTO memory_banks (bank_name, vector, dim, fact_count, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bank_name) DO UPDATE SET
                    vector = excluded.vector,
                    dim = excluded.dim,
                    fact_count = excluded.fact_count,
                    updated_at = excluded.updated_at
                """,
                (bank_name, hrr.phases_to_bytes(bank_vector), self.hrr_dim, fact_count),
            )
            self._conn.commit()

    def rebuild_all_vectors(self, dim: int | None = None) -> int:
        """Recompute all HRR vectors + banks from text. For recovery/migration.

        Returns the number of facts processed.
        """
        with self._lock:
            if not self._hrr_available:
                return 0

            if dim is not None:
                self.hrr_dim = dim

            rows = self._conn.execute(
                "SELECT fact_id, content, category FROM facts"
            ).fetchall()

            categories: set[str] = set()
            for row in rows:
                self._compute_hrr_vector(row["fact_id"], row["content"])
                categories.add(row["category"])

            for category in categories:
                self._rebuild_bank(category)

            return len(rows)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict."""
        return dict(row)

    @staticmethod
    def _trim_journal_text(text: str, max_chars: int) -> str:
        text = str(text or "").strip()
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n[truncated]"

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\-]{2,}", str(text or ""))
        }

    @staticmethod
    def _journal_timestamp(
        created_at: str | datetime | None = None,
        session_day: str | None = None,
    ) -> tuple[str, str]:
        if isinstance(created_at, datetime):
            created_text = created_at.astimezone().isoformat(sep=" ", timespec="seconds")
            derived_day = created_at.astimezone().date().isoformat()
        elif isinstance(created_at, str) and created_at.strip():
            created_text = created_at.strip()
            derived_day = created_text[:10]
        else:
            now = datetime.now().astimezone()
            created_text = now.isoformat(sep=" ", timespec="seconds")
            derived_day = now.date().isoformat()

        day = str(session_day or derived_day).strip()[:10]
        if not day:
            day = datetime.now().astimezone().date().isoformat()
        return created_text, day

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        clean = str(text or "")
        if len(clean) <= max_chars:
            return clean
        return clean[:max_chars].rstrip() + "..."

    @classmethod
    def _safe_json_detail(cls, value):
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                key = str(k)
                if any(secret in key.lower() for secret in ("key", "token", "secret", "password", "authorization")):
                    out[key] = "[REDACTED]"
                else:
                    out[key] = cls._safe_json_detail(v)
            return out
        if isinstance(value, list):
            return [cls._safe_json_detail(v) for v in value[:50]]
        if isinstance(value, str):
            return cls._clip_text(value, 2000)
        return value

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
