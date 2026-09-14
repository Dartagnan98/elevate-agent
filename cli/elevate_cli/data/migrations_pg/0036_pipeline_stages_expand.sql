-- 0036_pipeline_stages_expand.sql
-- Expand contacts.pipeline_status to the UNION of the AI's 6 legacy slugs and
-- Skyleigh's operator-facing 9-stage pipeline.
--
-- Background: the original CHECK constraint (0001_pg_init.sql, inline on the
-- contacts table so Postgres auto-named it `contacts_pipeline_status_check`)
-- allowed only the 6 values written by the AI classifier + sync pipeline:
--   new_lead, follow_up, ghosting, dead, closed_seller, closed_buyer.
-- The AI keeps writing those. Skyleigh's operator pipeline adds 8 new slugs
-- (New Lead reuses new_lead): attempted, prospect, client, pending_deal,
-- closed, referred, realtor_contact, trash. The UI displays legacy values in
-- her vocabulary via a display map; the DB just needs to accept both sets.
--
-- We do NOT touch the closed_seller/closed_buyer -> close_to_admin promotion
-- logic in code — her `closed`/`pending_deal` are plain statuses that never
-- auto-create a deal.
--
-- Defensive for the live Postgres operational DB: drop the old constraint
-- IF EXISTS (no-op if a prior run already changed it), then re-add the
-- widened constraint. Both statements are idempotent-friendly so re-running
-- the batch won't hard-crash the migration runner.

ALTER TABLE contacts
    DROP CONSTRAINT IF EXISTS contacts_pipeline_status_check;

ALTER TABLE contacts
    ADD CONSTRAINT contacts_pipeline_status_check
    CHECK (
        pipeline_status IS NULL
        OR pipeline_status IN (
            -- legacy 6 (AI-written)
            'new_lead', 'follow_up', 'ghosting', 'dead',
            'closed_seller', 'closed_buyer',
            -- Skyleigh's operator pipeline (8 new; new_lead reused above)
            'attempted', 'prospect', 'client', 'pending_deal',
            'closed', 'referred', 'realtor_contact', 'trash'
        )
    );
