-- 0012_pack_onboarding.sql
-- Entitlement pack onboarding contracts. Each paid pack owns the data it needs
-- before its dashboards, skills, or automations are allowed to run unattended.

CREATE TABLE IF NOT EXISTS pack_onboarding_profiles (
    pack_id        TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    entitlement    TEXT NOT NULL,
    description    TEXT,
    status         TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    completed_at   TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pack_onboarding_items (
    pack_id        TEXT NOT NULL,
    key            TEXT NOT NULL,
    category       TEXT NOT NULL,
    label          TEXT NOT NULL,
    description    TEXT,
    required       INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    status         TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider       TEXT,
    env_keys_json  TEXT,
    value_json     TEXT,
    notes          TEXT,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (pack_id, key),
    FOREIGN KEY (pack_id) REFERENCES pack_onboarding_profiles(pack_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pack_onboarding_items_pack_ready
    ON pack_onboarding_items(pack_id, required, status, sort_order);
