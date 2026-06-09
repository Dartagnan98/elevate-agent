-- 0027_surface_runs.sql
-- The surface-heartbeat run INDEX moves from per-surface history files
-- (accounts/<key>/heartbeats/<surface>/history/*.json — counted by the
-- skill's experiment-cadence check and scanned by web_server for lastRun +
-- the activity feed) into the account database. Markdown transcripts in
-- history/ stay on disk — they are documents; the queryable index is state.
-- One row per run; ``record`` is the full run-record JSON payload and
-- ``kind`` is 'work' | 'experiment'. TEXT/INTEGER only so the SQLite and
-- Postgres data paths stay identical. One-shot lazy file import lives in
-- tools/agent_bus_tool.py, gated by a per-surface ``history/.runs_imported``
-- sentinel marker; the json files are never deleted.

CREATE TABLE IF NOT EXISTS surface_runs (
    id          TEXT PRIMARY KEY,
    surface     TEXT NOT NULL,
    ran_at      TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'work',
    status      TEXT NOT NULL DEFAULT 'ok',
    summary     TEXT,
    record      TEXT
);
CREATE INDEX IF NOT EXISTS idx_surface_runs_surface
    ON surface_runs(surface, ran_at);
CREATE INDEX IF NOT EXISTS idx_surface_runs_ran_at
    ON surface_runs(ran_at);
