-- 0025_surface_activity.sql
-- The agent activity feed moves from the per-account JSONL file
-- ($ELEVATE_HOME/data/agent_activity.jsonl, appended/read by the agent_bus
-- tool's post_activity/list_activity actions) into the account database —
-- the last file-based surface-state holdout after migration 0024. One row
-- per event; ``metadata`` is a JSON TEXT payload carrying the record's
-- category/severity/kind alongside the caller-supplied metadata dict.
-- TEXT/INTEGER only so the SQLite and Postgres data paths stay identical.
-- One-shot lazy file import lives in tools/agent_bus_tool.py, gated by an
-- ``agent_activity.jsonl.imported`` sentinel marker; the jsonl is never
-- deleted.

CREATE TABLE IF NOT EXISTS surface_activity (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    event       TEXT NOT NULL,
    message     TEXT,
    metadata    TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_surface_activity_agent
    ON surface_activity(agent, at);
CREATE INDEX IF NOT EXISTS idx_surface_activity_at
    ON surface_activity(at);
