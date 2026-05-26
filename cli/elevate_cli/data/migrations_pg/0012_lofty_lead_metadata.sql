-- 0012_lofty_lead_metadata.sql
-- Adds the last batch of Lofty lead-level metadata that the contacts
-- table didn't already cover, so the Lofty CRM sync can stop dropping
-- ~90% of every lead on the floor.
--
-- Before this migration, `upsert_contact` only persisted name + email +
-- phone + (default) stage. The Lofty sync builds a full base_record
-- (stage label, lead source string, assigned agent name, score, tags)
-- and then loses every field except the four above on the JSONL→DB
-- writethrough. Result: the /leads drawer shows "Not yet scored",
-- "No notes yet", default 'cold' stage on every Lofty lead, even though
-- the API returned all of it.
--
-- The migration 0017_contacts_lofty_fields.sql (already folded into
-- 0001_pg_init.sql) added consent flags, qualification fields, pond and
-- lead_types/segments JSON. This migration covers what was still
-- missing:
--
-- - lead_source       free-text source label ("Zillow", "Facebook Ad",
--                     "Past Client Referral") — Lofty: `source`
-- - assigned_agent    human name of the agent the lead is routed to —
--                     Lofty: `assignedUser` (string). `crm_user_id` was
--                     already in the schema for the int64 user id, but
--                     no slot for the display label.
-- - crm_stage         Lofty's lifecycle stage label ("New", "Nurture",
--                     "Qualified", "Working", ...). Distinct from our
--                     own `stage` column which is a hot/warm/cold lane
--                     marker the autopilot writes.
-- - lead_score        Lofty's lead score (0-100, behavioural signal).
--                     Distinct from `heat_score` which is Elevate's own
--                     computed temperature.
-- - tags_json         JSON array of tag names attached in Lofty —
--                     `tags[].tagName`. Lofty tags drive routing
--                     buckets ("VIP", "Investor", "Cold Open House
--                     2024"), so the drawer needs to surface them.
--
-- All columns are nullable / additive. Existing rows stay legal until
-- the next Lofty sync backfills them. The follow-on migration walks
-- the snapshot JSONL and patches existing rows in place.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS lead_source TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS assigned_agent TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS crm_stage TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS lead_score INTEGER
        CHECK (lead_score IS NULL OR (lead_score BETWEEN 0 AND 100));

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS tags_json TEXT;

-- Light indexes for the /leads filter UI (source dropdown, agent
-- dropdown). Both are low-cardinality, so plain btree is fine.
CREATE INDEX IF NOT EXISTS idx_contacts_lead_source
    ON contacts(lead_source) WHERE lead_source IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_assigned_agent
    ON contacts(assigned_agent) WHERE assigned_agent IS NOT NULL;
