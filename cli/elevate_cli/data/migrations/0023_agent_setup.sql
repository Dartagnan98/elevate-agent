-- 0023_agent_setup.sql
-- Top-level Elevate agent onboarding gate. Captures the foundational
-- configuration the runtime needs before it can do anything useful:
-- primary LLM key, embedding model, memory store, operator channels,
-- Composio workspace, sub-agents, image model. Required keys are minimal
-- (primary LLM + embedding + memory); everything else is optional and
-- skippable so the agent can be brought up incrementally.

CREATE TABLE IF NOT EXISTS agent_setup_items (
    key          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    label        TEXT NOT NULL,
    description  TEXT,
    required     INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0,1)),
    status       TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider     TEXT,
    value_json   TEXT,
    notes        TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_setup_items_required_status
    ON agent_setup_items(required, status, sort_order);

CREATE TABLE IF NOT EXISTS agent_setup_state (
    id            TEXT PRIMARY KEY,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
