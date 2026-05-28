-- Legacy SQLite mirror for Admin calendar events.
-- Current installs use migrations_pg; this keeps the archived SQLite path
-- schema-complete for local/dev fallback tools.

CREATE TABLE IF NOT EXISTS admin_calendar_events (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL
                        CHECK (source IN ('gcal','deal_date')),
    source_event_id TEXT NOT NULL,
    deal_id         TEXT REFERENCES deals(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    location        TEXT,
    start_at        TEXT NOT NULL,
    end_at          TEXT,
    kind            TEXT NOT NULL,
    synced_at       TEXT NOT NULL DEFAULT (datetime('now')),
    raw_json        TEXT,
    UNIQUE (source, source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_events_start
    ON admin_calendar_events(start_at);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_events_deal_start
    ON admin_calendar_events(deal_id, start_at);

CREATE INDEX IF NOT EXISTS idx_admin_calendar_events_kind_start
    ON admin_calendar_events(kind, start_at);
