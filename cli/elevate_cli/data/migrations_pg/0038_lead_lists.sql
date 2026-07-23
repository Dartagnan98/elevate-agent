-- Named lead lists (Lofty-style smart lists): account-level list config in
-- crm_settings, per-contact membership as a JSON array of list keys.

ALTER TABLE crm_settings ADD COLUMN IF NOT EXISTS lead_lists_json TEXT;

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lists_json TEXT;
