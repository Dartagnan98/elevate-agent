-- Drop the accidental uniqueness constraint on chat-session titles.
--
-- migration 0005 created a partial-unique index on chat_sessions(title):
--     CREATE UNIQUE INDEX idx_chat_sessions_title_unique
--         ON chat_sessions(title) WHERE title IS NOT NULL;
-- but two sessions can legitimately share a title (e.g. repeated
-- "Hub Artifact Preview Guidance" chats). The constraint is the wrong shape:
-- titles are descriptive, not identifying. It also turned an ordinary session
-- upsert / shadow backfill (which conflicts on the id key, not the title key)
-- into a title-uniqueness IntegrityError, adding to the #4 write/log
-- amplification. Drop it.
--
-- Append-only + idempotent: IF EXISTS makes a re-run a no-op, and the runner's
-- sha256 ledger guards against any post-ship edit to this file.

DROP INDEX IF EXISTS idx_chat_sessions_title_unique;
