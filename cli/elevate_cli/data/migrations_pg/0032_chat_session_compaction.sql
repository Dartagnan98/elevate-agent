-- 0032_chat_session_compaction.sql
--
-- Payload-time compaction metadata for the compaction redesign
-- (docs/compaction-redesign.md). Compaction no longer rewrites the transcript
-- or rotates the session id; instead it stores two fields on the session row:
--
--   compaction_summary  — the synthetic handoff summary text, injected ONLY at
--                         API-payload build time, never written as a message row
--                         and never rendered in the transcript.
--   compaction_cursor   — number of leading messages the payload builder skips
--                         (everything before the cursor is represented by the
--                         summary). 0 = no compaction.
--
-- A row with compaction_cursor = 0 and NULL compaction_summary is the
-- legacy / no-compaction sentinel: such sessions still resolve via the old
-- rotation tip-walk read path. New-style compactions never rotate.

ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS compaction_summary TEXT;

ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS compaction_cursor INTEGER DEFAULT 0;
