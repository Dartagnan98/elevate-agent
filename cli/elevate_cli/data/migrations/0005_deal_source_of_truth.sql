-- 0005_deal_source_of_truth.sql
-- Grow Admin Hub deals from kanban cards into the durable transaction file.

ALTER TABLE deals ADD COLUMN board TEXT;
ALTER TABLE deals ADD COLUMN market TEXT;
ALTER TABLE deals ADD COLUMN listing_date TEXT;
ALTER TABLE deals ADD COLUMN offer_date TEXT;
ALTER TABLE deals ADD COLUMN subject_removal_date TEXT;
ALTER TABLE deals ADD COLUMN deposit_due_date TEXT;
ALTER TABLE deals ADD COLUMN completion_date TEXT;
ALTER TABLE deals ADD COLUMN possession_date TEXT;
ALTER TABLE deals ADD COLUMN anniversary_date TEXT;
ALTER TABLE deals ADD COLUMN list_price REAL;
ALTER TABLE deals ADD COLUMN offer_price REAL;
ALTER TABLE deals ADD COLUMN deposit_amount REAL;
ALTER TABLE deals ADD COLUMN commission_pct REAL;
ALTER TABLE deals ADD COLUMN mls_number TEXT;
ALTER TABLE deals ADD COLUMN legal_description TEXT;
ALTER TABLE deals ADD COLUMN lot_size_sqft REAL;
ALTER TABLE deals ADD COLUMN year_built INTEGER;
ALTER TABLE deals ADD COLUMN deposit_in_trust_at TEXT;
ALTER TABLE deals ADD COLUMN listing_published_at TEXT;
ALTER TABLE deals ADD COLUMN offer_accepted_at TEXT;
ALTER TABLE deals ADD COLUMN subjects_removed_at TEXT;
ALTER TABLE deals ADD COLUMN completed_at TEXT;

CREATE INDEX IF NOT EXISTS idx_deals_jurisdiction_status
    ON deals(province, board, market, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_deals_province_status
    ON deals(province, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_deals_subject_removal
    ON deals(subject_removal_date) WHERE subject_removal_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deals_completion
    ON deals(completion_date) WHERE completion_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deals_possession
    ON deals(possession_date) WHERE possession_date IS NOT NULL;

CREATE TABLE IF NOT EXISTS deal_contacts (
    id          TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    contact_id  TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,

    FOREIGN KEY(deal_id)    REFERENCES deals(id)    ON DELETE CASCADE,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
    UNIQUE(deal_id, role, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_deal_contacts_deal_role
    ON deal_contacts(deal_id, role);
CREATE INDEX IF NOT EXISTS idx_deal_contacts_contact
    ON deal_contacts(contact_id);

CREATE TABLE IF NOT EXISTS deal_attachments (
    id                  TEXT PRIMARY KEY,
    deal_id             TEXT NOT NULL,
    kind                TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    summary             TEXT,
    source_run_id       TEXT,
    source_snapshot_id  TEXT,
    created_at          TEXT NOT NULL,

    FOREIGN KEY(deal_id) REFERENCES deals(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_deal_attachments_deal_kind
    ON deal_attachments(deal_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_attachments_source_run
    ON deal_attachments(source_run_id) WHERE source_run_id IS NOT NULL;

-- Expand deal_events kinds without editing 0003.
PRAGMA foreign_keys=off;
CREATE TABLE IF NOT EXISTS deal_events_new (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT NOT NULL,
    kind            TEXT NOT NULL
                        CHECK (kind IN (
                            'created','stage_transition','toggle_change',
                            'run_result','attachment_added','contact_linked'
                        )),
    actor           TEXT NOT NULL,
    from_stage      INTEGER CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9),
    to_stage        INTEGER CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9),
    field_name      TEXT,
    old_value_json  TEXT,
    new_value_json  TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL,

    FOREIGN KEY(deal_id) REFERENCES deals(id) ON DELETE CASCADE,
    CHECK (kind != 'stage_transition' OR to_stage IS NOT NULL),
    CHECK (kind != 'toggle_change' OR field_name IS NOT NULL)
);
INSERT INTO deal_events_new(
    id, deal_id, kind, actor, from_stage, to_stage, field_name,
    old_value_json, new_value_json, payload_json, created_at
)
SELECT
    id, deal_id, kind, actor, from_stage, to_stage, field_name,
    old_value_json, new_value_json, payload_json, created_at
FROM deal_events;
DROP TABLE deal_events;
ALTER TABLE deal_events_new RENAME TO deal_events;
CREATE INDEX IF NOT EXISTS idx_deal_events_deal_created
    ON deal_events(deal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_events_kind_created
    ON deal_events(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_events_field_created
    ON deal_events(field_name, created_at)
    WHERE field_name IS NOT NULL;

-- Expand admin_action_runs statuses and add harness bridge.
CREATE TABLE IF NOT EXISTS admin_action_runs_new (
    id              TEXT PRIMARY KEY,
    registry_id     TEXT NOT NULL,
    deal_id         TEXT NOT NULL,
    deal_event_id   TEXT,
    cron_job_id     TEXT,
    harness_run_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN (
                            'queued','running','succeeded','completed',
                            'failed','skipped','cancelled',
                            'waiting_human','waiting_external'
                        )),
    output_path     TEXT,
    error_message   TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT,

    FOREIGN KEY(registry_id)   REFERENCES admin_action_registry(id) ON DELETE CASCADE,
    FOREIGN KEY(deal_id)       REFERENCES deals(id)                  ON DELETE CASCADE,
    FOREIGN KEY(deal_event_id) REFERENCES deal_events(id)            ON DELETE SET NULL
);
INSERT INTO admin_action_runs_new(
    id, registry_id, deal_id, deal_event_id, cron_job_id, harness_run_id,
    status, output_path, error_message, payload_json,
    created_at, updated_at, completed_at
)
SELECT
    id, registry_id, deal_id, deal_event_id, cron_job_id, NULL,
    status, output_path, error_message, payload_json,
    created_at, updated_at, completed_at
FROM admin_action_runs;
DROP TABLE admin_action_runs;
ALTER TABLE admin_action_runs_new RENAME TO admin_action_runs;
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_deal_created
    ON admin_action_runs(deal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_status_created
    ON admin_action_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_registry_created
    ON admin_action_runs(registry_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_harness
    ON admin_action_runs(harness_run_id) WHERE harness_run_id IS NOT NULL;
PRAGMA foreign_keys=on;
