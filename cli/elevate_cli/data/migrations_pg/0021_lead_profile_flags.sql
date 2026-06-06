-- UI-level flags for /leads source-inbox profiles. Profile IDs are generated
-- by source_connectors._profiles_from_threads: email:<value>, phone:<value>,
-- or thread:<source:thread> when no verifier/contact exists yet.
-- TEXT/INTEGER only so the compatibility layer stays simple.

CREATE TABLE IF NOT EXISTS lead_profile_flags (
    profile_id   TEXT PRIMARY KEY,
    contact_id   TEXT,
    favorite     INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    favorited_at TEXT,
    favorited_by TEXT,
    updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_lead_profile_flags_favorite
    ON lead_profile_flags(favorite, favorited_at DESC)
    WHERE favorite = 1;

CREATE INDEX IF NOT EXISTS idx_lead_profile_flags_contact
    ON lead_profile_flags(contact_id)
    WHERE contact_id IS NOT NULL;
