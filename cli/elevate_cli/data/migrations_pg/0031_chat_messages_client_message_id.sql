-- 0031_chat_messages_client_message_id.sql
--
-- Stable per-message identity for transcript reconciliation.
--
-- `client_message_id` is Elevate's OWN id for a chat message (uuid hex),
-- minted at SessionDB.append_message time and carried on the gateway wire as
-- `message_id` (message.start/delta/complete events, session.resume
-- transcripts, REST /api/sessions/{id}/messages). It lets the dashboard
-- reconcile live-streamed messages with hydrated history by identity instead
-- of content-fingerprint matching — the root cause of the "rendered reply
-- vanishes/shrinks" bug class (see plans/chat-transcript-refactor.md).
--
-- Distinct from `platform_message_id`, which is the EXTERNAL messaging
-- platform's id (telegram update_id, yuanbao msg_id, ...).
--
-- Pre-existing rows keep NULL; readers expose a deterministic
-- `legacy.{session_id}.{ordinal}` fallback so old transcripts still hydrate
-- with stable (weak) identity. No index: nothing queries by this column
-- server-side; it is carried, not searched.

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS client_message_id TEXT;
