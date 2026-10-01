-- migration 0035: drip campaigns
--
-- Dashboard-managed drip campaigns for the Leads pack. The Elevation
-- templates (The First 14 Days, Warm / Lukewarm / Long-Term Nurture, the Bad
-- Number Drip, the Buyer and Seller Courses, the Hot Leads / Top 25 / Raving
-- Fan Club playbooks and the Video Script Library) are seeded by
-- ``elevate_cli.drips_db`` from ``elevate_cli.drip_templates``; every row is
-- editable so each install can rename segments, tweak copy, switch campaigns
-- on and off, or build its own from scratch.
--
-- Model:
--   drip_segments          the pipeline segments (tags) a contact can be in
--   drip_campaigns         a campaign (nurture / course / playbook / custom)
--   drip_steps             the day-by-day touches inside a campaign
--   drip_contact_segments  which segment each contact is in right now
--   drip_enrollments       a contact running through a campaign
--   drip_touches           the materialised schedule for one enrollment
--   drip_videos            the shared video script library
--   drip_settings          engine settings (send window, auto-enroll, ...)

BEGIN;

CREATE TABLE IF NOT EXISTS drip_segments (
    key           TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    description   TEXT,
    window_label  TEXT,
    color         TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    builtin       INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0,1)),
    enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drip_campaigns (
    id               TEXT PRIMARY KEY,
    slug             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    description      TEXT,
    kind             TEXT NOT NULL DEFAULT 'nurture'
                         CHECK (kind IN ('nurture','course','playbook','custom')),
    role             TEXT NOT NULL DEFAULT 'primary'
                         CHECK (role IN ('primary','layer')),
    trigger_segment  TEXT,
    layer_flag       TEXT CHECK (layer_flag IS NULL OR layer_flag IN ('buying','selling')),
    defer_layers     INTEGER NOT NULL DEFAULT 0 CHECK (defer_layers IN (0,1)),
    run_once         INTEGER NOT NULL DEFAULT 0 CHECK (run_once IN (0,1)),
    enabled          INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    template_slug    TEXT,
    source_url       TEXT,
    exit_day         INTEGER,
    exit_rule        TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drip_campaigns_trigger
    ON drip_campaigns (trigger_segment, enabled);

CREATE TABLE IF NOT EXISTS drip_steps (
    id           TEXT PRIMARY KEY,
    campaign_id  TEXT NOT NULL REFERENCES drip_campaigns(id) ON DELETE CASCADE,
    day          INTEGER NOT NULL CHECK (day >= 1),
    sort_order   INTEGER NOT NULL DEFAULT 0,
    channel      TEXT NOT NULL CHECK (channel IN ('text','email','call','task','tag')),
    title        TEXT NOT NULL,
    subject      TEXT,
    body         TEXT,
    video_slot   TEXT,
    notes        TEXT,
    route_to     TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drip_steps_campaign
    ON drip_steps (campaign_id, day, sort_order);

CREATE TABLE IF NOT EXISTS drip_contact_segments (
    contact_id   TEXT PRIMARY KEY,
    segment_key  TEXT NOT NULL,
    set_at       TEXT NOT NULL,
    set_by       TEXT NOT NULL,
    note         TEXT,
    buying       INTEGER NOT NULL DEFAULT 0 CHECK (buying IN (0,1)),
    selling      INTEGER NOT NULL DEFAULT 0 CHECK (selling IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_drip_contact_segments_key
    ON drip_contact_segments (segment_key);

CREATE TABLE IF NOT EXISTS drip_enrollments (
    id            TEXT PRIMARY KEY,
    campaign_id   TEXT NOT NULL REFERENCES drip_campaigns(id) ON DELETE CASCADE,
    contact_id    TEXT NOT NULL,
    start_date    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','paused','completed','stopped')),
    stop_reason   TEXT,
    enrolled_by   TEXT NOT NULL,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drip_enrollments_contact
    ON drip_enrollments (contact_id, status);
CREATE INDEX IF NOT EXISTS idx_drip_enrollments_campaign
    ON drip_enrollments (campaign_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_drip_enrollments_live
    ON drip_enrollments (campaign_id, contact_id)
    WHERE status IN ('active','paused');

CREATE TABLE IF NOT EXISTS drip_touches (
    id             TEXT PRIMARY KEY,
    enrollment_id  TEXT NOT NULL REFERENCES drip_enrollments(id) ON DELETE CASCADE,
    step_id        TEXT NOT NULL REFERENCES drip_steps(id) ON DELETE CASCADE,
    due_date       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'scheduled'
                       CHECK (status IN ('scheduled','done','skipped','cancelled')),
    done_at        TEXT,
    note           TEXT,
    task_id        TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drip_touches_due
    ON drip_touches (status, due_date);
CREATE INDEX IF NOT EXISTS idx_drip_touches_enrollment
    ON drip_touches (enrollment_id, due_date);

CREATE TABLE IF NOT EXISTS drip_videos (
    slug          TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    length_label  TEXT,
    script        TEXT,
    used_in       TEXT,
    link          TEXT,
    recorded_at   TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    builtin       INTEGER NOT NULL DEFAULT 0 CHECK (builtin IN (0,1)),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drip_settings (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

COMMIT;
