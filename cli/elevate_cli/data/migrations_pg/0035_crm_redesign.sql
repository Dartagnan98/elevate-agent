-- CRM redesign (design/crm-redesign): realtor pipeline stages, contact tags,
-- Top 25 flag, and per-account goals for /reporting.

-- 1. Widen pipeline stages to the realtor pipeline. Legacy values stay valid
--    so existing rows and old writers keep working; the UI maps them.
ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_pipeline_status_check;
ALTER TABLE contacts ADD CONSTRAINT contacts_pipeline_status_check
    CHECK (pipeline_status IS NULL OR pipeline_status IN (
        'new_lead', 'follow_up', 'ghosting', 'dead',
        'closed_seller', 'closed_buyer',
        'attempted_contact', 'prospect', 'client', 'pending_deal',
        'closed', 'referred', 'realtor_contact', 'trash'
    ));

-- 2. Multi-value tags + saved-search criteria on the contact
--    (grouped tag picker on the card, tag filter on the list, Searches tab).
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags_json TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS search_criteria_json TEXT;

-- 3. Top 25 rides the same UI-flags table as favorites.
ALTER TABLE lead_profile_flags
    ADD COLUMN IF NOT EXISTS top25 INTEGER NOT NULL DEFAULT 0 CHECK (top25 IN (0, 1));
ALTER TABLE lead_profile_flags ADD COLUMN IF NOT EXISTS top25_at TEXT;
CREATE INDEX IF NOT EXISTS idx_lead_profile_flags_top25
    ON lead_profile_flags(top25, top25_at DESC)
    WHERE top25 = 1;

-- 4. Per-account goal targets read by /reporting and the admin board.
CREATE TABLE IF NOT EXISTS account_goals (
    id            TEXT PRIMARY KEY DEFAULT 'default',
    leads_goal    INTEGER,
    appts_goal    INTEGER,
    closings_goal INTEGER,
    gci_goal      INTEGER,
    updated_at    TEXT
);
