-- 0015_lead_inquiry.sql
-- Buyer-intent payload for the /leads Open Thread drawer. One row per
-- contact: the saved-search criteria Lofty exposes as `LeadInquiry`
-- (embedded in GET /v1.0/leads/{leadId}, round-trips through PUT).
--
-- This is the answer to "what does this lead actually want." Without it,
-- the Open Thread shows messages without the goal — operators have to
-- click into Lofty to see price band and bedroom count. Mirroring the
-- payload locally puts those facts on the drawer alongside the thread.
--
-- One row per contact (contact_id PRIMARY KEY) — Lofty allows multiple
-- saved searches but for now we mirror the lead-level "active" one.
-- Multi-search support comes when we wire saved-searches as a separate
-- endpoint; the lead-level inquiry is what flows through the read API
-- today.
--
-- Pricing is stored as INTEGER (cents, like the rest of operational.db
-- where money lives — see deals.commission_cents). Bathrooms are TEXT
-- because Lofty returns "1.5", "2", "2+", etc. — keeping the original
-- string avoids parsing ambiguity. Property types and locations land in
-- JSON: both are unbounded arrays and the operational read path just
-- echoes them onto the drawer.
--
-- Source: docs/lofty-api-catalog.md §2.

CREATE TABLE IF NOT EXISTS lead_inquiries (
    contact_id           TEXT PRIMARY KEY,
    price_min            INTEGER,
    price_max            INTEGER,
    property_types_json  TEXT,  -- JSON array of strings: ["Single Family Home", "Condo", ...]
    bedrooms_min         INTEGER,
    bedrooms_max         INTEGER,
    bathrooms_min        TEXT,  -- Lofty returns "1.5" / "2+", keep as string
    bathrooms_max        TEXT,
    locations_json       TEXT,  -- JSON array of {city, stateCode} objects
    modify_by_agent      INTEGER NOT NULL DEFAULT 0
                            CHECK (modify_by_agent IN (0,1)),
    is_default           INTEGER NOT NULL DEFAULT 0
                            CHECK (is_default IN (0,1)),
    source_created_at    TEXT,  -- Lofty createTime
    source_updated_at    TEXT,  -- Lofty updateTime
    synced_at            TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

-- Open Thread reads by contact_id (the only access pattern). The PK
-- already covers that. The synced_at index lets the connector pick the
-- N least-recently-synced inquiries to refresh on each Lofty poll.
CREATE INDEX IF NOT EXISTS idx_lead_inquiries_synced_at
    ON lead_inquiries(synced_at);
