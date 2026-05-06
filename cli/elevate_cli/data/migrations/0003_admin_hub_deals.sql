-- 0003_admin_hub_deals.sql
-- Admin Hub deal workflow state for $ELEVATE_HOME/data/operational.db.

CREATE TABLE IF NOT EXISTS deals (
    id                       TEXT PRIMARY KEY,
    title                    TEXT NOT NULL,
    side                     TEXT NOT NULL
                                 CHECK (side IN ('listing','buyer')),
    current_stage            INTEGER NOT NULL DEFAULT 0
                                 CHECK (current_stage BETWEEN 0 AND 9),
    status                   TEXT NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active','closed','archived')),
    province                 TEXT NOT NULL DEFAULT 'BC',
    primary_contact_id       TEXT,
    lofty_contact_id         TEXT,
    listing_address          TEXT,

    -- Named enum/toggle fields from the plan. Keep enum values as TEXT in
    -- 0003 because the plan names fields but not allowed enum values.
    signing_authority        TEXT,
    fintrac_form_type        TEXT,
    listing_track            TEXT,
    property_subtype         TEXT,
    estate_status            TEXT,
    transaction_type         TEXT,
    listing_type             TEXT,

    pep                      INTEGER CHECK (pep IN (0,1)),
    tenanted                 INTEGER CHECK (tenanted IN (0,1)),
    poa_signing              INTEGER CHECK (poa_signing IN (0,1)),
    corporate                INTEGER CHECK (corporate IN (0,1)),
    has_suite                INTEGER CHECK (has_suite IN (0,1)),
    multiple_offers          INTEGER CHECK (multiple_offers IN (0,1)),
    family_member            INTEGER CHECK (family_member IN (0,1)),
    dual_rep                 INTEGER CHECK (dual_rep IN (0,1)),
    unrepresented_other_side INTEGER CHECK (unrepresented_other_side IN (0,1)),
    lockbox                  INTEGER CHECK (lockbox IN (0,1)),
    delayed_offer            INTEGER CHECK (delayed_offer IN (0,1)),
    sale_of_buyers_property  INTEGER CHECK (sale_of_buyers_property IN (0,1)),

    extra_toggles_json       TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    stage_entered_at         TEXT NOT NULL,
    closed_at                TEXT,

    FOREIGN KEY(primary_contact_id) REFERENCES contacts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_side_stage_status
    ON deals(side, current_stage, status);
CREATE INDEX IF NOT EXISTS idx_deals_contact
    ON deals(primary_contact_id) WHERE primary_contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deals_updated_at
    ON deals(updated_at);

CREATE TABLE IF NOT EXISTS deal_events (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT NOT NULL,
    kind            TEXT NOT NULL
                        CHECK (kind IN ('created','stage_transition','toggle_change')),
    actor           TEXT NOT NULL,
    from_stage      INTEGER CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9),
    to_stage        INTEGER CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9),
    field_name      TEXT,
    old_value_json  TEXT,
    new_value_json  TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL,

    FOREIGN KEY(deal_id) REFERENCES deals(id) ON DELETE CASCADE,
    CHECK (kind != 'stage_transition' OR to_stage IS NOT NULL),
    CHECK (kind != 'toggle_change' OR field_name IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_deal_events_deal_created
    ON deal_events(deal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_events_kind_created
    ON deal_events(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_deal_events_field_created
    ON deal_events(field_name, created_at)
    WHERE field_name IS NOT NULL;
