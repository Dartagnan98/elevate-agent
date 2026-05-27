-- 0004_usage_ledger.sql — per-turn gateway usage ledger.
--
-- Replaces both the vestigial ~/.elevate/usage_ledger.sqlite file and the
-- turn_usage table that was living inside state.db. Once the state.db
-- session cutover lands, the legacy table can be dropped from state.db.
--
-- Backfill is handled by elevate_cli/data/_aux_data_migrate.py.

CREATE TABLE IF NOT EXISTS turn_usage (
    id                                  BIGSERIAL PRIMARY KEY,
    timestamp                           DOUBLE PRECISION NOT NULL,
    session_id                          TEXT,
    session_key                         TEXT,
    message_id                          TEXT,
    source                              TEXT,
    provider                            TEXT,
    model                               TEXT,
    gateway_tool_profile                TEXT,
    gateway_tool_profile_reason         TEXT,
    selected_toolsets                   TEXT,
    requested_toolsets                  TEXT,
    configured_toolsets                 TEXT,
    loaded_tool_count                   INTEGER NOT NULL DEFAULT 0,
    selected_tool_schema_tokens         INTEGER NOT NULL DEFAULT 0,
    configured_tool_schema_tokens       INTEGER NOT NULL DEFAULT 0,
    estimated_tool_schema_savings_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_tool_schema_savings_pct   DOUBLE PRECISION,
    input_tokens                        INTEGER NOT NULL DEFAULT 0,
    output_tokens                       INTEGER NOT NULL DEFAULT 0,
    total_tokens                        INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens                   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens                  INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens                    INTEGER NOT NULL DEFAULT 0,
    api_calls                           INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd                  DOUBLE PRECISION,
    cost_status                         TEXT,
    cost_source                         TEXT,
    latency_ms                          INTEGER NOT NULL DEFAULT 0,
    tool_calls                          TEXT,
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                              TEXT NOT NULL DEFAULT 'ok',
    error_type                          TEXT
);

CREATE INDEX IF NOT EXISTS idx_turn_usage_timestamp
    ON turn_usage(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turn_usage_session
    ON turn_usage(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turn_usage_source
    ON turn_usage(source, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turn_usage_profile
    ON turn_usage(gateway_tool_profile, timestamp DESC);

-- Partial dedup index: only enforce uniqueness when all three fields are non-empty.
CREATE UNIQUE INDEX IF NOT EXISTS idx_turn_usage_dedup
    ON turn_usage(source, session_key, message_id)
    WHERE source <> '' AND session_key <> '' AND message_id <> '';
