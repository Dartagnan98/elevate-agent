-- 0021_apple_identity_kinds.sql
-- Extend identities.kind CHECK to allow Apple Messages + macOS AddressBook
-- linkage kinds. Today the constraint only allows 'apple_handle' — but the
-- contract in docs/database-contract.md is that EVERY external id this
-- contact has across EVERY source lives in identities. Without these kinds
-- there's no way to join a contact_id to the macOS AddressBook record or to
-- a specific chat.db thread.
--
-- New kinds:
--   'apple_addressbook_id' — ZABCDRECORD.ZUNIQUEID in AddressBook-v22.abcddb
--   'apple_chat_id'        — chat.ROWID in chat.db (one thread)
--
-- SQLite can't ALTER a CHECK constraint in place. The standard pattern is
-- rebuild-and-swap: create the new table with the extended check, copy rows
-- across, drop the old table, rename. PRAGMA foreign_keys must be off during
-- the swap so the contact_id FK doesn't fight us when we drop+recreate.
--
-- Idempotent: if the kinds are already in the schema (re-running this
-- migration after a partial failure), the new INSERT picks the same rows
-- and the indexes get rebuilt. The migration runner records the sha256 in
-- _schema_migrations so a clean re-run is a no-op.

PRAGMA foreign_keys = OFF;

-- ── Rebuild identities with the extended CHECK ─────────────────────────
CREATE TABLE identities_new (
    id          TEXT PRIMARY KEY,
    contact_id  TEXT NOT NULL,
    kind        TEXT NOT NULL
                  CHECK (kind IN (
                    'email','phone',
                    'instagram_id','instagram_handle',
                    'facebook_id','telegram_id',
                    'lofty_id','fub_id','sierra_id','brivity_id','boldtrail_id',
                    'apple_handle','apple_addressbook_id','apple_chat_id',
                    'wa_id'
                  )),
    value       TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    verified    INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
    created_at  TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

INSERT INTO identities_new
    (id, contact_id, kind, value, source_id, verified, created_at)
SELECT
    id, contact_id, kind, value, source_id, verified, created_at
FROM identities;

DROP TABLE identities;
ALTER TABLE identities_new RENAME TO identities;

-- ── Rebuild indexes (DROP IF EXISTS first in case the old table's
--    auto-cleanup missed any) ──────────────────────────────────────────
DROP INDEX IF EXISTS uniq_identities_kind_value;
DROP INDEX IF EXISTS idx_identities_contact;

CREATE UNIQUE INDEX uniq_identities_kind_value
    ON identities(kind, value);

CREATE INDEX idx_identities_contact
    ON identities(contact_id);

-- AddressBook lookups are read-heavy on the value side too (incoming chat.db
-- handle → contact). The unique (kind, value) index already covers
-- equality lookups; no additional index needed.

PRAGMA foreign_keys = ON;
