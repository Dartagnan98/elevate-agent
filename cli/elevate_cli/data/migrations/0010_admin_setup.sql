-- 0010_admin_setup.sql
-- First-run Admin readiness gate. A realtor must complete this profile before
-- Admin actions, deal creation, task launch, or run drains can start.

CREATE TABLE IF NOT EXISTS admin_setup_profile (
    id                         TEXT PRIMARY KEY,
    realtor_legal_name         TEXT,
    license_name               TEXT,
    brokerage_name             TEXT,
    team_name                  TEXT,
    country                    TEXT NOT NULL DEFAULT 'CA',
    province                   TEXT NOT NULL DEFAULT '',
    market                     TEXT,
    board_memberships_json     TEXT,
    email_provider             TEXT,
    calendar_provider          TEXT,
    drive_provider             TEXT,
    crm_provider               TEXT,
    mls_provider               TEXT,
    forms_provider             TEXT,
    signing_provider           TEXT,
    compliance_provider        TEXT,
    showing_provider           TEXT,
    fintrac_provider           TEXT,
    approval_channel           TEXT,
    managing_broker_email      TEXT,
    default_folder_pattern     TEXT,
    commission_notes           TEXT,
    services_schedule          TEXT,
    regional_memory_json       TEXT,
    approval_policy_json       TEXT,
    completed_at               TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_setup_items (
    key          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    label        TEXT NOT NULL,
    description  TEXT,
    required     INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    status       TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider     TEXT,
    value_json   TEXT,
    notes        TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_setup_items_required_status
    ON admin_setup_items(required, status, sort_order);
