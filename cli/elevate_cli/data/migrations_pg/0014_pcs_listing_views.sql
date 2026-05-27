-- Per-listing engagement for PCS (Xposure private client search) buyers.
--
-- Source of truth for "which homes is this buyer viewing, how many times,
-- when did they last open it." Powers the outreach flagger triggers:
--   * view-count spike on a single listing
--   * repeat views of same MLS#
--   * favorite added
--   * dormant -> returned
--
-- Snapshot semantics: each scrape OVERWRITES the row for
-- (contact_id, search_id, mls_id). We keep a snapshot_at so the activity
-- flagger can diff against the previous scrape (stored in JSONL).

CREATE TABLE IF NOT EXISTS pcs_listing_views (
    contact_id           TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    search_id            TEXT NOT NULL,
    mls_id               TEXT NOT NULL,
    address              TEXT,
    major_area           TEXT,
    minor_area           TEXT,
    list_price_cents     BIGINT,
    status               TEXT,
    beds                 INTEGER,
    baths                INTEGER,
    year_built           INTEGER,
    style                TEXT,
    property_type        TEXT,
    dom_days             INTEGER,
    view_count           INTEGER NOT NULL DEFAULT 0,
    last_viewed_at       DATE,
    view_state           TEXT,           -- 'new' | 'pc' | 'older' | 'viewed' | 'favorite' | 'removed'
    snapshot_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contact_id, search_id, mls_id)
);

CREATE INDEX IF NOT EXISTS idx_pcs_listing_views_contact
    ON pcs_listing_views(contact_id);
CREATE INDEX IF NOT EXISTS idx_pcs_listing_views_engaged
    ON pcs_listing_views(contact_id, last_viewed_at DESC)
    WHERE view_count > 0;
CREATE INDEX IF NOT EXISTS idx_pcs_listing_views_mls
    ON pcs_listing_views(mls_id)
    WHERE view_count > 0;

-- Summary counts on the parent pcs_buyers row -- so the brief can quote
-- "140 matches / 2 favorites / 36 removed" without aggregating views every
-- read.
ALTER TABLE pcs_buyers
    ADD COLUMN IF NOT EXISTS results_count       INTEGER,
    ADD COLUMN IF NOT EXISTS favorites_count     INTEGER,
    ADD COLUMN IF NOT EXISTS removed_count       INTEGER,
    ADD COLUMN IF NOT EXISTS queue_count         INTEGER,
    ADD COLUMN IF NOT EXISTS last_client_access  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS views_scraped_at    TIMESTAMPTZ;

-- Track the xposure-side contact ID so the views scraper can land on the
-- right buyer without doing a fresh name lookup every run.
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS xposure_contact_id  TEXT;

CREATE INDEX IF NOT EXISTS idx_contacts_xposure_contact_id
    ON contacts(xposure_contact_id)
    WHERE xposure_contact_id IS NOT NULL;
