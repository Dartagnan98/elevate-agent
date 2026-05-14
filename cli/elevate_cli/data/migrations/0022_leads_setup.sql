-- 0022_leads_setup.sql
-- Leads onboarding gate. Mirrors admin_setup_items but scoped to inbound
-- lead capture: CRM (reused from admin_setup_profile.crm_provider), lead
-- sources (Meta / Google / website), auto-reply policy. No separate profile
-- table — leads inherits realtor + brokerage + province from admin_setup.

CREATE TABLE IF NOT EXISTS leads_setup_items (
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

CREATE INDEX IF NOT EXISTS idx_leads_setup_items_required_status
    ON leads_setup_items(required, status, sort_order);

CREATE TABLE IF NOT EXISTS leads_setup_state (
    id            TEXT PRIMARY KEY,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
