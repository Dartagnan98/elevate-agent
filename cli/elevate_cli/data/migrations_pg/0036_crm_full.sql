-- Full-CRM additions (design/crm-redesign follow-up): custom fields per
-- contact and account-level custom column configuration for the /leads list.

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS custom_fields_json TEXT;

CREATE TABLE IF NOT EXISTS crm_settings (
    id                  TEXT PRIMARY KEY DEFAULT 'default',
    custom_columns_json TEXT,
    updated_at          TEXT
);
