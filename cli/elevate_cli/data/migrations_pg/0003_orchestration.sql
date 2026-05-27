-- 0003_orchestration.sql — moves orchestration.db into the operational store.
--
-- Replaces the standalone SQLite file at ~/.elevate/orchestration.db.
-- Backfill is handled by elevate_cli/data/_aux_data_migrate.py.

CREATE TABLE IF NOT EXISTS orchestration_agents (
    agent_id        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT '',
    tier            TEXT NOT NULL DEFAULT 'specialist',
    reports_to      TEXT,
    lane            TEXT NOT NULL DEFAULT '',
    org             TEXT NOT NULL DEFAULT 'standalone',
    enabled         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'ready',
    current_task    TEXT,
    last_seen_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_orchestration_agents_org
    ON orchestration_agents(org);

CREATE TABLE IF NOT EXISTS orchestration_runs (
    run_id              TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL,
    parent_run_id       TEXT,
    parent_session_key  TEXT,
    session_key         TEXT,
    task                TEXT NOT NULL,
    status              TEXT NOT NULL,
    mode                TEXT NOT NULL DEFAULT 'manual',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    started_at          TEXT,
    completed_at        TEXT,
    summary             TEXT,
    error               TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_orchestration_runs_agent
    ON orchestration_runs(agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_orchestration_runs_status
    ON orchestration_runs(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS orchestration_events (
    event_seq   BIGSERIAL PRIMARY KEY,
    event_id    TEXT NOT NULL UNIQUE,
    run_id      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,
    message     TEXT,
    data_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_orchestration_events_run
    ON orchestration_events(run_id, event_seq ASC);
