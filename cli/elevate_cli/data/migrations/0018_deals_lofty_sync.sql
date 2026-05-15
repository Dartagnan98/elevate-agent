-- 0018_deals_lofty_sync.sql
-- Sync columns so the local `deals` table can mirror Lofty's
-- `TransactionV2Item` shape. The local rows stay the source of truth
-- for operator-driven workflow state (current_stage, toggles, FINTRAC
-- bits), but the financial/timeline fields land in dedicated columns
-- so the connector can reconcile without re-interpreting commission
-- math from `commission_notes`.
--
-- Existing columns we DO NOT duplicate (already present from 0003/0005):
--   * commission_pct REAL          — Lofty's commissionRate
--   * offer_date TEXT              — Lofty's offerDate
--   * completion_date TEXT         — workflow close-out, kept distinct
--                                     from Lofty's expectedCloseDate/closeDate
--   * list_price / offer_price     — local sources of truth
--   * lofty_contact_id             — already on 0003 (lead-side mapping)
--
-- New columns mirror what Lofty hands back. Money fields use REAL to
-- match the rest of `deals` (commission_pct, list_price, etc.); we'd
-- migrate to integer cents in a future cleanup pass rather than mix
-- styles here.
--
-- Source: docs/lofty-api-catalog.md §14.

-- ─── Lofty linkage ─────────────────────────────────────────────────────
ALTER TABLE deals ADD COLUMN lofty_transaction_id TEXT;
ALTER TABLE deals ADD COLUMN lofty_lead_id TEXT;
ALTER TABLE deals ADD COLUMN lofty_property_id TEXT;
ALTER TABLE deals ADD COLUMN lofty_transaction_status TEXT;
ALTER TABLE deals ADD COLUMN lofty_transaction_type TEXT;   -- Purchase | Listing | Lease | Other
ALTER TABLE deals ADD COLUMN lofty_assigned_agent_id TEXT;  -- int64 as text
ALTER TABLE deals ADD COLUMN lofty_synced_at TEXT;

-- ─── Money ─────────────────────────────────────────────────────────────
ALTER TABLE deals ADD COLUMN home_price REAL;
ALTER TABLE deals ADD COLUMN gci REAL;
ALTER TABLE deals ADD COLUMN team_revenue REAL;
ALTER TABLE deals ADD COLUMN agent_revenue REAL;

-- ─── Lofty timeline (separate from our workflow columns in 0005) ──────
-- expected_close_date is Lofty's projection; the local completion_date
-- (from 0005) captures the actual workflow close-out and may diverge
-- when Lofty's value is stale.
ALTER TABLE deals ADD COLUMN expected_close_date TEXT;
ALTER TABLE deals ADD COLUMN appointment_date TEXT;
ALTER TABLE deals ADD COLUMN agreement_signed_date TEXT;
ALTER TABLE deals ADD COLUMN contract_date TEXT;
ALTER TABLE deals ADD COLUMN appraisal_date TEXT;
ALTER TABLE deals ADD COLUMN home_inspection_date TEXT;
ALTER TABLE deals ADD COLUMN escrow_date TEXT;
ALTER TABLE deals ADD COLUMN expiration_date TEXT;

-- ─── Indexes ───────────────────────────────────────────────────────────
-- Connector reconcile path: "find deal by lofty_transaction_id." Unique
-- because each Lofty transaction maps to at most one local deal.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_deals_lofty_transaction
    ON deals(lofty_transaction_id)
    WHERE lofty_transaction_id IS NOT NULL;

-- Lookup by lead/contact when the connector pulls per-lead transactions.
CREATE INDEX IF NOT EXISTS idx_deals_lofty_lead
    ON deals(lofty_lead_id)
    WHERE lofty_lead_id IS NOT NULL;

-- Connector picks oldest-synced rows to refresh first.
CREATE INDEX IF NOT EXISTS idx_deals_lofty_synced_at
    ON deals(lofty_synced_at)
    WHERE lofty_transaction_id IS NOT NULL;
