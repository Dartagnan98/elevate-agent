-- 0013_contact_flags.sql
-- Make `contacts` the source of truth for /leads widgets. AI maintains these
-- flag columns; the dashboard queries them directly instead of replaying JSONL.
--
-- One row per person, flagged by lane:
--   heat_label              hot|warm|watch|normal  (Hot Leads widget)
--   needs_follow_up         0|1                    (Follow-ups widget)
--   buyer_search_active     0|1                    (Buyer Searches widget)
--   listing_active          0|1                    (Active Listings on Today)
--   ai_last_reviewed_at     ISO ts                 (when review_contact last ran)
--
-- When a contact converts, set contacts.stage = 'closed'. That action also
-- promotes the contact into Admin via promote_profile_to_admin_deal(side=...).
-- The 'closed' stage value is permitted because contacts.stage has no CHECK
-- constraint (see 0001_init.sql).

ALTER TABLE contacts
    ADD COLUMN heat_label TEXT NOT NULL DEFAULT 'normal'
        CHECK (heat_label IN ('hot','warm','watch','normal'));

ALTER TABLE contacts
    ADD COLUMN heat_score INTEGER NOT NULL DEFAULT 0
        CHECK (heat_score BETWEEN 0 AND 100);

ALTER TABLE contacts
    ADD COLUMN heat_reason TEXT;

ALTER TABLE contacts
    ADD COLUMN needs_follow_up INTEGER NOT NULL DEFAULT 0
        CHECK (needs_follow_up IN (0,1));

ALTER TABLE contacts
    ADD COLUMN next_follow_up_at TEXT;

ALTER TABLE contacts
    ADD COLUMN buyer_search_active INTEGER NOT NULL DEFAULT 0
        CHECK (buyer_search_active IN (0,1));

ALTER TABLE contacts
    ADD COLUMN listing_active INTEGER NOT NULL DEFAULT 0
        CHECK (listing_active IN (0,1));

ALTER TABLE contacts
    ADD COLUMN ai_last_reviewed_at TEXT;

ALTER TABLE contacts
    ADD COLUMN ai_review_run_id TEXT;

-- Indexes for the four /leads widgets. Each widget is a filtered scan that
-- should stay in the milliseconds at 1k-100k contacts. Partial indexes keep
-- size proportional to flagged rows, not the full pool.
CREATE INDEX IF NOT EXISTS idx_contacts_heat_label
    ON contacts(heat_label, heat_score DESC, last_activity_at DESC)
    WHERE heat_label IN ('hot','warm');

CREATE INDEX IF NOT EXISTS idx_contacts_needs_follow_up
    ON contacts(next_follow_up_at)
    WHERE needs_follow_up = 1;

CREATE INDEX IF NOT EXISTS idx_contacts_buyer_search_active
    ON contacts(buyer_search_active, last_activity_at DESC)
    WHERE buyer_search_active = 1;

CREATE INDEX IF NOT EXISTS idx_contacts_listing_active
    ON contacts(listing_active, last_activity_at DESC)
    WHERE listing_active = 1;

-- Closed contacts → Admin lookup. type filters buyer vs listing side.
CREATE INDEX IF NOT EXISTS idx_contacts_closed_by_type
    ON contacts(type, last_activity_at DESC)
    WHERE stage = 'closed';
