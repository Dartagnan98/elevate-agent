-- 0040_crm_fork_reconcile.sql
-- Carry the NET schema effect of mainline 0035-0039 forward for installs that
-- never ran those five files.
--
-- Background: Skyleigh's fork shipped its own CRM migrations at 0035-0039
-- (crm_goals, pipeline_stages_expand, contact_items, contacts_recency_segment,
-- contact_documents) before the fork was merged into mainline. Her ledger
-- records those five versions as APPLIED, so `_COMPATIBLE_PRIOR_HASHES` in
-- migrations.py re-labels her rows and skips mainline's 0035-0039 entirely —
-- re-applying them on top of her fork schema would kill her box (mainline
-- 0035_crm_redesign.sql adds a pipeline_status CHECK that rejects the
-- 'attempted' slug her live rows use). Her feature schema was renumbered to
-- 0041-0044 and is already present, but the *mainline-only* schema those five
-- files add is not. This migration supplies exactly that, idempotently.
--
-- Every statement is a no-op on a clean box (which got all of it from
-- 0035-0039 already) and safe to run twice. Net effect only: 0035 added a
-- pipeline_status CHECK and 0037 dropped it again, so the reconciled end state
-- has NO CHECK on that column — validation is app-layer, in
-- elevate_cli/data/contacts.py `is_valid_pipeline_status`. Do not add one back.

-- 1. Pipeline stages are operator-defined (mainline 0037_crm_unpinned).
--    On a clean box this is already gone. On a fork box this drops the widened
--    CHECK her 0036_pipeline_stages_expand left behind, which is what actually
--    lets her 'attempted' rows keep working under mainline code.
ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_pipeline_status_check;

-- 2. Contact-level CRM columns (0035 tags/searches, 0036 custom fields,
--    0037 documents + automation pause, 0038 list membership).
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags_json TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS search_criteria_json TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS custom_fields_json TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS documents_json TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lists_json TEXT;
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS outreach_paused INTEGER NOT NULL DEFAULT 0 CHECK (outreach_paused IN (0, 1));

-- 3. Top 25 rides the same UI-flags table as favorites (0035).
ALTER TABLE lead_profile_flags
    ADD COLUMN IF NOT EXISTS top25 INTEGER NOT NULL DEFAULT 0 CHECK (top25 IN (0, 1));
ALTER TABLE lead_profile_flags ADD COLUMN IF NOT EXISTS top25_at TEXT;
CREATE INDEX IF NOT EXISTS idx_lead_profile_flags_top25
    ON lead_profile_flags(top25, top25_at DESC)
    WHERE top25 = 1;

-- 4. Per-account goal targets read by /reporting and the admin board (0035).
--    Distinct from the fork's crm_goals table (0041), which mainline also
--    ships; both exist by design after the merge.
CREATE TABLE IF NOT EXISTS account_goals (
    id            TEXT PRIMARY KEY DEFAULT 'default',
    leads_goal    INTEGER,
    appts_goal    INTEGER,
    closings_goal INTEGER,
    gci_goal      INTEGER,
    updated_at    TEXT
);

-- 5. Account-level CRM configuration (0036 custom columns, 0037 custom stages,
--    0038 lead lists). CREATE first so the ADD COLUMNs have a table to hit on
--    a fork box; all three are no-ops on a clean box.
CREATE TABLE IF NOT EXISTS crm_settings (
    id                  TEXT PRIMARY KEY DEFAULT 'default',
    custom_columns_json TEXT,
    updated_at          TEXT
);
ALTER TABLE crm_settings ADD COLUMN IF NOT EXISTS custom_stages_json TEXT;
ALTER TABLE crm_settings ADD COLUMN IF NOT EXISTS lead_lists_json TEXT;

-- 6. Chat-session titles are descriptive, not identifying (0039).
DROP INDEX IF EXISTS idx_chat_sessions_title_unique;
