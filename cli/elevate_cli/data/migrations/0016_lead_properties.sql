-- 0016_lead_properties.sql
-- Properties a lead is attached to: viewed, favorited, inquired about,
-- or (for sellers) the home they're selling. Mirrors Lofty's
-- `leadPropertyList` embedded in GET /v1.0/leads/{leadId}.
--
-- This is the "what listings does this lead care about" panel for the
-- Open Thread drawer. Combined with lead_inquiries (the saved-search
-- criteria), it lets the operator see at a glance: this person wants
-- $400-600k condos in Saskatoon, has favorited 3 of them, and viewed 8.
--
-- One row per (contact, listing) pair. `source_record_id` is Lofty's
-- own lead-property record id (int64, stored as TEXT for JS precision).
-- `listing_id` is the canonical MLS link when present; `auto_listing_id`
-- is Lofty's internal listing record (set when the MLS one is missing,
-- e.g. for custom listings or off-MLS interest).
--
-- `label` is free-form: "Favorited", "Viewing", "Submitted Inquiry",
-- plus operator-defined labels. Keep it TEXT to match Lofty's open shape.
--
-- Address fields stay denormalized — the drawer renders them inline and
-- the connector writes whatever Lofty hands back. If two listings share
-- the same property we accept the duplication; deduping by listing_id
-- is a follow-up once we have the listings table (migration 0021).
--
-- Source: docs/lofty-api-catalog.md §3.

CREATE TABLE IF NOT EXISTS lead_properties (
    id                   TEXT PRIMARY KEY,
    contact_id           TEXT NOT NULL,
    source_record_id     TEXT,  -- Lofty's own lead-property id (int64 as text)
    listing_id           TEXT,  -- MLS-side listing id
    auto_listing_id      TEXT,  -- Lofty internal listing id
    street_address       TEXT,
    city                 TEXT,
    state                TEXT,
    zip_code             TEXT,
    county               TEXT,
    property_type        TEXT,
    bedrooms             INTEGER,
    bathrooms            REAL,
    square_feet          INTEGER,
    lot_size_acres       REAL,
    parking_space        INTEGER,
    floors               INTEGER,
    price                INTEGER,      -- whole dollars, matches Lofty payload
    price_min            INTEGER,
    price_max            INTEGER,
    label                TEXT,         -- "Favorited" | "Viewing" | "Submitted Inquiry" | ...
    label_type           TEXT,
    label_list_json      TEXT,         -- JSON array when Lofty returns multiple labels
    note                 TEXT,
    listing_status       TEXT,
    picture_url          TEXT,
    site_listing_url     TEXT,
    is_mailing_address   INTEGER NOT NULL DEFAULT 0
                            CHECK (is_mailing_address IN (0,1)),
    source_created_at    TEXT,
    source_updated_at    TEXT,
    synced_at            TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

-- Open Thread fetches all properties for one contact (the only access
-- pattern from the UI). The partial-on-label index lets the autopilot
-- find "leads who favorited something in the last N days" cheaply.
CREATE INDEX IF NOT EXISTS idx_lead_properties_contact
    ON lead_properties(contact_id, label, source_updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_lead_properties_listing
    ON lead_properties(listing_id)
    WHERE listing_id IS NOT NULL;

-- Idempotent re-imports: (contact, source_record_id) is the natural key
-- from Lofty. NULL source_record_id is allowed for legacy/manual rows;
-- those won't dedupe on re-import but that's intentional (we'd need a
-- separate path for hand-entered properties anyway).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_lead_properties_source
    ON lead_properties(contact_id, source_record_id)
    WHERE source_record_id IS NOT NULL;
