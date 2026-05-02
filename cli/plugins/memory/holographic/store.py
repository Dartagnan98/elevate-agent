"""
SQLite-backed fact store with entity resolution and trust scoring.
Single-user Elevate memory store plugin.
"""

import json
import re
import sqlite3
import threading
from datetime import datetime
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
    hrr_vector      BLOB
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
                    INSERT INTO facts (content, category, tags, trust_score)
                    VALUES (?, ?, ?, ?)
                    """,
                    (content, category, tags, self.default_trust),
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

            # Entity extraction and linking
            for name in self._extract_entities(content):
                entity_id = self._resolve_entity(name)
                self._link_fact_entity(fact_id, entity_id)

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
                       f.created_at, f.updated_at
                FROM facts f
                JOIN facts_fts fts ON fts.rowid = f.fact_id
                WHERE facts_fts MATCH ?
                  AND f.trust_score >= ?
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

            # If content changed, re-extract entities
            if content is not None:
                self._conn.execute(
                    "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
                )
                for name in self._extract_entities(content):
                    entity_id = self._resolve_entity(name)
                    self._link_fact_entity(fact_id, entity_id)
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
                       retrieval_count, helpful_count, created_at, updated_at
                FROM facts
                WHERE trust_score >= ?
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
                WHERE mine.entity_id = ?
                  AND other.entity_id != ?
                GROUP BY e.entity_id, e.name
                ORDER BY shared_facts DESC, e.name ASC
                LIMIT ?
                """,
                (entity_id, entity_id, max(1, int(limit))),
            ).fetchall()

        name = row["name"]
        return {
            "entity_id": entity_id,
            "entity": name,
            "entity_type": row["entity_type"],
            "aliases": row["aliases"],
            "exists": True,
            "wiki_link": f"[[{name}]]",
            "facts": [self._row_to_dict(r) for r in fact_rows],
            "related_entities": [
                {
                    "entity": r["name"],
                    "wiki_link": f"[[{r['name']}]]",
                    "shared_facts": int(r["shared_facts"] or 0),
                }
                for r in related_rows
            ],
        }

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
            indexed_facts = 0
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
            else:
                indexed_facts = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE target_type = 'fact'"
                ).fetchone()[0]
            status = {
                "enabled": self.embeddings_enabled(),
                "facts": int(fact_count),
                "indexed_facts": int(indexed_facts),
                "missing_or_stale": 0,
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

    def _embedding_current(self, fact_id: int, content: str) -> bool:
        if not self.embedding_client:
            return False
        row = self._conn.execute(
            """
            SELECT content_hash FROM memory_embeddings
            WHERE target_type = 'fact'
              AND target_id = ?
              AND provider = ?
              AND model = ?
            """,
            (fact_id, self.embedding_client.provider, self.embedding_client.model),
        ).fetchone()
        return bool(row and row["content_hash"] == content_hash(content))

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

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
