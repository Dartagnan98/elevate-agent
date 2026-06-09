-- 0026_hub_agents.sql
-- Agent Hub agent definitions move from the per-MACHINE config.yaml
-- (``agent_hub.agents`` list + ``agent_hub.removed_default_agents``
-- housekeeping ids) into the per-ACCOUNT database, the last per-machine
-- state holdout after migrations 0024/0025. One row per agent; ``config``
-- is the full agent config dict as JSON TEXT (same shape the yaml list
-- held). ``builtin=1`` marks a DEFAULT_AGENT_DEFS id. ``removed=1`` rows
-- are tombstones: a REMOVED default parked so reconcile does not re-seed
-- it (replaces the config.yaml removed-ids list). TEXT/INTEGER only so
-- the SQLite and Postgres data paths stay identical. One-shot lazy
-- config.yaml import lives in elevate_cli/agent_hub.py, guarded by a
-- marker row (agent_id='_imported', builtin=0, removed=1); config.yaml
-- is left untouched as a frozen archive.

CREATE TABLE IF NOT EXISTS hub_agents (
    agent_id    TEXT PRIMARY KEY,
    config      TEXT NOT NULL DEFAULT '{}',
    builtin     INTEGER NOT NULL DEFAULT 0,
    removed     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT,
    updated_at  TEXT
);
