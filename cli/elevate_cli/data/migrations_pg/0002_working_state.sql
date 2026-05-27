-- 0002_working_state.sql
--
-- Per-entity "where we left off" journal for the agent. Extends the
-- existing `notes` table rather than introducing a parallel table so
-- the agent journal lives alongside human-facing notes and the CRM
-- sync infrastructure (crm_provider / crm_sync_state) is reused.
--
-- Design (decided 2026-05-24):
--
-- * A working-state entry is a `notes` row with `is_working_state=1`.
-- * Each entry targets exactly ONE entity, identified by
--   (entity_kind, entity_id):
--     - 'contact' → entity_id is contact_id (mirrors contact_id column)
--     - 'deal'    → entity_id is deal_id    (mirrors deal_id    column)
--   (Leads are contacts with lead_signals, so entity_kind='contact' covers
--    leads too. We don't need a separate 'lead' kind.)
-- * Working-state rows are NEVER pushed to CRM (push_to_crm=False).
-- * Latest active entry per entity is the one with
--   is_working_state=1 AND superseded_by_id IS NULL AND deleted=0.
--   `update` operations supersede the previous row by stamping its
--   superseded_by_id and inserting a new row — so the full history is
--   preserved.
-- * `state_status` drives the session-start digest:
--     in_progress       — actively being worked
--     pending_external  — waiting on a third party (buyer agent, lawyer)
--     blocked           — waiting on user or external system, can't proceed
--     resolved          — done; excluded from active list
-- * `next_action` / `blocked_on` are short, human-readable, optional.

-- ─── Loosen contact_id NOT NULL so deal-scoped entries don't need a
--     placeholder contact ──────────────────────────────────────────────
ALTER TABLE notes ALTER COLUMN contact_id DROP NOT NULL;

-- ─── Working-state columns ──────────────────────────────────────────
ALTER TABLE notes ADD COLUMN entity_kind TEXT NOT NULL DEFAULT 'contact'
    CHECK (entity_kind IN ('contact', 'deal'));
ALTER TABLE notes ADD COLUMN deal_id TEXT;
ALTER TABLE notes ADD COLUMN is_working_state INTEGER NOT NULL DEFAULT 0
    CHECK (is_working_state IN (0, 1));
ALTER TABLE notes ADD COLUMN state_status TEXT
    CHECK (state_status IS NULL OR state_status IN
        ('in_progress', 'pending_external', 'blocked', 'resolved'));
ALTER TABLE notes ADD COLUMN next_action TEXT;
ALTER TABLE notes ADD COLUMN blocked_on TEXT;
ALTER TABLE notes ADD COLUMN superseded_by_id TEXT;
ALTER TABLE notes ADD COLUMN agent_kind TEXT;

-- ─── Integrity: every note must target at least one entity ─────────
ALTER TABLE notes ADD CONSTRAINT notes_targets_entity_chk CHECK (
    contact_id IS NOT NULL OR deal_id IS NOT NULL
);

-- ─── Integrity: working-state rows must carry the kind+id matching
--     either contact_id or deal_id ─────────────────────────────────
ALTER TABLE notes ADD CONSTRAINT notes_working_state_shape_chk CHECK (
    is_working_state = 0
    OR (entity_kind = 'contact' AND contact_id IS NOT NULL)
    OR (entity_kind = 'deal'    AND deal_id    IS NOT NULL)
);

-- ─── Integrity: resolved status must come with a body (the closing
--     note), and a non-resolved working-state row must have a status.
ALTER TABLE notes ADD CONSTRAINT notes_working_state_status_chk CHECK (
    is_working_state = 0 OR state_status IS NOT NULL
);

-- ─── Active-working-state lookup (per entity) ───────────────────────
CREATE INDEX idx_notes_working_contact_active
    ON notes (contact_id, updated_at DESC)
    WHERE is_working_state = 1
      AND superseded_by_id IS NULL
      AND deleted = 0
      AND entity_kind = 'contact';

CREATE INDEX idx_notes_working_deal_active
    ON notes (deal_id, updated_at DESC)
    WHERE is_working_state = 1
      AND superseded_by_id IS NULL
      AND deleted = 0
      AND entity_kind = 'deal';

-- ─── Session-start digest: every non-resolved active working state ──
CREATE INDEX idx_notes_working_status_active
    ON notes (state_status, updated_at DESC)
    WHERE is_working_state = 1
      AND superseded_by_id IS NULL
      AND deleted = 0
      AND state_status != 'resolved';
