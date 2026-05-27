-- 0013_xposure_enrichment.sql
-- Buyer-brief enrichment + activity-tier denormalization on contacts.
--
-- Background: the xposure-pcs MLS scraper drops raw buyer-search criteria
-- into `pcs_buyers.searches_json` (an array of {price, beds, area, ...}
-- search definitions). Nothing reads that JSON into a human-readable brief,
-- so /leads cards show only a generic "buyer interested" line for what is
-- actually a high-intent MLS private-search hit.
--
-- This migration adds four columns on `contacts` so the enrichment cron
-- and the dashboard don't have to re-derive the same summary on every read:
--
--   enrichment_brief    TEXT          human-readable buyer brief
--                                       ("$800k-$1.2M, 3+ bed, Aberdeen +
--                                        Westsyde, last search 6d ago,
--                                        14 searches in 90d")
--   activity_tier       TEXT          'active' | 'warm' | 'dormant' |
--                                     'never-touched'
--   last_search_at      TIMESTAMPTZ   most recent buyer search timestamp.
--                                     Denormalized from pcs_buyers /
--                                     lead_signals so the /leads filter
--                                     scans don't have to join across.
--   search_count_90d    INTEGER       count of buyer-search events in the
--                                     last 90d. Used by the tier bucketer.
--
-- All four are machine-set fields. The enrichment cron is the ONLY writer;
-- operators never edit them through the dashboard, and the connector
-- writethrough path never touches them. Keeps the boundary between
-- machine state and human-edited fields (display_name, notes, tags) clean.
--
-- Indexes target the /leads activity-tier filter and the outreach flagger
-- query "contacts with new searches in the last N days".
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, safe to re-run on partially-
-- migrated installs. Matches the pattern in 0012_lofty_lead_metadata.sql.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS enrichment_brief TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS activity_tier TEXT
        CHECK (activity_tier IS NULL OR activity_tier IN
            ('active','warm','dormant','never-touched'));

-- TIMESTAMPTZ (not TEXT) because /leads sweeps order by this column and
-- the outreach flagger filters on `last_search_at >= now() - interval`.
-- Storing as text would force a cast on every read.
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS last_search_at TIMESTAMPTZ;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS search_count_90d INTEGER NOT NULL DEFAULT 0;

-- Filtered index: /leads activity-tier filter only ever cares about
-- contacts with a tier set. Keeps index size proportional to enriched
-- contacts, not the full pool (which includes 240k+ Apple Messages rows
-- with no buyer-search signal at all).
CREATE INDEX IF NOT EXISTS idx_contacts_activity_tier
    ON contacts(activity_tier, last_search_at DESC NULLS LAST)
    WHERE activity_tier IS NOT NULL;

-- For the outreach flagger's "recent new searches" sweep.
CREATE INDEX IF NOT EXISTS idx_contacts_last_search_at
    ON contacts(last_search_at DESC)
    WHERE last_search_at IS NOT NULL;
