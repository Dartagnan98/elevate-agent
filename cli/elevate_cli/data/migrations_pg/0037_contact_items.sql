-- 0037_contact_items.sql
-- Per-contact Tasks / Appointments / Family storage for the CRM contact card.
--
-- Background: the redesigned single-contact card (crm-contact-card.tsx) renders
-- three right-rail sections — Tasks, Appointments, and Family — that were all
-- fixed read-only empty states with no add control, because there was no
-- per-contact storage for any of them. This one generic table backs the card's
-- new "+ add" feature for all three sections. The card's admin_contact_card.py
-- endpoints (GET/POST/PATCH/DELETE .../items) read and write it.
--
-- One row per item. `kind` discriminates the three sections:
--   'task'        -> checklist item (done toggle + optional due date in when_at)
--   'appointment' -> scheduled meeting (when_at = ISO datetime, subtitle = place)
--   'family'      -> household member (title = name, subtitle = relationship)
--
-- TEXT/INTEGER only so the same DDL is valid on both Postgres (live operational
-- DB) and SQLite (operational.db) with identical semantics. CREATE IF NOT EXISTS
-- so the migration is idempotent and matches the runtime _ensure guard in the
-- router (the endpoints work even before this migration runs).

CREATE TABLE IF NOT EXISTS contact_items (
    id          TEXT PRIMARY KEY,
    contact_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    title       TEXT,
    subtitle    TEXT,
    when_at     TEXT,
    done        INTEGER DEFAULT 0,
    created_at  TEXT,
    updated_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_contact_items_contact_kind
    ON contact_items (contact_id, kind);
