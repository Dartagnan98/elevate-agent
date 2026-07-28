-- 0038_contacts_recency_segment.sql
--
-- Persist Skyleigh's own follow-up recency segment on each contact so the
-- brew, outreach cadence, and any SQL/report can filter by it (the Leads UI
-- already derives the same chip live in compute-leads-data.ts `deriveTemperature`;
-- this column is the server-side, queryable mirror of that logic).
--
-- Segments (source: her "Lead segment breakdown" doctrine):
--   Hot 0-30d, Warm 30-90d, Lukewarm 90-180d, Cool 180d+ by days-since-last-touch
--   (contacts.last_activity_at); SOI/Past-Client and Nurture come from
--   relationship (crm_stage Client/Sphere/Closed, segments 'Past Clients',
--   or tags soi/sphere/past-client/nurture) and OVERRIDE the recency bucket.
--
-- recency_segment: one of hot|warm|lukewarm|cool|soi|nurture (nullable = not yet computed).
-- recency_segment_set_at: ISO timestamp of the last computation, so a nightly
--   recompute knows staleness. TEXT to stay valid on Postgres + SQLite.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS recency_segment TEXT;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS recency_segment_set_at TEXT;
