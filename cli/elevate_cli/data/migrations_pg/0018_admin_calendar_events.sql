-- Persist external calendar events for the Admin board.
--
-- `deal_events` already powers the Admin Hub timeline/audit trail, so Google
-- Calendar rows live in a separate table and are merged with deal-date events
-- at read time.

CREATE TABLE IF NOT EXISTS admin_calendar_events (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL
                        CHECK (source IN ('gcal','deal_date')),
    source_event_id TEXT NOT NULL,
    deal_id         TEXT REFERENCES deals(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    location        TEXT,
    start_at        TIMESTAMPTZ NOT NULL,
    end_at          TIMESTAMPTZ,
    kind            TEXT NOT NULL,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json        TEXT,
    UNIQUE (source, source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_events_start
    ON admin_calendar_events(start_at);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_events_deal_start
    ON admin_calendar_events(deal_id, start_at);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_events_kind_start
    ON admin_calendar_events(kind, start_at);
