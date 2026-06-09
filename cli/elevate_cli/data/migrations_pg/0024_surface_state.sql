-- 0024_surface_state.sql
-- Surface heartbeat STATE moves from per-account JSON files
-- (accounts/<key>/heartbeats/{surfaces.json, <surface>/config.json, goals.json,
-- goals_history.jsonl, heartbeat.json, experiments/**.json}) into the account
-- database, so the dashboard cards and the agent's agent_bus tool share one
-- source of truth with tasks/approvals/deals/leads. Markdown artifacts
-- (learnings.md, history/*.md run transcripts, playbooks) stay on disk — they
-- are documents, not state. TEXT/INTEGER only so the SQLite and Postgres data
-- paths stay identical. One-shot file import: _pg_surface_state_migrate.py
-- (sentinel 9010).

CREATE TABLE IF NOT EXISTS surface_registry (
    surface     TEXT PRIMARY KEY,
    spec        TEXT NOT NULL DEFAULT '{}',
    builtin     INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT,
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS surface_state (
    surface     TEXT PRIMARY KEY,
    config      TEXT NOT NULL DEFAULT '{}',
    goals       TEXT NOT NULL DEFAULT '{}',
    heartbeat   TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS surface_goals_history (
    id          TEXT PRIMARY KEY,
    surface     TEXT NOT NULL,
    at          TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_surface_goals_history_surface
    ON surface_goals_history(surface, at);

CREATE TABLE IF NOT EXISTS surface_experiments (
    id          TEXT PRIMARY KEY,
    surface     TEXT NOT NULL,
    cycle       TEXT,
    status      TEXT NOT NULL DEFAULT 'proposed',
    record      TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT,
    updated_at  TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_surface_experiments_surface
    ON surface_experiments(surface, status);
