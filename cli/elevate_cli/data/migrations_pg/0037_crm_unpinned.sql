-- Full-CRM pass 3: nothing pinned. Pipeline stages become operator-defined
-- (validation moves to the app layer), contacts gain document tracking and a
-- real automation pause, crm_settings gains custom stage config.

-- Stage values are free-form now: the app sanitizes slugs; the CHECK that
-- pinned the stage list is lifted so operator-defined stages persist.
ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_pipeline_status_check;

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS documents_json TEXT;
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS outreach_paused INTEGER NOT NULL DEFAULT 0 CHECK (outreach_paused IN (0, 1));

ALTER TABLE crm_settings ADD COLUMN IF NOT EXISTS custom_stages_json TEXT;
