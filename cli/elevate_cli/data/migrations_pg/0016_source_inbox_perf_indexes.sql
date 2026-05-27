-- Speed up /api/source-inbox: it reads open conversations ordered by heat and
-- latest activity, then joins each row to its newest inbound/outbound event.

CREATE INDEX IF NOT EXISTS idx_conversations_open_heat_activity
    ON conversations(
        heat_score DESC,
        (COALESCE(last_inbound_at, last_outbound_at)) DESC
    )
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_events_conv_kind_ts_desc
    ON events(conversation_id, kind, ts DESC)
    WHERE kind IN ('inbound', 'outbound');
