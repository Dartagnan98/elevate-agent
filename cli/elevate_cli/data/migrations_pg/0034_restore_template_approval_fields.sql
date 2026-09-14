-- migration 0034: restore rich template fields on the outreach-backed surface
--
-- 0011 replaced the original rich templates table with an outreach_templates
-- table plus a templates compat view. Later admin/template code kept using the
-- richer approval/version columns from 0001. Keep the outreach table as the
-- shared backing store, but make it a superset so both callers work.

BEGIN;

ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS match_rules TEXT;
ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'human';
ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS proposed_by_event_id TEXT;
ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS parent_template_id TEXT;
ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS approved_at TEXT;
ALTER TABLE outreach_templates ADD COLUMN IF NOT EXISTS approved_by TEXT;

UPDATE outreach_templates
SET approved_at = COALESCE(approved_at, updated_at, created_at),
    approved_by = COALESCE(approved_by, 'human:legacy_backfill')
WHERE status = 'live'
  AND (approved_at IS NULL OR approved_by IS NULL);

UPDATE outreach_templates
SET approved_at = NULL
WHERE status = 'proposed'
  AND approved_at IS NOT NULL;

DROP INDEX IF EXISTS uniq_outreach_templates_lane_name;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_outreach_templates_lane_name_version
    ON outreach_templates (lane, name, version);

CREATE INDEX IF NOT EXISTS idx_outreach_templates_status
    ON outreach_templates (status);

CREATE INDEX IF NOT EXISTS idx_outreach_templates_origin
    ON outreach_templates (origin);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_outreach_templates_active'
          AND conrelid = 'outreach_templates'::regclass
    ) THEN
        ALTER TABLE outreach_templates
            ADD CONSTRAINT chk_outreach_templates_active
            CHECK (active IN (0,1));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_outreach_templates_status'
          AND conrelid = 'outreach_templates'::regclass
    ) THEN
        ALTER TABLE outreach_templates
            ADD CONSTRAINT chk_outreach_templates_status
            CHECK (status IN ('active','proposed','live','superseded','retired'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_outreach_templates_origin'
          AND conrelid = 'outreach_templates'::regclass
    ) THEN
        ALTER TABLE outreach_templates
            ADD CONSTRAINT chk_outreach_templates_origin
            CHECK (origin IN ('human','ai_oneoff','ai_pattern','ai_failure_analysis'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_outreach_templates_live_approved'
          AND conrelid = 'outreach_templates'::regclass
    ) THEN
        ALTER TABLE outreach_templates
            ADD CONSTRAINT chk_outreach_templates_live_approved
            CHECK (
                status != 'live'
                OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_outreach_templates_proposed_unapproved'
          AND conrelid = 'outreach_templates'::regclass
    ) THEN
        ALTER TABLE outreach_templates
            ADD CONSTRAINT chk_outreach_templates_proposed_unapproved
            CHECK (status != 'proposed' OR approved_at IS NULL);
    END IF;
END $$;

CREATE OR REPLACE VIEW templates AS SELECT * FROM outreach_templates;

COMMIT;
