-- migration 0010: kanban store (formerly ~/.elevate/kanban.db)
--
-- Source schema: elevate_cli/kanban_db.py:SCHEMA_SQL + the additive
-- columns/indexes from _migrate_add_optional_columns. We fold everything
-- into the v1 PG shape — no legacy ALTER table dance needed for fresh PG.
--
-- Six tables back the agentic-dispatch system: tasks (board), task_links
-- (parent/child), task_comments, task_events (audit log), task_runs
-- (historical attempts), kanban_notify_subs (push subscriptions).
--
-- INTEGER PRIMARY KEY AUTOINCREMENT -> BIGINT GENERATED ALWAYS AS IDENTITY.
-- All timestamps stay as BIGINT epoch seconds (the application layer
-- treats them as opaque ints; no datetime() calls in the SQL surface).

BEGIN;

CREATE TABLE IF NOT EXISTS kanban_tasks (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    body                 TEXT,
    assignee             TEXT,
    status               TEXT NOT NULL,
    priority             INTEGER DEFAULT 0,
    created_by           TEXT,
    created_at           BIGINT NOT NULL,
    started_at           BIGINT,
    completed_at         BIGINT,
    workspace_kind       TEXT NOT NULL DEFAULT 'scratch',
    workspace_path       TEXT,
    branch_name          TEXT,
    claim_lock           TEXT,
    claim_expires        BIGINT,
    tenant               TEXT,
    result               TEXT,
    idempotency_key      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    worker_pid           INTEGER,
    last_failure_error   TEXT,
    max_runtime_seconds  INTEGER,
    last_heartbeat_at    BIGINT,
    current_run_id       BIGINT,
    workflow_template_id TEXT,
    current_step_key     TEXT,
    skills               TEXT,
    model_override       TEXT,
    max_retries          INTEGER,
    session_id           TEXT
);

CREATE TABLE IF NOT EXISTS kanban_task_links (
    parent_id  TEXT NOT NULL,
    child_id   TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);

CREATE TABLE IF NOT EXISTS kanban_task_comments (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id    TEXT NOT NULL,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_task_events (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id    TEXT NOT NULL,
    run_id     BIGINT,
    kind       TEXT NOT NULL,
    payload    TEXT,
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS kanban_task_runs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id             TEXT NOT NULL,
    profile             TEXT,
    step_key            TEXT,
    status              TEXT NOT NULL,
    claim_lock          TEXT,
    claim_expires       BIGINT,
    worker_pid          INTEGER,
    max_runtime_seconds INTEGER,
    last_heartbeat_at   BIGINT,
    started_at          BIGINT NOT NULL,
    ended_at            BIGINT,
    outcome             TEXT,
    summary             TEXT,
    metadata            TEXT,
    error               TEXT
);

CREATE TABLE IF NOT EXISTS kanban_notify_subs (
    task_id          TEXT NOT NULL,
    platform         TEXT NOT NULL,
    chat_id          TEXT NOT NULL,
    thread_id        TEXT NOT NULL DEFAULT '',
    user_id          TEXT,
    notifier_profile TEXT,
    created_at       BIGINT NOT NULL,
    last_event_id    BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (task_id, platform, chat_id, thread_id)
);

-- Indexes (matches v1 SCHEMA_SQL + the optional-column migration set).
-- Renamed to a kanban_ prefix to keep them distinct from any same-named
-- index in another module's PG migrations.
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_assignee_status ON kanban_tasks(assignee, status);
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_status          ON kanban_tasks(status);
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_tenant          ON kanban_tasks(tenant);
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_idempotency     ON kanban_tasks(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_kanban_tasks_session_id      ON kanban_tasks(session_id);

CREATE INDEX IF NOT EXISTS idx_kanban_links_child           ON kanban_task_links(child_id);
CREATE INDEX IF NOT EXISTS idx_kanban_links_parent          ON kanban_task_links(parent_id);

CREATE INDEX IF NOT EXISTS idx_kanban_comments_task         ON kanban_task_comments(task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_kanban_events_task           ON kanban_task_events(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_kanban_events_run            ON kanban_task_events(run_id, id);

CREATE INDEX IF NOT EXISTS idx_kanban_runs_task             ON kanban_task_runs(task_id, started_at);
CREATE INDEX IF NOT EXISTS idx_kanban_runs_status           ON kanban_task_runs(status);

CREATE INDEX IF NOT EXISTS idx_kanban_notify_task           ON kanban_notify_subs(task_id);

-- ---------------------------------------------------------------------------
-- Compat views: kanban_db.py issues SQL using unprefixed table names
-- (tasks, task_links, task_comments, task_events, task_runs). Auto-updatable
-- views over the prefixed tables let us keep the application SQL surface
-- untouched. PG promotes simple 1:1 views to read+write automatically.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW tasks         AS SELECT * FROM kanban_tasks;
CREATE OR REPLACE VIEW task_links    AS SELECT * FROM kanban_task_links;
CREATE OR REPLACE VIEW task_comments AS SELECT * FROM kanban_task_comments;
CREATE OR REPLACE VIEW task_events   AS SELECT * FROM kanban_task_events;
CREATE OR REPLACE VIEW task_runs     AS SELECT * FROM kanban_task_runs;

COMMIT;
