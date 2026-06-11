-- 0023_surface_task_parity.sql
-- Task-bus parity fields on Elevate's native surface_tasks store.

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'agent';

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS created_by TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS org TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS kpi_key TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS due_date TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS archived INTEGER NOT NULL DEFAULT 0;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS result TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS claimed_at TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS claim_owner TEXT;

UPDATE surface_tasks
SET type = 'agent'
WHERE type IS NULL OR type = '';

CREATE INDEX IF NOT EXISTS idx_surface_tasks_archived ON surface_tasks(archived);
CREATE INDEX IF NOT EXISTS idx_surface_tasks_due_date ON surface_tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_surface_tasks_claim_owner ON surface_tasks(claim_owner);

CREATE TABLE IF NOT EXISTS surface_task_events (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    event        TEXT NOT NULL,
    actor        TEXT,
    from_status  TEXT,
    to_status    TEXT,
    note         TEXT,
    payload_json TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_surface_task_events_task_id
    ON surface_task_events(task_id, created_at);
