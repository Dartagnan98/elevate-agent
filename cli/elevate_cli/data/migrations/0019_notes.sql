-- 0019_notes.sql
-- Notes the operator (or AI) writes about a contact. One row per note,
-- keyed to contact_id. Distinct from the existing `events` table:
--
--   * `events` is the activity timeline — inbound/outbound messages,
--     calls, system lifecycle changes. Append-only, immutable. The
--     read side renders it as the conversation log.
--
--   * `notes` is annotations — "spoke with husband, decision by Friday",
--     "AI marked ghosting: 3 outbounds no reply in 31d". Mutable
--     (operator can edit), pin-able, deletable.
--
-- Why a separate table: notes round-trip through Lofty's CRUD endpoints
-- (POST /v1.0/notes, PUT/DELETE /v1.0/notes/{noteId}). Treating them as
-- events would force every edit to write a new event-hash row and we'd
-- lose the ability to track "this is the SAME note I posted yesterday,
-- the operator just changed two words."
--
-- ── Authorship model ──────────────────────────────────────────────────
-- author_kind = 'ai'       → cron job wrote it (review_contact, draft
--                            monitor, theta-wave, close-to-admin).
--                            author_name carries the cron's identifier.
-- author_kind = 'operator' → human-typed in the Elevate UI.
-- author_kind = 'system'   → catch-all for migrations, backfills,
--                            recoveries — not user-visible authorship.
--
-- The Lofty content gets prefixed with [AI/{author_name}] at push time
-- so the operator can scan Lofty's note feed and see who wrote what.
--
-- ── Lofty sync state machine ─────────────────────────────────────────
--   pending → synced     (POST succeeded, lofty_note_id captured)
--   pending → failed     (4xx — bad payload, missing leadId, etc.; don't retry)
--   synced  → deleted    (pull side saw deleteFlag=true on lofty side)
--   pending → pending    (5xx/timeout, backoff and retry)
--
-- Notes from contacts WITHOUT a lofty_id identity stay local-only:
-- sync state never leaves NULL → the push job skips them.
--
-- ── Volume guard ──────────────────────────────────────────────────────
-- A per-contact daily cap lives at the application layer (write_note
-- helper checks last AI note ts on this contact before inserting).
-- Schema doesn't enforce it — keeping the rule in code lets us tune
-- caps per cron job without a migration.

CREATE TABLE IF NOT EXISTS notes (
    id                  TEXT PRIMARY KEY,
    contact_id          TEXT NOT NULL,
    body                TEXT NOT NULL,
    author_kind         TEXT NOT NULL
                            CHECK (author_kind IN ('ai','operator','system')),
    author_name         TEXT NOT NULL,         -- "review_contact" | "agent" | etc.
    source_event_id     TEXT,                  -- events.id if note was triggered by an event
    pinned              INTEGER NOT NULL DEFAULT 0
                            CHECK (pinned IN (0,1)),
    deleted             INTEGER NOT NULL DEFAULT 0
                            CHECK (deleted IN (0,1)),

    -- Lofty mirror state
    lofty_note_id       TEXT,                  -- int64 as text after successful POST
    lofty_sync_state    TEXT
                            CHECK (lofty_sync_state IS NULL OR
                                   lofty_sync_state IN ('pending','synced','failed','deleted')),
    lofty_synced_at     TEXT,
    lofty_last_error    TEXT,
    lofty_attempt_count INTEGER NOT NULL DEFAULT 0,

    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
    FOREIGN KEY(source_event_id) REFERENCES events(id) ON DELETE SET NULL
);

-- Drawer renders notes for one contact in reverse chronological order.
-- Filtering deleted=0 keeps soft-deletes out of the default view.
CREATE INDEX IF NOT EXISTS idx_notes_contact_created
    ON notes(contact_id, created_at DESC)
    WHERE deleted = 0;

-- Push worker picks pending notes oldest-first.
CREATE INDEX IF NOT EXISTS idx_notes_pending_sync
    ON notes(created_at)
    WHERE lofty_sync_state = 'pending';

-- Pull side: when we see a lofty_note in lead-events.jsonl that
-- references an existing lofty_note_id, look up by it to mark synced
-- → deleted on remote delete.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_notes_lofty_id
    ON notes(lofty_note_id)
    WHERE lofty_note_id IS NOT NULL;

-- Daily-cap query: "has this contact had an AI note from THIS cron
-- in the last 24h?" — covered by (contact_id, author_kind, author_name,
-- created_at).
CREATE INDEX IF NOT EXISTS idx_notes_contact_author_recent
    ON notes(contact_id, author_kind, author_name, created_at DESC);
