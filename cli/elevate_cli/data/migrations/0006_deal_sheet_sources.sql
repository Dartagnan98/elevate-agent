-- 0006_deal_sheet_sources.sql
-- Track external sheet rows that seed/update Admin Hub deal files.

ALTER TABLE deals ADD COLUMN source_key TEXT;
ALTER TABLE deals ADD COLUMN source_row_id TEXT;
ALTER TABLE deals ADD COLUMN source_label TEXT;
ALTER TABLE deals ADD COLUMN source_synced_at TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_deals_source_key
    ON deals(source_key)
    WHERE source_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_deals_source_row
    ON deals(source_label, source_row_id)
    WHERE source_row_id IS NOT NULL;
