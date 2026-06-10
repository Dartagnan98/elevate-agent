-- 0030_contacts_lofty_lead_user_id.sql
--
-- Add the missing `lofty_lead_user_id` column to `contacts`.
--
-- ROOT CAUSE: `lofty_lead_user_id` is in the contacts write-through whitelist
-- (`elevate_cli/data/contacts.py` _ENRICHMENT_COLUMNS) and the Lofty connector
-- maps `leadUserId` -> `lofty_lead_user_id`, but NO migration ever created the
-- column. 0012_lofty_lead_metadata.sql added the rest of the Lofty enrichment
-- columns (lead_source, crm_stage, crm_user_id, …) and this one was added to
-- the code later without a matching migration. Result: every contacts INSERT
-- that lists the full enrichment column set fails on Postgres with
--   column "lofty_lead_user_id" of relation "contacts" does not exist
-- which (under the single-transaction backfill) aborted the whole sync and
-- dropped the bulk of Lofty contacts + all lead/lifecycle events.
--
-- TEXT to match the other Lofty id columns. IF NOT EXISTS so it's idempotent
-- and safe on any install that somehow already has it.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS lofty_lead_user_id TEXT;
