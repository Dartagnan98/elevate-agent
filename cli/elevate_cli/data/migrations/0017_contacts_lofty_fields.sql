-- 0017_contacts_lofty_fields.sql
-- Extend `contacts` with Lofty fields the connector currently throws
-- away. Three buckets:
--
-- 1. Consent flags (cannot_text/call/email, unsubscription, hidden) —
--    the autopilot needs these to refuse to draft into a channel the
--    operator has marked off-limits. Without them, we'd ship a "send
--    SMS" CTA on someone who told us never to text.
--
-- 2. Buyer/seller qualification — Lofty exposes a dozen free-form
--    string fields ("Yes"/"No"/range codes) that capture buyingTimeFrame,
--    preQual status, has-house-to-sell, first-time-home-buyer, with
--    agent or not, mortgage status, sellingTimeFrame, with-listing-agent.
--    The Open Thread drawer wants these — they're the qualifying
--    questions the operator would otherwise have to re-ask.
--
-- 3. Lofty linkage — pond_id (shared lead pool), lead_types (Seller/
--    Buyer/Renter/Other as JSON int array), segments (replaces
--    deprecated `groups`), and lofty_lead_user_id (Lofty's user-side
--    handle for the lead, distinct from the lead record id).
--
-- All columns are nullable / default 0 — the migration is additive and
-- existing rows stay legal until the connector backfills.
--
-- Source: docs/lofty-api-catalog.md §1.

-- ─── Consent flags ─────────────────────────────────────────────────────
-- "1 = do not contact via this channel." Match Lofty's boolean semantics
-- (cannotText/cannotCall/cannotEmail/unsubscription/hiddenFlag).
ALTER TABLE contacts
    ADD COLUMN cannot_text INTEGER NOT NULL DEFAULT 0
        CHECK (cannot_text IN (0,1));

ALTER TABLE contacts
    ADD COLUMN cannot_call INTEGER NOT NULL DEFAULT 0
        CHECK (cannot_call IN (0,1));

ALTER TABLE contacts
    ADD COLUMN cannot_email INTEGER NOT NULL DEFAULT 0
        CHECK (cannot_email IN (0,1));

ALTER TABLE contacts
    ADD COLUMN unsubscribed INTEGER NOT NULL DEFAULT 0
        CHECK (unsubscribed IN (0,1));

ALTER TABLE contacts
    ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0
        CHECK (hidden IN (0,1));

-- ─── Qualification fields (free-form strings from Lofty) ──────────────
-- Lofty stores these as labels like "Yes" / "No" / "3-6 months" /
-- "Pre-qualified" / etc. Keep TEXT — coerce on display, not on write.
ALTER TABLE contacts
    ADD COLUMN buying_time_frame TEXT;

ALTER TABLE contacts
    ADD COLUMN selling_time_frame TEXT;

ALTER TABLE contacts
    ADD COLUMN pre_qual_status TEXT;          -- Lofty: preQual

ALTER TABLE contacts
    ADD COLUMN has_house_to_sell TEXT;        -- Lofty: houseToSell

ALTER TABLE contacts
    ADD COLUMN first_time_home_buyer TEXT;    -- Lofty: fthb

ALTER TABLE contacts
    ADD COLUMN with_buyer_agent TEXT;

ALTER TABLE contacts
    ADD COLUMN with_listing_agent TEXT;

ALTER TABLE contacts
    ADD COLUMN mortgage_status TEXT;          -- Lofty: mortgage

ALTER TABLE contacts
    ADD COLUMN buy_house_intent TEXT;         -- Lofty: buyHouse

ALTER TABLE contacts
    ADD COLUMN opportunity TEXT;              -- free-text opportunity field

ALTER TABLE contacts
    ADD COLUMN referred_by TEXT;

-- ─── Lofty linkage ─────────────────────────────────────────────────────
-- pond_id + pond_name: which shared lead pool this lead belongs to.
-- lead_types_json: JSON int array — 1=Seller, 2=Buyer, 3=Renter, -1=Other.
-- segments_json: JSON string array (modern replacement for deprecated `groups`).
-- lofty_lead_user_id: the user-side handle, distinct from the lead record id.
ALTER TABLE contacts
    ADD COLUMN pond_id TEXT;

ALTER TABLE contacts
    ADD COLUMN pond_name TEXT;

ALTER TABLE contacts
    ADD COLUMN lead_types_json TEXT;          -- JSON: [1,2] etc.

ALTER TABLE contacts
    ADD COLUMN segments_json TEXT;            -- JSON: ["Investor","Past Client"]

ALTER TABLE contacts
    ADD COLUMN lofty_lead_user_id TEXT;       -- int64 as text (JS precision)

-- ─── Indexes ───────────────────────────────────────────────────────────
-- Autopilot needs to skip do-not-contact people fast. Partial indexes
-- keep size proportional to flagged rows.
CREATE INDEX IF NOT EXISTS idx_contacts_dnc_text
    ON contacts(id) WHERE cannot_text = 1;

CREATE INDEX IF NOT EXISTS idx_contacts_dnc_call
    ON contacts(id) WHERE cannot_call = 1;

CREATE INDEX IF NOT EXISTS idx_contacts_dnc_email
    ON contacts(id) WHERE cannot_email = 1;

CREATE INDEX IF NOT EXISTS idx_contacts_unsubscribed
    ON contacts(id) WHERE unsubscribed = 1;

CREATE INDEX IF NOT EXISTS idx_contacts_pond
    ON contacts(pond_id) WHERE pond_id IS NOT NULL;
