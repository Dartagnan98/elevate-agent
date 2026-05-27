-- 0009_response_store.sql — gateway Responses-API LRU cache, ported
-- from ``$ELEVATE_HOME/response_store.db`` (sqlite, 20KB, 2 tables).
--
-- The gateway adapter uses this to reconstruct the full internal
-- conversation history when an OpenAI-Responses client passes
-- ``previous_response_id`` on a follow-up call. ``data`` is the JSON
-- envelope (history, tool calls, tool results) — kept as TEXT to match
-- the legacy schema exactly so the one-shot copy is bytewise lossless.
--
-- LRU eviction is driven by ``accessed_at`` (epoch seconds, double).
-- We keep the same column type to avoid format drift.

CREATE TABLE response_store_responses (
    response_id  TEXT PRIMARY KEY,
    data         TEXT NOT NULL,
    accessed_at  DOUBLE PRECISION NOT NULL
);

CREATE INDEX idx_response_store_responses_accessed
    ON response_store_responses (accessed_at);

CREATE TABLE response_store_conversations (
    name         TEXT PRIMARY KEY,
    response_id  TEXT NOT NULL
);
