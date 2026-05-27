-- Prevent duplicate chat_messages rows from shadow-write replays.
--
-- Background: chat_messages has no natural unique key — it relies on a
-- serial `id` PK, with the natural identity being (session_id, role,
-- timestamp, content). During the SessionDB shadow soak we discovered
-- that retry/backfill paths could insert the same row twice because
-- nothing in the DB enforced uniqueness on that signature.
--
-- This partial unique index is scoped to rows where `content IS NOT
-- NULL` so legitimate tool-call rows (which set content NULL and key
-- off tool_call_id) aren't constrained. It backs `ON CONFLICT DO
-- NOTHING` in the shadow + backfill paths going forward.
--
-- We index on md5(content) instead of content itself because chat
-- payloads frequently exceed the 8191-byte btree row limit (large
-- assistant turns with embedded tool results routinely hit 10–50 KB).
-- md5 collisions are astronomically unlikely for this dataset shape
-- and the index is only used for duplicate detection, not lookup.
--
-- The reconciler (`elevate_cli/data/_pg_drift_reconcile.py`) deduplicates
-- the existing table before this index is created; the migration runner
-- treats this file as additive and will fail loudly if dupes still
-- exist when it runs.

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_natural_key
    ON chat_messages (session_id, role, timestamp, md5(content))
    WHERE content IS NOT NULL;
