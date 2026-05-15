-- 0020_crm_agnostic_rename.sql
-- Rename Lofty-specific sync columns to CRM-agnostic names. The schema
-- I shipped in 0018 + 0019 hard-coded "lofty_" prefixes on sync state
-- (note_id, transaction_id, sync_state, synced_at, error, attempt_count,
-- etc.). That was wrong — the columns are CRM sync state in general;
-- they could just as well be populated by FUB, Sierra, Brivity, or
-- BoldTrail. Hard-coding a single provider in column names paints us
-- into a corner the moment a client migrates CRMs.
--
-- New shape: `crm_*` columns + a `crm_provider` discriminator (one of
-- 'lofty', 'followupboss', 'sierra', 'brivity', 'boldtrail', NULL=local).
-- The sync worker reads crm_provider to pick which API helper to call;
-- without it, every CRM would need its own dedicated column set.
--
-- SQLite ALTER TABLE RENAME COLUMN is native since 3.25 (2018) — we
-- don't need the rewrite-and-swap dance. CHECK constraints stay in
-- place across rename.
--
-- The earlier `lofty_contact_id` column on deals (shipped in 0003) is
-- intentionally left as-is — it's tech debt but renaming would risk
-- the existing /admin write paths that reference it. Future cleanup
-- can fold it into a generic identity once the rest stabilizes.

-- ─── notes ─────────────────────────────────────────────────────────────
ALTER TABLE notes RENAME COLUMN lofty_note_id        TO crm_remote_id;
ALTER TABLE notes RENAME COLUMN lofty_sync_state     TO crm_sync_state;
ALTER TABLE notes RENAME COLUMN lofty_synced_at      TO crm_synced_at;
ALTER TABLE notes RENAME COLUMN lofty_last_error     TO crm_last_error;
ALTER TABLE notes RENAME COLUMN lofty_attempt_count  TO crm_attempt_count;

ALTER TABLE notes ADD COLUMN crm_provider TEXT
    CHECK (crm_provider IS NULL OR crm_provider IN (
        'lofty', 'followupboss', 'sierra', 'brivity', 'boldtrail'
    ));

-- Old indexes referenced lofty_sync_state / lofty_note_id; SQLite
-- carries them across the rename, but the explicit drop+create lets
-- the names line up with the new schema so future operators don't get
-- confused reading the catalog.
DROP INDEX IF EXISTS idx_notes_pending_sync;
DROP INDEX IF EXISTS uniq_notes_lofty_id;

CREATE INDEX IF NOT EXISTS idx_notes_pending_sync
    ON notes(created_at)
    WHERE crm_sync_state = 'pending';

-- (crm_provider, crm_remote_id) is the natural key from the remote
-- side — two providers could in theory hand us the same int id.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_notes_crm_remote
    ON notes(crm_provider, crm_remote_id)
    WHERE crm_remote_id IS NOT NULL;

-- ─── deals ─────────────────────────────────────────────────────────────
ALTER TABLE deals RENAME COLUMN lofty_transaction_id     TO crm_transaction_id;
ALTER TABLE deals RENAME COLUMN lofty_lead_id            TO crm_lead_id;
ALTER TABLE deals RENAME COLUMN lofty_property_id        TO crm_property_id;
ALTER TABLE deals RENAME COLUMN lofty_transaction_status TO crm_transaction_status;
ALTER TABLE deals RENAME COLUMN lofty_transaction_type   TO crm_transaction_type;
ALTER TABLE deals RENAME COLUMN lofty_assigned_agent_id  TO crm_assigned_agent_id;
ALTER TABLE deals RENAME COLUMN lofty_synced_at          TO crm_synced_at;

ALTER TABLE deals ADD COLUMN crm_provider TEXT
    CHECK (crm_provider IS NULL OR crm_provider IN (
        'lofty', 'followupboss', 'sierra', 'brivity', 'boldtrail'
    ));

DROP INDEX IF EXISTS uniq_deals_lofty_transaction;
DROP INDEX IF EXISTS idx_deals_lofty_lead;
DROP INDEX IF EXISTS idx_deals_lofty_synced_at;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_deals_crm_transaction
    ON deals(crm_provider, crm_transaction_id)
    WHERE crm_transaction_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_deals_crm_lead
    ON deals(crm_provider, crm_lead_id)
    WHERE crm_lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_deals_crm_synced_at
    ON deals(crm_synced_at)
    WHERE crm_transaction_id IS NOT NULL;

-- ─── contacts ─────────────────────────────────────────────────────────
-- lofty_lead_user_id was the only Lofty-prefixed column on contacts.
-- Renaming to crm_user_id; the identities table already tracks which
-- CRM the user_id refers to via kind='lofty_id' / 'fub_id' / etc.
ALTER TABLE contacts RENAME COLUMN lofty_lead_user_id TO crm_user_id;
