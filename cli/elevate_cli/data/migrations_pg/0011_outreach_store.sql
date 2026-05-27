-- migration 0011: outreach store (formerly ~/.elevate/tools/data/outreach/outreach.db)
--
-- The original 0001_pg_init.sql baked in a richer outreach schema
-- (versioned templates, CHECK constraints, conversation_id linkage,
-- source_key uniqueness, FKs from events.template_id) that was never
-- actually wired up — the runtime kept reading/writing the simpler
-- sqlite shape in elevate_cli/outreach_db.py. This migration demotes
-- those stale public.* tables to match the live sqlite shape so the
-- code can finally point at PG.
--
-- A side-table _outreach_template_remap_stash captures the existing
-- (lane, name) -> stale_id mapping BEFORE the templates drop, so the
-- companion python migrator (_pg_outreach_migrate.py, sentinel 9009)
-- can rewrite events.template_id to the freshly-imported live UUIDs.

BEGIN;

-- ---------------------------------------------------------------------------
-- Capture stale template ids so events.template_id can be remapped post-port.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS _outreach_template_remap_stash (
    lane     TEXT NOT NULL,
    name     TEXT NOT NULL,
    stale_id TEXT NOT NULL,
    PRIMARY KEY (lane, name)
);

DO $$
BEGIN
    -- Only fires when public.templates is still the rich 0001-era table.
    -- The 'origin' column is unique to that shape; the sqlite-style
    -- replacement (created below) doesn't have it.
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'templates'
          AND column_name  = 'origin'
    ) THEN
        INSERT INTO _outreach_template_remap_stash (lane, name, stale_id)
        SELECT lane, name, id FROM public.templates
        ON CONFLICT (lane, name) DO NOTHING;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Release FKs from foreign tables, then drop the stale outreach surface.
-- ---------------------------------------------------------------------------

ALTER TABLE events         DROP CONSTRAINT IF EXISTS fk_events_3;
ALTER TABLE events_summary DROP CONSTRAINT IF EXISTS fk_events_summary_1;

DROP TABLE IF EXISTS draft_attempts CASCADE;
DROP TABLE IF EXISTS send_queue     CASCADE;
DROP TABLE IF EXISTS thread_meta    CASCADE;
DROP TABLE IF EXISTS lane_config    CASCADE;
DROP TABLE IF EXISTS inbound_seen   CASCADE;
DROP TABLE IF EXISTS templates      CASCADE;
DROP TABLE IF EXISTS meta           CASCADE;

-- ---------------------------------------------------------------------------
-- Sqlite-shape replacements, prefixed to keep namespace distinct.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS outreach_templates (
    id          TEXT PRIMARY KEY,
    lane        TEXT NOT NULL,
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'any',
    active      INTEGER NOT NULL DEFAULT 1,
    uses        INTEGER NOT NULL DEFAULT 0,
    replies     INTEGER NOT NULL DEFAULT 0,
    wins        INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    rationale   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_templates_lane
    ON outreach_templates (lane, active);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_outreach_templates_lane_name
    ON outreach_templates (lane, name);

CREATE TABLE IF NOT EXISTS outreach_draft_attempts (
    id                  TEXT PRIMARY KEY,
    template_id         TEXT NOT NULL,
    lane                TEXT NOT NULL,
    source_id           TEXT,
    thread_id           TEXT,
    task_id             TEXT,
    status              TEXT NOT NULL DEFAULT 'drafted',
    created_at          TEXT NOT NULL,
    outcome_recorded_at TEXT,
    outcome             TEXT
);
CREATE INDEX IF NOT EXISTS idx_outreach_attempts_template
    ON outreach_draft_attempts (template_id);
CREATE INDEX IF NOT EXISTS idx_outreach_attempts_thread
    ON outreach_draft_attempts (thread_id);

CREATE TABLE IF NOT EXISTS outreach_send_queue (
    id                  TEXT PRIMARY KEY,
    idempotency_key     TEXT NOT NULL UNIQUE,
    source_id           TEXT NOT NULL,
    thread_id           TEXT NOT NULL,
    task_id             TEXT NOT NULL,
    channel             TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'queued',
    attempts            INTEGER NOT NULL DEFAULT 0,
    next_retry_at       TEXT,
    last_error          TEXT,
    provider_message_id TEXT,
    attempt_id          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_send_queue_status
    ON outreach_send_queue (status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_outreach_send_queue_task
    ON outreach_send_queue (source_id, thread_id, task_id);

CREATE TABLE IF NOT EXISTS outreach_thread_meta (
    source_id  TEXT NOT NULL,
    thread_id  TEXT NOT NULL,
    score      INTEGER NOT NULL DEFAULT 0,
    label      TEXT NOT NULL DEFAULT 'unknown',
    reason     TEXT,
    scored_by  TEXT,
    scored_at  TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, thread_id)
);
CREATE INDEX IF NOT EXISTS idx_outreach_thread_meta_label
    ON outreach_thread_meta (label);
CREATE INDEX IF NOT EXISTS idx_outreach_thread_meta_score
    ON outreach_thread_meta (score);

CREATE TABLE IF NOT EXISTS outreach_lane_config (
    lane                  TEXT PRIMARY KEY,
    enabled_channels_json TEXT NOT NULL DEFAULT '[]',
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_inbound_seen (
    toolkit             TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    seen_at             TEXT NOT NULL,
    PRIMARY KEY (toolkit, provider_message_id)
);

CREATE TABLE IF NOT EXISTS outreach_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Compat views so outreach_db.py's unprefixed SQL keeps working.
-- PG promotes simple SELECT-* views to auto-updatable read+write surfaces.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW templates       AS SELECT * FROM outreach_templates;
CREATE OR REPLACE VIEW draft_attempts  AS SELECT * FROM outreach_draft_attempts;
CREATE OR REPLACE VIEW send_queue      AS SELECT * FROM outreach_send_queue;
CREATE OR REPLACE VIEW thread_meta     AS SELECT * FROM outreach_thread_meta;
CREATE OR REPLACE VIEW lane_config     AS SELECT * FROM outreach_lane_config;
CREATE OR REPLACE VIEW inbound_seen    AS SELECT * FROM outreach_inbound_seen;
CREATE OR REPLACE VIEW meta            AS SELECT * FROM outreach_meta;

COMMIT;
