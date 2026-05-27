-- 0005_chat_sessions.sql — chat session + message store (PG side).
--
-- Adds PG-side tables that mirror state.db's sessions / messages / state_meta.
-- This migration creates the schema and backfill target. The SessionDB
-- cutover (porting elevate_state.SessionDB to write here instead of
-- state.db) is queued as a follow-up — until that ships, these tables
-- are populated only by the one-shot backfill and by new code paths
-- that explicitly opt in (data/chat_sessions.py helper).
--
-- Backfill: elevate_cli/data/_aux_data_migrate.py copies state.db
-- + any orphan JSONL frames not yet in messages.
--
-- NOTE on naming: kept the column names identical to the SQLite originals
-- (no rename) so the eventual SessionDB cutover is a connection swap, not
-- a column-rename. messages.id stays a BIGSERIAL to preserve insert order.

CREATE TABLE IF NOT EXISTS chat_sessions (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    user_id             TEXT,
    model               TEXT,
    model_config        TEXT,
    system_prompt       TEXT,
    parent_session_id   TEXT REFERENCES chat_sessions(id),
    started_at          DOUBLE PRECISION NOT NULL,
    ended_at            DOUBLE PRECISION,
    end_reason          TEXT,
    message_count       INTEGER NOT NULL DEFAULT 0,
    tool_call_count     INTEGER NOT NULL DEFAULT 0,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens    INTEGER NOT NULL DEFAULT 0,
    billing_provider    TEXT,
    billing_base_url    TEXT,
    billing_mode        TEXT,
    estimated_cost_usd  DOUBLE PRECISION,
    actual_cost_usd     DOUBLE PRECISION,
    cost_status         TEXT,
    cost_source         TEXT,
    pricing_version     TEXT,
    title               TEXT,
    api_call_count      INTEGER NOT NULL DEFAULT 0,
    handoff_state       TEXT,
    handoff_platform    TEXT,
    handoff_error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_source   ON chat_sessions(source);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_parent   ON chat_sessions(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_started  ON chat_sessions(started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_title_unique
    ON chat_sessions(title) WHERE title IS NOT NULL;

CREATE TABLE IF NOT EXISTS chat_messages (
    id                      BIGSERIAL PRIMARY KEY,
    session_id              TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role                    TEXT NOT NULL,
    content                 TEXT,
    tool_call_id            TEXT,
    tool_calls              TEXT,
    tool_name               TEXT,
    timestamp               DOUBLE PRECISION NOT NULL,
    token_count             INTEGER,
    finish_reason           TEXT,
    reasoning               TEXT,
    reasoning_content       TEXT,
    reasoning_details       TEXT,
    codex_reasoning_items   TEXT,
    codex_message_items     TEXT,
    platform_message_id     TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_chat_messages_platform_msg_id
    ON chat_messages(session_id, platform_message_id)
    WHERE platform_message_id IS NOT NULL;

-- PG full-text search on content (replaces SQLite FTS4/FTS5 triggers).
-- Generated column keeps tsvector in sync without explicit triggers.
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english',
            left(coalesce(content, ''), 100000) || ' ' ||
            coalesce(tool_name, '') || ' ' ||
            left(coalesce(tool_calls, ''), 100000)
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_chat_messages_content_tsv
    ON chat_messages USING GIN (content_tsv);

CREATE TABLE IF NOT EXISTS chat_state_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
