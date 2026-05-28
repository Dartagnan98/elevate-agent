-- Embedded pgserver builds used by local Elevate installs may not ship the
-- Snowball dictionary file required by the "english" text-search config.
-- When chat_messages.content_tsv uses that config, every INSERT into
-- chat_messages can fail with:
--
--   could not access file "$libdir/dict_snowball"
--
-- The built-in "simple" config is enough for dashboard/session search and
-- keeps transcript writes working on stripped-down local Postgres bundles.

DROP INDEX IF EXISTS idx_chat_messages_content_tsv;

ALTER TABLE chat_messages
    DROP COLUMN IF EXISTS content_tsv;

ALTER TABLE chat_messages
    ADD COLUMN content_tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple',
            left(coalesce(content, ''), 100000) || ' ' ||
            coalesce(tool_name, '') || ' ' ||
            left(coalesce(tool_calls, ''), 100000)
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_chat_messages_content_tsv
    ON chat_messages USING GIN (content_tsv);
